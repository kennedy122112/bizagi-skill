#!/usr/bin/env node
// Instala el skill "bizagi" en tus agentes de IA:  npx -y github:kennedy122112/bizagi-steroids setup
//
// Deja una copia estable en ~/.bizagi-steroids (npx borra su caché) y la enlaza en ~/.agents/skills,
// la ruta estándar que leen Codex, OpenCode, Gemini CLI / Antigravity y Cursor, y en
// ~/.claude/skills para Claude Code. Volver a ejecutarlo actualiza.
import {
  cpSync, existsSync, lstatSync, mkdirSync, readFileSync, renameSync, rmSync, rmdirSync,
  symlinkSync, unlinkSync, writeFileSync,
} from 'node:fs';
import { homedir, platform, tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const VERSION = JSON.parse(readFileSync(join(ROOT, 'package.json'), 'utf8')).version;
const HOME = homedir();
const STORE = join(HOME, '.bizagi-steroids');
const SKILL = join(STORE, 'skills', 'bizagi');
const LINKS = [
  { label: 'Agent Skills (Codex, OpenCode, Gemini, Cursor)', path: join(HOME, '.agents', 'skills', 'bizagi') },
  { label: 'Claude Code', path: join(HOME, '.claude', 'skills', 'bizagi'), only: join(HOME, '.claude') },
];
const AGENTS = [
  ['Codex', 'codex', '.codex'],
  ['OpenCode', 'opencode', join('.config', 'opencode')],
  ['Gemini CLI / Antigravity', 'gemini', '.gemini'],
  ['Cursor', 'cursor', '.cursor'],
];
const HELP = `bizagi-steroids ${VERSION}

Uso:
  npx -y github:kennedy122112/bizagi-steroids setup       instala o actualiza el skill en tus agentes
  npx -y github:kennedy122112/bizagi-steroids uninstall   lo quita (las copias previas van a la carpeta temporal)
  npx -y github:kennedy122112/bizagi-steroids status      muestra dónde está instalado
`;

const isLink = (p) => { try { return lstatSync(p).isSymbolicLink(); } catch { return false; } };
const exists = (p) => isLink(p) || existsSync(p);

function removeLink(p) {
  // borra solo el enlace, nunca el contenido al que apunta
  try { unlinkSync(p); } catch { rmdirSync(p); }
}

function backup(p) {
  // el respaldo va fuera de las carpetas de skills para que ningún agente lo cargue dos veces
  const dest = join(tmpdir(), `bizagi-respaldo-${Date.now()}`);
  try { renameSync(p, dest); } catch { cpSync(p, dest, { recursive: true }); rmSync(p, { recursive: true, force: true }); }
  console.log(`  Copia anterior movida a ${dest}`);
}

function link(target, p) {
  mkdirSync(dirname(p), { recursive: true });
  if (isLink(p)) removeLink(p);
  else if (existsSync(p)) backup(p);
  // en Windows un junction no pide permisos de administrador
  symlinkSync(target, p, platform() === 'win32' ? 'junction' : 'dir');
}

function run(cmd, args) {
  const r = spawnSync(cmd, args, { encoding: 'utf8', shell: platform() === 'win32' && cmd !== 'git' });
  return r.status === 0 ? (r.stdout || '').trim() : null;
}

function python() {
  for (const c of ['python3', 'python', 'py']) {
    const v = run(c, ['--version']);
    if (v && /Python 3\.(9|[1-9]\d)/.test(v)) return c;
  }
  return null;
}

function onPath(cmd) {
  return Boolean(run(platform() === 'win32' ? 'where' : 'which', [cmd]));
}

function setup() {
  // 1) copia estable: si ~/.bizagi-steroids es un clon de git (install.ps1/sh) se actualiza con git
  if (existsSync(join(STORE, '.git'))) {
    console.log(`Actualizando ${STORE} (git) ...`);
    if (run('git', ['-C', STORE, 'pull', '--ff-only', '--quiet']) === null) {
      console.log('  No se pudo hacer git pull; se mantiene la versión actual.');
    }
  } else {
    console.log(`Copiando el skill en ${STORE} ...`);
    rmSync(join(STORE, 'skills'), { recursive: true, force: true });
    mkdirSync(STORE, { recursive: true });
    cpSync(join(ROOT, 'skills'), join(STORE, 'skills'), { recursive: true });
    writeFileSync(join(STORE, 'VERSION'), VERSION);
  }
  // 2) enlaces para cada agente
  const report = [];
  for (const l of LINKS) {
    if (l.only && !existsSync(l.only)) continue;
    link(SKILL, l.path);
    report.push([l.label, l.path.replace(HOME, '~')]);
  }
  for (const [label, cmd, dir] of AGENTS) {
    const found = onPath(cmd) || existsSync(join(HOME, dir));
    report.push([label, found ? 'lee ~/.agents/skills' : 'no detectado (lo verá si lo instalas)']);
  }
  // el proyecto antes se llamaba bizagi-skill: su copia ya no la usa ningún enlace
  const old = join(HOME, '.bizagi-skill');
  if (existsSync(old)) { console.log('Retirando la copia con el nombre anterior (bizagi-skill) ...'); backup(old); }
  // 3) comprobación
  const py = python();
  const v = py ? run(py, [join(SKILL, 'scripts', 'bizagi_cli.py'), '--version']) : null;
  console.log(`\nbizagi instalado (${v || 'sin Python 3.9+: instálalo para poder usar el skill'})`);
  for (const [a, b] of report) console.log(`  ${a.padEnd(48)} ${b}`);
  console.log('\nPara actualizar, vuelve a ejecutar el mismo comando.');
  console.log('Reinicia tus agentes (o usa /skills reload en Gemini) para que carguen el skill.');
  return Boolean(v);
}

function uninstall() {
  for (const l of LINKS) {
    if (isLink(l.path)) { removeLink(l.path); console.log(`Enlace eliminado: ${l.path}`); }
  }
  if (existsSync(STORE)) backup(STORE);
  console.log('Listo: bizagi desinstalado.');
  return true;
}

function status() {
  console.log(`bizagi-steroids ${VERSION}`);
  console.log(`  copia estable  ${existsSync(SKILL) ? SKILL : 'no instalada'}`);
  for (const l of LINKS) {
    const state = isLink(l.path) ? 'enlace' : exists(l.path) ? 'carpeta (no es de este instalador)' : 'no instalado';
    console.log(`  ${l.label.padEnd(48)} ${state}`);
  }
  return true;
}

const cmd = process.argv[2] || 'setup';
const actions = { setup, update: setup, install: setup, uninstall, status };
if (!actions[cmd]) {
  console.log(HELP);
  process.exit(cmd === '-h' || cmd === '--help' || cmd === 'help' ? 0 : 1);
}
process.exit(actions[cmd]() ? 0 : 1);
