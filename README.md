# semicyuc-mimic-sepsis-model
# SEMICYUC – MIMIC-IV Sepsis Prediction Model

Proyecto de investigación orientado al desarrollo de un modelo predictivo de sepsis y shock séptico en UCI utilizando la base de datos MIMIC-IV.

## Objetivo

Desarrollar y validar un modelo predictivo para:

* Sepsis (Sepsis-3)
* Shock séptico
* Deterioro clínico/hemodinámico precoz
* Aplicable posteriormente a bases de datos clínicas españolas.

## Base de datos

[MIMIC-IV](https://pubmed.ncbi.nlm.nih.gov/36596836/)

Base de datos desarrollada por el MIT que contiene:

+ Datos demográficos

+ Variables hemodinámicas

+ Resultados analíticos

+ Medicación administrada

+ Eventos clínicos

+ Datos temporales de UCI

## Estrategia metodológica

* Extracción estructurada de variables clínicas

* Definición de sepsis (Sepsis-3?)

* Diseño y análisis estadístico

### Modelado:

- Logistic regression

- Random Forest

- Gradient Boosting

- XGBoost

- ???

### Validación:

+ AUROC

+ AUPRC

+ Calibration

+ Decision curve analysis


## Definición clínica

Se utilizarán criterios de:

* Sepsis-3

+ SOFA ≥ 2

+ Lactato > 2 mmol/L

+ Necesidad de vasopresores

# Futuras fases

* Validación externa en cohorte española

* Implementación en entorno hospitalario

* Desarrollo de dashboard clínico

# Investigadores Principales

XXXX
GT
Proyecto SEMICYUC
