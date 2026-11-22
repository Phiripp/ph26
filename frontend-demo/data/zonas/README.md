# Datos por zona — exportación de M5 al frontend

> **Caudal prioriza, no acusa.** Predios por ID CIREN; sin nombres de dueños. Consumo y exceso siempre en rango.
> Solo los casos con multa se llaman "sancionados".

Generado por `scripts/build_m5_web.py` desde `data/processed/` (ver [docs/spec-demo.md](../../../docs/spec-demo.md),
"Datos: exportación de M5 al frontend"). Todas las cifras salen de los modelos del repo (M3 a M10).
`scripts/build_zonas_web.py --check` verifica lo exportado (sin red ni dependencias).

```bash
uv run scripts/extract/predios_ciren.py            # desde la raíz, una vez: predio.parquet (no va a git)
uv run frontend-demo/scripts/build_m5_web.py       # unos 90 s
python3 frontend-demo/scripts/build_zonas_web.py --check
```

Al cambiar los datos, subir `VERSION` en `sw.js`.

## Qué predios se exportan

Por zona: todos los de banda alta y media de 2025-26 (Z1: 788; Z2: 827), los predios de los 10 casos y de los
vecindarios de validación (`puntaje_validacion.parquet`) y las paradas de la ruta. Z1: 858 polígonos de 4.272
analizados; Z2: 878 de 3.639. El resto (banda baja y sin alerta) va solo como conteo en `resumen.json`.

## Archivos

| Archivo | Contenido | Origen |
| --- | --- | --- |
| `resumen.json` | `total` (7.911), por zona: predios analizados, exportados, conteo por banda y resumen de la ruta; bloque `impacto`; serie del caso demo de la portada | `puntaje.parquet`, `ruta_z*.json`, `impacto.json` |
| `impacto.json` | `impacto.json` de M9 + bloque `pitch` con las cifras de F6 y su fuente (lift 2,6 fijo, personas y latas del candidato `5301984`, candidatos, Torres Costanera, años de capacidad) | `impacto.json`, `puntaje.parquet`, `fiscalizacion.parquet` |
| `casos.json` | Los 10 casos + `detectable`, `banda_previa`, `primera_alerta`, `anos_adelanto`, `temporadas_en_alta`, `censurado`, `m3_antes_inspeccion` {min, central} | `impacto.py` (`adelanto`) sobre `validacion.casos()` |
| `{z}/predios.geojson` | Polígono simplificado a 5 m, `predio_id`, `rol` (solo en los predios con un caso sancionado; en el resto va vacío), comuna, `area_ha`, especie (`cultivo`), derechos del predio y del entorno, `caso`, `exportado_por` | `predio.parquet`, `predio_cultivo.parquet`, `puntaje.parquet` |
| `{z}/scores.lite.json` | `rank`, `banda`, `puntaje`, `confianza`, `motivos`, `frac_senal`, `n_fechas`, `consumo_m3`, `derecho_m3`, `derecho_ajeno_m3`, `exceso_m3`, `estado_derechos`, `canal_m`, `fiscalizado_500m` | `puntaje.parquet`; `fiscalizado_500m` como `impacto.py` |
| `{z}/series/` | `index.json` (eje `fechas`, bloques, secano de la zona) y `bNN.json`: por predio `i` (posiciones en el eje) y `ndvi`, `ndmi`, `ref_ndvi`, `ref_ndmi`, `en_ventana_seca`, `senal` | `anomalias_predio_elegibles_2025-26.parquet`; casos y vecindarios: `anomalias_predio_validacion.parquet` (7 temporadas) |
| `{z}/historial.json` | Predios de los casos: por temporada `banda`, `puntaje`, `confianza`, `m3_exceso_min/central/max` | `puntaje_validacion.parquet` |
| `{z}/poi.json` | Hasta 8 POI por predio: `tipo`, `lon`, `lat`, `razon`, `confianza` | `poi.parquet` |
| `{z}/ruta.json`, `ruta.gpx`, `ruta.geojson` | Ruta de M8 sin cambios de formato | `ruta_z*.*` |
| `{z}/clima.json`, `fiscalizaciones.geojson`, `bbox.json` | Ventanas secas, fiscalizaciones y escenas (sin cambios) | `build_zonas_data.py` |

`en_ventana_seca`: la fecha cae en una ventana seca de M1 de la celda del predio con 10 días o más sin lluvia
(`detector_riego.en_ventana`). `senal`: además despejada y con z_verdor ≥ 2,5 y z_humedad ≥ 1,5 (umbrales de M7).

Un predio cae en el bloque de series `hash(id) % bloques` (mismo hash en `js/zona-data.js`).
