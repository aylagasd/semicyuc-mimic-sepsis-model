# Secuencia reproducible de notebooks

Los notebooks constituyen el recorrido visible y modificable del análisis. Se
ejecutan en orden numérico desde un entorno limpio. Cada notebook declara sus
entradas, salidas, versión de datos, semilla y criterios de finalización.

## Secuencia prevista

| Nº | Notebook | Kernel | Propósito |
|---:|---|---|---|
| 00 | `00_download_and_inspect_demo.ipynb` | Python | Descargar y verificar MIMIC-IV Demo v2.2. |
| 01 | `01_demo_tables.ipynb` | Python | Inventariar tablas y validar enlaces del demo local. |
| 02 | `02_cohort_profile.ipynb` | Python | Perfil preliminar de la cohorte adulta del demo local. |
| 03 | `03_define_cohort.ipynb` | Python | Reconstruir, auditar y comparar las políticas versionadas de cohorte adulta. |
| 04 | `04_suspected_infection.ipynb` | Python | Auditar fuentes y probar pares antibiótico-cultivo. |
| 05 | `05_confirm_antimicrobials.ipynb` | Python | Clasificar fármacos y contrastar administración EMAR. |
| 06 | `06_sofa_readiness.ipynb` | Python | Auditar cobertura, umbrales y riesgos del SOFA dinámico. |
| 07 | `07_sofa_and_outcomes.ipynb` | Python + R | Validar SOFA y etiquetas Sepsis-3, auditar resultados agregados y comparar `matplotlib` con `ggplot2`. |
| 08 | `08_initial_analysis.ipynb` | Python + R | Auditoría agregada de multiplicidad, cobertura y sensibilidad `sofa_complete`; figuras con `ggplot2`. |
| 09 | `09_feature_engineering.ipynb` | Python + R | Auditar landmarks, particiones y predictores temporales; comparar Matplotlib con `ggplot2` sin abrir el test. |
| 10 | `10_model_development.ipynb` | Python + R | Ensamblar el horizonte primario y validar referencias de prevalencia/regresión clínica sin abrir el test. |
| 11 | `11_model_evaluation.ipynb` | Python + R | Evaluación interna y comparación pareada con bootstrap por paciente; figura `ggplot2`, sin abrir test. |
| 12 | `12_sensitivity_and_subgroups.ipynb` | Python + R | Sensibilidades de cohorte, evidencia antimicrobiana, concurrencia del proxy de shock, horizonte y lookback; contrato de subgrupos con supresión por privacidad. |
| 13 | `13_final_report.ipynb` | Python + R | Informe pre-test; admite demo monolítico o fuente particionada development/validation explícita. En esta última proyecta horizonte/variables primarios y aplica el preflight de 32 GiB antes de modelos, utilidad, subgrupos, missingness, readiness de calibración y figuras `ggplot2`. |

La secuencia 00–13 está implementada. El paso 13 sigue siendo un informe previo
al test hasta ejecutar MIMIC-IV completo y congelar el modelo.

## Contrato de ejecución

- Un notebook no contiene lógica clínica duplicada: importa funciones desde
  `src/` o SQL versionado desde `sql/`.
- Cada salida persistida debe incluir versión/configuración y ser consumible por
  el siguiente paso sin estado oculto del kernel.
- Los datos a nivel de paciente permanecen bajo `data/` y nunca se versionan.
- Los notebooks versionados no contienen outputs sensibles ni grandes.
- `ggplot2` es el sistema gráfico principal. El notebook 07 compara
  explícitamente su salida con `matplotlib` usando exactamente la misma tabla
  agregada; esta comparación metodológica no cambia el estándar de publicación.
- Las figuras publicables se guardan mediante `ggsave()` en `reports/figures/`,
  con unidades, denominador, cohorte, horizonte e incertidumbre explícitos.
- Las pruebas automatizadas del código viven en `tests/`; un notebook puede
  mostrar sus resultados, pero no sustituye la suite de tests.

## Entorno

`environment.yml` instala Python, R, Jupyter, IRkernel y `ggplot2` en un único
entorno. Tras crearlo, ambos kernels deben aparecer en Jupyter. La ejecución
integral se automatizará cuando estén implementados los primeros outcomes.
