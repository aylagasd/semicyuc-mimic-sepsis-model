# Perfil de ejecución en i5 con 32 GiB de RAM

## Objetivo

Este perfil permite desarrollar y ejecutar el recorrido de MIMIC-IV completo
sin cargar tablas fuente ni matrices anchas completas en memoria. No modifica
definiciones clínicas ni estimadores: cambia cómo se leen y remuestrean los
datos. La primera ejecución completa sigue necesitando monitorización porque el
tamaño definitivo depende de la versión descargada, la cohorte y la cobertura
de eventos.

## Presupuesto conservador

`config/compute_32gb.json` reserva un 25 % de la RAM para el sistema operativo,
Jupyter y variabilidad del proceso. El análisis solo puede planificarse dentro
de 24 GiB. La estimación previa añade 2 GiB fijos y multiplica por ocho la
memoria profunda de las tablas pandas proyectadas para cubrir joins, matrices
NumPy, preprocesamiento y temporales de los modelos.

La estimación es una puerta de ingeniería, no una garantía empírica. Antes del
informe final se ejecuta:

```bash
python scripts/preflight_pretest_memory.py config/pretest_source.local.json
```

El comando valida hashes y separación development/validation, carga únicamente
el horizonte primario y las cinco variables preespecificadas, y muestra solo
recuentos y bytes agregados. Un código de salida 2 impide continuar con ese
perfil.

## Ajustes operativos

1. Ejecutar la reducción CSV con DuckDB limitado a 8 GB y un directorio
   temporal en SSD local:

   ```bash
   python scripts/extract_full_mimic.py /ruta/mimiciv/3.1 \
     --data-version 3.1 \
     --output-dir /ruta/derivados/full_extract \
     --stay-policy first_per_admission \
     --temp-dir /ruta/ssd/duckdb \
     --memory-limit 8GB --threads 2 --resume
   ```

2. Construir SOFA, etiquetas, landmarks y features en lotes de 100 estancias.
   Si la monitorización demuestra margen sostenido puede ensayarse 250; si hay
   presión de memoria se reduce a 50 sin cambiar el contenido lógico:

   ```bash
   python scripts/build_full_pipeline_chunked.py \
     /ruta/derivados/full_extract \
     --output-root /ruta/derivados/full_pipeline \
     --compute-profile config/compute_32gb.json --resume
   ```

3. No ejecutar en paralelo etapas que materialicen pandas. El perfil fija como
   máximo dos hilos DuckDB y el pipeline actual es secuencial. El límite de
   memoria, los hilos y el directorio de spill se aplican a SOFA, etiquetas,
   landmarks y features, además de a la extracción.
4. Mantener el directorio temporal y los derivados en SSD. La capacidad libre
   se valida con `preflight_mimic_files.py`; no se presupone a partir de la RAM.
5. Crear `config/pretest_source.local.json`, ejecutar el preflight de memoria y
   solo entonces abrir `notebooks/13_final_report.ipynb`.

## Optimizaciones implementadas

- DuckDB aplica predicados y proyección directamente sobre Parquet: para el
  informe primario solo llegan a pandas el horizonte de 6 h observado, las
  claves necesarias y cinco predictores.
- En la construcción de features, una consulta SQL normaliza itemids y
  unidades, enlaza laboratorios con la estancia por tiempo de espécimen y
  descarta eventos que no pueden entrar en ninguna ventana del lote. La fuente
  se escanea una vez por lote y se reutiliza entre outcomes y particiones.
  Python conserva el agregador final `[L-W,L)`, vectorizado por estancia, para
  mantener el contrato ya probado.
- Cada ejecución escribe `resource_report.json` bajo el directorio de salida.
  Contiene solo tiempo, RSS, swap del proceso, E/S, bytes, filas y partes
  agregados por etapa; también persiste el tipo de excepción si una etapa
  falla, nunca el mensaje ni filas clínicas. Puede cambiarse con
  `--resource-report`.
- Los artefactos vacíos conservan su esquema. Por ello reducir el lote a 50 o
  menos no falla cuando una parte carece de episodios de sepsis o shock.
- Todos los ficheros y manifiestos se validan antes de leer la proyección; la
  optimización no omite controles de integridad ni leakage.
- El bootstrap por paciente usa códigos de clúster y pesos de frecuencia. Cada
  réplica conserva matemáticamente la misma multiplicidad que duplicar filas,
  pero no reconstruye vectores de outcome y probabilidad ni vuelve a ordenar
  las probabilidades.
- AUROC y AUPRC se calculan por grupos de probabilidades empatadas sobre un
  orden precalculado. Brier, log-loss y calibración usan pesos de frecuencia.

Las pruebas sintéticas comparan el resultado vectorizado con la duplicación
física de pacientes, incluyendo tamaños de clúster desiguales y empates. En la
Raspberry de desarrollo, un benchmark sintético de 9.000 filas, 300 pacientes y
40 réplicas pasó de 3,36 s a 0,96 s (3,5 veces); es evidencia de ingeniería,
no una predicción del tiempo total sobre MIMIC-IV.

En una parte real del demo con 5.684 filas de landmarks, el pushdown de fuentes
redujo la memoria residente de entrada de 1.569.595 a 570.350 bytes y el tiempo
de preparación de 0,198 a 0,087 s. Las seis matrices completas del demo —dos
outcomes por tres particiones— conservaron equivalencia exacta de multiconjunto
frente al backend anterior.

En el recorrido completo del demo, con lote 100, límite DuckDB de 1 GB y dos
hilos en la Raspberry, reutilizar la fuente por lote y vectorizar los índices de
ventana redujo primero la etapa de features de 97,3 a 63,1 s (35,1 %) en el
mismo entorno. Después, eliminar merges intermedios y reutilizar por variable la
ordenación de eventos entre ventanas redujo un benchmark fresco comparable de
59,6 a 38,8 s (34,9 %) y el recorrido total de 89,0 a 68,0 s (23,6 %), con pico
RSS de 197,7 MiB. Las seis matrices conservaron igualdad exacta frente al
resultado previo. Son medidas de ingeniería local, no una proyección lineal del
tiempo sobre MIMIC-IV completo.

## Criterio de aceptación en el i5

En la primera ejecución completa se registrarán por etapa tiempo, RSS máximo,
E/S y tamaño de salida mediante `resource_report.json`; el espacio temporal se
vigilará además a nivel del sistema. Se acepta el perfil si el RSS permanece
por debajo de 24 GiB, no hay swapping sostenido, los manifiestos validan y la
equivalencia/invariantes clínicos pasan. Si no se cumple, se reduce el lote y
se reanuda; aumentar paralelismo no es una corrección válida para falta de RAM.

El criterio ejecutable se comprueba inmediatamente después de la corrida:

```bash
python scripts/validate_pipeline_resources.py \
  /ruta/derivados/full_pipeline/resource_report.json \
  --compute-profile config/compute_32gb.json
```

Devuelve código 0 solo si terminaron en orden las cuatro etapas, el hash y los
parámetros coinciden con el perfil, el pico RSS no supera 24 GiB, el kernel pudo
informar memoria y no se observó swap del proceso. El espacio libre y el swap
global del sistema continúan siendo controles operativos adicionales.

El test continúa sin materializarse hasta completar las firmas y el congelado
del modelo descritos en la guía de despliegue.
