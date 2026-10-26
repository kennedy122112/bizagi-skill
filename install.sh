#!/usr/bin/env bash
# Instala el skill "bizagi" para todos tus agentes de IA (macOS / Linux / Git Bash).
#
# Clona el repo en ~/.bizagi-steroids y enlaza su skill en ~/.agents/skills/bizagi, la ruta
# estándar que leen Codex, OpenCode, Gemini CLI / Antigravity y Cursor, y en
# ~/.claude/skills/bizagi para Claude Code. Volver a ejecutar el script actualiza todo.
# Alternativa con Node: npx -y github:kennedy122112/bizagi-steroids setup
#
#   curl -fsSL https://raw.githubusercontent.com/kennedy122112/bizagi-steroids/main/install.sh | bash
#   bash install.sh --uninstall
set -euo pipefail

REPO="${BIZAGI_STEROIDS_REPO:-https://github.com/kennedy122112/bizagi-steroids.git}"
STORE="$HOME/.bizagi-steroids"
SKILL="$STORE/skills/bizagi"
LINKS=("Agent Skills (Codex, OpenCode, Gemini, Cursor)|$HOME/.agents/skills/bizagi|" \
       "Claude Code|$HOME/.claude/skills/bizagi|$HOME/.claude")

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
  local dest="${TMPDIR:-/tmp}/bizagi-respaldo-$(date +%Y%m%d-%H%M%S)-$RANDOM"
  mv "$1" "$dest"
  echo "  Copia anterior movida a $dest"
}

if [ "${1:-}" = "--uninstall" ]; then
  for row in "${LINKS[@]}"; do
    IFS="|" read -r label path only <<< "$row"
    if [ -L "$path" ]; then unlink_dir "$path"; echo "Enlace eliminado: $path"; fi
  done
  if [ -e "$STORE" ]; then backup "$STORE"; fi
  echo "Listo: bizagi desinstalado."
  exit 0
fi

command -v git >/dev/null || { echo "Se necesita git, o usa: npx -y github:kennedy122112/bizagi-steroids setup" >&2; exit 1; }
PY=""
for c in python3 python; do command -v "$c" >/dev/null && { PY="$c"; break; }; done
[ -z "$PY" ] && echo "Aviso: no se encontró Python 3.9+; el skill lo necesita para ejecutarse."

# 1) clon en ~/.bizagi-steroids
if [ -d "$STORE/.git" ]; then
  echo "Actualizando $STORE ..."
  git -C "$STORE" pull --ff-only --quiet
else
  [ -e "$STORE" ] && backup "$STORE"
  echo "Clonando en $STORE ..."
  git clone --quiet "$REPO" "$STORE"
fi

# 2) enlaces para cada agente (una instalación anterior en esas rutas se respalda)
report=""
for row in "${LINKS[@]}"; do
  IFS="|" read -r label path only <<< "$row"
  [ -n "$only" ] && [ ! -d "$only" ] && continue
  mkdir -p "$(dirname "$path")"
  if [ -L "$path" ]; then unlink_dir "$path"; elif [ -e "$path" ]; then backup "$path"; fi
  link_dir "$SKILL" "$path"
  report+="$(printf '  %-48s %s' "$label" "${path/#$HOME/~}")\n"
done
detect() { command -v "$1" >/dev/null || [ -d "$2" ]; }
for row in "Codex|codex|$HOME/.codex" "OpenCode|opencode|$HOME/.config/opencode" \
           "Gemini CLI / Antigravity|gemini|$HOME/.gemini" "Cursor|cursor|$HOME/.cursor"; do
  IFS="|" read -r label cmd dir <<< "$row"
  if detect "$cmd" "$dir"; then state="lee ~/.agents/skills"; else state="no detectado (lo verá si lo instalas)"; fi
  report+="$(printf '  %-48s %s' "$label" "$state")\n"
done

# el proyecto antes se llamaba bizagi-skill: su copia ya no la usa ningún enlace
if [ -e "$HOME/.bizagi-skill" ]; then echo "Retirando la copia con el nombre anterior (bizagi-skill) ..."; backup "$HOME/.bizagi-skill"; fi

# 3) comprobación
version="sin Python"
[ -n "$PY" ] && version="$("$PY" "$SKILL/scripts/bizagi_cli.py" --version 2>/dev/null || echo "error al ejecutar")"
echo
echo "bizagi instalado ($version)"
printf "%b" "$report"
echo
echo "Para actualizar más adelante, vuelve a ejecutar este instalador."
echo "Reinicia tus agentes (o usa /skills reload en Gemini) para que carguen el skill."
