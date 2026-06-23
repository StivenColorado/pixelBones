"""Self-check de apply_global_scale: un factor f debe multiplicar por f la
posicion y el tamano de mundo de CADA pieza en CADA frame (reposo y animado),
escalando respecto al pivot. Corre: py tools/test_global_scale.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

from pixelbones import model


def build():
    pr = model.Project()
    # rig: raiz 'cadera' con hijo 'torso'; un sprite libre y uno vinculado
    cad = model.Bone("cadera"); cad.parent = -1
    cad.rest = {"x": 10.0, "y": -40.0, "rot": 0.0, "scale": 1.0}
    tor = model.Bone("torso"); tor.parent = 0
    tor.rest = {"x": 0.0, "y": -20.0, "rot": 0.0, "scale": 1.0}
    pr.bones = [cad, tor]
    free = model.Sprite("libre"); free.transform = {"x": 5.0, "y": 5.0, "rot": 0.0, "scale": 1.0}
    bound = model.Sprite("ropa"); bound.bone = "torso"
    bound.local = {"x": 3.0, "y": 1.0, "rot": 0.0, "scale": 1.0}
    pr.sprites = [free, bound]
    # un clip con un frame animado (rota+escala el torso, mueve la cadera)
    fr = model.Frame("f1")
    fr.poses = {"cadera": {"x": 12.0, "y": -38.0, "rot": 0.0, "scale": 1.0},
                "torso": {"x": 0.0, "y": -20.0, "rot": 25.0, "scale": 1.3}}
    pr.clips[0].frames = [fr]
    return pr


def world_snapshot(pr, frame):
    pf = model.pose_for_frame(pr, frame)
    out = {}
    for i, b in enumerate(pr.bones):
        out["bone:" + b.name] = model.bone_world(pr, i, pf)
    for s in pr.sprites:
        out["spr:" + s.name] = model.sprite_world(pr, s, pf)
    return out


def main():
    from pixelbones.app import App  # importa la logica real
    pr = build()
    f, pivot = 2.0, (0.0, -56.0)

    before = {None: world_snapshot(pr, None),
              "f1": world_snapshot(pr, pr.clips[0].frames[0])}

    # aplica via el metodo real (sin construir ventana: parchea __init__)
    app = App.__new__(App)
    app.project = pr
    app.cur_frame = -1
    app.cur_clip = 0
    app.working = {}
    app.dirty = False
    app._thumbs_dirty = False
    app.apply_global_scale(f, pivot)

    after = {None: world_snapshot(pr, None),
             "f1": world_snapshot(pr, pr.clips[0].frames[0])}

    cx, cy = pivot
    for fname in (None, "f1"):
        for key in before[fname]:
            bx, by, brot, bsc = before[fname][key]
            ax, ay, arot, asc = after[fname][key]
            ex, ey = cx + (bx - cx) * f, cy + (by - cy) * f
            assert abs(ax - ex) < 1e-6, (fname, key, "x", ax, ex)
            assert abs(ay - ey) < 1e-6, (fname, key, "y", ay, ey)
            assert abs(arot - brot) < 1e-6, (fname, key, "rot")
            assert abs(asc - bsc * f) < 1e-6, (fname, key, "scale", asc, bsc * f)
    print("OK: escala global x%.1f uniforme en reposo y frame animado" % f)

    # --- mover global: mismo delta en todo, sin descuadrar entre frames ----
    dx, dy = 7.0, -3.0
    pre = {None: world_snapshot(pr, None),
           "f1": world_snapshot(pr, pr.clips[0].frames[0])}
    app.apply_global_move(dx, dy)
    post = {None: world_snapshot(pr, None),
            "f1": world_snapshot(pr, pr.clips[0].frames[0])}
    for fname in (None, "f1"):
        for key in pre[fname]:
            bx, by = pre[fname][key][0], pre[fname][key][1]
            ax, ay = post[fname][key][0], post[fname][key][1]
            assert abs(ax - (bx + dx)) < 1e-6, (fname, key, "x")
            assert abs(ay - (by + dy)) < 1e-6, (fname, key, "y")
    # la diferencia reposo<->frame de cada pieza debe ser identica antes/despues
    for key in pre[None]:
        d_pre = (pre["f1"][key][1] - pre[None][key][1])
        d_post = (post["f1"][key][1] - post[None][key][1])
        assert abs(d_pre - d_post) < 1e-6, (key, "altura relativa cambio")
    print("OK: mover global (%.0f,%.0f) sin descuadrar la altura de los frames"
          % (dx, dy))


if __name__ == "__main__":
    main()
