# Migración al equipo de cálculo

## Objetivo

Migrar el código reproducible al equipo x86_64 de 32 GiB sin publicar ni
duplicar innecesariamente datos MIMIC-IV, credenciales, entornos virtuales o
configuraciones con rutas locales. El código viaja mediante Git; MIMIC-IV se
descarga directamente desde PhysioNet en el equipo autorizado o se transfiere
por un canal privado entre equipos bajo el control del mismo usuario.

El perfil inicial del proyecto es `config/compute_32gb.json`: reserva 24 GiB
para el proceso, limita DuckDB a 8 GB y dos hilos y usa lotes de 100 estancias.
No se aumenta el paralelismo hasta disponer de telemetría de una ejecución
completa.

## 1. Qué se transfiere

| Contenido | Canal | Acción |
|---|---|---|
| Código, notebooks limpios, pruebas y configuración no sensible | GitHub | Commit, push y clonación. |
| MIMIC-IV completo | PhysioNet o SSH/rsync privado | Preferir descarga directa en destino. Nunca Git. |
| Demo local | Regenerable | Volver a descargar; copiarlo no es necesario. |
| Derivados demo | Regenerable | Reconstruir en destino para validar el entorno. |
| Derivados completos | Almacenamiento privado | Transferir solo si ya existen y conservar manifiestos. |
| `.venv/`, `.micromamba/`, `.cache/`, `.jupyter/` | No transferir | Recrear para la arquitectura x86_64. |
| `*.local.json`, `.env`, credenciales y tokens | No transferir por Git | Recrear localmente con permisos restrictivos. |

Antes de publicar código, el origen debe cumplir:

```bash
git status --short
git diff --check
python -m pytest -q
```

La salida de `git status` debe estar vacía. Los notebooks versionados no deben
contener outputs ni contadores de ejecución.

## 2. Preparar el equipo destino

Crear tres ubicaciones separadas conceptualmente. Pueden compartir un SSD si
el preflight confirma capacidad suficiente:

```text
/ruta/proyectos/semicyuc-mimic-sepsis-model   código
/ruta/datos/mimiciv/3.1                       fuentes MIMIC-IV
/ruta/trabajo/semicyuc/run-primary            derivados persistentes
/ruta/temporal/semicyuc-duckdb                 spill temporal DuckDB
```

Las rutas de datos y trabajo deben ser privadas para el usuario autorizado:

```bash
umask 077
mkdir -p /ruta/datos/mimiciv/3.1
mkdir -p /ruta/trabajo/semicyuc/run-primary
mkdir -p /ruta/temporal/semicyuc-duckdb
chmod 700 /ruta/datos/mimiciv /ruta/trabajo/semicyuc \
  /ruta/temporal/semicyuc-duckdb
```

No se deben introducir nombres de host, usuarios, rutas privadas o
credenciales en archivos versionados.

## 3. Clonar y recrear el entorno

```bash
cd /ruta/proyectos
git clone https://github.com/aylagasd/semicyuc-mimic-sepsis-model.git
cd semicyuc-mimic-sepsis-model
git rev-parse HEAD
```

Instalar micromamba para Linux x86_64 si el equipo no dispone ya de conda o
mamba. Después crear el entorno a partir del archivo versionado, sin copiar el
entorno ARM de la Raspberry:

```bash
export XDG_CACHE_HOME="$PWD/.cache"
micromamba create -y -p "$PWD/.micromamba/envs/semicyuc" -f environment.yml
micromamba run -p "$PWD/.micromamba/envs/semicyuc" \
  python scripts/preflight_analysis_environment.py
micromamba run -p "$PWD/.micromamba/envs/semicyuc" python -m pytest -q
```

El preflight debe localizar Python, Jupyter, `Rscript`, IRkernel y `ggplot2`.
La suite sintética no requiere MIMIC-IV y debe pasar antes de descargar datos.

## 4. Validar capacidad real

El dato nominal de 32 GB no basta: deben quedar disponibles 24 GiB durante el
pipeline. Cerrar aplicaciones y servicios pesados antes de medir. Ejecutar:

```bash
micromamba run -p "$PWD/.micromamba/envs/semicyuc" \
  python scripts/preflight_compute_host.py \
  --work-path /ruta/trabajo/semicyuc/run-primary \
  --temp-path /ruta/temporal/semicyuc-duckdb \
  --compute-profile config/compute_32gb.json \
  --minimum-work-free-gb 250 \
  --minimum-temp-free-gb 250
```

Si trabajo y temporales comparten volumen, el control exige 500 GiB libres en
conjunto. Un equipo con suficiente capacidad total puede fallar correctamente
si la partición concreta elegida no dispone de ese espacio o si otros procesos
consumen memoria. No se continúa hasta obtener `"ready": true`.

## 5. Descargar o transferir MIMIC-IV

La opción preferida es descargar MIMIC-IV 3.1 directamente en el destino. La
contraseña se solicita de forma interactiva y nunca se incluye en el comando,
un notebook, una variable persistente o el historial Git:

```bash
cd /ruta/datos/mimiciv
wget --user "USUARIO_PHYSIONET" --ask-password -r -N -c -np \
  -nH --cut-dirs=2 \
  https://physionet.org/files/mimiciv/3.1/
```

Si ya existe una copia autorizada en otro equipo, puede usarse `rsync` sobre
SSH. La ruta exacta y el host se mantienen fuera del repositorio:

```bash
rsync -a --partial --info=progress2 \
  /ruta/origen/mimiciv/3.1/ usuario@host:/ruta/datos/mimiciv/3.1/
```

Después se valida el árbol sin leer filas clínicas:

```bash
micromamba run -p "$PWD/.micromamba/envs/semicyuc" \
  python scripts/preflight_mimic_files.py /ruta/datos/mimiciv/3.1 \
  --minimum-free-gb 250
```

Si la distribución contiene checksums oficiales, verificarlos además desde la
raíz indicada por PhysioNet. Una transferencia interrumpida no se considera
válida solo porque los nombres de archivo estén presentes.

## 6. Prueba de aceptación con el demo

Antes del conjunto completo se reconstruye el demo desde cero en x86_64:

```bash
micromamba run -p "$PWD/.micromamba/envs/semicyuc" \
  python scripts/download_mimic_demo.py
micromamba run -p "$PWD/.micromamba/envs/semicyuc" \
  python scripts/build_demo_sofa_incremental.py --stage all --resume
micromamba run -p "$PWD/.micromamba/envs/semicyuc" \
  python scripts/execute_notebooks.py --start 0 --end 15 --timeout 600
```

Los notebooks ejecutados se escriben bajo `data/derived/notebook_runs/`, que
permanece fuera de Git. El éxito confirma instalación y orquestación, no
validez clínica sobre la población completa.

## 7. Inicio controlado del conjunto completo

Mientras la puerta clínica/metodológica continúe abierta, el recorrido se
detiene después de la extracción reducida:

```bash
micromamba run -p "$PWD/.micromamba/envs/semicyuc" \
  python scripts/run_full_workflow.py /ruta/datos/mimiciv/3.1 \
  --data-version 3.1 \
  --work-root /ruta/trabajo/semicyuc/run-primary \
  --temp-dir /ruta/temporal/semicyuc-duckdb \
  --minimum-work-free-gb 250 \
  --minimum-temp-free-gb 250 \
  --through extract \
  --resume
```

No se solicita `pipeline` o `validate` hasta congelar las decisiones exigidas
por la puerta de protocolo. El test no se materializa durante desarrollo.

## 8. Jupyter remoto seguro

Jupyter escucha solo en loopback en el equipo de cálculo:

```bash
micromamba run -p "$PWD/.micromamba/envs/semicyuc" \
  jupyter lab --no-browser --ip=127.0.0.1 --port=8888
```

Desde el equipo del investigador se abre un túnel SSH:

```bash
ssh -N -L 8888:127.0.0.1:8888 usuario@host
```

La interfaz se abre localmente en `http://127.0.0.1:8888`. No se expone
Jupyter con `--ip=0.0.0.0` ni se desactiva su token.

## 9. Criterio de migración completada

La migración técnica termina cuando:

1. el commit del origen y del destino coincide;
2. el preflight de análisis está listo;
3. la suite sintética pasa;
4. el preflight del host informa `ready: true`;
5. el demo se reconstruye y los notebooks 00–15 se ejecutan;
6. MIMIC-IV 3.1 supera el preflight de archivos;
7. la extracción primaria genera manifiestos válidos y telemetría agregada;
8. no hay credenciales, datos ni configuraciones locales rastreados por Git.

La guía de ejecución posterior sigue siendo
[`full_deployment_guide.md`](full_deployment_guide.md); el dimensionamiento y
las reglas ante presión de memoria están en
[`hardware_32gb.md`](hardware_32gb.md).
