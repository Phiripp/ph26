# Caudal · frontend demo

Mockup navegable del frontend de Caudal (Platanus Hack 26, track Physical World), alineado con el spec v2: priorizar qué predios inspeccionar en una zona combinando Sentinel-2 y clima, y entregar una ruta de inspección. Usa los datos reales del equipo para las dos zonas del spec (Z1 Petorca, Z2 Aconcagua bajo) y los 10 casos de validación. El sistema prioriza, no acusa.

## Cómo correrlo

```bash
cd frontend-demo
python3 -m http.server 8000
# abrir http://localhost:8000                    mapa de Chile
#       http://localhost:8000/#z1                directo a Z1 · Petorca (#petorca es alias)
#       http://localhost:8000/#z2                directo a Z2 · Aconcagua bajo
#       http://localhost:8000/#caso-FD-0501-181  directo a un caso sancionado por la DGA
#       http://localhost:8000/#aculeo            gancho: laguna de Aculeo en 3D
```

Hace falta un servidor local (módulos ES y `fetch` no funcionan con `file://`). Sin build: three.js y MapLibre se cargan desde CDN con versiones fijas. Necesita internet para las librerías, las fuentes y el detalle satelital sobre zoom 9.

## Recorrido

1. Mapa de Chile: satélite y relieve sobre Chile, resto del mundo oscuro. Marcadores de las dos zonas (Z1, Z2), los 10 casos sancionados por la DGA y Aculeo; con zoom ≥ 8 aparecen los puntos de fiscalización DGA (rojo = con infracción, gris = sin infracción).
2. Aculeo (gancho): terreno 3D con imágenes reales 2018–2024; el usuario mueve el año y ve cómo cambia el agua.
3. Zona (Z1 o Z2): terreno 3D con los predios por banda y los casos destacados. Panel con tres pestañas:
   - Predios: ranking por banda → ficha (derecho del rol en la DGA, banda provisional, serie NDVI/NDMI con ventanas secas, línea de inspección si es un caso) → expediente con los campos de la guía de denuncias de la DGA.
   - Casos: los casos de la zona → ficha del caso (expediente, comuna, fecha de inspección, decisión, multa en UTM, cómo se veía la señal antes de la inspección, imágenes antes/después).
   - Ruta: ruta de inspección del día (Google Maps / GPX).

Nada se reproduce solo en las vistas 3D: la ruta se recorre solo al tocar el botón.

## Estructura

```
index.html, css/          página y estilos (css/panels.css: paneles de la zona)
js/main.js                orquesta modos: mapa · laguna · zona, rutas #z1 #z2 #caso-… #aculeo
js/map.js                 mapa nacional (MapLibre, tiles locales + remotos), zonas, casos, fiscalizaciones
js/hero.js                Aculeo 3D (three.js)
js/valle.js               escena 3D de una zona (three.js): predios por banda, casos, ruta
js/zona-data.js           carga de datos por zona + formatos compartidos
js/ficha.js, caso.js, expediente.js, ruta-panel.js, chart.js   paneles
data/zonas/               datos de las zonas (ver abajo)
assets/zonas/, assets/casos/, assets/aculeo/   imágenes, DEM y recortes Sentinel-2 de los casos
tiles/                    caché local de tiles satelitales y de relieve de Chile (z3–z9)
scripts/                  scripts que descargan y procesan todo lo anterior
valle-test.html, panels-test.html   páginas de prueba de módulos sueltos
```

## Datos

Todo sale de `data/` del repo del equipo (ver `data/README.md`), convertido a JSON por los scripts de `scripts/`:

```
data/zonas/index.json              zonas Z1/Z2: comunas, bbox de la escena, casos
data/zonas/casos.json              los 10 casos de validación (+ recortes en assets/casos/)
data/zonas/fiscalizaciones.geojson expedientes de fiscalización DGA en Z1/Z2 (sin nombres)
data/zonas/{z1,z2}/predios.geojson predios CIREN de muestra + predios de los casos, con derechos
data/zonas/{z1,z2}/scores.json     banda, índice y rango de consumo (provisional)
data/zonas/{z1,z2}/series.json     NDVI/NDMI mensual por predio + referencia de secano CONAF
data/zonas/{z1,z2}/clima.json      lluvia, ET0 y ventanas secas (N = 10 días)
data/zonas/{z1,z2}/ruta.json, .gpx ruta de inspección
assets/zonas/{z1,z2}/              EOX Sentinel-2 cloudless 2018–2024 + DEM
```

Reales:
- Predios: catastro CIREN (muestra del equipo + predios de los casos).
- Derechos de agua por rol: DGA (cruce del equipo, temporada 2025-26, con su confianza).
- Casos de validación y fiscalizaciones: expedientes públicos de la DGA. Los 10 casos están resueltos con multa y se muestran como "caso sancionado por la DGA".
- Clima y ventanas secas: estaciones DMC + Open-Meteo corregido.
- Series NDVI/NDMI: Sentinel-2 L2A (Element84 Earth Search). No se usa `serie_predio` del equipo (bug D15, offset restado dos veces).
- Ruta: orden con OR-Tools, trazado con OSRM.
- Imágenes: Sentinel-2 cloudless (EOX). Relieve: AWS Terrain Tiles.

Provisional (marcado en la interfaz):
- Banda, índice y rango de consumo de cada predio: regla FAO-56 del spec sobre los derechos reales, hasta que llegue el modelo M5 del equipo.

Principio: el sistema prioriza, no acusa. Solo IDs y rol, nunca nombres de dueños; siempre rangos de m³, nunca una cifra única; ningún predio sin resolver se llama "infractor".

## Atribución

Sentinel-2 cloudless by EOX IT Services GmbH (Contains modified Copernicus Sentinel data) · AWS Terrain Tiles · © OpenStreetMap contributors · Natural Earth · Open-Meteo · DMC · CIREN · DGA · CONAF.
