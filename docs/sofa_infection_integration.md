# Integración temporal de infección sospechada, SOFA y Sepsis-3

## Propósito

Este documento especifica el contrato para convertir los pares auditables de
antimicrobiano–cultivo y el SOFA horario en episodios Sepsis-3. La etiqueta
puede confirmarse retrospectivamente con información posterior al inicio
estimado; los predictores de un landmark nunca pueden usar esa información.

La primera implementación debe producir artefactos derivados, no modificar las
tablas de infección ni SOFA originales. Toda elección de ventanas se guarda en
el manifiesto de ejecución.

## Entradas y granularidad

### Pares de infección sospechada

Una fila por par candidato de `pair_antibiotics_and_cultures`, con:

- claves `subject_id`, `hadm_id`, `antibiotic_id`, `culture_id`;
- `antibiotic_time`, `culture_time`, dirección y distancia del par;
- `t_si`, igual al evento más temprano;
- `t_si_confirmed_at`, igual al evento más tardío.

`t_si_confirmed_at` debe calcularse explícitamente en la integración. Es el
primer instante en que el par completo es observable, no el inicio clínico
estimado. La positividad del cultivo, la duración posterior del tratamiento y
los diagnósticos de alta no intervienen en la definición primaria.

### SOFA horario

Una fila por (`stay_id`, `hr`) con `endtime`, los seis componentes, el total
compatible con MIMIC (ausentes a cero), el total completo y el número de
componentes ausentes. Cada componente resume únicamente
`(endtime - 24 h, endtime]`.

La rejilla basada en frecuencia cardiaca sirve para compatibilidad con MIMIC
Code, pero no demuestra por sí sola cobertura completa alrededor de cada
infección. Los episodios cuyo intervalo requerido cae fuera de la rejilla deben
quedar marcados como no evaluables; no se extrapola el último SOFA ni se crea un
SOFA futuro mediante relleno hacia atrás.

## Asignación del episodio a la estancia UCI

Un par hospitalario es candidato para una estancia cuando su ventana de
asociación con disfunción orgánica, `[t_si - 24 h, t_si + 24 h]`, solapa la
estancia real `[intime, outtime)`. Si solapa varias estancias del mismo ingreso,
se evalúa en cada una y después se selecciona el primer inicio calificante por
estancia. No se enlaza por proximidad a una estancia de otro `hadm_id`.

Se conservan también los pares sin estancia compatible con
`exclusion_reason = no_overlapping_icu_stay`. Los eventos SOFA se relacionan por
`stay_id`; no se atribuyen mediciones entre estancias salvo que una futura
definición hospitalaria lo autorice de forma explícita.

## Convención temporal del SOFA

Para una hora de rejilla `e = endtime`, el valor representa el estado conocido
al terminar esa hora. Un valor medido exactamente en `e` puede contribuir a la
etiqueta en `e`; para predicción en un landmark `L`, las características deben
recalcularse con extremo derecho abierto y usar solo eventos `< L`.

La implementación primaria tendrá resolución horaria:

- horas candidatas agudas: `e` en `[t_si - 24 h, t_si + 24 h]`;
- horas basales: `e` en `[t_si - 48 h, t_si)`;
- `acute_sofa(e)`: `sofa_total` de la fila horaria;
- `baseline_sofa`: mínimo `acute_sofa(e)` entre las horas basales evaluables;
- `delta_sofa(e) = acute_sofa(e) - baseline_sofa`;
- `t0`: primer `e` agudo con `delta_sofa(e) >= 2`.

El mínimo basal aproxima el menor estado de disfunción observado antes del
episodio. No debe confundirse con tomar los peores componentes de toda la
ventana basal, que produciría un máximo y cambiaría el estimando. Si no hay
ninguna hora basal, la definición primaria presume baseline cero, siguiendo la
aproximación Sepsis-3, pero registra `baseline_assumed_zero = true`. Se reportará
por separado la sensibilidad que exige al menos una hora basal.

Debe conservarse `baseline_missing_components` y el perfil de missingness de la
hora de inicio. La sensibilidad de caso completo usa `sofa_complete`; no puede
reemplazar silenciosamente la etiqueta primaria.

Los límites exactos anteriores son deliberados:

- una fila exactamente en `t_si - 48 h` entra en baseline;
- una fila exactamente en `t_si` no entra en baseline y sí entra en agudo;
- una fila exactamente en `t_si + 24 h` entra en agudo.

## Resultado por episodio

El artefacto `sepsis_episodes` tiene una fila por par candidato y estancia, y
como mínimo:

| Campo | Significado |
|---|---|
| claves del par y `stay_id` | trazabilidad completa |
| `t_si`, `t_si_confirmed_at` | inicio estimado y disponibilidad del criterio |
| `baseline_sofa`, `baseline_time` | mínimo preinfección y primera hora que lo alcanza |
| `baseline_assumed_zero` | ausencia total de baseline evaluable |
| `peak_acute_sofa`, `peak_acute_time` | máximo de la ventana aguda, solo auditoría |
| `t0`, `sofa_at_t0`, `delta_sofa_at_t0` | primer incremento calificante |
| `sepsis3` | par más incremento SOFA de al menos 2 |
| `label_available_at` | `max(t0, t_si_confirmed_at)` |
| campos de completitud | cobertura de rejilla y componentes |
| `exclusion_reason` | motivo único, versionado y auditable |

`peak_acute_sofa` no determina `t0`: buscar primero el pico desplazaría el inicio
y puede introducir sesgo. `label_available_at` tampoco reemplaza a `t0`; sirve
para simulaciones de detección en tiempo real y para auditar cuánta anticipación
aparente depende de confirmación futura.

Cuando varios pares de una estancia producen el mismo episodio, el artefacto de
pares conserva todos. El artefacto `sepsis_stays` elige el menor `t0`; los
empates se resuelven de forma determinista por `t_si`, distancia del par e
identificadores fuente. No se deduplican pares antes de evaluar la asociación
SOFA, porque un par más tardío puede ser el primero que califique.

## Uso leakage-safe en modelos

La tabla de etiquetas y la tabla de características son DAG separados. Para un
landmark `L` y horizonte `H`:

- el paciente está en riesgo solo si no existe `t0 <= L`;
- el resultado positivo es `t0` en `(L, L + H]` en la convención primaria;
- las características usan exclusivamente eventos clínicos con tiempo `< L`;
- `t_si`, `t_si_confirmed_at`, `label_available_at`, tiempos/identificadores de
  pares y columnas derivadas de la etiqueta están prohibidos como predictores;
- resultados microbiológicos, duración del tratamiento y datos posteriores a
  `L` están prohibidos aunque confirmen retrospectivamente la etiqueta;
- el split se realiza por `subject_id` antes de cualquier ajuste aprendido.

La frontera del resultado debe congelarse junto al generador de landmarks. Si
se adopta `[L, L + H)` en lugar de `(L, L + H]`, debe cambiarse en ambos sitios
y en los tests; nunca pueden coexistir convenciones distintas.

Una evaluación de alerta retrospectiva reportará tanto anticipación respecto a
`t0` como respecto a `label_available_at`. La primera estima anticipación
clínica; la segunda evita presentar como detección observable una etiqueta que
solo quedó confirmada después.

## Validaciones obligatorias

Los tests sintéticos deben cubrir al menos:

1. límites inclusivos de las ventanas basal y aguda;
2. primer cruce de delta 2, aunque el pico ocurra después;
3. baseline mínimo observado y baseline cero marcado cuando no hay observación;
4. ausencia de cruce cuando baseline y SOFA agudo difieren menos de 2;
5. par que solapa una estancia, varias estancias y ninguna estancia;
6. múltiples pares, empate determinista y primer `t0` por estancia;
7. `label_available_at >= t0` y `>= t_si_confirmed_at`;
8. componentes ausentes conservados y sensibilidad de caso completo separada;
9. inserción de eventos después de `L` sin cambio en ninguna característica;
10. evento exactamente en `L` excluido de predictores;
11. sujeto íntegro en una única partición;
12. invariancia de la etiqueta al resultado/positividad posterior del cultivo.

Además se comprueban claves únicas, orden temporal posible, pertenencia al mismo
ingreso, cobertura de rejilla, incidencia por estancia y distribución de la
diferencia `label_available_at - t0`.

## Decisiones que deben congelarse antes de ejecutar MIMIC-IV completo

- [x] baseline mínimo observado con presunción cero como definición primaria;
- [ ] congelar el umbral mínimo de horas para la sensibilidad que exige
  baseline observado;
- confirmar resolución horaria o construir una rejilla independiente de la
  frecuencia cardiaca para episodios con cobertura insuficiente;
- fijar la convención exacta del intervalo de outcome del landmark;
- decidir si infecciones iniciadas antes de `intime` pueden producir sepsis
  incidente en UCI o se clasifican como prevalentes;
- congelar reglas de deduplicación de episodios y umbrales mínimos de
  completitud para análisis de sensibilidad.
