# -*- coding: utf-8 -*-
"""
Baja los datos del monitor económico y genera site/data/datos.json.

Fuentes (todas gratuitas):
  - API del INDEC (requiere token gratuito en la variable de entorno INDEC_TOKEN)
  - Archivo de series de salarios del INDEC (sin token)
  - ArgentinaDatos: dólar blue, oficial y riesgo país (sin token)
  - FMI World Economic Outlook, API DataMapper (sin token)
  - Banco Mundial (sin token)

Uso local:   set INDEC_TOKEN=...   (Windows)  /  export INDEC_TOKEN=...  (Linux/Mac)
             python scripts/actualizar.py
Solo usa la biblioteca estándar de Python (no hace falta instalar nada).
"""
import csv, io, json, os, sys, time, urllib.parse, urllib.request
from datetime import date, datetime, timezone

ANIO_INICIO = 2017
HOY = date.today()
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SALIDA = os.path.join(RAIZ, "site", "data", "datos.json")
TOKEN = os.environ.get("INDEC_TOKEN", "").strip()
UA = {"User-Agent": "monitor-economico/1.0 (+netlify)"}
# El FMI rechaza pedidos que no parecen de un navegador
NAVEGADOR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
             "Accept": "application/json, text/plain, */*", "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
             "Referer": "https://www.imf.org/external/datamapper/"}
errores, avisos = [], []


# ---------------------------------------------------------------- utilidades
def get(url, headers=None, intentos=3, texto=False):
    h = dict(UA, **(headers or {}))
    for i in range(intentos):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=60) as r:
                b = r.read()
                return b.decode("utf-8-sig", errors="replace") if texto else json.loads(b.decode("utf-8-sig"))
        except urllib.error.HTTPError as e:
            if e.code in (400, 401, 403, 404) or i == intentos - 1:
                raise
        except Exception:
            if i == intentos - 1:
                raise
        time.sleep(3 * (i + 1))


def indec(endpoint, **filtros):
    """Recorre todas las páginas de 1000 filas de la API del INDEC."""
    if not TOKEN:
        raise RuntimeError("falta INDEC_TOKEN")
    filas, offset = [], 0
    while True:
        q = dict(filtros, limit=1000, offset=offset)
        url = "https://api.indec.gob.ar/v1/" + endpoint + "?" + urllib.parse.urlencode(q, safe="*.,()")
        pag = get(url, {"Authorization": "Bearer " + TOKEN})
        filas += pag
        if len(pag) < 1000:
            return filas
        offset += 1000


def txt(*vals):
    return " | ".join("" if v is None else str(v) for v in vals).lower()


def num(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    t = str(v).strip()
    if t in ("", "NA", "...", "-", "///", "s", "."):
        return None
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def mes(anio, m):
    return f"{int(anio):04d}-{int(m):02d}"


def una_serie(filas, clave):
    """Si quedó más de una serie, se queda con la de texto más corto (la más general)."""
    if not filas:
        return []
    elegida = min({clave(f) for f in filas}, key=len)
    return [f for f in filas if clave(f) == elegida]


def promedio_por(filas, k, v):
    acc = {}
    for f in filas:
        x = v(f)
        if x is not None:
            acc.setdefault(k(f), []).append(x)
    return dict(sorted((a, sum(b) / len(b)) for a, b in acc.items()))


S = {}  # id -> {nombre, unidad, frecuencia, fuente, datos: {periodo: valor}}


def guardar(id_, nombre, unidad, frec, fuente, datos):
    if not datos:
        errores.append(f"{nombre}: sin datos")
    S[id_] = {"nombre": nombre, "unidad": unidad, "frecuencia": frec, "fuente": fuente, "datos": datos}
    print(f"  {nombre:<45} {len(datos):>5} períodos  último: {max(datos) if datos else '-'}")


def intentar(nombre, fn):
    try:
        fn()
    except Exception as e:
        errores.append(f"{nombre}: {type(e).__name__}: {e}")
        print(f"  !! {nombre}: {e}")


desde = f"gte.{ANIO_INICIO - 1}"

# ---------------------------------------------------------------- INDEC (API)
def emae():
    f = indec("estimador-mensual-de-actividad-economica-nivel-general", anio=desde,
              order="tipo_de_indicador_descripcion,anio,mes,periodo,tipo_de_indicador")
    c = lambda r: txt(r.get("tipo_de_indicador_descripcion"), r.get("tipo_de_indicador"))
    f = una_serie([r for r in f if "original" in c(r) and "ndice" in c(r) and "var" not in c(r)], c)
    guardar("emae", "EMAE (actividad económica)", "Índice 2004=100", "M", "INDEC",
            promedio_por(f, lambda r: mes(r["anio"], r["mes"]), lambda r: num(r.get("valor"))))


def emae_sectores():
    f = indec("estimador-mensual-de-actividad-economica-sectores", anio=desde,
              order="anio,mes,codigo,descripcion,periodo,tipo_de_indicador")
    f = [r for r in f if "ndice" in txt(r.get("tipo_de_indicador")) and "var" not in txt(r.get("tipo_de_indicador"))
         and "total" not in txt(r.get("descripcion")) and "nivel general" not in txt(r.get("descripcion"))]
    sect = {}
    for r in f:
        sect.setdefault(str(r.get("descripcion")), []).append(r)
    S["emae_sectores"] = {"nombre": "EMAE por sector", "unidad": "Índice", "frecuencia": "M", "fuente": "INDEC",
                          "sectores": {s: promedio_por(v, lambda r: mes(r["anio"], r["mes"]), lambda r: num(r.get("valor")))
                                       for s, v in sect.items()}}
    print(f"  {'EMAE por sector':<45} {len(sect):>5} sectores")
    if not sect:
        errores.append("EMAE por sector: sin datos")


def ipc(id_, nombre, patron):
    def run():
        f = indec("ipc_nacional", anio=desde, region="ilike.*nacional*", descripcion=patron,
                  order="clasificador,nivel,codigo,descripcion,periodo,anio,mes,indicador,tipo_de_indicador,tipo_de_indicador_descripcion,region,unidad_de_medida")
        c = lambda r: txt(r.get("tipo_de_indicador"), r.get("tipo_de_indicador_descripcion"), r.get("unidad_de_medida"))
        f = una_serie([r for r in f if "ndice" in c(r) and "var" not in c(r)], c)
        guardar(id_, nombre, "Índice dic 2016=100", "M", "INDEC",
                promedio_por(f, lambda r: mes(r["anio"], r["mes"]), lambda r: num(r.get("valor"))))
    return run


def cbt():
    f = indec("valorizacion_canastas_cba_cbt", anio=desde,
              order="clasificador,nivel,codigo,descripcion,periodo,anio,mes,indicador,tipo_de_indicador,tipo_de_indicador_descripcion,region,unidad_de_medida")
    c = lambda r: txt(*[r.get(k) for k in ("clasificador", "nivel", "codigo", "descripcion", "indicador",
                                            "tipo_de_indicador", "tipo_de_indicador_descripcion", "unidad_de_medida")])
    f = [r for r in f if ("total" in c(r) or "cbt" in c(r)) and "alimentaria" not in c(r) and "var" not in c(r)]
    acc = {}
    for r in f:
        v = num(r.get("valor"))
        if v is not None and v > 100:   # montos en pesos; la de adulto equivalente es la menor
            k = mes(r["anio"], r["mes"])
            acc[k] = min(acc.get(k, v), v)
    guardar("cbt", "Canasta básica total (adulto equivalente, GBA)", "$", "M", "INDEC", dict(sorted(acc.items())))


def eph(endpoint, campo, meses, mapa, frec):
    def run():
        f = indec(endpoint, anio=desde, order="area_geografica_nom,periodo")
        areas = {r.get("area_geografica_nom") for r in f}
        if len(areas) > 1:
            f = [r for r in f if "total" in txt(r.get("area_geografica_nom"))]
        for col, (id_, nombre) in mapa.items():
            def per(r):
                n = int(r[campo])
                return f"{int(r['anio'])}-{'T' if frec == 'T' else 'S'}{n}"
            guardar(id_, nombre, "%", frec, "INDEC (EPH)", promedio_por(f, per, lambda r: num(r.get(col))))
    return run


def poblacion():
    f = indec("proyecciones_poblacion_nacional_2022_2040", order="edad,sexo_cod,fecha")
    f = [r for r in f if "ambos" not in txt(r.get("sexo_nom")) and "total" not in txt(r.get("sexo_nom"))]
    acc = {}
    for r in f:
        v = num(r.get("poblacion"))
        if v is not None:
            acc[str(int(float(r["fecha"])))] = acc.get(str(int(float(r["fecha"]))), 0) + v
    guardar("poblacion", "Población (proyección)", "personas", "A", "INDEC", dict(sorted(acc.items())))


# ---------------------------------------------------------------- INDEC (archivo de salarios)
def salarios():
    t = get("https://www.indec.gob.ar/ftp/cuadros/sociedad/indice_salarios.csv", texto=True)
    filas = list(csv.reader(io.StringIO(t), delimiter=";"))
    enc = [h.strip() for h in filas[0]]
    i = enc.index("IS_indice_total")
    acc = {}
    for r in filas[1:]:
        if len(r) > i and r[0].strip():
            d, m, a = r[0].strip().split("/")
            v = num(r[i])
            if v is not None and int(a) >= ANIO_INICIO - 1:
                acc[mes(a, m)] = v
    guardar("salarios", "Índice de salarios (total)", "Índice oct 2016=100", "M", "INDEC", acc)


# ---------------------------------------------------------------- ArgentinaDatos
def diarios(ruta):
    return get("https://api.argentinadatos.com/v1/" + ruta)


def dolar(casa, id_, nombre):
    def run():
        f = diarios(f"cotizaciones/dolares/{casa}")
        f = [r for r in f if str(r.get("fecha", ""))[:4] >= str(ANIO_INICIO - 1)]
        guardar(id_, nombre, "$ por USD", "M", "ArgentinaDatos",
                promedio_por(f, lambda r: str(r["fecha"])[:7], lambda r: num(r.get("venta"))))
        ult = max(f, key=lambda r: r["fecha"]) if f else None
        if ult:
            S[id_]["ultimo_diario"] = {"fecha": str(ult["fecha"])[:10], "valor": num(ult.get("venta"))}
    return run


def riesgo_pais():
    f = diarios("finanzas/indices/riesgo-pais")
    f = [r for r in f if str(r.get("fecha", ""))[:4] >= str(ANIO_INICIO)]
    guardar("riesgo", "Riesgo país (EMBI)", "puntos básicos", "M", "ArgentinaDatos",
            promedio_por(f, lambda r: str(r["fecha"])[:7], lambda r: num(r.get("valor"))))
    ult = max(f, key=lambda r: r["fecha"]) if f else None
    if ult:
        S["riesgo"]["ultimo_diario"] = {"fecha": str(ult["fecha"])[:10], "valor": num(ult.get("valor"))}


# ---------------------------------------------------------------- FMI y Banco Mundial
PAISES = {"ARG": "Argentina", "BRA": "Brasil", "CHL": "Chile", "URY": "Uruguay", "MEX": "México",
          "COL": "Colombia", "PER": "Perú", "PRY": "Paraguay", "BOL": "Bolivia", "ECU": "Ecuador"}
MUNDO = {}


def fmi():
    def leer(ruta):
        motivo = ""
        for v in ("v1", "v2"):
            try:
                return get(f"https://www.imf.org/external/datamapper/api/{v}/{ruta}", NAVEGADOR)
            except Exception as e:
                motivo = f"{type(e).__name__} {getattr(e, 'code', '')} {e}"
        raise RuntimeError(f"FMI no respondió ({motivo.strip()}): {ruta}")
    cat = {}
    for grupo in ("regions", "groups"):
        try:
            cat.update(leer(grupo).get(grupo, {}))
        except Exception:
            pass
    lab = {c: str((v or {}).get("label", "")).lower() for c, v in cat.items()}
    mundo = next((c for c, l in lab.items() if l == "world"), "WEOWORLD")
    latam = next((c for c, l in lab.items() if "latin america" in l), None)
    codigos = dict(PAISES, **{mundo: "Mundo"}, **({latam: "América Latina y el Caribe"} if latam else {}))
    inds = {"NGDP_RPCH": ("Crecimiento del PIB real", "% anual"), "PCPIPCH": ("Inflación (promedio anual)", "%"),
            "LUR": ("Desempleo", "% de la población activa"), "PPPPC": ("PIB per cápita PPA", "USD internacionales"),
            "GGXWDG_NGDP": ("Deuda pública bruta", "% del PIB"), "BCA_NGDPD": ("Cuenta corriente (FMI)", "% del PIB")}
    mejor = {"NGDP_RPCH": "alto", "PCPIPCH": "bajo", "LUR": "bajo", "PPPPC": "alto", "GGXWDG_NGDP": "bajo", "BCA_NGDPD": "alto"}
    for cod, (nombre, unidad) in inds.items():
        try:
            vals = leer(cod + "/" + "/".join(codigos))["values"][cod]
        except Exception as e:
            avisos.append(f"FMI {nombre}: {e}"); continue
        paises = {codigos[c]: {a: v for a, v in sorted(serie.items()) if int(a) >= 2000 and v is not None}
                  for c, serie in vals.items() if c in codigos}
        MUNDO["fmi_" + cod] = {"nombre": nombre, "unidad": unidad, "fuente": "FMI (WEO)", "proyeccion_desde": HOY.year,
                               "categoria": "Macroeconomía", "mejor": mejor[cod], "paises": paises}
        print(f"  FMI {nombre:<41} {len(paises):>5} países/regiones")
    if not latam:
        avisos.append("FMI: no se encontró el código de América Latina en el catálogo")


# Si el FMI no responde, la sección se completa con los mismos indicadores del Banco Mundial (sin proyecciones)
RESPALDO_BM = {"NGDP_RPCH": ("NY.GDP.MKTP.KD.ZG", "Crecimiento del PIB real", "% anual", "alto"),
               "PCPIPCH": ("FP.CPI.TOTL.ZG", "Inflación (promedio anual)", "%", "bajo"),
               "LUR": ("SL.UEM.TOTL.ZS", "Desempleo", "% de la población activa", "bajo"),
               "PPPPC": ("NY.GDP.PCAP.PP.KD", "PIB per cápita PPA", "USD internacionales constantes", "alto")}

# Indicadores del Banco Mundial: código -> (nombre, unidad, categoría, qué es mejor: "alto", "bajo" o None)
INDS_BM = {
    "NE.RSB.GNFS.ZS": ("Balanza de bienes y servicios", "% del PIB", "Comercio y cuentas externas", "alto"),
    "BN.CAB.XOKA.GD.ZS": ("Cuenta corriente", "% del PIB", "Comercio y cuentas externas", "alto"),
    "NE.EXP.GNFS.ZS": ("Exportaciones", "% del PIB", "Comercio y cuentas externas", "alto"),
    "NE.IMP.GNFS.ZS": ("Importaciones", "% del PIB", "Comercio y cuentas externas", None),
    "TG.VAL.TOTL.GD.ZS": ("Comercio de mercancías (apertura)", "% del PIB", "Comercio y cuentas externas", "alto"),
    "TX.VAL.FOOD.ZS.UN": ("Exportaciones de alimentos", "% de las exportaciones", "Comercio y cuentas externas", None),
    "TX.VAL.FUEL.ZS.UN": ("Exportaciones de combustibles", "% de las exportaciones", "Comercio y cuentas externas", None),
    "TX.VAL.TECH.MF.ZS": ("Exportaciones de alta tecnología", "% de las manufacturas", "Comercio y cuentas externas", "alto"),
    "BX.KLT.DINV.WD.GD.ZS": ("Inversión extranjera directa", "% del PIB", "Comercio y cuentas externas", "alto"),
    "FI.RES.TOTL.MO": ("Reservas", "meses de importaciones", "Comercio y cuentas externas", "alto"),
    "SI.POV.GINI": ("Índice de Gini", "0 = igualdad, 100 = desigualdad", "Desigualdad y pobreza", "bajo"),
    "SI.POV.DDAY": ("Pobreza extrema (línea internacional)", "% de la población", "Desigualdad y pobreza", "bajo"),
    "SI.POV.UMIC": ("Pobreza (línea de país de ingreso medio-alto)", "% de la población", "Desigualdad y pobreza", "bajo"),
    "SI.DST.10TH.10": ("Ingreso del 10% más rico", "% del ingreso total", "Desigualdad y pobreza", "bajo"),
    "SI.DST.FRST.20": ("Ingreso del 20% más pobre", "% del ingreso total", "Desigualdad y pobreza", "alto"),
    "HD.HCI.OVRL": ("Índice de capital humano", "0 a 1", "Educación", "alto"),
    "SE.LPV.PRIM": ("Pobreza de aprendizaje", "% de chicos de 10 años", "Educación", "bajo"),
    "SE.XPD.TOTL.GD.ZS": ("Gasto en educación", "% del PIB", "Educación", "alto"),
    "SE.TER.ENRR": ("Matrícula terciaria y universitaria", "% bruto", "Educación", "alto"),
    "SE.SEC.CMPT.LO.ZS": ("Finalización del secundario inferior", "% del grupo de edad", "Educación", "alto"),
    "SP.DYN.TFRT.IN": ("Fecundidad", "hijos por mujer", "Demografía y salud", None),
    "SP.DYN.LE00.IN": ("Esperanza de vida", "años", "Demografía y salud", "alto"),
    "SP.DYN.IMRT.IN": ("Mortalidad infantil", "por 1.000 nacidos vivos", "Demografía y salud", "bajo"),
    "SP.POP.65UP.TO.ZS": ("Población de 65 años o más", "% de la población", "Demografía y salud", None),
    "SH.XPD.CHEX.GD.ZS": ("Gasto en salud", "% del PIB", "Demografía y salud", None),
    "FS.AST.PRVT.GD.ZS": ("Crédito al sector privado", "% del PIB", "Inversión, crédito e innovación", "alto"),
    "NE.GDI.TOTL.ZS": ("Inversión total", "% del PIB", "Inversión, crédito e innovación", "alto"),
    "GB.XPD.RSDV.GD.ZS": ("Gasto en investigación y desarrollo", "% del PIB", "Inversión, crédito e innovación", "alto"),
    "IT.NET.USER.ZS": ("Usuarios de internet", "% de la población", "Inversión, crédito e innovación", "alto"),
    "SL.TLF.CACT.FE.ZS": ("Participación laboral femenina", "% de mujeres de 15 años o más", "Trabajo", "alto"),
    "SL.UEM.1524.ZS": ("Desempleo juvenil", "% de 15 a 24 años", "Trabajo", "bajo"),
    "RL.EST": ("Estado de derecho", "-2,5 a +2,5", "Instituciones", "alto"),
    "CC.EST": ("Control de la corrupción", "-2,5 a +2,5", "Instituciones", "alto"),
    "AG.YLD.CREL.KG": ("Rinde de cereales", "kg por hectárea", "Agro", "alto"),
    "AG.LND.ARBL.ZS": ("Tierra cultivable", "% de la superficie", "Agro", None),
    "NV.AGR.TOTL.ZS": ("Agro, silvicultura y pesca", "% del PIB", "Agro", None),
}


def banco_mundial():
    codigos = dict(PAISES, LCN="América Latina y el Caribe", WLD="Mundo")
    pedidos = {cod: ("bm_" + cod,) + v for cod, v in INDS_BM.items()}
    faltan = {f: v for f, v in RESPALDO_BM.items() if "fmi_" + f not in MUNDO}
    for f, (cod, nombre, unidad, mejor) in faltan.items():
        pedidos[cod] = ("fmi_" + f, nombre, unidad, "Macroeconomía", mejor)   # ocupa el lugar del indicador del FMI
    if faltan:
        nombres = [v[1] for v in faltan.values()]
        errores[:] = [e for e in errores if not any(e.startswith("FMI " + n) for n in nombres)]
        avisos.append("El FMI no respondió: " + ", ".join(nombres).lower() + " salen del Banco Mundial (sin proyecciones)")
    ok = 0
    for cod, (clave, nombre, unidad, categoria, mejor) in pedidos.items():
        try:
            url = (f"https://api.worldbank.org/v2/country/{';'.join(codigos)}/indicator/{cod}"
                   f"?format=json&per_page=20000&date=2000:{HOY.year}")
            r = get(url)
            filas = r[1] if isinstance(r, list) and len(r) > 1 and r[1] else []
        except Exception as e:
            avisos.append(f"Banco Mundial {nombre}: {e}"); continue
        paises = {}
        for f in filas:
            p = codigos.get(f.get("countryiso3code"))
            if p and f.get("value") is not None:
                paises.setdefault(p, {})[str(f["date"])] = f["value"]
        if not paises:
            avisos.append(f"Banco Mundial {nombre}: sin datos"); continue
        ok += 1
        MUNDO[clave] = {"nombre": nombre, "unidad": unidad, "fuente": "Banco Mundial", "proyeccion_desde": None,
                        "categoria": categoria, "mejor": mejor, "paises": {p: dict(sorted(v.items())) for p, v in paises.items()}}
    print(f"  {'Banco Mundial':<45} {ok:>5} indicadores")
    if ok == 0:
        errores.append("Banco Mundial: no respondió")


# ---------------------------------------------------------------- BCRA (API pública, sin token)
def bcra():
    base = "https://api.bcra.gob.ar/estadisticas/v4.0/monetarias"
    try:
        lista = get(base).get("results", [])
    except Exception as e:
        lista = []
        avisos.append(f"BCRA catálogo: {e}")
    def buscar(*palabras, excluir=()):
        for v in lista:
            d = txt(v.get("descripcion"))
            if all(p in d for p in palabras) and not any(x in d for x in excluir):
                return v.get("idVariable")
        return None
    pedidos = {"reservas": (buscar("reservas internacionales") or 1, "Reservas internacionales del BCRA", "millones de USD"),
               "base_monetaria": (buscar("base monetaria", excluir=("var", "promedio")), "Base monetaria", "millones de $"),
               "mayorista": (buscar("tipo de cambio mayorista") or buscar("a3500"), "Dólar mayorista oficial (A3500)", "$ por USD")}
    for id_, (var, nombre, unidad) in pedidos.items():
        if not var:
            avisos.append(f"BCRA: no se encontró la variable {nombre}"); continue
        try:
            diario, offset = {}, 0
            while True:
                r = get(f"{base}/{var}?desde={ANIO_INICIO}-01-01&hasta={HOY.isoformat()}&limit=3000&offset={offset}")
                res = r.get("results") or []
                det = res[0].get("detalle", []) if res and isinstance(res[0], dict) and "detalle" in res[0] else res
                for f in det:
                    v = num(f.get("valor"))
                    if v is not None and f.get("fecha"):
                        diario[str(f["fecha"])[:10]] = v
                if len(det) < 3000:
                    break
                offset += 3000
            diario = dict(sorted(diario.items()))
            mensual = promedio_por([{"f": k, "v": v} for k, v in diario.items()], lambda x: x["f"][:7], lambda x: x["v"])
            guardar(id_, nombre, unidad, "M", "BCRA", mensual)
            S[id_]["diario"] = diario
            if diario:
                u = max(diario)
                S[id_]["ultimo_diario"] = {"fecha": u, "valor": diario[u]}
        except Exception as e:
            errores.append(f"BCRA {nombre}: {type(e).__name__}: {e}")
            print(f"  !! BCRA {nombre}: {e}")


# ---------------------------------------------------------------- indicadores derivados
def derivar():
    def ser(i):
        return S.get(i, {}).get("datos", {})
    def menos_meses(p, n):
        a, m = int(p[:4]), int(p[5:7]) - n
        while m <= 0:
            a, m = a - 1, m + 12
        return mes(a, m)
    def var(d, n):
        return {p: d[p] / d[menos_meses(p, n)] - 1 for p in d if menos_meses(p, n) in d and d[menos_meses(p, n)]}
    D = {}
    ipc_ = ser("ipc")
    D["ipc_m"] = var(ipc_, 1)
    D["ipc_ia"] = var(ipc_, 12)
    D["ipc_3m_anual"] = {p: (ipc_[p] / ipc_[menos_meses(p, 3)]) ** 4 - 1 for p in ipc_ if menos_meses(p, 3) in ipc_}
    D["ipc_acum_anio"] = {p: ipc_[p] / ipc_[f"{int(p[:4]) - 1}-12"] - 1 for p in ipc_ if f"{int(p[:4]) - 1}-12" in ipc_}
    D["alimentos_ia"] = var(ser("ipc_alimentos"), 12)
    D["emae_ia"] = var(ser("emae"), 12)
    D["salarios_ia"] = var(ser("salarios"), 12)
    D["cbt_ia"] = var(ser("cbt"), 12)
    D["blue_ia"] = var(ser("blue"), 12)
    sal, base = ser("salarios"), f"{ANIO_INICIO - 1}-12"
    if base in sal and base in ipc_:
        D["salario_real"] = {p: (sal[p] / sal[base]) / (ipc_[p] / ipc_[base]) * 100 for p in sal if p in ipc_}
        D["salario_real_ia"] = var(D["salario_real"], 12)
    blue, ofi = ser("blue"), ser("oficial")
    D["brecha"] = {p: blue[p] / ofi[p] - 1 for p in blue if p in ofi and ofi[p]}
    if ipc_:
        ult = max(ipc_)
        D["blue_real"] = {p: blue[p] * ipc_[ult] / ipc_[p] for p in blue if p in ipc_}   # pesos del último IPC
    cb = ser("cbt")
    D["cbt_usd"] = {p: cb[p] / blue[p] for p in cb if p in blue and blue[p]}
    # base 100 en el primer mes del período
    for i, src in (("base_blue", blue), ("base_ipc", ipc_), ("base_sal", sal)):
        ks = [p for p in sorted(src) if p >= f"{ANIO_INICIO}-01"]
        if ks:
            D[i] = {p: src[p] / src[ks[0]] * 100 for p in ks}
    # sectores: variación interanual del último mes común
    sec = S.get("emae_sectores", {}).get("sectores", {})
    ult = None
    vs = {}
    for s, d in sec.items():
        v = var(d, 12)
        if v:
            u = max(v)
            ult = max(ult or u, u)
            vs[s] = (u, v[u])
    D["sectores_ult"] = {"mes": ult, "valores": {s: x for s, (u, x) in vs.items() if u == ult}}
    return D


def main():
    print("Bajando datos...")
    tareas = [("EMAE", emae), ("EMAE sectores", emae_sectores),
              ("IPC", ipc("ipc", "IPC nivel general", "ilike.*nivel general*")),
              ("IPC alimentos", ipc("ipc_alimentos", "IPC alimentos y bebidas", "ilike.*bebidas no alcoh*")),
              ("CBT", cbt),
              ("Trabajo", eph("mercado_trabajo_eph", "trimestre", 3, {
                  "tasa_de_desocupacion": ("desocupacion", "Desocupación"),
                  "tasa_de_empleo_informal": ("informal", "Empleo informal"),
                  "tasa_de_actividad": ("actividad", "Tasa de actividad"),
                  "tasa_de_subocupacion": ("subocupacion", "Subocupación")}, "T")),
              ("Pobreza", eph("pobreza_eph", "semestre", 6, {
                  "tasa_pobreza_personas": ("pobreza", "Pobreza (personas)"),
                  "tasa_indigencia_personas": ("indigencia", "Indigencia (personas)")}, "S")),
              ("Población", poblacion), ("Salarios", salarios),
              ("Dólar blue", dolar("blue", "blue", "Dólar blue")),
              ("Dólar oficial", dolar("oficial", "oficial", "Dólar oficial")),
              ("Riesgo país", riesgo_pais), ("BCRA", bcra), ("FMI", fmi), ("Banco Mundial", banco_mundial)]
    for nombre, fn in tareas:
        intentar(nombre, fn)
    derivados = derivar()
    nuevo = {"actualizado": datetime.now(timezone.utc).isoformat(timespec="minutes"),
             "anio_inicio": ANIO_INICIO, "series": S, "derivados": derivados, "mundo": MUNDO,
             "errores": errores, "avisos": avisos}
    # Si una fuente falló, se conservan sus datos de la corrida anterior
    if os.path.exists(SALIDA):
        try:
            viejo = json.load(open(SALIDA, encoding="utf-8"))
            for k, v in viejo.get("series", {}).items():
                if k not in S or not (S[k].get("datos") or S[k].get("sectores")):
                    nuevo["series"][k] = v
            for k, v in viejo.get("mundo", {}).items():
                nuevo["mundo"].setdefault(k, v)
        except Exception:
            pass
        nuevo["derivados"] = derivar_desde(nuevo["series"])
    def redondear(x):
        if isinstance(x, float):
            return float(f"{x:.6g}")
        if isinstance(x, dict):
            return {k: redondear(v) for k, v in x.items()}
        if isinstance(x, list):
            return [redondear(v) for v in x]
        return x
    nuevo = redondear(nuevo)
    os.makedirs(os.path.dirname(SALIDA), exist_ok=True)
    json.dump(nuevo, open(SALIDA, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(f"\nListo: {SALIDA}")
    print("Errores:" if errores else "Sin errores.", *errores, sep="\n  ")
    # Falla la corrida solo si no se pudo bajar casi nada
    if len(S) < 5:
        sys.exit(1)


def derivar_desde(series):
    global S
    S = series
    return derivar()


if __name__ == "__main__":
    main()
