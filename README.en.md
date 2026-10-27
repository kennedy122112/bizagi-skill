# bizagi-steroids

<p align="center">
  <a href="README.md">🇪🇸 Español</a> | <a href="README.en.md">🇺🇸 English</a>
</p>

<p align="center">
  <img alt="Version" src="https://img.shields.io/badge/version-0.6.2-0a7bbb?style=for-the-badge">
  <img alt="Skills" src="https://img.shields.io/badge/skills-1-5fa500?style=for-the-badge">
  <img alt="Agents" src="https://img.shields.io/badge/agents-5-8a0f8a?style=for-the-badge">
  <img alt="BPMN" src="https://img.shields.io/badge/BPMN-2.0-e8601c?style=for-the-badge">
  <img alt="Bizagi" src="https://img.shields.io/badge/Bizagi%20Modeler-4.1-e8601c?style=for-the-badge">
  <img alt="License" src="https://img.shields.io/badge/license-MIT-5fa500?style=for-the-badge">
</p>

<p align="center">
  <a href="https://github.com/kennedy122112/bizagi-steroids/stargazers"><img alt="stars" src="https://img.shields.io/github/stars/kennedy122112/bizagi-steroids?style=flat&logo=github&label=stars"></a>
  <a href="https://github.com/kennedy122112/bizagi-steroids/actions/workflows/validate.yml"><img alt="validate" src="https://github.com/kennedy122112/bizagi-steroids/actions/workflows/validate.yml/badge.svg"></a>
  <img alt="works with" src="https://img.shields.io/badge/works%20with-Claude%20Code%20%C2%B7%20Codex%20%C2%B7%20OpenCode%20%C2%B7%20Gemini%20%C2%B7%20Cursor-e8601c?style=flat">
  <img alt="powered by" src="https://img.shields.io/badge/powered%20by-Python%20stdlib-3776ab?style=flat&logo=python&logoColor=white">
</p>

<p align="center">
  <img alt="bizagi-steroids: from natural language to Bizagi Modeler" src="docs/banner.svg" width="100%">
</p>

<p align="center">
  <b>Describe your process in plain language. Your AI agent models it, documents it in Word and gets it ready to import into Bizagi.</b><br>
  Local, no API, no MCP, no dependencies.
</p>

<p align="center"><sub>Independent open-source project, not affiliated with Bizagi. Bizagi and Bizagi Modeler are trademarks of their respective owners.</sub></p>

---

## ⚡ Quick start

**1. Install** the skill for all your agents with one command. You need **Node.js 18+** and **Python 3.9+**.

```bash
npx -y github:kennedy122112/bizagi-steroids setup
```

**2. Ask** your agent (Claude Code, Codex, OpenCode, Gemini or Cursor) for the process, the way you'd explain it to a colleague:

> *Model in Bizagi the auto-parts purchasing process: the warehouse logs the request, management approves or rejects it, purchasing requests quotes, picks a supplier and issues the order; when the goods arrive, the warehouse checks them and, if something doesn't match, it's sorted out with the supplier.*

The agent writes the spec, validates it and creates the **`.bpmn`**, a **preview** and the **Word** document in a folder.

**3. Open it in Bizagi** from the **Export/Import → Import → BPMN** tab. *File → Open* won't work here: it only opens native `.bpm` files. Afterwards you can save it as `.bpm` with *File → Save*.

> The spec keywords and the generated documents are in Spanish. Any language model handles them fine.

## ✨ What it does

It understands processes described the way people talk: with filler words, self-corrections ("no, sorry, first…"), abbreviations, or a single line. It turns them into **BPMN 2.0 with diagram layout** that Bizagi imports as is:

<p align="center">
  <img alt="Process imported into Bizagi Modeler" src="docs/importado-en-bizagi.jpg" width="100%">
</p>

It also models deadlines, exceptions, documents and systems. For example, a complaint-handling process with boundary timers, a delivery error, a complaints register and a note about the legal deadline:

<p align="center">
  <img alt="Complaint handling imported into Bizagi Modeler" src="docs/bizagi-reclamos.jpg" width="100%">
</p>

**Supports:**
- Pools and lanes, including external (black-box) pools, and message flows.
- Events: start, end, timer, message, signal, error and terminate.
- Boundary events on a task (timer, message, signal, conditional or error), interrupting or not.
- Every task type, and sub-processes.
- Data objects, data stores and annotations, linked by input and output associations.
- Exclusive, parallel, inclusive, event-based and complex gateways, with conditions and default flows.
- Rework loops.

Diagram positions are computed automatically: lines route around elements and labels look for free space.

## 💬 Example requests

| What you say | What you get |
|---|---|
| *"I need the travel expense reimbursement process: the employee submits the report and finance reviews and pays"* | A minimal process with review, correction and payment, plus a list of **assumptions and open questions** in the Word document |
| *"so, the employee requests leave in the system, and if the manager doesn't answer in three days it counts as approved…"* | A boundary timer, automatic notifications and a parallel split |
| *"model IT incident handling: L1 has 30 minutes, if it isn't solved it escalates to L2…"* | Time-based escalation, a loop back to L2 and automatic closure |
| *"document this .bpmn I exported from Bizagi"* | The process Word document from your model |
| *"generate the Word document with my company template"* | The document with your cover page, logo and sign-off block ([see below](#-your-own-template)) |

## 📄 Word document

Every process comes with a deliverable ready for review or sign-off:
- a summary sheet with code, version and owners;
- the objective, and the roles with their activities;
- the **diagram on a landscape page**, as vector with an image fallback (on A3 with detail pages when it's large);
- the activities table with inputs, outputs and systems, and the step-by-step flow;
- decision rules, exceptions and deadlines, documents, and interactions with external parties;
- assumptions and open questions.

Samples: [atencion-reclamos.docx](docs/atencion-reclamos.docx) · [solicitud-compra.docx](docs/solicitud-compra.docx)

## 🎨 Your own template

Use your organization's Word document (or any `.docx` or `.dotx`) as a template. Ask your agent, or run:

```bash
python skills/bizagi/scripts/bizagi_cli.py docx process.json -o deliverable.docx --template my-template.docx
```

Everything in your template is kept: logo, headers and footers, cover page, version history, signatures, margins and styles. The process content uses your heading styles, even if Word runs in another language, and the tables take your heading color.

Put these **placeholders** anywhere in the template, including headers and footers:

| Placeholder | Replaced with |
|---|---|
| `{{CONTENIDO}}` | All the process content: objective, roles, diagram, activities, flow… Without this placeholder, the content is appended at the end. |
| `{{nombre}}` | Process name |
| `{{codigo}}` `{{version}}` `{{fecha}}` | Values from `meta` in the spec. The date defaults to today. |
| `{{responsable}}` `{{area}}` | Values from `meta` |
| `{{elaborado}}` `{{revisado}}` `{{aprobado}}` | Values from `meta`, for the sign-off block |
| `{{any_key}}` | Any other key you add to `meta` |

Missing values appear as "Por completar". If the template already has `{{nombre}}`, the process title isn't repeated; if it has summary-sheet placeholders, the built-in summary sheet is left out.

[`skills/bizagi/plantillas/plantilla-ejemplo.docx`](skills/bizagi/plantillas/plantilla-ejemplo.docx) is a neutral starting template with a cover page, version history, approvals, and a header and footer with placeholders. Sample output: [atencion-reclamos-plantilla.docx](docs/atencion-reclamos-plantilla.docx).

## 🚀 Install

To run the skill you need **Python 3.9 or later**. No third-party packages.

### 1. One command (recommended)

```bash
npx -y github:kennedy122112/bizagi-steroids setup
```

It only needs **Node.js 18 or later**, no git. It makes the skill available to **every agent** at once, without duplicating it:

| Agent | How it finds the skill | Tested |
|---|---|---|
| Claude Code | Link at `~/.claude/skills/bizagi` | ✅ |
| Codex | Reads `~/.agents/skills` | ✅ (CLI 0.164) |
| OpenCode | Reads `~/.agents/skills` | ✅ |
| Gemini CLI / Antigravity | Reads `~/.agents/skills` (alias of `~/.gemini/skills`) | Detects the skill (CLI 0.40) |
| Cursor | Reads `~/.agents/skills` | Not tested |

The files live in `~/.bizagi-steroids`, and the agents reach them through links.
- **Update:** run the same command again, then start a new session in your agent.
- **Check status:** `npx -y github:kennedy122112/bizagi-steroids status`.
- **Uninstall:** `npx -y github:kennedy122112/bizagi-steroids uninstall`.

Any previous install is moved to the temp folder instead of being deleted.

### 2. As a plugin for your agent

**Claude Code:**

```
/plugin install bizagi --marketplace kennedy122112/bizagi-steroids
```

On versions older than 2.1.275, or from the terminal:

```bash
claude plugin marketplace add kennedy122112/bizagi-steroids
claude plugin install bizagi@bizagi-steroids
```

**Codex:**

```bash
codex plugin marketplace add kennedy122112/bizagi-steroids
codex plugin add bizagi@bizagi-steroids
```

As a plugin, the agent updates it from its own marketplace (`/plugin marketplace update` or `codex plugin marketplace upgrade`). Use **only one method per agent**, so the skill isn't loaded twice.

### 3. Without Node: with git

**Windows (PowerShell):**

```powershell
irm https://raw.githubusercontent.com/kennedy122112/bizagi-steroids/main/install.ps1 | iex
```

**macOS / Linux / Git Bash:**

```bash
curl -fsSL https://raw.githubusercontent.com/kennedy122112/bizagi-steroids/main/install.sh | bash
```

They give the same result as `npx … setup`, with a git clone in `~/.bizagi-steroids`.

If your agent doesn't support skills, add this to your project's `AGENTS.md`:
> *"To model Bizagi processes, follow `~/.agents/skills/bizagi/SKILL.md`."*

## 🔁 Workflow

1. **Describe** the process. If something important is missing, the agent asks. If you ask it to go ahead, it fills in the typical minimum and records it as an assumption.
2. The agent writes the spec and runs **`build`**, which creates the `.bpmn`, the preview (`.png`) and the Word document in a subfolder named after the process. When it's done, it gives you the paths of those files.
3. In Bizagi: **Export/Import → Import → BPMN**, then *File → Save* if you want a `.bpm`.
4. **To change a model**, export it from Bizagi (**Export → BPMN**), hand the file to the agent with the changes you want, and import the result again.

## 🧰 Commands

You can also use the tool without an agent:

| Command | Purpose |
|---|---|
| `build spec.json [-d folder] [--template template.docx]` | **All in one:** BPMN, preview and Word, and prints the created paths |
| `generate spec.json -o process.bpmn --svg preview.svg` | spec → BPMN that Bizagi can import, plus a preview |
| `read model.bpmn -o spec.json` | BPMN exported from Bizagi → editable spec |
| `validate spec.json\|model.bpmn` | Modeling rules: start and end events, unlabeled gateway outputs, unreachable nodes… |
| `preview spec.json\|model.bpmn -o preview.png` | Diagram to review without opening Bizagi (`.png` needs Chrome or Edge; `.svg` always works) |
| `doc spec.json\|model.bpmn -o doc.md` | Markdown documentation: roles, activities and sequence |
| `docx spec.json\|model.bpmn -o process.docx [--template template.docx]` | Word document |

```bash
python skills/bizagi/scripts/bizagi_cli.py build examples/solicitud-compra.json -d output
```

The spec format and the modeling rules are described in [SKILL.md](skills/bizagi/SKILL.md).

## 🩺 Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Bizagi says **"Error cargando Modelo: The file is invalid or corrupt"** | You opened it with *File → Open* or "Open with…". That route is for `.bpm` only. Use **Export/Import → Import → BPMN**. |
| The agent **shows the commands instead of running them**, or gives you a path that doesn't exist | Some models describe the steps without running them. Start a new session or try another model; the skill requires running `build` and reporting only the paths it prints. |
| The agent **doesn't know the skill** | Run `npx -y github:kennedy122112/bizagi-steroids status` and start a new session (in Gemini, `/skills reload`). |
| **No `.png` preview**, only `.svg` | The PNG needs Chrome or Edge. The `.svg` opens in any browser, and the Word document still includes the diagram. |
| **"Python not found"** | Install Python 3.9 or later and run `setup` again. |
| `AVISO diagrama: … could not avoid crossing an element` | Ask the agent to reorder the lanes or the main outgoing flow of the gateways; very large processes may keep a crossing or two. |

## 🧪 Tests

- **Real natural language:** tested on processes described the way people actually write or dictate them: a transcribed voice note, an email full of jargon, meeting notes with abbreviations, a dictation with self-corrections, and a one-line request. An independent agent modeled each case using only the text and `SKILL.md`. The cases are in [`tests/`](tests/).
- **Bizagi Modeler 4.1:** the examples and several test cases were checked by importing them into Bizagi: pools and lanes, exclusive and parallel gateways, boundary timers and errors, messages, documents, data stores and annotations.
- **CI:** on every push, with Python 3.9 and 3.13, all examples and cases are validated and regenerated (BPMN, Markdown, Word with and without a template), and the `npx` installer is tested.

## ⚠️ Limitations

- It can't read Bizagi's native `.bpm` file. Export the model to BPMN first.
- Sub-processes are generated collapsed.
- There are no event sub-processes or timers that span several activities: the deadline is attached to one activity and explained in a note.

## 🔗 Sibling project

[**figma-steroids**](https://github.com/kennedy122112/figma-steroids): design in Figma Desktop from your AI agent, with no API key and no MCP.

## 📄 License

[MIT](LICENSE)
