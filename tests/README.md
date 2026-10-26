# Pruebas con lenguaje natural

`casos/` tiene descripciones de procesos escritas como las escribe o dicta la gente: un audio transcrito, un correo, notas de reunión, un dictado con correcciones y un pedido de una sola línea.

Cada caso lo modeló un agente distinto que solo tenía el texto y el `SKILL.md`. `specs/` guarda la spec que produjo; la CI la valida y genera el BPMN, el Markdown y el Word en cada push.

| Caso | Qué pone a prueba |
|---|---|
| 01 vacaciones (audio) | Lenguaje coloquial, aprobación tácita por tiempo, tareas automáticas, paralelismo |
| 02 pago a proveedores (correo) | Jerga (SIAF, CCI, detracción), subsanación con regreso, paso opcional, plazo de 15 días |
| 03 incidencias TI (notas) | Abreviaturas y flechas, escalamiento N1 → N2, SLA, cierre automático |
| 04 contratación CAS (dictado) | Correcciones a mitad de frase, proceso largo (diagrama en A3), accesitario |
| 05 reembolso (una línea) | Pedido mínimo: supuestos y preguntas registrados en vez de inventar |
