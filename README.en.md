# bizagi-skill

<p align="center">
  <a href="README.md">🇪🇸 Español</a> | <a href="README.en.md">🇺🇸 English</a>
</p>

<p align="center">
  <img alt="Version" src="https://img.shields.io/badge/version-0.1.0-0a7bbb?style=for-the-badge">
  <img alt="Skills" src="https://img.shields.io/badge/skills-1-5fa500?style=for-the-badge">
  <img alt="Agents" src="https://img.shields.io/badge/agents-3-8a0f8a?style=for-the-badge">
  <img alt="BPMN" src="https://img.shields.io/badge/BPMN-2.0-e8601c?style=for-the-badge">
  <img alt="Bizagi" src="https://img.shields.io/badge/Bizagi%20Modeler-4.1-e8601c?style=for-the-badge">
  <img alt="License" src="https://img.shields.io/badge/license-MIT-5fa500?style=for-the-badge">
</p>

<p align="center">
  <a href="https://github.com/kennedy122112/bizagi-skill/stargazers"><img alt="stars" src="https://img.shields.io/github/stars/kennedy122112/bizagi-skill?style=flat&logo=github&label=stars"></a>
  <a href="https://github.com/kennedy122112/bizagi-skill/actions/workflows/validate.yml"><img alt="validate" src="https://github.com/kennedy122112/bizagi-skill/actions/workflows/validate.yml/badge.svg"></a>
  <img alt="works with" src="https://img.shields.io/badge/works%20with-Claude%20Code%20%C2%B7%20Codex%20%C2%B7%20OpenCode-e8601c?style=flat">
  <img alt="powered by" src="https://img.shields.io/badge/powered%20by-Python%20stdlib-3776ab?style=flat&logo=python&logoColor=white">
</p>

<p align="center">
  <img alt="bizagi-skill: from natural language to Bizagi Modeler" src="docs/banner.svg" width="100%">
</p>

<p align="center">
  <b>Describe your process in plain language. Your AI agent models it and gets it ready to import into Bizagi.</b><br>
  Local, no API, no MCP, no dependencies.
</p>

---

## ✨ What it does

Tell your agent (Claude Code, Codex or OpenCode) about the process:

> *The requester registers the request and the department head approves it; if it gets comments, the requester fixes it and sends it back for approval; if it is rejected, the process ends. Purchasing asks the supplier for a quote, issues the order and, in parallel, receives the goods while Finance schedules the payment.*

The agent interprets it, writes a spec, validates it and generates **BPMN 2.0 with diagram layout**. All you do is import it into Bizagi:

<p align="center">
  <img alt="Process imported into Bizagi Modeler" src="docs/importado-en-bizagi.jpg" width="100%">
</p>

## 🧰 Commands

| Command | Purpose |
|---|---|
| `generate spec.json -o process.bpmn --svg preview.svg` | spec → BPMN that Bizagi can import, plus a preview |
| `read model.bpmn -o spec.json` | BPMN exported from Bizagi → editable spec |
| `validate spec.json\|model.bpmn` | Modeling rules: start and end events, unlabeled gateway outputs, unreachable nodes… |
| `preview spec.json\|model.bpmn -o preview.svg` | SVG diagram to review without opening Bizagi |
| `doc spec.json\|model.bpmn -o doc.md` | Process documentation: roles, activities and sequence |

**Supports:**
- Pools and lanes, including external (black-box) pools, and message flows.
- Events: start, end, timer, message, signal, error and terminate.
- Every task type, and sub-processes.
- Exclusive, parallel, inclusive, event-based and complex gateways, with conditions and default flows.
- Rework loops.

Diagram positions are computed automatically.

> The spec keywords and generated documentation are in Spanish. Any language model handles them fine.

## 🚀 Install

Requirement: **Python 3.9 or later**. No third-party packages.

Clone the repo into your agent's skills folder:

```bash
# Claude Code
git clone https://github.com/kennedy122112/bizagi-skill ~/.claude/skills/bizagi

# Codex
git clone https://github.com/kennedy122112/bizagi-skill ~/.codex/skills/bizagi

# OpenCode
git clone https://github.com/kennedy122112/bizagi-skill ~/.config/opencode/skill/bizagi
```

> Skill paths can change between agent versions. If your agent doesn't support skills, add this line to your project's `AGENTS.md`:
> *"To model Bizagi processes, follow `<path>/bizagi/SKILL.md`."*

## 🔁 Workflow

1. **Describe** the process in plain language.
2. The agent **generates** `process.bpmn` and a preview.
3. In Bizagi: **Export/Import → Import → BPMN**.
4. **To change an existing model**, export it from Bizagi (**Export → BPMN**), hand the file to the agent with the changes you want, then import the result again.

You can also use the tool without an agent:

```bash
python scripts/bizagi_cli.py generate examples/solicitud-compra.json -o process.bpmn --svg process.svg
```

The spec format and the modeling rules are described in [SKILL.md](SKILL.md).

## ⚠️ Limitations

- It can't read Bizagi's native `.bpm` file. Export the model to BPMN first.
- It doesn't generate boundary events. When it reads one, it turns it into an intermediate event.
- Sub-processes are generated collapsed.

## 📄 License

[MIT](LICENSE)
