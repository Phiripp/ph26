# Caudal — Fiscalizador hídrico satelital

Nov 20, 2026 · @Tomas

## Resumen

Caudal detecta extracción ilegal de agua desde el satélite: estima cuántos m³ consume cada predio, lo cruza con sus derechos de agua y genera un expediente de fiscalización en minutos.

- **Track:** Physical World (datos del mundo real, producto con impacto).
- **Mentor:** Nicolás Orellana, product manager de Copec Wind Garage.
- **Caso de demo:** un valle real con sequía, por ejemplo Petorca o La Ligua (por confirmar en las primeras 2 horas).
- **Tiempo:** 36 horas.

## Problema y contexto

En zonas con sequía hay comunidades abastecidas por camiones aljibe mientras predios cercanos riegan cultivos verdes, a veces sin derechos de agua suficientes. Fiscalizar eso hoy es lento y depende de denuncias.

- **La DGA ya usa satélite:** procesa imágenes para estimar la vegetación de un predio y cruzarla con los derechos que necesitarían esos cultivos ([MOP](https://www.mop.gob.cl/ministerio-de-obras-publicas-da-a-conocer-plan-de-fiscalizacion-para-detectar-extraccion-ilegal-de-agua/)).
- **Pero es lento:** en un informe de la Cámara, según la DGA, el proceso demora alrededor de ocho meses ([informe](https://www.camara.cl/verDoc.aspx?prmID=6460&prmTipo=INFORME_COMISION)).
- **Las sanciones son relevantes:** en Hijuelas la DGA multó con más de 127 millones de pesos a un empresario agrícola por dos pozos sin derechos ([DGA](https://dga.mop.gob.cl/dga-valparaiso-multa-a-empresario-agricola-por-extraccion-no-autorizada-de-aguas-en-la-comuna-de-hijuelas/)).
- **El vecino afectado no tiene herramienta:** no puede pedir que revisen un predio ni ver la evidencia.

## Solución y cómo funciona

Un pipeline lineal de seis pasos convierte imágenes satelitales en un ranking de predios sospechosos y un expediente por predio.

1. **Zona y predios:** un valle acotado y los polígonos de sus predios (oficiales si se consiguen; dibujados a mano para la demo si no).
2. **Vegetación y agua:** NDVI mensual (vegetación) y NDWI (agua, para tranques nuevos) con Sentinel-2 L2A, serie por predio.
3. **Consumo estimado (FAO-56):** coeficiente de cultivo estimado desde el NDVI × evapotranspiración de referencia, menos la lluvia efectiva, multiplicado por el área.
4. **Cruce con derechos:** consumo estimado contra los derechos de agua registrados en la DGA para ese predio o titular.
5. **Ranking:** índice de sospecha = exceso de consumo sobre derechos, ponderado por confianza (nubes, tamaño del predio).
6. **Expediente con agente:** imágenes antes/después, serie de NDVI, cálculo de m³, derechos consultados y borrador de denuncia, en PDF.

```latex
V_{\text{riego}} = \sum_{\text{mes}} \max\big(0,\; K_c(\text{NDVI}) \cdot ET_0 - P_{\text{ef}}\big) \cdot A
```

Donde K\_c se estima linealmente desde el NDVI, ET\_0 viene de Open-Meteo, P\_ef es la lluvia efectiva y A el área del predio. El sistema no acusa: prioriza la fiscalización y deja la evidencia trazable.

## Diferencial

La técnica base es conocida; el diferencial es velocidad, cuantificación en m³, expediente automático y acceso ciudadano.

|  | DGA (fiscalización satelital) | Labkence (NASA Space Apps 2024) | Caudal |
| --- | --- | --- | --- |
| Usuario | Fiscalizadores del Estado | Agricultor | Comunidad, APR, juntas de vigilancia, DGA |
| Salida | Proceso interno | Uso de agua del propio cultivo | Ranking + expediente con evidencia |
| Tiempo | Meses | — | Minutos |
| Métrica | Vegetación vs. derechos | Evapotranspiración (Landsat 9) | m³ estimados vs. derechos |
| Acceso | Cerrado | Agricultor | Abierto a quien pida revisar un predio |

Respuesta lista a "la DGA ya lo hace": sí, pero tarda meses, no cuantifica para el ciudadano y no es accesible para la comunidad afectada. Fuente Labkence: [FCFM U. de Chile](https://ingenieria.uchile.cl/noticias/224098/nasa-space-apps-challenge-2024).

## Fuentes de datos

Todo es público o abierto; tres verificaciones definen si la zona elegida sirve y deben cerrarse en las primeras 2 horas.

| Dato | Fuente | Uso | Verificar |
| --- | --- | --- | --- |
| Imágenes multiespectrales 10 m | Sentinel-2 L2A vía STAC (Earth Search en AWS o Planetary Computer) | NDVI, NDWI, antes/después | Escenas sin nubes en la zona y fechas |
| Evapotranspiración de referencia y lluvia | Open-Meteo (histórico) | ET0 y lluvia efectiva | Cobertura histórica de la zona |
| Derechos de agua | Registro de derechos de la DGA | Cruce consumo vs. derecho | Que se pueda descargar la zona y vincular a predios o titulares |
| Límites de predios | Fuente catastral oficial, o polígonos dibujados | Unidad de análisis | Disponibilidad; si no, dibujar 10–20 predios para la demo |
| Contexto | Prensa y sanciones de la DGA | Pitch y validación | Un caso sancionado en la zona para validar el modelo |

- [ ] Elegir la zona y confirmar escenas sin nubes
- [ ] Descargar derechos de agua de la zona
- [ ] Conseguir o dibujar los polígonos de predios
- [ ] Buscar un caso sancionado para validar (el modelo debería marcarlo)

## Alcance del MVP y stack

El MVP es un valle, un ranking y un expediente generado en vivo; todo lo demás es opcional.

| Componente | Indispensable | Opcional si sobra tiempo |
| --- | --- | --- |
| Datos satelitales | NDVI/NDWI mensual por predio, 2–3 años | Detección automática de tranques nuevos |
| Modelo hídrico | FAO-56 simplificado, m³ por predio | Calibración con un caso sancionado |
| Cruce | Consumo vs. derechos, índice de sospecha | Incertidumbre por predio |
| Agente | Expediente PDF con evidencia y borrador de denuncia | "Revisa este predio" por WhatsApp |
| Frontend | Mapa, ranking y ficha por predio | Timelapse antes/después |
| Segundo caso | — | Loteos brujos o áridos con la misma arquitectura |

**Stack sugerido:** Python con `pystac-client`, `stackstac` o `rioxarray` y `geopandas` para los datos; precalcular las series en Parquet o GeoJSON; backend liviano (FastAPI); frontend con mapa (Leaflet o MapLibre); LLM para el expediente; despliegue en producción desde temprano, porque la demo se presenta en producción.

**Regla clave:** precalcular todo lo satelital; la demo en vivo solo consulta resultados y genera el expediente.

## Equipo y plan

Cuatro frentes en paralelo desde la hora 2; los nombres se asignan en la primera reunión.

| Frente | Responsable | Entrega |
| --- | --- | --- |
| Datos satelitales | Por definir | Series NDVI/NDWI por predio precalculadas |
| Modelo hídrico y cruce | Por definir | m³ por predio, índice de sospecha, ranking |
| Agente y expediente | Por definir | PDF con evidencia y borrador de denuncia |
| Frontend, demo y pitch | Por definir | Mapa, ficha, guion y slides |

1. **Horas 0–2:** elegir zona, verificar escenas, derechos y predios; validar cliente con el mentor.
2. **Horas 2–12:** pipeline de datos de punta a punta con datos reales, aunque sea feo.
3. **Horas 12–20:** modelo hídrico, ranking y primer expediente; frontend conectado.
4. **Horas 20–28:** pulir resultados, validar con un caso sancionado, desplegar en producción.
5. **Horas 28–34:** demo congelada, guion, ensayo del pitch y video de respaldo.
6. **Horas 34–36:** solo arreglos menores; nada nuevo.

## Demo, rúbrica y riesgos

La demo cierra con un dato duro: "este predio consumió X m³ y tiene derechos por Y", y un expediente generado frente al jurado.

**Guion de demo (3 min):**

1. El problema en una frase y una imagen: camión aljibe frente a un predio verde.
2. El mapa del valle con el ranking de predios sospechosos.
3. Timelapse antes/después de un predio: cómo aparece el verde y el tranque.
4. Los m³ estimados frente a los derechos.
5. Botón "generar expediente" en vivo.
6. Cierre: de meses a minutos, con datos públicos.

**Rúbrica** (según pesos publicados por un equipo del tour 2026, no oficial): Técnico 25%, Ejecución 20%, Ambición 20%, Impacto 20%, Originalidad 15%. Mostrar el modelo FAO-56 y la validación con un caso real suma en Técnico.

| Riesgo | Mitigación |
| --- | --- |
| Derechos de la DGA no vinculables a predios | Cruzar por titular o usar un subconjunto verificado a mano |
| Nubes o escenas faltantes | Cambiar de zona temprano; usar composiciones mensuales |
| Falsos positivos que acusen a inocentes | El sistema prioriza, no acusa; mostrar la confianza por predio |
| Modelo hídrico impreciso | Vender orden de magnitud y ranking relativo, no m³ exactos |
| Falla en vivo | Demo en producción desde temprano y video de respaldo |

## Preguntas para el mentor y decisiones abiertas

Cuatro decisiones bloquean el trabajo y deben cerrarse antes de la hora 2.

- [ ] ¿Quién paga: DGA, juntas de vigilancia, comités APR o agroindustria (cumplimiento)?
- [ ] ¿Qué impacta más en la demo: el mapa con ranking o el expediente en vivo?
- [ ] ¿Qué dato duro esperaría ver el jurado?
- [ ] ¿Cómo manejar el riesgo de falsos positivos en el pitch?
- [ ] Zona final del caso de demo
- [ ] Nombre del producto ("Caudal" es provisorio)
- [ ] ¿Sumar un segundo caso (loteos brujos o áridos) o enfocarse solo en agua?
