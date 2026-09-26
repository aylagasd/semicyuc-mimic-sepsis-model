# Revisión clínica de reglas antimicrobianas (D004)

## Propósito

La lista ordenada de `config/antimicrobial_rules.csv` es código clínico y debe
revisarse antes de congelar D004. El siguiente comando crea un paquete JSON sin
datos de pacientes que contiene la lista completa, su posición, grupo, hash,
exclusiones de vía/forma, eventos EMAR aceptados y solapamientos de subcadenas:

```bash
python scripts/audit_antimicrobial_rules.py \
  --output data/derived/audit/antimicrobial_rule_review.json
```

El hash permite demostrar qué versión se firmó. El informe siempre conserva
`clinical_review_required=true`: generarlo no cambia el estado de D004.

## Qué debe resolver la revisión

Para cada regla, infecciosas/farmacia e intensivos deben confirmar inclusión,
grupo, uso sistémico y riesgo de profilaxis. También deben revisar explícitamente:

1. si faltan principios activos o sinónimos presentes en MIMIC-IV;
2. si una subcadena puede capturar otro medicamento antes que una regla posterior;
3. si las vías y formas excluidas son suficientes;
4. si la igualdad exacta con `administered`, `started` y `restarted` tiene el
   significado operativo deseado en EMAR (las negaciones no se aceptan);
5. si antifúngicos forman parte de la definición primaria;
6. si combinaciones, tratamientos perioperatorios y desensibilización requieren
   reglas adicionales.

La revisión de la lista debe combinarse con los agregados de cobertura y tiempos
de `scripts/audit_phenotype_freeze.py`. El paquete estático prueba qué reglas se
revisaron; el informe fenotípico muestra cómo operaron sobre los datos. Ninguno
de los dos sustituye la firma descrita en `clinical_freeze_dossier.md`.
