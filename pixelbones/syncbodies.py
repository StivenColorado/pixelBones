"""Sincronizacion entre bodies (conexiones + animaciones) y re-export espejo.

Un body "origen" (donde el usuario ya configuro los sockets/anclas y los clips)
se replica al resto de bodies de <root>/<src_dir>/characters/body/*: las anclas
se copian mapeando el hueso padre por NOMBRE y los clips se anaden SOLO si no
existen en el destino (nunca se pisan). Si hubo cambios se guarda el .pbproj y
(opcional) se re-exporta el espejo <root>/<assets_dir> (animacion.png/.json +
animacion_frente.png), replicando App.export_composite para kind="body".

Modulo puro (sin UI): la app lo usa desde su modal y tambien es ejecutable
como self-check (ver __main__ al final).
"""

from __future__ import annotations
import os
import sys

import pygame

try:
    from . import model, render
except ImportError:                    # ejecutado como script (self-check)
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from pixelbones import model, render


BODY_SUBPATH = os.path.join("characters", "body")


# ---------------------------------------------------------------------------
# descubrimiento y plan
# ---------------------------------------------------------------------------
def list_bodies(project_root, src_dir="art-src"):
    """[(variante, ruta_pbproj)] de los bodies editables bajo
    <root>/<src_dir>/characters/body/<variante>/animacion.pbproj, ordenado.
    Excluye rutas inexistentes; [] si no hay project_root."""
    out = []
    if not project_root:
        return out
    base = os.path.join(project_root, src_dir, BODY_SUBPATH)
    if os.path.isdir(base):
        for name in sorted(os.listdir(base)):
            p = os.path.join(base, name, "animacion.pbproj")
            if os.path.isfile(p):
                out.append((name, p))
    return out


def plan_sync(src_project):
    """Resumen de lo que se sincronizaria desde el body origen (para la UI):
    {"anchors": [nombres de sockets presentes], "clips": [nombres de clips]}."""
    return {
        "anchors": [b.name for b in src_project.bones
                    if getattr(b, "anchor", False)],
        "clips": [c.name for c in src_project.clips],
    }


# ---------------------------------------------------------------------------
# rutas espejo art-src -> assets (replica App._mirror_path como funcion pura)
# ---------------------------------------------------------------------------
def mirror_path(project_root, src_dir, assets_dir, pbproj_path, ext):
    """Ruta espejo en <root>/<assets_dir> de un .pbproj bajo <root>/<src_dir>.
    Devuelve None si no aplica (fuera del arbol de editables)."""
    if not (project_root and pbproj_path):
        return None
    src = os.path.abspath(os.path.join(project_root, src_dir))
    p = os.path.abspath(pbproj_path)
    if not (p == src or p.startswith(src + os.sep)):
        return None
    rel = os.path.relpath(p, src)
    return os.path.join(project_root, assets_dir,
                        os.path.splitext(rel)[0] + ext)


def _infer_root(pbproj_path, src_dir):
    """Raiz del proyecto = padre del componente <src_dir> en la ruta. None si
    la ruta no pasa por <src_dir> (entonces no hay espejo donde exportar)."""
    cur = os.path.dirname(os.path.abspath(pbproj_path))
    while True:
        parent, name = os.path.split(cur)
        if not name:
            return None
        if name.lower() == src_dir.lower():
            return parent
        cur = parent


# ---------------------------------------------------------------------------
# export (replica App.export_composite para kind="body")
# ---------------------------------------------------------------------------
def _clip_content_box(project, clip, margin=4):
    """bbox en mundo (bx, by, w, h) que contiene TODO el contenido de todos
    los frames del clip, con margen. None si no hay contenido."""
    sprites = [s for s in project.sprites
               if s.visible and s.surface is not None and s.content_rect]
    if not sprites:
        return None
    frames = clip.frames or [None]
    minx = miny = 1e9
    maxx = maxy = -1e9
    for f in frames:
        pose_for = model.pose_for_frame(project, f)
        for sp in sprites:
            wt = model.sprite_world(project, sp, pose_for)
            cx, cy, cw, ch = sp.content_rect
            for ix, iy in ((cx, cy), (cx + cw, cy),
                           (cx + cw, cy + ch), (cx, cy + ch)):
                ox, oy = model._rot((ix - sp.pivot[0]) * wt[3],
                                    (iy - sp.pivot[1]) * wt[3], wt[2])
                px, py = wt[0] + ox, wt[1] + oy
                minx, maxx = min(minx, px), max(maxx, px)
                miny, maxy = min(miny, py), max(maxy, py)
    if minx > maxx:
        return None
    return (minx - margin, miny - margin,
            (maxx - minx) + 2 * margin, (maxy - miny) + 2 * margin)


def ensure_clips_fit(project, margin=4):
    """Expande (nunca encoge) el recuadro de cada animacion para que el
    contenido NUNCA se recorte. Devuelve cuantas animaciones se agrandaron."""
    import math
    changed = 0
    for clip in project.clips:
        cb = _clip_content_box(project, clip, margin)
        if cb is None:
            continue
        cur = render.clip_box(project, clip)
        x0, y0 = min(cur[0], cb[0]), min(cur[1], cb[1])
        x1 = max(cur[0] + cur[2], cb[0] + cb[2])
        y1 = max(cur[1] + cur[3], cb[1] + cb[3])
        nw, nh = int(math.ceil(x1 - x0)), int(math.ceil(y1 - y0))
        if (nw > int(round(cur[2])) or nh > int(round(cur[3]))
                or x0 < cur[0] - 0.5 or y0 < cur[1] - 0.5):
            clip.box_x, clip.box_y = math.floor(x0), math.floor(y0)
            clip.tile_w, clip.tile_h = nw, nh
            changed += 1
    return changed


def _front_band_ids(project):
    """Indices de sprites del body que van en la banda DELANTE de la ropa
    (z > clothes_z) -> se exportan a animacion_frente.png. set() si no aplica."""
    if project.kind == "body" and project.clothes_z is not None:
        return {i for i, s in enumerate(project.sprites)
                if s.z > project.clothes_z}
    return set()


def _ensure_display():
    """Display perezoso SOLO para exportar (blits/convert necesitan modo de
    video). (ok, msg): si no hay video disponible no crashea, avisa."""
    if pygame.display.get_init() and pygame.display.get_surface() is not None:
        return True, ""
    try:
        pygame.display.init()
        if pygame.display.get_surface() is None:
            pygame.display.set_mode((1, 1), pygame.HIDDEN)
        return True, ""
    except Exception as e:
        # deja el display SIN init: convert_alpha() de cargas posteriores no
        # debe asumir que hay modo de video
        try:
            pygame.display.quit()
        except Exception:
            pass
        return False, f"sin video para exportar ({e})"


def export_body(project, project_root, src_dir="art-src", assets_dir="assets"):
    """Re-exporta un body a su espejo assets: animacion.png + animacion.json y,
    si hay banda frente (clothes_z), animacion_frente.png. Devuelve (ok, msg)."""
    path = mirror_path(project_root, src_dir, assets_dir, project.path, ".png")
    if not path:
        return False, "sin ruta espejo art-src -> assets"
    ok, msg = _ensure_display()
    if not ok:
        return False, msg
    try:
        render.ensure_surfaces(project)
        nfit = ensure_clips_fit(project)      # nunca recortar (body)
        if nfit and project.path:             # el pbproj refleja el ajuste
            project.save(project.path)
        front_ids = _front_band_ids(project)
        main_filter = ((set(range(len(project.sprites))) - front_ids)
                       if front_ids else None)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        sz = render.export_composite(project, path, None,
                                     sprites_filter=main_filter)
        render.export_meta(project, os.path.splitext(path)[0] + ".json")
        if front_ids:                         # banda del frente (sobre ropa)
            render.export_composite(project,
                                    os.path.splitext(path)[0] + "_frente.png",
                                    None, sprites_filter=front_ids)
        extra = f", ajuste {nfit} anim." if nfit else ""
        if front_ids:
            extra += f", +banda _frente ({len(front_ids)} partes)"
        return True, f"exportado {sz[0]}x{sz[1]}{extra}"
    except Exception as e:
        return False, f"error export: {e}"


# ---------------------------------------------------------------------------
# sincronizacion
# ---------------------------------------------------------------------------
def _rig_names(project):
    """Nombres de los huesos NO-ancla (el rig real que debe coincidir)."""
    return {b.name for b in project.bones if not getattr(b, "anchor", False)}


def sync_to_bodies(src_project, dst_paths, sync_anchors=True, sync_clips=True,
                   reexport=True, progress=None,
                   src_dir="art-src", assets_dir="assets"):
    """Replica anclas/clips del body origen a cada .pbproj de dst_paths.

    - anclas: se actualiza la existente del mismo nombre o se anade; el padre
      se mapea por NOMBRE del hueso (si falta en el destino, se salta con aviso).
    - clips: se anaden SOLO los que no existan por nombre (deep-copy).
    - guarda y re-exporta (espejo assets) SOLO si hubo cambios.
    Devuelve [{"name","ok","msg","anchors","clips_added","exported"}, ...].
    """
    src_anchors = [b for b in src_project.bones if getattr(b, "anchor", False)]
    src_rig = _rig_names(src_project)
    src_path = (os.path.abspath(src_project.path)
                if getattr(src_project, "path", None) else None)
    results = []
    total = len(dst_paths)
    for i, path in enumerate(dst_paths):
        name = os.path.basename(os.path.dirname(os.path.abspath(path)))
        if progress:
            progress(name, i, total)
        res = {"name": name, "ok": True, "msg": "", "anchors": 0,
               "clips_added": 0, "exported": False}
        results.append(res)
        if src_path and os.path.abspath(path) == src_path:
            res["msg"] = "es el body origen (omitido)"
            continue
        try:
            dst = model.Project.load(path)
        except Exception as e:
            res.update(ok=False, msg=f"no se pudo abrir: {e}")
            continue
        # rig compatible: mismos nombres de huesos no-ancla (si no, NO tocar)
        dst_rig = _rig_names(dst)
        if dst_rig != src_rig:
            det = []
            faltan = sorted(src_rig - dst_rig)
            sobran = sorted(dst_rig - src_rig)
            if faltan:
                det.append("faltan: " + ", ".join(faltan[:6]))
            if sobran:
                det.append("sobran: " + ", ".join(sobran[:6]))
            res.update(ok=False,
                       msg="rig incompatible (" + "; ".join(det) + ")")
            continue
        changed = False
        warns = []
        if sync_anchors:
            for b in src_anchors:
                pname = (src_project.bones[b.parent].name
                         if 0 <= b.parent < len(src_project.bones) else None)
                pidx = dst.bone_by_name(pname) if pname else -1
                if pname and pidx < 0:
                    warns.append(f"ancla '{b.name}': sin hueso '{pname}'")
                    continue
                di = dst.bone_by_name(b.name)
                if di < 0:                     # append: no rompe indices padre
                    dst.bones.append(model.Bone(b.name))
                    di = len(dst.bones) - 1
                    changed = True
                db = dst.bones[di]
                if (db.parent != pidx or not getattr(db, "anchor", False)
                        or float(db.length) != float(b.length)
                        or model.clone_pose(db.rest) != model.clone_pose(b.rest)):
                    changed = True
                db.parent = pidx
                db.rest = model.clone_pose(b.rest)
                db.length = float(b.length)
                db.anchor = True
                res["anchors"] += 1
        if sync_clips:
            have = {c.name for c in dst.clips}
            for c in src_project.clips:
                if c.name in have:
                    continue
                dst.clips.append(model.Clip.from_dict(c.to_dict()))
                res["clips_added"] += 1
                changed = True
        parts = [f"anclas {res['anchors']}, clips +{res['clips_added']}"]
        parts += warns
        if not changed:
            res["msg"] = "sin cambios" + ("; " + "; ".join(warns) if warns else "")
            continue
        try:
            dst.save(path)
        except Exception as e:
            res.update(ok=False, msg=f"no se pudo guardar: {e}")
            continue
        if reexport:
            root = _infer_root(path, src_dir)
            if not root:
                parts.append(f"sin raiz {src_dir}/ (no exportado)")
            else:
                eok, emsg = export_body(dst, root, src_dir, assets_dir)
                res["exported"] = eok
                parts.append(emsg)
        res["msg"] = "; ".join(parts)
    return results


# ---------------------------------------------------------------------------
# self-check (usa COPIAS en %TEMP% de un body real; NUNCA toca art-src)
# ---------------------------------------------------------------------------
def _self_check():
    import json
    import shutil
    import tempfile

    # raiz de TrashGame (hermano de pixelBones) o argv[1]
    default_root = os.path.normpath(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        os.pardir, "TrashGame"))
    root = sys.argv[1] if len(sys.argv) > 1 else default_root
    bodies = list_bodies(root)
    assert bodies, f"no hay bodies en {root}/art-src/characters/body"
    real_name, real_pb = bodies[0]
    print(f"body real de referencia: '{real_name}' ({real_pb})")

    tmp = tempfile.mkdtemp(prefix="pb_syncbodies_")
    try:
        base = os.path.join(tmp, "art-src", BODY_SUBPATH)

        def copy_body(vname):
            d = os.path.join(base, vname)
            os.makedirs(d)
            p = os.path.join(d, "animacion.pbproj")
            shutil.copyfile(real_pb, p)
            return p

        def degrade(path):
            """Borra un ancla (hoja) y renombra un clip, en el JSON crudo.
            Devuelve (nombre_ancla_borrada, nombre_clip_original)."""
            with open(path, encoding="utf-8") as fh:
                d = json.load(fh)
            bones = d["bones"]
            used = {b["parent"] for b in bones}
            idx = max(i for i, b in enumerate(bones)
                      if b.get("anchor") and i not in used)
            removed = bones.pop(idx)["name"]
            for b in bones:                    # reindexa padres tras el pop
                if b["parent"] > idx:
                    b["parent"] -= 1
            renamed = d["clips"][0]["name"]
            d["clips"][0]["name"] = "zz_renombrado"
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(d, fh)
            return removed, renamed

        origen = copy_body("origen")
        destino = copy_body("destino")
        destino2 = copy_body("destino2")
        removed, renamed = degrade(destino)
        degrade(destino2)
        print(f"degradado: ancla '{removed}' borrada, clip '{renamed}' renombrado")

        src = model.Project.load(origen)
        plan = plan_sync(src)
        assert removed in plan["anchors"], plan
        assert renamed in plan["clips"], plan
        ai = src.bone_by_name(removed)
        src_parent = src.bones[src.bones[ai].parent].name

        # 1) sync SIN export: restaura el ancla + anade el clip faltante
        seen = []
        res = sync_to_bodies(src, [destino], reexport=False,
                             progress=lambda n, i, t: seen.append((n, i, t)))
        r = res[0]
        print("resultado 1:", r)
        assert r["ok"] and not r["exported"], r
        assert r["anchors"] == len(plan["anchors"]), r
        assert r["clips_added"] == 1, r
        assert seen == [("destino", 0, 1)], seen
        dst = model.Project.load(destino)
        di = dst.bone_by_name(removed)
        assert di >= 0, "el ancla borrada no se restauro"
        db = dst.bones[di]
        assert db.anchor, "restaurada pero sin flag anchor"
        assert dst.bones[db.parent].name == src_parent, \
            f"padre mal mapeado: {dst.bones[db.parent].name} != {src_parent}"
        assert model.clone_pose(db.rest) == model.clone_pose(src.bones[ai].rest)
        assert renamed in {c.name for c in dst.clips}, "clip faltante no anadido"
        sc = next(c for c in src.clips if c.name == renamed)
        dc = next(c for c in dst.clips if c.name == renamed)
        assert len(dc.frames) == len(sc.frames), "deep-copy de frames incompleta"
        # idempotencia: segunda pasada sin cambios -> no reescribe
        res2 = sync_to_bodies(src, [destino], reexport=False)
        assert "sin cambios" in res2[0]["msg"], res2

        # 2) sync CON export -> espejo assets/ del dir temporal
        res3 = sync_to_bodies(src, [destino2], reexport=True)
        r3 = res3[0]
        print("resultado 2:", r3)
        assert r3["ok"], r3
        if not r3["exported"]:                 # entorno sin video: no crashea
            print("AVISO: sin video, export omitido ->", r3["msg"])
        else:
            mirror = os.path.join(tmp, "assets", BODY_SUBPATH, "destino2")
            png = os.path.join(mirror, "animacion.png")
            js = os.path.join(mirror, "animacion.json")
            assert os.path.isfile(png), "falta animacion.png en el espejo"
            assert os.path.isfile(js), "falta animacion.json en el espejo"
            with open(js, encoding="utf-8") as fh:
                meta = json.load(fh)
            rows = {row["name"] for row in meta["rows"]}
            assert renamed in rows, rows
            anchors0 = meta["rows"][0].get("anchors", {})
            assert all(a in anchors0 for a in plan["anchors"]), anchors0.keys()
            dst2 = model.Project.load(destino2)
            if _front_band_ids(dst2):
                fp = os.path.join(mirror, "animacion_frente.png")
                assert os.path.isfile(fp), "falta animacion_frente.png"
                print("banda _frente exportada OK")
        print("self-check OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    _self_check()
