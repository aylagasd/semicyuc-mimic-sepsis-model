"""Pure SOFA component scoring functions for validated clinical inputs."""

from __future__ import annotations

import math


def _missing(value: float | int | None) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))


def _reject_negative(value: float | int | None, name: str) -> None:
    if not _missing(value) and value < 0:
        raise ValueError(f"{name} must be non-negative")


def respiratory_score(pao2_fio2: float | None, invasive_ventilation: bool = False) -> int | None:
    """Score one PaO2/FiO2 observation with contemporaneous invasive ventilation.

    Score observations individually before selecting the worst score in a time
    window. Never combine a minimum ratio with ventilation at another time.
    """
    if _missing(pao2_fio2):
        return None
    _reject_negative(pao2_fio2, "pao2_fio2")
    if pao2_fio2 < 100 and invasive_ventilation:
        return 4
    if pao2_fio2 < 200 and invasive_ventilation:
        return 3
    if pao2_fio2 < 300:
        return 2
    if pao2_fio2 < 400:
        return 1
    return 0


def coagulation_score(platelets: float | None) -> int | None:
    """Score platelet count in 10^9/L."""
    if _missing(platelets):
        return None
    _reject_negative(platelets, "platelets")
    if platelets < 20:
        return 4
    if platelets < 50:
        return 3
    if platelets < 100:
        return 2
    if platelets < 150:
        return 1
    return 0


def liver_score(bilirubin_mg_dl: float | None) -> int | None:
    """Score total bilirubin in mg/dL."""
    if _missing(bilirubin_mg_dl):
        return None
    _reject_negative(bilirubin_mg_dl, "bilirubin_mg_dl")
    if bilirubin_mg_dl >= 12:
        return 4
    if bilirubin_mg_dl >= 6:
        return 3
    if bilirubin_mg_dl >= 2:
        return 2
    if bilirubin_mg_dl >= 1.2:
        return 1
    return 0


def cardiovascular_score(
    *,
    map_mmhg: float | None = None,
    dopamine: float | None = None,
    epinephrine: float | None = None,
    norepinephrine: float | None = None,
    dobutamine: float | None = None,
) -> int | None:
    """Score MAP and vasopressor doses in µg/kg/min (dobutamine: any dose)."""
    doses = [dopamine, epinephrine, norepinephrine, dobutamine]
    if _missing(map_mmhg) and all(_missing(value) for value in doses):
        return None
    for value, name in zip(doses, ["dopamine", "epinephrine", "norepinephrine", "dobutamine"]):
        _reject_negative(value, name)
    _reject_negative(map_mmhg, "map_mmhg")
    dopamine = 0 if _missing(dopamine) else dopamine
    epinephrine = 0 if _missing(epinephrine) else epinephrine
    norepinephrine = 0 if _missing(norepinephrine) else norepinephrine
    dobutamine = 0 if _missing(dobutamine) else dobutamine
    if dopamine > 15 or epinephrine > 0.1 or norepinephrine > 0.1:
        return 4
    if dopamine > 5 or epinephrine > 0 or norepinephrine > 0:
        return 3
    if dopamine > 0 or dobutamine > 0:
        return 2
    if not _missing(map_mmhg) and map_mmhg < 70:
        return 1
    return 0


def cns_score(gcs: float | None) -> int | None:
    """Score Glasgow Coma Scale total."""
    if _missing(gcs):
        return None
    if gcs < 3 or gcs > 15:
        raise ValueError("gcs must be between 3 and 15")
    if gcs < 6:
        return 4
    if gcs <= 9:
        return 3
    if gcs <= 12:
        return 2
    if gcs <= 14:
        return 1
    return 0


def renal_score(
    creatinine_mg_dl: float | None = None, urine_output_ml_24h: float | None = None
) -> int | None:
    """Return the worse score from creatinine and 24-hour urine output."""
    scores: list[int] = []
    _reject_negative(creatinine_mg_dl, "creatinine_mg_dl")
    _reject_negative(urine_output_ml_24h, "urine_output_ml_24h")
    if not _missing(creatinine_mg_dl):
        if creatinine_mg_dl >= 5:
            scores.append(4)
        elif creatinine_mg_dl >= 3.5:
            scores.append(3)
        elif creatinine_mg_dl >= 2:
            scores.append(2)
        elif creatinine_mg_dl >= 1.2:
            scores.append(1)
        else:
            scores.append(0)
    if not _missing(urine_output_ml_24h):
        if urine_output_ml_24h < 200:
            scores.append(4)
        elif urine_output_ml_24h < 500:
            scores.append(3)
        else:
            scores.append(0)
    return max(scores) if scores else None


def total_sofa(
    *components: int | None, mimic_missing_components_as_zero: bool = False
) -> int | None:
    """Sum six scores, optionally reproducing MIMIC's component imputation.

    This is distinct from the Sepsis-3 convention of assuming a *baseline total
    SOFA* of zero when prior organ dysfunction is unknown.
    """
    if len(components) != 6:
        raise ValueError("SOFA requires exactly six components")
    if not mimic_missing_components_as_zero and any(component is None for component in components):
        return None
    return sum(0 if component is None else component for component in components)
