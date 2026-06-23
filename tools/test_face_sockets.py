"""Self-check: los sockets faciales deben caer SOBRE el hueso de la cabeza
(entre la corona y el cuello), no en fracciones fijas del tile que se salen.
Corre: py tools/test_face_sockets.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
from pixelbones import model, templates
from pixelbones.app import App

pr = model.Project.load(os.path.join(os.path.dirname(__file__), "..",
                                     "pixelbones", "templates", "humano.pbproj"))
# la plantilla ya trae sockets (posiciones autoradas por el usuario); para probar
# la LOGICA de colocacion los quitamos y los re-creamos desde cero.
keep = [i for i, b in enumerate(pr.bones) if not b.anchor]
remap = {oi: ni for ni, oi in enumerate(keep)}
nb = []
for oi in keep:
    b = pr.bones[oi]
    b.parent = remap.get(b.parent, -1) if b.parent >= 0 else -1
    nb.append(b)
pr.bones = nb
for c in pr.clips:                       # limpia poses de huesos ya inexistentes
    for f in c.frames:
        f.poses = {k: v for k, v in f.poses.items()
                   if pr.bone_by_name(k) >= 0}
app = App.__new__(App)
app.project = pr
app.sel_kind, app.sel_idx = None, -1
app.cur_frame, app.cur_clip = -1, 0
app.working = {}
app.dirty = False
app.history = type("H", (), {"push": lambda self, d: None})()
app.status = ""

hi = templates.rig_profile(pr)["head"]
hw = model.bone_world(pr, hi, model.pose_for_frame(pr, None))
tx, ty = model.bone_tip(pr, hi, hw)
crown_y, neck_y = ty, hw[1]            # corona (arriba) .. cuello (abajo)
print(f"cabeza: corona y={crown_y:.1f}  cuello y={neck_y:.1f}")

order = []
for sid in ("pelo", "ojos", "nariz", "boca"):
    app.sel_kind, app.sel_idx = None, -1      # sin seleccion: auto-detecta cabeza
    app.create_socket(sid)
    j = pr.bone_by_name(sid)
    w = model.bone_world(pr, j, model.pose_for_frame(pr, None))
    order.append((sid, w[1]))
    assert pr.bones[j].parent == hi, f"{sid} no quedo enganchado a la cabeza"
    # dentro del span de la cabeza (con holgura de 1px para el pelo en la corona)
    assert crown_y - 1.0 <= w[1] <= neck_y + 1.0, \
        f"{sid} y={w[1]:.1f} fuera de la cabeza [{crown_y:.1f},{neck_y:.1f}]"
    print(f"  {sid:6s} -> world y={w[1]:.1f}  (parent=cabeza OK)")

# orden vertical correcto: pelo arriba < ojos < nariz < boca
ys = [y for _, y in order]
assert ys == sorted(ys), f"orden facial incorrecto: {order}"
print("OK: pelo/ojos/nariz/boca sobre la cabeza, enganchados y en orden")
