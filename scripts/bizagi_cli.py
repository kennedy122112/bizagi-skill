#!/usr/bin/env python3
"""bizagi-cli: genera, lee, valida, previsualiza y documenta procesos BPMN 2.0
para Bizagi Modeler, 100 % local (sin MCP ni API).

Comandos:
  generate <spec.json> -o salida.bpmn [--svg vista.svg]   spec -> BPMN 2.0 con diagrama (importable en Bizagi)
  read     <modelo.bpmn> [-o spec.json]                    BPMN (export de Bizagi) -> spec JSON editable
  validate <spec.json|modelo.bpmn>                         reglas de modelado
  preview  <spec.json|modelo.bpmn> -o vista.svg            diagrama SVG para revisar sin abrir Bizagi
  doc      <spec.json|modelo.bpmn> [-o doc.md]             documentación Markdown del proceso
  docx     <spec.json|modelo.bpmn> -o doc.docx             documento Word con diagrama y tablas
"""
import argparse
import html
import json
import math
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from collections import defaultdict, deque
from pathlib import Path

VERSION = "0.3.0"

NS = {
    "bpmn": "http://www.omg.org/spec/BPMN/20100524/MODEL",
    "bpmndi": "http://www.omg.org/spec/BPMN/20100524/DI",
    "dc": "http://www.omg.org/spec/DD/20100524/DC",
    "di": "http://www.omg.org/spec/DD/20100524/DI",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
}
for _p, _u in NS.items():
    ET.register_namespace(_p, _u)


def q(prefix, tag):
    return f"{{{NS[prefix]}}}{tag}"


def local(tag):
    return tag.split("}", 1)[-1]


# ---------------------------------------------------------------- tipos BPMN

EVENT_TYPES = {
    "start": ("startEvent", None),
    "startMessage": ("startEvent", "message"),
    "startTimer": ("startEvent", "timer"),
    "startSignal": ("startEvent", "signal"),
    "startConditional": ("startEvent", "conditional"),
    "end": ("endEvent", None),
    "endMessage": ("endEvent", "message"),
    "endError": ("endEvent", "error"),
    "endTerminate": ("endEvent", "terminate"),
    "endSignal": ("endEvent", "signal"),
    "intermediate": ("intermediateThrowEvent", None),
    "timer": ("intermediateCatchEvent", "timer"),
    "messageCatch": ("intermediateCatchEvent", "message"),
    "messageThrow": ("intermediateThrowEvent", "message"),
    "signalCatch": ("intermediateCatchEvent", "signal"),
    "signalThrow": ("intermediateThrowEvent", "signal"),
    "conditional": ("intermediateCatchEvent", "conditional"),
    "errorCatch": ("intermediateCatchEvent", "error"),
}
ACTIVITY_TYPES = {t: t for t in (
    "task", "userTask", "serviceTask", "manualTask", "scriptTask", "sendTask",
    "receiveTask", "businessRuleTask", "subProcess", "callActivity")}
GATEWAY_TYPES = {
    "exclusive": "exclusiveGateway",
    "parallel": "parallelGateway",
    "inclusive": "inclusiveGateway",
    "eventBased": "eventBasedGateway",
    "complex": "complexGateway",
}
ARTIFACT_TYPES = {"dataObject": "dataObjectReference", "dataStore": "dataStoreReference",
                  "annotation": "textAnnotation"}
DATA_TYPES = ("dataObject", "dataStore")
# tipos que pueden ir adjuntos al borde de una actividad
BOUNDARY_TYPES = ("timer", "messageCatch", "signalCatch", "conditional", "errorCatch")
ALIASES = {
    "inicio": "start", "fin": "end", "tarea": "task", "usuario": "userTask",
    "servicio": "serviceTask", "manual": "manualTask", "script": "scriptTask",
    "regla": "businessRuleTask", "subproceso": "subProcess", "xor": "exclusive",
    "and": "parallel", "or": "inclusive", "gateway": "exclusive",
    "compuerta": "exclusive", "temporizador": "timer", "error": "errorCatch",
    "documento": "dataObject", "dato": "dataObject", "basededatos": "dataStore",
    "almacen": "dataStore", "nota": "annotation", "anotacion": "annotation",
}
_ALL_TYPES = {**EVENT_TYPES, **ACTIVITY_TYPES, **GATEWAY_TYPES, **ARTIFACT_TYPES}
_LOWER = {k.lower(): k for k in _ALL_TYPES}
_LOWER.update({k.lower(): v for k, v in ALIASES.items()})
EVENT_DEF_TAG = {
    "message": "messageEventDefinition", "timer": "timerEventDefinition",
    "signal": "signalEventDefinition", "conditional": "conditionalEventDefinition",
    "error": "errorEventDefinition", "terminate": "terminateEventDefinition",
}


def normalize_type(t):
    t = (t or "task").strip()
    if t in _ALL_TYPES:
        return t
    hit = _LOWER.get(t.lower()) or _LOWER.get(t.lower().replace("gateway", "").replace("event", ""))
    if not hit:
        raise SpecError(f"tipo desconocido: '{t}'. Válidos: {', '.join(_ALL_TYPES)}")
    return hit


def kind(t):
    if t in EVENT_TYPES:
        return "event"
    if t in GATEWAY_TYPES:
        return "gateway"
    if t in ARTIFACT_TYPES:
        return "artifact"
    return "activity"


SIZE = {"event": (36, 36), "gateway": (40, 40), "activity": (100, 64),
        "dataObject": (36, 50), "dataStore": (50, 50), "annotation": (110, 46)}


def size_of(t):
    return SIZE.get(t) or SIZE[kind(t)]


class SpecError(Exception):
    pass


# ---------------------------------------------------------------- spec

def ncname(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    s = re.sub(r"[^\w.-]", "_", s)
    if not re.match(r"[A-Za-z_]", s or "0"):
        s = "id_" + s
    return s


class IdMaker:
    def __init__(self):
        self.used = set()

    def make(self, raw):
        base = ncname(raw)
        out, i = base, 2
        while out in self.used:
            out, i = f"{base}_{i}", i + 1
        self.used.add(out)
        return out


FLOW_RE = re.compile(r"^\s*(.+?)\s*->\s*(.+?)\s*(?::\s*(.*?))?\s*$")


def parse_flow(f, i, prefix):
    if isinstance(f, str):
        m = FLOW_RE.match(f)
        if not m:
            raise SpecError(f"flujo inválido: '{f}' (use 'origen -> destino : etiqueta')")
        f = {"from": m.group(1), "to": m.group(2), "name": m.group(3) or ""}
    src, dst = f.get("from", f.get("source")), f.get("to", f.get("target"))
    if not src or not dst:
        raise SpecError(f"flujo sin origen/destino: {f}")
    return {
        "id": f.get("id") or f"{prefix}_{i + 1}",
        "from": str(src), "to": str(dst),
        "name": f.get("name") or f.get("label") or "",
        "condition": f.get("condition") or "",
        "default": bool(f.get("default")),
        "doc": f.get("doc") or f.get("documentation") or "",
    }


def normalize_spec(raw):
    """Convierte el JSON escrito a mano (o por Claude) en una estructura uniforme."""
    errors = []
    spec = {"name": raw.get("name") or "Proceso",
            "doc": raw.get("doc") or raw.get("documentation") or "",
            "meta": {k: str(v) for k, v in (raw.get("meta") or {}).items()},
            "pools": [], "nodes": [], "flows": [], "messageFlows": [], "associations": [],
            "_errors": errors, "_warnings": []}
    ids = IdMaker()

    pools_raw = raw.get("pools") or [{"name": raw.get("pool") or spec["name"],
                                      "lanes": raw.get("lanes", [])}]
    for p in pools_raw:
        if isinstance(p, str):
            p = {"name": p}
        lanes = [l if isinstance(l, str) else l["name"] for l in p.get("lanes", [])]
        spec["pools"].append({
            "id": ids.make(p.get("id") or "Pool_" + p["name"]), "orig": p.get("id") or p["name"],
            "name": p["name"], "lanes": lanes, "doc": p.get("doc", ""),
            "blackbox": bool(p.get("blackbox")),
        })
    live_pools = [p for p in spec["pools"] if not p["blackbox"]]

    def find_pool(ref):
        for p in spec["pools"]:
            if ref in (p["name"], p["id"], p["orig"]):
                return p
        return None

    node_ids = {}
    for n in raw.get("nodes", []):
        orig = str(n.get("id") or n.get("name") or n.get("text"))
        if orig in node_ids:
            errors.append(f"id de nodo duplicado: '{orig}'")
            continue
        t = normalize_type(n.get("type"))
        attached = n.get("attachedTo") or ""
        pool, lane = None, n.get("lane")
        # eventos adjuntos y artefactos sin ubicación heredan la de su actividad/asociación
        inherit = (attached or kind(t) == "artifact") and not lane and not n.get("pool")
        if inherit:
            pass
        elif n.get("pool"):
            pool = find_pool(n["pool"])
            if not pool:
                errors.append(f"nodo '{orig}': pool desconocido '{n['pool']}'")
        elif lane:
            owners = [p for p in spec["pools"] if lane in p["lanes"]]
            if len(owners) == 1:
                pool = owners[0]
            elif not owners:
                errors.append(f"nodo '{orig}': carril desconocido '{lane}'")
            else:
                errors.append(f"nodo '{orig}': carril '{lane}' existe en varios pools; indique 'pool'")
        else:
            pool = live_pools[0] if len(live_pools) == 1 else None
            if not pool:
                errors.append(f"nodo '{orig}': indique 'lane' o 'pool'")
        if pool and lane and lane not in pool["lanes"]:
            errors.append(f"nodo '{orig}': el carril '{lane}' no pertenece al pool '{pool['name']}'")
        if pool and not lane and pool["lanes"]:
            lane = pool["lanes"][0]
            spec["_warnings"].append(f"nodo '{orig}' sin carril: se ubicó en '{lane}'")
        nid = ids.make(orig)
        node_ids[orig] = nid
        spec["nodes"].append({
            "id": nid, "orig": orig, "type": t,
            "name": n.get("name") or (n.get("text", "") if t != "annotation" else ""),
            "text": n.get("text") or (n.get("name", "") if t == "annotation" else ""),
            "pool": pool["id"] if pool else None, "lane": lane, "inherit": bool(inherit),
            "doc": n.get("doc") or n.get("documentation") or "",
            "timer": n.get("timer") or "",
            "attachedTo": attached, "interrupting": n.get("interrupting", True) is not False,
        })

    def ref(x, allow_pool):
        if x in node_ids:
            return node_ids[x], False
        if allow_pool and find_pool(x):
            return find_pool(x)["id"], True
        return None, False

    for key, prefix, allow_pool in (("flows", "Flow", False), ("messageFlows", "MsgFlow", True),
                                    ("associations", "Assoc", False)):
        for i, f in enumerate(raw.get(key, [])):
            f = parse_flow(f, i, prefix)
            s, s_pool = ref(f["from"], allow_pool)
            t, t_pool = ref(f["to"], allow_pool)
            if not s or not t:
                errors.append(f"{'asociación' if key == 'associations' else 'flujo'} "
                              f"'{f['from']} -> {f['to']}': referencia a nodo inexistente "
                              f"'{f['from'] if not s else f['to']}'")
                continue
            f.update(id=ids.make(f["id"]), source=s, target=t, sourceIsPool=s_pool, targetIsPool=t_pool)
            spec[key].append(f)

    # ubicación heredada: primero los eventos adjuntos, luego los artefactos
    nodes = {n["id"]: n for n in spec["nodes"]}
    for n in spec["nodes"]:
        if not n["attachedTo"]:
            continue
        host = nodes.get(node_ids.get(n["attachedTo"], ""))
        if not host:
            errors.append(f"evento '{n['orig']}': actividad adjunta desconocida '{n['attachedTo']}'")
            n["attachedTo"] = ""
            continue
        n["attachedTo"] = host["id"]
        if n["inherit"]:
            n["pool"], n["lane"] = host["pool"], host["lane"]
    for n in spec["nodes"]:
        if kind(n["type"]) != "artifact" or not n["inherit"]:
            continue
        partner = next((nodes[a["target"] if a["source"] == n["id"] else a["source"]]
                        for a in spec["associations"] if n["id"] in (a["source"], a["target"])), None)
        if partner and partner["pool"]:
            n["pool"], n["lane"] = partner["pool"], partner["lane"]
        elif len(live_pools) == 1:
            n["pool"] = live_pools[0]["id"]
            n["lane"] = live_pools[0]["lanes"][0] if live_pools[0]["lanes"] else None
        else:
            errors.append(f"'{n['orig']}' no tiene asociación: indique 'lane' o 'pool'")
    return spec


def load_any(path):
    p = Path(path)
    if p.suffix.lower() == ".json":
        return normalize_spec(json.loads(p.read_text(encoding="utf-8")))
    if p.suffix.lower() in (".bpmn", ".xml"):
        return normalize_spec(bpmn_to_raw(p))
    if p.suffix.lower() == ".bpm":
        raise SpecError("archivo .bpm nativo: en Bizagi use Archivo > Exportar > BPMN 2.0 y lea el .bpmn")
    raise SpecError(f"extensión no soportada: {p.suffix}")


# ---------------------------------------------------------------- validación

def validate(spec):
    errors = list(spec["_errors"])
    warnings = list(spec.get("_warnings", []))
    nodes = {n["id"]: n for n in spec["nodes"]}
    label = lambda i: nodes[i]["orig"] if i in nodes else i
    inc, out = defaultdict(list), defaultdict(list)
    for f in spec["flows"]:
        a, b = nodes.get(f["source"]), nodes.get(f["target"])
        if a and b and (kind(a["type"]) == "artifact" or kind(b["type"]) == "artifact"):
            errors.append(f"flujo de secuencia con un artefacto ({a['orig']} -> {b['orig']}): "
                          "use associations")
            continue
        if a and b and a["pool"] != b["pool"]:
            errors.append(f"flujo de secuencia entre pools distintos ({a['orig']} -> {b['orig']}): "
                          "use messageFlows")
        out[f["source"]].append(f)
        inc[f["target"]].append(f)
    for f in spec["messageFlows"]:
        a, b = nodes.get(f["source"]), nodes.get(f["target"])
        pa = a["pool"] if a else f["source"]
        pb = b["pool"] if b else f["target"]
        if pa == pb:
            errors.append(f"flujo de mensaje dentro del mismo pool ({label(f['source'])} -> "
                          f"{label(f['target'])}): use flows")
    for a in spec["associations"]:
        s, t = nodes[a["source"]], nodes[a["target"]]
        if kind(s["type"]) != "artifact" and kind(t["type"]) != "artifact":
            errors.append(f"asociación entre dos elementos de flujo ({s['orig']} -> {t['orig']}): "
                          "use flows")
    for p in spec["pools"]:
        if p["blackbox"]:
            continue
        pn = [n for n in spec["nodes"] if n["pool"] == p["id"] and kind(n["type"]) != "artifact"]
        if not pn:
            warnings.append(f"pool '{p['name']}' sin nodos (márquelo \"blackbox\": true si es externo)")
            continue
        if not any(n["type"].startswith("start") for n in pn):
            warnings.append(f"pool '{p['name']}' no tiene evento de inicio")
        if not any(n["type"].startswith("end") for n in pn):
            warnings.append(f"pool '{p['name']}' no tiene evento de fin")
    for n in spec["nodes"]:
        nid, t, k = n["id"], n["type"], kind(n["type"])
        if k == "artifact":
            if not any(nid in (a["source"], a["target"]) for a in spec["associations"]):
                warnings.append(f"'{n['orig']}' no está asociado a ningún elemento")
            continue
        if n["attachedTo"]:
            host = nodes[n["attachedTo"]]
            if kind(host["type"]) != "activity":
                errors.append(f"evento '{n['orig']}': solo puede adjuntarse a una actividad")
            if t not in BOUNDARY_TYPES:
                errors.append(f"evento adjunto '{n['orig']}' de tipo '{t}': use "
                              f"{', '.join(BOUNDARY_TYPES)}")
            if inc[nid]:
                errors.append(f"el evento adjunto '{n['orig']}' no puede tener flujos de entrada")
            if not out[nid]:
                warnings.append(f"evento adjunto '{n['orig']}' no tiene flujo de salida")
            continue
        if not n["name"] and k == "activity":
            warnings.append(f"actividad '{n['orig']}' sin nombre")
        if t.startswith("start") and inc[nid]:
            errors.append(f"el inicio '{n['orig']}' no puede tener flujos de entrada")
        if t.startswith("end") and out[nid]:
            errors.append(f"el fin '{n['orig']}' no puede tener flujos de salida")
        if not t.startswith("start") and not inc[nid]:
            warnings.append(f"'{n['orig']}' no tiene flujo de entrada")
        if not t.startswith("end") and not out[nid]:
            warnings.append(f"'{n['orig']}' no tiene flujo de salida")
        if t in ("exclusive", "inclusive") and len(out[nid]) > 1:
            unnamed = [f for f in out[nid] if not (f["name"] or f["condition"] or f["default"])]
            if unnamed:
                warnings.append(f"compuerta '{n['orig']}': {len(unnamed)} salida(s) sin etiqueta/condición")
        if k == "gateway" and len(out[nid]) <= 1 and len(inc[nid]) <= 1:
            warnings.append(f"compuerta '{n['orig']}' no divide ni une caminos")
        if sum(f["default"] for f in out[nid]) > 1:
            errors.append(f"'{n['orig']}' tiene más de un flujo por defecto")
    # alcanzabilidad desde los inicios (un evento adjunto se alcanza con su actividad)
    succ = defaultdict(list)
    for f in spec["flows"] + spec["messageFlows"]:
        succ[f["source"]].append(f["target"])
    for n in spec["nodes"]:
        if n["attachedTo"]:
            succ[n["attachedTo"]].append(n["id"])
    seen = set()
    dq = deque(n["id"] for n in spec["nodes"] if n["type"].startswith("start"))
    while dq:
        x = dq.popleft()
        if x in seen:
            continue
        seen.add(x)
        dq.extend(succ[x])
    for n in spec["nodes"]:
        if (n["id"] not in seen and not n["type"].startswith("start")
                and kind(n["type"]) != "artifact"):
            warnings.append(f"'{n['orig']}' no es alcanzable desde ningún inicio")
    return errors, sorted(set(warnings), key=warnings.index)


# ---------------------------------------------------------------- layout

COL_W, ROW_H, LANE_PAD, POOL_HDR, LEFT_PAD = 160, 110, 12, 30, 20
X0, Y0, POOL_GAP, BLACKBOX_H = 20, 20, 70, 70


def layout(spec):
    nodes = {n["id"]: n for n in spec["nodes"]}
    is_art = lambda i: kind(nodes[i]["type"]) == "artifact"
    grid = [n["id"] for n in spec["nodes"] if not n["attachedTo"] and not is_art(n["id"])]
    boundaries = [n["id"] for n in spec["nodes"] if n["attachedTo"]]
    artifacts = [n["id"] for n in spec["nodes"] if is_art(n["id"])]
    anchor = lambda i: nodes[i]["attachedTo"] or i
    lane_key = lambda i: (nodes[i]["pool"], nodes[i]["lane"])

    # aristas para el layout: un evento adjunto cuenta como su actividad
    edges = []
    for f in spec["flows"] + spec["messageFlows"]:
        s, t = f["source"], f["target"]
        if s in nodes and t in nodes and not is_art(s) and not is_art(t):
            edges.append((anchor(s), anchor(t), f["id"], bool(nodes[s]["attachedTo"])))
    succ = defaultdict(list)
    for s, t, fid, _ in edges:
        succ[s].append((t, fid))

    # 1) flujos de retorno (ciclos) con DFS iterativo
    back, state = set(), {}
    for r in [i for i in grid if nodes[i]["type"].startswith("start")] + grid:
        if r in state:
            continue
        stack = [(r, iter(succ[r]))]
        state[r] = 1
        while stack:
            v, it = stack[-1]
            nxt = next(it, None)
            if nxt is None:
                state[v] = 2
                stack.pop()
                continue
            w, fid = nxt
            if state.get(w) == 1:
                back.add(fid)
            elif w not in state:
                state[w] = 1
                stack.append((w, iter(succ[w])))

    # 2) columnas = camino más largo en el grafo sin ciclos
    indeg = defaultdict(int)
    fsucc, fpred = defaultdict(list), defaultdict(list)
    for s, t, fid, from_b in edges:
        if fid in back or s == t:
            continue
        indeg[t] += 1
        fsucc[s].append(t)
        fpred[t].append((s, 1 if from_b else 0))
    col = {i: 0 for i in grid}
    dq = deque(i for i in grid if indeg[i] == 0)
    topo = []
    while dq:
        v = dq.popleft()
        topo.append(v)
        for w in fsucc[v]:
            col[w] = max(col[w], col[v] + 1)
            indeg[w] -= 1
            if indeg[w] == 0:
                dq.append(w)

    # 3) filas: seguir la fila del predecesor; ramas y salidas de excepción debajo
    row, occupied = {}, set()

    def place(v, pref):
        r = pref
        while (lane_key(v), col[v], r) in occupied:
            r += 1
        row[v] = r
        occupied.add((lane_key(v), col[v], r))

    for v in topo:
        cands = [row[p] + bump for p, bump in fpred[v] if p in row and lane_key(p) == lane_key(v)]
        place(v, cands[0] if cands else 0)
    # artefactos: debajo de la actividad con la que se asocian
    max_grid_col = max(col.values(), default=0)
    host_of = {}
    for a in spec["associations"]:
        for x, y in ((a["source"], a["target"]), (a["target"], a["source"])):
            if is_art(x) and not is_art(y) and x not in host_of:
                host_of[x] = anchor(y)
    with_boundary = {nodes[b]["attachedTo"] for b in boundaries}
    is_output = {a["target"] for a in spec["associations"] if not is_art(a["source"])}
    for v in artifacts:
        h = host_of.get(v)
        same_lane = h in row and lane_key(h) == lane_key(v)
        if same_lane:
            # debajo de la actividad; si ya hay algo (o pasan flujos de eventos adjuntos),
            # en diagonal: las salidas a la derecha, las entradas a la izquierda
            c, rr = col[h], row[h] + 1
            side = [c + 1, c - 1] if v in is_output else [c - 1, c + 1]
            cands = ([] if h in with_boundary else [c]) + side
            free = next((cc for cc in cands if cc >= 0 and cc <= max_grid_col
                         and (lane_key(v), cc, rr) not in occupied), None)
            if free is not None:
                col[v], row[v] = free, rr
                occupied.add((lane_key(v), free, rr))
                continue
        col[v] = col.get(h, 0)
        place(v, row[h] + 1 if same_lane else 0)

    placed = grid + artifacts
    max_col = max(col.values(), default=0)
    pool_w = POOL_HDR + LEFT_PAD + (max_col + 1) * COL_W + LEFT_PAD
    geo = {"pools": {}, "lanes": {}, "nodes": {}, "edges": {}, "labels": {}, "back": back,
           "slot": {}}
    y = Y0
    for p in pool_order(spec, nodes):
        if p["blackbox"]:
            geo["pools"][p["id"]] = (X0, y, pool_w, BLACKBOX_H)
            y += BLACKBOX_H + POOL_GAP
            continue
        py = y
        for lane in (p["lanes"] or [None]):
            mine = [i for i in placed if nodes[i]["pool"] == p["id"] and nodes[i]["lane"] == lane]
            rows = 1 + max((row[i] for i in mine), default=0)
            lh = rows * ROW_H + 2 * LANE_PAD
            if lane is not None:
                geo["lanes"][(p["id"], lane)] = (X0 + POOL_HDR, y, pool_w - POOL_HDR, lh)
            for i in mine:
                w, h = size_of(nodes[i]["type"])
                cx = X0 + POOL_HDR + LEFT_PAD + col[i] * COL_W + COL_W / 2
                cy = y + LANE_PAD + ROW_H / 2 + row[i] * ROW_H
                geo["nodes"][i] = (cx - w / 2, cy - h / 2, w, h)
            y += lh
        geo["pools"][p["id"]] = (X0, py, pool_w, y - py)
        y += POOL_GAP
    geo["size"] = (X0 + pool_w + 20, y - POOL_GAP + 20)

    # eventos adjuntos sobre el borde inferior de su actividad, de derecha a izquierda;
    # el de destino más alto va a la derecha para que sus flujos no se crucen
    tgt_y = {}
    for f in spec["flows"]:
        if f["source"] in boundaries and f["target"] in geo["nodes"]:
            tgt_y.setdefault(f["source"], center(geo["nodes"][f["target"]])[1])
    per_host = defaultdict(int)
    for b in sorted(boundaries, key=lambda b: tgt_y.get(b, 0)):
        h = nodes[b]["attachedTo"]
        if h not in geo["nodes"]:
            continue
        x, yy, w, hh = geo["nodes"][h]
        k = per_host[h]
        per_host[h] += 1
        geo["slot"][b] = k
        bw, bh = SIZE["event"]
        cx = x + w - 20 - k * 34
        geo["nodes"][b] = (cx - bw / 2, yy + hh - bh / 2, bw, bh)

    obstacles = [geo["nodes"][i] for i in placed if i in geo["nodes"]]
    for f in spec["flows"]:
        s, t = f["source"], f["target"]
        if s in geo["nodes"] and t in geo["nodes"]:
            geo["edges"][f["id"]] = route_seq(
                geo["nodes"][s], geo["nodes"][t], kind(nodes[s]["type"]), kind(nodes[t]["type"]),
                f["id"] in back or anchor(s) == anchor(t), bool(nodes[s]["attachedTo"]), obstacles)
    pool_of = {n["id"]: n["pool"] for n in spec["nodes"]}
    for f in spec["messageFlows"]:
        geo["edges"][f["id"]] = route_msg(f, geo, pool_of)
    for a in spec["associations"]:
        S, T = geo["nodes"].get(a["source"]), geo["nodes"].get(a["target"])
        if S and T:
            geo["edges"][a["id"]] = [side_point(S, center(T)), side_point(T, center(S))]
    place_labels(spec, geo)
    return geo


def pool_order(spec, nodes):
    """Un pool externo va arriba si conversa sobre todo con los carriles superiores."""
    rel = {}
    for p in spec["pools"]:
        for i, lane in enumerate(p["lanes"]):
            rel[(p["id"], lane)] = i / len(p["lanes"])
    above, middle, below = [], [], []
    for p in spec["pools"]:
        if not p["blackbox"]:
            middle.append(p)
            continue
        pos = [rel.get((nodes[x]["pool"], nodes[x]["lane"]), 0)
               for f in spec["messageFlows"] if p["id"] in (f["source"], f["target"])
               for x in (f["source"], f["target"]) if x in nodes]
        (above if pos and sum(pos) / len(pos) < 0.4 else below).append(p)
    return above + middle + below


def center(b):
    return (b[0] + b[2] / 2, b[1] + b[3] / 2)


def side_point(B, P):
    x, y, w, h = B
    cx, cy = x + w / 2, y + h / 2
    dx, dy = P[0] - cx, P[1] - cy
    if abs(dy) * w >= abs(dx) * h:
        return (cx, y + h if dy > 0 else y)
    return (x + w if dx > 0 else x, cy)


def route_seq(S, T, sk, tk, is_back, from_boundary, obstacles):
    sx, sy, sw, sh = S
    tx, ty, tw, th = T
    scx, scy, tcx, tcy = sx + sw / 2, sy + sh / 2, tx + tw / 2, ty + th / 2
    if from_boundary:
        bot = sy + sh
        if tx > scx:
            if tcy >= bot:
                return [(scx, bot), (scx, tcy), (tx, tcy)]
            y2 = bot + 20
            return [(scx, bot), (scx, y2), (tx - 20, y2), (tx - 20, tcy), (tx, tcy)]
        yb = max(bot, ty + th) + 20
        return [(scx, bot), (scx, yb), (tcx, yb), (tcx, ty + th)]
    if not is_back and tx > sx + sw / 2:
        if abs(scy - tcy) < 1:
            blockers = [b for b in obstacles if b != S and b != T and b[0] < tx and
                        b[0] + b[2] > sx + sw and b[1] < scy < b[1] + b[3]]
            if not blockers:
                return [(sx + sw, scy), (tx, tcy)]
            # rodear por debajo los nodos que hay en medio
            dy = max(b[1] + b[3] for b in blockers) + 18
            pts = ([(scx, sy + sh), (scx, dy)] if sk == "gateway"
                   else [(sx + sw, scy), (sx + sw + 15, scy), (sx + sw + 15, dy)])
            pts += ([(tcx, dy), (tcx, ty + th)] if tk == "gateway"
                    else [(tx - 15, dy), (tx - 15, tcy), (tx, tcy)])
            return pts
        if sk == "gateway":
            ey = sy if tcy < scy else sy + sh
            return [(scx, ey), (scx, tcy), (tx, tcy)]
        if tk == "gateway":
            ey = ty if scy < tcy else ty + th
            return [(sx + sw, scy), (tcx, scy), (tcx, ey)]
        mx = tx - 25
        return [(sx + sw, scy), (mx, scy), (mx, tcy), (tx, tcy)]
    # retorno: rodear por encima
    top = min(sy, ty) - 20
    return [(scx, sy), (scx, top), (tcx, top), (tcx, ty)]


def route_msg(f, geo, pool_of):
    def box(ref, is_pool):
        return geo["pools"][ref] if is_pool else geo["nodes"][ref]

    S, T = box(f["source"], f["sourceIsPool"]), box(f["target"], f["targetIsPool"])
    sx, sy, sw, sh = S
    tx, ty, tw, th = T
    # contra un pool caja negra, la línea cae en vertical desde el nodo
    scx = sx + sw / 2 if not f["sourceIsPool"] else tx + tw / 2
    tcx = tx + tw / 2 if not f["targetIsPool"] else scx
    tpool = geo["pools"][f["target"] if f["targetIsPool"] else pool_of[f["target"]]]
    if ty > sy:
        y1, y2 = sy + sh, ty
        my = tpool[1] - POOL_GAP / 2
    else:
        y1, y2 = sy, ty + th
        my = tpool[1] + tpool[3] + POOL_GAP / 2
    if abs(scx - tcx) < 1:
        return [(scx, y1), (tcx, y2)]
    return [(scx, y1), (scx, my), (tcx, my), (tcx, y2)]


def text_lines(text, width=16):
    return max(1, len(wrap(text, width)))


def place_labels(spec, geo):
    """Cajas de etiqueta para eventos, compuertas y flujos (Bizagi las respeta vía BPMNLabel)."""
    ends = set()
    for pts in geo["edges"].values():
        for x, y in (pts[0], pts[-1]):
            ends.add((round(x), round(y)))
    for n in spec["nodes"]:
        k = kind(n["type"])
        if not n["name"] or n["id"] not in geo["nodes"] or k not in ("event", "gateway"):
            continue
        x, y, w, h = geo["nodes"][n["id"]]
        cx = x + w / 2
        lh = 13 * text_lines(n["name"]) + 2
        if n["attachedTo"]:
            slot = geo["slot"].get(n["id"], 0)
            if slot == 0:    # a la derecha
                geo["labels"][n["id"]] = (x + w + 2, y + h - 6, 96, lh)
            elif slot == 1:  # a la izquierda
                geo["labels"][n["id"]] = (x - 98, y + h - 6, 96, lh)
            else:
                geo["labels"][n["id"]] = (cx - 50, y + h + 4, 100, lh)
        elif k == "gateway":
            geo["labels"][n["id"]] = (x - 98, y - lh - 2, 100, lh)
        elif (round(cx), round(y + h)) in ends and (round(cx), round(y)) not in ends:
            geo["labels"][n["id"]] = (cx - 50, y - lh - 4, 100, lh)
        else:
            geo["labels"][n["id"]] = (cx - 50, y + h + 4, 100, lh)
    for f in spec["flows"] + spec["messageFlows"]:
        pts = geo["edges"].get(f["id"])
        if not f["name"] or not pts:
            continue
        (x1, y1), (x2, y2) = (pts[1], pts[2]) if len(pts) > 2 else (pts[0], pts[1])
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        w, h = 7 * len(f["name"]) + 10, 16
        if abs(y1 - y2) < 1:
            geo["labels"][f["id"]] = (mx - w / 2, my - h - 2, w, h)
        else:
            geo["labels"][f["id"]] = (mx + 4, my - h / 2, w, h)


# ---------------------------------------------------------------- BPMN XML

def sub(parent, prefix, tag, text=None, **attrs):
    e = ET.SubElement(parent, q(prefix, tag), {k: str(v) for k, v in attrs.items() if v is not None})
    if text:
        e.text = text
    return e


def spec_to_bpmn(spec, geo):
    defs = ET.Element(q("bpmn", "definitions"), {
        "id": "Definitions_1", "name": spec["name"],
        "targetNamespace": "http://bizagi-cli/bpmn", "exporter": "bizagi-cli",
        "exporterVersion": VERSION})
    nodes = {n["id"]: n for n in spec["nodes"]}
    collab = sub(defs, "bpmn", "collaboration", id="Collaboration_1")
    proc_of = {}
    for p in spec["pools"]:
        # Bizagi descarta participantes sin processRef: el pool externo lleva un proceso vacío
        proc_of[p["id"]] = "Process_" + p["id"]
        part = sub(collab, "bpmn", "participant", id=p["id"], name=p["name"], processRef=proc_of[p["id"]])
        if p["doc"]:
            sub(part, "bpmn", "documentation", p["doc"])
    for f in spec["messageFlows"]:
        mf = sub(collab, "bpmn", "messageFlow", id=f["id"], name=f["name"] or None,
                 sourceRef=f["source"], targetRef=f["target"])
        if f["doc"]:
            sub(mf, "bpmn", "documentation", f["doc"])
    inc, out = defaultdict(list), defaultdict(list)
    for f in spec["flows"]:
        out[f["source"]].append(f)
        inc[f["target"]].append(f)

    for i, p in enumerate(spec["pools"]):
        proc = sub(defs, "bpmn", "process", id=proc_of[p["id"]], name=p["name"], isExecutable="false")
        if p["blackbox"]:
            continue
        if i == 0 and spec["doc"]:
            sub(proc, "bpmn", "documentation", spec["doc"])
        pnodes = [n for n in spec["nodes"] if n["pool"] == p["id"]]
        if p["lanes"]:
            ls = sub(proc, "bpmn", "laneSet", id="LaneSet_" + p["id"])
            for lane in p["lanes"]:
                le = sub(ls, "bpmn", "lane", id=lane_id(p, lane), name=lane)
                for n in pnodes:
                    if n["lane"] == lane and kind(n["type"]) != "artifact":
                        sub(le, "bpmn", "flowNodeRef", n["id"])
        for n in pnodes:
            t = n["type"]
            if t == "annotation":
                continue
            if t in DATA_TYPES:
                # Bizagi dibuja el dataObject en sí (no la referencia) y rechaza dataStore
                # con dataStoreRef: se escribe el elemento directo, como en sus exportaciones
                tag = "dataObject" if t == "dataObject" else "dataStoreReference"
                d = sub(proc, "bpmn", tag, id=n["id"], name=n["name"])
                if n["doc"]:
                    sub(d, "bpmn", "documentation", n["doc"])
                continue
            evdef = None
            if n["attachedTo"]:
                tag, evdef = "boundaryEvent", EVENT_TYPES[t][1]
            elif t in EVENT_TYPES:
                tag, evdef = EVENT_TYPES[t]
            else:
                tag = ACTIVITY_TYPES.get(t) or GATEWAY_TYPES[t]
            default = next((f["id"] for f in out[n["id"]] if f["default"]), None)
            e = sub(proc, "bpmn", tag, id=n["id"], name=n["name"], default=default)
            if n["attachedTo"]:
                e.set("attachedToRef", n["attachedTo"])
                e.set("cancelActivity", "true" if n["interrupting"] else "false")
            if t == "eventBased":
                e.set("eventGatewayType", "Exclusive")
            if n["doc"]:
                sub(e, "bpmn", "documentation", n["doc"])
            for f in inc[n["id"]]:
                sub(e, "bpmn", "incoming", f["id"])
            for f in out[n["id"]]:
                sub(e, "bpmn", "outgoing", f["id"])
            # sin xsi:type en las expresiones: Bizagi agrega el suyo y exportaría el atributo duplicado
            if evdef:
                d = sub(e, "bpmn", EVENT_DEF_TAG[evdef], id=n["id"] + "_def")
                if evdef == "timer" and n["timer"]:
                    sub(d, "bpmn", "timeDuration", n["timer"])
                if evdef == "conditional":
                    sub(d, "bpmn", "condition", n["timer"] or None)
        for f in spec["flows"]:
            if f["source"] in nodes and nodes[f["source"]]["pool"] == p["id"]:
                sf = sub(proc, "bpmn", "sequenceFlow", id=f["id"], name=f["name"] or None,
                         sourceRef=f["source"], targetRef=f["target"])
                if f["doc"]:
                    sub(sf, "bpmn", "documentation", f["doc"])
                if f["condition"]:
                    sub(sf, "bpmn", "conditionExpression", f["condition"])
        for n in pnodes:
            if n["type"] == "annotation":
                ta = sub(proc, "bpmn", "textAnnotation", id=n["id"])
                sub(ta, "bpmn", "text", n["text"])
        # Bizagi enlaza datos con asociaciones dirigidas (no con data associations)
        for a in spec["associations"]:
            if nodes[a["source"]]["pool"] == p["id"]:
                directed = (nodes[a["source"]]["type"] in DATA_TYPES
                            or nodes[a["target"]]["type"] in DATA_TYPES)
                sub(proc, "bpmn", "association", id=a["id"], sourceRef=a["source"],
                    targetRef=a["target"], associationDirection="One" if directed else "None")

    # diagrama (BPMN DI)
    diag = sub(defs, "bpmndi", "BPMNDiagram", id="Diagram_1", name=spec["name"])
    plane = sub(diag, "bpmndi", "BPMNPlane", id="Plane_1", bpmnElement="Collaboration_1")

    def bounds(parent, b):
        sub(parent, "dc", "Bounds", x=r(b[0]), y=r(b[1]), width=r(b[2]), height=r(b[3]))

    def shape(el_id, b, **extra):
        s = sub(plane, "bpmndi", "BPMNShape", id=el_id + "_di", bpmnElement=el_id, **extra)
        bounds(s, b)
        if el_id in geo["labels"]:
            bounds(sub(s, "bpmndi", "BPMNLabel"), geo["labels"][el_id])

    for p in spec["pools"]:
        shape(p["id"], geo["pools"][p["id"]], isHorizontal="true")
        for lane in p["lanes"]:
            shape(lane_id(p, lane), geo["lanes"][(p["id"], lane)], isHorizontal="true")
    for n in spec["nodes"]:
        if n["id"] not in geo["nodes"]:
            continue
        extra = {}
        if n["type"] == "exclusive":
            extra["isMarkerVisible"] = "true"
        if n["type"] in ("subProcess", "callActivity"):
            extra["isExpanded"] = "false"
        shape(n["id"], geo["nodes"][n["id"]], **extra)
    for f in spec["flows"] + spec["messageFlows"] + spec["associations"]:
        if f["id"] in geo["edges"]:
            e = sub(plane, "bpmndi", "BPMNEdge", id=f["id"] + "_di", bpmnElement=f["id"])
            for x, y in geo["edges"][f["id"]]:
                sub(e, "di", "waypoint", x=r(x), y=r(y))
            if f["id"] in geo["labels"]:
                bounds(sub(e, "bpmndi", "BPMNLabel"), geo["labels"][f["id"]])
    ET.indent(defs, space="  ")
    return ET.tostring(defs, encoding="unicode", xml_declaration=False)


def lane_id(pool, lane):
    return ncname(f"Lane_{pool['id']}_{lane}")


def r(v):
    return str(int(round(v)))


# ---------------------------------------------------------------- lector BPMN

REVERSE_EVENT = {v: k for k, v in EVENT_TYPES.items()}
REVERSE_GATEWAY = {v: k for k, v in GATEWAY_TYPES.items()}


def doc_of(el):
    d = el.find(q("bpmn", "documentation"))
    return (d.text or "").strip() if d is not None else ""


def child_text(el, tag):
    c = el.find(q("bpmn", tag))
    return (c.text or "").strip() if c is not None else ""


def bpmn_to_raw(path):
    """Lee un BPMN 2.0 (p. ej. exportado desde Bizagi) y devuelve una spec JSON."""
    text = Path(path).read_bytes().decode("utf-8-sig", errors="replace")
    # algunas exportaciones de Bizagi repiten xsi:type en una misma etiqueta (XML inválido)
    text = re.sub(r'(xsi:type="[^"]*")(\s+xsi:type="[^"]*")+', r"\1", text)
    root = ET.fromstring(text)
    raw = {"name": root.get("name") or "", "pools": [], "nodes": [], "flows": [],
           "messageFlows": [], "associations": [], "_notes": []}
    diag = root.find(f".//{q('bpmndi', 'BPMNDiagram')}")
    raw["name"] = raw["name"] or (diag.get("name") if diag is not None else "") or Path(path).stem
    procs = {p.get("id"): p for p in root.findall(q("bpmn", "process"))}
    participants = root.findall(f".//{q('bpmn', 'participant')}")
    pools = []
    used_procs = set()
    for part in participants:
        pref = part.get("processRef")
        pools.append((part.get("id"), part.get("name") or "", procs.get(pref), doc_of(part)))
        used_procs.add(pref)
    for pid, p in procs.items():
        if pid not in used_procs:
            pools.append((pid, p.get("name") or raw["name"], p, ""))
    ids_by_elem = {}
    known = set()
    alias = {}  # id de dataObject -> id de su referencia
    for pool_id, pool_name, proc, pdoc in pools:
        pool = {"id": pool_id, "name": pool_name or pool_id}
        if pdoc:
            pool["doc"] = pdoc
        if proc is None or not any(local(c.tag) not in ("documentation", "extensionElements", "laneSet")
                                   for c in proc):
            pool["blackbox"] = True
            raw["pools"].append(pool)
            continue
        lane_of, lanes = {}, []

        def walk_lanes(parent):
            for ls in parent.findall(q("bpmn", "laneSet")) + parent.findall(q("bpmn", "childLaneSet")):
                for lane in ls.findall(q("bpmn", "lane")):
                    child = lane.find(q("bpmn", "childLaneSet"))
                    if child is not None and child.findall(q("bpmn", "lane")):
                        walk_lanes(lane)
                        continue
                    name = lane.get("name") or lane.get("id")
                    lanes.append(name)
                    for ref in lane.findall(q("bpmn", "flowNodeRef")):
                        lane_of[(ref.text or "").strip()] = name

        walk_lanes(proc)
        pool["lanes"] = lanes
        raw["pools"].append(pool)
        if proc.find(q("bpmn", "documentation")) is not None and not raw.get("doc"):
            raw["doc"] = doc_of(proc)
        # un dataObject con referencia se lee a través de la referencia (evita duplicados)
        referenced = {}
        for ref in proc.findall(q("bpmn", "dataObjectReference")):
            if ref.get("dataObjectRef"):
                referenced[ref.get("dataObjectRef")] = ref.get("id")
        alias.update(referenced)
        for el in proc:
            tag = local(el.tag)
            t, extra = None, {}
            if tag in ("startEvent", "endEvent", "intermediateCatchEvent", "intermediateThrowEvent",
                       "boundaryEvent"):
                defs = [local(c.tag).replace("EventDefinition", "") for c in el
                        if local(c.tag).endswith("EventDefinition")]
                lookup_tag = "intermediateCatchEvent" if tag == "boundaryEvent" else tag
                t = REVERSE_EVENT.get((lookup_tag, defs[0] if defs else None)) \
                    or REVERSE_EVENT.get((lookup_tag, None)) or "intermediate"
                if tag == "boundaryEvent":
                    extra["attachedTo"] = el.get("attachedToRef")
                    if el.get("cancelActivity") == "false":
                        extra["interrupting"] = False
                    if t not in BOUNDARY_TYPES:
                        raw["_notes"].append(f"evento adjunto '{el.get('name') or el.get('id')}' "
                                             f"de tipo no soportado se leyó como temporizador")
                        t = "timer"
            elif tag in ACTIVITY_TYPES:
                t = tag
                if tag == "subProcess" and any(local(c.tag) in ACTIVITY_TYPES for c in el):
                    raw["_notes"].append(f"subproceso '{el.get('name')}' tiene contenido interno; "
                                         "se representa contraído")
            elif tag in REVERSE_GATEWAY:
                t = REVERSE_GATEWAY[tag]
            elif tag == "dataObjectReference" or (tag == "dataObject" and el.get("id") not in referenced):
                t = "dataObject"
            elif tag == "dataStoreReference":
                t = "dataStore"
            elif tag == "textAnnotation":
                t = "annotation"
                extra["text"] = child_text(el, "text")
            if not t:
                continue
            node = {"id": el.get("id"), "type": t}
            if el.get("name") or t != "annotation":
                node["name"] = el.get("name") or ""
            node.update(extra)
            if el.get("id") in lane_of:
                node["lane"] = lane_of[el.get("id")]
            elif kind(t) == "artifact" or extra.get("attachedTo"):
                pass  # se ubica junto a su actividad / asociación
            elif lanes:
                node["lane"] = lanes[0]
            else:
                node["pool"] = pool_id
            d = doc_of(el)
            if d:
                node["doc"] = d
            td = el.find(f".//{q('bpmn', 'timeDuration')}")
            if td is None:
                td = el.find(f".//{q('bpmn', 'timeDate')}")
            if td is not None and (td.text or "").strip():
                node["timer"] = td.text.strip()
            ids_by_elem[el.get("id")] = el
            known.add(el.get("id"))
            raw["nodes"].append(node)
            for da in el.findall(q("bpmn", "dataInputAssociation")):
                for src in da.findall(q("bpmn", "sourceRef")):
                    raw["associations"].append(f"{(src.text or '').strip()} -> {el.get('id')}")
            for da in el.findall(q("bpmn", "dataOutputAssociation")):
                tgt = child_text(da, "targetRef")
                if tgt:
                    raw["associations"].append(f"{el.get('id')} -> {tgt}")
        for sf in proc.findall(q("bpmn", "sequenceFlow")):
            raw["flows"].append(flow_to_raw(sf, ids_by_elem))
    # anotaciones a nivel de colaboración
    for col in root.findall(q("bpmn", "collaboration")):
        for ta in col.findall(q("bpmn", "textAnnotation")):
            raw["nodes"].append({"id": ta.get("id"), "type": "annotation",
                                 "text": child_text(ta, "text")})
            known.add(ta.get("id"))
    for assoc in root.findall(f".//{q('bpmn', 'association')}"):
        s, t = alias.get(assoc.get("sourceRef"), assoc.get("sourceRef")), \
            alias.get(assoc.get("targetRef"), assoc.get("targetRef"))
        if s in known and t in known:
            raw["associations"].append(f"{s} -> {t}")
    # asociaciones de datos que apuntan a nodos no leídos (p. ej. propiedades) se descartan
    raw["associations"] = list(dict.fromkeys(a for a in raw["associations"]
                                             if all(x.strip() in known for x in a.split("->"))))
    # carriles con el mismo nombre en distintos pools: fijar el pool en cada nodo
    lane_count = defaultdict(int)
    for p in raw["pools"]:
        for lane in p.get("lanes", []):
            lane_count[lane] += 1
    pool_of_node = {}
    for pool_id, _, proc, _ in pools:
        if proc is None:
            continue
        for el in proc:
            pool_of_node[el.get("id")] = pool_id
    for n in raw["nodes"]:
        if n.get("lane") and lane_count[n["lane"]] > 1:
            n["pool"] = pool_of_node[n["id"]]
    for mf in root.findall(f".//{q('bpmn', 'messageFlow')}"):
        raw["messageFlows"].append(flow_to_raw(mf, ids_by_elem))
    for key in ("associations", "_notes"):
        if not raw[key]:
            del raw[key]
    return raw


def flow_to_raw(el, ids_by_elem):
    src, dst = el.get("sourceRef"), el.get("targetRef")
    name = el.get("name") or ""
    cond = el.find(q("bpmn", "conditionExpression"))
    cond = (cond.text or "").strip() if cond is not None else ""
    is_default = src in ids_by_elem and ids_by_elem[src].get("default") == el.get("id")
    d = doc_of(el)
    if not (cond or is_default or d):
        return f"{src} -> {dst}" + (f" : {name}" if name else "")
    f = {"from": src, "to": dst}
    if name:
        f["name"] = name
    if cond:
        f["condition"] = cond
    if is_default:
        f["default"] = True
    if d:
        f["doc"] = d
    return f


# ---------------------------------------------------------------- vista previa SVG

def wrap(text, width):
    lines, cur = [], ""
    for w in (text or "").split():
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return lines


def svg_text(x, y, text, width, size=11, anchor="middle", weight="normal", fill="#1f2937"):
    lines = wrap(text, width)
    y0 = y - (len(lines) - 1) * (size + 2) / 2
    return "".join(
        f'<text x="{x:.0f}" y="{y0 + i * (size + 2):.0f}" font-size="{size}" text-anchor="{anchor}" '
        f'dominant-baseline="middle" font-weight="{weight}" fill="{fill}">{html.escape(l)}</text>'
        for i, l in enumerate(lines))


TASK_ICON = {"userTask": "👤", "serviceTask": "⚙", "manualTask": "✋", "scriptTask": "📜",
             "sendTask": "✉", "receiveTask": "✉", "businessRuleTask": "▦", "callActivity": "↗"}
EVENT_ICON = {"message": "✉", "timer": "⏱", "signal": "△", "conditional": "≡", "error": "ϟ"}
GATEWAY_ICON = {"exclusive": "✕", "parallel": "+", "inclusive": "○", "eventBased": "⬠", "complex": "✱"}


def render_svg(spec, geo):
    W, H = geo["size"]
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H:.0f}" '
           f'viewBox="0 0 {W:.0f} {H:.0f}" font-family="Segoe UI, Arial, sans-serif">',
           '<defs><marker id="arr" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="8" '
           'markerHeight="8" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#374151"/></marker>'
           '<marker id="msg" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="9" markerHeight="9" '
           'orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#fff" stroke="#374151"/></marker>'
           '<marker id="open" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="8" markerHeight="8" '
           'orient="auto"><path d="M0,0 L10,5 L0,10" fill="none" stroke="#6b7280"/></marker>'
           '<marker id="circ" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="7" markerHeight="7">'
           '<circle cx="5" cy="5" r="4" fill="#fff" stroke="#374151"/></marker></defs>',
           f'<rect width="{W:.0f}" height="{H:.0f}" fill="#ffffff"/>']
    for p in spec["pools"]:
        x, y, w, h = geo["pools"][p["id"]]
        out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="#fff" stroke="#4b5563" stroke-width="1.5"/>')
        if p["blackbox"]:
            out.append(svg_text(x + w / 2, y + h / 2, p["name"], 60, 13, weight="600"))
            continue
        out.append(f'<line x1="{x + POOL_HDR}" y1="{y}" x2="{x + POOL_HDR}" y2="{y + h}" stroke="#4b5563"/>')
        out.append(f'<g transform="translate({x + POOL_HDR / 2},{y + h / 2}) rotate(-90)">'
                   + svg_text(0, 0, p["name"], 40, 12, weight="600") + "</g>")
        for lane in p["lanes"]:
            lx, ly, lw, lh = geo["lanes"][(p["id"], lane)]
            out.append(f'<rect x="{lx}" y="{ly}" width="{lw}" height="{lh}" fill="#f9fafb" stroke="#9ca3af"/>')
            out.append(f'<line x1="{lx + 26}" y1="{ly}" x2="{lx + 26}" y2="{ly + lh}" stroke="#9ca3af"/>')
            out.append(f'<g transform="translate({lx + 13},{ly + lh / 2}) rotate(-90)">'
                       + svg_text(0, 0, lane, 22, 11) + "</g>")
    nodes = {n["id"]: n for n in spec["nodes"]}
    msg_ids = {f["id"] for f in spec["messageFlows"]}
    for a in spec["associations"]:
        pts = geo["edges"].get(a["id"])
        if not pts:
            continue
        d = " ".join(f"{x:.0f},{y:.0f}" for x, y in pts)
        arrow = 'marker-end="url(#open)"' if nodes[a["target"]]["type"] in DATA_TYPES or \
            nodes[a["source"]]["type"] in DATA_TYPES else ""
        out.append(f'<polyline points="{d}" fill="none" stroke="#6b7280" stroke-width="1.2" '
                   f'stroke-dasharray="2 3" {arrow}/>')
    for f in spec["flows"] + spec["messageFlows"]:
        pts = geo["edges"].get(f["id"])
        if not pts:
            continue
        d = " ".join(f"{x:.0f},{y:.0f}" for x, y in pts)
        style = ('stroke-dasharray="6 4" marker-start="url(#circ)" marker-end="url(#msg)"'
                 if f["id"] in msg_ids else 'marker-end="url(#arr)"')
        out.append(f'<polyline points="{d}" fill="none" stroke="#374151" stroke-width="1.3" {style}/>')
        if f["default"]:
            (x1, y1), (x2, y2) = pts[0], pts[1]
            seg = math.hypot(x2 - x1, y2 - y1) or 1
            mx, my = x1 + (x2 - x1) * 12 / seg, y1 + (y2 - y1) * 12 / seg
            out.append(f'<line x1="{mx - 5}" y1="{my - 5}" x2="{mx + 5}" y2="{my + 5}" stroke="#374151"/>')
        if f["id"] in geo["labels"]:
            lx, ly, lw, lh = geo["labels"][f["id"]]
            anchor, tx = ("middle", lx + lw / 2) if abs(pts[1][1] - pts[0][1]) < 1 or len(pts) > 2 \
                and abs(pts[1][1] - pts[2][1]) < 1 else ("start", lx)
            out.append(f'<text x="{tx:.0f}" y="{ly + lh / 2:.0f}" font-size="10" text-anchor="{anchor}" '
                       f'dominant-baseline="middle" fill="#1d4ed8" paint-order="stroke" stroke="#fff" '
                       f'stroke-width="3">{html.escape(f["name"])}</text>')
    # actividades primero, para que los eventos adjuntos queden encima
    order = sorted(geo["nodes"], key=lambda i: bool(nodes[i]["attachedTo"]))
    for nid in order:
        x, y, w, h = geo["nodes"][nid]
        n = nodes[nid]
        t, k = n["type"], kind(n["type"])
        cx, cy = x + w / 2, y + h / 2
        if t == "dataObject":
            out.append(f'<path d="M{x},{y} h{w - 10} l10,10 v{h - 10} h{-w} z" fill="#fff" stroke="#4b5563"/>'
                       f'<path d="M{x + w - 10},{y} v10 h10" fill="none" stroke="#4b5563"/>')
            out.append(svg_text(cx, y + h + 12, n["name"], 18, 10))
        elif t == "dataStore":
            out.append(f'<path d="M{x},{y + 8} v{h - 16} a{w / 2},8 0 0 0 {w},0 v{-(h - 16)}" fill="#fff" '
                       f'stroke="#4b5563"/><ellipse cx="{cx}" cy="{y + 8}" rx="{w / 2}" ry="8" fill="#fff" '
                       f'stroke="#4b5563"/>')
            out.append(svg_text(cx, y + h + 12, n["name"], 18, 10))
        elif t == "annotation":
            out.append(f'<path d="M{x + 12},{y} h-12 v{h} h12" fill="none" stroke="#6b7280" stroke-width="1.3"/>')
            out.append(svg_text(x + 6, cy, n["text"], 20, 10, anchor="start", fill="#374151"))
        elif k == "activity":
            sw = 3 if t == "callActivity" else 1.5
            out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="9" fill="#eef5ff" '
                       f'stroke="#2563eb" stroke-width="{sw}"/>')
            out.append(svg_text(cx, cy + 4, n["name"], 16, 10.5))
            if t in TASK_ICON:
                out.append(f'<text x="{x + 6}" y="{y + 13}" font-size="11">{TASK_ICON[t]}</text>')
            if t == "subProcess":
                out.append(f'<rect x="{cx - 7}" y="{y + h - 15}" width="14" height="13" fill="none" stroke="#2563eb"/>'
                           f'<text x="{cx}" y="{y + h - 5}" font-size="12" text-anchor="middle">+</text>')
        elif k == "event":
            _, ev = EVENT_TYPES[t]
            if t.startswith("start"):
                stroke, sw, fill = "#16a34a", 1.8, "#f0fdf4"
            elif t.startswith("end"):
                stroke, sw, fill = "#dc2626", 3.5, "#fef2f2"
            else:
                stroke, sw, fill = "#d97706", 1.5, "#fffbeb"
            dash = ' stroke-dasharray="4 3"' if n["attachedTo"] and not n["interrupting"] else ""
            out.append(f'<circle cx="{cx}" cy="{cy}" r="{w / 2}" fill="{fill}" stroke="{stroke}" '
                       f'stroke-width="{sw}"{dash}/>')
            if not t.startswith(("start", "end")):
                out.append(f'<circle cx="{cx}" cy="{cy}" r="{w / 2 - 3}" fill="none" stroke="{stroke}"{dash}/>')
            if ev == "terminate":
                out.append(f'<circle cx="{cx}" cy="{cy}" r="{w / 2 - 7}" fill="{stroke}"/>')
            elif ev:
                out.append(f'<text x="{cx}" y="{cy + 1}" font-size="13" text-anchor="middle" '
                           f'dominant-baseline="middle">{EVENT_ICON[ev]}</text>')
        else:
            out.append(f'<polygon points="{cx},{y} {x + w},{cy} {cx},{y + h} {x},{cy}" fill="#fefce8" '
                       f'stroke="#ca8a04" stroke-width="1.5"/>')
            out.append(f'<text x="{cx}" y="{cy + 1}" font-size="16" text-anchor="middle" '
                       f'dominant-baseline="middle" fill="#854d0e">{GATEWAY_ICON[t]}</text>')
        if nid in geo["labels"]:
            lx, ly, lw, lh = geo["labels"][nid]
            if k == "gateway":
                out.append(svg_text(lx + lw, ly + lh / 2, n["name"], 16, 10, anchor="end"))
            elif n["attachedTo"]:
                slot = geo["slot"].get(nid, 0)
                bx, anchor = {0: (lx, "start"), 1: (lx + lw, "end")}.get(slot, (lx + lw / 2, "middle"))
                out.append(svg_text(bx, ly + lh / 2, n["name"], 16, 10, anchor=anchor, fill="#92400e"))
            else:
                out.append(svg_text(lx + lw / 2, ly + lh / 2, n["name"], 16, 10))
    out.append("</svg>")
    return "\n".join(out)


# ---------------------------------------------------------------- documentación

TYPE_ES = {"task": "Tarea", "userTask": "Tarea de usuario", "serviceTask": "Tarea de servicio",
           "manualTask": "Tarea manual", "scriptTask": "Tarea de script", "sendTask": "Envío",
           "receiveTask": "Recepción", "businessRuleTask": "Regla de negocio",
           "subProcess": "Subproceso", "callActivity": "Subproceso reutilizable"}
BOUNDARY_ES = {"timer": "tiempo", "messageCatch": "mensaje", "signalCatch": "señal",
               "conditional": "condición", "errorCatch": "error"}


def summarize(spec, geo):
    """Contenido documental del proceso, común a Markdown y Word."""
    nodes = {n["id"]: n for n in spec["nodes"]}
    pools = {p["id"]: p for p in spec["pools"]}
    title = lambda i: (nodes[i]["name"] or nodes[i]["orig"]) if i in nodes else pools[i]["name"]
    who = lambda n: n["lane"] or pools[n["pool"]]["name"]
    out_f = defaultdict(list)
    for f in spec["flows"]:
        out_f[f["source"]].append(f)
    ins, outs, notes = defaultdict(list), defaultdict(list), defaultdict(list)
    used_in, made_by = defaultdict(list), defaultdict(list)
    note_rows = []
    for a in spec["associations"]:
        s, t = nodes[a["source"]], nodes[a["target"]]
        if s["type"] in DATA_TYPES:
            ins[t["id"]].append(s["name"])
            used_in[s["id"]].append(title(t["id"]))
        elif t["type"] in DATA_TYPES:
            outs[s["id"]].append(t["name"])
            made_by[t["id"]].append(title(s["id"]))
        elif "annotation" in (s["type"], t["type"]):
            note, other = (s, t) if s["type"] == "annotation" else (t, s)
            notes[other["id"]].append(note["text"])
            note_rows.append((title(other["id"]), note["text"]))
    boundary_of = defaultdict(list)
    for n in spec["nodes"]:
        if n["attachedTo"]:
            boundary_of[n["attachedTo"]].append(n)
    order = sorted((i for i in geo["nodes"] if kind(nodes[i]["type"]) != "artifact"
                    and not nodes[i]["attachedTo"]),
                   key=lambda i: (geo["nodes"][i][0], geo["nodes"][i][1]))
    S = {"name": spec["name"], "doc": spec["doc"], "meta": spec.get("meta", {}),
         "participants": [], "activities": [], "sequence": [], "decisions": [],
         "exceptions": [], "data": [], "messages": [], "notes": note_rows}
    for p in spec["pools"]:
        roles = ", ".join(p["lanes"]) if p["lanes"] else ("Participante externo" if p["blackbox"] else "—")
        S["participants"].append((p["name"], roles, p["doc"]))
    for i in order:
        n = nodes[i]
        if kind(n["type"]) == "activity":
            S["activities"].append({
                "name": n["name"], "type": TYPE_ES.get(n["type"], n["type"]), "who": who(n),
                "ins": ", ".join(ins[i]), "outs": ", ".join(outs[i]),
                "desc": " ".join(filter(None, [n["doc"]] + notes[i]))})
    # secuencia como segmentos (texto, estilo) para poder pintarla en Markdown o Word
    seq = S["sequence"]
    for i in order:
        n, nxt, name = nodes[i], out_f[i], title(i)
        if kind(n["type"]) == "gateway" and len(nxt) > 1:
            seq.append((0, [(name, "b"), (" (decisión)", "")]))
            for f in nxt:
                cond = f["name"] or f["condition"] or ("por defecto" if f["default"] else "")
                seq.append((1, [(f"{cond or '→'}: ir a ", ""), (title(f["target"]), "i")]))
                S["decisions"].append((name, who(n), cond or "—", title(f["target"])))
        elif n["type"].startswith("end"):
            seq.append((0, [("Fin: ", ""), (name, "b")]))
        elif nxt:
            segs = [(name, "b"), (" → ", "")]
            for k, f in enumerate(nxt):
                segs += ([(", ", "")] if k else []) + [(title(f["target"]), "i")]
            seq.append((0, segs))
        for b in boundary_of[i]:
            tgt = ", ".join(title(f["target"]) for f in out_f[b["id"]]) or "—"
            kind_es = BOUNDARY_ES.get(b["type"], b["type"])
            mode = "interrumpe la actividad" if b["interrupting"] else "sin interrumpir la actividad"
            when = f" ({b['timer']})" if b["timer"] else ""
            seq.append((1, [(f"Excepción por {kind_es}: ", ""), (b["name"] or b["orig"], "b"),
                            (f"{when}, {mode} → ", ""), (tgt, "i")]))
            S["exceptions"].append((name, b["name"] or b["orig"], kind_es.capitalize(),
                                    b["timer"] or "—", "Sí" if b["interrupting"] else "No", tgt))
    for f in spec["messageFlows"]:
        S["messages"].append((title(f["source"]), f["name"] or "—", title(f["target"])))
    for n in spec["nodes"]:
        if n["type"] in DATA_TYPES:
            S["data"].append((n["name"], "Documento" if n["type"] == "dataObject" else "Almacén / sistema",
                              ", ".join(used_in[n["id"]]) or "—", ", ".join(made_by[n["id"]]) or "—"))
    return S


def render_doc(spec, geo):
    S = summarize(spec, geo)
    cell = lambda s: (s or "").replace("|", "/").replace("\n", " ")
    mark = {"b": "**", "i": "*", "": ""}
    md = [f"# {S['name']}", ""]
    if S["doc"]:
        md += [S["doc"], ""]
    md += ["## Participantes", ""]
    md += [f"- **{name}**: {roles}" for name, roles, _ in S["participants"]]
    md += ["", "## Actividades", "",
           "| # | Actividad | Tipo | Responsable | Entradas | Salidas | Descripción |",
           "|---|---|---|---|---|---|---|"]
    for k, a in enumerate(S["activities"], 1):
        md.append(f"| {k} | {cell(a['name'])} | {a['type']} | {cell(a['who'])} | {cell(a['ins'])} | "
                  f"{cell(a['outs'])} | {cell(a['desc'])} |")
    md += ["", "## Secuencia", ""]
    for level, segs in S["sequence"]:
        md.append("  " * level + "- " + "".join(f"{mark[st]}{t}{mark[st]}" for t, st in segs))
    for src, name, dst in S["messages"]:
        md.append(f"- Mensaje{(' «' + name + '»') if name != '—' else ''}: {src} ⇢ {dst}")
    return "\n".join(md) + "\n"


# ---------------------------------------------------------------- Word (.docx)

DOCX_NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
           'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
           'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
           'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
           'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"')
ACCENT = "C2410C"         # naranja Bizagi, legible sobre blanco
HEAD_FILL = "E8601C"
PORTRAIT, LANDSCAPE = (11906, 16838), (16838, 11906)   # A4 en twips
MARGIN = 1134                                           # 2 cm


def x(s):
    return html.escape(str(s), quote=True)


def w_run(text, style="", size=None, color=None):
    props = ""
    if "b" in style:
        props += "<w:b/>"
    if "i" in style:
        props += "<w:i/>"
    if color:
        props += f'<w:color w:val="{color}"/>'
    if size:
        props += f'<w:sz w:val="{size}"/>'
    rpr = f"<w:rPr>{props}</w:rPr>" if props else ""
    return f'<w:r>{rpr}<w:t xml:space="preserve">{x(text)}</w:t></w:r>'


def w_para(runs="", style=None, align=None, indent=None):
    ppr = ""
    if style:
        ppr += f'<w:pStyle w:val="{style}"/>'
    if indent:
        ppr += f'<w:ind w:left="{indent}"/>'
    if align:
        ppr += f'<w:jc w:val="{align}"/>'
    return f"<w:p>{'<w:pPr>' + ppr + '</w:pPr>' if ppr else ''}{runs}</w:p>"


def w_table(headers, rows, widths):
    grid = "".join(f'<w:gridCol w:w="{w}"/>' for w in widths)

    def cell(text, w, head=False):
        shade = f'<w:shd w:val="clear" w:color="auto" w:fill="{HEAD_FILL}"/>' if head else ""
        paras = "".join(w_para(w_run(line, "b" if head else "", color="FFFFFF" if head else None),
                               style="Celda")
                        for line in (str(text) if text not in (None, "") else "—").split("\n"))
        return f'<w:tc><w:tcPr><w:tcW w:w="{w}" w:type="dxa"/>{shade}</w:tcPr>{paras}</w:tc>'

    out = [f'<w:tbl><w:tblPr><w:tblStyle w:val="Tabla"/><w:tblW w:w="{sum(widths)}" w:type="dxa"/>'
           f'<w:tblLayout w:type="fixed"/></w:tblPr><w:tblGrid>{grid}</w:tblGrid>',
           '<w:tr><w:trPr><w:tblHeader/><w:cantSplit/></w:trPr>'
           + "".join(cell(h, w, True) for h, w in zip(headers, widths)) + "</w:tr>"]
    for row in rows:
        out.append("<w:tr><w:trPr><w:cantSplit/></w:trPr>"
                   + "".join(cell(c, w) for c, w in zip(row, widths)) + "</w:tr>")
    out.append("</w:tbl>")
    return "".join(out) + w_para()


def scale_widths(fracs, total):
    s = sum(fracs)
    return [int(total * f / s) for f in fracs]


def w_section(size):
    w, h = size
    orient = ' w:orient="landscape"' if w > h else ""
    return (f'<w:sectPr><w:footerReference w:type="default" r:id="rIdFooter"/>'
            f'<w:pgSz w:w="{w}" w:h="{h}"{orient}/>'
            f'<w:pgMar w:top="{MARGIN}" w:right="{MARGIN}" w:bottom="{MARGIN}" w:left="{MARGIN}" '
            f'w:header="567" w:footer="567" w:gutter="0"/></w:sectPr>')


def w_image(cx, cy, png_rid, svg_rid, alt=""):
    svg_ext = ""
    if svg_rid:
        svg_ext = ('<a:extLst><a:ext uri="{96DAC541-7B7A-43D3-8B79-37D633B846F1}">'
                   '<asvg:svgBlip xmlns:asvg="http://schemas.microsoft.com/office/drawing/2016/SVG/main" '
                   f'r:embed="{svg_rid}"/></a:ext></a:extLst>')
    return (f'<w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0">'
            f'<wp:extent cx="{cx}" cy="{cy}"/><wp:docPr id="1" name="Diagrama del proceso" descr="{x(alt)}"/>'
            f'<wp:cNvGraphicFramePr><a:graphicFrameLocks noChangeAspect="1"/></wp:cNvGraphicFramePr>'
            f'<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
            f'<pic:pic><pic:nvPicPr><pic:cNvPr id="1" name="diagrama.png"/><pic:cNvPicPr/></pic:nvPicPr>'
            f'<pic:blipFill><a:blip r:embed="{png_rid}">{svg_ext}</a:blip>'
            f'<a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
            f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
            f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic>'
            f'</a:graphicData></a:graphic></wp:inline></w:drawing></w:r>')


def find_browser():
    import shutil
    cands = [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
             r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
             r"C:\Program Files\Google\Chrome\Application\chrome.exe",
             "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
             "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"]
    for name in ("msedge", "microsoft-edge", "google-chrome", "chrome", "chromium", "chromium-browser"):
        if shutil.which(name):
            cands.insert(0, shutil.which(name))
    return next((c for c in cands if Path(c).exists()), None)


def svg_to_png(svg_text, size):
    """Rasteriza el SVG con un Chrome/Edge en modo headless, si hay uno instalado."""
    import subprocess
    import tempfile
    browser = find_browser()
    if not browser:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        svg_p, png_p = Path(tmp) / "d.svg", Path(tmp) / "d.png"
        svg_p.write_text(svg_text, encoding="utf-8")
        w, h = (int(math.ceil(v)) for v in size)
        try:
            subprocess.run([browser, "--headless", "--disable-gpu", "--hide-scrollbars",
                            "--force-device-scale-factor=2", f"--window-size={w},{h}",
                            f"--screenshot={png_p}", svg_p.resolve().as_uri()],
                           capture_output=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            return None
        return png_p.read_bytes() if png_p.exists() else None


def blank_png():
    import struct
    import zlib

    def chunk(kind_, data):
        return struct.pack(">I", len(data)) + kind_ + data + struct.pack(">I", zlib.crc32(kind_ + data))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00\xff\xff\xff")) + chunk(b"IEND", b""))


META_ES = {"codigo": "Código", "version": "Versión", "responsable": "Responsable del proceso",
           "area": "Área", "elaborado": "Elaborado por", "revisado": "Revisado por",
           "aprobado": "Aprobado por", "fecha": "Fecha"}


def render_docx(spec, geo, out_path, png=True):
    import datetime
    import zipfile
    S = summarize(spec, geo)
    svg = render_svg(spec, geo)
    png_bytes = (svg_to_png(svg, geo["size"]) if png else None)
    has_png = png_bytes is not None
    png_bytes = png_bytes or blank_png()
    today = datetime.date.today().isoformat()

    pw = PORTRAIT[0] - 2 * MARGIN
    lw = LANDSCAPE[0] - 2 * MARGIN
    body = [w_para(w_run(S["name"]), "Title"),
            w_para(w_run("Documentación del proceso"), "Subtitle")]
    meta = [(META_ES.get(k, k.capitalize()), v) for k, v in S["meta"].items()]
    if not any(k == "fecha" for k in S["meta"]):
        meta.append(("Fecha", today))
    meta.append(("Generado con", f"bizagi-cli {VERSION} (BPMN 2.0 para Bizagi Modeler)"))
    body.append(w_table(["Dato", "Valor"], meta, scale_widths([1, 2.4], pw)))

    sec = 0

    def h1(text):
        nonlocal sec
        sec += 1
        return w_para(w_run(f"{sec}. {text}"), "Heading1")

    body.append(h1("Objetivo y alcance"))
    body.append(w_para(w_run(S["doc"] or "Sin descripción registrada.")))
    body.append(h1("Participantes y roles"))
    body.append(w_table(["Participante", "Roles (carriles)", "Descripción"],
                        S["participants"], scale_widths([1.2, 2, 2], pw)))
    # fin de la sección vertical; lo que sigue va en horizontal
    body.append(f"<w:p><w:pPr>{w_section(PORTRAIT)}</w:pPr></w:p>")

    # diagrama en horizontal, ajustado al área útil de la página
    body.append(h1("Diagrama del proceso"))
    W, H = geo["size"]
    max_cx, max_cy = lw * 635, (LANDSCAPE[1] - 2 * MARGIN - 1400) * 635
    s = min(max_cx / (W * 9525), max_cy / (H * 9525), 1.0)
    cx, cy = int(W * 9525 * s), int(H * 9525 * s)
    body.append(w_para(w_image(cx, cy, "rIdPng", "rIdSvg",
                                       alt=f"Diagrama BPMN del proceso {S['name']}"), align="center"))
    body.append(w_para(w_run(f"Figura 1. {S['name']} (BPMN 2.0). El archivo .bpmn se importa en "
                             "Bizagi Modeler desde Exportar/Importar → Importar → BPMN."), "Caption"))

    body.append(h1("Descripción de actividades"))
    body.append(w_table(["N.º", "Actividad", "Tipo", "Responsable", "Entradas", "Salidas", "Descripción"],
                        [(k, a["name"], a["type"], a["who"], a["ins"], a["outs"], a["desc"])
                         for k, a in enumerate(S["activities"], 1)],
                        scale_widths([0.45, 2, 1.3, 1.4, 1.5, 1.5, 3.6], lw)))
    body.append(h1("Flujo del proceso"))
    for level, segs in S["sequence"]:
        body.append(w_para(w_run("• " if level == 0 else "– ")
                           + "".join(w_run(t, st) for t, st in segs), indent=360 + 400 * level))
    if S["decisions"]:
        body.append(h1("Reglas de decisión"))
        body.append(w_table(["Decisión", "Responsable", "Condición", "Continúa en"], S["decisions"],
                            scale_widths([2, 1.5, 2.5, 2], lw)))
    if S["exceptions"]:
        body.append(h1("Excepciones y plazos"))
        body.append(w_table(["Actividad", "Evento", "Tipo", "Plazo", "Interrumpe", "Acción"],
                            S["exceptions"], scale_widths([1.8, 2, 1, 0.9, 0.9, 2], lw)))
    if S["data"]:
        body.append(h1("Documentos y sistemas"))
        body.append(w_table(["Elemento", "Tipo", "Se usa en", "Lo produce"], S["data"],
                            scale_widths([2, 1.3, 2.5, 2.5], lw)))
    if S["messages"]:
        body.append(h1("Interacciones con externos"))
        body.append(w_table(["Origen", "Mensaje", "Destino"], S["messages"],
                            scale_widths([2, 2, 2], lw)))
    if S["notes"]:
        body.append(h1("Notas"))
        body.append(w_table(["Elemento", "Nota"], S["notes"], scale_widths([1, 3], lw)))
    if not has_png:
        body.append(w_para(w_run("Nota: el diagrama se incrustó como SVG (Word 2016 o superior). "
                                 "Para una imagen de respaldo instale Chrome o Edge y vuelva a generar.",
                                 "i", size=16, color="6B7280")))

    document = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {DOCX_NS}>'
                f'<w:body>{"".join(body)}{w_section(LANDSCAPE)}</w:body></w:document>')
    footer = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:ftr {DOCX_NS}>'
              f'<w:p><w:pPr><w:pStyle w:val="Footer"/><w:jc w:val="right"/></w:pPr>'
              f'{w_run(S["name"] + "  ·  Página ")}<w:fldSimple w:instr=" PAGE "><w:r><w:t>1</w:t></w:r>'
              f'</w:fldSimple></w:p></w:ftr>')
    styles = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:eastAsia="Calibri" w:cs="Calibri"/>
<w:sz w:val="21"/><w:szCs w:val="21"/><w:lang w:val="es-PE"/></w:rPr></w:rPrDefault>
<w:pPrDefault><w:pPr><w:spacing w:after="100" w:line="264" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>
<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:qFormat/>
<w:pPr><w:spacing w:before="1200" w:after="80"/></w:pPr><w:rPr><w:b/><w:color w:val="1F2937"/><w:sz w:val="52"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Subtitle"><w:name w:val="Subtitle"/><w:basedOn w:val="Normal"/><w:qFormat/>
<w:pPr><w:spacing w:after="480"/><w:pBdr><w:bottom w:val="single" w:sz="12" w:space="8" w:color="{HEAD_FILL}"/></w:pBdr></w:pPr>
<w:rPr><w:color w:val="{ACCENT}"/><w:sz w:val="28"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>
<w:pPr><w:keepNext/><w:spacing w:before="360" w:after="120"/><w:outlineLvl w:val="0"/></w:pPr>
<w:rPr><w:b/><w:color w:val="{ACCENT}"/><w:sz w:val="30"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Caption"><w:name w:val="caption"/><w:basedOn w:val="Normal"/><w:qFormat/>
<w:pPr><w:jc w:val="center"/><w:spacing w:before="80" w:after="240"/></w:pPr><w:rPr><w:i/><w:color w:val="6B7280"/><w:sz w:val="17"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Celda"><w:name w:val="Celda"/><w:basedOn w:val="Normal"/>
<w:pPr><w:spacing w:before="20" w:after="20" w:line="240" w:lineRule="auto"/></w:pPr><w:rPr><w:sz w:val="18"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Footer"><w:name w:val="footer"/><w:basedOn w:val="Normal"/>
<w:rPr><w:color w:val="6B7280"/><w:sz w:val="16"/></w:rPr></w:style>
<w:style w:type="table" w:default="1" w:styleId="TableNormal"><w:name w:val="Normal Table"/>
<w:tblPr><w:tblInd w:w="0" w:type="dxa"/><w:tblCellMar><w:top w:w="0" w:type="dxa"/><w:left w:w="108" w:type="dxa"/>
<w:bottom w:w="0" w:type="dxa"/><w:right w:w="108" w:type="dxa"/></w:tblCellMar></w:tblPr></w:style>
<w:style w:type="table" w:styleId="Tabla"><w:name w:val="Tabla proceso"/><w:basedOn w:val="TableNormal"/>
<w:tblPr><w:tblBorders><w:top w:val="single" w:sz="4" w:space="0" w:color="D1D5DB"/><w:left w:val="single" w:sz="4" w:space="0" w:color="D1D5DB"/>
<w:bottom w:val="single" w:sz="4" w:space="0" w:color="D1D5DB"/><w:right w:val="single" w:sz="4" w:space="0" w:color="D1D5DB"/>
<w:insideH w:val="single" w:sz="4" w:space="0" w:color="D1D5DB"/><w:insideV w:val="single" w:sz="4" w:space="0" w:color="D1D5DB"/></w:tblBorders>
<w:tblCellMar><w:top w:w="50" w:type="dxa"/><w:left w:w="90" w:type="dxa"/><w:bottom w:w="50" w:type="dxa"/><w:right w:w="90" w:type="dxa"/></w:tblCellMar></w:tblPr></w:style>
</w:styles>'''
    content_types = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Default Extension="png" ContentType="image/png"/>
<Default Extension="svg" ContentType="image/svg+xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
<Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>
<Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>
<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>'''
    rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>'''
    doc_rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
<Relationship Id="rIdSettings" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings" Target="settings.xml"/>
<Relationship Id="rIdFooter" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>
<Relationship Id="rIdPng" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/diagrama.png"/>
<Relationship Id="rIdSvg" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/diagrama.svg"/>
</Relationships>'''
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    core = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            f'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
            f'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            f'<dc:title>{x(S["name"])}</dc:title><dc:creator>bizagi-cli</dc:creator>'
            f'<dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created>'
            f'<dcterms:modified xsi:type="dcterms:W3CDTF">{now}</dcterms:modified></cp:coreProperties>')
    app = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
           f'<Application>bizagi-cli {VERSION}</Application></Properties>')
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", rels)
        z.writestr("docProps/core.xml", core)
        z.writestr("docProps/app.xml", app)
        z.writestr("word/document.xml", document)
        z.writestr("word/styles.xml", styles)
        # modo de compatibilidad 15 (Word 2013+): sin él Word abre el archivo en "Modo de compatibilidad"
        z.writestr("word/settings.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<w:settings xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                   '<w:defaultTabStop w:val="708"/><w:compat><w:compatSetting w:name="compatibilityMode" '
                   'w:uri="http://schemas.microsoft.com/office/word" w:val="15"/></w:compat></w:settings>')
        z.writestr("word/footer1.xml", footer)
        z.writestr("word/_rels/document.xml.rels", doc_rels)
        z.writestr("word/media/diagrama.png", png_bytes)
        z.writestr("word/media/diagrama.svg", svg)
    return has_png


# ---------------------------------------------------------------- CLI

def report(errors, warnings):
    for e in errors:
        print(f"ERROR: {e}")
    for w in warnings:
        print(f"AVISO: {w}")
    print(f"{len(errors)} error(es), {len(warnings)} aviso(s)")


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser(prog="bizagi_cli", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"bizagi-cli {VERSION}")
    sp = ap.add_subparsers(dest="cmd", required=True)
    g = sp.add_parser("generate")
    g.add_argument("spec")
    g.add_argument("-o", "--out", required=True)
    g.add_argument("--svg")
    g.add_argument("--force", action="store_true", help="generar aunque haya errores")
    rd = sp.add_parser("read")
    rd.add_argument("bpmn")
    rd.add_argument("-o", "--out")
    v = sp.add_parser("validate")
    v.add_argument("file")
    pv = sp.add_parser("preview")
    pv.add_argument("file")
    pv.add_argument("-o", "--out", required=True)
    d = sp.add_parser("doc")
    d.add_argument("file")
    d.add_argument("-o", "--out")
    dx = sp.add_parser("docx")
    dx.add_argument("file")
    dx.add_argument("-o", "--out", required=True)
    dx.add_argument("--no-png", action="store_true", help="no rasterizar el diagrama (solo SVG)")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "read":
            raw = bpmn_to_raw(a.bpmn)
            text = json.dumps(raw, ensure_ascii=False, indent=2)
            if a.out:
                Path(a.out).write_text(text, encoding="utf-8")
                print(f"spec escrita en {a.out}: {len(raw['nodes'])} nodos, {len(raw['flows'])} flujos")
            else:
                print(text)
            return 0
        spec = load_any(getattr(a, "spec", None) or a.file)
        errors, warnings = validate(spec)
        if a.cmd == "validate":
            report(errors, warnings)
            return 1 if errors else 0
        if errors and not getattr(a, "force", False):
            report(errors, warnings)
            print("Corrija los errores (o use --force).")
            return 1
        geo = layout(spec)
        if a.cmd == "generate":
            xml = spec_to_bpmn(spec, geo)
            Path(a.out).write_text('<?xml version="1.0" encoding="UTF-8"?>\n' + xml, encoding="utf-8")
            print(f"BPMN escrito en {a.out}: {len(spec['pools'])} pool(s), {len(spec['nodes'])} nodos, "
                  f"{len(spec['flows'])} flujos, {len(spec['messageFlows'])} mensajes, "
                  f"{len(spec['associations'])} asociaciones")
            if a.svg:
                Path(a.svg).write_text(render_svg(spec, geo), encoding="utf-8")
                print(f"vista previa en {a.svg}")
            if warnings:
                report([], warnings)
        elif a.cmd == "preview":
            Path(a.out).write_text(render_svg(spec, geo), encoding="utf-8")
            print(f"vista previa en {a.out}")
        elif a.cmd == "docx":
            has_png = render_docx(spec, geo, a.out, png=not a.no_png)
            print(f"documento Word en {a.out}"
                  + ("" if has_png else " (diagrama solo en SVG: requiere Word 2016 o superior)"))
        elif a.cmd == "doc":
            md = render_doc(spec, geo)
            if a.out:
                Path(a.out).write_text(md, encoding="utf-8")
                print(f"documentación en {a.out}")
            else:
                print(md)
        return 0
    except (SpecError, ET.ParseError, FileNotFoundError, json.JSONDecodeError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
