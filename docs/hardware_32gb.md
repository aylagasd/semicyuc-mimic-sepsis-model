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
     --temp-dir /ruta/ssd/duckdb \
     --memory-limit 8GB --resume
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
   máximo dos trabajadores para futuras etapas explícitamente paralelizables,
   pero el pipeline actual es secuencial.
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
  descarta eventos que no pueden entrar en ninguna ventana del lote. Python
  conserva el agregador final `[L-W,L)` para mantener el contrato ya probado.
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

## Criterio de aceptación en el i5

En la primera ejecución completa se registrarán por etapa tiempo, RSS máximo,
espacio temporal y tamaño de salida. Se acepta el perfil si el RSS permanece
por debajo de 24 GiB, no hay swapping sostenido, los manifiestos validan y la
equivalencia/invariantes clínicos pasan. Si no se cumple, se reduce el lote y
se reanuda; aumentar paralelismo no es una corrección válida para falta de RAM.

El test continúa sin materializarse hasta completar las firmas y el congelado
del modelo descritos en la guía de despliegue.
