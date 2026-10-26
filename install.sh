#!/usr/bin/env bash
# Instala el skill "bizagi" para todos tus agentes de IA (macOS / Linux / Git Bash).
#
# Deja un solo clon de git en ~/.agents/skills/bizagi, la ruta estándar que leen
# Codex, OpenCode, Gemini CLI / Antigravity y Cursor. Claude Code no lee esa ruta,
# así que se crea un enlace simbólico en ~/.claude/skills/bizagi al mismo clon.
# Volver a ejecutar el script actualiza todo con git pull.
#
#   curl -fsSL https://raw.githubusercontent.com/kennedy122112/bizagi-skill/main/install.sh | bash
#   bash install.sh --uninstall
set -euo pipefail

NAME="bizagi"
REPO="${BIZAGI_SKILL_REPO:-https://github.com/kennedy122112/bizagi-skill.git}"
MAIN="$HOME/.agents/skills/$NAME"
CLAUDE_LINK="$HOME/.claude/skills/$NAME"

# en Git Bash (Windows) ln -s copia en vez de enlazar: allí se usa un junction de Windows
case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) WINDOWS=1 ;; *) WINDOWS=0 ;; esac

link_dir() {
  if [ "$WINDOWS" = 1 ]; then
    powershell.exe -NoProfile -Command "New-Item -ItemType Junction -Path '$(cygpath -w "$2")' -Target '$(cygpath -w "$1")' | Out-Null"
  else
    ln -s "$1" "$2"
  fi
}

unlink_dir() {
  # borra solo el enlace, nunca el contenido al que apunta
  if [ "$WINDOWS" = 1 ]; then
    powershell.exe -NoProfile -Command "[System.IO.Directory]::Delete('$(cygpath -w "$1")')"
  else
    rm "$1"
  fi
}

backup() {
  # el respaldo va fuera de las carpetas de skills para que ningún agente lo cargue dos veces
  local dest="${TMPDIR:-/tmp}/$NAME-respaldo-$(date +%Y%m%d-%H%M%S)"
  mv "$1" "$dest"
  echo "  Copia anterior movida a $dest"
}

if [ "${1:-}" = "--uninstall" ]; then
  [ -L "$CLAUDE_LINK" ] && unlink_dir "$CLAUDE_LINK" && echo "Enlace de Claude Code eliminado."
  [ -e "$MAIN" ] && backup "$MAIN" && echo "Skill retirado de ~/.agents/skills."
  echo "Listo: bizagi desinstalado."
  exit 0
fi

command -v git >/dev/null || { echo "Se necesita git." >&2; exit 1; }
PY=""
for c in python3 python; do command -v "$c" >/dev/null && { PY="$c"; break; }; done
[ -z "$PY" ] && echo "Aviso: no se encontró Python 3.9+; el skill lo necesita para ejecutarse."

# 1) clon único en ~/.agents/skills/bizagi
mkdir -p "$(dirname "$MAIN")"
if [ -d "$MAIN/.git" ]; then
  echo "Actualizando $MAIN ..."
  git -C "$MAIN" pull --ff-only --quiet
else
  [ -e "$MAIN" ] && backup "$MAIN"
  echo "Clonando en $MAIN ..."
  git clone --quiet "$REPO" "$MAIN"
fi

# 2) Claude Code: enlace al mismo clon
report=""
if [ -d "$HOME/.claude" ]; then
  mkdir -p "$(dirname "$CLAUDE_LINK")"
  if [ -L "$CLAUDE_LINK" ]; then unlink_dir "$CLAUDE_LINK"; elif [ -e "$CLAUDE_LINK" ]; then backup "$CLAUDE_LINK"; fi
  link_dir "$MAIN" "$CLAUDE_LINK"
  report+="  Claude Code                enlace ~/.claude/skills/$NAME\n"
fi

# 3) el resto lee ~/.agents/skills directamente
detect() { command -v "$2" >/dev/null || [ -d "$3" ]; }
for row in "Codex|codex|$HOME/.codex" "OpenCode|opencode|$HOME/.config/opencode" \
           "Gemini CLI / Antigravity|gemini|$HOME/.gemini" "Cursor|cursor|$HOME/.cursor"; do
  IFS="|" read -r label cmd dir <<< "$row"
  if detect "$label" "$cmd" "$dir"; then state="lee ~/.agents/skills"; else state="no detectado (lo verá si lo instalas)"; fi
  report+="$(printf '  %-26s %s' "$label" "$state")\n"
done

# 4) comprobación
version="sin Python"
[ -n "$PY" ] && version="$("$PY" "$MAIN/scripts/bizagi_cli.py" --version 2>/dev/null || echo "error al ejecutar")"
echo
echo "bizagi instalado ($version)"
printf "%b" "$report"
echo
echo "Para actualizar más adelante, vuelve a ejecutar este instalador."
echo "Reinicia tus agentes (o usa /skills reload en Gemini) para que carguen el skill."
