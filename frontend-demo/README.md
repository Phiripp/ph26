# Caudal · frontend demo

Mockup navegable del frontend de Caudal (Platanus Hack 26, track Physical World), alineado con el spec v2: priorizar qué predios inspeccionar en un valle combinando Sentinel-2 y clima, y entregar una ruta de inspección. El sistema prioriza, no acusa.

## Cómo correrlo

```bash
cd frontend-demo
python3 -m http.server 8000
# abrir http://localhost:8000          mapa de Chile
#       http://localhost:8000/#petorca  directo al valle
#       http://localhost:8000/#aculeo   gancho: laguna de Aculeo en 3D
```

Hace falta un servidor local (módulos ES y `fetch` no funcionan con `file://`). Sin build: three.js y MapLibre se cargan desde CDN con versiones fijas. Necesita internet para las librerías, las fuentes y el detalle satelital sobre zoom 9.

## Recorrido

1. Mapa de Chile: satélite y relieve sobre Chile, resto del mundo oscuro. Marcadores por sitio, agrupados cuando se tapan.
2. Aculeo (gancho): terreno 3D con imágenes reales 2018–2024; el usuario mueve el año y ve cómo cambia el agua.
3. Valle de Petorca: terreno 3D con los 34 predios por banda, ranking, ficha con serie NDVI/NDMI y ventanas secas, expediente con los campos de la guía de denuncias de la DGA y ruta de inspección (Google Maps / GPX).

## Estructura

```
index.html, css/          página y estilos (css/panels.css: paneles del valle)
js/main.js                orquesta modos: mapa · laguna · valle
js/map.js                 mapa nacional (MapLibre, tiles locales + remotos)
js/hero.js                Aculeo 3D (three.js)
js/valle.js               valle de Petorca 3D (three.js): predios, ruta
js/ficha.js, expediente.js, ruta-panel.js, petorca-data.js, chart.js   paneles
data/                     sitios, límites, datos de Petorca (predios, series, clima, ruta)
assets/                   imágenes y DEM de Aculeo y Petorca
tiles/                    caché local de tiles satelitales y de relieve de Chile (z3–z9)
scripts/                  scripts que descargan y procesan todo lo anterior
valle-test.html, panels-test.html   páginas de prueba de módulos sueltos
```

## Datos

Reales:
- Predios: polígonos de OpenStreetMap (Overpass).
- Series NDVI/NDMI mensuales 2022–2024: Sentinel-2 L2A (Element84 Earth Search).
- Clima y ventanas secas (≥10 días sin lluvia efectiva): Open-Meteo (ERA5).
- Ruta: orden con OR-Tools, trazado con OSRM.
- Imágenes: Sentinel-2 cloudless (EOX). Relieve: AWS Terrain Tiles.

Ilustrativos (marcados en la interfaz):
- Derechos de agua por predio y, por lo tanto, bandas e índice de sospecha.
- Cifras de los sitios del mapa nacional distintos de Aculeo y Petorca.

Estos datos son del prototipo y se reemplazan por los del pipeline en `data/processed/` cuando se integren.

## Atribución

Sentinel-2 cloudless by EOX IT Services GmbH (Contains modified Copernicus Sentinel data) · AWS Terrain Tiles · © OpenStreetMap contributors · Natural Earth · Open-Meteo.
