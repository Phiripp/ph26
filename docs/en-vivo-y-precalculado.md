# Qué se calcula en vivo y qué viene calculado

Nov 21, 2026 · @Tomas

Caudal tiene dos partes: una cadena de scripts que se corre por lotes y deja sus resultados en `data/processed/`, y una página con una API que leen esos resultados. Nada de lo que muestra la página está simulado ni escrito a mano: cada cifra sale de un archivo que genera un script del repo.

## En vivo

| Qué | Cómo | Dónde |
| --- | --- | --- |
| Expediente PDF | Se arma en el servidor al pedirlo: lee los datos del predio, baja las imágenes satelitales de esa fecha y dibuja el PDF. Tarda unos 20 segundos | [api/expedientes.py](../api/expedientes.py), [scripts/models/expediente.py](../scripts/models/expediente.py) |
| Texto de "por qué está en alerta" | Se redacta en cada consulta a partir de las filas del predio. No guarda frases | [scripts/models/explicacion.py](../scripts/models/explicacion.py) |
| Ranking, ficha, serie, casos | Consultas de DuckDB sobre los Parquet, en cada solicitud | [api/datos.py](../api/datos.py) |

Dos matices del expediente:

- Si ya existe uno con los mismos insumos, la API devuelve ese y lo dice (`reutilizado: true`, con su fecha). Los del caso y del candidato de [data/demo.json](../data/demo.json) se generan al construir la imagen.
- Si la API no responde, la página abre un PDF guardado y muestra su fecha.

## Calculado antes

| Qué | Script | Salida | Dónde corre |
| --- | --- | --- | --- |
| Series Sentinel-2 por predio | `scripts/extract/serie_sentinel2.py` | `serie_predio_*.parquet` | GCP |
| Clima y ventanas sin lluvia | `scripts/extract/d2_clima_*.py`, `scripts/models/ventana_seca.py` | `clima.parquet`, `ventana_seca.parquet` | Local |
| Anomalías frente al secano | `scripts/models/anomalias.py` | `anomalias_predio_*.parquet` | Local |
| Señal de riego | `scripts/models/detector_riego.py` | `senal_riego_*.parquet` | Local |
| Consumo FAO-56 | `scripts/models/consumo_fao56.py` | `consumo_predio_*.parquet` | Local |
| Índice de sospecha | `scripts/models/indice_sospecha.py` | `puntaje.parquet` | Local |
| Puntos a revisar | `scripts/extract/poi_predio.py` | `poi.parquet` | GCP |
| Ruta de inspección | `scripts/models/ruta_inspeccion.py` | `ruta_z1.*`, `ruta_z2.*` | Local, con OSRM |
| Validación, calibración, impacto | `validacion.py`, `calibracion.py`, `impacto.py` | `docs/validacion.md`, `docs/calibracion.md`, `impacto.json` | Local |

- El ranking es de la temporada 2025-26. La última imagen usada es del 28 de marzo de 2026. La API informa ambas fechas en cada respuesta (`dato_al`, `calculado`) y en `/api/health`.
- La ruta no se calcula en la demo: el servidor público de OSRM a veces tarda minutos. Se guarda el resultado.
- La página carga una exportación de esos archivos (`frontend-demo/scripts/build_m5_web.py`) y pide el expediente a la API.

## Lo que no hace

- No recalcula las series satelitales al abrir un predio.
- No envía la denuncia: el expediente queda listo para que una persona lo presente con su Clave Única.
- No afirma infracciones. Entrega indicios y rangos; la infracción la constata un inspector.

## Cómo se reproduce

El orden de la cadena. El comando exacto de cada script está en su encabezado y en [data/README.md](../data/README.md).

1. Predios, derechos, fiscalizaciones, cultivos, cauces y canales: `scripts/extract/` (`predios_ciren.py` primero; `predio.parquet` no está en git porque la capa de CIREN no se redistribuye).
2. Clima y ventanas sin lluvia: `d2_clima_*.py` y `ventana_seca.py`.
3. Series satelitales de los predios y del secano de referencia: `serie_sentinel2.py`.
4. Modelos, en este orden: `anomalias.py`, `detector_riego.py`, `consumo_fao56.py`, `indice_sospecha.py`.
5. Validación y calibración: `validacion.py`, `calibracion.py`. Después `impacto.py`, `ruta_inspeccion.py` y `poi_predio.py`.
6. Página y API: `frontend-demo/scripts/build_m5_web.py`, `api/respaldo.py` y `scripts/cloud/api/desplegar.sh`.
