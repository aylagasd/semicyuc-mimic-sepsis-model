# Registro de acceso a particiones test

Este registro es parte de la gobernanza del modelo. Toda lectura de una
partición denominada `test`, incluso accidental o limitada a agregados, se
anota antes de comunicar resultados. El test final de MIMIC-IV completo solo
se abrirá una vez congelados fenotipo, variables, modelos, calibración y
umbrales.

| Fecha | Datos | Acceso | Motivo | Uso en decisiones | Consecuencia |
|---|---|---|---|---|---|
| 2026-09-09 | MIMIC-IV Demo v2.2 | Recuentos agregados de filas, pacientes, observabilidad y positivos de los artefactos test | Verificar aislamiento físico y coherencia de asignación durante el desarrollo del pipeline | Ninguno: no se entrenó ni seleccionó modelo, variable, umbral o fenotipo con esos recuentos | El test del demo se considera ensayo de ingeniería y no evaluación ciega. El test final del conjunto completo permanece sin crear ni acceder. |

Los notebooks de desarrollo 09 y siguientes no descubren ni cargan artefactos
test. Las validaciones automáticas pueden comprobar manifiestos, esquema y
aislamiento sin utilizar valores de desenlace para tomar decisiones.
