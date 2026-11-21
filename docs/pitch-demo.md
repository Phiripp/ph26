# Caudal — Pitch y demo de 3 minutos

Nov 21, 2026 · @Tomas

Este documento define qué decimos y qué mostramos en los 3 minutos de la final. Lo que hay que construir para mostrarlo está en [spec-demo.md](spec-demo.md). Las cifras salen de [impacto.md](impacto.md) y [validacion.md](validacion.md); si se regeneran, hay que actualizar el guion.

## Reglas del formato

| Regla | Valor | Fuente |
| --- | --- | --- |
| Duración | 3 minutos | Organización |
| Demo mínima | 1 minuto 30 segundos | Organización |
| Corte duro a los 3:00 y 2 minutos de preguntas | Probable | Notas de otros equipos sobre las finales del tour; sin confirmar para Santiago |
| El reloj parte con la primera palabra | Probable | Mismas notas |
| El jurado lee el repo y castiga las demos simuladas | Probable | Mismas notas |

No encontramos una rúbrica oficial. Hay que confirmar tiempo y criterios en la charla del sábado a las 20:00 ("cómo dar una buena demo").

Consecuencias para nosotros:

- El guion tiene 430 palabras como máximo (unas 150 por minuto).
- Todo lo que se muestra corre en producción con datos reales. Nada de botones simulados.
- Una persona habla y otra maneja el computador.

## Mensaje

**Caudal le dice a la DGA qué predios inspeccionar mañana.** Usa satélite, clima y el registro público de derechos de agua, y entrega una ruta de inspección y un expediente listo para presentar.

Tres ideas que el jurado debe recordar:

1. **Funciona con un caso real.** Caudal marca dos años antes un predio que la DGA multó con $127 millones.
2. **Termina en una acción física.** La salida es una ruta para un inspector y un expediente con el formato de la DGA.
3. **Está validado y no exagera.** Se probó contra las fiscalizaciones reales de la DGA y todo va en rango.

## Guion

La demo ocupa 1:45 de los 3:00. Toda la demo ocurre en una sola zona (Aconcagua bajo, comuna de Hijuelas) para no gastar tiempo en vuelos entre zonas.

| Tiempo | Qué se dice | Qué se ve |
| --- | --- | --- |
| 0:00–0:20 | Gancho | Portada: mapa de Chile con las dos zonas |
| 0:20–0:35 | Qué es Caudal | Vuelo a la zona; aparecen los predios por banda |
| 0:35–1:05 | Demo 1: el caso real | Ficha del caso FO-0504-95: serie y antes/después |
| 1:05–1:45 | Demo 2: un candidato de hoy y su expediente | Ficha del candidato; se genera el PDF en vivo |
| 1:45–2:20 | Demo 3: la ruta de mañana | Pestaña Ruta: paradas, horas y botón de navegación |
| 2:20–2:50 | Validación e impacto | Panel de impacto con 4 cifras |
| 2:50–3:00 | Cierre | Logo, URL y equipo |

### Texto

**0:00 Gancho.**
"Entre enero y marzo de este año, la provincia de Petorca gastó 176 millones de pesos en camiones aljibe para darle agua a su gente. En el mismo valle hay huertos verdes en pleno verano que riegan sin derechos de agua. La DGA tiene que encontrarlos entre miles de predios, y hoy acierta en una de cada tres fiscalizaciones."

**0:20 Qué es.**
"Caudal le dice a la DGA qué predios inspeccionar primero. Mira cada predio con Sentinel-2 cada cinco días. Si no ha llovido en diez días y el predio sigue más verde y más húmedo que el cerro de al lado, alguien lo está regando. Después compara el agua que consume con los derechos inscritos. Analizamos 7.911 predios en Petorca y Aconcagua."

**0:35 Demo 1, el caso real.**
"Esto es Hijuelas. En noviembre de 2021 la DGA multó este predio de paltos con 127 millones de pesos por sacar agua sin derechos. Esta es su serie satelital. La línea gris es el cerro seco; la verde es el predio. Caudal lo pone en alerta alta desde el verano de 2019, dos años antes de la inspección. En ese tiempo sacó unos 140 mil metros cúbicos sin derecho."

**1:05 Demo 2, un candidato de hoy.**
"Ahora, el verano pasado. Este predio está en la misma comuna: 19 hectáreas de palto, verde en todas las imágenes de la temporada seca. No tiene derechos inscritos a 500 metros, no tiene un canal a un kilómetro y la DGA nunca ha fiscalizado aquí. Consume entre 105 y 280 mil metros cúbicos al año. Caudal no acusa: prioriza. Con un clic genera el expediente, con los campos de la guía oficial de denuncias de la DGA: ubicación, hechos, imágenes y anexo técnico. Se genera ahora, en producción."

**1:45 Demo 3, la ruta.**
"Y esta es la decisión que importa: a dónde va el inspector mañana. Caudal arma la ruta del día: doce predios, ocho horas, 91 kilómetros, saliendo de la plaza de Quillota. Se abre en Google Maps o se baja al GPS. Dentro de cada predio marca dónde mirar: el parche regado, el tranque, el pozo."

**2:20 Validación e impacto.**
"Lo validamos contra las fiscalizaciones reales de la DGA. Entre los predios que Caudal pone en alerta alta hay 2,6 veces más infractores que eligiendo al azar. Hoy hay 501 predios en alerta alta que nunca han sido fiscalizados. Con el acierto actual de la DGA, son entre 39 y 153 casos y hasta 9 millones de metros cúbicos al año: el agua de 250 mil personas. Al ritmo actual, la DGA tardaría 14 años en revisarlos. Con Caudal, parte mañana por los primeros doce."

**2:50 Cierre.**
"Caudal usa solo datos públicos y sirve para cualquier valle de Chile. Somos Nicolás, Felipe, Gabriela y Tomás. Gracias."

El texto tiene unas 420 palabras.

## Cifras del guion y su respaldo

| Cifra | Valor | Fuente | Advertencia |
| --- | --- | --- | --- |
| Gasto en camiones aljibe | $176,4 millones por 41.201 m³, ene–mar 2026 | Mercado Público, Delegación de Petorca ([spec-v2.md](spec-v2.md#métricas-de-impacto)) | Es Petorca; la demo es en Aconcagua. El gancho habla del problema, no de la zona de la demo |
| Acierto de la DGA | 33 % (107 fiscalizaciones por extracción, 2022–2025) | `impacto.md` | Solo Z1 y Z2 |
| Predios analizados | 7.911 | `puntaje.parquet` | Predios con rol válido y 1 ha o más |
| Multa del caso base | 1.983,9 UTM, unos $127 millones | Planilla de la DGA y nota de prensa de la DGA | — |
| Adelanto en el caso base | Al menos 2 años | `impacto.md` | La serie parte en 2019-20: es una cota inferior |
| Agua del caso base antes de la inspección | Unos 140.000 m³ (valor central) | `impacto.md` | Estimación FAO-56; decir "unos" |
| Candidato de hoy | 18,8 ha, 89 % palto, 105.000–280.000 m³/año, sin derechos a 500 m, canal a 1,2 km | `puntaje.parquet`, predio `5301984` | No mostrar rol ni dueño |
| Ruta | 12 predios, 8 horas, 91 km | `ruta_z2.json` | Cambia si se regenera la ruta (ver spec, tarea T4) |
| Lift en alerta alta | 2,6 veces (IC 95 %: 1,3–4,4) | `validacion.md` | Usar 2,6 y no 3,7: el 3,7 se midió con los mismos casos que calibraron los umbrales |
| Candidatos sin fiscalizar | 501 | `impacto.md` | Sin fiscalización a 500 m desde 2018 |
| Casos esperados | 39 a 153 | `impacto.md` | Conservador a central; central usa el 33 % de la DGA |
| Agua en juego | 2,1 a 9,3 millones de m³/año | `impacto.md` | Sin predios de más de 100 ha |
| Personas | 34.000 a 256.000 | `impacto.md` | Dotación de 36,5 a 62 m³ por persona al año |
| Años al ritmo de la DGA | 14 | `impacto.md` | 467 candidatos entre 33 fiscalizaciones por año |

## Decisiones

| Decisión | Elegido | Alternativa | Por qué |
| --- | --- | --- | --- |
| Zona de la demo | Z2, Hijuelas | Z1, Cabildo: caso FD-0501-181 y candidato `5344181` (31 ha de palto) | El caso FO-0504-95 es el más sólido (la DGA dijo que lo detectó con satélite y el verdor baja después de la multa). El candidato está en la misma comuna, así que la demo no cambia de zona |
| Candidato en vivo (D19) | Predio `5301984` | `5344181` (Cabildo), `5345478` (Cabildo, 7 ha de nogal) | Señal en el 100 % de las fechas, sin derechos a 500 m, sin canal a 1 km, sin fiscalización a 500 m, 89 % de la superficie con frutales |
| Cifra de validación | 2,6 veces | 3,7 veces | Es la cifra sin sesgo de calibración; aguanta una pregunta del jurado |
| Cómo se muestra el candidato | Por ID interno, sin rol ni dueño, con la palabra "candidato" | No mostrar ningún predio no multado | El expediente y la ruta necesitan un predio concreto. El equipo debe confirmar esta decisión (ver abajo) |

**Por confirmar con el equipo:** la convención era mostrar a los candidatos solo agregados. La demo en vivo necesita un predio concreto que no ha sido multado, y la ruta ya muestra ubicaciones. La propuesta es mostrarlo sin rol ni dueño y decir en voz alta que Caudal prioriza y no acusa. Si el equipo no está de acuerdo, el expediente en vivo se genera para el caso FO-0504-95 y el paso "candidato de hoy" muestra solo el ranking agregado.

## Preguntas probables del jurado

| Pregunta | Respuesta corta |
| --- | --- |
| ¿Cuántos falsos positivos tiene? | Entre los fiscalizados en alerta alta, 7 de 15 tuvieron infracción (47 %; la DGA tiene 33 %). Son pocos casos y lo decimos. Por eso Caudal prioriza y entrega rangos; la infracción la constata el inspector |
| ¿Cómo saben que es agua ilegal y no de un canal? | No lo sabemos con certeza. El agua de canal no está en el registro de derechos. Por eso el escenario conservador excluye a todo predio con un canal a 300 m, y la ficha lo avisa |
| ¿Qué es en vivo y qué es precalculado? | Las series satelitales se precalculan (7.911 predios, 97 escenas, en GCP). En vivo: ranking, ficha, expediente PDF y ruta |
| ¿La DGA no hace esto ya? | En el caso de Hijuelas dijo que usó imágenes, pero su fiscalización parte casi siempre de una denuncia. Caudal lo hace para todos los predios y todas las temporadas |
| ¿El satélite es "mundo físico"? | La entrada son mediciones físicas (reflectancia, lluvia, evapotranspiración) y la salida es una inspección en terreno con ruta y puntos a revisar |
| ¿Por qué el AUC entre fiscalizados es bajo (0,62)? | La DGA ya fiscaliza predios regados, así que entre ellos el verdor no separa. La pregunta útil es otra: frente a todos los predios, Caudal concentra 2,6 veces más infractores |
| ¿Escala a otros valles? | Sí: Sentinel-2, DGA, CIREN y CONAF cubren todo Chile. Sumar una zona es correr los mismos scripts con otro polígono |
| ¿Modelo de negocio? | El cliente es la DGA y las juntas de vigilancia. También sirve a APR y comunidades que hoy denuncian sin pruebas |

## Riesgos de la presentación

| Riesgo | Mitigación |
| --- | --- |
| Se cae la red o el servicio | La página funciona sin red desde la segunda visita (service worker). El PDF de la demo queda también como archivo estático. Video de respaldo de 1:45 grabado el sábado en la noche |
| El expediente tarda en generarse | El backend guarda los PDF ya generados; el del candidato se genera antes y sale del caché en menos de 2 segundos |
| Nos pasamos de los 3:00 | Ensayar 5 veces con cronómetro. Si a los 2:20 no partió la validación, se salta la frase de los POI |
| Arranque en frío de Cloud Run | `min-instances=1` en ambos servicios desde el sábado en la noche |
| Vuelos del mapa lentos en el computador de la demo | Abrir la página 5 minutos antes y esperar `data-warm=done`; probar en el computador real |

## Antes de presentar

- [ ] Confirmar tiempo, rúbrica y si hay preguntas (charla del sábado a las 20:00).
- [ ] Llenar `platanus-hack-project.jsonc` con el nombre, la descripción y la URL de producción.
- [ ] Correr el recorrido completo en producción, en el computador de la demo.
- [ ] Grabar el video de respaldo.
- [ ] Ensayar 5 veces con cronómetro y con los dos roles (quien habla y quien maneja).
- [ ] Revisar que las cifras del guion coincidan con `impacto.md` y `validacion.md`.
