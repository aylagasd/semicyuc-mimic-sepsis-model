# Inventario SOFA en MIMIC-IV Demo v2.2

## Alcance

Inventario exploratorio de metadatos y cobertura agregada en las 140 estancias de
UCI del demo. Los recuentos de laboratorio incluyen únicamente mediciones entre
`icustays.intime` y `icustays.outtime`; los demás proceden de tablas ICU y ya
contienen `stay_id`. No se inspeccionan ni documentan filas individuales.

"Confirmado" significa que la etiqueta, el fluido y/o la unidad identifican la
medición requerida por SOFA. No implica que la transformación temporal o de
unidades esté terminada. "Pendiente" identifica proxies o variantes que no deben
entrar en la puntuación hasta validarlos.

## Resumen por componente

| Componente | Fuente principal | Candidatos confirmados | Eventos | Estancias (% de 140) | Unidades observadas | Trabajo pendiente |
|---|---|---|---:|---:|---|---|
| Respiratorio | `hosp.labevents`, `icu.chartevents`, `icu.procedureevents` | PaO2: 50821; FiO2: 223835; ventilación invasiva: 225792 | 743 PaO2; 1.746 FiO2; 65 episodios de ventilación | 87 (62,1%); 76 (54,3%); 60 (42,9%) | PaO2 `mm Hg`; FiO2 sin UOM; ventilación `min` | Emparejar PaO2/FiO2, normalizar FiO2 0–1 frente a 0–100 y definir soporte respiratorio en cada instante. |
| Coagulación | `hosp.labevents` | Plaquetas: 51265 | 847 | 133 (95,0%) | `K/uL` | Tratar duplicados y seleccionar el peor valor de cada ventana. |
| Hepático | `hosp.labevents` | Bilirrubina total: 50885, 53089 | 284 | 65 (46,4%) | `mg/dL` | Verificar equivalencia entre los dos itemids y política ante ausencia. |
| Cardiovascular | `icu.chartevents`, `icu.inputevents` | PAM: 220052; norepinefrina: 221906; epinefrina: 221289; dopamina: 221662; dobutamina: 221653 | 5.560 PAM; 1.055 eventos de los cuatro fármacos | 65 (46,4%); 35 (25,0%) | PAM `mmHg`; fármacos `mg` y `mcg/kg/min` | Reconstruir dosis activas, convertir a µg/kg/min y considerar peso/intervalos. |
| Neurológico | `icu.chartevents` | GCS ocular: 220739; verbal: 223900; motor: 223901 | 9.791 en conjunto | 140 (100%) | valores categóricos/numéricos sin UOM | Mapear categorías, sumar componentes contemporáneos y estudiar sedación/intubación. |
| Renal | `hosp.labevents`, `icu.outputevents` | Creatinina: 50912, 52546; orina: 226559, 226560, 226627, 226631 | 923 creatininas; 7.226 registros de orina | 137 (97,9%); 137 (97,9%) | creatinina `mg/dL`; orina `ml` | Sumar diuresis por ventana, evitar doble conteo y aplicar el peor criterio entre creatinina y volumen urinario. |

Los porcentajes son cobertura de presencia, no disponibilidad en cada landmark.

## Candidatos confirmados y variantes pendientes

### Respiratorio

- Confirmados: `50821` (`pO2`, sangre, gasometría), `223835` (`Inspired O2
  Fraction`) y `225792` (`Invasive Ventilation`).
- Pendientes: `52042` también se etiqueta `pO2`, pero su fluido es genérico
  (`Fluid`) y no debe combinarse con PaO2 arterial sin verificar el espécimen.
  `229280`/`229841` son FiO2 específica de ECMO/CH; `226260` (`Mechanically
  Ventilated`) existe en el diccionario pero tiene cero eventos en el demo.
- El cociente P/F no será válido hasta imponer proximidad temporal y estado de
  ventilación. Debe decidirse si se incorpora un proxy SpO2/FiO2 cuando falte PaO2.

### Coagulación

- Confirmado: `51265` (`Platelet Count`, sangre, hematología).
- Pendientes: `51704` también se denomina `Platelet Count`, pero está catalogado
  como química; `227457` y `225678` son registros ICU/variantes y no deben
  sustituir automáticamente al laboratorio central.

### Hepático

- Confirmados: `50885` y `53089`, ambos `Bilirubin, Total`, sangre, química y
  expresados en `mg/dL` en el demo.
- Pendientes/excluidos: bilirrubina directa, indirecta, neonatal y de otros
  fluidos; `225690` (chart ICU) y `226998` (APACHE IV) son duplicado/proxy y score,
  respectivamente.

### Cardiovascular

- Confirmados: `220052` para PAM y los cuatro vasopresores SOFA (`221906`,
  `221289`, `221662`, `221653`).
- Pendiente: `229617` (`Epinephrine.`) parece una variante del mismo fármaco,
  pero requiere comprobar su semántica y solapamiento antes de incluirlo.
- Una cantidad administrada en `mg` no equivale a una dosis activa. La
  puntuación exige intervalos de infusión, tasa, peso y normalización de unidad.

### Neurológico

- Confirmados: `220739`, `223900` y `223901`, los tres componentes de GCS.
- Pendientes/excluidos: campos derivados APACHE (`227011`–`227014`, entre otros)
  no serán la fuente primaria. Debe definirse cómo tratar verbal intubado y
  mediciones bajo sedación.

### Renal

- Confirmados: creatinina sanguínea `50912` y `52546`; orina Foley `226559`,
  micción `226560`, orina de quirófano `226627` y PACU `226631`.
- Pendientes: `52024` (`Creatinine, Whole Blood`) puede ser válido, pero pertenece
  a gasometría y se mantendrá separado hasta comprobar comparabilidad. El balance
  `227489` (`GU Irrigant/Urine Volume Out`, 31 eventos/3 estancias) puede mezclar
  irrigación con orina y no se sumará sin una regla de corrección. `226566` es una
  salida combinada y tampoco es una medición urinaria primaria.

## Implicaciones para la implementación

1. Construir tablas largas con `stay_id`, tiempo clínico, valor y unidad; no
   calcular SOFA directamente desde tablas anchas del notebook.
2. Probar normalización de FiO2 y dosis de vasopresores con casos sintéticos antes
   de aplicarlas al demo.
3. Calcular cada subscore en ventanas temporales explícitas y conservar tanto el
   valor fuente como el motivo de ausencia.
4. Auditar cobertura por ventana/landmark; los porcentajes de este documento sólo
   prueban que la señal aparece alguna vez durante la estancia.
5. Validar los itemids contra los conceptos versionados de MIMIC Code antes del
   análisis completo y mantener cualquier ampliación como sensibilidad.
