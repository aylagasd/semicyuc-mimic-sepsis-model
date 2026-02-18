# Development and Internal Validation of a Predictive Model for Sepsis and Septic Shock in ICU Patients Using MIMIC-IV
### 1. Background and Rationale

Sepsis remains a leading cause of mortality in critically ill patients worldwide [1,2]. The introduction of the Sepsis-3 definition redefined sepsis as life-threatening organ dysfunction caused by a dysregulated host response to infection [1].

Large-scale ICU datasets such as MIMIC-IV enable reproducible development of predictive models [3]. However, clinically deployable models require rigorous methodology, appropriate validation, and transparent reporting [4].

This protocol defines a reproducible modeling framework aligned with TRIPOD recommendations [4] and modern predictive modeling standards [5].

### 2. Study Objectives
_Primary Objective_

To develop and internally validate a predictive model for:

Sepsis (Sepsis-3)

Septic shock

_Secondary Objectives_

Compare logistic regression with machine learning models

Evaluate calibration and clinical utility

Prepare model transportability assessment for external validation

### 3. Data Source

MIMIC-IV

Single-center ICU database

Adult critical care admissions

De-identified clinical data

Publicly accessible under credentialed use agreement [3]

### 4. Outcome Definitions
#### 4.1 Sepsis

Defined according to Sepsis-3 [1]:

Suspected infection

SOFA increase ≥ 2 points

Operational definition adapted from Seymour et al. [2].

#### 4.2 Septic Shock

Sepsis criteria met

Vasopressor requirement to maintain MAP ≥ 65 mmHg

Lactate > 2 mmol/L [1]

### 5. Study Design

Retrospective cohort study

Longitudinal time-series modeling

Supervised prediction framework

### 6. Candidate Predictors

Predictors will include:

Demographics

Physiological variables

Laboratory data

Organ dysfunction scores

Therapeutic interventions

Feature construction follows principles described by Steyerberg et al. [5].

### 7. Feature Engineering

Rolling time windows (6h / 12h / 24h)

Slopes and temporal deltas

Variability measures

Missingness indicators

Time-aware encoding consistent with modern dynamic prediction approaches.

### 8. Model Development
#### 8.1 Baseline Model

Logistic regression

Penalized regression (LASSO / Elastic Net)

Penalization reduces overfitting in high-dimensional settings [5].

#### 8.2 Machine Learning Models

Random Forest [6]

Gradient Boosting

XGBoost [7]

Hyperparameters tuned via cross-validation.

### 9. Sample Size and Overfitting Control

Sample size adequacy evaluated using contemporary guidance for prediction models [8].

Overfitting mitigation strategies:

Penalization

Bootstrap optimism correction

Internal validation

### 10. Missing Data Handling

Exploration of missingness mechanism

Multiple imputation when appropriate

Sensitivity analyses

### 11. Model Validation Strategy

Train / validation / test split

5-fold cross-validation

Bootstrap resampling (≥1000 iterations)

### 12. Performance Metrics
Discrimination

AUROC

AUPRC

Calibration

Calibration slope

Calibration plots

Brier score [9]

Clinical Utility

Decision Curve Analysis [10]

### 13. Model Interpretability

Coefficient analysis (logistic regression)

Feature importance

SHAP values for boosting models [11]

Interpretability prioritized to facilitate ICU adoption.

### 14. Sensitivity Analyses

Alternative sepsis definitions

Alternative prediction horizons

Subgroup analyses (medical vs surgical ICU)

### 15. Ethical Considerations

Use of fully de-identified data

Compliance with database use agreement

No patient-level identifiable data released

### 16. Reporting Standards

The study will adhere to:

TRIPOD reporting guidelines [4]

TRIPOD-AI extension for machine learning models [12]

### References

1. Singer M, Deutschman CS, Seymour CW, et al. The Third International Consensus Definitions for Sepsis and Septic Shock (Sepsis-3). JAMA. 2016;315(8):801–810.

2. Seymour CW, Liu VX, Iwashyna TJ, et al. Assessment of Clinical Criteria for Sepsis. JAMA. 2016;315(8):762–774.

3. Johnson AEW, Bulgarelli L, Shen L, et al. MIMIC-IV, a freely accessible electronic health record dataset. Sci Data. 2023;10:1.

4. Collins GS, Reitsma JB, Altman DG, Moons KGM. Transparent Reporting of a multivariable prediction model (TRIPOD). Ann Intern Med. 2015;162:55–63.

5. Steyerberg EW. Clinical Prediction Models. Springer; 2019.

6. Breiman L. Random Forests. Mach Learn. 2001;45:5–32.

7. Chen T, Guestrin C. XGBoost: A Scalable Tree Boosting System. KDD. 2016.

8. Riley RD, Snell KIE, Ensor J, et al. Minimum sample size for developing a multivariable prediction model. Stat Med. 2020;39:126–146.

9. Van Calster B, McLernon DJ, van Smeden M, et al. Calibration: the Achilles heel of predictive analytics. BMC Med. 2019;17:230.

10. Vickers AJ, Elkin EB. Decision curve analysis. Med Decis Making. 2006;26:565–574.

11. Lundberg SM, Lee SI. A Unified Approach to Interpreting Model Predictions. NeurIPS. 2017.

12. Wolff RF, Moons KGM, Riley RD, et al. PROBAST-AI and TRIPOD-AI. BMJ. 2023;370:m3160.
