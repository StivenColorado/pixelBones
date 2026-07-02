"""Render y exportacion con pygame. Solo los SPRITES se dibujan/exportan; los
huesos son guias de rig (se dibujan como overlay en el editor, no se exportan).
"""

from __future__ import annotations
import json
import math
import os
import pygame

from . import model


def ensure_layers(sprite, default_size=(64, 128)):
    """Garantiza que el sprite tenga al menos una capa raster editable.
    Si trae image_path (import o proyecto v2) la carga como capa 'base';
    si no, crea un lienzo transparente del tamano dado."""
    if sprite.layers:
        return
    surf = None
    if sprite.image_path and os.path.isfile(sprite.image_path):
        try:
            surf = pygame.image.load(sprite.image_path).convert_alpha()
        except pygame.error:
            surf = None
    if surf is None:
        w, h = default_size
        surf = pygame.Surface((w, h), pygame.SRCALPHA)
    sprite.layers = [model.Layer("base", surf)]
    sprite.active_layer = 0


def flatten_sprite(sprite, recompute_bbox=True):
    """Compone las capas visibles en sprite.surface y recomputa content_rect.

    Optimizado para lienzos grandes:
    - una sola capa visible a opacidad plena -> se COMPARTE su surface (sin
      copiar ni blittear 1.7M px por trazo);
    - recompute_bbox=False salta el get_bounding_rect (escaneo de toda la hoja),
      que en un trazo continuo se difiere hasta soltar el mouse.
    """
    if not sprite.layers or sprite.layers[0].surface is None:
        sprite.surface = None
        sprite.size = (0, 0)
        sprite.content_rect = None
        return
    w, h = sprite.layers[0].surface.get_size()
    vis = [l for l in sprite.layers if l.visible and l.surface is not None]
    if len(vis) == 1 and vis[0].opacity >= 0.999:
        sprite.surface = vis[0].surface          # comparte: rapido (sin copia)
    else:
        comp = pygame.Surface((w, h), pygame.SRCALPHA)
        for lay in vis:
            s = lay.surface
            if lay.opacity < 0.999:
                s = lay.surface.copy()
                a = max(0, min(255, int(255 * lay.opacity)))
                s.fill((255, 255, 255, a), special_flags=pygame.BLEND_RGBA_MULT)
            comp.blit(s, (0, 0))
        sprite.surface = comp
    sprite.size = (w, h)
    if recompute_bbox or sprite.content_rect is None:
        bb = sprite.surface.get_bounding_rect(min_alpha=1)
        if bb.width == 0 or bb.height == 0:
            bb = sprite.surface.get_rect()
        sprite.content_rect = (bb.x, bb.y, bb.width, bb.height)


def load_sprite_surface(sprite, default_size=(64, 128)):
    ensure_layers(sprite, default_size)
    flatten_sprite(sprite)


def ensure_surfaces(project):
    ds = (project.tile_w, project.tile_h)
    for s in project.sprites:
        if s.surface is None:
            load_sprite_surface(s, ds)
    for s in getattr(project, "drawings", []):
        if s.surface is None:
            load_sprite_surface(s, ds)


def blit_rotate(dest, image, screen_pos, pivot, angle_deg, scale=1.0):
    """Dibuja image con su pivot sobre screen_pos, rotada angle_deg (horario)
    y escalada. Devuelve el rect."""
    px, py = pivot
    if scale != 1.0:
        w = max(1, int(round(image.get_width() * scale)))
        h = max(1, int(round(image.get_height() * scale)))
        image = pygame.transform.scale(image, (w, h))
        px, py = px * scale, py * scale
    rotated = pygame.transform.rotate(image, -angle_deg)
    iw, ih = image.get_size()
    cx, cy = iw / 2.0, ih / 2.0
    ox, oy = px - cx, py - cy
    a = math.radians(angle_deg)
    c, s = math.cos(a), math.sin(a)
    rox = ox * c - oy * s
    roy = ox * s + oy * c
    center = (screen_pos[0] - rox, screen_pos[1] - roy)
    rect = rotated.get_rect(center=center)
    dest.blit(rotated, rect)
    return rect


def draw_sprites(dest, project, frame, world_to_screen, zoom=1.0,
                 only_visible=True, sprites_filter=None):
    pose_for = model.pose_for_frame(project, frame)
    # la visibilidad por frame es LIBRE: la decide frame.hidden (lo que el usuario
    # eligio mostrar en ESE frame). El frame de reposo codifica el visible global.
    hidden = getattr(frame, "hidden", None)
    for idx in project.sprite_draw_order():
        if sprites_filter is not None and idx not in sprites_filter:
            continue
        sp = project.sprites[idx]
        if sp.surface is None:
            continue
        if hidden and sp.name in hidden:         # oculto en ESTE frame
            continue
        if hidden is None and only_visible and not sp.visible:
            continue                              # sin frame: visible global
        wx, wy, wrot, wscale = model.sprite_world(project, sp, pose_for)
        sx, sy = world_to_screen(wx, wy)
        blit_rotate(dest, sp.surface, (sx, sy), sp.pivot, wrot,
                    scale=wscale * zoom)


def clip_box(project, clip):
    """Recuadro de exportacion (bx, by, w, h) de un clip. Si el clip tiene
    esquina propia (box_x/box_y, p.ej. tras 'Ajustar al contenido') se usa esa;
    si no, se centra en el mismo centro que el recuadro del proyecto."""
    pw, ph = project.tile_w, project.tile_h
    cw = getattr(clip, "tile_w", None) or pw
    ch = getattr(clip, "tile_h", None) or ph
    bx = getattr(clip, "box_x", None)
    by = getattr(clip, "box_y", None)
    if bx is not None and by is not None:
        return (bx, by, cw, ch)
    cx = project.box_x + pw / 2.0
    cy = project.box_y + ph / 2.0
    return (cx - cw / 2.0, cy - ch / 2.0, cw, ch)


def render_tile(project, frame, sprites_filter=None, box=None):
    if box is None:
        box = (project.box_x, project.box_y, project.tile_w, project.tile_h)
    bx, by, w, h = box
    tile = pygame.Surface((max(1, int(round(w))), max(1, int(round(h)))),
                          pygame.SRCALPHA)
    draw_sprites(tile, project, frame, lambda x, y: (x - bx, y - by),
                 zoom=1.0, sprites_filter=sprites_filter)
    return tile


def content_box(project, sprites_filter=None, margin=1):
    """bbox en mundo (bx, by, w, h) que envuelve el contenido de los sprites
    dados a lo largo de TODOS los frames de TODOS los clips. Sirve para exportar
    un material RECORTADO a su tamano real (no al tile del cuerpo). None si vacio.
    """
    sprites = [(i, s) for i, s in enumerate(project.sprites)
               if s.visible and s.surface is not None and s.content_rect
               and (sprites_filter is None or i in sprites_filter)]
    if not sprites:
        return None
    minx = miny = 1e9
    maxx = maxy = -1e9
    clips = project.clips or [model.Clip("animacion")]
    for c in clips:
        frames = c.frames or [None]
        for f in frames:
            pose_for = model.pose_for_frame(project, f)
            for _, sp in sprites:
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
    bx, by = math.floor(minx - margin), math.floor(miny - margin)
    return (bx, by, int(math.ceil(maxx + margin)) - bx,
            int(math.ceil(maxy + margin)) - by)


def part_connection(project):
    """Socket al que se pega el material exportado (el primer sprite con conexion)."""
    for s in project.sprites:
        if getattr(s, "connection", None):
            return s.connection
    return None


def pack_clips_sheet(project, sprites_filter=None, box_override=None):
    """Hoja unica con UNA FILA POR ANIMACION (clip). Cada fila usa el tamano de
    frame de su clip (puede ser mas ancho/alto). El ancho de la hoja lo fija la
    fila mas larga; el alto es la suma de los altos de cada fila. Si box_override
    se da, TODAS las filas usan ese recuadro (export recortado del material)."""
    clips = project.clips or [model.Clip("animacion")]
    rows = []
    total_h, max_w = 0, 0
    for c in clips:
        bx, by, cw, ch = box_override if box_override else clip_box(project, c)
        nf = max(1, len(c.frames))
        rows.append((c, bx, by, cw, ch))
        total_h += int(round(ch))
        max_w = max(max_w, nf * int(round(cw)))
    sheet = pygame.Surface((max(1, max_w), max(1, total_h)), pygame.SRCALPHA)
    y = 0
    for c, bx, by, cw, ch in rows:
        cw_i, ch_i = int(round(cw)), int(round(ch))
        frames = c.frames if c.frames else [None]
        for i, f in enumerate(frames):
            tile = render_tile(project, f, sprites_filter, (bx, by, cw, ch))
            sheet.blit(tile, (i * cw_i, y))
        y += ch_i
    return sheet


def build_meta(project, box_override=None, connection=None, conn_offset=None):
    """Metadata de la hoja para el juego (sidecar JSON).

    Incluye, por animacion (fila) y por frame, el transform de los huesos
    marcados como ANCLA (mano, ojos, pelo...) en pixeles del tile: posicion del
    nodo (x,y), angulo en grados (ang, horario), escala, y la punta (tx,ty). El
    juego coloca cualquier item/material en ese transform -> se siente pegado.

    box_override recorta todas las filas a ese recuadro (export de material).
    connection (socket id) marca a que punto del cuerpo se pega ESTE material
    por su centro -> el juego lo ubica solo.
    """
    anchors = [(i, b) for i, b in enumerate(project.bones)
               if getattr(b, "anchor", False)]
    fw = box_override[2] if box_override else project.tile_w
    fh = box_override[3] if box_override else project.tile_h
    meta = {"frame_w": fw, "frame_h": fh, "rows": []}
    if connection:
        meta["connection"] = {"socket": connection, "pivot": "center"}
        # offset (px) del CENTRO dibujado respecto al socket: el juego coloca la
        # pieza DONDE se dibujo (WYSIWYG) y la hace seguir al hueso por frame.
        if conn_offset:
            meta["connection"]["offset"] = [round(conn_offset[0], 2),
                                            round(conn_offset[1], 2)]
    for c in (project.clips or []):
        bx, by, cw, ch = box_override if box_override else clip_box(project, c)
        frames = c.frames or [None]
        row = {"name": c.name, "frames": max(1, len(c.frames)),
               "frame_w": int(round(cw)), "frame_h": int(round(ch)),
               "origin": [round(-bx, 2), round(-by, 2)],   # mundo (0,0) en el frame
               "duration": round(c.duration, 3), "fps": round(c.fps, 2)}
        if anchors:
            row["anchors"] = {}
            for i, b in anchors:
                seq = []
                for f in frames:
                    pose_for = model.pose_for_frame(project, f)
                    wx, wy, wrot, wsc = model.bone_world(project, i, pose_for)
                    tx, ty = model.bone_tip(project, i, (wx, wy, wrot, wsc))
                    seq.append({"x": round(wx - bx, 2), "y": round(wy - by, 2),
                                "ang": round(wrot, 2), "scale": round(wsc, 3),
                                "tx": round(tx - bx, 2), "ty": round(ty - by, 2)})
                row["anchors"][b.name] = seq
        meta["rows"].append(row)
    return meta


def export_meta(project, path, box_override=None, connection=None,
                conn_offset=None):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(build_meta(project, box_override, connection, conn_offset),
                  fh, indent=2, ensure_ascii=False)
    return path


def export_composite(project, out_path, box_override=None, sprites_filter=None):
    sheet = pack_clips_sheet(project, sprites_filter=sprites_filter,
                             box_override=box_override)
    pygame.image.save(sheet, out_path)
    return sheet.get_size()


def export_part(project, png_path, margin=1):
    """Exporta el material RECORTADO a su tamano real + su .json con la conexion.
    Pensado para capas (ojos, pelo, boca...) que se pegan a un socket del cuerpo:
    el juego centra este PNG en el punto de conexion, sin redibujarlo grande."""
    box = content_box(project, margin=margin)
    conn = part_connection(project)
    sheet = pack_clips_sheet(project, box_override=box)
    pygame.image.save(sheet, png_path)
    meta_path = os.path.splitext(png_path)[0] + ".json"
    export_meta(project, meta_path, box_override=box, connection=conn)
    return sheet.get_size(), conn


def export_per_layer(project, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    written = []
    for idx, sp in enumerate(project.sprites):
        if sp.surface is None:
            continue
        sheet = pack_clips_sheet(project, sprites_filter={idx})
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_"
                       for ch in sp.name)
        path = os.path.join(out_dir, f"{safe}.png")
        pygame.image.save(sheet, path)
        written.append(path)
    return written
