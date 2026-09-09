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
| 03 | `03_define_cohort.ipynb` | Python | Construir, auditar y comparar políticas de cohorte adulta. |
| 04 | `04_suspected_infection.ipynb` | Python | Auditar fuentes y probar pares antibiótico-cultivo. |
| 05 | `05_confirm_antimicrobials.ipynb` | Python | Clasificar fármacos y contrastar administración EMAR. |
| 06 | `06_sofa_readiness.ipynb` | Python | Auditar cobertura, umbrales y riesgos del SOFA dinámico. |
| 07 | `07_sofa_and_outcomes.ipynb` | Python + R | Validar SOFA y etiquetas Sepsis-3, auditar resultados agregados y comparar `matplotlib` con `ggplot2`. |
| 08 | `08_initial_analysis.ipynb` | Python + R | Auditoría agregada de multiplicidad, cobertura y sensibilidad; figuras con `ggplot2`. |
| 09 | `09_feature_engineering.ipynb` | Python/SQL | Crear landmarks y predictores temporales. |
| 10 | `10_model_development.ipynb` | Python | Entrenar los modelos preespecificados. |
| 11 | `11_model_evaluation.ipynb` | R | Discriminación, calibración y utilidad con `ggplot2`. |
| 12 | `12_sensitivity_and_subgroups.ipynb` | R | Sensibilidades y subgrupos con `ggplot2`. |
| 13 | `13_final_report.ipynb` | R | Tablas y figuras finales reproducibles. |

Los nombres posteriores al 02 son el plan inicial y se crearán cuando exista su
lógica y prueba correspondiente; no se añadirán notebooks vacíos como marcador.

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
