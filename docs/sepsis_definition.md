# Operational definition of sepsis and septic shock in MIMIC-IV

## 1. Scope and status

This document specifies the initial, reproducible outcome-labeling algorithm for a retrospective prediction study using MIMIC-IV. It is a research phenotype, not a clinical diagnostic rule, and has not been externally or prospectively validated. Database version, code version, item identifiers and all deviations from this specification must be recorded with each analysis.

## 2. Population and unit of analysis

- Include ICU stays in `mimiciv_icu.icustays` linked to `mimiciv_hosp.admissions` and `patients`.
- Include adults aged at least 18 years at hospital admission. Use the MIMIC-IV anchor-age convention and cap/report ages according to the database documentation.
- Exclude stays with invalid/non-positive duration or missing linkage/timestamps. Do not exclude early deaths or short stays merely on prognosis grounds; eligibility for a prediction landmark is handled separately.
- A patient may have several admissions and ICU stays in descriptive analyses. The prediction unit is an **ICU stay–landmark pair**, while all data splitting and uncertainty procedures are grouped by `subject_id`.
- Primary analysis (provisional until full-dataset counts are reviewed): first eligible ICU stay per hospital admission. Sensitivity analyses: first ICU stay per patient and all eligible stays with patient-clustered inference. The implementation and audit rules live in `src/mimic_sepsis/cohort.py` and are demonstrated in notebook 03.

## 3. Time conventions

All timestamps are interpreted within a patient's internally shifted MIMIC-IV timeline. They must never be compared as real calendar dates between patients.

- `icu_intime`: start of risk follow-up.
- `t0`: estimated sepsis onset (defined below).
- Measurements use their clinical event time (`charttime`, `starttime`, specimen time), not store time.
- Intervals are half-open unless stated otherwise: `[start, end)`. At identical timestamps, conservative leakage control excludes outcome-defining information from predictors.
- Duplicate events are deduplicated using a documented source-specific key; implausible values and unit conversions are handled before scoring.

## 4. Suspected infection

### 4.1 Primary implementation

Suspected infection is an antibiotic–culture pair, adapted from the Sepsis-3 electronic phenotype:

1. **Antibiotic first:** a qualifying systemic antimicrobial starts, followed by collection of a qualifying microbiology culture within 24 hours.
2. **Culture first:** a qualifying culture is collected, followed by a qualifying antimicrobial start within 72 hours.

The suspected-infection time `t_si` is the earlier timestamp in the qualifying pair. If several pairs qualify, use the earliest pair that also satisfies the organ-dysfunction rule. Retain all candidate pairs in an audit table.

Antimicrobial administrations should be derived from medication administration/order tables appropriate to the installed MIMIC-IV version (for example `emar`/`emar_detail` and prescriptions), using a version-controlled whitelist of systemic antibacterials and antifungals. Topical, ophthalmic, otic, prophylaxis-only and non-systemic routes are excluded where route is known. A primary sensitivity analysis requires evidence of administration rather than prescription alone.

Qualifying cultures come from `microbiologyevents` and use specimen collection (`charttime`) where available. Blood cultures are the primary definition; a sensitivity analysis includes urine, respiratory, CSF and other normally sterile-site cultures. Culture positivity is not required because it is future information and would select only microbiologically confirmed infection.

### 4.2 Ambiguities to record

- Do not infer infection from ICD codes in the primary phenotype.
- Repeated doses belonging to one treatment episode are collapsed; the episode gap and antimicrobial whitelist are versioned configuration parameters.
- Antibiotic prophylaxis around surgery can mimic suspected infection. Planned sensitivity analyses exclude pairs near elective surgery and/or require treatment continuation (e.g. at least 48 hours), while recognizing survivor bias introduced by duration requirements.
- Exact MIMIC-IV tables and item mappings are **pending verification against the installed database version**.

## 5. Organ dysfunction and Sepsis-3 phenotype

Compute total SOFA using six components (respiratory, coagulation, liver, cardiovascular, central nervous system and renal) with explicit item mappings and standard thresholds. Score each component by the worst eligible value in the defined window. Treatment variables used by SOFA (ventilation and vasopressors) must be timestamped.

For every suspected-infection episode:

- **Baseline SOFA:** minimum total SOFA observed on the hourly grid in
  `[t_si - 48 h, t_si)`. The hourly total itself uses the worst eligible value
  of each component in its preceding 24-hour window. If no baseline hour is
  observable, baseline is assumed to be zero and explicitly flagged; requiring
  an observed baseline is a prespecified sensitivity analysis.
- **Acute SOFA:** rolling/worst SOFA assessed from `[t_si - 24 h, t_si + 24 h]`.
- **Sepsis:** increase in total SOFA of at least 2 points relative to baseline, temporally associated with suspected infection.
- **Onset `t0`:** earliest time in `[t_si - 24 h, t_si + 24 h]` at which the computable SOFA increase first reaches 2. Component state is carried only for a prespecified clinically plausible validity interval; no backward filling from future measurements.

Because MIMIC often lacks a reliable premorbid SOFA, scoring missing pre-infection components as zero approximates the Sepsis-3 convention but can misclassify chronic dysfunction. Therefore report missingness by component and perform sensitivity analyses using: (a) total SOFA at least 2 without subtraction; (b) a 24-hour versus 48-hour baseline; and (c) exclusion/adjustment for documented chronic renal, hepatic, respiratory or neurologic dysfunction.

Patients already meeting the phenotype at or before the first prediction landmark are prevalent cases and are excluded from incident-onset risk sets, but described separately. This does not exclude them from descriptive phenotype analyses.

## 6. Septic shock phenotype

Primary research definition requires all of the following:

1. Sepsis phenotype above.
2. Vasopressor therapy temporally compatible with shock and required to maintain mean arterial pressure at least 65 mmHg.
3. Lactate greater than 2 mmol/L (>18 mg/dL) after adequate volume resuscitation.

Operationally, identify a qualifying vasopressor infusion (norepinephrine, epinephrine, vasopressin, dopamine or phenylephrine; whitelist versioned) and lactate >2 mmol/L within a symmetric six-hour window. Shock onset is the later time at which both criteria have become observable. Require the pair within 24 hours before to 24 hours after `t0` in the primary analysis.

La implementación provisional vive en `src/mimic_sepsis/septic_shock.py` y sus
parámetros en `config/septic_shock.json`. Normaliza lactato a mmol/L, conserva
su tiempo de disponibilidad y produce `shock_t0` y
`shock_label_available_at`. El campo `adequate_fluids_verified` permanece falso
en el proxy primario: no se interpreta como ausencia de fluidoterapia, sino
como imposibilidad de verificar fielmente esta cláusula con la regla actual.
La definición se apoya en los criterios originales de
[Sepsis-3](https://doi.org/10.1001/jama.2016.0287) y su
[derivación clínica](https://doi.org/10.1001/jama.2016.0289).

“Adequate volume resuscitation” and “vasopressors required to maintain MAP” cannot be perfectly reconstructed from observational EHR data. The primary proxy and alternatives must therefore be reported explicitly:

- primary proxy: vasopressor infusion plus lactate criterion, with crystalloid/colloid exposure summarized but not used as an unverified causal requirement;
- sensitivity: require a documented fluid bolus in the preceding six hours;
- sensitivity: require MAP <65 mmHg before/at vasopressor start;
- sensitivity: restrict vasopressor selection and vary concurrency windows (3/6/12 hours).

## 7. Label construction and audit outputs

Label code must produce one row per candidate infection episode and an episode-level audit trail containing `subject_id`, `hadm_id`, `stay_id`, antibiotic/culture identifiers and times, component SOFA values/times, baseline and acute SOFA, `t_si`, `t0`, vasopressor/lactate times, phenotype flags and exclusion reason. A stay-level table then identifies the first qualifying onset.

Required quality checks include impossible temporal ordering, events outside admission, duplicate episodes, frequency by ICU/year, incidence per 100 stays and per 1,000 ICU-days, SOFA component completeness, and manual review of a reproducibly sampled set of records.

## 8. Prespecified sensitivity definitions

- Blood culture only versus expanded specimen set.
- Administration-confirmed versus prescription-based antimicrobial exposure.
- Alternative antibiotic–culture pairing windows.
- SOFA baseline/acute windows and missing-baseline assumptions.
- Sepsis onset anchored at `t_si` versus first SOFA increase.
- Septic shock concurrency and fluid/MAP proxies.
- CDC Adult Sepsis Event or diagnosis-code phenotypes as secondary comparators, never silently mixed with the primary outcome.

## 9. Decisions pending before model fitting

- [ ] Pin MIMIC-IV and derived/concepts code versions.
- [ ] Approve antimicrobial, culture, vasopressor and SOFA item mappings.
- [ ] Choose medication episode gap and administration evidence hierarchy.
- [x] Freeze primary SOFA baseline as the minimum observed hourly total over
  48 hours, with an explicitly flagged zero assumption when no hour exists.
- [ ] Choose physiologic carry-forward validity intervals for dynamic SOFA.
- [ ] Confirm primary shock fluid-resuscitation proxy.
- [ ] Quantify phenotype agreement and complete blinded chart-level plausibility review.

Any decision above must be frozen in configuration before final test-set evaluation.
