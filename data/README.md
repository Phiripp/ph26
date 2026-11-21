# data/

Datos de entrada de Caudal. Las zonas, las fuentes y las convenciones están en [docs/spec-v2.md](../docs/spec-v2.md). Quién hace qué está en [docs/tareas-datos-modelos.md](../docs/tareas-datos-modelos.md).

## Para empezar (Gabi: D1, D2 y D11)

1. Lee las zonas en [`zonas.json`](zonas.json): comunas, bounding box y periodo de cada zona.
2. Para tener predios ya, usa [`processed/predio_muestra.geojson`](processed/predio_muestra.geojson). Son 100 predios (50 por zona) alrededor de los casos de validación, y ya están en git.
3. Para tener todos los predios (20.050), corre:

   ```bash
   uv run scripts/extract/predios_ciren.py
   ```

   Tarda menos de un minuto y genera `processed/predio.parquet`. No va a git (ver [Licencia](#licencia-y-datos-personales)).
4. Para revisar las series, los casos de validación están en [`casos_validacion.geojson`](casos_validacion.geojson). Empieza por estos dos:
   - **FO-0501-462** (`papel = demo_principal`, La Ligua, predio `88-31`, inspección el 07-05-2025): la serie del verano 2024-25 debería mostrar riego en ventana seca antes de la inspección. Es el caso que se muestra en la demo.
   - **FO-0504-95** (`papel = antecedente_satelital`, Hijuelas, predio `61-6`, inspección el 23-11-2021): la DGA dice que lo detectó con satélite; su serie de 2021 debería mostrar riego en ventana seca.
5. Periodos: el análisis cubre desde enero de 2020 hasta la última escena limpia. Los periodos prioritarios de cada zona están en `zonas.json`. Para la demo, el ranking usa la temporada seca 2025-26 (diciembre de 2025 a marzo de 2026), y la ficha muestra además la escena limpia más reciente.
6. Cuidado con octubre de 2026: según Open-Meteo llovieron unos 100 mm en La Ligua y unos 160 mm en Hijuelas (última lluvia fuerte: 20-10 en La Ligua y 03-11 en Hijuelas). Las escenas de noviembre de 2026 muestran todo verde y separan mal riego de secano.

## Archivos

| Archivo | En git | Qué es | Lo genera |
| --- | --- | --- | --- |
| `zonas.json` | Sí | Copia de las zonas del spec, para leer desde código, con los periodos prioritarios de cada zona | A mano; si cambia, se edita también el spec |
| `casos_validacion.geojson` | Sí | 8 casos resueltos por extracción no autorizada (6 en Z1, 2 en Z2; 4 de 2025), con la columna `papel` | A mano desde la planilla DGA; D6 lo reemplaza |
| `processed/predio_muestra.geojson` | Sí | 100 predios cerca de los casos, con `caso_cercano` y `dist_caso_m` | `scripts/extract/predios_ciren.py` |
| `processed/predio.parquet` | No | Todos los predios de Z1 (9.331) y Z2 (10.719), GeoParquet | `scripts/extract/predios_ciren.py` |
| `raw/ciren/<COMUNA>.geojson` | No | Respuesta cruda de CIREN, una por comuna (caché) | `scripts/extract/predios_ciren.py` |

## Columnas de `predio`

| Columna | Tipo | Descripción |
| --- | --- | --- |
| `predio_id` | int | `mslink` de CIREN; único en la capa. Es la llave para `serie_predio` y el resto de las tablas |
| `zona` | str | `Z1` o `Z2` |
| `comuna` | str | Nombre de la comuna en mayúsculas, sin tildes |
| `rol` | str | Rol SII. Se repite dentro de una comuna (un predio puede tener varios polígonos) |
| `rol_valido` | bool | `True` si el rol tiene formato `manzana-predio` (p. ej. `87-3`). `False` en ríos, caminos, vialidad (`VP-*`, `RV-*`), sin rol (`SR`) y bienes comunes (`BC`): unos 1.800 polígonos que no son predios agrícolas |
| `area_ha` | float | Área en hectáreas, calculada en EPSG:32719 |
| `geometry` | Polygon | EPSG:4326 |

La muestra tiene además `caso_cercano` (expediente del caso más cercano) y `dist_caso_m` (distancia en metros). Solo incluye predios con `rol_valido` y área de 0,5 ha o más.

## Lo que hay que saber

- Filtra `rol_valido = True` antes de calcular series; los demás polígonos son cauces, caminos o cerros sin rol.
- Hay polígonos muy grandes (hasta unas 1.000 ha) que son cerros o fundos enteros. Su NDVI promedio diluye la señal de riego.
- El punto del caso es el pozo o la captación, no el centro del predio. El punto cae dentro de un predio válido en FO-0501-462 (`88-31`, 6,1 ha), FO-0504-95 (`61-6`, 5,7 ha), FO-0504-157 (`46-25`, 29,8 ha) y FO-0501-376 (`101-12`, 993 ha: demasiado grande para una señal clara). En los otros 4 casos cae fuera, a entre 5 y 24 m del predio más cercano.
- Solo se usan casos resueltos. Hay expedientes "En trámite" en las zonas; no se muestran como infractores en la demo.
- Las coordenadas de los casos suponen datum WGS84; la planilla de la DGA no lo indica.

## Licencia y datos personales

- Predios: CIREN 2022, vía IDE Minagri. No se encontraron términos de uso. Se cita la fuente y no se sube la capa completa; solo la muestra.
- Casos: planilla pública de la DGA. No trae nombres.
- Los nombres de titulares de derechos de agua (tarea D4) no se suben a git.
