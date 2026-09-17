# Guía de despliegue sobre MIMIC-IV completo

## 1. Dos accesos distintos

Las credenciales personales de **PhysioNet** autorizan la descarga HTTPS de
MIMIC-IV. No constituyen por sí mismas un host, usuario o contraseña de
PostgreSQL. El proyecto admite dos escenarios:

1. descargar la distribución autorizada en el servidor de cálculo y cargarla
   después en PostgreSQL/otro motor analítico;
2. conectarse a una instalación PostgreSQL ya creada por la institución.

Nunca se copian credenciales de PhysioNet a `config/mimic.env`. Ese archivo es
exclusivamente para una base PostgreSQL propia y permanece fuera de Git.

## 2. Descarga autorizada

La versión prevista por D001 es MIMIC-IV 3.1. La descarga se hace en el equipo
de mayor capacidad y mediante solicitud interactiva de contraseña, por ejemplo:

```bash
wget --user "USUARIO_PHYSIONET" --ask-password -r -N -c -np \
  https://physionet.org/files/mimiciv/3.1/
```

No se usa `--password`, no se introduce la contraseña en un notebook y no se
guarda en variables versionadas. El directorio descargado debe quedar fuera
del repositorio o bajo una ruta ignorada `data/` con permisos restrictivos.

Antes de leer filas:

```bash
python scripts/preflight_mimic_files.py /ruta/mimiciv/3.1 \
  --minimum-free-gb CAPACIDAD_RESERVADA
```

El preflight solo abre la cabecera comprimida de las 11 tablas requeridas,
detecta ficheros ausentes, deriva de esquema y espacio libre. Devuelve JSON y
código 0 únicamente cuando todos los controles pasan.

## 3. PostgreSQL institucional o propio

Copiar `config/mimic.env.example` a un fichero local ignorado, completar sus
valores y exportarlo en la sesión. El usuario de base de datos debe tener solo
`CONNECT`, `USAGE` y `SELECT` sobre los esquemas necesarios.

```bash
set -a
source config/mimic.env
set +a
python scripts/check_mimic_connection.py
```

El motor añade a cada conexión:

- `default_transaction_read_only=on`;
- un `statement_timeout` configurable;
- comprobación explícita de `transaction_read_only` antes de inspeccionar
  metadatos.

El comprobador ejecuta `SELECT 1`, consulta metadatos de esquemas/tablas y no
lee filas de pacientes. Su salida nunca incluye URL, host, usuario o contraseña.

## 4. Estado de portabilidad

| Componente | Demo CSV | MIMIC completo |
|---|---:|---:|
| Definiciones clínicas y pruebas de frontera | listo | reutilizable |
| Manifiestos, landmarks, particiones y features | listo | contrato reutilizable |
| Lectura monolítica con pandas | aceptable | **no ejecutar** |
| Extracción SQL/chunked pushdown | no necesaria | pendiente |
| Modelado y bootstrap | prueba técnica | ejecutar en servidor de cálculo |

El script `build_demo_sofa_incremental.py` está diseñado deliberadamente para
el demo. No debe apuntarse a los CSV completos: cargaría tablas masivas en
memoria. Antes del despliegue se implementará una extracción SQL o por chunks
que produzca exactamente los mismos contratos de artefactos y supere las
pruebas existentes.

## 5. Puertas antes de ejecutar el conjunto completo

1. congelar D002, D004, D010, D011, D014 y D016;
2. ejecutar preflight de archivos o conexión read-only;
3. registrar versión, checksum/configuración y commit del código;
4. generar la partición por paciente antes de cualquier ajuste empírico;
5. mantener test separado y registrar cada acceso;
6. revisar recuentos agregados, espacio, memoria y tiempos por etapa;
7. no abrir el test hasta congelar modelos, calibración y umbrales.

La ejecución completa sigue siendo investigación retrospectiva. No autoriza
uso asistencial ni despliegue de alertas clínicas.
