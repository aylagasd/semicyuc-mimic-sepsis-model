# Evidencia reproducible de política de cohorte (D002)

## Alcance

Este informe reconstruye la cohorte adulta desde las tres tablas fuente para
cada política preespecificada: primera estancia elegible por ingreso, primera
por paciente y todas las estancias elegibles. No simula alternativas filtrando
la cohorte primaria ya construida.

El resultado permite revisar flujo, disposiciones de exclusión y anidamiento de
las selecciones. No decide D002, no modifica el registro ni reemplaza las
sensibilidades posteriores de fenotipo y modelo. El demo comprueba ingeniería;
sus cifras no son estimaciones clínicas.

## Ejecución

Demo local:

```bash
python scripts/audit_cohort_policy_freeze.py \
  data/mimic-iv-demo/2.2 --data-version 2.2
```

Distribución completa autorizada:

```bash
python scripts/audit_cohort_policy_freeze.py \
  /ruta/mimiciv/3.1 --data-version 3.1 \
  --memory-limit 1GB --threads 2
```

DuckDB proyecta únicamente las claves, edad anclada y tiempos necesarios de
`patients`, `admissions` e `icustays`. El informe enlaza los SHA-256 de esos tres
ficheros, no guarda rutas y solo escribe agregados. La salida predeterminada,
`data/derived/audit/cohort_policy_evidence.json`, tiene permisos `0600`, está
ignorada por Git y contiene recuentos no suprimidos; debe revisarse en el
entorno protegido.

## Controles

- las políticas deben aparecer exactamente en el orden versionado de
  `config/sensitivity.json`;
- cada cohorte se reconstruye con las mismas reglas de enlace, edad y duración;
- primera por paciente debe ser subconjunto de primera por ingreso, y esta de
  todas las elegibles;
- se informan denominadores de estancia, ingreso y paciente por separado;
- se registran estancias añadidas o retiradas respecto al primario;
- ninguna tabla del informe puede contener `subject_id`, `hadm_id` o `stay_id`.

## Reconstrucción completa de sensibilidades

La comparación anterior cubre selección y flujo. Para ejecutar después
fenotipo/modelo bajo una política alternativa, la política forma parte del hash
de configuración y debe tener una raíz distinta:

```bash
python scripts/extract_full_mimic.py /ruta/mimiciv/3.1 \
  --data-version 3.1 --stay-policy first_per_patient \
  --output-dir /ruta/derivados/first_per_patient/extract --resume
```

El mismo principio se aplica a `all`. No se deben sobrescribir ni mezclar
raíces entre políticas. Cada extracción alimenta su propio pipeline por lotes;
la partición, los landmarks, las etiquetas y las características se reconstruyen
completamente. La comparación de métricas se mantiene en development/validation
y nunca se usa para elegir una política mirando el test.
