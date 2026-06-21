"""Modelo de datos y matematica (sin pygame). v2.

Conceptos separados (estilo PixelOver):
- Sprite: una imagen colocada libremente en el lienzo. Tiene su propio
  transform y un punto de anclaje (pivot). Puede estar VINCULADA a un hueso,
  en cuyo caso sigue al hueso mediante un offset local.
- Bone (hueso): un nodo del esqueleto con cabeza (origen), longitud y
  orientacion. Jerarquia padre->hijo (FK). Se anima por frames.
- Frame: captura de las poses locales de los HUESOS (por nombre).

Coordenadas: espacio mundo en pixeles, Y hacia abajo. Rotacion positiva =
horaria en pantalla.
"""

from __future__ import annotations
import base64
import json
import math
import os
import zlib

import pygame


# Puntos de conexion (sockets) reservados. SOLO para piezas RIGIDAS que el juego
# coloca por su CENTRO sobre un punto (rasgos de la cara y objetos en la mano):
# cada material declara a cual se pega -> el juego lo ubica solo, pequeno.
# La ROPA NO usa sockets: se VINCULA a huesos (Sigue al hueso) y se hornea en la
# hoja como overlay, asi las mangas/perneras siguen el mismo movimiento del rig.
SOCKETS = ["mano_izq", "mano_der", "ojos", "pelo", "nariz", "boca",
           "pierna_izq", "pierna_der", "zapato_izq", "zapato_der"]

SOCKET_LABELS = {
    "mano_izq": "Mano izq", "mano_der": "Mano der", "ojos": "Ojos",
    "pelo": "Pelo", "nariz": "Nariz", "boca": "Boca",
    "pierna_izq": "Pierna izq", "pierna_der": "Pierna der",
    "zapato_izq": "Zapato izq", "zapato_der": "Zapato der",
}

# Huesos sugeridos del esqueleto humanoide (para vincular cuerpo y ropa). No son
# sockets: son el rig al que se enganchan las piezas con "Sigue al hueso".
SKELETON_BONES = ["cadera", "torso", "cabeza", "brazo_izq", "brazo_der",
                  "mano_izq_h", "mano_der_h", "pierna_izq", "pierna_der",
                  "pie_izq", "pie_der"]


def default_pose():
    return {"x": 0.0, "y": 0.0, "rot": 0.0, "scale": 1.0}


def clone_pose(p):
    return {"x": float(p["x"]), "y": float(p["y"]),
            "rot": float(p["rot"]), "scale": float(p.get("scale", 1.0))}


def _rot(x, y, deg):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return (x * c - y * s, x * s + y * c)


# ---------------------------------------------------------------------------
# Codec de pixeles (capas): RGBA crudo comprimido (zlib) en base64.
# Mantiene el .pbproj autocontenido y portable.
# ---------------------------------------------------------------------------
_to_bytes = getattr(pygame.image, "tobytes", None) or pygame.image.tostring
_from_bytes = getattr(pygame.image, "frombytes", None) or pygame.image.fromstring


def encode_surface(surf):
    w, h = surf.get_size()
    raw = _to_bytes(surf, "RGBA")
    return {"w": w, "h": h,
            "pix": base64.b64encode(zlib.compress(raw, 6)).decode("ascii")}


def decode_surface(d):
    w, h, pix = d.get("w", 0), d.get("h", 0), d.get("pix")
    if not (pix and w and h):
        return None
    raw = zlib.decompress(base64.b64decode(pix))
    surf = _from_bytes(raw, (w, h), "RGBA")
    if pygame.display.get_init():
        surf = surf.convert_alpha()
    return surf


# ---------------------------------------------------------------------------
# Layer (capa raster de un sprite, estilo Pixelorama)
# ---------------------------------------------------------------------------
class Layer:
    def __init__(self, name="capa", surface=None, visible=True, opacity=1.0):
        self.name = name
        self.visible = visible
        self.opacity = float(opacity)
        self.surface = surface          # pygame.Surface SRCALPHA

    def clone(self):
        c = Layer(self.name, None, self.visible, self.opacity)
        if self.surface is not None:
            c.surface = self.surface.copy()
        return c

    def to_dict(self):
        d = {"name": self.name, "visible": self.visible, "opacity": self.opacity}
        if self.surface is not None:
            d.update(encode_surface(self.surface))
        return d

    @classmethod
    def from_dict(cls, d):
        return cls(d.get("name", "capa"), decode_surface(d),
                   d.get("visible", True), d.get("opacity", 1.0))


# ---------------------------------------------------------------------------
# Sprite (imagen)
# ---------------------------------------------------------------------------
class Sprite:
    def __init__(self, name, image_path=None):
        self.name = name
        self.image_path = image_path
        self.pivot = [0.0, 0.0]            # anclaje en px de la imagen
        self.transform = default_pose()    # colocacion libre (pivot en mundo)
        self.bone = None                   # nombre de hueso vinculado | None
        self.local = default_pose()        # offset relativo al hueso (si bone)
        self.connection = None             # socket al que se PEGA (centro) | None
        self.z = 0
        self.visible = True
        self.layers = []               # list[Layer]; vacia => se crea al cargar
        self.active_layer = 0
        # runtime (no se serializa)
        self.surface = None            # composicion de las capas visibles
        self.size = (0, 0)
        self.content_rect = None       # bbox de pixeles no transparentes

    def to_dict(self):
        return {"name": self.name, "image_path": self.image_path,
                "pivot": list(self.pivot), "transform": clone_pose(self.transform),
                "bone": self.bone, "local": clone_pose(self.local),
                "connection": self.connection,
                "z": self.z, "visible": self.visible,
                "layers": [l.to_dict() for l in self.layers],
                "active_layer": self.active_layer}

    @classmethod
    def from_dict(cls, d):
        s = cls(d["name"], d.get("image_path"))
        s.pivot = list(d.get("pivot", [0.0, 0.0]))
        s.transform = clone_pose(d.get("transform", default_pose()))
        s.bone = d.get("bone")
        s.local = clone_pose(d.get("local", default_pose()))
        s.connection = d.get("connection")
        s.z = d.get("z", 0)
        s.visible = d.get("visible", True)
        s.layers = [Layer.from_dict(ld) for ld in d.get("layers", [])]
        s.active_layer = d.get("active_layer", 0)
        return s


# ---------------------------------------------------------------------------
# Bone (hueso)
# ---------------------------------------------------------------------------
class Bone:
    def __init__(self, name):
        self.name = name
        self.parent = -1                   # indice en project.bones | -1
        self.rest = default_pose()         # pose local en reposo
        self.length = 30.0                 # longitud (para dibujar el cilindro)
        self.anchor = False                # punto de anclaje de items (mano, etc.)

    def to_dict(self):
        return {"name": self.name, "parent": self.parent,
                "rest": clone_pose(self.rest), "length": self.length,
                "anchor": self.anchor}

    @classmethod
    def from_dict(cls, d):
        b = cls(d["name"])
        b.parent = d.get("parent", -1)
        b.rest = clone_pose(d.get("rest", default_pose()))
        b.length = d.get("length", 30.0)
        b.anchor = d.get("anchor", False)
        return b


# ---------------------------------------------------------------------------
# Frame
# ---------------------------------------------------------------------------
class Frame:
    def __init__(self, name="frame"):
        self.name = name
        self.poses = {}                    # bone_name -> pose

    def to_dict(self):
        return {"name": self.name,
                "poses": {k: clone_pose(v) for k, v in self.poses.items()}}

    @classmethod
    def from_dict(cls, d):
        f = cls(d.get("name", "frame"))
        f.poses = {k: clone_pose(v) for k, v in d.get("poses", {}).items()}
        return f


# ---------------------------------------------------------------------------
# Clip (animacion con nombre = una FILA de la hoja exportada)
# ---------------------------------------------------------------------------
class Clip:
    def __init__(self, name="animacion", duration=1.0):
        self.name = name
        self.frames = []                   # [Frame]
        self.duration = float(duration)    # segundos que dura la animacion
        self.tile_w = None                 # ancho de frame propio (None = proyecto)
        self.tile_h = None                 # alto de frame propio (None = proyecto)
        self.box_x = None                  # esquina del recuadro (None = centrado)
        self.box_y = None

    @property
    def fps(self):
        return (len(self.frames) / self.duration) if self.duration > 0 else 0.0

    def to_dict(self):
        d = {"name": self.name, "duration": self.duration,
             "frames": [f.to_dict() for f in self.frames]}
        if self.tile_w:
            d["tile_w"] = self.tile_w
        if self.tile_h:
            d["tile_h"] = self.tile_h
        if self.box_x is not None:
            d["box_x"] = self.box_x
        if self.box_y is not None:
            d["box_y"] = self.box_y
        return d

    @classmethod
    def from_dict(cls, d):
        c = cls(d.get("name", "animacion"), d.get("duration", 1.0))
        c.frames = [Frame.from_dict(x) for x in d.get("frames", [])]
        c.tile_w = d.get("tile_w")
        c.tile_h = d.get("tile_h")
        c.box_x = d.get("box_x")
        c.box_y = d.get("box_y")
        return c


# ---------------------------------------------------------------------------
# Project
# ---------------------------------------------------------------------------
class Project:
    def __init__(self):
        self.sprites = []
        self.bones = []
        self.clips = [Clip("animacion")]   # animaciones (filas de la hoja)
        self.drawings = []        # lienzos del modo Pintar (independientes)
        self.tile_w = 64
        self.tile_h = 128
        self.box_x = -32.0
        self.box_y = -120.0
        self.fps = 8
        self.path = None

    # -- utilidades ----------------------------------------------------------
    def bone_by_name(self, name):
        for i, b in enumerate(self.bones):
            if b.name == name:
                return i
        return -1

    def unique_sprite_name(self, base):
        names = {s.name for s in self.sprites}
        return self._unique(base, names)

    def unique_bone_name(self, base):
        names = {b.name for b in self.bones}
        return self._unique(base, names)

    @staticmethod
    def _unique(base, names):
        if base not in names:
            return base
        n = 1
        while f"{base}.{n}" in names:
            n += 1
        return f"{base}.{n}"

    def is_ancestor(self, anc, idx):
        cur = idx
        seen = set()
        while cur >= 0 and cur not in seen:
            seen.add(cur)
            if cur == anc:
                return True
            cur = self.bones[cur].parent
        return False

    def sprite_draw_order(self):
        return sorted(range(len(self.sprites)),
                      key=lambda i: (self.sprites[i].z, i))

    @property
    def box_rect(self):
        return (self.box_x, self.box_y, self.tile_w, self.tile_h)

    # -- IO ------------------------------------------------------------------
    def to_dict(self):
        return {
            "version": 4,
            "tile_w": self.tile_w, "tile_h": self.tile_h,
            "box_x": self.box_x, "box_y": self.box_y, "fps": self.fps,
            "sprites": [s.to_dict() for s in self.sprites],
            "bones": [b.to_dict() for b in self.bones],
            "clips": [c.to_dict() for c in self.clips],
            "drawings": [d.to_dict() for d in self.drawings],
        }

    @classmethod
    def from_dict(cls, d, base_dir=None):
        pr = cls()
        pr.tile_w = d.get("tile_w", 64)
        pr.tile_h = d.get("tile_h", 128)
        pr.box_x = d.get("box_x", -32.0)
        pr.box_y = d.get("box_y", -120.0)
        pr.fps = d.get("fps", 8)
        if "sprites" in d or "bones" in d:
            pr.sprites = [Sprite.from_dict(s) for s in d.get("sprites", [])]
            pr.bones = [Bone.from_dict(b) for b in d.get("bones", [])]
            if "clips" in d:
                pr.clips = [Clip.from_dict(c) for c in d["clips"]]
            else:                                 # v<=3: frames planos -> 1 clip
                c = Clip("animacion")
                c.frames = [Frame.from_dict(f) for f in d.get("frames", [])]
                if c.frames and pr.fps:           # conservar la velocidad anterior
                    c.duration = len(c.frames) / float(pr.fps)
                pr.clips = [c]
            pr.drawings = [Sprite.from_dict(s) for s in d.get("drawings", [])]
        elif "parts" in d:
            pr._migrate_v1(d)
        if not pr.clips:
            pr.clips = [Clip("animacion")]
        if base_dir:
            for s in pr.sprites:
                if s.image_path and not os.path.isabs(s.image_path):
                    s.image_path = os.path.normpath(
                        os.path.join(base_dir, s.image_path))
        return pr

    def _migrate_v1(self, d):
        """Convierte el formato v1 (parts = imagen+hueso) al v2."""
        for pd in d.get("parts", []):
            b = Bone(pd["name"])
            b.parent = pd.get("parent", -1)
            b.rest = clone_pose(pd.get("rest", default_pose()))
            self.bones.append(b)
            s = Sprite(pd["name"], pd.get("image_path"))
            s.pivot = list(pd.get("pivot", [0.0, 0.0]))
            s.bone = pd["name"]
            s.local = default_pose()
            s.z = pd.get("z", 0)
            s.visible = pd.get("visible", True)
            self.sprites.append(s)
        c = Clip("animacion")
        c.frames = [Frame.from_dict(f) for f in d.get("frames", [])]
        if c.frames and self.fps:
            c.duration = len(c.frames) / float(self.fps)
        self.clips = [c]

    def save(self, path):
        base = os.path.dirname(os.path.abspath(path))
        d = self.to_dict()
        for sd, s in zip(d["sprites"], self.sprites):
            if s.image_path:
                try:
                    sd["image_path"] = os.path.relpath(s.image_path, base)
                except ValueError:
                    sd["image_path"] = s.image_path
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(d, fh, indent=2, ensure_ascii=False)
        self.path = path

    @classmethod
    def load(cls, path):
        with open(path, "r", encoding="utf-8") as fh:
            d = json.load(fh)
        pr = cls.from_dict(d, base_dir=os.path.dirname(os.path.abspath(path)))
        pr.path = path
        return pr


# ---------------------------------------------------------------------------
# Transformaciones
# ---------------------------------------------------------------------------
def bone_world(project, idx, pose_for):
    """(x, y, rot, scale) en mundo del hueso idx. pose_for(i)->pose local."""
    b = project.bones[idx]
    p = pose_for(idx)
    lx, ly, lrot, lscale = p["x"], p["y"], p["rot"], p.get("scale", 1.0)
    if b.parent < 0:
        return (lx, ly, lrot, lscale)
    px, py, prot, pscale = bone_world(project, b.parent, pose_for)
    ox, oy = _rot(lx * pscale, ly * pscale, prot)
    return (px + ox, py + oy, prot + lrot, pscale * lscale)


def bone_tip(project, idx, world):
    """Punto (x,y) de la punta del hueso dado su world transform."""
    wx, wy, wrot, wscale = world
    ox, oy = _rot(project.bones[idx].length * wscale, 0, wrot)
    return (wx + ox, wy + oy)


def sprite_world(project, sprite, bone_pose_for):
    """(x, y, rot, scale) en mundo del pivot del sprite."""
    if not sprite.bone:
        t = sprite.transform
        return (t["x"], t["y"], t["rot"], t.get("scale", 1.0))
    bidx = project.bone_by_name(sprite.bone)
    if bidx < 0:
        t = sprite.transform
        return (t["x"], t["y"], t["rot"], t.get("scale", 1.0))
    bx, by, brot, bscale = bone_world(project, bidx, bone_pose_for)
    l = sprite.local
    ox, oy = _rot(l["x"] * bscale, l["y"] * bscale, brot)
    return (bx + ox, by + oy, brot + l["rot"], bscale * l.get("scale", 1.0))


def compute_local(bone_w, sprite_w):
    """Offset local de un sprite respecto a un hueso (para vincular sin salto)."""
    bx, by, brot, bscale = bone_w
    sx, sy, srot, sscale = sprite_w
    dx, dy = sx - bx, sy - by
    lx, ly = _rot(dx, dy, -brot)
    sc = bscale or 1e-6
    return {"x": lx / sc, "y": ly / sc, "rot": srot - brot,
            "scale": sscale / sc}


def world_to_image_point(wx, wy, wrot, wscale, pivot, point):
    dx, dy = point[0] - wx, point[1] - wy
    rx, ry = _rot(dx, dy, -wrot)
    wscale = wscale or 1e-6
    return (pivot[0] + rx / wscale, pivot[1] + ry / wscale)


def pose_for_frame(project, frame):
    def lookup(idx):
        b = project.bones[idx]
        if frame is not None and b.name in frame.poses:
            return frame.poses[b.name]
        return b.rest
    return lookup
