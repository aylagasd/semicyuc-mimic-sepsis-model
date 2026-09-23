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

Superado el preflight, la reducción fuera de memoria se ejecuta con:

```bash
python scripts/extract_full_mimic.py /ruta/mimiciv/3.1 \
  --data-version 3.1 \
  --output-dir /ruta/derivados/full_extract \
  --temp-dir /ruta/disco_temporal/duckdb \
  --memory-limit 16GB \
  --resume
```

El límite de memoria y las rutas deben adaptarse al servidor. DuckDB selecciona
primero la cohorte, filtra filas por estancia, tiempo e `itemid`, y escribe solo
las columnas requeridas en Parquet comprimido. Cada salida tiene un manifiesto
con número de filas, esquema, versión, hash de configuración y SHA-256. Con
`--resume` solo se reutiliza un artefacto cuyo hash y configuración coincidan.
La salida del comando contiene exclusivamente recuentos y hashes agregados.

Antes de construir el fenotipo completo debe pasar además la puerta de
protocolo:

```bash
python scripts/preflight_protocol.py phenotype
```

Mientras una decisión requerida siga `pending` o `provisional`, el comando
devuelve código 2 y enumera únicamente IDs/estados. El orquestador aplica esta
misma puerta automáticamente para cualquier versión distinta del Demo 2.2.
Una aprobación clínica debe actualizar en el mismo commit el acta, el registro
de decisiones y `config/protocol_status.json`; no basta editar solo el JSON.

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
| Extracción CSV fuera de memoria con pushdown | validada | implementada; falta benchmark completo |
| SOFA, infección, landmarks y features por lotes | equivalencia exacta | implementado; falta benchmark completo |
| Modelado y bootstrap | prueba técnica | ejecutar en servidor de cálculo |

El script `build_demo_sofa_incremental.py` está diseñado deliberadamente para
el demo. No debe apuntarse a los CSV completos: cargaría tablas masivas en
memoria. `extract_full_mimic.py` resuelve la reducción fuera de memoria. Las
etapas posteriores se ejecutan por lotes deterministas de estancias, sin cargar
los Parquet completos en pandas:

```bash
python scripts/build_full_pipeline_chunked.py /ruta/derivados/full_extract \
  --output-root /ruta/derivados/full_pipeline \
  --batch-size 250 \
  --resume
```

En una versión no-demo, este comando exige la puerta `model` y materializa
solo `development` y `validation`. Los constructores de bajo nivel también
rechazan test no-demo, de modo que no se crea por accidente al ejecutar un
script de etapa.

El test se materializa una sola vez, después de congelar y versionar
`config/model_freeze.json`, registrar previamente el acceso y crear una
autorización local a partir de `config/test_release.example.json`:

```bash
python scripts/build_full_pipeline_chunked.py /ruta/derivados/full_extract \
  --output-root /ruta/derivados/full_pipeline \
  --materialize-test \
  --model-freeze config/model_freeze.json \
  --test-release config/test_release.local.json \
  --resume
```

La autorización debe declarar roles clínico y estadístico, versión de datos,
momento UTC, motivo y el SHA-256 exacto del modelo congelado. El archivo local
está ignorado por Git; no contiene contraseñas ni se imprime en la salida.
La especificación congelada se valida contra
`config/model_freeze.example.json`: debe fijar commit y run de origen, outcome,
horizonte, variables, modelo y parámetros, calibración, umbrales operativos,
estado de decisiones y hash del informe agregado de validation.
Ese informe se genera mediante el notebook 13 y se valida como un conjunto de
tablas exclusivamente agregadas; su manifiesto
`aggregate_report.manifest.json` contiene el SHA-256 que debe copiarse al
documento de congelación.

Cada derivado encadena hashes de sus entradas concretas; cambiar una parte
invalida sus descendientes. El tamaño de lote debe ajustarse con una prueba de
memoria en el servidor. La equivalencia de contenido se comprobó sobre Demo
2.2 con `verify_demo_chunked_equivalence.py`; ese verificador rechaza otras
versiones deliberadamente y no debe utilizarse para abrir el test completo.
Al pasar `--full-extract-root`, compara además el esquema y multiconjunto de
los descriptores comunes de cohorte entre la extracción fuera de memoria y el
recorrido monolítico.

## 5. Puertas antes de ejecutar el conjunto completo

1. congelar D002, D004, D010, D011, D014, D016 y D027 antes del modelado, y D029 antes de test; D031 ya fija el contrato verificable del informe;
2. ejecutar preflight de archivos o conexión read-only;
3. registrar versión, checksum/configuración y commit del código;
4. generar la partición por paciente antes de cualquier ajuste empírico;
5. mantener test separado y registrar cada acceso;
6. revisar recuentos agregados, espacio, memoria y tiempos por etapa;
7. no crear ni abrir el test hasta congelar modelos, calibración y umbrales;
8. registrar el acceso y validar la autorización ligada al modelo congelado.

La ejecución completa sigue siendo investigación retrospectiva. No autoriza
uso asistencial ni despliegue de alertas clínicas.
