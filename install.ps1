<#
.SYNOPSIS
  Instala el skill "bizagi" para todos tus agentes de IA (Windows).

.DESCRIPTION
  Clona el repo en ~/.bizagi-skill y enlaza su skill en ~/.agents/skills/bizagi, la ruta
  estándar que leen Codex, OpenCode, Gemini CLI / Antigravity y Cursor, y en
  ~/.claude/skills/bizagi para Claude Code (junctions: no piden administrador).
  Volver a ejecutar el script actualiza todo con git pull.
  Alternativa con Node: npx -y github:kennedy122112/bizagi-skill setup

.EXAMPLE
  irm https://raw.githubusercontent.com/kennedy122112/bizagi-skill/main/install.ps1 | iex

.EXAMPLE
  & ([scriptblock]::Create((irm https://raw.githubusercontent.com/kennedy122112/bizagi-skill/main/install.ps1))) -Uninstall
#>
param(
    [switch]$Uninstall,
    [string]$Repo = "https://github.com/kennedy122112/bizagi-skill.git"
)

$ErrorActionPreference = "Stop"
$Store = Join-Path $HOME ".bizagi-skill"
$Skill = Join-Path $Store "skills\bizagi"
$Links = @(
    @{ Label = "Agent Skills (Codex, OpenCode, Gemini, Cursor)"; Path = (Join-Path $HOME ".agents\skills\bizagi"); Only = $null },
    @{ Label = "Claude Code"; Path = (Join-Path $HOME ".claude\skills\bizagi"); Only = (Join-Path $HOME ".claude") }
)

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
    $dest = Join-Path $env:TEMP ("bizagi-respaldo-" + (Get-Date -Format "yyyyMMdd-HHmmss-fff"))
    Move-Item -LiteralPath $path -Destination $dest
    Say "  Copia anterior movida a $dest" "DarkYellow"
}

if ($Uninstall) {
    foreach ($l in $Links) { if (Test-Link $l.Path) { Remove-Link $l.Path; Say "Enlace eliminado: $($l.Path)" } }
    if (Test-Path $Store) { Backup-Folder $Store }
    Say "Listo: bizagi desinstalado." "Green"
    return
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Se necesita git (https://git-scm.com/download/win), o usa: npx -y github:kennedy122112/bizagi-skill setup"
}
$python = @("python", "py", "python3") | Where-Object { Get-Command $_ -ErrorAction SilentlyContinue } | Select-Object -First 1
if (-not $python) { Say "Aviso: no se encontró Python 3.9+; el skill lo necesita para ejecutarse." "Yellow" }

# 1) clon en ~/.bizagi-skill
if (Test-Path (Join-Path $Store ".git")) {
    Say "Actualizando $Store ..."
    git -C $Store pull --ff-only --quiet
} else {
    if (Test-Path $Store) { Backup-Folder $Store }
    Say "Clonando en $Store ..."
    git clone --quiet $Repo $Store
}

# 2) enlaces para cada agente (una instalación anterior en esas rutas se respalda)
$report = [ordered]@{}
foreach ($l in $Links) {
    if ($l.Only -and -not (Test-Path $l.Only)) { continue }
    New-Item -ItemType Directory -Force -Path (Split-Path $l.Path) | Out-Null
    if (Test-Link $l.Path) { Remove-Link $l.Path } elseif (Test-Path $l.Path) { Backup-Folder $l.Path }
    New-Item -ItemType Junction -Path $l.Path -Target $Skill | Out-Null
    $report[$l.Label] = $l.Path.Replace($HOME, "~")
}
$detect = [ordered]@{
    "Codex"                    = (Get-Command codex -ErrorAction SilentlyContinue) -or (Test-Path "$HOME\.codex")
    "OpenCode"                 = (Get-Command opencode -ErrorAction SilentlyContinue) -or (Test-Path "$HOME\.config\opencode")
    "Gemini CLI / Antigravity" = (Get-Command gemini -ErrorAction SilentlyContinue) -or (Test-Path "$HOME\.gemini")
    "Cursor"                   = (Get-Command cursor -ErrorAction SilentlyContinue) -or (Test-Path "$HOME\.cursor")
}
foreach ($k in $detect.Keys) {
    $report[$k] = if ($detect[$k]) { "lee ~/.agents/skills" } else { "no detectado (lo verá si lo instalas)" }
}

# 3) comprobación
$version = if ($python) { & $python (Join-Path $Skill "scripts\bizagi_cli.py") --version 2>$null } else { "sin Python" }
Say ""
Say "bizagi instalado ($version)" "Green"
foreach ($k in $report.Keys) { Say ("  {0,-48} {1}" -f $k, $report[$k]) }
Say ""
Say "Para actualizar más adelante, vuelve a ejecutar este instalador."
Say "Reinicia tus agentes (o usa /skills reload en Gemini) para que carguen el skill."
