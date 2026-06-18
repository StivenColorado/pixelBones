"""Render y exportacion con pygame. Solo los SPRITES se dibujan/exportan; los
huesos son guias de rig (se dibujan como overlay en el editor, no se exportan).
"""

from __future__ import annotations
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


def flatten_sprite(sprite):
    """Compone las capas visibles en sprite.surface y recomputa content_rect."""
    if not sprite.layers or sprite.layers[0].surface is None:
        sprite.surface = None
        sprite.size = (0, 0)
        sprite.content_rect = None
        return
    w, h = sprite.layers[0].surface.get_size()
    comp = pygame.Surface((w, h), pygame.SRCALPHA)
    for lay in sprite.layers:
        if not lay.visible or lay.surface is None:
            continue
        s = lay.surface
        if lay.opacity < 0.999:
            s = lay.surface.copy()
            a = max(0, min(255, int(255 * lay.opacity)))
            s.fill((255, 255, 255, a), special_flags=pygame.BLEND_RGBA_MULT)
        comp.blit(s, (0, 0))
    sprite.surface = comp
    sprite.size = (w, h)
    bb = comp.get_bounding_rect(min_alpha=1)
    if bb.width == 0 or bb.height == 0:
        bb = comp.get_rect()
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
    for idx in project.sprite_draw_order():
        if sprites_filter is not None and idx not in sprites_filter:
            continue
        sp = project.sprites[idx]
        if (only_visible and not sp.visible) or sp.surface is None:
            continue
        wx, wy, wrot, wscale = model.sprite_world(project, sp, pose_for)
        sx, sy = world_to_screen(wx, wy)
        blit_rotate(dest, sp.surface, (sx, sy), sp.pivot, wrot,
                    scale=wscale * zoom)


def render_tile(project, frame, sprites_filter=None):
    tile = pygame.Surface((project.tile_w, project.tile_h), pygame.SRCALPHA)
    bx, by = project.box_x, project.box_y
    draw_sprites(tile, project, frame, lambda x, y: (x - bx, y - by),
                 zoom=1.0, sprites_filter=sprites_filter)
    return tile


def pack_sheet(tiles, columns=0):
    if not tiles:
        return pygame.Surface((1, 1), pygame.SRCALPHA)
    tw, th = tiles[0].get_size()
    n = len(tiles)
    if columns <= 0:
        cols, rows = n, 1
    else:
        cols = columns
        rows = (n + cols - 1) // cols
    sheet = pygame.Surface((cols * tw, rows * th), pygame.SRCALPHA)
    for i, t in enumerate(tiles):
        sheet.blit(t, ((i % cols) * tw, (i // cols) * th))
    return sheet


def export_composite(project, out_path, columns=0):
    frames = project.frames or [None]
    tiles = [render_tile(project, f) for f in frames]
    sheet = pack_sheet(tiles, columns)
    pygame.image.save(sheet, out_path)
    return sheet.get_size()


def export_per_layer(project, out_dir, columns=0):
    os.makedirs(out_dir, exist_ok=True)
    written = []
    frames = project.frames or [None]
    for idx, sp in enumerate(project.sprites):
        if sp.surface is None:
            continue
        tiles = [render_tile(project, f, sprites_filter={idx}) for f in frames]
        sheet = pack_sheet(tiles, columns)
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_"
                       for ch in sp.name)
        path = os.path.join(out_dir, f"{safe}.png")
        pygame.image.save(sheet, path)
        written.append(path)
    return written
