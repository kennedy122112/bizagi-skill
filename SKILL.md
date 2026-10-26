---
name: bizagi
description: Modela procesos para Bizagi Modeler a partir de lenguaje natural, 100 % local y sin MCP. Convierte una descripción ("el solicitante registra, el jefe aprueba, si se rechaza termina...") en un archivo BPMN 2.0 con diagrama que se importa en Bizagi. También lee modelos exportados desde Bizagi para analizarlos, validarlos, documentarlos o modificarlos. Úsalo cuando el usuario diga "modela/diagrama/crea el proceso", "pásalo a Bizagi", "BPMN", "flujo de proceso", "documenta este .bpmn", "revisa mi modelo de Bizagi", o cuando adjunte un .bpmn.
---

# Bizagi desde lenguaje natural

Herramienta: `python scripts/bizagi_cli.py`, con la ruta relativa a la carpeta de este skill (p. ej. `~/.claude/skills/bizagi/scripts/bizagi_cli.py`). Solo usa la biblioteca estándar de Python 3.9 o superior.

| Comando | Para qué |
|---|---|
| `generate spec.json -o proceso.bpmn --svg proceso.svg` | Genera el BPMN que se importa en Bizagi y una vista previa |
| `read modelo.bpmn -o spec.json` | Convierte un BPMN exportado de Bizagi en una spec editable |
| `validate spec.json\|modelo.bpmn` | Revisa las reglas de modelado (errores y avisos) |
| `preview spec.json\|modelo.bpmn -o vista.svg` | Dibuja el diagrama sin abrir Bizagi |
| `doc spec.json\|modelo.bpmn -o doc.md` | Genera la documentación del proceso (roles, actividades, secuencia) |

## Flujo de trabajo

1. **Interpretar la descripción.** Identifica los participantes (pools), los roles (carriles), las actividades, las decisiones, los paralelismos, las esperas y los mensajes con externos. Si falta algo que cambia el diagrama, pregúntalo antes: quién decide, qué pasa si se rechaza, qué termina el proceso. Lo menor, asúmelo y dilo.
2. **Escribir la spec JSON** (formato abajo) junto a los demás archivos del usuario.
3. **Ejecutar `validate`** y corregir todos los errores. Los avisos conviene resolverlos.
4. **Ejecutar `generate ... --svg`.** Para revisar la vista previa, conviértela a PNG con Edge en modo headless y mírala:
   `msedge --headless --disable-gpu --hide-scrollbars --window-size=2000,1200 --screenshot=vista.png file:///ruta/vista.svg`
5. **Entregar el `.bpmn`.** El usuario lo abre en Bizagi Modeler con **Exportar/Importar → Importar → BPMN**, que crea una pestaña de diagrama nueva. Si el usuario lo pide y computer-use está disponible, puedes importarlo tú.
6. **Para modificar un modelo existente:** en Bizagi se usa **Exportar/Importar → Exportar → BPMN**. Luego `read` → editas la spec → `generate` → se importa de nuevo.

## Formato de la spec

```json
{
  "name": "Solicitud de compra",
  "doc": "Objetivo y alcance del proceso.",
  "pools": [
    {"name": "Empresa", "lanes": ["Solicitante", "Jefe de área", "Compras"]},
    {"name": "Proveedor", "blackbox": true}
  ],
  "nodes": [
    {"id": "inicio", "type": "start", "name": "Necesidad de compra", "lane": "Solicitante"},
    {"id": "registrar", "type": "userTask", "name": "Registrar solicitud", "lane": "Solicitante",
     "doc": "Descripción de la actividad"},
    {"id": "gw", "type": "exclusive", "name": "¿Aprobada?", "lane": "Jefe de área"},
    {"id": "esperar", "type": "timer", "name": "Esperar 2 días", "lane": "Compras", "timer": "P2D"}
  ],
  "flows": [
    "inicio -> registrar",
    "gw -> fin_rechazo : No",
    {"from": "gw", "to": "cotizar", "name": "Sí", "condition": "aprobado == true", "default": true}
  ],
  "messageFlows": ["cotizar -> Proveedor : Pedido de cotización"]
}
```

- Con un solo pool basta `"lanes": [...]` en la raíz, sin `pools`.
- Cada nodo lleva `lane`. Si el mismo nombre de carril existe en dos pools, indica también `pool`.
- `flows` conecta nodos del **mismo** pool. Entre pools se usan `messageFlows`, que pueden apuntar al nombre de un pool externo (`blackbox`).
- Los ids son cortos, sin espacios y únicos. Los nombres de las actividades se escriben como verbo en infinitivo + objeto ("Aprobar solicitud"). Las decisiones se escriben como pregunta ("¿Aprobada?"), y cada salida lleva una etiqueta.

**Tipos:**
- Eventos: `start`, `startMessage`, `startTimer`, `startSignal`, `startConditional`, `end`, `endMessage`, `endError`, `endTerminate`, `endSignal`, `intermediate`, `timer`, `messageCatch`, `messageThrow`, `signalCatch`, `signalThrow`, `conditional`.
- Actividades: `task`, `userTask`, `serviceTask`, `manualTask`, `scriptTask`, `sendTask`, `receiveTask`, `businessRuleTask`, `subProcess`, `callActivity`.
- Compuertas: `exclusive`, `parallel`, `inclusive`, `eventBased`, `complex`.

## Buenas prácticas que aplicar al interpretar

- Cada pool tiene al menos un inicio y un fin. Usa varios fines con nombre del resultado ("Solicitud rechazada", "Compra completada").
- Una compuerta paralela que divide se cierra con otra paralela que une. No cierres ramas paralelas con una exclusiva.
- Los retrabajos ("si está observada, se corrige y vuelve a aprobación") se modelan como un flujo de regreso. El layout los dibuja por encima.
- Elige el tipo de tarea según quién la hace: una persona en el sistema es `userTask`, el sistema es `serviceTask`, fuera del sistema es `manualTask`, enviar o recibir a un externo es `sendTask`/`receiveTask` o un evento de mensaje.

## Limitaciones

- El `.bpm` nativo no se lee directamente: hay que exportarlo a BPMN desde Bizagi.
- No se generan eventos adjuntos (boundary). Al leerlos se convierten en eventos intermedios, con una nota en `_notes`.
- Los subprocesos se generan contraídos. Si se necesita su detalle, se crea otra spec para el subproceso.
