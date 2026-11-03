# Monitor económico argentino · web pública y gratuita

Una página con todos los indicadores del monitor (INDEC, dólar, riesgo país, FMI y Banco Mundial)
que se actualiza sola todos los días a las 7:17 de Argentina.

## Cómo funciona

```
GitHub (gratis)                                        Netlify (gratis)
 └─ todos los días corre scripts/actualizar.py          └─ publica la página (site/index.html)
    baja los datos y guarda site/data/datos.json  ──►      la página lee datos.json desde GitHub
```

La página se publica en Netlify **una sola vez**. Los datos nuevos los toma de GitHub,
así que no hace falta volver a publicar en Netlify cada día.

**Por qué así:** en el plan gratuito de Netlify cada publicación gasta 15 de los 300 créditos
del mes. Publicar todos los días agotaría los créditos y Netlify pausaría **todos** tus
sitios, incluido argensig.netlify.app.

---

## Paso 1 · Crear el repositorio en GitHub

1. Entrá a https://github.com y creá una cuenta gratuita (sirve el Gmail).
2. Arriba a la derecha **+ → New repository**.
   - Repository name: `monitor-economico` (exactamente así).
   - Marcá **Public**.
   - Tocá **Create repository**.
3. En la página del repositorio vacío tocá **uploading an existing file**.
4. Arrastrá desde tu computadora las carpetas **scripts** y **site** y el archivo **LEEME.md**.
   Abajo tocá **Commit changes**.

## Paso 2 · Crear la actualización automática

La carpeta `.github` es oculta y GitHub no la deja subir arrastrando, así que se crea a mano:

1. En el repositorio: **Add file → Create new file**.
2. En el nombre escribí exactamente: `.github/workflows/actualizar.yml`
3. Abrí con el Bloc de notas el archivo `.github/workflows/actualizar.yml` de esta carpeta,
   copiá todo el contenido y pegalo.
4. **Commit changes**.

## Paso 3 · Guardar el token del INDEC (en secreto)

1. En el repositorio: **Settings → Secrets and variables → Actions → New repository secret**.
2. Name: `INDEC_TOKEN` · Secret: pegá tu token (sin la palabra Bearer).
3. **Add secret**. El token queda cifrado: no lo ve nadie, ni siquiera en el repositorio público.

## Paso 4 · Dar permiso para guardar los datos y probar

1. **Settings → Actions → General**, abajo en **Workflow permissions** elegí
   **Read and write permissions** → **Save**.
2. Pestaña **Actions** → a la izquierda **Actualizar datos** → **Run workflow** → **Run workflow**.
3. Esperá 1 o 2 minutos. Si queda en verde, en la carpeta `site/data` del repositorio aparece
   `datos.json`. Si queda en rojo, abrí la corrida y mandame una captura del paso
   "Bajar datos": ahí figura qué fuente falló.

## Paso 5 · Conectar la página con los datos

Ya está hecho: `site/index.html` apunta a
`https://raw.githubusercontent.com/PabloOjeda/monitor-economico/main/site/data/datos.json`.
Si el repositorio se llama distinto de `monitor-economico`, cambiá ese nombre en esa línea.

## Paso 6 · Publicar en Netlify (una sola vez)

1. Entrá a https://app.netlify.com → **Add new project → Deploy manually**.
2. Arrastrá la carpeta **site** (solo esa carpeta).
3. Netlify te da una dirección. Para cambiarla: **Project configuration → Change project name**,
   por ejemplo `monitor-economico-argensig` → https://monitor-economico-argensig.netlify.app

Listo. Desde ahí la página muestra siempre los datos del día, sin hacer nada más.

---

## Mantenimiento

- **Actualizar a mano:** Actions → Actualizar datos → Run workflow.
- **Cambiar el diseño o los textos:** editás `site/index.html` y volvés a arrastrar la carpeta
  `site` en Netlify → tu proyecto → **Deploys** (gasta 15 créditos cada vez; tenés 300 por mes).
- **Si una fuente falla un día**, la página conserva sus datos anteriores y muestra un aviso arriba.
- **Si GitHub desactiva la tarea programada** (lo hace si un repositorio pasa 60 días sin actividad),
  te avisa por correo: entrás a Actions y tocás **Enable workflow**.
- **Si el INDEC no responde desde GitHub** (los servidores de GitHub están fuera del país),
  se puede correr la actualización desde tu computadora:
  `set INDEC_TOKEN=tu_token` y `python scripts/actualizar.py`, y subir el `datos.json` al repositorio.

## Probar en tu computadora antes de subir

```
set INDEC_TOKEN=tu_token
python scripts/actualizar.py
cd site
python -m http.server 8000
```
Abrí http://localhost:8000 en el navegador. (En localhost la página lee el `datos.json` local.)

## Indicadores

**Hoy:** actividad (EMAE), inflación mensual, interanual, anualizada de 3 meses y acumulada del año,
salario real, desocupación, pobreza e indigencia, dólar blue, brecha cambiaria, riesgo país,
canasta básica en dólares y población.

**Gráficos:** actividad e inflación, inflación mensual, actividad por sector, alimentos,
salario real, canasta contra salarios, pobreza, trabajo, dólar-precios-salarios (base 100),
dólar blue a precios de hoy, brecha, riesgo país, canasta en dólares, y Argentina contra
América Latina, el Mundo, Brasil, Chile, Uruguay y México (FMI con proyecciones y Banco Mundial).

**Fuentes:** API del INDEC, archivo de salarios del INDEC, ArgentinaDatos (dólar y riesgo país),
FMI World Economic Outlook (DataMapper) y Banco Mundial. Todas gratuitas.
