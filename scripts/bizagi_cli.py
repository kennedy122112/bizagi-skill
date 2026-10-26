#!/usr/bin/env python3
"""bizagi-cli: genera, lee, valida, previsualiza y documenta procesos BPMN 2.0
para Bizagi Modeler, 100 % local (sin MCP ni API).

Comandos:
  generate <spec.json> -o salida.bpmn [--svg vista.svg]   spec -> BPMN 2.0 con diagrama (importable en Bizagi)
  read     <modelo.bpmn> [-o spec.json]                    BPMN (export de Bizagi) -> spec JSON editable
  validate <spec.json|modelo.bpmn>                         reglas de modelado
  preview  <spec.json|modelo.bpmn> -o vista.svg            diagrama SVG para revisar sin abrir Bizagi
  doc      <spec.json|modelo.bpmn> [-o doc.md]             documentación Markdown del proceso
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

VERSION = "0.2.0"

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


def render_doc(spec, geo):
    nodes = {n["id"]: n for n in spec["nodes"]}
    title = lambda i: nodes[i]["name"] or nodes[i]["orig"]
    out_f = defaultdict(list)
    for f in spec["flows"]:
        out_f[f["source"]].append(f)
    ins, outs, notes = defaultdict(list), defaultdict(list), defaultdict(list)
    for a in spec["associations"]:
        s, t = nodes[a["source"]], nodes[a["target"]]
        if s["type"] in DATA_TYPES:
            ins[t["id"]].append(s["name"])
        elif t["type"] in DATA_TYPES:
            outs[s["id"]].append(t["name"])
        elif s["type"] == "annotation":
            notes[t["id"]].append(s["text"])
        elif t["type"] == "annotation":
            notes[s["id"]].append(t["text"])
    boundary_of = defaultdict(list)
    for n in spec["nodes"]:
        if n["attachedTo"]:
            boundary_of[n["attachedTo"]].append(n)
    order = sorted((i for i in geo["nodes"] if kind(nodes[i]["type"]) != "artifact"
                    and not nodes[i]["attachedTo"]),
                   key=lambda i: (geo["nodes"][i][0], geo["nodes"][i][1]))
    pools = {p["id"]: p for p in spec["pools"]}
    md = [f"# {spec['name']}", ""]
    if spec["doc"]:
        md += [spec["doc"], ""]
    md += ["## Participantes", ""]
    for p in spec["pools"]:
        roles = ", ".join(p["lanes"]) if p["lanes"] else ("externo" if p["blackbox"] else "—")
        md.append(f"- **{p['name']}**: {roles}")
    md += ["", "## Actividades", "",
           "| # | Actividad | Tipo | Responsable | Entradas | Salidas | Descripción |",
           "|---|---|---|---|---|---|---|"]
    k = 0
    cell = lambda s: (s or "").replace("|", "/").replace("\n", " ")
    for i in order:
        n = nodes[i]
        if kind(n["type"]) == "activity":
            k += 1
            who = n["lane"] or pools[n["pool"]]["name"]
            desc = " ".join(filter(None, [n["doc"]] + notes[i]))
            md.append(f"| {k} | {cell(n['name'])} | {TYPE_ES.get(n['type'], n['type'])} | {cell(who)} | "
                      f"{cell(', '.join(ins[i]))} | {cell(', '.join(outs[i]))} | {cell(desc)} |")
    md += ["", "## Secuencia", ""]
    for i in order:
        n = nodes[i]
        nxt = out_f[i]
        name = title(i)
        if kind(n["type"]) == "gateway" and len(nxt) > 1:
            md.append(f"- **{name}** (decisión)")
            for f in nxt:
                cond = f["name"] or f["condition"] or ("por defecto" if f["default"] else "")
                md.append(f"  - {cond or '→'}: ir a *{title(f['target'])}*")
        elif n["type"].startswith("end"):
            md.append(f"- Fin: **{name}**")
        elif nxt:
            tgt = ", ".join(f"*{title(f['target'])}*" for f in nxt)
            md.append(f"- **{name}** → {tgt}")
        for b in boundary_of[i]:
            tgt = ", ".join(f"*{title(f['target'])}*" for f in out_f[b["id"]]) or "—"
            mode = "interrumpe la actividad" if b["interrupting"] else "sin interrumpir la actividad"
            when = f" ({b['timer']})" if b["timer"] else ""
            md.append(f"  - Excepción por {BOUNDARY_ES.get(b['type'], b['type'])}: "
                      f"**{b['name'] or b['orig']}**{when}, {mode} → {tgt}")
    for f in spec["messageFlows"]:
        src = title(f["source"]) if f["source"] in nodes else pools[f["source"]]["name"]
        dst = title(f["target"]) if f["target"] in nodes else pools[f["target"]]["name"]
        md.append(f"- Mensaje{(' «' + f['name'] + '»') if f['name'] else ''}: {src} ⇢ {dst}")
    return "\n".join(md) + "\n"


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
