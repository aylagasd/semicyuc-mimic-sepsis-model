# Initial modeling strategy

## 1. Purpose and estimand

Develop and internally validate models that estimate the probability of **incident** Sepsis-3 onset and, separately, septic shock onset within a prespecified future horizon among adult ICU patients who are event-free and observable at a prediction landmark. This is methodological research; performance in MIMIC-IV does not establish clinical validity, safety, utility or transportability.

The primary estimand is risk within 6 hours at each eligible hourly landmark. Secondary horizons are 3, 12 and 24 hours. Sepsis and septic shock are distinct binary tasks; a shock model conditional on established sepsis is a prespecified secondary task.

## 2. Risk sets and landmarks

- Begin landmarks after a minimum 6-hour ICU observation period; generate them hourly until the earliest of outcome onset, ICU discharge/death, or end of available data.
- A landmark at time `L` is eligible only if the patient is in ICU, has sufficient lookback availability, and has not met the target by `L`.
- Primary predictor lookback: `[L - 24 h, L)`. Secondary windows: 6 and 12 hours. Static features use only information available by `L`.
- Outcome interval for horizon `H`: `(L, L + H]`. An event exactly at `L` is
  prevalent and removes that landmark; an event exactly at `L+H` counts.
  Events after ICU discharge are not primary outcomes. Discharge before `L+H`
  without an observed event yields a censored/nullable label, never a control;
  an event observed before early discharge remains positive.
- To reduce dominance by long stays, retain all hourly landmarks with patient-level weighting or sample one/multiple landmarks under a prespecified scheme. Compare with one-landmark-per-stay analyses.

The index `L` is not selected retrospectively relative to onset for controls. Case-control sampling, if used for computation, occurs only within risk sets and uses sampling weights so predicted probabilities and calibration can be recovered.

## 3. Predictors and feature timing

Candidate features are defined in the versioned variable dictionary. For repeated measurements, compute count, missing indicator, last, minimum, maximum, mean, sample standard deviation, slope and time since last measurement over prespecified windows where clinically meaningful. The initial implemented matrix is declared in `config/features.json`. Laboratory values become available at `storetime`, not retrospectively at specimen `charttime`. Normalize units before aggregation and clip/winsorize only using training-set rules.

SOFA and its components may be evaluated in an explicit secondary model but are excluded from the parsimonious primary model if their inclusion makes the endpoint tautological. Treatment variables require special scrutiny because they can encode clinician recognition rather than underlying physiology.

### Leakage controls

- Feature SQL must enforce event time `< L`; never use a full-stay summary, discharge diagnosis, death outcome, later culture result, later antibiotic duration, later specimen positivity, or post-landmark documentation.
- Outcome-label queries and feature queries are separate. Outcome-defining events at exactly `L` are unavailable to predictors.
- Fit imputation, scaling, category grouping, feature selection, calibration and hyperparameter tuning on training data only, nested within resampling folds.
- Missingness indicators are allowed, but store/chart times and measurement frequency are included only after assessing whether they encode workflow artifacts.
- Do not use `subject_id`, `hadm_id`, `stay_id`, shifted calendar date, post-discharge codes, or label-derived variables as predictors.
- Automated tests should insert synthetic post-landmark events and verify features remain unchanged.

## 4. Cohort description and sample size

Construct a CONSORT-style flow of patients, admissions, stays, landmarks, events and exclusions. Report event prevalence per stay and per landmark, time-to-event, follow-up, class imbalance, missingness, and effective sample size accounting for repeated landmarks.

Before fitting, estimate required sample size for binary prediction using expected event fraction, anticipated model fit and number of candidate parameters. Effective complexity includes nonlinear terms and categories, not merely named variables. Reduce complexity or use stronger penalization if information is insufficient; do not select sample size from observed performance.

## 5. Data partitioning

All stays belonging to one `subject_id` must remain in one partition.

### Primary validation design

Use a **temporal split** based on an admission-time ordering that is meaningful within the deidentified dataset/version, with earlier patients for development and the latest approximately 20% for a locked test set. If shifted dates make cross-patient calendar ordering unsuitable in the installed version, use a patient-grouped random 70/15/15 split as primary and treat temporal validation as infeasible; document this before analysis.

- Development set: model specification and fitting.
- Inner patient-grouped cross-validation: hyperparameter tuning.
- Outer/grouped folds or bootstrap: internal optimism and uncertainty during development.
- Validation set (optional): model choice and calibration specification.
- Locked test set: exactly one final evaluation after freezing phenotype, features, models and thresholds.

No patient is shared across folds. Stratification is performed at patient level where possible. Report ICU type and outcome balance by partition. A grouped random split is a sensitivity analysis when temporal splitting is primary.

## 6. Models

1. Reference models: prevalence/intercept-only and a small prespecified clinical baseline.
2. Main interpretable model: penalized logistic regression (elastic net), with restricted cubic splines or prespecified transforms for continuous predictors.
3. Nonlinear comparator: gradient-boosted decision trees. Random forest is exploratory.

Hyperparameter search spaces, random seeds, stopping criteria and software versions are committed before locked-test evaluation. Class weighting may aid optimization but does not replace probability correction; resampling must not distort final calibration. Primary predictions remain continuous probabilities.

## 7. Missing data

Describe missingness by predictor, time window and partition. The primary pipeline uses training-derived simple/iterative imputation plus missingness indicators where appropriate, performed inside each fold. Multiple imputation is considered for regression inference and as sensitivity analysis. Tree-native missing handling is compared explicitly. Never impute outcomes, fabricate pre-ICU history, or use post-landmark measurements. Evaluate performance by missingness burden and ICU workflow strata.

## 8. Evaluation

Report patient-clustered 95% confidence intervals using bootstrap resampling of `subject_id` (target at least 1,000 successful replicates; seed fixed).

### Discrimination

- AUROC with confidence interval.
- AUPRC with event prevalence and a no-skill reference.
- Sensitivity, specificity, PPV, NPV and likelihood ratios at thresholds chosen without the test set.

### Calibration and overall accuracy

- Calibration-in-the-large (intercept) and calibration slope.
- Flexible calibration curve with uncertainty.
- Brier score and, where useful, scaled Brier score/log loss.
- Observed versus predicted risks in clinically interpretable bins.

If recalibration is needed, fit intercept/slope or isotonic calibration using development/validation data only and evaluate the frozen transformation on test data. Report pre- and post-recalibration results.

### Utility and operational behavior

Decision-curve analysis across prespecified plausible threshold probabilities is exploratory until a clinical action and harm/benefit tradeoff are defined. Also report alerts per 100 patient-days, proportion of ICU time under alert, median warning time, repeated-alert burden and performance per admission rather than only per row.

Do not claim benefit from AUROC/AUPRC alone. Thresholds must correspond to an intended action and require prospective evaluation.

## 9. Comparisons and uncertainty

Compare models on identical test observations using patient-clustered paired bootstrap differences in metrics. Avoid significance-driven model selection. Correct or qualify multiplicity for extensive subgroup/model comparisons. For dynamic landmarks, patient-level resampling is mandatory; naive row-level confidence intervals are invalid.

## 10. Prespecified sensitivity analyses

- Outcome-phenotype variants listed in `sepsis_definition.md`.
- Prediction horizons 3/6/12/24 hours and lookbacks 6/12/24 hours.
- First ICU stay per patient, first stay per admission, and all stays.
- Landmark sampling/weighting alternatives and exclusion gaps close to onset.
- Exclude antibiotics, cultures, vasopressors and SOFA-derived features to quantify recognition/label circularity.
- Patient-grouped random versus feasible temporal split.
- Death/discharge before horizon: complete-case, composite adverse outcome, and time-to-event/competing-risk formulations.
- Medical versus surgical ICU, sex, age groups, recorded race/ethnicity, admission source and missingness burden. These are heterogeneity checks, not proof of fairness.
- Calendar/ICU workflow drift and alternative imputation schemes.

Subgroups with few events are reported descriptively with uncertainty; no unsupported claims of equivalence are made.

## 11. Reproducibility and governance

- Pin MIMIC-IV schema/data version, SQL concepts, Python environment, random seeds and configuration hash.
- Save immutable cohort/feature manifests and aggregate data checks; never commit protected patient-level data.
- Track every test-set access. Changes prompted by test results require a new test set or are labeled exploratory.
- Produce a model card describing intended research use, exclusions, known biases and prohibited clinical use.
- Follow TRIPOD+AI and assess risk of bias/applicability with PROBAST+AI where applicable.

## 12. Decisions pending before extraction/modeling

- [ ] Freeze primary population rule (first stay/admission versus all stays).
- [ ] Confirm whether a valid cross-patient temporal ordering exists for the installed MIMIC-IV release.
- [x] Freeze primary 6-hour horizon, 24-hour lookback, hourly landmarks and
  outcome boundary `(L,L+H]` in `config/landmarks.json`.
- [ ] Define minimum predictor set, transforms and whether SOFA/treatments enter the primary model.
- [ ] Select landmark weighting/sampling and competing-event strategy.
- [ ] Perform formal sample-size calculation after phenotype counts are available.
- [ ] Define actionable thresholds and the intended clinical response before decision-curve interpretation.
- [x] Freeze locked-test access rules and start the append-only access log in `docs/test_access_log.md`.
