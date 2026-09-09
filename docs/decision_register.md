# Registro de decisiones metodológicas

Este archivo es el índice estructurado de decisiones del proyecto. Los
documentos enlazados contienen la justificación completa; la configuración
versionada contiene los valores que ejecuta el código. Una decisión `frozen`
no se modifica después de consultar el test bloqueado: cualquier alternativa
se implementa como sensibilidad o como nueva versión del protocolo.

## Estados

- `frozen`: decisión primaria aprobada e implementada.
- `provisional`: se usa en el demo, pendiente de auditoría antes de MIMIC-IV completo.
- `pending`: no debe asumirse ni implementarse silenciosamente.

## Decisiones

| ID | Estado | Decisión primaria | Implementación/configuración | Evidencia y sensibilidades |
|---|---|---|---|---|
| D001 | frozen | MIMIC-IV Demo v2.2 para desarrollo local; MIMIC-IV v3.1 previsto para el análisis completo. | `scripts/download_mimic_demo.py`; manifiestos de artefactos | `docs/mimic_code_sofa_plan.md` |
| D002 | provisional | Primera estancia UCI elegible por ingreso para el análisis primario de cohorte. | `src/mimic_sepsis/cohort.py` | Todas las estancias y primera por paciente serán sensibilidades. |
| D003 | frozen | Infección sospechada: antimicrobiano primero + cultivo en 24 h, o cultivo primero + antimicrobiano en 72 h; `t_si` es el evento anterior. | `src/mimic_sepsis/infection.py` | `docs/sepsis_definition.md` |
| D004 | provisional | Antimicrobiano sistémico confirmado por primera administración EMAR; cultivo de sangre en la definición primaria. | `config/antimicrobial_rules.csv`; `scripts/build_demo_sofa_incremental.py` | Prescripción y cultivos expandidos serán sensibilidades. La lista requiere revisión clínica antes del análisis completo. |
| D005 | frozen | SOFA horario: peor valor por componente en `(e-24 h, e]`; ausentes a cero en el total MIMIC y total completo conservado aparte. | `src/mimic_sepsis/sofa_*.py` | `docs/mimic_code_sofa_plan.md` |
| D006 | frozen | Baseline Sepsis-3: mínimo SOFA total horario en `[t_si-48 h, t_si)`; cero explícitamente marcado si no hay hora basal. | `config/sepsis3.json`; `src/mimic_sepsis/sepsis_labels.py` | Sensibilidad exigiendo baseline observado. |
| D007 | frozen | Ventana aguda `[t_si-24 h, t_si+24 h]`; `t0` es el primer cruce de incremento SOFA ≥2. | `config/sepsis3.json`; `src/mimic_sepsis/sepsis_labels.py` | `docs/sofa_infection_integration.md` |
| D008 | frozen | Separar inicio estimado (`t0`) de disponibilidad retrospectiva: `label_available_at=max(t0,t_si_confirmed_at)`. | `src/mimic_sepsis/sepsis_labels.py` | Ambos tiempos se auditan; ninguno se usa como predictor. |
| D009 | provisional | Landmarks horarios desde 6 h de UCI; horizonte primario de 6 h y lookback de 24 h. | Pendiente de notebook 09 | Horizontes 3/12/24 h y lookbacks 6/12 h. |
| D010 | provisional | Proxy primario de shock: Sepsis-3, vasopresor y lactato >2 mmol/L concurrentes ±6 h y dentro de ±24 h de `t0`; la resucitación adecuada no se infiere y se marca como no verificada. | `config/septic_shock.json`; `src/mimic_sepsis/septic_shock.py` | Exigir fluidos documentados y/o MAP <65 será sensibilidad; requiere revisión clínica. |
| D011 | pending | Umbral de cobertura SOFA para declarar un episodio evaluable en el análisis principal. | Se audita `acute_window_covered`; aún no excluye | Debe congelarse tras revisar el demo y antes del conjunto completo. |
| D012 | pending | Convención exacta del intervalo futuro de cada landmark. | No implementado | Elegir `(L,L+H]` o `[L,L+H)` de forma conjunta en etiquetas y tests. |

## Proceso de cambio

Cada nueva decisión recibe un identificador estable. Un cambio debe actualizar
en el mismo commit: este registro, el documento clínico correspondiente, la
configuración ejecutable, las pruebas de frontera y la versión/esquema de los
artefactos afectados.
