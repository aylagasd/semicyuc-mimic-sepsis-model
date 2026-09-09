# semicyuc-mimic-sepsis-model
# SEMICYUC – MIMIC-IV Sepsis Prediction Model

Proyecto de investigación orientado al desarrollo de un modelo predictivo de sepsis y shock séptico en UCI utilizando la base de datos MIMIC-IV.

Para comprender el proyecto completo y reproducir su estado actual, comience
por la **[guía narrativa para investigadores y revisores](docs/project_guide.md)**.

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

## Estado del proyecto

El repositorio dispone ya de fenotipo, landmarks, características temporales y
baselines técnicos reproducibles sobre el demo. El código es exclusivamente para investigación y no está
validado para tomar decisiones clínicas.

## Inicio rápido

Requisitos: Python 3.10 o posterior, acceso autorizado a MIMIC-IV cargado en
PostgreSQL y credenciales de solo lectura.

El análisis utiliza dos kernels Jupyter: Python para descarga, SQL y pipelines;
R para visualización con `ggplot2`. El entorno completo está definido en
`environment.yml`. La secuencia canónica está documentada en
`notebooks/README.md`.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[analysis,dev]'
cp config/mimic.env.example config/mimic.env
```

Edite `config/mimic.env` con su conexión local. Este archivo está excluido de
Git. Exporte las variables y lance Jupyter:

```bash
set -a
source config/mimic.env
set +a
jupyter lab
```

Los tres primeros notebooks son:

1. `notebooks/00_download_and_inspect_demo.ipynb`: descarga y verifica la muestra
   pública MIMIC-IV Demo v2.2 y prueba sus tablas localmente con DuckDB.
2. `notebooks/01_demo_tables.ipynb`: comprueba localmente las tablas y relaciones
   esenciales del demo sin solicitar credenciales.
3. `notebooks/02_cohort_profile.ipynb`: construye el perfil adulto preliminar,
   estancia UCI, mortalidad agregada y reingresos sobre el demo local.

La muestra también puede descargarse sin abrir Jupyter:

```bash
python scripts/download_mimic_demo.py
```

El demo oficial contiene 100 pacientes y se usa solo para pruebas funcionales.
No debe utilizarse para entrenar el modelo, validar rendimiento ni estimar
prevalencias. El acceso al MIMIC-IV completo exige credenciales personales de
PhysioNet; nunca se guardan en este repositorio.

### Descarga protegida desde PhysioNet

Cuando se despliegue el pipeline en el equipo de mayor capacidad, la descarga
completa se realizará de forma interactiva para evitar contraseñas en comandos,
scripts, historial o notebooks:

```bash
wget --user "USUARIO_PHYSIONET" --ask-password -r -N -c -np \
  https://physionet.org/files/mimiciv/3.1/
```

El usuario debe disponer de acceso aprobado a esa versión. No usar
`--password`, no compartir las credenciales y no copiar los datos descargados al
repositorio. Antes de ejecutar la descarga completa se confirmarán espacio,
versión y backend del servidor de cálculo.

Para validar el módulo sin una base MIMIC-IV real:

```bash
pytest -q
```

## Pasos iniciales de investigación

1. Registrar la versión exacta de MIMIC-IV y de los conceptos de `mimic-code`.
2. Verificar acceso a `mimiciv_hosp`, `mimiciv_icu` y, si se usa,
   `mimiciv_derived` mediante el primer notebook.
3. Congelar la cohorte, la unidad de análisis y las decisiones pendientes de
   `docs/sepsis_definition.md`.
4. Implementar en SQL versionado sospecha de infección, SOFA, sepsis y shock,
   manteniendo separadas etiquetas y características.
5. Ejecutar controles agregados de calidad y prevalencia antes de construir
   predictores.
6. Crear landmarks y ventanas temporales con pruebas explícitas contra fuga de
   información.
7. Dividir por paciente y bloquear el test antes de imputar, seleccionar
   variables o entrenar modelos.

Las normas detalladas para contribuir y para manipular datos protegidos están
en `AGENTS.md`.

## Convención gráfica

Todas las figuras publicables del análisis inicial, modelos, evaluación,
sensibilidades y subgrupos se crearán en R con `ggplot2` y se guardarán con
`ggsave()`. Algunos notebooks comparan explícitamente la misma tabla agregada
con Matplotlib para evaluar estilos; esa comparación no cambia el estándar de
publicación.
Las decisiones metodológicas y su estado se indexan en
[`docs/decision_register.md`](docs/decision_register.md); las definiciones
clínicas detalladas permanecen en `docs/sepsis_definition.md` y los parámetros
ejecutables en `config/`.
