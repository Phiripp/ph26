# Caudal — Spec de flujos por polígono

Nov 21, 2026 · complementa `docs/spec-v2.md`

## Alcance

Cuando se elige un polígono (predio) en el mapa, se ejecutan dos flujos en paralelo sobre el mismo contexto de análisis. Cada flujo tiene una salida concreta:

| Flujo | Salida | Quién la usa |
| --- | --- | --- |
| A. Recorrido | Ruta de visita del supervisor (GPX, enlace de navegación) y, opcional, plan de vuelo del dron | Supervisor DGA u operador de dron |
| B. Informe | Expediente PDF con los campos de la *Guía para la presentación de denuncias por infracciones al Código de Aguas* (jul 2025) | Persona denunciante, que revisa, firma y presenta |

Principio heredado de v2: el sistema prioriza, no acusa. Ningún flujo presenta una denuncia ni afirma una infracción; los m³ son un indicio en banda.

## Contexto compartido (paso 0)

Se ejecuta una vez al elegir el polígono y lo consumen ambos flujos. Todo sale de datos precalculados; la selección solo consulta.

Entrada: `predio_id` (o polígono dibujado), punto de partida del supervisor, fecha de corte.

Salida, el **paquete de contexto**:

| Campo | Fuente |
| --- | --- |
| Geometría, área (ha), centroide, bbox | predio |
| Provincia, comuna, sector | cruce espacial con división político-administrativa (por verificar la capa) |
| Cauce natural o artificial cercano y distancia | capa hidrográfica DGA (por verificar disponibilidad) |
| Derechos registrados (normalizados a m³/mes) | derecho |
| Serie NDVI, NDMI, NDWI, nubosidad por fecha | serie_predio |
| Ventana(s) seca(s) detectadas | estaciones para lluvia; Open-Meteo solo para ET0 (ver `pruebas-acceso-datos.md`: la grilla sobreestima la lluvia ~2×) |
| Puntaje: banda, índice, rango m³ estimado vs. derechos, confianza | puntaje |
| Hallazgos espaciales (zonas húmedas o verdes fuera de patrón, posibles tranques por NDWI) | análisis intra-predio, ver flujo A |

Si falta un dato crítico (sin referencia, sin escenas válidas, sin derechos vinculados), el contexto lo marca con `confianza = baja` y el flujo B lo declara en el informe en vez de ocultarlo.

## Flujo A — Recorrido del supervisor y del dron

Objetivo: que quien llegue al predio vaya directo a lo que hay que verificar, no a recorrerlo entero.

### A1. Puntos de interés (POI)

Se extraen del contexto, en este orden de prioridad:

1. Zonas con anomalía de humedad y verdor en ventana seca (celdas contiguas sobre umbral).
2. Cuerpos de agua nuevos o crecientes (NDWI), candidatos a tranque.
3. Punto del cauce más cercano al predio (posible bocatoma).
4. Accesos al predio (cruce del polígono con red vial, por verificar fuente: OSM).

Cada POI lleva: coordenada, tipo, razón (qué señal lo generó), fecha de la imagen y confianza. Máximo ~8 POI para que la visita sea acotada.

### A2. Ruta terrestre del supervisor

- Entrada: punto de partida, hora de inicio, POI del predio.
- Proceso: ruta por red vial hasta el punto de acceso, luego orden de visita de los POI que minimiza el recorrido (OR-Tools, con tramo a pie dentro del predio como línea recta o sendero si hay dato).
- Salida: lista ordenada con tiempo estimado, mapa, GPX y enlace de navegación al punto de acceso.
- Cada parada trae una **ficha de verificación**: qué mirar (¿hay riego activo?, ¿tranque con agua?, ¿bocatoma o bomba?), qué foto tomar (con GPS y hora) y qué anotar.
- Cuando el supervisor va a varios predios, se encadena con la ruta multipredio de v2 (`GET /ruta`); este flujo es el detalle de una parada.

### A3. Plan de vuelo del dron (opcional, solo con dron y operador)

- Entrada: polígono, POI, parámetros del dron (altura, traslape, cámara).
- Proceso: patrón de barrido (franjas paralelas) sobre el polígono con un buffer, más órbitas o pasadas bajas sobre los POI de tipo tranque y bocatoma.
- Parámetros por defecto: altura ≤ 120 m sobre el suelo, traslape frontal 75 % y lateral 65 %; se ajustan a la cámara. Debe verificarse la normativa DGAC vigente (altura, línea de vista, zonas restringidas) antes de usarlo; el sistema no valida permisos.
- Salida: archivo de misión (KML o waypoints en formato genérico, formato por definir según el dron), tiempo y baterías estimadas, y advertencia visible si el polígono cae cerca de zonas restringidas.
- Sin hardware: se omite y la salida del flujo A es solo A2.

### A4. Retorno de campo (opcional)

El supervisor sube fotos y observaciones por POI (coordenada, hora, nota). Alimenta el flujo B como adjunto y como evidencia de contacto en terreno. Sin retorno, el informe se entrega como pre-visita.

### Criterios de aceptación del flujo A

- Dado un polígono y un punto de partida, devuelve en pocos segundos una ruta ordenada con GPX descargable.
- Cada POI explica qué señal lo generó; ninguno aparece sin razón.
- Si no hay POI (sin señal de riego), devuelve solo la ruta al acceso y lo dice.
- El plan de vuelo nunca se genera por defecto; requiere indicar que hay dron.

## Flujo B — Informe final (expediente)

Objetivo: dejar al denunciante con un borrador casi listo para el trámite, respetando que la admisibilidad exige un interesado y su afectación.

### B1. Mapeo a la guía de la DGA

| Sección del informe (campo de la guía) | Contenido | Estado | Quién completa |
| --- | --- | --- | --- |
| 1. Denunciante: nombre o razón social, RUN o RUT, dirección (comuna y región), correo o teléfono, copia de cédula | Campos vacíos con instrucciones | Vacío | Persona, con Clave Única |
| 2. Representante legal o apoderado, si corresponde | Campos vacíos | Vacío | Persona |
| 3. Ubicación y referencias: provincia, comuna, sector, nombre del cauce, croquis | Del contexto: división administrativa, cauce cercano y distancia, mapa con polígono y coordenadas, POI marcados como croquis | Pre-llenado | Caudal pre-llena, la persona revisa |
| 4. Descripción breve de hechos y fecha | Borrador: ventana seca, señales observadas (verdor y humedad sobre referencia), fechas de las imágenes, estimación de consumo vs. derechos en banda | Borrador | Caudal redacta, la persona edita |
| 5. Afectación o perjuicio del denunciante (requisito de admisibilidad, sección 3.1) | Recuadro con preguntas guía: ¿qué derecho o fuente se ve afectada?, ¿desde cuándo?, ¿cómo? | Vacío | Solo la persona |
| 6. Adjuntos: fotografías, croquis, respaldos | Anexo técnico generado (ver B2) y, si hubo retorno de campo, fotos y notas | Generado | Caudal genera, la persona decide qué adjuntar |
| 7. Declaración y firma | Texto de cierre, sin firma | Vacío | Persona |

La sección 5 se agrega por la regla de admisibilidad de la guía: la DGA declara admisible la denuncia cuando la presenta un interesado que expone el daño o la afectación a sus derechos o a los de terceros. Caudal no la redacta por la persona.

### B2. Anexo técnico (adjunto generado)

- Mapa del predio con polígono, POI y cauce cercano.
- Series NDVI y NDMI con la ventana seca marcada y la referencia usada.
- Imágenes antes y después (fechas y escena de origen).
- Estimación de consumo en rango, derechos consultados y su fuente, supuestos del modelo (FAO-56 simplificado).
- Calidad: confianza, nubosidad, escenas válidas, limitaciones conocidas.
- Si hubo retorno de campo: fotos con coordenada y hora, y notas del supervisor.

### B3. Lenguaje y límites

- Redacción en términos de "eventual infracción" e "indicios", igual que la guía; nunca "se cometió" ni "robo de agua".
- Los m³ siempre en rango, con confianza y advertencia de que no son prueba.
- Banner fijo: el informe no es una denuncia presentada; la presenta una persona.
- Última sección: instrucciones de presentación, con las dos vías de la guía: Oficina Virtual (snia.mop.gob.cl, Clave Única, opción "Denuncias por infracciones al Código de Aguas") o presencial con el formulario firmado (Anexo 1) en la oficina de partes de la dirección regional correspondiente.
- Se anota que, si faltan documentos legales en forma, la DGA da 5 días hábiles para subsanar (sección 3.1), para que la persona sepa qué preparar.

### B4. Formato y trazabilidad

- Salida: PDF generado desde plantilla, descargable; registro en `expediente` (id, predio_id, url_pdf, fecha_creación) con el hash o versión del puntaje usado.
- Versión "pre-visita" (sin retorno de campo) y "post-visita" (con él); se regenera al subir datos de campo.

### Criterios de aceptación del flujo B

- El PDF contiene las siete secciones, con las no automatizables claramente vacías y marcadas.
- Todo dato pre-llenado indica su origen y fecha.
- Un predio con confianza baja produce un informe que lo declara en la primera página.
- Nada en el documento afirma una infracción confirmada.

## Orquestación

```
elegir polígono
   └─ paso 0: paquete de contexto (consulta, precalculado)
        ├─ A: POI → ruta supervisor → (dron opcional) → [retorno de campo]
        └─ B: mapeo a la guía → anexo técnico → PDF
                                       ▲
                      [retorno de campo, si existe]
```

- A y B corren en paralelo; B solo depende de A para los POI (croquis) y el retorno de campo, y funciona sin ellos.
- Endpoints sugeridos (extienden los de v2): `GET /predios/{id}/contexto`, `GET /predios/{id}/recorrido?inicio=lat,lon&dron=false`, `POST /expediente/{id}` (ya existe), `POST /predios/{id}/retorno`.
- Presupuesto de latencia en la demo: contexto < 2 s (precalculado); ruta < 5 s; PDF < 10 s. Si algo falla, se sirve el último resultado cacheado.

## Qué se comparte entre flujos y qué no

| Dato | A | B |
| --- | --- | --- |
| POI | Genera | Usa como croquis |
| Estimación de m³ y banda | Prioriza POI | Describe hechos |
| Fotos de campo | Recibe | Adjunta |
| Datos del denunciante | No usa | Deja vacíos |

## Preguntas abiertas

- [ ] ¿Hay dron y operador? Define si A3 entra.
- [ ] ¿Qué capa de cauces de la DGA se puede descargar para B1.3 y para el POI de bocatoma?
- [ ] ¿Fuente de red vial para la ruta (OSM) y de accesos al predio?
- [ ] ¿Quién es el usuario del informe en la demo: un interesado afectado, o un fiscalizador de la DGA? Cambia la sección 5 (en un caso de oficio, la DGA puede fiscalizar sin denunciante).
- [ ] Formato de misión del dron.
- [ ] Alcance del retorno de campo (A4): ¿entra en el MVP o se muestra solo en el diagrama?
