"""PixelBones - editor de animacion por huesos para pixel art.

Modelo estilo PixelOver: las imagenes son SPRITES libres; los HUESOS se crean
aparte (cilindros con nodos) y los sprites se vinculan a ellos para animarse.

Dos herramientas:
- Seleccion (V): selecciona y mueve sprites; tambien posa huesos (rota/mueve).
- Hueso (B): crea huesos arrastrando desde un nodo de inicio.
"""

from __future__ import annotations
import math
import os
import pygame

from . import model, render, dialogs, recovery
from .history import History

# ---- tema -----------------------------------------------------------------
BG        = (32, 34, 40)
CANVAS_BG = (44, 47, 56)
PANEL     = (40, 42, 50)
PANEL2    = (54, 57, 68)
HOVER     = (70, 74, 88)
ACTIVE    = (90, 120, 180)
ACCENT    = (240, 190, 90)
SELECT    = (250, 210, 120)
TEXT      = (225, 228, 235)
DIM       = (150, 155, 165)
LINE      = (60, 63, 74)
BONE      = (110, 165, 225)
BONE_SEL  = (250, 210, 120)
GRID      = (52, 55, 64)

TOP_H   = 36
TIME_H  = 132
LEFT_W  = 212
RIGHT_W = 256


class App:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption("PixelBones")
        # tamano inicial que quepa en el escritorio (evita el resize forzado)
        try:
            dw, dh = pygame.display.get_desktop_sizes()[0]
        except Exception:
            dw, dh = 1320, 840
        win = (min(1320, dw - 60), min(840, dh - 90))
        self.screen = pygame.display.set_mode(win, pygame.RESIZABLE)
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("dejavusans,sans", 14)
        self.font_b = pygame.font.SysFont("dejavusans,sans", 14, bold=True)
        self.font_s = pygame.font.SysFont("dejavusans,sans", 12)

        self.project = model.Project()
        self.sel_kind = None          # "sprite" | "bone" | None
        self.sel_idx = -1
        self.cur_frame = -1
        self.working = {}             # bone_name -> pose

        self.tool = "select"          # select | bone
        self.show_bones = True
        self.show_help = False

        self.zoom = 3.0
        self.cam_x = self.project.box_x + self.project.tile_w / 2
        self.cam_y = self.project.box_y + self.project.tile_h / 2

        self.drag = None
        self.pan = None
        self.active_scrub = None
        self.scrub_x0 = 0
        self.scrub_v0 = 0.0

        self.playing = False
        self.play_t = 0.0
        self.play_i = 0

        self.export_cols = 0
        self.history = History()
        self.dirty = False
        self.editing = None           # ("rename_sprite"|"rename_bone", idx)
        self.edit_buf = ""
        self._caption = ""

        self.last_autosave = pygame.time.get_ticks()
        self.autosave_ms = 15000
        self.recovery_data = recovery.read() if recovery.exists() else None

        # input por frame
        self.mouse = (0, 0)
        self.prev_mouse = (0, 0)
        self.lmb_down = False
        self.lmb_held = False
        self.wheel = 0

        self._thumbs = []
        self._thumbs_dirty = True

        dialogs.set_host(self)
        self.status = ("Importa imagenes (boton 'Importar imagen' o arrastra "
                       "PNG). Herramienta Hueso (B) para crear huesos.")
        self.running = True

    # ====================================================================
    # ciclo principal
    # ====================================================================
    def run(self):
        while self.running:
            dt = self.clock.tick(60) / 1000.0
            self._poll_events()
            self._update_play(dt)
            self._handle_canvas()
            self._autosave_tick()
            self.update_caption()
            self._draw()
            self.prev_mouse = self.mouse
            pygame.display.flip()
        pygame.quit()

    def _poll_events(self):
        self.lmb_down = False
        self.wheel = 0
        dropped = []
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                self.running = False
            elif e.type == pygame.DROPFILE:
                dropped.append(e.file)
            elif e.type == pygame.VIDEORESIZE:
                self.screen = pygame.display.set_mode((e.w, e.h),
                                                      pygame.RESIZABLE)
            elif e.type == pygame.MOUSEBUTTONDOWN:
                if e.button == 1:
                    self.lmb_down = True
                elif e.button == 2:
                    self.pan = (e.pos, self.cam_x, self.cam_y)
            elif e.type == pygame.MOUSEBUTTONUP:
                if e.button == 2:
                    self.pan = None
            elif e.type == pygame.MOUSEWHEEL:
                self.wheel += e.y
            elif e.type == pygame.KEYDOWN:
                if self.editing is not None:
                    self._edit_key(e)
                else:
                    self._hotkey(e.key)
        self.mouse = pygame.mouse.get_pos()
        pressed = pygame.mouse.get_pressed()
        self.lmb_held = pressed[0]
        if dropped:
            self.import_dropped(dropped)
        self.layout()

    def _hotkey(self, key):
        mods = pygame.key.get_mods()
        ctrl = mods & pygame.KMOD_CTRL
        shift = mods & pygame.KMOD_SHIFT
        if ctrl:
            if key == pygame.K_s:
                self.save_project(as_new=bool(shift))
            elif key == pygame.K_o:
                self.open_project()
            elif key == pygame.K_n:
                self.new_project()
            elif key == pygame.K_e:
                self.export_composite()
            elif key == pygame.K_z:
                self.redo() if shift else self.undo()
            elif key == pygame.K_y:
                self.redo()
            return
        if key == pygame.K_v:
            self.tool = "select"
        elif key == pygame.K_b:
            self.tool = "bone"
        elif key == pygame.K_h or key == pygame.K_F1:
            self.show_help = not self.show_help
        elif key == pygame.K_k:
            self.capture_frame()
        elif key == pygame.K_SPACE:
            self.toggle_play()
        elif key == pygame.K_DELETE:
            self.delete_selected()
        elif key == pygame.K_F2:
            self.rename_selected()
        elif key == pygame.K_ESCAPE:
            self.sel_kind, self.sel_idx = None, -1

    # -- edicion de texto inline -----------------------------------------
    def rename_selected(self):
        if self.sel_kind == "sprite" and self.selected_sprite():
            self.editing = ("rename_sprite", self.sel_idx)
            self.edit_buf = self.selected_sprite().name
        elif self.sel_kind == "bone" and self.selected_bone():
            self.editing = ("rename_bone", self.sel_idx)
            self.edit_buf = self.selected_bone().name

    def _edit_key(self, e):
        if e.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self._commit_rename()
        elif e.key == pygame.K_ESCAPE:
            self.editing = None
        elif e.key == pygame.K_BACKSPACE:
            self.edit_buf = self.edit_buf[:-1]
        elif e.unicode and e.unicode.isprintable() and len(self.edit_buf) < 40:
            self.edit_buf += e.unicode

    def _commit_rename(self):
        kind, idx = self.editing
        new = self.edit_buf.strip()
        self.editing = None
        if not new:
            return
        if kind == "rename_sprite" and idx < len(self.project.sprites):
            old = self.project.sprites[idx].name
            if new == old:
                return
            self.snapshot()
            self.project.sprites[idx].name = self.project.unique_sprite_name(new)
        elif kind == "rename_bone" and idx < len(self.project.bones):
            old = self.project.bones[idx].name
            if new == old:
                return
            self.snapshot()
            new = self.project.unique_bone_name(new)
            self.project.bones[idx].name = new
            if old in self.working:
                self.working[new] = self.working.pop(old)
            for f in self.project.frames:
                if old in f.poses:
                    f.poses[new] = f.poses.pop(old)
            for s in self.project.sprites:
                if s.bone == old:
                    s.bone = new
        self._thumbs_dirty = True

    # ====================================================================
    # layout / camara
    # ====================================================================
    def layout(self):
        w, h = self.screen.get_size()
        self.r_top = pygame.Rect(0, 0, w, TOP_H)
        self.r_time = pygame.Rect(0, h - TIME_H, w, TIME_H)
        self.r_left = pygame.Rect(0, TOP_H, LEFT_W, h - TOP_H - TIME_H)
        self.r_right = pygame.Rect(w - RIGHT_W, TOP_H, RIGHT_W,
                                   h - TOP_H - TIME_H)
        self.r_canvas = pygame.Rect(LEFT_W, TOP_H, w - LEFT_W - RIGHT_W,
                                    h - TOP_H - TIME_H)

    def w2s(self, wx, wy):
        c = self.r_canvas
        return (c.centerx + (wx - self.cam_x) * self.zoom,
                c.centery + (wy - self.cam_y) * self.zoom)

    def s2w(self, sx, sy):
        c = self.r_canvas
        return (self.cam_x + (sx - c.centerx) / self.zoom,
                self.cam_y + (sy - c.centery) / self.zoom)

    # ====================================================================
    # seleccion / poses
    # ====================================================================
    def selected_sprite(self):
        if self.sel_kind == "sprite" and 0 <= self.sel_idx < len(self.project.sprites):
            return self.project.sprites[self.sel_idx]
        return None

    def selected_bone(self):
        if self.sel_kind == "bone" and 0 <= self.sel_idx < len(self.project.bones):
            return self.project.bones[self.sel_idx]
        return None

    def pose_for(self):
        def lookup(idx):
            name = self.project.bones[idx].name
            return self.working.get(name, self.project.bones[idx].rest)
        return lookup

    def display_frame(self):
        f = model.Frame("__work__")
        f.poses = self.working
        return f

    def active_frame(self):
        if self.playing and self.project.frames:
            return self.project.frames[self.play_i % len(self.project.frames)]
        return self.display_frame()

    def sync_working(self):
        self.working = {}
        for b in self.project.bones:
            if self.cur_frame >= 0:
                fr = self.project.frames[self.cur_frame]
                self.working[b.name] = model.clone_pose(fr.poses.get(b.name, b.rest))
            else:
                self.working[b.name] = model.clone_pose(b.rest)

    def _write_pose(self, bone_idx):
        name = self.project.bones[bone_idx].name
        pose = model.clone_pose(self.working[name])
        if self.cur_frame >= 0:
            self.project.frames[self.cur_frame].poses[name] = pose
            self._thumbs_dirty = True
        else:
            self.project.bones[bone_idx].rest = pose
        self.dirty = True

    # ====================================================================
    # historial / dirty / recuperacion / caption
    # ====================================================================
    def snapshot(self):
        self.history.push(self.project.to_dict())
        self.dirty = True

    def _restore(self, d):
        self.project = model.Project.from_dict(d)
        render.ensure_surfaces(self.project)
        self.sel_kind, self.sel_idx = None, -1
        self.cur_frame = min(self.cur_frame, len(self.project.frames) - 1)
        self.editing = None
        self.sync_working()
        self._thumbs_dirty = True
        self.dirty = True

    def undo(self):
        d = self.history.undo(self.project.to_dict())
        if d is not None:
            self._restore(d)
            self.status = "Deshacer."

    def redo(self):
        d = self.history.redo(self.project.to_dict())
        if d is not None:
            self._restore(d)
            self.status = "Rehacer."

    def _autosave_tick(self):
        now = pygame.time.get_ticks()
        if self.dirty and now - self.last_autosave > self.autosave_ms:
            recovery.write(self.project.to_dict(), self.project.path)
            self.last_autosave = now

    def accept_recovery(self):
        if not self.recovery_data:
            return
        try:
            self._restore(self.recovery_data["data"])
            self.project.path = self.recovery_data.get("source_path")
            self.history.clear()
            self.status = "Sesion recuperada."
        except Exception as e:
            self.status = f"No se pudo recuperar: {e}"
        self.recovery_data = None

    def discard_recovery(self):
        self.recovery_data = None
        recovery.clear()

    def update_caption(self):
        name = (os.path.basename(self.project.path) if self.project.path
                else "sin titulo")
        cap = f"PixelBones — {'*' if self.dirty else ''}{name}"
        if cap != self._caption:
            pygame.display.set_caption(cap)
            self._caption = cap

    # ====================================================================
    # sprites
    # ====================================================================
    def _add_sprite(self, path):
        base = os.path.splitext(os.path.basename(path))[0]
        sp = model.Sprite(self.project.unique_sprite_name(base), path)
        render.load_sprite_surface(sp)
        if sp.surface is None:
            self.status = f"No se pudo cargar {base}"
            return False
        w, h = sp.size
        # pivote en el centro del CONTENIDO (mascara), no del PNG completo
        if sp.content_rect:
            cx, cy, cw, ch = sp.content_rect
            sp.pivot = [cx + cw / 2.0, cy + ch / 2.0]
        else:
            sp.pivot = [w / 2.0, h / 2.0]
        sp.z = len(self.project.sprites)
        sp.transform = {"x": self.project.box_x + self.project.tile_w / 2,
                        "y": self.project.box_y + self.project.tile_h / 2,
                        "rot": 0.0, "scale": 1.0}
        self.project.sprites.append(sp)
        self.sel_kind, self.sel_idx = "sprite", len(self.project.sprites) - 1
        return True

    def import_images(self):
        paths = dialogs.open_images()
        if not paths:
            return
        self.snapshot()
        n = sum(1 for p in paths if self._add_sprite(p))
        self._thumbs_dirty = True
        self.status = f"{n} imagen(es) importada(s)."

    def import_dropped(self, paths):
        imgs = [p for p in paths if os.path.splitext(p)[1].lower() in
                (".png", ".gif", ".bmp", ".jpg", ".jpeg")]
        proj = [p for p in paths if p.lower().endswith(".pbproj")]
        if proj:
            self._load_path(proj[0])
            return
        if not imgs:
            return
        self.snapshot()
        n = sum(1 for p in imgs if self._add_sprite(p))
        self._thumbs_dirty = True
        self.status = f"{n} imagen(es) importada(s)."

    def delete_sprite(self, idx):
        self.snapshot()
        del self.project.sprites[idx]
        self.sel_kind, self.sel_idx = None, -1
        self._thumbs_dirty = True

    def bind_sprite(self, sprite_idx, bone_name):
        """Vincula (o desvincula con bone_name=None) sin que el sprite salte."""
        self.snapshot()
        sp = self.project.sprites[sprite_idx]
        pose_for = self.pose_for()
        sw = model.sprite_world(self.project, sp, pose_for)
        if bone_name is None:
            sp.transform = {"x": sw[0], "y": sw[1], "rot": sw[2], "scale": sw[3]}
            sp.bone = None
        else:
            bidx = self.project.bone_by_name(bone_name)
            bw = model.bone_world(self.project, bidx, pose_for)
            sp.local = model.compute_local(bw, sw)
            sp.bone = bone_name
        self._thumbs_dirty = True

    def cycle_binding(self, sprite_idx, direction):
        sp = self.project.sprites[sprite_idx]
        options = [None] + [b.name for b in self.project.bones]
        cur = sp.bone if sp.bone in options else None
        pos = options.index(cur)
        self.bind_sprite(sprite_idx, options[(pos + direction) % len(options)])

    # ====================================================================
    # huesos
    # ====================================================================
    def create_bone(self, head_world, tail_world, parent):
        if parent is None:
            parent = -1
        self.snapshot()
        wrot = math.degrees(math.atan2(tail_world[1] - head_world[1],
                                       tail_world[0] - head_world[0]))
        length = math.hypot(tail_world[0] - head_world[0],
                            tail_world[1] - head_world[1])
        pose_for = self.pose_for()
        if parent >= 0:
            pw = model.bone_world(self.project, parent, pose_for)
            dx, dy = head_world[0] - pw[0], head_world[1] - pw[1]
            a = math.radians(-pw[2])
            c, s = math.cos(a), math.sin(a)
            psc = pw[3] or 1
            lx = (dx * c - dy * s) / psc
            ly = (dx * s + dy * c) / psc
            rest = {"x": lx, "y": ly, "rot": wrot - pw[2], "scale": 1.0}
            length /= psc
        else:
            rest = {"x": head_world[0], "y": head_world[1], "rot": wrot,
                    "scale": 1.0}
        b = model.Bone(self.project.unique_bone_name("hueso"))
        b.parent = parent
        b.rest = rest
        b.length = max(4.0, length)
        self.project.bones.append(b)
        self.working[b.name] = model.clone_pose(b.rest)
        self.sel_kind, self.sel_idx = "bone", len(self.project.bones) - 1
        self.status = f"Hueso '{b.name}' creado."

    def delete_bone(self, idx):
        self.snapshot()
        target = self.project.bones[idx]
        for b in self.project.bones:
            if b.parent == idx:
                b.parent = target.parent
        del self.project.bones[idx]
        for b in self.project.bones:
            if b.parent > idx:
                b.parent -= 1
            elif b.parent == idx:
                b.parent = -1
        for s in self.project.sprites:
            if s.bone == target.name:
                self.bind_sprite_inplace_unbind(s, target.name)
        self.working.pop(target.name, None)
        for f in self.project.frames:
            f.poses.pop(target.name, None)
        self.sel_kind, self.sel_idx = None, -1
        self._thumbs_dirty = True

    def bind_sprite_inplace_unbind(self, sp, bone_name):
        """Desvincula dejando el sprite donde estaba (sin snapshot extra)."""
        sw = model.sprite_world(self.project, sp, self.pose_for())
        sp.transform = {"x": sw[0], "y": sw[1], "rot": sw[2], "scale": sw[3]}
        sp.bone = None

    def cycle_parent(self, idx, direction):
        self.snapshot()
        allowed = [-1] + [i for i in range(len(self.project.bones))
                          if i != idx and not self.project.is_ancestor(idx, i)]
        cur = self.project.bones[idx].parent
        if cur not in allowed:
            cur = -1
        self.project.bones[idx].parent = allowed[
            (allowed.index(cur) + direction) % len(allowed)]
        self._thumbs_dirty = True

    def delete_selected(self):
        if self.sel_kind == "sprite" and self.selected_sprite():
            self.delete_sprite(self.sel_idx)
        elif self.sel_kind == "bone" and self.selected_bone():
            self.delete_bone(self.sel_idx)

    # ====================================================================
    # frames
    # ====================================================================
    def capture_frame(self):
        self.snapshot()
        f = model.Frame(f"f{len(self.project.frames)+1}")
        for b in self.project.bones:
            f.poses[b.name] = model.clone_pose(self.working.get(b.name, b.rest))
        self.project.frames.append(f)
        self.cur_frame = len(self.project.frames) - 1
        self._thumbs_dirty = True
        self.status = f"Frame {self.cur_frame+1} capturado."

    def select_frame(self, i):
        self.cur_frame = i
        self.sync_working()

    def delete_frame(self, i):
        if 0 <= i < len(self.project.frames):
            self.snapshot()
            del self.project.frames[i]
            self.cur_frame = min(self.cur_frame, len(self.project.frames) - 1)
            self.sync_working()
            self._thumbs_dirty = True

    def duplicate_frame(self, i):
        if 0 <= i < len(self.project.frames):
            self.snapshot()
            src = self.project.frames[i]
            f = model.Frame(src.name + "*")
            f.poses = {k: model.clone_pose(v) for k, v in src.poses.items()}
            self.project.frames.insert(i + 1, f)
            self.cur_frame = i + 1
            self.sync_working()
            self._thumbs_dirty = True

    def move_frame(self, i, d):
        j = i + d
        if 0 <= i < len(self.project.frames) and 0 <= j < len(self.project.frames):
            self.snapshot()
            fr = self.project.frames
            fr[i], fr[j] = fr[j], fr[i]
            self.cur_frame = j
            self._thumbs_dirty = True

    def toggle_play(self):
        if not self.project.frames:
            return
        self.playing = not self.playing
        self.play_t = 0.0
        self.play_i = 0

    def _update_play(self, dt):
        if not self.playing or not self.project.frames:
            return
        self.play_t += dt
        step = 1.0 / max(1, self.project.fps)
        if self.play_t >= step:
            self.play_t -= step
            self.play_i = (self.play_i + 1) % len(self.project.frames)

    # ====================================================================
    # archivo
    # ====================================================================
    def new_project(self):
        self.project = model.Project()
        self.sel_kind, self.sel_idx = None, -1
        self.cur_frame = -1
        self.working = {}
        self.history.clear()
        self.dirty = False
        self.recovery_data = None
        recovery.clear()
        self._thumbs_dirty = True
        self.status = "Proyecto nuevo."

    def _load_path(self, path):
        try:
            self.project = model.Project.load(path)
        except Exception as e:
            self.status = f"Error al abrir: {e}"
            return
        render.ensure_surfaces(self.project)
        self.sel_kind, self.sel_idx = None, -1
        self.cur_frame = -1
        self.sync_working()
        self.history.clear()
        self.dirty = False
        self._thumbs_dirty = True
        self.status = f"Abierto: {os.path.basename(path)}"

    def open_project(self):
        path = dialogs.open_project()
        if path:
            self._load_path(path)

    def save_project(self, as_new=False):
        path = self.project.path
        if as_new or not path:
            path = dialogs.save_project_as()
        if not path:
            return
        try:
            self.project.save(path)
            self.dirty = False
            recovery.clear()
            self.status = f"Guardado: {os.path.basename(path)}"
        except Exception as e:
            self.status = f"Error al guardar: {e}"

    def export_composite(self):
        if not self.project.sprites:
            self.status = "No hay imagenes para exportar."
            return
        path = dialogs.save_png_as()
        if not path:
            return
        try:
            sz = render.export_composite(self.project, path, self.export_cols)
            self.status = f"Exportado {sz[0]}x{sz[1]}: {os.path.basename(path)}"
        except Exception as e:
            self.status = f"Error export: {e}"

    def export_layers(self):
        if not self.project.sprites:
            self.status = "No hay imagenes para exportar."
            return
        d = dialogs.choose_dir()
        if not d:
            return
        try:
            files = render.export_per_layer(self.project, d, self.export_cols)
            self.status = f"{len(files)} hojas por capa exportadas."
        except Exception as e:
            self.status = f"Error export: {e}"

    # ====================================================================
    # hit testing
    # ====================================================================
    def _hit_sprite(self, sx, sy):
        wx, wy = self.s2w(sx, sy)
        pose = self.pose_for()
        for idx in reversed(self.project.sprite_draw_order()):
            sp = self.project.sprites[idx]
            if not sp.visible or sp.surface is None:
                continue
            wt = model.sprite_world(self.project, sp, pose)
            ix, iy = model.world_to_image_point(wt[0], wt[1], wt[2], wt[3],
                                                 sp.pivot, (wx, wy))
            w, h = sp.size
            if 0 <= ix < w and 0 <= iy < h:
                try:
                    if sp.surface.get_at((int(ix), int(iy)))[3] > 8:
                        return idx
                except IndexError:
                    pass
        return -1

    def _bone_endpoints_screen(self, idx, pose):
        wt = model.bone_world(self.project, idx, pose)
        head = self.w2s(wt[0], wt[1])
        tip_w = model.bone_tip(self.project, idx, wt)
        tip = self.w2s(*tip_w)
        return head, tip

    def _hit_bone(self, sx, sy):
        """Devuelve (idx, 'head'|'body') del hueso mas cercano o None."""
        pose = self.pose_for()
        best = None
        best_d = 1e9
        for idx in range(len(self.project.bones)):
            head, tip = self._bone_endpoints_screen(idx, pose)
            dh = math.hypot(sx - head[0], sy - head[1])
            if dh < 10 and dh < best_d:
                best, best_d = (idx, "head"), dh
            db = _seg_dist((sx, sy), head, tip)
            if db < 7 and db < best_d:
                best, best_d = (idx, "body"), db
        return best

    def _nearest_tip(self, sx, sy, radius=16):
        """Punta de hueso mas cercana (para encadenar al crear)."""
        pose = self.pose_for()
        best, best_d = None, radius
        for idx in range(len(self.project.bones)):
            head, tip = self._bone_endpoints_screen(idx, pose)
            d = math.hypot(sx - tip[0], sy - tip[1])
            if d < best_d:
                best, best_d = idx, d
        return best

    def _sprite_handle(self, sp, dist=44):
        """(pivot_screen, handle_screen, rot) de la manija de rotacion."""
        wt = model.sprite_world(self.project, sp, self.pose_for())
        psx, psy = self.w2s(wt[0], wt[1])
        ux, uy = model._rot(0, -1, wt[2])     # "arriba" del sprite
        return (psx, psy), (psx + ux * dist, psy + uy * dist), wt[2]

    def bind_nearest(self, sprite_idx):
        sp = self.project.sprites[sprite_idx]
        sw = model.sprite_world(self.project, sp, self.pose_for())
        best, bd = None, 1e9
        for i, b in enumerate(self.project.bones):
            bw = model.bone_world(self.project, i, self.pose_for())
            d = math.hypot(sw[0] - bw[0], sw[1] - bw[1])
            if d < bd:
                bd, best = d, b.name
        if best:
            self.bind_sprite(sprite_idx, best)
            self.status = f"'{sp.name}' vinculado a '{best}'."

    def pivot_to_content(self, sprite_idx):
        """Coloca el pivote en el centro del contenido visible (mascara)."""
        sp = self.project.sprites[sprite_idx]
        if not sp.content_rect:
            return
        self.snapshot()
        cx, cy, cw, ch = sp.content_rect
        sp.pivot = [cx + cw / 2.0, cy + ch / 2.0]
        self._thumbs_dirty = True
        self.status = "Pivote centrado en el contenido."

    # ====================================================================
    # interaccion del canvas
    # ====================================================================
    def _handle_canvas(self):
        c = self.r_canvas
        over = c.collidepoint(self.mouse)

        if self.pan:
            if pygame.mouse.get_pressed()[1]:
                sp, cx, cy = self.pan
                self.cam_x = cx - (self.mouse[0] - sp[0]) / self.zoom
                self.cam_y = cy - (self.mouse[1] - sp[1]) / self.zoom
            else:
                self.pan = None

        if self.wheel != 0 and over:
            old = self.s2w(*self.mouse)
            self.zoom = max(0.5, min(16.0, self.zoom * (1.1 ** self.wheel)))
            new = self.s2w(*self.mouse)
            self.cam_x += old[0] - new[0]
            self.cam_y += old[1] - new[1]

        if self.playing:
            return

        if self.lmb_down and over and self.active_scrub is None:
            self._canvas_press()

        if self.drag is not None:
            if self.lmb_held:
                self._canvas_drag()
            else:
                self._canvas_release()

    def _canvas_press(self):
        if self.tool == "bone":
            head = self.s2w(*self.mouse)
            parent = self._nearest_tip(*self.mouse)
            if parent is not None:
                pose = self.pose_for()
                _, tip = self._bone_endpoints_screen(parent, pose)
                head = self.s2w(*tip)
            else:
                parent = -1                # sin punta cercana => hueso raiz
            self.drag = {"mode": "bone_create", "parent": parent,
                         "head": head}
            return
        # herramienta seleccion: manija de rotacion del sprite seleccionado
        ssp = self.selected_sprite()
        if ssp is not None:
            (pcx, pcy), (hx, hy), _ = self._sprite_handle(ssp)
            if math.hypot(self.mouse[0] - hx, self.mouse[1] - hy) < 11:
                self.snapshot()
                ang0 = math.degrees(math.atan2(self.mouse[1] - pcy,
                                               self.mouse[0] - pcx))
                rot0 = ssp.local["rot"] if ssp.bone else ssp.transform["rot"]
                self.drag = {"mode": "sprite_rotate", "idx": self.sel_idx,
                             "ang0": ang0, "rot0": rot0,
                             "pcx": pcx, "pcy": pcy}
                return
        hb = self._hit_bone(*self.mouse) if self.show_bones else None
        if hb is not None:
            idx, part = hb
            self.sel_kind, self.sel_idx = "bone", idx
            self.snapshot()
            if part == "head":
                self.drag = {"mode": "bone_move", "idx": idx}
            else:
                wt = model.bone_world(self.project, idx, self.pose_for())
                mwx, mwy = self.s2w(*self.mouse)
                self.drag = {"mode": "bone_rotate", "idx": idx,
                             "ang0": math.degrees(math.atan2(mwy - wt[1],
                                                             mwx - wt[0])),
                             "rot0": self.working[self.project.bones[idx].name]["rot"]}
            return
        hs = self._hit_sprite(*self.mouse)
        if hs >= 0:
            self.sel_kind, self.sel_idx = "sprite", hs
            self.snapshot()
            self.drag = {"mode": "sprite_move", "idx": hs}
        else:
            self.sel_kind, self.sel_idx = None, -1

    def _canvas_drag(self):
        mwx, mwy = self.s2w(*self.mouse)
        pwx, pwy = self.s2w(*self.prev_mouse)
        m = self.drag["mode"]

        if m == "sprite_rotate":
            sp = self.project.sprites[self.drag["idx"]]
            ang = math.degrees(math.atan2(self.mouse[1] - self.drag["pcy"],
                                          self.mouse[0] - self.drag["pcx"]))
            rot = self.drag["rot0"] + (ang - self.drag["ang0"])
            if pygame.key.get_mods() & pygame.KMOD_CTRL:
                rot = round(rot / 15.0) * 15.0
            if sp.bone:
                sp.local["rot"] = rot
            else:
                sp.transform["rot"] = rot
            self.dirty = True
            self._thumbs_dirty = True

        elif m == "sprite_move":
            sp = self.project.sprites[self.drag["idx"]]
            dwx, dwy = mwx - pwx, mwy - pwy
            if sp.bone:
                bidx = self.project.bone_by_name(sp.bone)
                bw = model.bone_world(self.project, bidx, self.pose_for())
                a = math.radians(-bw[2])
                cs, sn = math.cos(a), math.sin(a)
                sc = bw[3] or 1
                sp.local["x"] += (dwx * cs - dwy * sn) / sc
                sp.local["y"] += (dwx * sn + dwy * cs) / sc
            else:
                sp.transform["x"] += dwx
                sp.transform["y"] += dwy
            self.dirty = True
            self._thumbs_dirty = True

        elif m == "bone_rotate":
            idx = self.drag["idx"]
            name = self.project.bones[idx].name
            wt = model.bone_world(self.project, idx, self.pose_for())
            ang = math.degrees(math.atan2(mwy - wt[1], mwx - wt[0]))
            rot = self.drag["rot0"] + (ang - self.drag["ang0"])
            if pygame.key.get_mods() & pygame.KMOD_CTRL:
                rot = round(rot / 15.0) * 15.0
            self.working[name]["rot"] = rot
            self._write_pose(idx)

        elif m == "bone_move":
            idx = self.drag["idx"]
            name = self.project.bones[idx].name
            b = self.project.bones[idx]
            dwx, dwy = mwx - pwx, mwy - pwy
            if b.parent >= 0:
                pw = model.bone_world(self.project, b.parent, self.pose_for())
                a = math.radians(-pw[2])
                cs, sn = math.cos(a), math.sin(a)
                sc = pw[3] or 1
                self.working[name]["x"] += (dwx * cs - dwy * sn) / sc
                self.working[name]["y"] += (dwx * sn + dwy * cs) / sc
            else:
                self.working[name]["x"] += dwx
                self.working[name]["y"] += dwy
            self._write_pose(idx)

    def _canvas_release(self):
        if self.drag["mode"] == "bone_create":
            head = self.drag["head"]
            tail = self.s2w(*self.mouse)
            if math.hypot(tail[0] - head[0], tail[1] - head[1]) >= 4:
                self.create_bone(head, tail, self.drag["parent"])
        self.drag = None

    # ====================================================================
    # widgets
    # ====================================================================
    def text(self, s, pos, color=TEXT, font=None, center=False, right=False):
        font = font or self.font
        img = font.render(str(s), True, color)
        r = img.get_rect()
        if center:
            r.center = pos
        elif right:
            r.midright = pos
        else:
            r.topleft = pos
        self.screen.blit(img, r)
        return r

    def button(self, rect, label, active=False, enabled=True):
        hot = rect.collidepoint(self.mouse) and enabled
        col = ACTIVE if active else (HOVER if hot else PANEL2)
        pygame.draw.rect(self.screen, col, rect, border_radius=4)
        pygame.draw.rect(self.screen, LINE, rect, 1, border_radius=4)
        self.text(label, rect.center, TEXT if enabled else DIM,
                  font=self.font_s, center=True)
        return enabled and self.lmb_down and hot

    def scrub(self, sid, rect, value, step, fmt="{:.0f}"):
        hot = rect.collidepoint(self.mouse)
        active = self.active_scrub == sid
        col = ACTIVE if active else (HOVER if hot else PANEL2)
        pygame.draw.rect(self.screen, col, rect, border_radius=3)
        pygame.draw.rect(self.screen, LINE, rect, 1, border_radius=3)
        self.text(fmt.format(value), (rect.right - 6, rect.centery), TEXT,
                  font=self.font_s, right=True)
        new = value
        if active:
            if not self.lmb_held:
                self.active_scrub = None
            else:
                new = self.scrub_v0 + (self.mouse[0] - self.scrub_x0) * step
        elif self.lmb_down and hot and self.active_scrub is None:
            self.active_scrub = sid
            self.scrub_x0 = self.mouse[0]
            self.scrub_v0 = value
            self.snapshot()
        return new, (new != value)

    # ====================================================================
    # dibujo
    # ====================================================================
    def _draw(self):
        self.screen.fill(BG)
        self._draw_canvas()
        self._draw_toolbar()
        self._draw_topbar()
        self._draw_left()
        self._draw_right()
        self._draw_timeline()
        if self.recovery_data:
            self._draw_recovery_banner()
        if self.show_help:
            self._draw_help()

    def _draw_canvas(self):
        c = self.r_canvas
        pygame.draw.rect(self.screen, CANVAS_BG, c)
        self.screen.set_clip(c)
        self._draw_grid()
        bx, by = self.w2s(self.project.box_x, self.project.box_y)
        box = pygame.Rect(int(bx), int(by), int(self.project.tile_w * self.zoom),
                          int(self.project.tile_h * self.zoom))
        pygame.draw.rect(self.screen, (24, 26, 32), box)
        self._draw_grid(box)
        pygame.draw.rect(self.screen, ACCENT, box, 1)

        render.draw_sprites(self.screen, self.project, self.active_frame(),
                            self.w2s, zoom=self.zoom)

        if self.show_bones and not self.playing:
            self._draw_links()
            self._draw_bones()
        if not self.playing:
            self._draw_sprite_gizmo()
        if self.drag and self.drag["mode"] == "bone_create":
            h = self.w2s(*self.drag["head"])
            pygame.draw.line(self.screen, BONE_SEL, h, self.mouse, 2)
            pygame.draw.circle(self.screen, BONE_SEL,
                               (int(h[0]), int(h[1])), 5, 1)
        self.screen.set_clip(None)

        tool_lbl = "SELECCION (V)" if self.tool == "select" else "HUESO (B)"
        self.text(tool_lbl, (c.x + 56, c.y + 8), ACCENT, font=self.font_b)
        fr = ("Reposo" if self.cur_frame < 0
              else f"Frame {self.cur_frame+1}/{len(self.project.frames)}")
        self.text(fr, (c.right - 10, c.y + 8), TEXT, font=self.font_b, right=True)

    def _draw_grid(self, clip=None):
        c = clip or self.r_canvas
        step = self.zoom if self.zoom >= 6 else self.zoom * 8
        ox = self.w2s(0, 0)
        x = c.x + (ox[0] - c.x) % step
        while x < c.right:
            pygame.draw.line(self.screen, GRID, (x, c.y), (x, c.bottom))
            x += step
        y = c.y + (ox[1] - c.y) % step
        while y < c.bottom:
            pygame.draw.line(self.screen, GRID, (c.x, y), (c.right, y))
            y += step

    def _draw_links(self):
        """Linea fina entre cada sprite vinculado y la cabeza de su hueso."""
        pose = self.pose_for()
        for sp in self.project.sprites:
            if not sp.bone or sp.surface is None:
                continue
            bidx = self.project.bone_by_name(sp.bone)
            if bidx < 0:
                continue
            sw = model.sprite_world(self.project, sp, pose)
            bw = model.bone_world(self.project, bidx, pose)
            a = self.w2s(sw[0], sw[1])
            b = self.w2s(bw[0], bw[1])
            pygame.draw.line(self.screen, (90, 110, 90), a, b, 1)

    def _draw_sprite_gizmo(self):
        sp = self.selected_sprite()
        if sp is None or sp.surface is None:
            return
        wt = model.sprite_world(self.project, sp, self.pose_for())
        # contorno del contenido (mascara) rotado con el sprite
        if sp.content_rect:
            cx, cy, cw, ch = sp.content_rect
            corners = [(cx, cy), (cx + cw, cy), (cx + cw, cy + ch), (cx, cy + ch)]
            pts = []
            for ix, iy in corners:
                ox, oy = model._rot((ix - sp.pivot[0]) * wt[3],
                                    (iy - sp.pivot[1]) * wt[3], wt[2])
                pts.append(self.w2s(wt[0] + ox, wt[1] + oy))
            pygame.draw.polygon(self.screen, (120, 200, 140), pts, 1)
        (pcx, pcy), (hx, hy), _ = self._sprite_handle(sp)
        pygame.draw.line(self.screen, SELECT, (pcx, pcy), (hx, hy), 1)
        pygame.draw.circle(self.screen, SELECT, (int(hx), int(hy)), 6, 2)
        pygame.draw.circle(self.screen, SELECT, (int(pcx), int(pcy)), 3, 1)

    def _draw_bones(self):
        pose = self.pose_for()
        for idx in range(len(self.project.bones)):
            head, tip = self._bone_endpoints_screen(idx, pose)
            sel = (self.sel_kind == "bone" and self.sel_idx == idx)
            self._draw_one_bone(head, tip, sel)

    def _draw_one_bone(self, head, tip, sel):
        col = BONE_SEL if sel else BONE
        hx, hy = head
        tx, ty = tip
        dx, dy = tx - hx, ty - hy
        ln = math.hypot(dx, dy) or 1
        nx, ny = -dy / ln, dx / ln       # normal
        r = max(3, min(8, ln * 0.18))    # mitad del ancho en la base
        base_l = (hx + nx * r, hy + ny * r)
        base_r = (hx - nx * r, hy - ny * r)
        poly = [base_l, tip, base_r]
        body = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
        pygame.draw.polygon(body, (*col, 90), poly)
        pygame.draw.polygon(body, (*col, 220), poly, 1)
        self.screen.blit(body, (0, 0))
        pygame.draw.circle(self.screen, col, (int(hx), int(hy)),
                           int(r) + 1, 2)
        pygame.draw.circle(self.screen, (20, 20, 24), (int(hx), int(hy)), 2)
        pygame.draw.circle(self.screen, col, (int(tx), int(ty)), 3)

    def _draw_toolbar(self):
        c = self.r_canvas
        bar = pygame.Rect(c.x + 6, c.y + 30, 40, 88)
        pygame.draw.rect(self.screen, PANEL, bar, border_radius=6)
        pygame.draw.rect(self.screen, LINE, bar, 1, border_radius=6)
        b1 = pygame.Rect(bar.x + 4, bar.y + 4, 32, 32)
        b2 = pygame.Rect(bar.x + 4, bar.y + 44, 32, 32)
        self._tool_btn(b1, "select")
        self._tool_btn(b2, "bone")

    def _tool_btn(self, rect, tool):
        active = self.tool == tool
        hot = rect.collidepoint(self.mouse)
        col = ACTIVE if active else (HOVER if hot else PANEL2)
        pygame.draw.rect(self.screen, col, rect, border_radius=4)
        pygame.draw.rect(self.screen, LINE, rect, 1, border_radius=4)
        cx, cy = rect.center
        if tool == "select":   # flecha de cursor
            pts = [(cx - 6, cy - 8), (cx - 6, cy + 7), (cx - 2, cy + 3),
                   (cx + 1, cy + 9), (cx + 4, cy + 7), (cx + 1, cy + 1),
                   (cx + 6, cy + 1)]
            pygame.draw.polygon(self.screen, TEXT, pts)
        else:                  # hueso
            pygame.draw.line(self.screen, TEXT, (cx - 6, cy + 6),
                             (cx + 6, cy - 6), 3)
            for ex, ey in ((cx - 6, cy + 6), (cx + 6, cy - 6)):
                pygame.draw.circle(self.screen, TEXT, (ex, ey), 3)
        if self.lmb_down and hot:
            self.tool = tool

    # -- topbar ----------------------------------------------------------
    def _draw_topbar(self):
        pygame.draw.rect(self.screen, PANEL, self.r_top)
        pygame.draw.line(self.screen, LINE, (0, TOP_H), (self.r_top.right, TOP_H))
        x = 6
        for label, fn in [("Nuevo", self.new_project), ("Abrir", self.open_project),
                          ("Guardar", lambda: self.save_project(False)),
                          ("Guardar como", lambda: self.save_project(True))]:
            w = self.font_s.size(label)[0] + 16
            if self.button(pygame.Rect(x, 5, w, 26), label):
                fn()
            x += w + 4
        x += 10
        if self.button(pygame.Rect(x, 5, 124, 26), "+ Importar imagen",
                       active=True):
            self.import_images()
        x += 132
        for label, fn in [("Exportar hoja", self.export_composite),
                          ("Exportar capas", self.export_layers)]:
            w = self.font_s.size(label)[0] + 16
            if self.button(pygame.Rect(x, 5, w, 26), label):
                fn()
            x += w + 4
        self.text("cols", (x + 4, 12), DIM, font=self.font_s)
        v, ch = self.scrub("excols", pygame.Rect(x + 34, 5, 50, 26),
                           self.export_cols, 0.1)
        if ch:
            self.export_cols = max(0, int(round(v)))
        x += 92
        if self.button(pygame.Rect(x, 5, 66, 26), "Deshacer",
                       enabled=self.history.can_undo()):
            self.undo()
        x += 70
        if self.button(pygame.Rect(x, 5, 62, 26), "Rehacer",
                       enabled=self.history.can_redo()):
            self.redo()
        x += 66
        if self.button(pygame.Rect(x, 5, 54, 26), "Ayuda", active=self.show_help):
            self.show_help = not self.show_help

    # -- panel izquierdo: imagenes + huesos ------------------------------
    def _draw_left(self):
        p = self.r_left
        pygame.draw.rect(self.screen, PANEL, p)
        pygame.draw.line(self.screen, LINE, (p.right, p.y), (p.right, p.bottom))
        half = p.y + (p.h // 2)

        self.text("IMAGENES", (p.x + 10, p.y + 8), ACCENT, font=self.font_b)
        if self.button(pygame.Rect(p.x + 8, p.y + 28, p.w - 16, 24),
                       "+ Importar imagen"):
            self.import_images()
        # el borrado se DIFIERE: no se puede mutar la lista mientras se dibuja
        pending_delete = None
        y = p.y + 58
        order = sorted(range(len(self.project.sprites)),
                       key=lambda i: (self.project.sprites[i].z, i), reverse=True)
        for idx in order:
            if y > half - 26:
                break
            sp = self.project.sprites[idx]
            sel = (self.sel_kind == "sprite" and self.sel_idx == idx)
            y, dele = self._list_row(
                p, y, sp.name, sel, sp.visible,
                lambda i=idx: self._sel("sprite", i),
                lambda i=idx: self._toggle_vis_sprite(i),
                tag="B" if sp.bone else "")
            if dele:
                pending_delete = ("sprite", idx)

        pygame.draw.line(self.screen, LINE, (p.x + 6, half), (p.right - 6, half))
        self.text("HUESOS", (p.x + 10, half + 6), ACCENT, font=self.font_b)
        y = half + 28
        for idx in range(len(self.project.bones)):
            if y > p.bottom - 26:
                break
            b = self.project.bones[idx]
            sel = (self.sel_kind == "bone" and self.sel_idx == idx)
            depth = 0
            par = b.parent
            while par >= 0 and depth < 6:
                depth += 1
                par = self.project.bones[par].parent
            y, dele = self._list_row(
                p, y, b.name, sel, True,
                lambda i=idx: self._sel("bone", i), None,
                indent=depth * 10)
            if dele:
                pending_delete = ("bone", idx)

        if pending_delete is not None:
            kind, i = pending_delete
            if kind == "sprite" and i < len(self.project.sprites):
                self.delete_sprite(i)
            elif kind == "bone" and i < len(self.project.bones):
                self.delete_bone(i)

    def _list_row(self, p, y, label, sel, visible, on_sel, on_eye,
                  indent=0, tag=""):
        """Dibuja una fila. Devuelve (nuevo_y, borrar_pedido). El borrado se
        difiere al que llama para no mutar la lista durante el dibujo."""
        row = pygame.Rect(p.x + 8, y, p.w - 16, 24)
        col = ACTIVE if sel else (HOVER if row.collidepoint(self.mouse) else PANEL2)
        pygame.draw.rect(self.screen, col, row, border_radius=3)
        self.text(label, (row.x + 6 + indent, row.centery - 7),
                  TEXT if visible else DIM, font=self.font_s)
        if tag:
            self.text(tag, (row.right - 52, row.centery - 7), ACCENT,
                      font=self.font_s)
        xbtn = pygame.Rect(row.right - 22, row.y + 3, 18, 18)
        delete_requested = self.button(xbtn, "x")
        eye = None
        consumed = delete_requested
        if on_eye is not None:
            eye = pygame.Rect(row.right - 44, row.y + 3, 18, 18)
            if self.button(eye, "o" if visible else "-"):
                on_eye()
                consumed = True
        if (self.lmb_down and row.collidepoint(self.mouse) and not consumed
                and not xbtn.collidepoint(self.mouse)
                and not (eye and eye.collidepoint(self.mouse))):
            on_sel()
        return y + 26, delete_requested

    def _sel(self, kind, idx):
        self.sel_kind, self.sel_idx = kind, idx

    def _toggle_vis_sprite(self, idx):
        self.snapshot()
        self.project.sprites[idx].visible = not self.project.sprites[idx].visible
        self._thumbs_dirty = True

    # -- panel derecho: propiedades --------------------------------------
    def _draw_right(self):
        p = self.r_right
        pygame.draw.rect(self.screen, PANEL, p)
        pygame.draw.line(self.screen, LINE, (p.x, p.y), (p.x, p.bottom))
        x = p.x + 10
        w = p.w - 20
        self.text("PROPIEDADES", (x, p.y + 8), ACCENT, font=self.font_b)
        y = p.y + 32

        if self.sel_kind == "sprite" and self.selected_sprite():
            y = self._props_sprite(x, w, y, p)
        elif self.sel_kind == "bone" and self.selected_bone():
            y = self._props_bone(x, w, y, p)
        else:
            self.text("(nada seleccionado)", (x, y), DIM, font=self.font_s)
            y += 30

        pygame.draw.line(self.screen, LINE, (p.x + 6, y), (p.right - 6, y))
        y += 8
        self.text("TILE / PROYECTO", (x, y), ACCENT, font=self.font_s)
        y += 20
        for key, lbl, step in (("tile_w", "Tile ancho", 0.25),
                               ("tile_h", "Tile alto", 0.25), ("fps", "FPS", 0.05)):
            self.text(lbl, (x + 4, y + 4), TEXT, font=self.font_s)
            v, ch = self.scrub("g_" + key, pygame.Rect(x + 90, y, w - 90, 22),
                               getattr(self.project, key), step)
            if ch:
                setattr(self.project, key, max(1, int(round(v))))
                self._thumbs_dirty = True
            y += 26
        for key, lbl in (("box_x", "Caja X"), ("box_y", "Caja Y")):
            self.text(lbl, (x + 4, y + 4), TEXT, font=self.font_s)
            v, ch = self.scrub("g_" + key, pygame.Rect(x + 90, y, w - 90, 22),
                               getattr(self.project, key), 0.5)
            if ch:
                setattr(self.project, key, v)
                self._thumbs_dirty = True
            y += 26

    def _name_header(self, x, w, y, p, kind, idx, name):
        editing = (self.editing is not None and self.editing[1] == idx
                   and self.editing[0] == ("rename_" + kind))
        if editing:
            box = pygame.Rect(x, y - 2, w, 22)
            pygame.draw.rect(self.screen, (24, 26, 32), box, border_radius=3)
            pygame.draw.rect(self.screen, ACCENT, box, 1, border_radius=3)
            caret = "|" if (pygame.time.get_ticks() // 400) % 2 else ""
            self.text(self.edit_buf + caret, (x + 5, y + 2), TEXT, font=self.font_s)
        else:
            self.text(name, (x, y), TEXT, font=self.font_b)
            if self.button(pygame.Rect(p.right - 90, y - 2, 80, 20), "Renombrar"):
                self.rename_selected()
        return y + 26

    def _pose_rows(self, x, w, y, pose, prefix, on_change):
        for key, lbl, step, fmt in (("rot", "Rotacion", 0.5, "{:.1f}"),
                                    ("x", "Pos X", 0.25, "{:.1f}"),
                                    ("y", "Pos Y", 0.25, "{:.1f}"),
                                    ("scale", "Escala", 0.01, "{:.2f}")):
            self.text(lbl, (x + 4, y + 4), TEXT, font=self.font_s)
            v, ch = self.scrub(prefix + key, pygame.Rect(x + 90, y, w - 90, 22),
                               pose[key], step, fmt)
            if ch:
                on_change(key, v)
            y += 26
        return y

    def _props_sprite(self, x, w, y, p):
        idx = self.sel_idx
        sp = self.project.sprites[idx]
        y = self._name_header(x, w, y, p, "sprite", idx, sp.name)
        # Z
        self.text("Z (orden)", (x, y + 4), DIM, font=self.font_s)
        if self.button(pygame.Rect(x + 80, y, 22, 22), "-"):
            self.snapshot(); sp.z -= 1; self._thumbs_dirty = True
        self.text(str(sp.z), (x + 112, y + 4), TEXT, font=self.font_s)
        if self.button(pygame.Rect(x + 134, y, 22, 22), "+"):
            self.snapshot(); sp.z += 1; self._thumbs_dirty = True
        y += 30
        # binding
        self.text("Sigue al hueso", (x, y + 4), DIM, font=self.font_s)
        if self.button(pygame.Rect(x + 96, y, 22, 22), "<"):
            self.cycle_binding(idx, -1)
        bname = sp.bone if sp.bone else "(libre)"
        self.text(bname, (x + 122, y + 4),
                  TEXT if sp.bone else SELECT, font=self.font_s)
        if self.button(pygame.Rect(p.right - 32, y, 22, 22), ">"):
            self.cycle_binding(idx, 1)
        y += 28
        if self.project.bones and self.button(
                pygame.Rect(x, y, w, 22), "Vincular al hueso mas cercano"):
            self.bind_nearest(idx)
        y += 26
        if not sp.bone and self.project.bones:
            self.text("Libre: no sigue ningun hueso.", (x, y), SELECT,
                      font=self.font_s)
            y += 18
        # transform o offset
        if sp.bone:
            self.text("OFFSET respecto al hueso", (x, y), ACCENT, font=self.font_s)
            y += 20
            y = self._pose_rows(x, w, y, sp.local, "sl_",
                                lambda k, v: self._set_sprite(sp, "local", k, v))
        else:
            self.text("POSICION (libre)", (x, y), ACCENT, font=self.font_s)
            y += 20
            y = self._pose_rows(x, w, y, sp.transform, "st_",
                                lambda k, v: self._set_sprite(sp, "transform", k, v))
        y += 6
        self.text("PIVOTE (centro de rotacion)", (x, y), ACCENT, font=self.font_s)
        y += 20
        for i, lbl in ((0, "Pivote X"), (1, "Pivote Y")):
            self.text(lbl, (x + 4, y + 4), TEXT, font=self.font_s)
            v, ch = self.scrub("piv" + lbl, pygame.Rect(x + 90, y, w - 90, 22),
                               sp.pivot[i], 0.25, "{:.1f}")
            if ch:
                sp.pivot[i] = v; self._thumbs_dirty = True
            y += 26
        if self.button(pygame.Rect(x, y, w, 22),
                       "Pivote al centro del contenido"):
            self.pivot_to_content(idx)
        y += 32
        if self.button(pygame.Rect(x, y, w, 24), "Borrar imagen (Supr)"):
            self.delete_sprite(idx)
        return y + 32

    def _set_sprite(self, sp, which, key, v):
        getattr(sp, which)[key] = v
        self.dirty = True
        self._thumbs_dirty = True

    def _props_bone(self, x, w, y, p):
        idx = self.sel_idx
        b = self.project.bones[idx]
        y = self._name_header(x, w, y, p, "bone", idx, b.name)
        self.text("Padre", (x, y + 4), DIM, font=self.font_s)
        if self.button(pygame.Rect(x + 60, y, 22, 22), "<"):
            self.cycle_parent(idx, -1)
        pname = "(raiz)" if b.parent < 0 else self.project.bones[b.parent].name
        self.text(pname, (x + 90, y + 4), TEXT, font=self.font_s)
        if self.button(pygame.Rect(p.right - 32, y, 22, 22), ">"):
            self.cycle_parent(idx, 1)
        y += 30
        self.text("Longitud", (x + 4, y + 4), TEXT, font=self.font_s)
        v, ch = self.scrub("blen", pygame.Rect(x + 90, y, w - 90, 22),
                           b.length, 0.25, "{:.1f}")
        if ch:
            b.length = max(1.0, v); self.dirty = True
        y += 30
        dest = "frame" if self.cur_frame >= 0 else "reposo"
        self.text(f"POSE (-> {dest})", (x, y), ACCENT, font=self.font_s)
        y += 20
        pose = self.working.get(b.name, b.rest)
        y = self._pose_rows(x, w, y, pose, "bp_", lambda k, v: self._set_bone(idx, k, v))
        y += 6
        if self.button(pygame.Rect(x, y, w, 24), "Borrar hueso (Supr)"):
            self.delete_bone(idx)
        return y + 32

    def _set_bone(self, idx, key, v):
        name = self.project.bones[idx].name
        self.working[name][key] = v
        self._write_pose(idx)

    # -- timeline --------------------------------------------------------
    def _rebuild_thumbs(self):
        self._thumbs = []
        th = 80
        frames = self.project.frames
        for f in frames:
            tile = render.render_tile(self.project, f)
            tw, hh = tile.get_size()
            sc = th / hh if hh else 1
            self._thumbs.append(pygame.transform.smoothscale(
                tile, (max(1, int(tw * sc)), th)))
        self._thumbs_dirty = False

    def _draw_timeline(self):
        p = self.r_time
        pygame.draw.rect(self.screen, PANEL, p)
        pygame.draw.line(self.screen, LINE, (0, p.y), (p.right, p.y))
        x, y = 8, p.y + 6
        if self.button(pygame.Rect(x, y, 96, 24), "Capturar (K)"):
            self.capture_frame()
        x += 100
        canf = self.cur_frame >= 0
        if self.button(pygame.Rect(x, y, 70, 24), "Duplicar", enabled=canf):
            self.duplicate_frame(self.cur_frame)
        x += 74
        if self.button(pygame.Rect(x, y, 60, 24), "Borrar", enabled=canf):
            self.delete_frame(self.cur_frame)
        x += 64
        if self.button(pygame.Rect(x, y, 28, 24), "<", enabled=canf):
            self.move_frame(self.cur_frame, -1)
        x += 30
        if self.button(pygame.Rect(x, y, 28, 24), ">", enabled=canf):
            self.move_frame(self.cur_frame, +1)
        x += 36
        if self.button(pygame.Rect(x, y, 70, 24),
                       "Detener" if self.playing else "Play", active=self.playing):
            self.toggle_play()
        x += 74
        if self.button(pygame.Rect(x, y, 70, 24), "Reposo",
                       active=self.cur_frame < 0):
            self.cur_frame = -1
            self.sync_working()
        x += 80
        self.text(f"{len(self.project.frames)} frames  |  {self.status}",
                  (x, y + 5), DIM, font=self.font_s)

        if self._thumbs_dirty:
            self._rebuild_thumbs()
        sx = 8
        sy = p.y + 38
        for i, thumb in enumerate(self._thumbs):
            rect = pygame.Rect(sx, sy, thumb.get_width() + 4, thumb.get_height() + 4)
            ph = self.playing and self._thumbs and (self.play_i % len(self._thumbs)) == i
            sel = (i == self.cur_frame) or ph
            pygame.draw.rect(self.screen, (30, 32, 38), rect)
            self.screen.blit(thumb, (rect.x + 2, rect.y + 2))
            pygame.draw.rect(self.screen, SELECT if sel else LINE, rect,
                             2 if sel else 1)
            self.text(str(i + 1), (rect.x + 3, rect.y + 1), ACCENT, font=self.font_s)
            if self.lmb_down and rect.collidepoint(self.mouse):
                self.select_frame(i)
            sx += rect.width + 6
            if sx > p.right - 60:
                break

    def _draw_recovery_banner(self):
        w = self.screen.get_width()
        bar = pygame.Rect(w // 2 - 260, TOP_H + 8, 520, 40)
        pygame.draw.rect(self.screen, (70, 60, 40), bar, border_radius=6)
        pygame.draw.rect(self.screen, ACCENT, bar, 2, border_radius=6)
        self.text("Se encontro una sesion sin guardar.",
                  (bar.x + 12, bar.centery - 7), TEXT, font=self.font_s)
        if self.button(pygame.Rect(bar.right - 180, bar.y + 8, 84, 24), "Recuperar"):
            self.accept_recovery()
        if self.button(pygame.Rect(bar.right - 90, bar.y + 8, 80, 24), "Descartar"):
            self.discard_recovery()

    def _draw_help(self):
        w, h = self.screen.get_size()
        ov = pygame.Surface((w, h), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 185))
        self.screen.blit(ov, (0, 0))
        lines = [
            "PixelBones - ayuda",
            "",
            "1) Importa imagenes (boton o arrastrar PNG). Son SPRITES libres.",
            "2) Herramienta SELECCION (V): clic en una imagen y arrastra para",
            "   MOVERLA; usa la MANIJA (circulo arriba del sprite) para ROTARLA.",
            "   Tambien posa huesos (cuerpo = rotar; nodo cabeza = mover).",
            "3) Herramienta HUESO (B): clic en el punto de inicio (nodo) y",
            "   arrastra hasta el extremo para crear el hueso (cilindro). Si",
            "   empiezas cerca de la PUNTA de otro hueso, se encadena (hijo).",
            "4) IMPORTANTE: vincula cada imagen a un hueso para que lo siga.",
            "   En PROPIEDADES usa 'Sigue al hueso < >' o el boton 'Vincular al",
            "   hueso mas cercano'. Una linea verde confirma el vinculo.",
            "5) Mueve/rota huesos y pulsa Capturar (K) por frame. Exporta PNG.",
            "",
            "K capturar   Espacio play   Supr borrar   F2 renombrar   Esc nada",
            "Rueda zoom   Boton central paneo   Ctrl al rotar = pasos de 15",
            "Ctrl+S guardar  Ctrl+Shift+S guardar como  Ctrl+O abrir",
            "Ctrl+E exportar  Ctrl+Z deshacer  Ctrl+Y rehacer",
            "",
            "Recuadro NARANJA = area exportada (tile). Solo se exportan imagenes.",
            "",
            "H / F1  cerrar ayuda",
        ]
        y = 60
        for ln in lines:
            f = self.font_b if ln == "PixelBones - ayuda" else self.font
            self.text(ln, (w // 2, y), TEXT if ln else DIM, font=f, center=True)
            y += 23


def _seg_dist(p, a, b):
    ax, ay = a
    bx, by = b
    px, py = p
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def main():
    App().run()


if __name__ == "__main__":
    main()
