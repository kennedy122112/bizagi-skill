---
name: bizagi
description: Modela procesos para Bizagi Modeler a partir de lenguaje natural, 100 % local y sin MCP. Convierte una descripción ("el solicitante registra, el jefe aprueba, si se rechaza termina...") en un archivo BPMN 2.0 con diagrama que se importa en Bizagi. También lee modelos exportados desde Bizagi para analizarlos, validarlos, documentarlos o modificarlos. Úsalo cuando el usuario diga "modela/diagrama/crea el proceso", "pásalo a Bizagi", "BPMN", "flujo de proceso", "documenta este .bpmn", "revisa mi modelo de Bizagi", o cuando adjunte un .bpmn.
---

# Bizagi desde lenguaje natural

Herramienta: `python scripts/bizagi_cli.py`, con la ruta relativa a la carpeta de este skill (normalmente `~/.agents/skills/bizagi/scripts/bizagi_cli.py`). Solo usa la biblioteca estándar de Python 3.9 o superior.

| Comando | Para qué |
|---|---|
| `generate spec.json -o proceso.bpmn --svg proceso.svg` | Genera el BPMN que se importa en Bizagi y una vista previa |
| `read modelo.bpmn -o spec.json` | Convierte un BPMN exportado de Bizagi en una spec editable |
| `validate spec.json\|modelo.bpmn` | Revisa las reglas de modelado (errores y avisos) |
| `preview spec.json\|modelo.bpmn -o vista.png` | Dibuja el diagrama sin abrir Bizagi (`.png` necesita Chrome o Edge; `.svg` siempre funciona) |
| `doc spec.json\|modelo.bpmn -o doc.md` | Genera la documentación del proceso (roles, actividades, secuencia) |
| `docx spec.json\|modelo.bpmn -o proceso.docx [--template plantilla.docx]` | Genera un documento Word con ficha, diagrama, actividades, decisiones, excepciones, documentos y externos |

## Flujo de trabajo

1. **Interpretar la descripción.** La gente describe procesos como habla: con muletillas, correcciones ("no, perdón, primero…"), abreviaturas y pasos implícitos. Quédate con la última versión de cada corrección e identifica:
   - los participantes (pools) y los roles (carriles);
   - las actividades;
   - las decisiones, los paralelismos y las esperas;
   - los plazos, los documentos y sistemas, y los mensajes con externos.

   Si falta algo que cambia el diagrama (quién decide, qué pasa si se rechaza, qué termina el proceso), pregúntalo antes.
   **Si no puedes preguntar** o el usuario pide avanzar, no te detengas: completa con lo típico y mínimo, sin inventar sistemas, plazos ni aprobaciones que nadie mencionó. Registra lo que asumiste en `assumptions` y lo que habría que confirmar en `questions`; ambos salen en la documentación como "Supuestos y puntos por validar".
   Ante un pedido de una línea ("el empleado presenta y finanzas revisa y paga"), modela solo:
   - inicio;
   - las actividades nombradas;
   - una decisión de revisión con salida "conforme" y salida "observada" (corrige y vuelve); agrega "rechazada" solo si el texto la sugiere;
   - los fines.

   Si el texto nombra un documento ("rendición", "factura"), inclúyelo como `dataObject`.
   No inventes `meta`: lo que falte saldrá como "Por completar" en la ficha del Word.
2. **Escribir la spec JSON** (formato abajo) junto a los demás archivos del usuario.
3. **Ejecutar `validate`** y corregir todos los errores. Los avisos conviene resolverlos.
4. **Ejecutar `generate spec.json -o proceso.bpmn`** (el archivo para Bizagi). Luego `preview spec.json -o vista.png` y **mira la imagen**.
   - Si aparece `AVISO diagrama`, alguna línea cruza un elemento.
   - **Lo que controla el layout:**
     - El orden de los carriles: ponlos en el orden en que intervienen.
     - El orden de los `flows`: de cada compuerta, la primera salida listada sigue recta y las demás se abren hacia abajo, así que escribe primero el camino principal.
5. **Entregar el `.bpmn`.** El usuario lo abre en Bizagi Modeler con **Exportar/Importar → Importar → BPMN**, que crea una pestaña de diagrama nueva. Si el usuario lo pide y computer-use está disponible, puedes importarlo tú.
6. **Si piden documentación o un entregable**, ejecuta `docx`.
   - El diagrama se incrusta en SVG, con un PNG de respaldo si hay Chrome o Edge instalado.
   - Un diagrama grande va en hojas A3: una vista general y páginas de detalle legibles al imprimir.
   - La ficha se completa con `meta` en la spec: `codigo`, `version`, `responsable`, `area`, `elaborado`, `revisado`, `aprobado`, `fecha`.
   - **Si el usuario tiene un formato propio** (el Word de su organización), usa `--template su-plantilla.docx`:
     - se conservan su carátula, logos, encabezados, pies y estilos;
     - `{{CONTENIDO}}` marca dónde va el proceso; sin ese marcador, el proceso se agrega al final;
     - `{{nombre}}`, `{{codigo}}`, `{{version}}`, `{{fecha}}`, `{{responsable}}`, `{{elaborado}}`, `{{revisado}}`, `{{aprobado}}` y cualquier clave de `meta` se rellenan, también en encabezados y pies.

     Si no tiene plantilla y quiere una, ofrécele `plantillas/plantilla-ejemplo.docx` para que la adapte.
7. **Para modificar un modelo existente:** en Bizagi se usa **Exportar/Importar → Exportar → BPMN**. Luego `read` → editas la spec → `generate` → se importa de nuevo.

## Formato de la spec

```json
{
  "name": "Solicitud de compra",
  "doc": "Objetivo y alcance del proceso.",
  "meta": {"codigo": "PR-LOG-001", "version": "1.0", "responsable": "Jefatura de Logística"},
  "assumptions": ["La solicitud observada vuelve a aprobación"],
  "questions": ["¿Hay un monto a partir del cual aprueba gerencia?"],
  "pools": [
    {"name": "Empresa", "lanes": ["Solicitante", {"name": "Jefe de área", "doc": "Aprueba según presupuesto"}, "Compras"]},
    {"name": "Proveedor", "blackbox": true}
  ],
  "nodes": [
    {"id": "inicio", "type": "start", "name": "Necesidad de compra", "lane": "Solicitante"},
    {"id": "registrar", "type": "userTask", "name": "Registrar solicitud", "lane": "Solicitante",
     "doc": "Descripción de la actividad"},
    {"id": "gw", "type": "exclusive", "name": "¿Aprobada?", "lane": "Jefe de área"},
    {"id": "esperar", "type": "timer", "name": "Esperar 2 días", "lane": "Compras", "timer": "P2D"},
    {"id": "vence", "type": "timer", "name": "Plazo vencido", "attachedTo": "aprobar", "timer": "P5D",
     "deadline": "5 días hábiles"},
    {"id": "aviso", "type": "timer", "name": "3 días sin respuesta", "attachedTo": "aprobar",
     "interrupting": false},
    {"id": "solicitud", "type": "dataObject", "name": "Formato de solicitud"},
    {"id": "bd", "type": "dataStore", "name": "Sistema logístico"},
    {"id": "nota", "type": "annotation", "text": "Montos > S/ 10 000 requieren visto de gerencia"}
  ],
  "flows": [
    "inicio -> registrar",
    "gw -> fin_rechazo : No",
    {"from": "gw", "to": "cotizar", "name": "Sí", "condition": "aprobado == true", "default": true},
    "vence -> escalar"
  ],
  "messageFlows": ["cotizar -> Proveedor : Pedido de cotización"],
  "associations": ["solicitud -> registrar", "registrar -> bd", "nota -> aprobar"]
}
```

- Con un solo pool basta `"lanes": [...]` en la raíz, sin `pools`.
- Cada nodo lleva `lane`. Si el mismo nombre de carril existe en dos pools, indica también `pool`.
- `flows` conecta nodos del **mismo** pool. Entre pools se usan `messageFlows`, que pueden apuntar al nombre de un pool externo (`blackbox`).
- **Eventos adjuntos** (al borde de una actividad): usa `attachedTo` con el id de la actividad. Heredan su carril y no llevan flujos de entrada. Por defecto interrumpen la actividad; con `"interrupting": false` la actividad continúa (recordatorios, alertas). Tipos permitidos: `timer`, `messageCatch`, `signalCatch`, `conditional`, `errorCatch`.
- **Datos y notas**: `dataObject` (documento), `dataStore` (base de datos o sistema) y `annotation` (nota con `text`). Se enlazan con `associations`: `"dato -> actividad"` es una entrada y `"actividad -> dato"` es una salida. Si no indicas `lane`, heredan el carril del elemento con el que se asocian.
- **Paso opcional** (bypass, "si tiene detracción primero deposita"): usa una compuerta exclusiva con una salida a la actividad y otra directa a la compuerta de unión posterior.
- **Plazos**: `timer` va en ISO 8601 (`P3D`, `PT4H`, `PT30M`); en la documentación aparece en palabras ("3 días"). Si el plazo es en días hábiles u otra regla, ponlo en `deadline` como texto ("5 días hábiles") y deja en `timer` una aproximación. El `name` del evento dice qué pasa ("Plazo de firma vencido"); el plazo va en `timer`/`deadline`, sin repetirlo.
- Un carril puede ser `{"name": ..., "doc": ...}` para describir el rol. La documentación lista además las actividades a cargo de cada rol.
- Los ids son cortos, sin espacios y únicos. Los nombres de las actividades se escriben como verbo en infinitivo + objeto ("Aprobar solicitud"). Las decisiones se escriben como pregunta ("¿Aprobada?"), y cada salida lleva una etiqueta.

**Tipos:**
- Eventos: `start`, `startMessage`, `startTimer`, `startSignal`, `startConditional`, `end`, `endMessage`, `endError`, `endTerminate`, `endSignal`, `intermediate`, `timer`, `messageCatch`, `messageThrow`, `signalCatch`, `signalThrow`, `conditional`, `errorCatch` (este último, solo adjunto).
- Actividades: `task`, `userTask`, `serviceTask`, `manualTask`, `scriptTask`, `sendTask`, `receiveTask`, `businessRuleTask`, `subProcess`, `callActivity`.
- Compuertas: `exclusive`, `parallel`, `inclusive`, `eventBased`, `complex`.
- Artefactos: `dataObject`, `dataStore`, `annotation`.

## Buenas prácticas que aplicar al interpretar

- Cada pool tiene al menos un inicio y un fin. Usa varios fines con nombre del resultado ("Solicitud rechazada", "Compra completada").
- Una compuerta paralela que divide se cierra con otra paralela que une. No cierres ramas paralelas con una exclusiva.
- Los retrabajos ("si está observada, se corrige y vuelve a aprobación") se modelan como un flujo de regreso. El layout los dibuja por encima.
- Elige el tipo de tarea según quién la hace: una persona en el sistema es `userTask`, el sistema es `serviceTask`, fuera del sistema es `manualTask`, enviar o recibir a un externo es `sendTask`/`receiveTask` o un evento de mensaje.
- Plazos, vencimientos y escalamientos ("si no responde en 10 días, alertar a jefatura") se modelan como un `timer` adjunto. Si la actividad sigue en curso, el timer es no interrumpible. Fallos de sistema ("si el envío falla, notificar en físico") se modelan como `errorCatch` adjunto.
- Agrega los documentos de entrada y salida y los sistemas que se mencionen. Agrega una `annotation` para las reglas o plazos legales que no se ven en el diagrama.
- **Nombra las compuertas que dividen** como pregunta. Las que unen pueden ir sin nombre: la documentación las omite y sigue al paso siguiente.
- **Cuando dos o más caminos llegan al mismo paso**, únelos con una compuerta (exclusiva si llega solo uno de ellos, paralela si llegan todos). La excepción es un retrabajo que regresa a una actividad anterior.
- **Lo que hace el sistema solo** ("le llega un correo", "se actualiza la planilla") es un `serviceTask`. Va en el carril del rol responsable o en un carril "Sistema" si hay varias tareas automáticas.
- **Un tercero externo** (proveedor, ciudadano, postulante, banco) es un pool `blackbox` con `messageFlows`. Si sus pasos internos importan, dale carriles y nodos como a cualquier pool.
- **Un mismo trámite que llega por varios canales** ("por mesa de partes o por correo") es un solo inicio con nombre inclusivo ("Factura recibida"), salvo que el tratamiento cambie según el canal.
- **Un plazo que cubre varias actividades** (un SLA o "15 días desde la conformidad") va adjunto a la actividad principal o a la última del tramo, con una `annotation` que diga desde dónde corre.

## Limitaciones

- El `.bpm` nativo no se lee directamente: hay que exportarlo a BPMN desde Bizagi.
- Los subprocesos se generan contraídos. Si se necesita su detalle, se crea otra spec para el subproceso.
- No hay subprocesos de evento ni temporizadores que cubran un tramo de varias actividades (ver la práctica de plazos más arriba).
