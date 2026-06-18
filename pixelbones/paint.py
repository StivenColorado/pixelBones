"""Motor de pintura raster para el modo Pintar de PixelBones.

Opera en coordenadas de pixel locales de una capa (pygame.Surface SRCALPHA).
No conoce la escena ni los huesos: recibe superficies y coordenadas enteras.
La seleccion (vara magica) es una pygame.mask.Mask del tamano del lienzo;
cuando esta presente, las operaciones se restringen a sus pixeles.
"""
from __future__ import annotations
import colorsys
import pygame


# Paleta amplia (estilo pixel-art): grises + 6 matices x 4 tonos + pieles.
DEFAULT_PALETTE = [
    (0, 0, 0, 255), (40, 42, 50, 255), (74, 78, 90, 255), (110, 116, 130, 255),
    (150, 156, 168, 255), (190, 196, 206, 255), (224, 228, 236, 255), (255, 255, 255, 255),
    (120, 36, 40, 255), (190, 60, 60, 255), (228, 100, 90, 255), (250, 160, 150, 255),
    (150, 80, 30, 255), (210, 130, 55, 255), (240, 175, 80, 255), (250, 215, 130, 255),
    (70, 110, 40, 255), (110, 165, 60, 255), (150, 205, 95, 255), (200, 235, 150, 255),
    (30, 90, 110, 255), (45, 140, 165, 255), (95, 190, 205, 255), (165, 225, 235, 255),
    (40, 60, 130, 255), (60, 95, 195, 255), (95, 140, 230, 255), (160, 195, 245, 255),
    (90, 50, 120, 255), (135, 80, 175, 255), (180, 120, 210, 255), (220, 175, 235, 255),
    (210, 120, 165, 255), (245, 170, 200, 255), (90, 60, 44, 255), (140, 100, 70, 255),
    (190, 150, 110, 255), (235, 200, 165, 255), (255, 225, 195, 255), (60, 44, 36, 255),
]


class PaintState:
    def __init__(self):
        self.tool = "pencil"
        self.color = (34, 35, 40, 255)
        self.color2 = (255, 255, 255, 255)
        self.brush = 1
        self.tolerance = 0
        self.shade_amount = 0.18
        self.shade_lighten = False
        self.palette = list(DEFAULT_PALETTE)
        self.sel_mask = None            # pygame.mask.Mask | None
        self.hue = 0.62                 # estado del picker HSV (fuente de verdad)
        self.sat = 0.15
        self.val = 0.16


# --------------------------------------------------------------------------- util
def _in_sel(sel, x, y):
    if sel is None:
        return True
    try:
        return bool(sel.get_at((x, y)))
    except IndexError:
        return False


def _bresenham(x0, y0, x1, y1):
    pts = []
    dx = abs(x1 - x0)
    dy = -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    while True:
        pts.append((x0, y0))
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy
    return pts


def _match(c, target, tol):
    return (abs(c[0] - target[0]) + abs(c[1] - target[1])
            + abs(c[2] - target[2]) + abs(c[3] - target[3])) <= tol * 4


def bezier_point(p0, p1, p2, t):
    mt = 1 - t
    x = mt * mt * p0[0] + 2 * mt * t * p1[0] + t * t * p2[0]
    y = mt * mt * p0[1] + 2 * mt * t * p1[1] + t * t * p2[1]
    return (x, y)


# --------------------------------------------------------------------------- trazo
def stamp(surf, x, y, rgba, brush, sel=None):
    w, h = surf.get_size()
    r = brush // 2
    surf.lock()
    try:
        for yy in range(y - r, y - r + brush):
            if yy < 0 or yy >= h:
                continue
            for xx in range(x - r, x - r + brush):
                if 0 <= xx < w and _in_sel(sel, xx, yy):
                    surf.set_at((xx, yy), rgba)
    finally:
        surf.unlock()


def line(surf, x0, y0, x1, y1, rgba, brush, sel=None):
    for px, py in _bresenham(x0, y0, x1, y1):
        stamp(surf, px, py, rgba, brush, sel)


def curve(surf, p0, ctrl, p2, rgba, brush, sel=None):
    pts = [bezier_point(p0, ctrl, p2, t / 24.0) for t in range(25)]
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        line(surf, int(round(a[0])), int(round(a[1])),
             int(round(b[0])), int(round(b[1])), rgba, brush, sel)


def bspline_points(points, per_seg=18):
    """Curva B-spline cubica uniforme sobre puntos de control (estilo CorelDRAW:
    la curva es suave y se aproxima a los puntos). Duplica los extremos para
    que arranque/termine cerca del primer/ultimo punto."""
    n = len(points)
    if n == 0:
        return []
    if n <= 2:
        return list(points)
    # triplicar extremos -> la curva queda anclada al primer y ultimo nodo
    pts = [points[0], points[0]] + list(points) + [points[-1], points[-1]]
    out = []
    for i in range(len(pts) - 3):
        p0, p1, p2, p3 = pts[i], pts[i + 1], pts[i + 2], pts[i + 3]
        for s in range(per_seg + 1):
            t = s / per_seg
            t2, t3 = t * t, t * t * t
            b0 = (-t3 + 3 * t2 - 3 * t + 1) / 6.0
            b1 = (3 * t3 - 6 * t2 + 4) / 6.0
            b2 = (-3 * t3 + 3 * t2 + 3 * t + 1) / 6.0
            b3 = t3 / 6.0
            out.append((b0 * p0[0] + b1 * p1[0] + b2 * p2[0] + b3 * p3[0],
                        b0 * p0[1] + b1 * p1[1] + b2 * p2[1] + b3 * p3[1]))
    return out


def spline(surf, points, rgba, brush, sel=None):
    sp = bspline_points(points)
    for i in range(len(sp) - 1):
        a, b = sp[i], sp[i + 1]
        line(surf, int(round(a[0])), int(round(a[1])),
             int(round(b[0])), int(round(b[1])), rgba, brush, sel)


# --------------------------------------------------------------------------- color
def pick(surf, x, y, composite=None):
    src = composite if composite is not None else surf
    w, h = src.get_size()
    if 0 <= x < w and 0 <= y < h:
        c = src.get_at((x, y))
        return (c.r, c.g, c.b, c.a)
    return None


def shade(surf, x, y, brush, amount, lighten, sel=None):
    """Mezcla negro translucido (sombra) o blanco translucido (brillo) SOLO
    sobre pixeles ya pintados, conservando su alpha. Acumula al pasar varias
    veces, como una capa de sombra negra transparente."""
    w, h = surf.get_size()
    r = brush // 2
    a = max(0.0, min(1.0, amount))
    ov = 255 if lighten else 0
    surf.lock()
    try:
        for yy in range(y - r, y - r + brush):
            if yy < 0 or yy >= h:
                continue
            for xx in range(x - r, x - r + brush):
                if not (0 <= xx < w) or not _in_sel(sel, xx, yy):
                    continue
                c = surf.get_at((xx, yy))
                if c.a == 0:
                    continue
                nr = int(c.r * (1 - a) + ov * a)
                ng = int(c.g * (1 - a) + ov * a)
                nb = int(c.b * (1 - a) + ov * a)
                surf.set_at((xx, yy), (nr, ng, nb, c.a))
    finally:
        surf.unlock()


def shade_line(surf, x0, y0, x1, y1, brush, amount, lighten, sel=None):
    for px, py in _bresenham(x0, y0, x1, y1):
        shade(surf, px, py, brush, amount, lighten, sel)


# --------------------------------------------------------------------------- relleno
def bucket(surf, x, y, rgba, sel=None, tol=0):
    w, h = surf.get_size()
    if not (0 <= x < w and 0 <= y < h) or not _in_sel(sel, x, y):
        return
    c0 = surf.get_at((x, y))
    start = (c0.r, c0.g, c0.b, c0.a)
    stack = [(x, y)]
    seen = set()
    surf.lock()
    try:
        while stack:
            cx, cy = stack.pop()
            if (cx, cy) in seen:
                continue
            seen.add((cx, cy))
            if not (0 <= cx < w and 0 <= cy < h) or not _in_sel(sel, cx, cy):
                continue
            c = surf.get_at((cx, cy))
            if not _match((c.r, c.g, c.b, c.a), start, tol):
                continue
            surf.set_at((cx, cy), rgba)
            stack.extend([(cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)])
    finally:
        surf.unlock()


# --------------------------------------------------------------------------- seleccion
def magic_select(surf, x, y, tol=0):
    """Region de color contigua a (x,y), como pygame.mask.Mask."""
    w, h = surf.get_size()
    mask = pygame.mask.Mask((w, h))
    if not (0 <= x < w and 0 <= y < h):
        return mask
    c0 = surf.get_at((x, y))
    start = (c0.r, c0.g, c0.b, c0.a)
    stack = [(x, y)]
    seen = set()
    while stack:
        cx, cy = stack.pop()
        if (cx, cy) in seen:
            continue
        seen.add((cx, cy))
        if not (0 <= cx < w and 0 <= cy < h):
            continue
        c = surf.get_at((cx, cy))
        if not _match((c.r, c.g, c.b, c.a), start, tol):
            continue
        mask.set_at((cx, cy), 1)
        stack.extend([(cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)])
    return mask


def clear_selection(surf, sel=None):
    """Borra (a transparente) los pixeles seleccionados, o todo si sel es None."""
    if sel is None:
        surf.fill((0, 0, 0, 0))
        return
    w, h = surf.get_size()
    surf.lock()
    try:
        for yy in range(h):
            for xx in range(w):
                if sel.get_at((xx, yy)):
                    surf.set_at((xx, yy), (0, 0, 0, 0))
    finally:
        surf.unlock()
