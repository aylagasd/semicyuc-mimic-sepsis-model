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
| D009 | frozen | Landmarks horarios desde 6 h de UCI; horizonte primario de 6 h y lookback de 24 h. | `config/landmarks.json`; `src/mimic_sepsis/landmarks.py` | Horizontes 3/12/24 h y lookbacks 6/12 h. |
| D010 | provisional | Proxy primario de shock: Sepsis-3, vasopresor y lactato >2 mmol/L concurrentes ±6 h y dentro de ±24 h de `t0`; la resucitación adecuada no se infiere y se marca como no verificada. | `config/septic_shock.json`; `src/mimic_sepsis/septic_shock.py` | Exigir fluidos documentados y/o MAP <65 será sensibilidad; requiere revisión clínica. |
| D011 | pending | Umbral de cobertura SOFA para declarar un episodio evaluable en el análisis principal. | Se audita `acute_window_covered`; aún no excluye | Debe congelarse tras revisar el demo y antes del conjunto completo. |
| D012 | frozen | Outcome futuro en `(L,L+H]`: un evento en `L` es prevalente; uno exactamente al final cuenta. Seguimiento corto sin evento se censura, no se convierte en control. | `config/landmarks.json`; `src/mimic_sepsis/landmarks.py` | La convención alternativa `[L,L+H)` queda descartada para evitar coexistencia ambigua. |
| D013 | frozen | Los signos vitales están disponibles en `charttime`; los laboratorios solo en `storetime` y se atribuyen a la estancia por el `charttime` de la muestra. Las ventanas predictoras son `[L-W,L)`. | `config/features.json`; `src/mimic_sepsis/feature_sources.py`; `src/mimic_sepsis/features.py` | Un laboratorio sin `storetime` no se backdata ni entra como predictor. |
| D014 | provisional | Conjunto inicial de diez variables para validar ingeniería: frecuencia cardiaca, MAP, frecuencia respiratoria, SpO2, temperatura, leucocitos, creatinina, bilirrubina, plaquetas y lactato. | `config/features.json` | La selección final, transformaciones y complejidad deben congelarse antes del test completo. |
| D015 | frozen | Development, validation y test se separan por `subject_id`; los artefactos son físicamente distintos y los notebooks de desarrollo no abren test. Todo acceso se registra. | `config/splits.json`; `src/mimic_sepsis/splits.py`; `docs/test_access_log.md` | El test del demo es una prueba de ingeniería, no una evaluación ciega. |
| D016 | provisional | El baseline clínico usa cinco resúmenes preespecificados de las últimas 24 h; la regresión imputa y escala dentro de cada fold. Los landmarks se ponderan para que cada paciente tenga igual peso total. | `config/modeling.json`; `src/mimic_sepsis/modeling.py`; notebook 10 | El demo solo valida ingeniería. Variables, penalización y ponderación se congelarán con el conjunto completo antes de abrir su test. |
| D017 | frozen | La incertidumbre y las comparaciones entre modelos remuestrean `subject_id` completos. Las diferencias son pareadas sobre las mismas réplicas; se intentan 1.000 réplicas con semilla fija. | `config/evaluation.json`; `src/mimic_sepsis/evaluation.py`; notebook 11 | Réplicas sin ambas clases producen métricas de discriminación no definidas y se contabilizan, no se sustituyen. |
| D018 | frozen | Las sensibilidades técnicas se ejecutan sobre la cuadrícula de horizontes 3/6/12/24 h y lookbacks 6/12/24 h, siempre sin test. Se comparan además las políticas de estancia de forma estructural. | `config/sensitivity.json`; `src/mimic_sepsis/sensitivity.py`; notebook 12 | En el análisis completo cada política de cohorte requerirá reconstrucción de extremo a extremo; los resultados del demo no seleccionan configuración. |

## Proceso de cambio

Cada nueva decisión recibe un identificador estable. Un cambio debe actualizar
en el mismo commit: este registro, el documento clínico correspondiente, la
configuración ejecutable, las pruebas de frontera y la versión/esquema de los
artefactos afectados.
