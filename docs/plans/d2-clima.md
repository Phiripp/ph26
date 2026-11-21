# Plan D2 — Lluvia diaria y ET0

Nov 21, 2026 · Responsable: Gabriela · Tarea D2 de [tareas-datos-modelos.md](../tareas-datos-modelos.md)

Entrega: `data/processed/clima.parquet` y `data/processed/estacion_clima.parquet`, con la columna `zona`. Las zonas, el periodo y las convenciones están en [spec-v2.md](../spec-v2.md); este plan no las repite.

## Punto de partida

Lo que dicen las pruebas de [pruebas-acceso-datos.md](../pruebas-acceso-datos.md) cambia el diseño original:

- Open-Meteo sobreestima la lluvia cerca de 2 veces (Chincolco 2025: 125,7 mm de estación contra 305,5 mm). No sirve para decidir la ventana seca de un día concreto.
- Por eso la **lluvia viene de estaciones DMC** y Open-Meteo aporta **ET0** y un respaldo corregido.
- La lluvia diaria de DMC llega hasta el 2025-12-31. De enero a octubre de 2026 no hay serie histórica en línea.
- DMC pide usuario y token (ya probados, en `.env`). INIA no responde y DGA no tiene API.

## Salidas

`clima.parquet`, una fila por fuente, punto y fecha:

| Columna | Contenido |
| --- | --- |
| `zona` | `Z1` o `Z2` |
| `punto_id` | Código de estación DMC (por ejemplo `320049`) o id de celda (`OM_Z1_03_05`) |
| `fuente` | `dmc` o `openmeteo` |
| `fecha` | Día |
| `lluvia_mm` | Lluvia tal como la entrega la fuente |
| `lluvia_corr_mm` | Solo Open-Meteo: lluvia corregida con las estaciones (ver paso 4); vacía en DMC |
| `et0_mm` | ET0 FAO de Open-Meteo; vacía en DMC |
| `lluvia_dato_faltante` | `true` si el día no tiene registro en la estación |

`predio_clima.parquet`: `predio_id`, `zona`, `celda_id`, `estacion_id` y `distancia_estacion_km`. Es la tabla de enlace entre predios y clima.

`estacion_clima.parquet`: `punto_id`, `fuente`, `nombre`, `lat`, `lon`, `zona`, `distancia_a_zona_km`, primera y última fecha con lluvia.

## Pasos

1. **Estaciones candidatas.** Bajar el catálogo `getEstacionesRedEma`, convertir lat y lon de texto a número y quedarse con las estaciones dentro de cada zona más un margen de 20 km. Ya se sabe que en Z1 solo hay Chincolco dentro y que Llay Llay, Panquehue, Zapallar Catapilco y El Tártaro están cerca. Falta mirar Z2 (Quillota, La Calera, Hijuelas). Guardar el resultado en `estacion_clima.parquet`.
2. **Lluvia diaria DMC.** Para cada estación candidata, llamar a `getAguaCaidaDiaria/{codigo}` (ruta `serviciosb`) de 2020 a 2025 y guardar la respuesta en `data/raw/clima/dmc/`. Marcar los días faltantes en vez de rellenarlos. Descartar estaciones con más de 30 % de días faltantes en 2021–2022 (Z2) o 2024–2025 (Z1).
3. **ET0 y lluvia Open-Meteo, ancladas a los predios.** Open-Meteo tiene resolución de unos 10 km, así que pedir un punto por predio devolvería la misma serie muchas veces. En cambio, tomar el centroide de cada predio con `rol_valido` (de `predio.parquet`; mientras tanto, de `predio_muestra.geojson`), redondearlo a la celda de 0,1° y quedarse con las celdas únicas. Eso descarta las celdas de cordillera sin predios y reduce las llamadas respecto de cubrir todo el bounding box. Guardar también `predio_celda` (`predio_id`, `punto_id` de la celda y de la estación más cercana) para que M1 y M4 no tengan que recalcular el cruce. Pedir `precipitation_sum` y `et0_fao_evapotranspiration` diarios de enero de 2020 a octubre de 2026 y guardar en `data/raw/clima/openmeteo/`. Pedir varias coordenadas por llamada y espaciar las llamadas para no topar el límite gratuito.
4. **Corrección de la lluvia de Open-Meteo.** Para cada celda, asignar la estación DMC más cercana con serie válida. Con 2020–2025, calcular un factor mensual (lluvia de estación sobre lluvia de la grilla, con tope) y aplicarlo para obtener `lluvia_corr_mm`. Este paso cubre dos huecos: las celdas lejos de estaciones y el año 2026. Es una aproximación y se documenta como tal; si el factor sale inestable, se usa un factor anual.
5. **Serie propia 2026.** DMC no tiene histórico de 2026, así que se escribe `scripts/extract/d2_clima_dmc_diario.py`, que llama a `getEmaResumenDiario` y agrega el día anterior a `data/raw/clima/dmc/2026_acumulado.parquet`. Debe ser idempotente para poder correrlo a diario (cron o a mano) hasta la demo. El servicio devuelve unos 4 días, así que basta correrlo cada 3 días. **Hecho:** [d2_clima_dmc_diario.py](../../scripts/extract/d2_clima_dmc_diario.py). También baja los **totales mensuales de 2026** (`getAguaCaidaMensualAnual`, sí disponibles en línea para enero a noviembre), que quedan en `2026_mensual.parquet`. Lo que no se alcance a acumular se cubre con `lluvia_corr_mm`, y en 2026 ese factor se calibra mes a mes con los totales de la estación: la lluvia diaria de Open-Meteo se reescala para que su suma mensual calce con la estación.
6. **Unir y validar.** Concatenar las dos fuentes en `clima.parquet` y comprobar:
   - Sin fechas duplicadas por `punto_id`.
   - Open-Meteo sin huecos entre 2020-01-01 y 2026-10-31.
   - `lluvia_corr_mm` anual de las celdas vecinas a una estación dentro de ±25 % de la estación en 2025.
   - Un gráfico mensual por estación contra su celda más cercana, guardado en `docs/`.

## Scripts

Todos en `scripts/extract/`, uno por fuente, leyendo `DMC_USER` y `DMC_TOKEN` desde `.env`:

- `d2_clima_dmc.py`: pasos 1 y 2.
- `d2_clima_openmeteo.py`: paso 3.
- `d2_clima_dmc_diario.py`: paso 5.
- `d2_clima_unir.py`: pasos 4 y 6; escribe los dos Parquet.

El contraste exploratorio de las pruebas de acceso quedó absorbido por `d2_clima_unir.py` (tabla `clima_validacion.csv`).

## Orden y tiempo

1. Pasos 1 y 3 en paralelo (no dependen entre sí).
2. Paso 2, que necesita la lista de estaciones.
3. Paso 5, lo antes posible: cada día sin correrlo es un día de 2026 sin dato de estación.
4. Pasos 4 y 6 al final.

Lo mínimo para desbloquear a M1 es `clima.parquet` con lluvia de estaciones 2020–2025 y `lluvia_corr_mm` para 2026; el resto puede llegar después.

## Riesgos y decisiones abiertas

- **Pocas estaciones en Z1.** Una sola dentro de la caja; la lluvia de Petorca y Cabildo depende de la corrección con estaciones a decenas de km. Se anota en la confianza de M5.
- **Cuota de la API DMC.** No está documentada; si hay límite, bajar solo las estaciones elegidas en el paso 1.
- **DGA e INIA.** No se esperan; si llega un CSV de DGA o respuesta de INIA, se agrega como una fuente más con el mismo formato.
- **Umbral de "lluvia efectiva".** Lo fija M1 (hoy, N = 10 días) y no se decide aquí; D2 entrega la lluvia sin umbral.
- **Open-Meteo 2026.** Si el archivo histórico no cubre los últimos días, completar con el endpoint de pronóstico con `past_days`.

## Al terminar

Poner D2 en ✅ en el seguimiento, anotar las dos rutas en "Entrega" y marcar Z1 y Z2 en "Estado por zona". Si hay estaciones sin cobertura en alguna zona, dejarlo escrito en Bloqueos o Decisiones.

## Resultado (2026-11-21)

Los pasos 1 a 6 están hechos con los 18.244 predios válidos (57 celdas de Open-Meteo, 10 estaciones DMC con serie). Salidas: `clima.parquet` (184.104 filas), `predio_clima.parquet`, `estacion_clima.parquet` y `clima_validacion.csv`, más el gráfico `docs/img/clima_validacion.png`. Para regenerar todo: `d2_clima_dmc.py`, `d2_clima_openmeteo.py`, `d2_clima_dmc_diario.py` y `d2_clima_unir.py`, en ese orden.

Qué dice la validación (con la estación calibrando el factor, así que es optimista):

- Lluvia anual 2020–2025: la corregida queda a menos de 3 % de la estación en las celdas de referencia; la cruda sobreestimaba entre 5 % y 80 %.
- 2025 por separado: dentro de ±15 % salvo en dos referencias. Zapallar Catapilco (320063) registró 52 mm en 2025 contra 310–360 mm de Open-Meteo, y la corregida queda a 2,8 veces: o fue un año extremo en la costa o el pluviómetro tiene problemas. Quintero (320056) queda a 1,5 veces.
- Acierto en días lluviosos (≥ 1 mm): sube de 93–95 % a 94–97 %. Es poco, porque casi todos los días son secos.

Limitaciones que conviene recordar al usar el dato:

- No hay estación dentro de las comunas interiores de Z2 (Quillota, La Cruz, La Calera): Quillota Liceo y Catemu no tienen historia. Sus predios usan estaciones a unos 20 km.
- En Z1 casi todos los predios usan Zapallar (costa) o Chincolco, a 19–25 km de mediana.
- La lluvia corregida de 2026 está calzada mes a mes con las estaciones, no día a día. Las ventanas secas de 2026 son aproximadas; los días acumulados desde el 17-11 sí son de estación.

Pendiente fuera del alcance de D2: contrastar con INIA y DGA (sin acceso), y correr `d2_clima_dmc_diario.py` cada 3 días hasta la demo.
