# bizagi-skill

Modela procesos para **Bizagi Modeler** a partir de lenguaje natural, de forma 100 % local: sin MCP, sin API y sin dependencias externas.

Le describes el proceso a tu agente de IA (Claude Code, Codex, OpenCode u otro). El agente escribe una especificación JSON y `bizagi_cli.py` la convierte en un archivo **BPMN 2.0 con diagrama**, que se importa en Bizagi.

![Proceso importado en Bizagi Modeler](docs/importado-en-bizagi.jpg)

## Qué hace

| Comando | Para qué |
|---|---|
| `generate spec.json -o proceso.bpmn --svg vista.svg` | spec → BPMN importable en Bizagi, con vista previa |
| `read modelo.bpmn -o spec.json` | BPMN exportado de Bizagi → spec editable |
| `validate spec.json\|modelo.bpmn` | Reglas de modelado: inicios y fines, compuertas sin etiquetas, nodos inalcanzables… |
| `preview spec.json\|modelo.bpmn -o vista.svg` | Diagrama SVG para revisar sin abrir Bizagi |
| `doc spec.json\|modelo.bpmn -o doc.md` | Documentación del proceso: roles, actividades y secuencia |

Soporta pools y carriles, pools externos (caja negra), flujos de mensaje, eventos (inicio, fin, temporizador, mensaje, señal, error, terminación), todos los tipos de tarea, subprocesos, compuertas (exclusiva, paralela, inclusiva, basada en eventos, compleja), condiciones, flujos por defecto y retrabajos (ciclos). Las posiciones del diagrama se calculan automáticamente.

Probado con **Bizagi Modeler 4.1**, importando desde *Exportar/Importar → Importar → BPMN*.

## Requisitos

- Python 3.9 o superior. Solo usa la biblioteca estándar.

## Instalación como skill

Clona el repo en la carpeta de skills de tu agente:

```bash
# Claude Code
git clone https://github.com/kennedy122112/bizagi-skill ~/.claude/skills/bizagi

# Codex
git clone https://github.com/kennedy122112/bizagi-skill ~/.codex/skills/bizagi

# OpenCode
git clone https://github.com/kennedy122112/bizagi-skill ~/.config/opencode/skill/bizagi
```

Las rutas de skills de Codex y OpenCode pueden variar según la versión: revisa la documentación de la tuya. Si tu agente no soporta skills, añade al `AGENTS.md` de tu proyecto una línea como esta:

> Para modelar procesos de Bizagi, sigue las instrucciones de `<ruta>/bizagi/SKILL.md`.

## Uso

Pídele al agente algo como:

> Modela en Bizagi el proceso de solicitud de compra: el solicitante registra la solicitud, el jefe de área la aprueba; si la observa, el solicitante la corrige y vuelve a aprobación; si la rechaza, termina. Compras pide cotización al proveedor, emite la orden y, en paralelo, recibe el bien mientras Finanzas programa el pago.

El agente genera `proceso.bpmn`. En Bizagi: **Exportar/Importar → Importar → BPMN**.

Para modificar un modelo existente: en Bizagi usa **Exportar → BPMN**, pásale el archivo al agente con los cambios que quieres, y vuelve a importar el resultado.

También puedes usar la herramienta directamente:

```bash
python scripts/bizagi_cli.py generate examples/solicitud-compra.json -o proceso.bpmn --svg proceso.svg
```

El formato de la spec y las reglas de modelado están en [SKILL.md](SKILL.md).

## Limitaciones

- El `.bpm` nativo de Bizagi no se lee directamente: hay que exportarlo a BPMN.
- No genera eventos adjuntos (boundary). Al leerlos, los convierte en eventos intermedios.
- Los subprocesos se generan contraídos.
