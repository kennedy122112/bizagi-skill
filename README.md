# bizagi-skill

<p align="center">
  <a href="README.md">🇪🇸 Español</a> | <a href="README.en.md">🇺🇸 English</a>
</p>

<p align="center">
  <img alt="Versión" src="https://img.shields.io/badge/versi%C3%B3n-0.2.0-0a7bbb?style=for-the-badge">
  <img alt="Skills" src="https://img.shields.io/badge/skills-1-5fa500?style=for-the-badge">
  <img alt="Agentes" src="https://img.shields.io/badge/agentes-3-8a0f8a?style=for-the-badge">
  <img alt="BPMN" src="https://img.shields.io/badge/BPMN-2.0-e8601c?style=for-the-badge">
  <img alt="Bizagi" src="https://img.shields.io/badge/Bizagi%20Modeler-4.1-e8601c?style=for-the-badge">
  <img alt="Licencia" src="https://img.shields.io/badge/license-MIT-5fa500?style=for-the-badge">
</p>

<p align="center">
  <a href="https://github.com/kennedy122112/bizagi-skill/stargazers"><img alt="stars" src="https://img.shields.io/github/stars/kennedy122112/bizagi-skill?style=flat&logo=github&label=stars"></a>
  <a href="https://github.com/kennedy122112/bizagi-skill/actions/workflows/validate.yml"><img alt="validate" src="https://github.com/kennedy122112/bizagi-skill/actions/workflows/validate.yml/badge.svg"></a>
  <img alt="funciona con" src="https://img.shields.io/badge/funciona%20con-Claude%20Code%20%C2%B7%20Codex%20%C2%B7%20OpenCode-e8601c?style=flat">
  <img alt="powered by" src="https://img.shields.io/badge/powered%20by-Python%20stdlib-3776ab?style=flat&logo=python&logoColor=white">
</p>

<p align="center">
  <img alt="bizagi-skill: del lenguaje natural a tu Bizagi Modeler" src="docs/banner.svg" width="100%">
</p>

<p align="center">
  <b>Describe tu proceso en lenguaje natural. Tu agente de IA lo modela y lo deja listo para importarlo en Bizagi.</b><br>
  Local, sin API, sin MCP y sin dependencias.
</p>

---

## ✨ Qué hace

Le cuentas el proceso a tu agente (Claude Code, Codex u OpenCode):

> *El solicitante registra la solicitud, el jefe de área la aprueba; si la observa, el solicitante la corrige y vuelve a aprobación; si la rechaza, termina. Compras pide cotización al proveedor, emite la orden y, en paralelo, recibe el bien mientras Finanzas programa el pago.*

El agente lo interpreta, escribe una especificación, la valida y genera un **BPMN 2.0 con diagrama**. Tú solo lo importas en Bizagi:

<p align="center">
  <img alt="Proceso importado en Bizagi Modeler" src="docs/importado-en-bizagi.jpg" width="100%">
</p>

Y con plazos, excepciones, documentos y sistemas, por ejemplo una atención de reclamos con temporizadores adjuntos, un error de envío, un libro de reclamaciones y la nota del plazo legal:

<p align="center">
  <img alt="Atención de reclamos importada en Bizagi Modeler" src="docs/bizagi-reclamos.jpg" width="100%">
</p>

## 🧰 Comandos

| Comando | Para qué |
|---|---|
| `generate spec.json -o proceso.bpmn --svg vista.svg` | spec → BPMN importable en Bizagi, con vista previa |
| `read modelo.bpmn -o spec.json` | BPMN exportado de Bizagi → spec editable |
| `validate spec.json\|modelo.bpmn` | Reglas de modelado: inicios y fines, compuertas sin etiquetas, nodos inalcanzables… |
| `preview spec.json\|modelo.bpmn -o vista.svg` | Diagrama SVG para revisar sin abrir Bizagi |
| `doc spec.json\|modelo.bpmn -o doc.md` | Documentación del proceso: roles, actividades y secuencia |

**Soporta:**
- Pools y carriles, incluidos pools externos (caja negra), y flujos de mensaje.
- Eventos: inicio, fin, temporizador, mensaje, señal, error y terminación.
- Eventos adjuntos al borde de una tarea (temporizador, mensaje, señal, condición o error), interrumpibles o no.
- Todos los tipos de tarea, y subprocesos.
- Objetos de datos, almacenes de datos y anotaciones, con asociaciones de entrada y salida.
- Compuertas exclusiva, paralela, inclusiva, basada en eventos y compleja, con condiciones y flujos por defecto.
- Retrabajos (ciclos).

Las posiciones del diagrama se calculan automáticamente.

## 🚀 Instalación

Requisito: **Python 3.9 o superior**. No usa paquetes externos.

Clona el repo en la carpeta de skills de tu agente:

```bash
# Claude Code
git clone https://github.com/kennedy122112/bizagi-skill ~/.claude/skills/bizagi

# Codex
git clone https://github.com/kennedy122112/bizagi-skill ~/.codex/skills/bizagi

# OpenCode
git clone https://github.com/kennedy122112/bizagi-skill ~/.config/opencode/skill/bizagi
```

> Las rutas de skills pueden variar según la versión de cada agente. Si el tuyo no soporta skills, añade al `AGENTS.md` de tu proyecto:
> *"Para modelar procesos de Bizagi, sigue las instrucciones de `<ruta>/bizagi/SKILL.md`."*

## 🔁 Flujo de trabajo

1. **Describe** el proceso en lenguaje natural.
2. El agente **genera** `proceso.bpmn` y una vista previa.
3. En Bizagi: **Exportar/Importar → Importar → BPMN**.
4. **Para modificar un modelo existente**, en Bizagi usa **Exportar → BPMN**, pásale el archivo al agente con los cambios que quieres y vuelve a importarlo.

También puedes usar la herramienta sin agente:

```bash
python scripts/bizagi_cli.py generate examples/solicitud-compra.json -o proceso.bpmn --svg proceso.svg
```

El formato de la spec y las reglas de modelado están en [SKILL.md](SKILL.md).

## ⚠️ Limitaciones

- El `.bpm` nativo de Bizagi no se lee directamente: hay que exportarlo a BPMN.
- Los subprocesos se generan contraídos.

## 📄 Licencia

[MIT](LICENSE)
