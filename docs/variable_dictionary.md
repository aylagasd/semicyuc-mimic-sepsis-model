# Variable Dictionary  
## SEMICYUC – MIMIC-IV Sepsis Prediction Model

---

## 1. Overview

This document defines all candidate predictors, derived variables, and outcomes used in the development of the sepsis and septic shock prediction model.

Each variable includes:

- Clinical meaning
- Source table (MIMIC-IV)
- Operational definition
- Units
- Time handling
- Preprocessing notes

All definitions are reproducible via SQL extraction and Python feature engineering scripts.

---

# 2. Demographics (Static Variables)

| Variable | Source Table | Definition | Unit | Notes |
|------------|-------------|------------|------|-------|
| age | patients | Age at ICU admission | years | Ages >89 truncated in MIMIC |
| sex | patients | Biological sex | categorical | M/F |
| ethnicity | admissions | Ethnicity group | categorical | Collapsed categories |
| admission_type | admissions | Admission type | categorical | Emergency / Urgent / Elective |
| admission_location | admissions | Source of admission | categorical | ED / Ward / OR |

Static variables are constant per ICU stay.

---

# 3. Physiological Variables (Time-Series)

Extracted primarily from `chartevents`.

For each rolling window (6h / 12h / 24h) we compute:

- mean
- min
- max
- std
- slope
- last_value

---

## 3.1 Hemodynamic Variables

| Variable | Clinical Meaning | Unit |
|------------|-----------------|------|
| heart_rate | Heart rate | bpm |
| map | Mean arterial pressure | mmHg |
| sbp | Systolic blood pressure | mmHg |
| dbp | Diastolic blood pressure | mmHg |

Derived variables:

- delta_map = slope(map)
- hypotension_flag = map < 65 mmHg

---

## 3.2 Respiratory Variables

| Variable | Clinical Meaning | Unit |
|------------|-----------------|------|
| resp_rate | Respiratory rate | breaths/min |
| spo2 | Peripheral oxygen saturation | % |
| fio2 | Fraction of inspired oxygen | % |
| pao2 | Arterial oxygen pressure | mmHg |

Derived variables:

- pao2_fio2_ratio
- resp_rate_variability
- hypoxemia_flag = pao2_fio2_ratio < 300

---

## 3.3 Temperature

| Variable | Clinical Meaning | Unit |
|------------|-----------------|------|
| temperature | Core body temperature | °C |

Derived:

- fever_flag = temperature > 38.3
- hypothermia_flag = temperature < 36

---

# 4. Laboratory Variables (Time-Series)

Extracted from `labevents`.

Aggregated using identical windowing strategy as physiological variables.

---

## 4.1 Infection / Inflammatory Markers

| Variable | Unit | Notes |
|------------|------|------|
| wbc | 10^9/L | White blood cell count |
| neutrophils | % | If available |
| crp | mg/L | If available |
| procalcitonin | ng/mL | If available |

Derived:

- leukocytosis_flag
- leukopenia_flag

---

## 4.2 Organ Dysfunction Markers

| Variable | Unit | Notes |
|------------|------|------|
| creatinine | mg/dL | Renal function |
| bilirubin | mg/dL | Hepatic function |
| platelets | 10^9/L | Coagulation |
| lactate | mmol/L | Tissue hypoperfusion |

Derived:

- delta_creatinine
- lactate_trend
- hyperlactatemia_flag = lactate > 2 mmol/L

---

## 4.3 Arterial Blood Gases

| Variable | Unit |
|------------|------|
| ph | unitless |
| paco2 | mmHg |
| hco3 | mmol/L |
| base_excess | mmol/L |

Derived:

- metabolic_acidosis_flag
- respiratory_acidosis_flag

---

# 5. Therapeutic Variables (Time-Dependent)

---

## 5.1 Vasopressors

Extracted from `inputevents`.

| Variable | Definition | Unit |
|------------|------------|------|
| norepinephrine_rate | Continuous infusion rate | mcg/kg/min |
| vasopressor_flag | Any vasopressor active | binary |
| vasopressor_load | Standardized dose sum | normalized |

Shock criterion component:
vasopressor_flag = 1 AND lactate > 2

## 5.2 Fluids

| Variable | Definition | Unit |
|------------|------------|------|
| fluid_balance_6h | Net fluid balance | mL |
| fluid_balance_24h | Net fluid balance | mL |

---

## 5.3 Mechanical Ventilation

| Variable | Definition | Unit |
|------------|------------|------|
| mech_vent_flag | Invasive ventilation | binary |
| peep | Positive end-expiratory pressure | cmH2O |
| tidal_volume_ml_kg | Tidal volume normalized to PBW | mL/kg |

---

# 6. Clinical Scores (Derived)

---

## 6.1 SOFA Score (Dynamic)

Components:

- Respiratory (PaO2/FiO2)
- Coagulation (Platelets)
- Liver (Bilirubin)
- Cardiovascular (MAP / vasopressors)
- CNS (if available)
- Renal (Creatinine / urine output)

Variables:

| Variable | Definition |
|------------|------------|
| sofa_total | Sum of components |
| delta_sofa | Change from baseline |

Sepsis operational rule:
delta_sofa >= 2 AND suspected_infection = 1


---

## 6.2 qSOFA

Criteria:

- RR ≥ 22
- SBP ≤ 100
- Altered mentation (if available)

---

# 7. Outcome Variables

---

## 7.1 Suspected Infection

Operational definition:

- Antibiotic administration
AND
- Culture request

Binary variable:

suspected_infection = 1/0

Timestamp:

t_infection

---

## 7.2 Sepsis

sepsis = suspected_infection AND delta_sofa >= 2

Timestamp:

t_sepsis

---

## 7.3 Septic Shock

Timestamp:

t_shock


---

# 8. Missing Data Strategy

For each time-dependent variable:

- missing_indicator created
- Imputation strategy defined in modeling stage
- Sensitivity analysis without imputation

---

# 9. Time Encoding for Modeling

Final modeling dataset columns:

| Column | Description |
|------------|------------|
| subject_id | Patient ID |
| hadm_id | Hospital admission ID |
| icu_stay_id | ICU stay ID |
| t_pred | Prediction timestamp |
| lookback_hr | Window size |
| horizon_hr | Prediction horizon |
| feature_* | Engineered predictors |
| label_sepsis | Binary outcome |
| label_shock | Binary outcome |

---

# 10. Variable Categories for Modeling

### Static
- age
- sex
- admission_type

### Dynamic
- Vital signs
- Lab values
- Therapeutics
- SOFA components

---

# Current Version

v0.2 – Feature Definition Phase





