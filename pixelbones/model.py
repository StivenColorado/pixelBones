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
import json
import math
import os


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
        self.z = 0
        self.visible = True
        # runtime (no se serializa)
        self.surface = None
        self.size = (0, 0)
        self.content_rect = None       # bbox de pixeles no transparentes

    def to_dict(self):
        return {"name": self.name, "image_path": self.image_path,
                "pivot": list(self.pivot), "transform": clone_pose(self.transform),
                "bone": self.bone, "local": clone_pose(self.local),
                "z": self.z, "visible": self.visible}

    @classmethod
    def from_dict(cls, d):
        s = cls(d["name"], d.get("image_path"))
        s.pivot = list(d.get("pivot", [0.0, 0.0]))
        s.transform = clone_pose(d.get("transform", default_pose()))
        s.bone = d.get("bone")
        s.local = clone_pose(d.get("local", default_pose()))
        s.z = d.get("z", 0)
        s.visible = d.get("visible", True)
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

    def to_dict(self):
        return {"name": self.name, "parent": self.parent,
                "rest": clone_pose(self.rest), "length": self.length}

    @classmethod
    def from_dict(cls, d):
        b = cls(d["name"])
        b.parent = d.get("parent", -1)
        b.rest = clone_pose(d.get("rest", default_pose()))
        b.length = d.get("length", 30.0)
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
# Project
# ---------------------------------------------------------------------------
class Project:
    def __init__(self):
        self.sprites = []
        self.bones = []
        self.frames = []
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
            "version": 2,
            "tile_w": self.tile_w, "tile_h": self.tile_h,
            "box_x": self.box_x, "box_y": self.box_y, "fps": self.fps,
            "sprites": [s.to_dict() for s in self.sprites],
            "bones": [b.to_dict() for b in self.bones],
            "frames": [f.to_dict() for f in self.frames],
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
            pr.frames = [Frame.from_dict(f) for f in d.get("frames", [])]
        elif "parts" in d:
            pr._migrate_v1(d)
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
        self.frames = [Frame.from_dict(f) for f in d.get("frames", [])]

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
