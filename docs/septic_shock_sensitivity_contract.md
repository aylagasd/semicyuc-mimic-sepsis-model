# Contrato de sensibilidades del proxy de shock séptico (D010)

## Alcance y regla primaria

El resultado se denomina **proxy EHR de shock séptico**. La regla primaria
requiere una estancia Sepsis-3, lactato estrictamente mayor de 2 mmol/L y un
intervalo de vasopresor concurrente con tolerancia de ±6 horas, ambos dentro de
la ventana configurada alrededor de `t0`. No demuestra resucitación adecuada.

`config/septic_shock.json` es la fuente versionada de umbral, `itemid`, lista de
vasopresores y ventanas anterior/posterior. El pipeline aplica ahora todos esos
campos: un mapeo desconocido falla y las ventanas anterior y posterior no se
colapsan en una sola por accidente.

## Variantes preespecificadas

Cada variante debe reconstruirse desde lactatos y vasopresores; no se obtiene
filtrando solo los positivos primarios.

| Variante | Cambio único respecto al primario | Estado técnico | Decisión pendiente |
|---|---|---|---|
| concurrencia 3 h | tolerancia ±3 h | artefacto versionado en ambos pipelines | firma clínica |
| concurrencia 12 h | tolerancia ±12 h | artefacto versionado en ambos pipelines | firma clínica |
| MAP <65 | exige MAP documentada antes o durante la concurrencia | fuente aún no integrada | ventana y resumen de MAP |
| fluidos documentados | exige evidencia de cristaloide previa | fuente aún no integrada | fluidos, volumen y ventana |
| vasopresores restrictivos | subconjunto explícito de la lista primaria | motor parametrizado y probado | composición del subconjunto |

No se elegirá una variante por producir una prevalencia conveniente en el demo.
La lista restrictiva no se inventa en ingeniería: debe quedar firmada por
intensivos/metodología y versionada antes del análisis completo.

## Artefactos y comparación

Las variantes se materializarán con nombres distintos y el manifiesto conservará
la configuración completa. La tabla de revisión agregada debe informar por
variante: estancias Sepsis-3 evaluadas, proxy positivo/negativo, cambio absoluto
y concordancia con el primario. No incluirá identificadores ni cambiará D010 a
`frozen` automáticamente.

Para cada positivo se preservan por separado:

- `shock_t0`: primer instante en que concurren los criterios;
- `shock_label_available_at`: máximo entre inicio y disponibilidad del lactato;
- evidencia de vasopresor y lactato que originó la etiqueta;
- indicador explícito de si fluidos adecuados fueron verificados.

## Condiciones para cerrar D010

1. firmar la denominación de proxy y la ausencia de inferencia sobre fluidos;
2. aprobar las variantes de 3/12 horas y el subconjunto restrictivo;
3. decidir la semántica y procedencia de MAP y fluidos;
4. materializar todas las variantes en demo y después en development;
5. incorporar solo agregados al dossier protegido;
6. actualizar en un mismo cambio el registro, el estado ejecutable, las pruebas
   y el acta firmada.
