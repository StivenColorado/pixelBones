"""Plantillas de animacion: un esqueleto + sus animaciones (poses de huesos),
SIN arte. El usuario carga una plantilla, dibuja/importa su arte, vincula cada
sprite a un hueso UNA vez (en reposo) y -como las animaciones son poses de
huesos- TODAS las animaciones aparecen con su dibujo. Reutilizable para cuerpos,
camisas, pantalones, zapatos, etc.

Una plantilla es un .pbproj normal (mismo formato) guardado en TEMPLATES_DIR,
pero con la lista de sprites vacia (solo rig + clips).
"""
from __future__ import annotations
import math
import os

from . import model, config

# carpeta de plantillas del usuario (junto a la config)
TEMPLATES_DIR = os.path.join(config.CONFIG_DIR, "templates")
# plantillas que vienen con el programa
BUILTIN_DIR = os.path.join(os.path.dirname(__file__), "templates")


def _ensure_dirs():
    os.makedirs(TEMPLATES_DIR, exist_ok=True)


def list_templates():
    """[(nombre, ruta)] de plantillas (builtin + usuario)."""
    out = []
    for d in (BUILTIN_DIR, TEMPLATES_DIR):
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if f.lower().endswith(".pbproj"):
                out.append((os.path.splitext(f)[0], os.path.join(d, f)))
    return out


def strip_art(project):
    """Devuelve una COPIA del proyecto sin sprites (solo rig + animaciones)."""
    d = project.to_dict()
    d["sprites"] = []
    return model.Project.from_dict(d)


def save_as_template(project, name):
    """Guarda el proyecto actual como plantilla (quita el arte)."""
    _ensure_dirs()
    safe = "".join(c if c.isalnum() or c in "-_ " else "_" for c in name).strip()
    if not safe:
        safe = "plantilla"
    path = os.path.join(TEMPLATES_DIR, safe + ".pbproj")
    strip_art(project).save(path)
    return path


def load_template(path):
    """Carga una plantilla como Project (rig + clips, sin sprites)."""
    pr = model.Project.load(path)
    pr.sprites = []          # por si la plantilla trae arte residual
    pr.path = None           # no sobrescribir la plantilla al guardar
    return pr


# ---------------------------------------------------------------------------
# Perfil del rig: detecta torso / cabeza / brazos / piernas por la jerarquia.
# (Funciona con nombres genericos tipo hueso.N.)
# ---------------------------------------------------------------------------
def rig_profile(project):
    bones = project.bones
    n = len(bones)
    children = {i: [] for i in range(n)}
    roots = []
    for i, b in enumerate(bones):
        if b.parent is None or b.parent < 0:
            roots.append(i)
        else:
            children[b.parent].append(i)
    if not roots:
        return None

    def subtree_size(i):
        return 1 + sum(subtree_size(c) for c in children[i])

    torso = max(roots, key=lambda r: (len(children[r]), subtree_size(r)))
    legs = [r for r in roots if r != torso]

    def chain(i):
        out = [i]
        while children[out[-1]]:
            out.append(children[out[-1]][0])
        return out

    tch = children[torso]
    arm_roots = [c for c in tch if children[c]]
    head = [c for c in tch if not children[c]]
    arm_chains = [chain(a) for a in arm_roots]
    leg_chains = [chain(l) for l in legs]

    def world_x(i):
        return model.bone_world(project, i, model.pose_for_frame(project, None))[0]

    arm_chains.sort(key=lambda ch: world_x(ch[0]))   # izq..der por X mundo
    leg_chains.sort(key=lambda ch: world_x(ch[0]))
    return {"torso": torso, "head": head[0] if head else None,
            "arms": arm_chains, "legs": leg_chains,
            "name": [b.name for b in bones]}


# ---------------------------------------------------------------------------
# Generador de animaciones "extra" a partir de la pose de REPOSO.
# Son borradores editables (rotaciones plausibles de extremidades).
# ---------------------------------------------------------------------------
def _base_poses(project):
    """Pose NATURAL de pie: la del primer frame de la animacion 'reposo' (o
    'caminando'), no la rest/T-pose del editor (que suele tener brazos en cruz).
    Las animaciones extra se construyen sobre esta para verse coherentes."""
    base = {b.name: model.clone_pose(b.rest) for b in project.bones}
    for nm in ("reposo", "idle", "caminando", "andar"):
        c = next((c for c in project.clips if c.name == nm), None)
        if c and c.frames:
            for k, v in c.frames[0].poses.items():
                base[k] = model.clone_pose(v)
            break
    return base


def _frame_from_deltas(project, deltas, fname):
    """deltas: {bone_idx: {'drot':deg,'dx':,'dy':,'dscale':}}. Construye un Frame
    partiendo de la pose natural de pie y aplicando los deltas indicados."""
    f = model.Frame(fname)
    f.poses = _base_poses(project)
    for idx, dd in deltas.items():
        nm = project.bones[idx].name
        p = f.poses[nm]
        p["rot"] += dd.get("drot", 0.0)
        p["x"] += dd.get("dx", 0.0)
        p["y"] += dd.get("dy", 0.0)
        p["scale"] *= dd.get("dscale", 1.0)
    return f


def _swing(chain, amps):
    """{bone_idx: {'drot':amp}} para una cadena (hombro, codo, ...)."""
    return {chain[i]: {"drot": amps[i]} for i in range(min(len(chain), len(amps)))}


def build_extra_animations(project, replace=False):
    """Anade clips borrador: agacharse, sentado, atacar, cortar, acostado.
    Usa el perfil del rig. Devuelve los nombres anadidos."""
    prof = rig_profile(project)
    if not prof:
        return []
    torso = prof["torso"]
    arms = prof["arms"]
    legs = prof["legs"]
    head = prof["head"]
    armR = arms[-1] if arms else []          # brazo derecho (mayor X)
    existing = {c.name for c in project.clips}
    added = []

    def add_clip(name, frames, dur=1.0):
        if name in existing and not replace:
            return
        if name in existing:
            project.clips = [c for c in project.clips if c.name != name]
        c = model.Clip(name, dur)
        c.frames = frames
        project.clips.append(c)
        added.append(name)

    # -- agacharse: flexion SUAVE de rodillas + bajar el torso --------------
    def crouch(amount):
        d = {torso: {"dy": 14 * amount}}
        for leg in legs:
            if len(leg) >= 1:
                d[leg[0]] = {"drot": 18 * amount}      # cadera
            if len(leg) >= 2:
                d[leg[1]] = {"drot": -34 * amount}     # rodilla
        if head is not None:
            d[head] = {"dy": 14 * amount}
        return d
    add_clip("agacharse",
             [_frame_from_deltas(project, crouch(0.0), "f1"),
              _frame_from_deltas(project, crouch(1.0), "f2")], dur=0.6)

    # -- sentado: torso bajado y piernas algo flexionadas (borrador) --------
    def sit():
        d = {torso: {"dy": 22}}
        for leg in legs:
            if len(leg) >= 1:
                d[leg[0]] = {"drot": 30}
            if len(leg) >= 2:
                d[leg[1]] = {"drot": -55}
        if head is not None:
            d[head] = {"dy": 22}
        return d
    add_clip("sentado", [_frame_from_deltas(project, sit(), "f1")], dur=1.0)

    # -- atacar: brazo derecho describe un arco (golpe) ---------------------
    if armR:
        atk = [
            _frame_from_deltas(project, _swing(armR, [-70, -30]), "f1"),
            _frame_from_deltas(project, _swing(armR, [-20, -10]), "f2"),
            _frame_from_deltas(project, _swing(armR, [55, 35]), "f3"),
            _frame_from_deltas(project, _swing(armR, [80, 50]), "f4"),
            _frame_from_deltas(project, _swing(armR, [10, 0]), "f5"),
        ]
        add_clip("atacar", atk, dur=0.6)
        # -- cortar: arco mas horizontal y repetido -------------------------
        cut = [
            _frame_from_deltas(project, _swing(armR, [-50, -20]), "f1"),
            _frame_from_deltas(project, _swing(armR, [20, 30]), "f2"),
            _frame_from_deltas(project, _swing(armR, [60, 10]), "f3"),
            _frame_from_deltas(project, _swing(armR, [20, 30]), "f4"),
        ]
        add_clip("cortar", cut, dur=0.7)

    # NOTA: "acostado" (girar el cuerpo 90) no se genera porque en este rig las
    # piernas son raices independientes (no cuelgan de una cadera), asi que el
    # cuerpo no rota como una pieza. Requiere re-riggear con un hueso 'cadera'
    # padre de torso y piernas; entonces se puede anadir.

    return added
