"""Self-check de los sockets faciales de la PLANTILLA estandar (humano):
- cada socket facial (ojos/pelo/nariz/boca) cuelga del MISMO hueso (la cabeza);
- son offset FIJO (sin poses por frame) -> siguen al hueso en TODAS las anims:
  la distancia socket<->punta del hueso padre es constante en cada frame/clip.
Corre: py tools/test_face_sockets.py"""
import os, sys, math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
from pixelbones import model, templates

TPL = os.path.join(os.path.dirname(__file__), "..", "pixelbones",
                   "templates", "humano.pbproj")
pr = model.Project.load(TPL)

FACE = ("ojos", "pelo", "nariz", "boca")
parents = set()
for sid in FACE:
    j = pr.bone_by_name(sid)
    assert j >= 0, f"falta el socket {sid} en la plantilla"
    assert pr.bones[j].anchor, f"{sid} debe ser ancla"
    parents.add(pr.bones[j].parent)
assert len(parents) == 1, f"los sockets faciales deben colgar del MISMO hueso: {parents}"
head = pr.bones[next(iter(parents))]
print(f"cabeza = '{head.name}', sockets faciales colgando de ella")

# normalizados: ningun ancla con poses por frame
for b in pr.bones:
    if not b.anchor:
        continue
    leaks = sum(1 for c in pr.clips for f in c.frames if b.name in f.poses)
    assert leaks == 0, f"{b.name} aun tiene {leaks} poses por frame (no normalizado)"

# siguen estrictamente: distancia al hueso padre CONSTANTE en todas las anims
for sid in FACE + ("mano_izq", "mano_der"):
    j = pr.bone_by_name(sid)
    par = pr.bones[j].parent
    ds = []
    for c in pr.clips:
        for f in (c.frames or [None]):
            pf = model.pose_for_frame(pr, f)
            sw = model.bone_world(pr, j, pf)
            ptip = model.bone_tip(pr, par, model.bone_world(pr, par, pf))
            ds.append(math.hypot(sw[0] - ptip[0], sw[1] - ptip[1]))
    assert max(ds) - min(ds) < 0.01, f"{sid}: no sigue al hueso (varia {max(ds)-min(ds):.3f})"
    print(f"  {sid:9s} dist al hueso CONSTANTE = {ds[0]:.2f}")

print("OK: sockets faciales sobre la cabeza y siguiendo el rig en todas las anims")
