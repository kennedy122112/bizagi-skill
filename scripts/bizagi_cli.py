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
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from collections import defaultdict, deque
from pathlib import Path

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
ALIASES = {
    "inicio": "start", "fin": "end", "tarea": "task", "usuario": "userTask",
    "servicio": "serviceTask", "manual": "manualTask", "script": "scriptTask",
    "regla": "businessRuleTask", "subproceso": "subProcess", "xor": "exclusive",
    "and": "parallel", "or": "inclusive", "gateway": "exclusive",
    "compuerta": "exclusive", "temporizador": "timer",
}
_ALL_TYPES = {**EVENT_TYPES, **ACTIVITY_TYPES, **GATEWAY_TYPES}
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
    return "activity"


SIZE = {"event": (36, 36), "gateway": (40, 40), "activity": (100, 64)}


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
            "pools": [], "nodes": [], "flows": [], "messageFlows": [], "_errors": errors}
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

    def find_pool(ref):
        for p in spec["pools"]:
            if ref in (p["name"], p["id"], p["orig"]):
                return p
        return None

    node_ids = {}
    for n in raw.get("nodes", []):
        orig = str(n.get("id") or n.get("name"))
        if orig in node_ids:
            errors.append(f"id de nodo duplicado: '{orig}'")
            continue
        t = normalize_type(n.get("type"))
        pool, lane = None, n.get("lane")
        if n.get("pool"):
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
            live = [p for p in spec["pools"] if not p["blackbox"]]
            pool = live[0] if len(live) == 1 else None
            if not pool:
                errors.append(f"nodo '{orig}': indique 'lane' o 'pool'")
        if pool and lane and lane not in pool["lanes"]:
            errors.append(f"nodo '{orig}': el carril '{lane}' no pertenece al pool '{pool['name']}'")
        if pool and not lane and pool["lanes"]:
            lane = pool["lanes"][0]
            spec.setdefault("_warnings", []).append(
                f"nodo '{orig}' sin carril: se ubicó en '{lane}'")
        nid = ids.make(orig)
        node_ids[orig] = nid
        spec["nodes"].append({
            "id": nid, "orig": orig, "type": t, "name": n.get("name", ""),
            "pool": pool["id"] if pool else None, "lane": lane,
            "doc": n.get("doc") or n.get("documentation") or "",
            "timer": n.get("timer") or "",
        })

    def ref(x, allow_pool):
        if x in node_ids:
            return node_ids[x], False
        if allow_pool and find_pool(x):
            return find_pool(x)["id"], True
        return None, False

    for key, prefix, allow_pool in (("flows", "Flow", False), ("messageFlows", "MsgFlow", True)):
        for i, f in enumerate(raw.get(key, [])):
            f = parse_flow(f, i, prefix)
            s, s_pool = ref(f["from"], allow_pool)
            t, t_pool = ref(f["to"], allow_pool)
            if not s or not t:
                errors.append(f"flujo '{f['from']} -> {f['to']}': referencia a nodo inexistente "
                              f"'{f['from'] if not s else f['to']}'")
                continue
            f.update(id=ids.make(f["id"]), source=s, target=t, sourceIsPool=s_pool, targetIsPool=t_pool)
            spec[key].append(f)
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
    for p in spec["pools"]:
        if p["blackbox"]:
            continue
        pn = [n for n in spec["nodes"] if n["pool"] == p["id"]]
        if not pn:
            warnings.append(f"pool '{p['name']}' sin nodos (márquelo \"blackbox\": true si es externo)")
            continue
        if not any(n["type"].startswith("start") for n in pn):
            warnings.append(f"pool '{p['name']}' no tiene evento de inicio")
        if not any(n["type"].startswith("end") for n in pn):
            warnings.append(f"pool '{p['name']}' no tiene evento de fin")
    for n in spec["nodes"]:
        nid, t, k = n["id"], n["type"], kind(n["type"])
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
    # alcanzabilidad desde los inicios
    seen = set()
    dq = deque(n["id"] for n in spec["nodes"] if n["type"].startswith("start"))
    succ = defaultdict(list)
    for f in spec["flows"] + spec["messageFlows"]:
        succ[f["source"]].append(f["target"])
    while dq:
        x = dq.popleft()
        if x in seen:
            continue
        seen.add(x)
        dq.extend(succ[x])
    for n in spec["nodes"]:
        if n["id"] not in seen and not n["type"].startswith("start"):
            warnings.append(f"'{n['orig']}' no es alcanzable desde ningún inicio")
    return errors, sorted(set(warnings), key=warnings.index)


# ---------------------------------------------------------------- layout

COL_W, ROW_H, LANE_PAD, POOL_HDR, LEFT_PAD = 160, 110, 12, 30, 20
X0, Y0, POOL_GAP, BLACKBOX_H = 20, 20, 70, 70


def layout(spec):
    nodes = {n["id"]: n for n in spec["nodes"]}
    order = [n["id"] for n in spec["nodes"]]
    edges = [(f["source"], f["target"], f["id"]) for f in spec["flows"] + spec["messageFlows"]
             if f["source"] in nodes and f["target"] in nodes]
    succ = defaultdict(list)
    for s, t, fid in edges:
        succ[s].append((t, fid))

    # 1) detectar flujos de retorno (ciclos) con DFS iterativo
    back, state = set(), {}
    roots = [i for i in order if nodes[i]["type"].startswith("start")] + order
    for r in roots:
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
    fwd = [(s, t, fid) for s, t, fid in edges if fid not in back]
    indeg = defaultdict(int)
    fsucc, fpred = defaultdict(list), defaultdict(list)
    for s, t, fid in fwd:
        indeg[t] += 1
        fsucc[s].append(t)
        fpred[t].append(s)
    col = {i: 0 for i in order}
    dq = deque(i for i in order if indeg[i] == 0)
    topo = []
    while dq:
        v = dq.popleft()
        topo.append(v)
        for w in fsucc[v]:
            col[w] = max(col[w], col[v] + 1)
            indeg[w] -= 1
            if indeg[w] == 0:
                dq.append(w)

    # 3) filas dentro de cada carril: seguir la fila del predecesor, ramas debajo
    row, occupied = {}, set()
    for v in topo:
        n = nodes[v]
        lane_key = (n["pool"], n["lane"])
        pref = next((row[p] for p in fpred[v]
                     if p in row and (nodes[p]["pool"], nodes[p]["lane"]) == lane_key), 0)
        r = pref
        while (lane_key, col[v], r) in occupied:
            r += 1
        row[v] = r
        occupied.add((lane_key, col[v], r))

    max_col = max(col.values(), default=0)
    pool_w = POOL_HDR + LEFT_PAD + (max_col + 1) * COL_W + LEFT_PAD
    geo = {"pools": {}, "lanes": {}, "nodes": {}, "edges": {}, "back": back}
    y = Y0
    for p in spec["pools"]:
        if p["blackbox"]:
            geo["pools"][p["id"]] = (X0, y, pool_w, BLACKBOX_H)
            y += BLACKBOX_H + POOL_GAP
            continue
        py = y
        for lane in (p["lanes"] or [None]):
            rows = 1 + max((row[i] for i in order
                            if nodes[i]["pool"] == p["id"] and nodes[i]["lane"] == lane), default=0)
            lh = rows * ROW_H + 2 * LANE_PAD
            if lane is not None:
                geo["lanes"][(p["id"], lane)] = (X0 + POOL_HDR, y, pool_w - POOL_HDR, lh)
            for i in order:
                n = nodes[i]
                if n["pool"] == p["id"] and n["lane"] == lane:
                    w, h = SIZE[kind(n["type"])]
                    cx = X0 + POOL_HDR + LEFT_PAD + col[i] * COL_W + COL_W / 2
                    cy = y + LANE_PAD + ROW_H / 2 + row[i] * ROW_H
                    geo["nodes"][i] = (cx - w / 2, cy - h / 2, w, h)
            y += lh
        geo["pools"][p["id"]] = (X0, py, pool_w, y - py)
        y += POOL_GAP
    geo["size"] = (X0 + pool_w + 20, y - POOL_GAP + 20)

    for f in spec["flows"]:
        if f["source"] in geo["nodes"] and f["target"] in geo["nodes"]:
            geo["edges"][f["id"]] = route_seq(geo["nodes"][f["source"]], geo["nodes"][f["target"]],
                                              kind(nodes[f["source"]]["type"]),
                                              kind(nodes[f["target"]]["type"]), f["id"] in back)
    pool_of = {n["id"]: n["pool"] for n in spec["nodes"]}
    for f in spec["messageFlows"]:
        geo["edges"][f["id"]] = route_msg(f, geo, pool_of)
    return geo


def route_seq(S, T, sk, tk, is_back):
    sx, sy, sw, sh = S
    tx, ty, tw, th = T
    scx, scy, tcx, tcy = sx + sw / 2, sy + sh / 2, tx + tw / 2, ty + th / 2
    if not is_back and tx > sx + sw / 2:
        if abs(scy - tcy) < 1:
            return [(sx + sw, scy), (tx, tcy)]
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
    if ty > sy:
        y1, y2 = sy + sh, ty
        tpool = geo["pools"][f["target"] if f["targetIsPool"] else pool_of[f["target"]]]
        my = tpool[1] - POOL_GAP / 2
    else:
        y1, y2 = sy, ty + th
        tpool = geo["pools"][f["target"] if f["targetIsPool"] else pool_of[f["target"]]]
        my = tpool[1] + tpool[3] + POOL_GAP / 2
    if abs(scx - tcx) < 1:
        return [(scx, y1), (tcx, y2)]
    return [(scx, y1), (scx, my), (tcx, my), (tcx, y2)]


# ---------------------------------------------------------------- BPMN XML

def sub(parent, prefix, tag, text=None, **attrs):
    e = ET.SubElement(parent, q(prefix, tag), {k: str(v) for k, v in attrs.items() if v is not None})
    if text:
        e.text = text
    return e


def spec_to_bpmn(spec, geo):
    defs = ET.Element(q("bpmn", "definitions"), {
        "id": "Definitions_1", "name": spec["name"],
        "targetNamespace": "http://bizagi-cli/bpmn", "exporter": "bizagi-cli", "exporterVersion": "1.0"})
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
                    if n["lane"] == lane:
                        sub(le, "bpmn", "flowNodeRef", n["id"])
        for n in pnodes:
            t = n["type"]
            if t in EVENT_TYPES:
                tag, evdef = EVENT_TYPES[t]
            else:
                tag, evdef = (ACTIVITY_TYPES.get(t) or GATEWAY_TYPES[t]), None
            default = next((f["id"] for f in out[n["id"]] if f["default"]), None)
            e = sub(proc, "bpmn", tag, id=n["id"], name=n["name"], default=default)
            if t == "eventBased":
                e.set("eventGatewayType", "Exclusive")
            if n["doc"]:
                sub(e, "bpmn", "documentation", n["doc"])
            for f in inc[n["id"]]:
                sub(e, "bpmn", "incoming", f["id"])
            for f in out[n["id"]]:
                sub(e, "bpmn", "outgoing", f["id"])
            if evdef:
                d = sub(e, "bpmn", EVENT_DEF_TAG[evdef], id=n["id"] + "_def")
                if evdef == "timer" and n["timer"]:
                    td = sub(d, "bpmn", "timeDuration", n["timer"])
                    td.set(q("xsi", "type"), "bpmn:tFormalExpression")
                if evdef == "conditional":
                    c = sub(d, "bpmn", "condition", n["timer"] or None)
                    c.set(q("xsi", "type"), "bpmn:tFormalExpression")
        for f in spec["flows"]:
            if f["source"] in nodes and nodes[f["source"]]["pool"] == p["id"]:
                sf = sub(proc, "bpmn", "sequenceFlow", id=f["id"], name=f["name"] or None,
                         sourceRef=f["source"], targetRef=f["target"])
                if f["doc"]:
                    sub(sf, "bpmn", "documentation", f["doc"])
                if f["condition"]:
                    ce = sub(sf, "bpmn", "conditionExpression", f["condition"])
                    ce.set(q("xsi", "type"), "bpmn:tFormalExpression")

    # diagrama (BPMN DI)
    diag = sub(defs, "bpmndi", "BPMNDiagram", id="Diagram_1", name=spec["name"])
    plane = sub(diag, "bpmndi", "BPMNPlane", id="Plane_1", bpmnElement="Collaboration_1")

    def shape(el_id, b, **extra):
        s = sub(plane, "bpmndi", "BPMNShape", id=el_id + "_di", bpmnElement=el_id, **extra)
        sub(s, "dc", "Bounds", x=r(b[0]), y=r(b[1]), width=r(b[2]), height=r(b[3]))

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
    for f in spec["flows"] + spec["messageFlows"]:
        if f["id"] in geo["edges"]:
            e = sub(plane, "bpmndi", "BPMNEdge", id=f["id"] + "_di", bpmnElement=f["id"])
            for x, y in geo["edges"][f["id"]]:
                sub(e, "di", "waypoint", x=r(x), y=r(y))
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


def bpmn_to_raw(path):
    """Lee un BPMN 2.0 (p. ej. exportado desde Bizagi) y devuelve una spec JSON."""
    root = ET.parse(path).getroot()
    raw = {"name": root.get("name") or "", "pools": [], "nodes": [], "flows": [],
           "messageFlows": [], "_notes": []}
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
        for el in proc:
            tag = local(el.tag)
            t = None
            if tag in ("startEvent", "endEvent", "intermediateCatchEvent", "intermediateThrowEvent",
                       "boundaryEvent"):
                defs = [local(c.tag).replace("EventDefinition", "") for c in el
                        if local(c.tag).endswith("EventDefinition")]
                lookup_tag = "intermediateCatchEvent" if tag == "boundaryEvent" else tag
                t = REVERSE_EVENT.get((lookup_tag, defs[0] if defs else None)) \
                    or REVERSE_EVENT.get((lookup_tag, None)) or "intermediate"
                if tag == "boundaryEvent":
                    raw["_notes"].append(f"evento adjunto '{el.get('name') or el.get('id')}' en "
                                         f"'{el.get('attachedToRef')}' se leyó como evento intermedio")
            elif tag in ACTIVITY_TYPES:
                t = tag
                if tag == "subProcess" and any(local(c.tag) in ACTIVITY_TYPES for c in el):
                    raw["_notes"].append(f"subproceso '{el.get('name')}' tiene contenido interno; "
                                         "se representa contraído")
            elif tag in REVERSE_GATEWAY:
                t = REVERSE_GATEWAY[tag]
            if not t:
                continue
            node = {"id": el.get("id"), "type": t, "name": el.get("name") or ""}
            if lanes:
                node["lane"] = lane_of.get(el.get("id"), lanes[0])
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
            raw["nodes"].append(node)
        for sf in proc.findall(q("bpmn", "sequenceFlow")):
            raw["flows"].append(flow_to_raw(sf, ids_by_elem))
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
    if not raw["_notes"]:
        del raw["_notes"]
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
    for f in spec["flows"] + spec["messageFlows"]:
        pts = geo["edges"].get(f["id"])
        if not pts:
            continue
        is_msg = f["id"] in msg_ids
        d = " ".join(f"{x:.0f},{y:.0f}" for x, y in pts)
        style = ('stroke-dasharray="6 4" marker-start="url(#circ)" marker-end="url(#msg)"' if is_msg
                 else 'marker-end="url(#arr)"')
        out.append(f'<polyline points="{d}" fill="none" stroke="#374151" stroke-width="1.3" {style}/>')
        if f["default"]:
            (x1, y1), (x2, y2) = pts[0], pts[1]
            mx, my = x1 + (x2 - x1) * 0.25, y1 + (y2 - y1) * 0.25
            out.append(f'<line x1="{mx - 5}" y1="{my - 5}" x2="{mx + 5}" y2="{my + 5}" stroke="#374151"/>')
        if f["name"]:
            (x1, y1), (x2, y2) = pts[-2], pts[-1]
            if len(pts) > 2:
                (x1, y1), (x2, y2) = pts[1], pts[2]
            lx, ly = (x1 + x2) / 2, (y1 + y2) / 2 - 9
            out.append(f'<text x="{lx:.0f}" y="{ly:.0f}" font-size="10" text-anchor="middle" '
                       f'fill="#1d4ed8" paint-order="stroke" stroke="#fff" stroke-width="3">'
                       f'{html.escape(f["name"])}</text>')
    for nid, (x, y, w, h) in geo["nodes"].items():
        n = nodes[nid]
        t, k = n["type"], kind(n["type"])
        cx, cy = x + w / 2, y + h / 2
        if k == "activity":
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
            out.append(f'<circle cx="{cx}" cy="{cy}" r="{w / 2}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>')
            if k == "event" and not t.startswith(("start", "end")):
                out.append(f'<circle cx="{cx}" cy="{cy}" r="{w / 2 - 3}" fill="none" stroke="{stroke}"/>')
            if ev == "terminate":
                out.append(f'<circle cx="{cx}" cy="{cy}" r="{w / 2 - 7}" fill="{stroke}"/>')
            elif ev:
                out.append(f'<text x="{cx}" y="{cy + 1}" font-size="13" text-anchor="middle" '
                           f'dominant-baseline="middle">{EVENT_ICON[ev]}</text>')
            out.append(svg_text(cx, y + h + 14, n["name"], 18, 10))
        else:
            out.append(f'<polygon points="{cx},{y} {x + w},{cy} {cx},{y + h} {x},{cy}" fill="#fefce8" '
                       f'stroke="#ca8a04" stroke-width="1.5"/>')
            out.append(f'<text x="{cx}" y="{cy + 1}" font-size="16" text-anchor="middle" '
                       f'dominant-baseline="middle" fill="#854d0e">{GATEWAY_ICON[t]}</text>')
            # arriba a la izquierda: las ramas salen por arriba/abajo del rombo
            out.append(svg_text(x - 4, y - 4, n["name"], 20, 10, anchor="end"))
    out.append("</svg>")
    return "\n".join(out)


# ---------------------------------------------------------------- documentación

TYPE_ES = {"task": "Tarea", "userTask": "Tarea de usuario", "serviceTask": "Tarea de servicio",
           "manualTask": "Tarea manual", "scriptTask": "Tarea de script", "sendTask": "Envío",
           "receiveTask": "Recepción", "businessRuleTask": "Regla de negocio",
           "subProcess": "Subproceso", "callActivity": "Subproceso reutilizable"}


def render_doc(spec, geo):
    nodes = {n["id"]: n for n in spec["nodes"]}
    out_f = defaultdict(list)
    for f in spec["flows"]:
        out_f[f["source"]].append(f)
    order = sorted(geo["nodes"], key=lambda i: (geo["nodes"][i][0], geo["nodes"][i][1]))
    pools = {p["id"]: p for p in spec["pools"]}
    md = [f"# {spec['name']}", ""]
    if spec["doc"]:
        md += [spec["doc"], ""]
    md += ["## Participantes", ""]
    for p in spec["pools"]:
        roles = ", ".join(p["lanes"]) if p["lanes"] else ("externo" if p["blackbox"] else "—")
        md.append(f"- **{p['name']}**: {roles}")
    md += ["", "## Actividades", "", "| # | Actividad | Tipo | Responsable | Descripción |",
           "|---|---|---|---|---|"]
    k = 0
    for i in order:
        n = nodes[i]
        if kind(n["type"]) == "activity":
            k += 1
            who = n["lane"] or pools[n["pool"]]["name"]
            md.append(f"| {k} | {n['name']} | {TYPE_ES.get(n['type'], n['type'])} | {who} | "
                      f"{n['doc'].replace('|', '/') or ''} |")
    md += ["", "## Secuencia", ""]
    for i in order:
        n = nodes[i]
        nxt = out_f[i]
        name = n["name"] or n["orig"]
        if kind(n["type"]) == "gateway" and len(nxt) > 1:
            md.append(f"- **{name}** (decisión)")
            for f in nxt:
                cond = f["name"] or f["condition"] or ("por defecto" if f["default"] else "")
                md.append(f"  - {cond or '→'}: ir a *{nodes[f['target']]['name'] or f['target']}*")
        elif n["type"].startswith("end"):
            md.append(f"- Fin: **{name}**")
        elif nxt:
            tgt = ", ".join(f"*{nodes[f['target']]['name'] or f['target']}*" for f in nxt)
            md.append(f"- **{name}** → {tgt}")
    for f in spec["messageFlows"]:
        src = nodes[f["source"]]["name"] if f["source"] in nodes else pools[f["source"]]["name"]
        dst = nodes[f["target"]]["name"] if f["target"] in nodes else pools[f["target"]]["name"]
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
                  f"{len(spec['flows'])} flujos, {len(spec['messageFlows'])} mensajes")
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
