# Caudal — Pitch y demo de 3 minutos

Nov 21, 2026 · @Tomas

Este documento define qué decimos y qué mostramos en los 3 minutos de la final. Lo que hay que construir para mostrarlo está en [spec-demo.md](spec-demo.md). Las cifras salen de [impacto.md](impacto.md) y [validacion.md](validacion.md); si se regeneran, hay que actualizar el guion.

## Reglas del formato

| Regla | Valor | Fuente |
| --- | --- | --- |
| Duración | 3 minutos | Organización |
| Demo mínima | 1 minuto 30 segundos | Organización |
| Corte duro a los 3:00 y 2 minutos de preguntas | Confirmado | Equipo |
| El reloj parte con la primera palabra | Confirmado | Equipo |
| El jurado lee el repo y castiga las demos simuladas | Confirmado | Equipo |

No hay una rúbrica oficial publicada.

Consecuencias para nosotros:

- El guion tiene 430 palabras como máximo (unas 150 por minuto) y termina a los 2:55.
- Todo lo que se muestra corre en producción con datos reales. Nada de botones simulados.
- Una persona habla y otra maneja el computador.

## Mensaje

**Caudal le dice a la DGA qué predios inspeccionar mañana.** Usa satélite, clima y el registro público de derechos de agua, y entrega una ruta de inspección y un expediente listo para presentar.

Tres ideas que el jurado debe recordar:

1. **Funciona con un caso real.** Caudal marca dos años antes un predio que la DGA multó con $127 millones.
2. **Termina en una acción física.** La salida es una ruta para un inspector y un expediente con el formato de la DGA.
3. **Está validado y no exagera.** Se probó contra las fiscalizaciones reales de la DGA y todo va en rango.

## Guion

Toda la demo ocurre en una sola zona (Aconcagua bajo, comuna de Hijuelas) para no gastar tiempo en vuelos entre zonas. El producto está en pantalla desde el 0:22 hasta el cierre; el recorrido en vivo va de 0:22 a 2:00.

| Tiempo | Qué se dice | Qué se ve |
| --- | --- | --- |
| 0:00–0:22 | Gancho | Portada: mapa de Chile con las dos zonas |
| 0:22–0:37 | Qué es Caudal | Vuelo a la zona; aparecen los predios por banda |
| 0:37–1:02 | Demo 1: el caso real | Ficha del caso FO-0504-95: serie y antes/después |
| 1:02–1:35 | Demo 2: un candidato de hoy y su expediente | Ficha del candidato; se genera el PDF en vivo |
| 1:35–2:00 | Demo 3: la ruta de mañana | Pestaña Ruta: paradas, horas y botón de navegación |
| 2:00–2:45 | Validación e impacto | Panel de impacto |
| 2:45–2:55 | Cierre | Logo, URL y equipo |

### Texto

El tono es hablado. No se nombran satélites, índices ni métodos (Sentinel-2, NDVI, FAO-56): van en el material de apoyo y en las respuestas.

**0:00 Gancho.**
"En Petorca hay 40 mil personas que han tenido que vivir con 50 litros de agua al día, y esa agua les llega en camión aljibe. Solo en 2023 y 2024, el Estado contrató más de 5.700 millones de pesos en esos camiones. Mientras tanto, ahí mismo, hay huertos verdes en pleno verano que riegan sin tener derechos de agua. ¿Y cómo se pilla eso hoy? Solo si un vecino denuncia."

**0:22 Qué es.**
"Caudal mira desde el satélite los casi 8 mil predios de Petorca y Aconcagua, cada cinco días. Si lleva diez días sin llover y un predio sigue más verde que el cerro de al lado, alguien lo está regando. Y si riega más de lo que sus derechos le permiten, lo marcamos."

**0:37 Demo 1, el caso real.**
"Esto es Hijuelas. En 2021 la DGA multó a este predio de paltos con 127 millones de pesos por sacar agua sin derechos. Miren su historia: la línea gris es el cerro seco, la verde es el predio. Caudal lo tenía en alerta alta desde 2019. Dos años antes de que llegara un inspector."

**1:02 Demo 2, un candidato de hoy.**
"Ahora, el verano pasado, en la misma comuna. Diecinueve hectáreas de paltos, verdes todo el verano. No tiene derechos de agua inscritos, no tiene un canal cerca y nunca lo han fiscalizado. Ojo: Caudal no acusa, prioriza. Y con un clic arma el expediente, con el formato oficial de denuncias de la DGA. Esto se está generando ahora, en producción."

**1:35 Demo 3, la ruta.**
"Y esto es lo que importa: a dónde va el inspector mañana. Cinco predios, cuatro horas, 71 kilómetros. Se abre en Google Maps. Y dentro de cada predio le decimos dónde mirar: el parche regado, el tranque, el pozo."

**2:00 Validación e impacto.**
"Esto lo probamos contra las fiscalizaciones reales de la DGA: donde Caudal marca alerta alta, hay 2,6 veces más infractores que si uno eligiera al azar. Y para que se hagan una idea: un solo predio como el que acaban de ver se toma al año el agua de casi 3.000 personas. O, si prefieren, 220 millones de latas de Monster. Como ese hay 501 predios que nadie ha ido a mirar. Juntos son entre 5 y 20 Torres Costanera llenas de agua, todos los años. Revisarlos uno por uno tomaría 14 años. Caudal te dice por cuáles cinco partir mañana."

**2:45 Cierre.**
"Todo esto con datos públicos, y sirve para cualquier valle de Chile. Somos Nicolás, Felipe, Gabriela y Tomás. Gracias."

El texto tiene unas 410 palabras.

## Cifras del guion y su respaldo

| Frase | Valor y cálculo | Fuente | Advertencia |
| --- | --- | --- | --- |
| 40 mil personas con 50 litros al día | 40.000 personas en la provincia de Petorca | [Radio JGM, U. de Chile, 04-05-2020](https://radiojgm.uchile.cl/de-50-a-100-litros-de-agua-el-suministro-que-el-minsal-no-pudo-cumplir/) | Es un dato de 2020: decir "han tenido que vivir". En 2021 la Corte Suprema subió la dotación a 100 litros |
| 5.700 millones en camiones aljibe | $5.710 millones en contratos de la Delegación Presidencial Provincial de Petorca, 2023 y 2024 sumados | [Consejo para la Transparencia, 05-10-2026](https://www.consejotransparencia.cl/fiscalizacion-cplt-municipios-y-delegaciones-contrataron-mas-de-30-mil-millones-en-camiones-aljibe-en-2023-y-2024-pero-a-cuantas-familias-llego-el-agua-potable/) | Son montos contratados e informados por la delegación, no pagos: decir "contrató", no "gastó". Leímos el comunicado; el informe completo no abrió |
| Casi 8 mil predios | 7.911 | `puntaje.parquet` | Predios con rol válido y 1 ha o más |
| Multa de 127 millones | 1.983,9 UTM | Planilla de la DGA y nota de prensa de la DGA | — |
| Alerta alta desde 2019, dos años antes | Temporada 2019-20; inspección el 23-11-2021 | `impacto.md` | La serie parte en 2019-20: es una cota inferior |
| Diecinueve hectáreas, sin derechos, sin canal cerca, nunca fiscalizado | 18,8 ha, 89 % palto, sin derechos a 500 m, canal a 1,2 km, sin fiscalización a 500 m desde 2018 | `puntaje.parquet`, predio `5301984` | No mostrar rol ni dueño |
| Cinco predios, cuatro horas, 71 km | Ruta de Z2 (5 paradas, 08:30 a 12:28, 71,3 km) | `ruta_z2.json` | Cambia si se regenera la ruta. Con tope de 5 paradas desde el 21-11; antes eran 12 predios, 8 horas y 91 km |
| 2,6 veces más infractores | IC 95 %: 1,3–4,4 | `validacion.md` | Usar 2,6 y no 3,7: el 3,7 se midió con los mismos casos que calibraron los umbrales |
| El agua de casi 3.000 personas | 105.000 m³ al año ÷ 36,5 m³ por persona = 2.877 | `puntaje.parquet`; dotación de 100 litros al día ([Corte Suprema, 2021](https://www.24horas.cl/regiones/valparaiso/corte-suprema-determina-100-litros-de-agua-por-habitantes-de-petorca-4708851)) | 105.000 m³ es el mínimo del rango del candidato |
| 220 millones de latas de Monster | 105.000 m³ ÷ 473 ml = 222 millones | Lata de 473 ml | — |
| 501 predios que nadie ha ido a mirar | Banda alta sin fiscalización a 500 m desde 2018 | `impacto.md` | — |
| Entre 5 y 20 Torres Costanera al año | 2,1 a 9,3 millones de m³ ÷ 450.000 m³ = 4,7 a 20,7 | `impacto.md`; torre de 107.125 m² construidos y 300 m de alto | El volumen de la torre es una estimación nuestra (superficie por unos 4,2 m por piso); ninguna fuente lo publica. Si preguntan, decir "unas" |
| 14 años | 467 candidatos ÷ 33 fiscalizaciones por extracción al año | `impacto.md` | Es capacidad, no calidad: no decir que Caudal acierta más que la DGA |

Datos de reserva para las preguntas:

- Acierto de la DGA: 33 % (107 fiscalizaciones por extracción, 2022–2025). Caudal en alerta alta: 7 de 15.
- Casos esperados entre los 501 candidatos: 39 a 153.
- Caso de Hijuelas: unos 140.000 m³ sin derecho en los dos años previos a la inspección, el agua de unas 1.900 personas durante esos dos años.
- Camiones aljibe en Petorca, enero a marzo de 2026: $176,4 millones por 41.201 m³ (Mercado Público).
- En todo el país, 2023 y 2024: 370 contratos por más de $30.192 millones; la Región de Valparaíso concentra el 47 % del monto (mismo comunicado del Consejo para la Transparencia).
- Escuela de Petorca con jornada reducida a la mitad por cortes de agua ([BBC Mundo, 16-12-2021](https://www.elmostrador.cl/dia/2021/12/16/petorca-en-la-bbc-mundo-el-pueblo-de-chile-que-esta-cerrando-escuelas-por-culpa-de-la-sequia/)).

## Decisiones

| Decisión | Elegido | Alternativa | Por qué |
| --- | --- | --- | --- |
| Zona de la demo | Z2, Hijuelas | Z1, Cabildo: caso FD-0501-181 y candidato `5344181` (31 ha de palto) | El caso FO-0504-95 es el más sólido (la DGA dijo que lo detectó con satélite y el verdor baja después de la multa). El candidato está en la misma comuna, así que la demo no cambia de zona |
| Candidato en vivo (D19) | Predio `5301984` | `5344181` (Cabildo), `5345478` (Cabildo, 7 ha de nogal) | Señal en el 100 % de las fechas, sin derechos a 500 m, sin canal a 1 km, sin fiscalización a 500 m, 89 % de la superficie con frutales |
| Cifra de validación | 2,6 veces | 3,7 veces | Es la cifra sin sesgo de calibración; aguanta una pregunta del jurado |
| Comparación con la DGA | Una sola mención, como capacidad: "14 años". El 33 % queda para las preguntas | Abrir con "la DGA acierta 1 de cada 3" | No tenemos datos para decir que acertamos más (7 de 15, intervalo ancho) y la DGA es el cliente. La capacidad muestra que falta una herramienta; no nos presenta como una mejora de algo que ya existe |
| Equivalencias de volumen | Personas, latas de Monster y Torres Costanera | Metros cúbicos y pesos | Nadie imagina un millón de m³. Se presenta en la oficina de Buk, cerca del Costanera Center |
| Cómo se muestra el candidato | Por ID interno, sin rol ni dueño, con la palabra "candidato" | No mostrar ningún predio no multado | El expediente y la ruta necesitan un predio concreto. El equipo debe confirmar esta decisión (ver abajo) |

**Por confirmar con el equipo:** la convención era mostrar a los candidatos solo agregados. La demo en vivo necesita un predio concreto que no ha sido multado, y la ruta ya muestra ubicaciones. La propuesta es mostrarlo sin rol ni dueño y decir en voz alta que Caudal prioriza y no acusa. Si el equipo no está de acuerdo, el expediente en vivo se genera para el caso FO-0504-95 y el paso "candidato de hoy" muestra solo el ranking agregado.

## Preguntas probables del jurado

| Pregunta | Respuesta corta |
| --- | --- |
| ¿Cuántos falsos positivos tiene? | Entre los fiscalizados en alerta alta, 7 de 15 tuvieron infracción (47 %; la DGA tiene 33 %). Son pocos casos y lo decimos. Por eso Caudal prioriza y entrega rangos; la infracción la constata el inspector |
| ¿Cómo saben que es agua ilegal y no de un canal? | No lo sabemos con certeza. El agua de canal no está en el registro de derechos. Por eso el escenario conservador excluye a todo predio con un canal a 300 m, y la ficha lo avisa |
| ¿Qué es en vivo y qué es precalculado? | Las series satelitales, el puntaje y la ruta se precalculan (7.911 predios, en GCP y en los scripts del repo). En vivo: el expediente PDF y las consultas de la API. Detalle en [en-vivo-y-precalculado.md](en-vivo-y-precalculado.md) |
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

- [ ] Llenar `platanus-hack-project.jsonc` con el nombre, la descripción y la URL de producción.
- [ ] Correr el recorrido completo en producción, en el computador de la demo.
- [ ] Grabar el video de respaldo.
- [ ] Ensayar 5 veces con cronómetro y con los dos roles (quien habla y quien maneja).
- [ ] Revisar que las cifras del guion coincidan con `impacto.md` y `validacion.md`.
