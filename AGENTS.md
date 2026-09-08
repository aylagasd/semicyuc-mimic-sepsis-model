# AGENTS.md — SEMICYUC / MIMIC-IV Sepsis Prediction Model

Estas instrucciones se aplican a todo el repositorio. Su finalidad es que cualquier agente contribuya de forma reproducible, clínicamente rigurosa y compatible con las condiciones de uso de MIMIC-IV.

## 1. Objetivo y alcance

Este repositorio desarrolla y valida internamente modelos de predicción temporal de:

- sepsis según Sepsis-3 (sospecha de infección y aumento de SOFA >= 2);
- shock séptico (sepsis, necesidad de vasopresores y lactato > 2 mmol/L);
- deterioro clínico o hemodinámico precoz en pacientes adultos ingresados en UCI.

La fuente primaria es MIMIC-IV. El objetivo posterior es evaluar transportabilidad y validación externa en cohortes españolas. El código de este repositorio es para investigación; no constituye un dispositivo médico ni debe emplearse para decisiones clínicas sin validación externa, evaluación prospectiva y autorización regulatoria.

Antes de implementar una definición clínica, consultar `docs/protocol.md`, `docs/sepsis_definition.md` y `docs/variable_dictionary.md`. Si los documentos no resuelven una ambigüedad, hacerla explícita en la documentación y parametrizarla; no elegir silenciosamente una definición conveniente.

## 2. Estructura esperada

- `docs/`: protocolo, definiciones clínicas, diccionario de variables y estrategia de modelado.
- `sql/`: consultas versionadas, separadas por cohorte, etiquetas y dominios de variables.
- `src/data_processing/`: acceso, validación y transformación de datos.
- `src/feature_engineering/`: ventanas temporales y variables derivadas.
- `src/modeling/`: particiones, pipelines, entrenamiento y ajuste.
- `src/evaluation/`: discriminación, calibración, utilidad clínica y subgrupos.
- `src/utils/`: utilidades compartidas sin lógica clínica oculta.
- `notebooks/`: recorridos ejecutables para Jupyter, numerados según el flujo de trabajo.
- `config/`: configuración no sensible y ejemplos de configuración.
- `tests/`: pruebas unitarias, de integración y de invariantes temporales.
- `models/`, `reports/figures/`, `reports/results/`: artefactos locales o resultados pequeños y agregados, según `.gitignore`.

No crear lógica duplicada en notebooks. La lógica reutilizable debe residir en `src/`; los notebooks importan esas funciones y muestran el proceso.

## 3. Flujo de trabajo inicial

1. Congelar y documentar la versión de MIMIC-IV y el motor de consulta utilizado.
2. Definir la unidad de análisis (`subject_id`, `hadm_id`, `stay_id`) y los criterios de inclusión/exclusión.
3. Implementar y probar por separado la cohorte, la sospecha de infección, SOFA, sepsis y shock séptico.
4. Fijar el instante índice, los horizontes de predicción y las ventanas de observación.
5. Extraer predictores usando exclusivamente información disponible antes del tiempo de corte.
6. Auditar calidad, unidades, duplicados, cobertura, missingness y cronología.
7. Dividir por paciente antes de imputar, seleccionar variables o ajustar modelos.
8. Construir un modelo de referencia interpretable y después comparar modelos más complejos.
9. Evaluar discriminación, calibración, utilidad clínica, incertidumbre y subgrupos.
10. Documentar cada decisión y conservar un camino reproducible desde SQL hasta resultados agregados.

## 4. Acceso a MIMIC-IV, privacidad y credenciales

MIMIC-IV es un conjunto desidentificado, pero de acceso controlado. Cada usuario debe tener sus propias credenciales, formación y acuerdo de uso vigentes. No intentar eludir controles de acceso ni redistribuir datos.

- Leer credenciales únicamente desde variables de entorno o un archivo local ignorado por Git (por ejemplo `.env`, nunca versionado).
- Proporcionar `.env.example` solo con nombres y valores ficticios.
- No incluir contraseñas, tokens, claves, cadenas de conexión completas, rutas privadas ni identificadores institucionales en código, notebooks, salidas, logs, commits o documentación.
- Usar conexiones de solo lectura y consultas parametrizadas. Limitar las filas en comprobaciones exploratorias.
- No descargar ni copiar tablas de pacientes al repositorio.
- No publicar datos a nivel de paciente, incluso si MIMIC-IV está desidentificado. Tratar identificadores, fechas desplazadas, texto clínico y combinaciones raras como datos sensibles.
- No enviar datos o fragmentos de historias clínicas a APIs, servicios externos o herramientas no autorizadas.
- Las salidas compartibles deben ser agregadas y revisadas para evitar celdas pequeñas o reidentificación. Seguir el acuerdo de uso de PhysioNet/MIMIC y las normas institucionales aplicables.

## 5. Convenciones de Python

- Usar Python moderno, type hints y funciones pequeñas con entradas y salidas explícitas.
- Seguir PEP 8; usar `snake_case` para funciones/variables, `PascalCase` para clases y constantes en mayúsculas.
- Añadir docstrings a la lógica pública y explicar supuestos clínicos, unidades y semántica temporal.
- Evitar estado global, rutas absolutas y semillas implícitas. Centralizar configuración y fijar semillas cuando proceda.
- Usar `pathlib`, logging y excepciones informativas; no imprimir credenciales ni filas clínicas.
- Validar esquemas y tipos en los límites del pipeline. Conservar los tiempos en un formato coherente y documentar zonas horarias cuando sean relevantes.
- Mantener dependencias declaradas y versiones reproducibles. No añadir una dependencia pesada si la biblioteca estándar o una dependencia existente basta.
- Separar extracción, transformación, entrenamiento y evaluación. Los estimadores deben integrarse en pipelines que encapsulen el preprocesamiento.

## 6. Convenciones de SQL

- Preferir CTE con nombres clínicamente descriptivos y una responsabilidad por bloque.
- Calificar esquema y tabla; listar columnas explícitamente, sin `SELECT *` en consultas de producción.
- Conservar `subject_id`, `hadm_id` y `stay_id` solo mientras sean necesarios para enlaces y particiones; excluirlos de los predictores.
- Documentar versión de MIMIC-IV, tablas, `itemid`, unidades, reglas de prioridad y criterios de exclusión.
- Normalizar unidades de forma explícita y auditable. No combinar mediciones incompatibles.
- Evitar uniones muchos-a-muchos accidentales; comprobar cardinalidad y unicidad tras cada unión relevante.
- Definir intervalos temporales con límites inequívocos (`>=`/`<`) y anclar toda ventana al instante índice.
- Parametrizar nombres de esquema y fechas/límites cuando lo permita el cliente; nunca interpolar credenciales o entradas no confiables.
- Incluir consultas de control: recuentos, duplicados, valores imposibles, cobertura y pérdida de filas.

## 7. Convenciones de notebooks

- Numerar notebooks por orden (`01_...`, `02_...`) y hacerlos ejecutables de principio a fin desde un kernel limpio.
- Mantener una versión script Python/Jupytext cuando el proyecto adopte ese flujo, para revisión y diffs legibles.
- Al inicio, indicar objetivo, entradas, salidas, versión de datos, configuración y semilla.
- Importar lógica desde `src/`; limitar celdas a orquestación, comprobaciones y visualización.
- No incorporar tokens, DSN, identificadores reales, muestras clínicas ni grandes salidas embebidas.
- Limpiar outputs antes de versionar, salvo figuras/tablas pequeñas, agregadas y necesarias para comprender el análisis.
- No depender del orden histórico de ejecución ni de variables creadas manualmente.
- Tratar `notebooks/README.md` como el manifiesto del recorrido reproducible y
  mantener su secuencia sincronizada con los notebooks implementados.
- Usar R y `ggplot2` para todas las figuras del análisis descriptivo, desarrollo
  y evaluación de modelos, tests gráficos, sensibilidades y subgrupos. No
  sustituirlo silenciosamente por Matplotlib, Seaborn o una reimplementación de
  la gramática de gráficos en Python.
- Guardar figuras mediante `ggsave()` con dimensiones y formato explícitos; fijar
  escalas, unidades, denominadores y tema de forma consistente en una utilidad R
  reutilizable cuando se establezca el estilo del proyecto.

## 8. Semántica temporal y prevención de leakage

La prevención de fuga de información tiene prioridad sobre la mejora aparente de métricas.

- Definir para cada ejemplo: tiempo índice, ventana de observación, horizonte de predicción y tiempo del evento.
- Un predictor solo puede usar eventos cuyo tiempo de disponibilidad clínica sea anterior o igual al corte permitido. Considerar cuándo el resultado estuvo disponible, no solo cuándo se tomó una muestra.
- No usar variables que formen parte de la etiqueta en una ventana que revele el desenlace. SOFA, lactato, vasopresores, cultivos y antibióticos requieren especial auditoría porque pueden definir la etiqueta y también actuar como predictores.
- No usar información posterior al diagnóstico, órdenes o tratamientos iniciados como respuesta al deterioro, alta, mortalidad futura ni resúmenes retrospectivos.
- Separar etiquetas y características en módulos distintos, con pruebas de límites temporales.
- Hacer particiones por `subject_id`, nunca por filas o estancias aisladas que permitan que un paciente aparezca en más de una partición.
- Ajustar imputación, escalado, selección de variables, reducción dimensional, calibración y tuning solo con datos de entrenamiento y dentro de cada fold.
- Mantener el test final bloqueado hasta congelar decisiones. Preferir validación temporal adicional cuando sea viable.
- Auditar explícitamente solapamiento entre ventanas y múltiples ejemplos de una misma estancia.

## 9. Definiciones clínicas y trazabilidad

- Cada variable derivada debe tener nombre, significado, fuente, `itemid` o código, unidad, transformación, ventana y política de valores faltantes en `docs/variable_dictionary.md`.
- Cada outcome debe especificar criterios, precedencia temporal, tolerancias, baseline de SOFA y tratamiento de casos inciertos en `docs/sepsis_definition.md`.
- No sustituir Sepsis-3 por un proxy sin declararlo. Mantener análisis de sensibilidad para definiciones alternativas.
- Registrar recuentos del diagrama de cohorte y prevalencia por partición; investigar diferencias inesperadas.
- Distinguir claramente predicción, asociación y causalidad. No formular conclusiones clínicas causales a partir de importancia de variables o SHAP.

## 10. Validación y evaluación

Como mínimo, informar con intervalos de confianza cuando corresponda:

- AUROC y AUPRC (esta última junto con la prevalencia);
- Brier score, intercepto y pendiente de calibración, y curvas de calibración;
- sensibilidad, especificidad, PPV y NPV en umbrales preespecificados;
- decision curve analysis en un rango clínicamente justificado;
- resultados por horizonte y subgrupos relevantes, con tamaños muestrales;
- distribución de missingness y rendimiento frente a baselines simples.

Usar validación cruzada agrupada por paciente para desarrollo y bootstrap agrupado cuando se estime incertidumbre. Comparar regresión logística penalizada con modelos complejos. Si se recalibra un modelo, usar un conjunto independiente del test final. Documentar hiperparámetros, semillas, versión de datos y entorno.

Evaluar sesgo y transportabilidad (por ejemplo edad, sexo, grupo étnico reportado, tipo de ingreso y tipo de UCI) sin interpretar categorías administrativas como constructos biológicos. Señalar tamaños pequeños, incertidumbre y límites de generalización de un único centro estadounidense.

## 11. Pruebas y controles de calidad

Todo cambio de lógica debe incluir pruebas proporcionales al riesgo:

- tests unitarios con datos sintéticos, nunca filas reales de MIMIC-IV;
- casos frontera para tiempos exactamente en los límites de ventana;
- invariantes de unicidad, cardinalidad, rangos fisiológicos y conversión de unidades;
- tests que demuestren que ningún evento posterior al corte entra en las features;
- tests de separación por paciente y de ajuste exclusivo en entrenamiento;
- prueba de humo de SQL o integración solo cuando exista un entorno autorizado.

Antes de entregar, ejecutar los tests y linters disponibles. Si no pueden ejecutarse por falta de acceso a MIMIC-IV, declararlo y validar con fixtures sintéticos. No relajar una prueba para hacer pasar una implementación incorrecta.

## 12. Documentación y entregables

- Actualizar documentación y diccionario en el mismo cambio que modifica una definición clínica o variable.
- Explicar decisiones metodológicas y alternativas descartadas; enlazar fuentes primarias cuando proceda.
- Mantener README con instalación, configuración segura, flujo reproducible y advertencia de uso investigacional.
- Las tablas y figuras deben indicar cohorte, periodo, horizonte, unidades, denominadores e incertidumbre.
- Evitar afirmar que un modelo está “validado” sin precisar validación interna/externa y población.
- Mantener commits pequeños y temáticos. No modificar archivos ajenos a la tarea ni sobrescribir cambios existentes del usuario.

## 13. Archivos que no deben entrar en Git

Nunca versionar:

- datos MIMIC-IV crudos, intermedios o a nivel de paciente (`.csv`, `.parquet`, volcados SQL, extractos o texto clínico);
- credenciales, `.env`, tokens, claves, certificados o configuraciones privadas;
- notebooks con datos/salidas sensibles;
- modelos que memoricen datos o que no hayan sido evaluados para publicación;
- caches, entornos virtuales, logs, checkpoints y artefactos grandes;
- resultados con identificadores o celdas pequeñas susceptibles de reidentificación.

Antes de `git add`, revisar `git diff`, archivos no rastreados, tamaño de artefactos y outputs de notebooks. Si un dato sensible llegó al historial, detenerse y avisar: borrarlo solo del último archivo no elimina el historial.

## 14. Criterio de finalización

Un cambio está terminado cuando el código es reproducible, las pruebas relevantes pasan, la semántica temporal está auditada, la documentación coincide con la implementación y no se han añadido datos sensibles, credenciales ni artefactos grandes. Indicar cualquier prueba no ejecutada, supuesto pendiente o limitación clínica en la entrega.
