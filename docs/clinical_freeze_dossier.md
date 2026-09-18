# Dossier para congelar protocolo antes de MIMIC-IV completo

## 1. Finalidad y autoridad

Este documento reúne las decisiones que todavía requieren aprobación clínica o
metodológica antes de ejecutar desarrollo/validación sobre MIMIC-IV completo.
No las convierte por sí solo en decisiones `frozen`: la aprobación debe quedar
fechada, atribuida a un rol y reflejada en `decision_register.md`, configuración,
pruebas y versión de artefactos en el mismo cambio.

No se usarán métricas del test para resolver ninguna opción. El demo sirve
exclusivamente para verificar ingeniería y mostrar qué información deberá
revisarse en development.

El estado ejecutable se refleja en `config/protocol_status.json`. El preflight
de fase no sustituye esta acta: solo impide que una decisión no firmada pase
silenciosamente al análisis completo.

## 2. Propuestas que requieren firma

| ID | Propuesta primaria para aprobar | Sensibilidades preespecificadas | Revisor mínimo | Estado |
|---|---|---|---|---|
| D002 | Primera estancia UCI elegible por ingreso hospitalario. Mantiene episodios agudos distintos de un mismo paciente; toda partición e inferencia sigue agrupada por `subject_id`. | Primera estancia por paciente; todas las estancias elegibles. Cada variante reconstruye el pipeline completo. | Intensivista + metodología | pendiente de firma |
| D004 | Antimicrobiano sistémico según lista versionada, confirmado por primera administración EMAR; cultivo de sangre; ventanas 24/72 h. | Prescripción sin EMAR; cultivos expandidos; variación de ventanas; exclusión perioperatoria. | Infecciosas/farmacia + intensivista | pendiente de revisión de lista |
| D010 | Denominar el resultado **proxy EHR de shock séptico**, no shock clínico completo: Sepsis-3 + vasopresor + lactato >2 mmol/L concurrentes ±6 h y asociados ±24 h a `t0`. No afirmar resucitación adecuada. | Ventanas 3/12 h; MAP <65 previa; fluido documentado; lista restrictiva de vasopresores. | Intensivista + metodología | pendiente de firma |
| D011 | No excluir del primario mediante un umbral de cobertura elegido con el demo. Conservar missingness y cobertura como auditoría; exigir baseline observado y/o ventana aguda completa en sensibilidades. | Baseline observado; extremos agudos cubiertos; seis componentes completos; análisis por carga de missingness. | Intensivista + estadística | pendiente de firma |
| D014 | Diez dominios fisiológicos iniciales, sin SOFA, vasopresores, antibióticos ni cultivos en el modelo primario. Laboratorios disponibles en `storetime`. Congelar transformaciones y grados de libertad después de contar eventos en development y antes de ajustar. | Baseline de cinco resúmenes; SOFA explícitamente secundario; modelos por carga de missingness. | Intensivista + estadística | pendiente de complejidad final |
| D016 | Referencias: prevalencia e intercepto; baseline clínico de cinco parámetros. Landmarks con peso total igual por paciente. El modelo ampliado solo procede si la planificación formal soporta todos sus parámetros candidatos. | Un landmark por estancia; ponderación por estancia; penalización más fuerte; reducción preespecificada de complejidad. | Estadística | pendiente de tamaño muestral |

## 3. Checklist de revisión clínica

### Antimicrobianos y cultivos

- revisar cada regla de `config/antimicrobial_rules.csv`, grupo, vía y forma;
- identificar profilaxis quirúrgica y tratamientos no sistémicos que aún entren;
- confirmar jerarquía EMAR/prescripción y significado de eventos administrados;
- aprobar sangre como fuente primaria y la lista de especímenes de sensibilidad;
- revisar agregados y ejemplos sintéticos; no copiar filas de pacientes al acta.

### SOFA, sepsis y shock

- aprobar `itemid`, conversiones, límites fisiológicos y ventanas de validez;
- revisar el cero basal cuando no existe observación y sus sensibilidades;
- confirmar que `t0` es primer cruce y no máximo retrospectivo;
- aceptar explícitamente que el proxy de shock no verifica resucitación adecuada;
- fijar qué análisis de cobertura será exclusión y cuál solo estratificación.

### Predicción y operación

- aprobar la lista de parámetros, no solo nombres de variables;
- documentar no linealidades, interacciones y categorías con sus grados de libertad;
- definir una acción clínica hipotética antes de interpretar decision curves;
- aprobar weighting/sampling de landmarks y manejo de alta/muerte competidora;
- dejar firmado que el test permanece cerrado hasta congelar modelo y umbrales.

## 4. Puerta cuantitativa de información

La regla «10 eventos por variable» no será el cálculo principal. Para un
resultado binario se aplicará el marco de Riley et al., que considera número de
parámetros candidatos, prevalencia anticipada, rendimiento anticipado y tres
objetivos: precisión del riesgo global, shrinkage global y optimismo del ajuste.
El método y su explicación práctica están descritos en el
[artículo metodológico primario](https://pubmed.ncbi.nlm.nih.gov/30357870/) y en
la [guía de cálculo](https://www.bmj.com/content/368/bmj.m441).

Los landmarks repetidos no son participantes independientes. Por ello:

1. se informan landmarks observados/censurados, estancias, pacientes y
   pacientes con al menos un evento;
2. el número de parámetros cuenta todos los grados de libertad candidatos;
3. la prevalencia y el Cox–Snell R² anticipado se estiman solo con literatura o
   development, nunca con test;
4. el cálculo de Riley se presenta como mínimo para observaciones independientes;
5. la suficiencia final se somete además a validación agrupada, estabilidad de
   calibración y, si es necesario, simulación que preserve clústeres por paciente.

`config/sample_size.json` deja `anticipated_cox_snell_r2=null` de forma
deliberada. Mientras siga nulo, `formal_sample_size_ready` debe ser falso y no
se autoriza presentar un tamaño formal. El comando agregado es:

```bash
python scripts/audit_development_information.py \
  /ruta/sepsis3_development_landmarks.parquet \
  /ruta/sepsis3_development_features.parquet
```

El comando falla si detecta una partición distinta de development y nunca
imprime identificadores. En el demo encuentra 62 pacientes development, seis
pacientes con algún positivo a seis horas y 270 predictores ingenierizados; esto
demuestra que el demo no permite decidir la complejidad ni estimar rendimiento.

## 5. Acta de congelación

Para cada fila de la sección 2 debe registrarse:

| Campo | Valor |
|---|---|
| ID de decisión | |
| Opción aprobada | |
| Sensibilidades aprobadas | |
| Justificación | |
| Rol y nombre del revisor | |
| Fecha | |
| Commit de implementación | |
| Configuración/esquema afectado | |
| Pruebas revisadas | |

Una firma no autoriza uso clínico. Solo permite pasar a development/validation
retrospectivos bajo el protocolo versionado.
