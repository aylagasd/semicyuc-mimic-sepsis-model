# Contrato de sensibilidades de sospecha de infección (D004)

## Alcance

Este contrato separa cambios de una sola dimensión respecto al primario. No
congela D004 ni convierte una variante en definición clínica aprobada. Cada
variante debe reconstruir pares, episodios Sepsis-3 y primer episodio por
estancia; no es válido filtrar retrospectivamente los positivos primarios.

La regla primaria mantiene administración EMAR confirmada, cultivo sanguíneo y
las ventanas asimétricas originales: cultivo hasta 24 horas después si el
antimicrobiano ocurre primero, o antimicrobiano hasta 72 horas después si el
cultivo ocurre primero. Esta operacionalización coincide con Seymour et al. y
con MIMIC Code, aunque el proyecto conserva su propia definición explícita de
baseline SOFA y tiempo de disponibilidad.

## Matriz preespecificada

| Variante | Cambio único | Estado técnico | Decisión clínica pendiente |
|---|---|---|---|
| `prescription_start` | Inicio de prescripción en vez de primera administración EMAR confirmada. | Implementada y materializada. | Confirmar si representa una sensibilidad suficientemente específica. |
| `all_specimens` | Cualquier espécimen microbiológico en vez de solo sangre. | Implementada y materializada. | Confirmar qué tipos de espécimen deben excluirse por contaminación, vigilancia o baja especificidad. |
| Ventanas alternativas | Cambiar 24/72 h manteniendo las demás reglas. | Parametrizable, pero sin valores activados. | Preespecificar valores y justificación antes de ejecutar MIMIC-IV completo. |
| Exclusión perioperatoria | Excluir profilaxis alrededor de procedimientos. | No implementada. | Definir fuente de procedimiento, intervalo, fármacos y tratamiento de cirugía urgente/infecciosa. |

`all_specimens` considera una colección por `micro_specimen_id`, aunque existan
varias filas de organismos. Usa `charttime` y, si falta, `chartdate`. No exige
resultado positivo: la etiqueta representa sospecha clínica, no infección
microbiológicamente confirmada.

## Invariantes verificables

1. Las ventanas incluyen exactamente sus límites.
2. Los dos eventos pertenecen al mismo `subject_id` y `hadm_id`.
3. `t_si` es el evento más temprano y `t_si_confirmed_at` se calcula después
   como el segundo evento del par.
4. Cada espécimen se cuenta una vez por ingreso.
5. La variante de alcance conserva evidencia antimicrobiana y ventanas del
   primario; la variante de prescripción conserva alcance y ventanas.
6. Todas las variantes se almacenan en formato largo con `sensitivity` y se
   comparan mediante agregados protegidos, nunca seleccionando la que produzca
   mejor prevalencia o rendimiento.

La configuración rechaza una variante idéntica al primario o que cambie más de
un eje. Las dos ventanas forman conjuntamente un solo eje temporal, por lo que
una variante puede modificar ambas sin mezclar además alcance o evidencia.

## Evidencia y revisión

- Seymour et al., *Assessment of Clinical Criteria for Sepsis* (JAMA, 2016),
  operacionaliza sospecha mediante antimicrobianos y toma de cultivos con
  ventanas asimétricas 24/72 h.
- Churpek et al., *Investigating the impact of different suspicion of
  infection criteria* (Critical Care Medicine, 2017), demuestra que elegir
  cualquier cultivo frente a cultivo sanguíneo cambia materialmente la cohorte
  y el rendimiento aparente.
- La consulta pública `suspicion_of_infection` de MIMIC Code se usa como
  referencia de portabilidad, no como sustituto de la firma clínica local.

Antes de congelar D004, infecciosas/farmacia e intensivos deben revisar los
agregados de cada variante en MIMIC-IV completo, la lista antimicrobiana y las
reglas perioperatorias. El hash del informe y de la configuración firmada debe
quedar registrado en el acta.
