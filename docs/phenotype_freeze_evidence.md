# Evidencia reproducible para revisar el fenotipo

## Propósito y límite de autoridad

Este procedimiento reúne agregados para la revisión de D002, D004, D010 y
D011. No selecciona la alternativa con el resultado más favorable, no cambia
`config/protocol_status.json` y no equivale a una firma clínica. El demo se usa
solo para comprobar el contrato y detectar consecuencias estructurales; sus
recuentos no estiman prevalencia ni rendimiento en MIMIC-IV completo.

El informe contiene recuentos agregados sin identificadores, pero no suprime
celdas pequeñas. Por ello se clasifica como derivado protegido, se crea con
permisos `0600`, permanece bajo `data/` y no se publica ni se incorpora a Git.

## Ejecución

Sobre una ejecución monolítica del demo:

```bash
python scripts/audit_phenotype_freeze.py \
  data/derived/sofa/<run_id>
```

Sobre una ejecución por lotes de MIMIC-IV completo, si el protocolo ya ha
autorizado esa fase:

```bash
python scripts/audit_phenotype_freeze.py \
  /ruta/derivados/full_pipeline/labels/<label_run_id>
```

El lector detecta ambos layouts, valida el checksum y la coherencia de versión
y configuración de los artefactos primarios de etiquetas y falla si falta alguno.
La salida por defecto es
`<label_run>/audit/phenotype_freeze_evidence.json`. La terminal solo muestra
versión, layout y SHA-256 del informe; los recuentos permanecen en el archivo
protegido. Volver a ejecutarlo sobre las mismas entradas y el mismo estado de
protocolo produce el mismo `report_sha256`, aunque cambie la hora de creación.

## Contenido y denominadores

| Tabla | Denominador | Uso |
|---|---|---|
| `phenotype_summary` | pares, ingresos, filas par–estancia o estancias, indicado por fila | Flujo general del fenotipo. |
| `infection_timing` | pares antimicrobiano–cultivo | Orden temporal de las dos evidencias de infección. |
| `pair_multiplicity` | ingresos con pares | Multiplicidad de candidatos por ingreso. |
| `coverage` | filas par–estancia | Cobertura aguda completa, parcial o no evaluable. |
| `coverage_sensitivities` | filas y estancias elegibles; estancias Sepsis-3 | Primario, baseline observado, ventana aguda completa y combinación. |
| `complete_sofa_sensitivities` | filas y estancias recalculadas con `sofa_complete` | Caso completo solo y combinado con baseline observado/cobertura física. |
| `sofa_completeness_at_t0` | primer episodio Sepsis-3 por estancia | Componentes ausentes en el `t0` primario. |
| `shock_proxy` | estancias Sepsis-3 | Proxy positivo/negativo y verificación de fluidos. |
| `shock_concurrency_sensitivities` | estancias Sepsis-3 por variante | Positivos, cambio absoluto y concordancia frente a la regla primaria. |
| `decision_evidence` | decisiones D002/D004/D010/D011 | Estado actual y evidencia que todavía falta. |

Los pares, las filas par–estancia y las estancias no son intercambiables. Cada
tabla conserva su unidad para evitar que un gran número de pares por ingreso se
interprete como un gran número de pacientes o desenlaces.

## Qué permite concluir para cada decisión

### D002 — política de cohorte

Una sola ejecución no compara políticas. Para revisar D002 hay que reconstruir
por separado las variantes preespecificadas —primera estancia por ingreso,
primera por paciente y todas las elegibles— y comparar flujo y consecuencias
agregadas. No se debe filtrar un único resultado ya construido para simular una
política distinta.

### D004 — sospecha de infección

El informe comprueba multiplicidad y orden temporal de los pares producidos por
la regla vigente. No valida la adecuación clínica de cada antimicrobiano ni
decide si deben entrar profilaxis, otras vías o cultivos no sanguíneos. La lista
versionada y las sensibilidades continúan requiriendo revisión de
infecciosas/farmacia e intensivos.

### D010 — proxy de shock séptico

Se auditan estancias positivas y negativas y se hace visible que la resucitación
adecuada con fluidos no se infiere. Las ventanas de concurrencia de 3 y 12 horas
se recalculan desde las fuentes y se comparan con la primaria de 6 horas; no se
derivan filtrando sus positivos. El informe verifica que cada variante evalúe
exactamente el mismo conjunto de estancias una sola vez. Estos agregados no
convierten el proxy EHR en diagnóstico clínico de shock ni sustituyen la firma
de su nombre, ventanas y sensibilidades de MAP/fluidos/lista restrictiva.

### D011 — cobertura y missingness SOFA

Las sensibilidades de baseline observado y cobertura aguda se recalculan antes
de contar estancias Sepsis-3. La distribución de componentes ausentes se
describe sobre el `t0` primario, una fila por estancia.

La sensibilidad «seis componentes completos» se deriva de nuevo desde el SOFA
horario: utiliza `sofa_complete` tanto para el mínimo basal como para cada hora
aguda y vuelve a buscar el primer cruce elegible. No elimina después los `t0`
incompletos, porque eso podría perder un cruce completo posterior y cambiaría la
pregunta. Se materializa por separado como
`sepsis_episodes_complete_sofa`/`sepsis_stays_complete_sofa`.

Las ejecuciones antiguas que todavía no contienen ambos artefactos siguen
siendo legibles, pero la tabla declara `available=false` y D011 conserva como
requisito pendiente el recálculo. Si aparece solo uno de los dos artefactos, el
informe falla: una sensibilidad parcial no es interpretable. En la combinación
con «ventana aguda completa», cobertura significa que existe rejilla física en
ambos extremos; no implica que los seis componentes estén observados en todas
las horas intermedias.

## Procedimiento de revisión y firma

1. Registrar `report_sha256`, `source.config_sha256`, versión de datos y commit.
2. Revisar los agregados en el entorno protegido, nunca copiando filas clínicas.
3. Contrastar cada tabla con las propuestas y sensibilidades del
   `clinical_freeze_dossier.md`.
4. Documentar justificación, revisor y fecha en el acta; una cifra del demo no
   puede ser la justificación principal.
5. Implementar cualquier cambio en configuración, código y pruebas dentro del
   mismo cambio versionado.
6. Solo entonces actualizar `decision_register.md` y
   `config/protocol_status.json` a `frozen`. La puerta de protocolo seguirá
   fallando hasta completar ese paso explícito.
