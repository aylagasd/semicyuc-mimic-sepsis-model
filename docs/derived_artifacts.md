# Contrato de artefactos derivados para SOFA

## Propósito

Este documento define el contrato de los artefactos incrementales usados para
construir el SOFA horario. Su objetivo es que una ejecución pueda interrumpirse
y reanudarse sin repetir etapas válidas, que los resultados sean auditables y
que el mismo DAG pueda ejecutarse sobre el demo local y sobre MIMIC-IV completo.

Los artefactos contienen datos a nivel de paciente y **no son entregables del
repositorio**. Deben residir bajo una ruta ignorada por Git, con acceso limitado
a usuarios autorizados. El manifiesto también se considera sensible si contiene
rutas privadas, identificadores o recuentos pequeños.

## Identidad de una ejecución

Cada ejecución tendrá un `run_id` inmutable, generado a partir de la
configuración efectiva y no de credenciales:

```text
{backend}-{mimic_data_version}-{mimic_code_version}-{config_hash_12}
```

Ejemplos:

```text
demo-2.2-v2.4.0-a1b2c3d4e5f6
postgres-3.1-v3.0.1-0a1b2c3d4e5f
```

La ubicación local canónica será:

```text
data/derived/sofa/{run_id}/
```

En un servidor, la raíz podrá ser un volumen protegido u object storage
institucional. Cambiar la raíz no cambia la identidad lógica del artefacto.
Dentro de una ejecución no se sobrescriben artefactos terminados: una
configuración o código distintos generan otro `run_id`.

`config_hash` será SHA-256 del JSON canónico (UTF-8, claves ordenadas, sin
espacios no significativos) que incluya como mínimo:

- versión y release de los datos;
- backend y dialecto;
- versión y commit de `mimic-code`;
- commit del repositorio o hash del código fuente relevante;
- política de cohorte;
- límites temporales y semántica de intervalos;
- mapeos de `itemid`, unidades y parámetros clínicos;
- versión del esquema de artefactos.

Nunca incluirá usuario, contraseña, token, host privado ni DSN.

## Estructura y nombres

```text
data/derived/sofa/{run_id}/
├── manifest.json
├── 00_cohort/
│   ├── cohort_stays.parquet
│   └── hourly_grid.parquet
├── 10_events/
│   ├── respiratory_events.parquet
│   ├── coagulation_events.parquet
│   ├── liver_events.parquet
│   ├── map_events.parquet
│   ├── vasoactive_intervals.parquet
│   ├── cns_events.parquet
│   ├── creatinine_events.parquet
│   └── urine_events.parquet
├── 20_components/
│   ├── respiratory_hourly.parquet
│   ├── coagulation_hourly.parquet
│   ├── liver_hourly.parquet
│   ├── cardiovascular_hourly.parquet
│   ├── cns_hourly.parquet
│   └── renal_hourly.parquet
├── 30_score/
│   └── sofa_hourly.parquet
└── audit/
    ├── cohort_audit.json
    ├── quality_checks.json
    └── build_log.jsonl
```

Parquet es el formato portátil primario. DuckDB puede registrar vistas o tablas
externas sobre estos archivos, pero su fichero de base de datos es cache local,
no la fuente normativa. En PostgreSQL o BigQuery se pueden materializar tablas
equivalentes; antes de exportarlas a Parquet deben respetar los mismos nombres,
tipos, claves y metadatos.

En el servidor se permite particionar un artefacto como directorio Parquet, por
ejemplo por `stay_id_bucket` o por lote de cohorte. El nombre lógico continúa
siendo el de la tabla anterior y todas sus particiones comparten esquema.

## Esquemas y claves

Los tiempos se almacenarán como `timestamp[us]` sin zona horaria: las fechas de
MIMIC-IV son tiempos clínicos desplazados y no deben convertirse usando la zona
horaria del equipo. Los identificadores son `int64`, `hr` es `int32`, los
valores fisiológicos son `float64` y las puntuaciones son enteros anulables.

### Cohorte y rejilla

`cohort_stays` tiene una fila por estancia y clave primaria `stay_id`:

| Columna | Tipo | Significado |
|---|---|---|
| `subject_id` | int64 | Paciente; solo para enlaces y particiones |
| `hadm_id` | int64 | Ingreso hospitalario |
| `stay_id` | int64 | Estancia UCI |
| `intime` | timestamp | Entrada UCI |
| `outtime` | timestamp | Salida UCI |
| `cohort_included` | bool | Cumple la política de cohorte |
| `exclusion_reason` | string nullable | Motivo auditable de exclusión |

`hourly_grid` tiene una fila por hora y clave compuesta (`stay_id`, `hr`):

| Columna | Tipo | Significado |
|---|---|---|
| `subject_id`, `hadm_id`, `stay_id` | int64 | Claves de enlace |
| `hr` | int32 | Hora relativa de la rejilla oficial |
| `endtime` | timestamp | Extremo derecho de la ventana |

Debe cumplirse la unicidad de (`stay_id`, `hr`) y de (`stay_id`, `endtime`).

### Eventos normalizados

Los artefactos `*_events` contienen una fila por observación clínica
normalizada. Su contrato común mínimo es:

| Columna | Tipo | Significado |
|---|---|---|
| `stay_id` | int64 | Estancia enlazada |
| `event_time` | timestamp | Momento clínicamente disponible para SOFA |
| `source_table` | string | Tabla cruda de procedencia |
| `source_row_id` | string | Identidad estable de la fila fuente o hash |
| `itemid` | int64 nullable | Concepto fuente cuando exista |
| `value` | float64 nullable | Valor normalizado |
| `unit` | string nullable | Unidad normalizada |
| `score` | int8 nullable | Puntuación instantánea del componente |

La clave será (`stay_id`, `source_table`, `source_row_id`, `event_time`). Si la
fuente no ofrece una clave estable, `source_row_id` será SHA-256 de los campos
fuente que determinan la observación, después de su serialización canónica.
Nunca se usará el ordinal de lectura del CSV como identidad.

Excepciones explícitas:

- `respiratory_events` añade `pao2`, `fio2`, `pao2_fio2`,
  `pao2_time`, `fio2_time` e `invasive_ventilation`; `event_time` es
  `pao2_time` y no se permite un FiO2 futuro.
- `vasoactive_intervals` usa clave (`stay_id`, `source_row_id`,
  `starttime`, `endtime`) y añade `drug`, `dose_mcg_kg_min`,
  `starttime` y `endtime`. Los intervalos deben satisfacer
  `endtime > starttime`.
- `cns_events` añade los componentes ocular, verbal y motor, `gcs_total` y la
  marca `verbal_intubated`.
- `urine_events` conserva el volumen normalizado en mL y el tiempo de la
  observación; la suma de 24 horas se calcula en la etapa horaria.

Todo evento debe pertenecer a un `stay_id` de `cohort_stays`. Los eventos
duplicados por su clave se consideran error, no se resuelven de forma implícita.

### Componentes horarios

Cada `*_hourly` tiene exactamente una fila por fila de `hourly_grid`, clave
(`stay_id`, `hr`) y estas columnas mínimas:

| Columna | Tipo | Significado |
|---|---|---|
| `stay_id` | int64 | Estancia |
| `hr` | int32 | Hora de rejilla |
| `endtime` | timestamp | Extremo derecho |
| `score_24h` | int8 nullable | Peor puntuación en `(endtime-24 h, endtime]` |
| `observed_24h` | bool | Hubo información válida para el componente |
| `source_event_count_24h` | int32 | Eventos válidos en la ventana |

Los componentes cardiovascular y renal combinan subcomponentes. Deben añadir,
respectivamente, `map_score_24h`/`vasoactive_score_24h` y
`creatinine_score_24h`/`urine_score_24h`, conservando valores anulables. La
combinación usa el máximo observado, sin convertir previamente ausentes a cero.

`score_24h` solo admite valores 0–4 o nulo. Los límites de la ventana son
obligatoriamente abiertos por la izquierda y cerrados por la derecha.

### SOFA horario final

`sofa_hourly` tiene clave (`stay_id`, `hr`) y contiene:

- `subject_id`, `hadm_id`, `stay_id`, `hr`, `endtime`;
- `sofa_respiratory`, `sofa_coagulation`, `sofa_liver`,
  `sofa_cardiovascular`, `sofa_cns`, `sofa_renal` (`int8` anulable);
- `missing_components` (`int8`, 0–6);
- `sofa_complete` (`int8` anulable), suma solo cuando se observan los seis;
- `sofa_total` (`int8`, 0–24), suma compatible con MIMIC Code imputando a
  cero los componentes no observados.

`sofa_complete` y `sofa_total` se conservan simultáneamente: el primero audita
missingness y el segundo reproduce la definición canónica. Ninguna de estas
columnas se usará como predictor sin aplicar el corte y horizonte definidos.

## Procedencia y manifiesto

`manifest.json` es el índice autoritativo de la ejecución. Tendrá una sección
general y una entrada por artefacto:

```json
{
  "schema_version": 1,
  "run_id": "demo-2.2-v2.4.0-a1b2c3d4e5f6",
  "created_at_utc": "2026-07-18T12:00:00Z",
  "mimic_data_version": "2.2",
  "mimic_code": {"version": "v2.4.0", "commit": "570ef01"},
  "project_commit": "commit-o-DIRTY+source_hash",
  "backend": "duckdb",
  "config_sha256": "...",
  "artifacts": {
    "hourly_grid": {
      "status": "complete",
      "relative_path": "00_cohort/hourly_grid.parquet",
      "schema_sha256": "...",
      "content_sha256": "...",
      "row_count": 15618,
      "primary_key": ["stay_id", "hr"],
      "inputs": {"cohort_stays": "...", "chartevents": "..."},
      "code_sha256": "...",
      "started_at_utc": "...",
      "completed_at_utc": "..."
    }
  }
}
```

Cada entrada registra además, cuando proceda, particiones, recuento de
identificadores distintos, mínimo/máximo temporal, versión de PyArrow/DuckDB o
motor SQL y resultado de los checks de calidad. `project_commit` no basta si el
árbol está sucio: en ese caso se registra `DIRTY` y el hash de los archivos de
código y configuración realmente usados.

La procedencia de cada artefacto incluye:

1. checksums de todos sus inputs lógicos;
2. checksum del código/SQL que lo produce;
3. configuración clínica efectiva;
4. versión de datos, `mimic-code`, librerías y motor;
5. timestamps de inicio y finalización;
6. checks de esquema, clave, cardinalidad, rangos y cronología.

## Checksums

- Se usa SHA-256; MD5 no es suficiente para la identidad normativa.
- Para un único Parquet, `content_sha256` es el hash de sus bytes una vez
  cerrado y renombrado atómicamente.
- Para un dataset particionado, se ordenan las rutas relativas y se calcula un
  hash raíz del JSON canónico `{ruta: sha256}`. El manifiesto conserva también
  el hash y número de filas de cada partición.
- `schema_sha256` se calcula sobre una representación canónica de nombres,
  tipos, nulabilidad, orden y metadatos clínicos de columnas.
- Los archivos fuente locales se identifican por hash y ruta relativa dentro
  del release MIMIC; en una base remota se registra el identificador inmutable
  disponible (release/snapshot/table metadata) y el hash de la consulta.
- Al reanudar se recalculan el hash del artefacto y los hashes de sus inputs; no
  se confía solo en la existencia del archivo.

El checksum prueba identidad de bytes, no corrección clínica. Siempre se
requieren los controles de calidad.

## Construcción, publicación y reanudación

Cada artefacto recorre los estados `pending`, `running`, `complete` o `failed`.
Solo `complete` puede alimentar una etapa posterior.

1. Adquirir un bloqueo exclusivo por `run_id` y artefacto.
2. Escribir en el mismo filesystem a
   `.<artifact>.<uuid>.partial`, nunca en la ruta definitiva.
3. Validar esquema, clave, rangos, cardinalidad y tiempos.
4. Cerrar el archivo, calcular checksums y hacer `fsync` cuando el backend lo
   permita.
5. Renombrar atómicamente a la ruta definitiva.
6. Actualizar el manifiesto de forma atómica y marcar `complete`.

Al reiniciar:

- se eliminan o ponen en cuarentena los `.partial` huérfanos;
- se reutiliza un artefacto `complete` únicamente si esquema, contenido, código,
  configuración e inputs siguen coincidiendo;
- un estado `running` sin bloqueo activo se trata como `failed`;
- se reconstruye desde el primer nodo inválido; los nodos independientes
  válidos se conservan;
- nunca se concatena una segunda ejecución sobre un artefacto completo.

Los logs no incluirán filas clínicas. Solo contendrán nombres lógicos,
duraciones, hashes, estados y recuentos agregados permitidos.

## Invalidación

Un artefacto y todos sus descendientes se invalidan si cambia cualquiera de:

- checksum o snapshot de un input;
- SQL, función Python o dependencia clínica relevante;
- esquema o `schema_version`;
- cohorte, ventana, límites, unidades, itemids o política de missingness;
- versión de MIMIC-IV o pin de `mimic-code`;
- backend cuando pueda cambiar la semántica (timestamps, joins, decimales);
- resultado de un check que antes era válido.

El DAG de invalidación es:

```text
cohort_stays ──> hourly_grid ───────────────────────────────────────────┐
raw sources ──> component events ──> component hourly ─────────────────┤
                                                                        v
                                                                  sofa_hourly
```

Cambiar un mapeo de bilirrubina, por ejemplo, invalida
`liver_events`, `liver_hourly` y `sofa_hourly`, pero no los demás componentes.
Cambiar la cohorte o la rejilla invalida todos los componentes horarios y el
resultado final. Una actualización de una librería solo obliga a invalidar si
forma parte del entorno declarado; las diferencias de versión siempre se
registran, incluso cuando una validación explícita permita reutilización.

No se borra automáticamente una ejecución anterior: se conserva como evidencia
hasta aplicar la política institucional de retención segura. Una reconstrucción
genera un nuevo `run_id`, salvo recuperación de un artefacto incompleto con
idéntica identidad.

## Orden de construcción

El orden lógico y las oportunidades de paralelismo son:

1. Verificar release/snapshot, tablas fuente, configuración y espacio.
2. Construir `cohort_stays`.
3. Construir `hourly_grid`.
4. En paralelo, construir los ocho artefactos de eventos normalizados.
5. En paralelo, construir los seis componentes horarios:
   - respiratorio después de `respiratory_events`;
   - coagulación después de `coagulation_events`;
   - hepático después de `liver_events`;
   - cardiovascular después de `map_events` y `vasoactive_intervals`;
   - neurológico después de `cns_events`;
   - renal después de `creatinine_events` y `urine_events`.
6. Ensamblar `sofa_hourly`.
7. Ejecutar validación cruzada de recuentos y distribuciones contra el concepto
   oficial de la misma versión.
8. Solo entonces construir sospecha de infección, Sepsis-3 y shock.

Todos los nodos horarios dependen también de `hourly_grid`.

### Perfil demo en Raspberry Pi

- Datos: MIMIC-IV Demo v2.2; código normativo `mimic-code v2.4.0`.
- Motor de extracción: DuckDB; transformaciones compactas en pandas.
- Un Parquet por artefacto, compresión Zstandard y ejecución componente a
  componente para limitar memoria.
- Paralelismo conservador: se pueden preparar componentes independientes, pero
  no deben escanear simultáneamente varias copias completas de `chartevents`.
- Los notebooks orquestan, muestran controles agregados y reutilizan artefactos;
  la lógica y el estado de reanudación permanecen fuera del notebook.

### Perfil de servidor

- Datos: MIMIC-IV v3.1; código normativo `mimic-code v3.0.1`.
- Materialización preferente dentro de PostgreSQL o BigQuery, con exportación
  Parquet únicamente de tablas compactas necesarias para análisis.
- Procesamiento por lotes deterministas de cohorte o particiones estables; nunca
  por límites de fila sin orden.
- Índices/particiones por `stay_id` y tiempo en PostgreSQL, o particionado y
  clustering equivalentes en BigQuery.
- Consolidación final con comprobación de que cada `stay_id` pertenece a una
  sola partición y de que no existen claves duplicadas entre lotes.
- Comparación contra las tablas derivadas oficiales v3.1 antes de considerar el
  artefacto apto para etiquetas.

Los artefactos demo sirven para probar lógica y reproducibilidad, no son
intercambiables ni combinables con artefactos v3.1.

## Privacidad, retención y publicación

- La raíz `data/derived/` debe estar en `.gitignore` y no sincronizarse con
  servicios personales o no autorizados.
- Permisos recomendados: directorios `0700` y archivos `0600`, además de
  cifrado en reposo en el servidor.
- Los identificadores y fechas se conservan solo en los artefactos protegidos
  necesarios para enlaces. Se eliminan de matrices de predictores y resultados
  compartibles.
- No se guardan texto clínico, credenciales ni cadenas de conexión en Parquet,
  metadatos, manifiestos o logs.
- No se publican Parquet, DuckDB, manifiestos ni notebooks con salidas a nivel
  de paciente. Los informes públicos contienen únicamente agregados revisados,
  suprimiendo celdas pequeñas conforme al acuerdo de uso y política
  institucional.
- La eliminación al final de la retención debe abarcar artefactos, parciales,
  caches, copias de seguridad y snapshots, y quedar registrada sin exponer
  identificadores.

Un artefacto puede marcarse `validated` solo después de superar controles
estructurales, temporales y clínicos. `complete` significa que terminó su
construcción; no implica que sea correcto ni apto para modelado.
