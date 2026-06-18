"""Icono de PixelBones dibujado por codigo (un hueso). Se usa como icono de la
ventana en tiempo de ejecucion y para generar los archivos .png/.ico del
ejecutable (ver tools/make_icon.py)."""
from __future__ import annotations
import math
import pygame

BG = (40, 42, 50)
ACCENT = (240, 190, 90)
BONE = (236, 239, 246)
BONE_SH = (188, 196, 214)


def make_icon(size=256):
    s = pygame.Surface((size, size), pygame.SRCALPHA)
    r = int(size * 0.22)
    pygame.draw.rect(s, BG, (0, 0, size, size), border_radius=r)
    pygame.draw.rect(s, ACCENT, (0, 0, size, size),
                     max(2, int(size * 0.035)), border_radius=r)

    cx = cy = size / 2.0
    L = size * 0.26          # mitad del largo de la barra
    rad = size * 0.115       # radio de cada lobulo
    ang = math.radians(-35)  # hueso en diagonal
    dx, dy = math.cos(ang), math.sin(ang)
    nx, ny = -dy, dx
    e1 = (cx - dx * L, cy - dy * L)
    e2 = (cx + dx * L, cy + dy * L)

    # sombra sutil
    off = size * 0.02
    _bone(s, (e1[0] + off, e1[1] + off), (e2[0] + off, e2[1] + off),
          nx, ny, rad, BONE_SH)
    _bone(s, e1, e2, nx, ny, rad, BONE)
    return s


def _bone(s, e1, e2, nx, ny, rad, col):
    pygame.draw.line(s, col, e1, e2, int(rad * 1.5))
    for e in (e1, e2):
        for sgn in (1, -1):
            c = (e[0] + nx * rad * 0.78 * sgn, e[1] + ny * rad * 0.78 * sgn)
            pygame.draw.circle(s, col, (int(c[0]), int(c[1])), int(rad))
