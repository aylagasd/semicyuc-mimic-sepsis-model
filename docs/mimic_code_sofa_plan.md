# Plan de conceptos MIMIC Code para SOFA dinámico

## Objetivo y alcance

Este documento fija el grafo mínimo de conceptos oficiales de MIT-LCP necesario
para reproducir el SOFA horario (ventana móvil de 24 horas) de MIMIC-IV. No es
una implementación: define versiones, dependencias y estrategia de ejecución
para el demo local v2.2 y para el futuro backend con MIMIC-IV v3.1.

El concepto canónico es `concepts/score/sofa.sql`. Genera una fila por hora de
estancia UCI y calcula cada componente con el peor valor de las 24 horas
anteriores. El SOFA total suma los seis componentes, imputando cero cuando un
componente completo no tiene observaciones. Esta conducta debe conservarse y
auditarse, no reinterpretarse silenciosamente.

## Versiones fijadas

No se debe usar `main`, porque el código y los mapeos pueden cambiar.

| Datos | Pin de `mimic-code` | Commit | Uso |
|---|---|---|---|
| MIMIC-IV Demo v2.2 | tag `v2.4.0` | `570ef01` | Desarrollo y pruebas locales |
| MIMIC-IV v3.1 | tag `v3.0.1` | `c7e0756` | Despliegue definitivo |

La [release v2.4.0](https://github.com/MIT-LCP/mimic-code/releases/tag/v2.4.0)
declara expresamente que fue construida con MIMIC-IV v2.2. La
[release v3.0.0](https://github.com/MIT-LCP/mimic-code/releases/tag/v3.0.0)
es la transición oficial de los conceptos derivados a MIMIC-IV v3.1 y mantiene
una instantánea separada para v2.2. Se recomienda el parche posterior
[v3.0.1](https://github.com/MIT-LCP/mimic-code/releases/tag/v3.0.1) para v3.1.

Por tanto, los resultados del demo y del despliegue se deben identificar con
ambas versiones (`mimic_data_version` y `mimic_code_version`). No se validará el
SOFA de v2.2 contra tablas derivadas actuales de BigQuery v3.1.

## Grafo mínimo

La fuente oficial organiza cada abstracción como una tabla derivada; véase el
[índice de conceptos MIMIC-IV](https://github.com/MIT-LCP/mimic-code/blob/main/mimic-iv/concepts/README.md)
y el [SOFA canónico](https://github.com/MIT-LCP/mimic-code/blob/main/mimic-iv/concepts/score/sofa.sql).

```text
icu.icustays
icu.chartevents ─┬─> icustay_times ─> icustay_hourly ───────────────┐
                 ├─> vitalsign (MAP) ────────────────────────────────┤
                 ├─> gcs ────────────────────────────────────────────┤
                 ├─> ventilator_setting ─┐                           │
                 ├─> oxygen_delivery ────┴─> ventilation ─┐          │
                 └─> weight_durations ─┐                  │          │
icu.outputevents ───> urine_output ────┴─> urine_output_rate ────────┤
icu.inputevents ─┬─> dopamine ───────────────────────────────────────┤
                 ├─> dobutamine ─────────────────────────────────────┤
                 ├─> epinephrine ────────────────────────────────────┤
                 └─> norepinephrine ─────────────────────────────────┤
hosp.labevents ──┬─> bg (PaO2/FiO2) ─────────────────────────────────┤
                 ├─> complete_blood_count (plaquetas) ───────────────┤
                 ├─> enzyme (bilirrubina) ───────────────────────────┤
                 └─> chemistry (creatinina) ─────────────────────────┤
                                                                    v
                                                              score/sofa
```

### Dependencias directas de `score/sofa.sql`

- `demographics/icustay_hourly.sql`: rejilla horaria por `stay_id`.
- `measurement/bg.sql`: PaO2 y FiO2 para el componente respiratorio.
- `treatment/ventilation.sql`: estado de ventilación que modifica los umbrales
  respiratorios.
- `measurement/vitalsign.sql`: presión arterial media.
- `measurement/gcs.sql`: Glasgow Coma Scale.
- `measurement/enzyme.sql`: bilirrubina total.
- `measurement/chemistry.sql`: creatinina.
- `measurement/complete_blood_count.sql`: plaquetas.
- `measurement/urine_output_rate.sql`: diuresis acumulada en 24 horas.
- `medication/dopamine.sql`, `dobutamine.sql`, `epinephrine.sql` y
  `norepinephrine.sql`: dosis de vasoactivos/inotrópicos.

`coagulation.sql` no es dependencia del SOFA oficial: las plaquetas proceden de
`complete_blood_count.sql`. Tampoco se necesita `vasopressin.sql` para reproducir
este SOFA concreto. No deben añadirse como si formaran parte de la definición
canónica; cualquier SOFA modificado se versionará como análisis separado.

### Dependencias transitivas

- `icustay_hourly` depende de `icustay_times`; este último usa `icustays` y
  `chartevents`.
- `ventilation` depende de `ventilator_setting` y `oxygen_delivery`; ambos se
  derivan de `chartevents`.
- `urine_output_rate` depende de `urine_output` (`outputevents`) y
  `weight_durations` (`chartevents` e `icustays`).
- Los cuatro conceptos vasoactivos leen `inputevents`.
- `bg`, `chemistry`, `complete_blood_count` y `enzyme` leen `labevents`; `bg`
  también utiliza mediciones de `chartevents`.

Los scripts y rutas enlazados arriba son la fuente normativa. Las versiones
PostgreSQL se generan automáticamente; por ejemplo, el
[SOFA PostgreSQL](https://github.com/MIT-LCP/mimic-code/blob/main/mimic-iv/concepts_postgres/score/sofa.sql)
documenta explícitamente el máximo móvil de 24 horas.

## Orden mínimo de materialización

1. Verificar tablas crudas y columnas requeridas: `icustays`, `chartevents`,
   `labevents`, `outputevents` e `inputevents`.
2. Construir en paralelo los conceptos hoja: `icustay_times`, `vitalsign`,
   `gcs`, `bg`, `chemistry`, `complete_blood_count`, `enzyme`,
   `ventilator_setting`, `oxygen_delivery`, `urine_output`,
   `weight_durations` y los cuatro vasoactivos.
3. Construir `icustay_hourly`, `ventilation` y `urine_output_rate`.
4. Construir `score/sofa.sql`.
5. Solo tras validar SOFA, enlazar con sospecha de infección y construir
   Sepsis-3; el [concepto oficial Sepsis-3](https://github.com/MIT-LCP/mimic-code/blob/main/mimic-iv/concepts/sepsis/sepsis3.sql)
   depende de `sofa` y `suspicion_of_infection`.

## Ejecución local con DuckDB

En la Raspberry Pi se usará DuckDB como motor de extracción/materialización,
no como biblioteca estadística. La estrategia será:

- trabajar exclusivamente con el demo v2.2 y el pin `v2.4.0`;
- portar o transpilar únicamente el subgrafo anterior, conservando en el
  repositorio el SQL adaptado y su procedencia (tag, commit y ruta original);
- materializar resultados intermedios como tablas DuckDB o Parquet, evitando
  cargar `chartevents`/`labevents` completos en pandas;
- limitar primero las tablas grandes a los `stay_id`, `hadm_id`, itemids y
  ventanas temporales de la cohorte;
- entregar a pandas/R únicamente tablas horarias compactas para auditoría,
  tests y gráficos;
- probar límites horarios, ventanas de 24 h, unidades, duplicados y ausencia de
  mediciones mediante datos sintéticos.

La release v2.5.0 introdujo conversión con SQLGlot y mejoras específicas de
DuckDB, pero no sustituye el pin v2.4.0 para resultados v2.2. Sus herramientas
pueden evaluarse como ayuda de transpiliación; el SQL clínico de referencia
seguirá siendo el del pin compatible con los datos.

## Backend de mayor capacidad

Para MIMIC-IV v3.1 se reconstruirá el mismo DAG con `mimic-code v3.0.1` en
BigQuery o PostgreSQL, preferentemente materializando los conceptos oficiales
antes de extraer la cohorte analítica. Si se usa BigQuery, los conceptos
pregenerados están disponibles para usuarios acreditados según la
[documentación oficial del repositorio](https://github.com/MIT-LCP/mimic-code/blob/main/mimic-iv/concepts/README.md),
pero se comprobará la tabla `_metadata` añadida en v3.0.1 para registrar la
versión de los datos.

La extracción final deberá ser por particiones temporales/cohorte, con tablas
intermedias persistentes e índices adecuados en PostgreSQL. DuckDB podrá seguir
leyendo exports Parquet para análisis, pero no será responsable de escanear el
MIMIC-IV completo en la Raspberry Pi.

## Validación obligatoria antes de usar SOFA como etiqueta

- Comparar recuentos por estancia/hora y distribuciones de los seis componentes
  con la tabla oficial derivada de la misma versión de MIMIC-IV.
- Auditar por separado disponibilidad y proporción imputada a cero de cada
  componente.
- Revisar casos frontera de ventilación, PaO2/FiO2, dosis vasoactivas, GCS y
  diuresis de 24 horas.
- Confirmar que cada fila horaria usa solo información disponible hasta esa
  hora; no usar valores posteriores para imputación ni selección.
- Mantener `sofa` (estado observado) separado de las variables predictoras y
  aplicar el horizonte de predicción antes de entrenar para evitar leakage.
- Registrar hashes de los SQL adaptados y comprobar diferencias entre los pins
  v2.4.0 y v3.0.1 antes de migrar resultados.

## Fuentes primarias

- [MIT-LCP/mimic-code](https://github.com/MIT-LCP/mimic-code)
- [Índice oficial de conceptos MIMIC-IV](https://github.com/MIT-LCP/mimic-code/blob/main/mimic-iv/concepts/README.md)
- [SOFA oficial](https://github.com/MIT-LCP/mimic-code/blob/main/mimic-iv/concepts/score/sofa.sql)
- [Releases oficiales y compatibilidad de versiones](https://github.com/MIT-LCP/mimic-code/releases)
- [Construcción oficial en BigQuery](https://github.com/MIT-LCP/mimic-code/blob/main/mimic-iv/buildmimic/bigquery/README.md)

