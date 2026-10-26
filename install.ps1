<#
.SYNOPSIS
  Instala el skill "bizagi" para todos tus agentes de IA (Windows).

.DESCRIPTION
  Deja un solo clon de git en ~/.agents/skills/bizagi, la ruta estándar que leen
  Codex, OpenCode, Gemini CLI / Antigravity y Cursor. Claude Code no lee esa ruta,
  así que se crea un enlace (junction) en ~/.claude/skills/bizagi apuntando al mismo
  clon. Volver a ejecutar el script actualiza todo con git pull.

.EXAMPLE
  irm https://raw.githubusercontent.com/kennedy122112/bizagi-skill/main/install.ps1 | iex

.EXAMPLE
  .\install.ps1 -Uninstall
#>
param(
    [switch]$Uninstall,
    [string]$Repo = "https://github.com/kennedy122112/bizagi-skill.git"
)

$ErrorActionPreference = "Stop"
$Name = "bizagi"
$Main = Join-Path $HOME ".agents\skills\$Name"
$ClaudeLink = Join-Path $HOME ".claude\skills\$Name"

function Say($msg, $color = "Gray") { Write-Host $msg -ForegroundColor $color }

function Test-Link($path) {
    $item = Get-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
    return $item -and $item.LinkType
}

function Remove-Link($path) {
    # borra solo el enlace, nunca el contenido al que apunta
    [System.IO.Directory]::Delete($path)
}

function Backup-Folder($path) {
    # el respaldo va fuera de las carpetas de skills para que ningún agente lo cargue dos veces
    $dest = Join-Path $env:TEMP ("$Name-respaldo-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
    Move-Item -LiteralPath $path -Destination $dest
    Say "  Copia anterior movida a $dest" "DarkYellow"
}

if ($Uninstall) {
    if (Test-Link $ClaudeLink) { Remove-Link $ClaudeLink; Say "Enlace de Claude Code eliminado." }
    if (Test-Path $Main) { Backup-Folder $Main; Say "Skill retirado de ~/.agents/skills." }
    Say "Listo: bizagi desinstalado." "Green"
    return
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Se necesita git (https://git-scm.com/download/win)."
}
$python = @("python", "py", "python3") | Where-Object { Get-Command $_ -ErrorAction SilentlyContinue } | Select-Object -First 1
if (-not $python) { Say "Aviso: no se encontró Python 3.9+; el skill lo necesita para ejecutarse." "Yellow" }

# 1) clon único en ~/.agents/skills/bizagi
New-Item -ItemType Directory -Force -Path (Split-Path $Main) | Out-Null
if (Test-Path (Join-Path $Main ".git")) {
    Say "Actualizando $Main ..."
    git -C $Main pull --ff-only --quiet
} else {
    if (Test-Path $Main) { Backup-Folder $Main }
    Say "Clonando en $Main ..."
    git clone --quiet $Repo $Main
}

# 2) Claude Code: enlace al mismo clon
$agents = [ordered]@{}
if (Test-Path (Join-Path $HOME ".claude")) {
    New-Item -ItemType Directory -Force -Path (Split-Path $ClaudeLink) | Out-Null
    if (Test-Link $ClaudeLink) {
        Remove-Link $ClaudeLink
    } elseif (Test-Path $ClaudeLink) {
        Backup-Folder $ClaudeLink
    }
    New-Item -ItemType Junction -Path $ClaudeLink -Target $Main | Out-Null
    $agents["Claude Code"] = "enlace ~/.claude/skills/$Name"
}

# 3) el resto lee ~/.agents/skills directamente
$detect = [ordered]@{
    "Codex"                      = (Get-Command codex -ErrorAction SilentlyContinue) -or (Test-Path "$HOME\.codex")
    "OpenCode"                   = (Get-Command opencode -ErrorAction SilentlyContinue) -or (Test-Path "$HOME\.config\opencode")
    "Gemini CLI / Antigravity"   = (Get-Command gemini -ErrorAction SilentlyContinue) -or (Test-Path "$HOME\.gemini")
    "Cursor"                     = (Get-Command cursor -ErrorAction SilentlyContinue) -or (Test-Path "$HOME\.cursor")
}
foreach ($k in $detect.Keys) {
    $agents[$k] = if ($detect[$k]) { "lee ~/.agents/skills" } else { "no detectado (lo verá si lo instalas)" }
}

# 4) comprobación
$version = if ($python) { & $python (Join-Path $Main "scripts\bizagi_cli.py") --version 2>$null } else { "sin Python" }
Say ""
Say "bizagi instalado ($version)" "Green"
foreach ($k in $agents.Keys) { Say ("  {0,-26} {1}" -f $k, $agents[$k]) }
Say ""
Say "Para actualizar más adelante, vuelve a ejecutar este instalador."
Say "Reinicia tus agentes (o usa /skills reload en Gemini) para que carguen el skill."
