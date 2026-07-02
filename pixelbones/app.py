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
import uuid
import pygame

from . import model, render, dialogs, recovery, paint, config, appicon, templates
from . import syncbodies
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
        try:
            pygame.display.set_icon(appicon.make_icon(64))
        except Exception:
            pass
        self.screen = pygame.display.set_mode(win, pygame.RESIZABLE)
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("dejavusans,sans", 14)
        self.font_b = pygame.font.SysFont("dejavusans,sans", 14, bold=True)
        self.font_s = pygame.font.SysFont("dejavusans,sans", 12)

        self.project = model.Project()
        self.ref_project = None        # body de referencia (fantasma) de un item
        self.shirt_idx = -1            # camisa de guia (cargable): -1 = ninguna
        self._shirt_cache = {}         # name -> (surface, ox, oy)
        self.ghost_op = 1.0            # opacidad del fantasma (0..1; 1 = la maxima)
        self.show_z = False            # overlay de z-index de las partes del body
        self.sel_kind = None          # "sprite" | "bone" | None
        self.sel_idx = -1
        self.cur_clip = 0             # animacion activa (project.clips)
        self.cur_frame = -1
        self.working = {}             # bone_name -> pose

        self.tool = "select"          # select | bone | link  (modo animar)
        self.scale_mode = "bones"     # "bones" (esqueleto) | "materials" (arte)
        self.link_bone = None         # hueso origen durante el enlace de 2 clics
        self.show_bones = True
        self.show_help = False

        # --- modo Pintar (raster, estilo Pixelorama) -------------------
        self.mode = "animate"         # animate | paint
        self.ptool = "pencil"         # herramienta de pintura activa
        self.paint = paint.PaintState()
        self.draw_idx = -1            # dibujo activo del taller (project.drawings)
        self.pzoom = 8.0              # zoom de la vista de lienzo (plano)
        self.pcx = 32.0              # centro de la vista en px de lienzo
        self.pcy = 64.0
        self.paint_undo = []          # [(sprite, layer, surface_copy)]
        self.paint_redo = []
        self.line_anchor = None       # estado de linea/curva en curso
        self._cursor = None
        self._rotate_cursor = None    # cursor custom de rotacion (lazy)
        self._hover_node = -1         # hueso cuyo NODO esta bajo el mouse (hover)
        self._preview = None          # (surface, label, anchor_x, y) hover preview
        self._sv_key = None           # cache del cuadro Saturacion/Valor
        self._sv_surf = None
        self._hue_surf = None

        # paneles redimensionables (soldados) + scroll de listas
        self.left_w = LEFT_W
        self.right_w = RIGHT_W
        self.time_h = TIME_H
        self.left_split = 0.5         # fraccion del panel izq para la lista de arriba
        self.split_drag = None        # "left"|"right"|"time"|"leftsplit"
        self.scroll_img = 0
        self.scroll_bone = 0
        self.scroll_draw = 0
        self.scroll_layer = 0
        self.clipboard = None         # ("layer"|"pixels"|"sprite"|"bone", data)

        # proyecto por defecto: editables en <root>/<src_dir>, export espejo a assets
        _cfg = config.load()
        self.project_root = _cfg.get("project_root")
        self.src_dir = _cfg.get("src_dir", "art-src")
        self.assets_dir = _cfg.get("assets_dir", "assets")

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
        self._last_row_click = None    # (edit_tuple, ms) para detectar doble clic
        self._edit_sel_all = None      # tupla de edicion con TODO seleccionado
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
        self.rmb_down = False
        self.wheel = 0

        self._thumbs = []
        self._thumbs_dirty = True
        self._fold = {"assign": True}   # 'asignar' colapsado (se abre al cargar plantilla)
        self._right_scroll = 0     # desplazamiento vertical del panel derecho
        self.modal = None          # ("template", [(nombre,ruta)...]) | None
        self._drawing_modal = False

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
            if not self._handle_splitters():
                self._handle_canvas()
            self._autosave_tick()
            self.update_caption()
            self._update_cursor()
            self._draw()
            self.prev_mouse = self.mouse
            pygame.display.flip()
        pygame.quit()

    def _poll_events(self):
        self.lmb_down = False
        self.rmb_down = False
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
                elif e.button == 3:
                    self.rmb_down = True
                elif e.button == 2:
                    self.pan = (e.pos, self.cam_x, self.cam_y, self.pcx, self.pcy)
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

    def _save_screenshot(self):
        # F12: guarda la ventana del editor en docs/screenshots/ (PNG).
        # ponytail: contador en vez de timestamp, sin depender de la hora.
        out = os.path.join(os.getcwd(), "docs", "screenshots")
        os.makedirs(out, exist_ok=True)
        n = 1
        while os.path.isfile(os.path.join(out, f"shot_{n:03d}.png")):
            n += 1
        path = os.path.join(out, f"shot_{n:03d}.png")
        pygame.image.save(self.screen, path)
        self.status = f"Captura guardada: docs/screenshots/shot_{n:03d}.png"

    def _hotkey(self, key):
        if self.modal is not None:
            if key == pygame.K_ESCAPE:
                self.modal = None
            return
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
            elif key == pygame.K_c:
                self.copy_active()
            elif key == pygame.K_v:
                self.paste_clipboard()
            elif key == pygame.K_d:
                self.duplicate_active()
            return
        if key == pygame.K_TAB:
            self.toggle_mode()
            return
        if key == pygame.K_F1:
            self.show_help = not self.show_help
            return
        if key == pygame.K_F12:
            self._save_screenshot()
            return
        if self.mode == "paint":
            self._hotkey_paint(key)
            return
        # ---- modo ANIMAR ----
        if key == pygame.K_v:
            self.tool, self.link_bone = "select", None
        elif key == pygame.K_b and self.project.kind != "ropa":
            self.tool, self.link_bone = "bone", None
        elif key == pygame.K_c:
            self.tool, self.link_bone = "link", None
            self.status = "Enlace: clic en un hueso y luego en una imagen."
        elif key == pygame.K_e:
            if self.tool == "scale":                 # re-pulsar E alterna el modo
                self.scale_mode = ("materials" if self.scale_mode == "bones"
                                   else "bones")
            else:
                self.tool, self.link_bone = "scale", None
            modo = ("ESQUELETO (huesos)" if self.scale_mode == "bones"
                    else "MATERIALES (arte)")
            self.status = (f"Escalar [{modo}]: arrastra horizontal. E alterna modo. "
                           "Afecta todas las animaciones.")
        elif key == pygame.K_m:
            self.tool, self.link_bone = "move", None
            self.status = ("Mover: arrastra para reubicar TODO el personaje en "
                           "todas las animaciones (no descuadra los frames).")
        elif key == pygame.K_h:
            self.tool, self.link_bone = "hand", None
        elif key == pygame.K_k:
            self.capture_frame()
        elif key == pygame.K_SPACE:
            self.toggle_play()
        elif key == pygame.K_DELETE:
            self.delete_selected()
        elif key == pygame.K_F2:
            self.rename_selected()
        elif key == pygame.K_ESCAPE:
            if self.link_bone is not None:
                self.link_bone = None
                self.status = "Enlace cancelado."
            else:
                self.sel_kind, self.sel_idx = None, -1

    PAINT_KEYS = {
        pygame.K_p: "pencil", pygame.K_e: "eraser", pygame.K_c: "shade",
        pygame.K_b: "bucket", pygame.K_o: "eyedropper", pygame.K_h: "hand",
        pygame.K_l: "line", pygame.K_j: "curve", pygame.K_w: "wand",
        pygame.K_s: "select", pygame.K_m: "move", pygame.K_k: "scale",
    }

    def _hotkey_paint(self, key):
        if key in self.PAINT_KEYS:
            self.ptool = self.PAINT_KEYS[key]
            self.line_anchor = None
            return
        if key == pygame.K_LEFTBRACKET:
            self.paint.brush = max(1, self.paint.brush - 1)
        elif key == pygame.K_RIGHTBRACKET:
            self.paint.brush = min(32, self.paint.brush + 1)
        elif key == pygame.K_x:
            self.paint.color, self.paint.color2 = self.paint.color2, self.paint.color
        elif key == pygame.K_DELETE:
            self.paint_clear_pixels()
        elif key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self.commit_curve()
        elif key == pygame.K_F2:
            self.rename_active_layer()
        elif key == pygame.K_ESCAPE:
            if self.line_anchor is not None:
                self.line_anchor = None
            else:
                self.paint.sel_mask = None

    # -- modos -----------------------------------------------------------
    def toggle_mode(self):
        if self.mode == "paint" and self.is_tile:
            # un tile es pintura pura: no tiene esqueleto ni modo Animar
            self.status = ("Un tile es pintura pura (sin esqueleto): cada "
                           "dibujo del taller es un frame de la tira.")
            return
        if self.mode == "animate":
            self.mode = "paint"
            self.playing = False
            self.paint.sel_mask = None
            self.line_anchor = None
            if self.paint_target() is None:
                if self.project.drawings:
                    self.draw_idx = 0
                else:
                    self.status = ("Taller de dibujo. Crea uno con 'Nuevo "
                                   "dibujo' y, al terminar, 'Enviar como material'.")
            # Si el lienzo activo está VACÍO, sincronízalo con el tile actual
            # (así cambiar el tamaño en Animar y pasar a Pintar "simplemente
            # funciona"). No se toca un dibujo con contenido.
            d = self.paint_target()
            tw, th = self.project.tile_w, self.project.tile_h
            if d is not None and d.size != (tw, th):
                bb = d.surface.get_bounding_rect(min_alpha=1) if d.surface else None
                if not bb or bb.width == 0:        # lienzo vacío
                    self.resize_active_drawing(tw, th)
            self._fit_canvas_view()
            if self.paint_target() is not None:
                self.status = "Modo PINTAR (taller). Tab vuelve a Animar."
        else:
            self.mode = "animate"
            self.line_anchor = None
            self.status = "Modo ANIMAR."

    def paint_target(self):
        """Dibujo activo del taller (independiente de los materiales)."""
        if 0 <= self.draw_idx < len(self.project.drawings):
            return self.project.drawings[self.draw_idx]
        return None

    def _fit_canvas_view(self):
        sp = self.paint_target()
        if sp is None or sp.surface is None:
            self.pcx, self.pcy = 32.0, 64.0
            return
        w, h = sp.size
        self.pcx, self.pcy = w / 2.0, h / 2.0
        c = getattr(self, "r_canvas", None)
        if c and c.w and c.h and w and h:
            # min 0.05: permite ALEJAR para que un lienzo grande (p.ej. 1700x1000)
            # entre completo en la vista (antes el tope era 1.0 y se salia).
            self.pzoom = max(0.05, min(24.0, min((c.w - 60) / w, (c.h - 60) / h)))

    # -- edicion de texto inline -----------------------------------------
    def rename_selected(self):
        if self.sel_kind == "sprite" and self.selected_sprite():
            self.editing = ("rename_sprite", self.sel_idx)
            self.edit_buf = self.selected_sprite().name
        elif self.sel_kind == "bone" and self.selected_bone():
            self.editing = ("rename_bone", self.sel_idx)
            self.edit_buf = self.selected_bone().name
        else:                                   # nada seleccionado: la animacion
            self.rename_clip()

    def _edit_all_selected(self):
        return self.editing is not None and self._edit_sel_all == self.editing

    def _draw_edit_buf(self, x, y):
        """Dibuja el texto en edicion con cursor, o resaltado si esta TODO
        seleccionado (Ctrl+A). Usado por todos los campos de renombrar."""
        txt = self.edit_buf
        if self._edit_all_selected() and txt:
            w = self.font_s.size(txt)[0]
            pygame.draw.rect(self.screen, (60, 95, 150),
                             pygame.Rect(x - 1, y - 1, w + 2, 16))
            self.text(txt, (x, y), TEXT, font=self.font_s)
        else:
            caret = "|" if (pygame.time.get_ticks() // 400) % 2 else ""
            self.text(txt + caret, (x, y), TEXT, font=self.font_s)

    def _edit_key(self, e):
        ctrl = pygame.key.get_mods() & pygame.KMOD_CTRL
        if ctrl and e.key == pygame.K_a:          # Ctrl+A: seleccionar todo
            self._edit_sel_all = self.editing
            return
        if e.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self._commit_rename()
        elif e.key == pygame.K_ESCAPE:
            self.editing = None
        elif e.key in (pygame.K_BACKSPACE, pygame.K_DELETE):
            if self._edit_all_selected():         # borra TODO de una
                self.edit_buf = ""
            elif e.key == pygame.K_BACKSPACE:
                self.edit_buf = self.edit_buf[:-1]
            self._edit_sel_all = None
        elif e.unicode and e.unicode.isprintable():
            if self._edit_all_selected():         # teclear REEMPLAZA lo seleccionado
                self.edit_buf = ""
            self._edit_sel_all = None
            if len(self.edit_buf) < 40:
                self.edit_buf += e.unicode

    def _num_field(self, x, w, y, key, label, value):
        """Campo numérico EDITABLE escribiendo (clic -> teclea -> Enter). Para el
        tamaño del lienzo (tile_w/tile_h) y la caja (box_x/box_y)."""
        self.text(label, (x + 4, y + 4), TEXT, font=self.font_s)
        rect = pygame.Rect(x + 90, y, w - 90, 22)
        editing = self.editing == ("edit_num", key)
        hot = rect.collidepoint(self.mouse)
        col = ACTIVE if editing else (HOVER if hot else PANEL2)
        pygame.draw.rect(self.screen, col, rect, border_radius=3)
        pygame.draw.rect(self.screen, LINE, rect, 1, border_radius=3)
        if editing:
            caret = "|" if (pygame.time.get_ticks() // 400) % 2 else ""
            self.text(self.edit_buf + caret, (rect.right - 6, rect.centery),
                      TEXT, font=self.font_s, right=True)
        else:
            self.text(f"{value:g}", (rect.right - 6, rect.centery), TEXT,
                      font=self.font_s, right=True)
            self.text("escribe", (rect.x + 6, rect.centery - 7), DIM,
                      font=self.font_s)
        if self.lmb_down and hot and not editing:
            if self.editing and self.editing[0] == "edit_num":
                self._commit_rename()        # confirma el campo anterior
            self.editing = ("edit_num", key)
            self.edit_buf = f"{value:g}"
            self.lmb_down = False

    def _commit_rename(self):
        kind, idx = self.editing
        new = self.edit_buf.strip()
        self.editing = None
        if kind == "edit_num":
            try:
                val = float(new)
            except ValueError:
                return
            if idx in ("tile_w", "tile_h"):
                setattr(self.project, idx, max(1, int(round(val))))
            elif idx == "export_crop_h":
                h = int(round(val))
                self.project.export_crop_h = h if h > 0 else None
            elif idx == "clothes_z":
                z = int(round(val))
                self.project.clothes_z = z if z > 0 else None
            else:
                setattr(self.project, idx, val)
            self._thumbs_dirty = True
            return
        if not new:
            return
        if kind == "rename_sprite" and idx < len(self.project.sprites):
            old = self.project.sprites[idx].name
            if new == old:
                return
            self.snapshot()
            new = self.project.unique_sprite_name(new)
            self.project.sprites[idx].name = new
            for c in self.project.clips:          # conserva los 'ocultos' por frame
                for fr in c.frames:
                    if old in fr.hidden:
                        fr.hidden.discard(old)
                        fr.hidden.add(new)
        elif kind == "rename_bone" and idx < len(self.project.bones):
            old = self.project.bones[idx].name
            if new == old:
                return
            self.snapshot()
            new = self.project.unique_bone_name(new)
            self.project.bones[idx].name = new
            if old in self.working:
                self.working[new] = self.working.pop(old)
            for f in self.all_frames():
                if old in f.poses:
                    f.poses[new] = f.poses.pop(old)
            for s in self.project.sprites:
                if s.bone == old:
                    s.bone = new
        elif kind == "rename_layer":
            sp = self.paint_target()
            if sp and idx < len(sp.layers):
                self.snapshot()
                sp.layers[idx].name = new
        elif kind == "rename_drawing":
            if idx < len(self.project.drawings):
                self.snapshot()
                self.project.drawings[idx].name = self._unique_drawing_name(new)
        elif kind == "rename_clip":
            if idx < len(self.project.clips):
                self.snapshot()
                self.project.clips[idx].name = self._unique_clip_name(new, skip=idx)
        self._thumbs_dirty = True

    # ====================================================================
    # layout / camara
    # ====================================================================
    def layout(self):
        w, h = self.screen.get_size()
        # clamps para que ningun panel se coma el lienzo
        self.time_h = max(90, min(h - TOP_H - 120, self.time_h))
        self.left_w = max(150, min(w - self.right_w - 200, self.left_w))
        self.right_w = max(180, min(w - self.left_w - 200, self.right_w))
        body_h = h - TOP_H - self.time_h
        self.r_top = pygame.Rect(0, 0, w, TOP_H)
        self.r_time = pygame.Rect(0, h - self.time_h, w, self.time_h)
        self.r_left = pygame.Rect(0, TOP_H, self.left_w, body_h)
        self.r_right = pygame.Rect(w - self.right_w, TOP_H, self.right_w, body_h)
        self.r_canvas = pygame.Rect(self.left_w, TOP_H,
                                    w - self.left_w - self.right_w, body_h)

    # bordes arrastrables entre paneles (siempre soldados)
    def _splitter_rects(self):
        w, h = self.screen.get_size()
        body_top, body_bot = TOP_H, h - self.time_h
        sy = body_top + int((body_bot - body_top) * self.left_split)
        return {
            "left":  pygame.Rect(self.left_w - 3, body_top, 6, body_bot - body_top),
            "right": pygame.Rect(w - self.right_w - 3, body_top, 6,
                                 body_bot - body_top),
            "time":  pygame.Rect(0, h - self.time_h - 3, w, 6),
            "leftsplit": pygame.Rect(0, sy - 3, self.left_w, 6),
        }

    def _handle_splitters(self):
        if self.modal is not None:
            return False
        w, h = self.screen.get_size()
        rects = self._splitter_rects()
        if self.split_drag is None and self.lmb_down:
            # prioridad: bordes principales antes que el interno
            for key in ("left", "right", "time", "leftsplit"):
                if rects[key].collidepoint(self.mouse):
                    self.split_drag = key
                    self.lmb_down = False     # no activar widgets debajo
                    break
        if self.split_drag is None:
            return False
        if not self.lmb_held:
            self.split_drag = None
            return False
        mx, my = self.mouse
        if self.split_drag == "left":
            self.left_w = mx
        elif self.split_drag == "right":
            self.right_w = w - mx
        elif self.split_drag == "time":
            self.time_h = h - my
            self._thumbs_dirty = True
        elif self.split_drag == "leftsplit":
            self.left_split = max(0.18, min(0.82,
                                  (my - TOP_H) / max(1, (h - self.time_h - TOP_H))))
        self.layout()
        return True

    def _draw_splitters(self):
        for key, r in self._splitter_rects().items():
            hot = r.collidepoint(self.mouse) or self.split_drag == key
            col = ACCENT if (self.split_drag == key) else (HOVER if hot else LINE)
            if key in ("left", "right"):
                x = r.centerx
                pygame.draw.line(self.screen, col, (x, r.y + 2), (x, r.bottom - 2),
                                 2 if hot else 1)
            else:
                y = r.centery
                x2 = self.left_w if key == "leftsplit" else self.screen.get_width()
                pygame.draw.line(self.screen, col, (r.x, y), (x2, y),
                                 2 if hot else 1)

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

    # -- clips (animaciones) ---------------------------------------------
    @property
    def clip(self):
        if 0 <= self.cur_clip < len(self.project.clips):
            return self.project.clips[self.cur_clip]
        return None

    @property
    def frames(self):
        c = self.clip
        return c.frames if c else []

    def all_frames(self):
        return [f for c in self.project.clips for f in c.frames]

    def pose_for(self):
        def lookup(idx):
            b = self.project.bones[idx]
            if b.anchor:                     # anclas/sockets: offset fijo (reposo)
                return b.rest
            return self.working.get(b.name, b.rest)
        return lookup

    def _current_hidden(self):
        """Materiales NO mostrados ahora mismo: en un frame, los de ese frame;
        en reposo, los que tienen visible global apagado."""
        if self.cur_frame >= 0:
            return set(self.frames[self.cur_frame].hidden)
        return {s.name for s in self.project.sprites if not s.visible}

    def display_frame(self):
        f = model.Frame("__work__")
        f.poses = self.working
        f.hidden = self._current_hidden()
        return f

    def active_frame(self):
        if self.playing and self.frames:
            return self.frames[self.play_i % len(self.frames)]
        return self.display_frame()

    def sync_working(self):
        self.working = {}
        for b in self.project.bones:
            # los anclas/sockets usan SIEMPRE su reposo (offset fijo al padre)
            if b.anchor or self.cur_frame < 0:
                self.working[b.name] = model.clone_pose(b.rest)
            else:
                fr = self.frames[self.cur_frame]
                self.working[b.name] = model.clone_pose(fr.poses.get(b.name, b.rest))

    def _write_pose(self, bone_idx):
        b = self.project.bones[bone_idx]
        pose = model.clone_pose(self.working[b.name])
        # un ancla/socket guarda su offset en REPOSO (vale para todas las anims);
        # un hueso normal en el frame actual (o en reposo si no hay frame).
        if b.anchor or self.cur_frame < 0:
            b.rest = pose
        else:
            self.frames[self.cur_frame].poses[b.name] = pose
            self._thumbs_dirty = True
        self.dirty = True

    def apply_global_scale(self, f, pivot):
        """Reescala TODO el personaje por el factor f respecto a `pivot`, afectando
        a TODAS las animaciones. Solo toca huesos RAIZ (pose de reposo + cada
        frame) y sprites libres: el resto del rig hereda la escala por la cadena
        padre->hijo, asi que no hay que tocar huesos hijos ni sprites vinculados.
        """
        if f == 1.0:
            return
        cx, cy = pivot

        def sc(p):
            p["x"] = cx + (p["x"] - cx) * f
            p["y"] = cy + (p["y"] - cy) * f
            p["scale"] = p.get("scale", 1.0) * f

        roots = {b.name for b in self.project.bones if b.parent < 0}
        for b in self.project.bones:
            if b.name in roots:
                sc(b.rest)
        for c in self.project.clips:
            for fr in c.frames:
                for name in roots:
                    if name in fr.poses:
                        sc(fr.poses[name])
        for s in self.project.sprites:
            if not s.bone:
                sc(s.transform)
        self.sync_working()
        self.dirty = True
        self._thumbs_dirty = True

    def apply_material_scale(self, f):
        """Escala SOLO el tamano de los materiales (el arte) por el factor f, SIN
        tocar el esqueleto: multiplica la escala propia de cada sprite (local si
        esta vinculado a un hueso, transform si es libre). Los huesos y las poses
        no cambian, asi que cada pieza crece/encoge anclada en su sitio, en TODAS
        las animaciones. Util cuando el dibujo quedo chico/grande para el rig."""
        if f == 1.0:
            return
        for s in self.project.sprites:
            t = s.local if s.bone else s.transform
            t["scale"] = t.get("scale", 1.0) * f
        self.dirty = True
        self._thumbs_dirty = True

    def apply_global_move(self, dx, dy):
        """Desplaza TODO el personaje por (dx, dy) en mundo, en TODAS las
        animaciones. Aplica el MISMO delta al reposo y a cada frame, asi las
        posiciones relativas entre frames no cambian (no descuadra la altura).
        Igual que la escala: solo huesos RAIZ + sprites libres; el resto hereda.
        """
        if dx == 0.0 and dy == 0.0:
            return

        def mv(p):
            p["x"] += dx
            p["y"] += dy

        roots = {b.name for b in self.project.bones if b.parent < 0}
        for b in self.project.bones:
            if b.name in roots:
                mv(b.rest)
        for c in self.project.clips:
            for fr in c.frames:
                for name in roots:
                    if name in fr.poses:
                        mv(fr.poses[name])
        for s in self.project.sprites:
            if not s.bone:
                mv(s.transform)
        self.sync_working()
        self.dirty = True
        self._thumbs_dirty = True

    # ====================================================================
    # historial / dirty / recuperacion / caption
    # ====================================================================
    def snapshot(self):
        self.history.push(self.project.to_dict())
        self.dirty = True

    def _restore(self, d):
        self.project = model.Project.from_dict(d)
        render.ensure_surfaces(self.project)
        if self.is_item:                  # re-injerta el rig del body referenciado
            self._attach_ref_body()
        self.sel_kind, self.sel_idx = None, -1
        self.cur_clip = max(0, min(self.cur_clip, len(self.project.clips) - 1))
        self.cur_frame = min(self.cur_frame, len(self.frames) - 1)
        self.editing = None
        self.sync_working()
        self.paint_undo.clear()
        self.paint_redo.clear()
        self._thumbs_dirty = True
        self.dirty = True

    def undo(self):
        # en modo Pintar, Ctrl+Z deshace primero los trazos de pixel
        if self.mode == "paint" and self.paint_undo:
            sp, layer, before = self.paint_undo.pop()
            self.paint_redo.append((sp, layer, layer.surface.copy()))
            layer.surface = before
            render.flatten_sprite(sp)
            self._thumbs_dirty = True
            self.dirty = True
            self.status = "Deshacer (pixeles)."
            return
        d = self.history.undo(self.project.to_dict())
        if d is not None:
            self._restore(d)
            self.status = "Deshacer."

    def redo(self):
        if self.mode == "paint" and self.paint_redo:
            sp, layer, after = self.paint_redo.pop()
            self.paint_undo.append((sp, layer, layer.surface.copy()))
            layer.surface = after
            render.flatten_sprite(sp)
            self._thumbs_dirty = True
            self.dirty = True
            self.status = "Rehacer (pixeles)."
            return
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
    # conexiones (sockets)
    # ====================================================================
    def cycle_connection(self, sprite_idx, direction):
        """Asigna a un material el socket al que se pega (centro -> punto)."""
        sp = self.project.sprites[sprite_idx]
        options = [None] + list(model.SOCKETS)
        cur = sp.connection if sp.connection in options else None
        self.snapshot()
        sp.connection = options[(options.index(cur) + direction) % len(options)]
        self.dirty = True
        self.status = (f"Material '{sp.name}' se pega a "
                       f"'{sp.connection}'." if sp.connection
                       else f"Material '{sp.name}' sin conexion.")

    # posicion por defecto de cada socket dentro del tile (fracciones x,y) cuando
    # se crea SIN un hueso seleccionado -> cada uno cae en un sitio logico.
    _SOCKET_DEFAULT = {
        "pelo": (0.50, 0.08), "ojos": (0.50, 0.18), "nariz": (0.50, 0.25),
        "boca": (0.50, 0.31), "mano_izq": (0.18, 0.55), "mano_der": (0.82, 0.55),
        "pierna_izq": (0.40, 0.74), "pierna_der": (0.60, 0.74),
        "zapato_izq": (0.40, 0.95), "zapato_der": (0.60, 0.95),
    }

    # sockets de la CARA: su posicion se deriva del hueso de la cabeza, NO del
    # tile. t = fraccion a lo largo del hueso, 0 = punta (corona) .. 1 = base
    # (cuello). Asi pelo/ojos/nariz/boca caen siempre SOBRE la cabeza real,
    # cualquiera sea su tamano o posicion (estilo cara distribuida).
    _FACE_T = {"pelo": 0.05, "ojos": 0.30, "nariz": 0.52, "boca": 0.72}

    def _head_bone_idx(self):
        """Indice del hueso 'cabeza' (o -1). Si ya hay un socket facial enganchado,
        la cabeza es su padre (el perfil del rig deja de detectarla en cuanto la
        cabeza tiene un hijo anclado, asi que esto lo hace robusto)."""
        for b in self.project.bones:
            if b.name in self._FACE_T and b.parent >= 0:
                return b.parent
        try:
            prof = templates.rig_profile(self.project)
        except Exception:
            prof = None
        h = prof.get("head") if prof else None
        return h if (h is not None and 0 <= h < len(self.project.bones)) else -1

    def create_socket(self, sid):
        """Crea (o selecciona) el punto de conexion 'sid' en el cuerpo. Es un
        anchor con nombre reservado: sigue el rig por frame como cualquier hueso.

        - Sockets de la CARA (pelo/ojos/nariz/boca): se colocan SOBRE el hueso de
          la cabeza (el seleccionado, o el detectado por el perfil del rig) y se
          enganchan a el -> toda la cara sigue la cabeza y queda a su tamano.
        - Otros sockets: posicion logica en el tile; hijos del hueso seleccionado.
        """
        lbl = model.SOCKET_LABELS.get(sid, sid)
        idx = self.project.bone_by_name(sid)
        if idx >= 0:                                    # ya existe -> seleccionar
            self.project.bones[idx].anchor = True
            self.sel_kind, self.sel_idx = "bone", idx
            self.status = (f"Punto '{lbl}' ya existe: seleccionado. Arrastralo, "
                           "o 'Borrar hueso (Supr)' para quitarlo.")
            return
        self.snapshot()
        b = model.Bone(sid)
        b.anchor = True
        b.length = 10.0

        sel_bone = self.selected_bone() if self.sel_kind == "bone" else None
        # solo se pega a un hueso del RIG (no a otro socket: evita encadenarlos).
        if sel_bone is not None and sel_bone.name in model.SOCKETS:
            sel_bone = None

        # referencia para la CARA: el hueso elegido o la cabeza detectada.
        ref = (self.sel_idx if sel_bone is not None
               else (self._head_bone_idx() if sid in self._FACE_T else -1))

        if sid in self._FACE_T and ref >= 0:
            # posicion = punto a lo largo del hueso de la cabeza (corona->cuello)
            hw = model.bone_world(self.project, ref, self.pose_for())
            hx, hy = hw[0], hw[1]
            tx, ty = model.bone_tip(self.project, ref, hw)
            t = self._FACE_T[sid]
            wx = tx + (hx - tx) * t                     # t=0 corona, t=1 cuello
            wy = ty + (hy - ty) * t
            parent_idx = ref
        else:
            # fallback: posicion logica en el tile (manos, piernas, o sin cabeza)
            fx, fy = self._SOCKET_DEFAULT.get(sid, (0.5, 0.5))
            wx = self.project.box_x + self.project.tile_w * fx
            wy = self.project.box_y + self.project.tile_h * fy
            parent_idx = self.sel_idx if sel_bone is not None else -1

        if parent_idx >= 0:             # HIJO del hueso: se mueve con el, sin saltar
            pw = model.bone_world(self.project, parent_idx, self.pose_for())
            dx, dy = wx - pw[0], wy - pw[1]
            aa = math.radians(-pw[2])
            cc, ss = math.cos(aa), math.sin(aa)
            psc = pw[3] or 1.0
            b.parent = parent_idx
            b.rest = {"x": (dx * cc - dy * ss) / psc,
                      "y": (dx * ss + dy * cc) / psc,
                      "rot": -pw[2], "scale": 1.0}
            pname = self.project.bones[parent_idx].name
            msg = (f"'{lbl}' colocado sobre la cabeza ('{pname}') y enlazado a "
                   "ella: toda la cara la sigue.")
        else:                                           # punto libre en su sitio
            b.parent = -1
            b.rest = {"x": wx, "y": wy, "rot": 0.0, "scale": 1.0}
            msg = (f"Punto '{lbl}' creado. Selecciona el hueso de la cabeza y "
                   "pulsa de nuevo para enlazar toda la cara a el.")
        self.project.bones.append(b)
        self.working[b.name] = model.clone_pose(b.rest)
        self.sel_kind, self.sel_idx = "bone", len(self.project.bones) - 1
        self.dirty = True
        self.status = msg

    # ====================================================================
    # plantillas (esqueleto + animaciones reutilizables)
    # ====================================================================
    def open_template_picker(self):
        self.modal = ("template", templates.list_templates())

    def open_export_menu(self):
        if self.is_tile:                     # tile: un solo formato de salida
            self.export_tile()
            return
        self.modal = ("export", None)

    def save_current_as_template(self):
        if not self.project.bones:
            self.status = "La plantilla necesita huesos (rig) para reutilizarse."
            return
        path = dialogs.save_template_as()
        if not path:
            return
        try:
            templates.strip_art(self.project).save(path)
            n = len(self.project.clips)
            self.status = (f"Plantilla guardada: {os.path.basename(path)} "
                           f"({len(self.project.bones)} huesos, {n} animaciones).")
        except Exception as e:
            self.status = f"Error al guardar plantilla: {e}"

    def load_template(self, path):
        try:
            pr = templates.load_template(path)
        except Exception as e:
            self.status = f"No se pudo cargar la plantilla: {e}"
            return
        self.snapshot()
        # la plantilla SOLO aporta rig + animaciones: conserva tus DIBUJOS del
        # taller (modo Pintar), que son tu arte y no dependen del esqueleto.
        kept_drawings = self.project.drawings
        self.project = pr
        self.project.drawings = kept_drawings
        self.sel_kind, self.sel_idx = None, -1
        self.cur_clip = 0
        self.cur_frame = -1
        self.draw_idx = min(self.draw_idx, len(kept_drawings) - 1)
        self.sync_working()
        self._thumbs_dirty = True
        self.dirty = True
        self._fold["assign"] = False        # abrir el asistente
        kept = (f" Se conservaron {len(kept_drawings)} dibujo(s) del taller."
                if kept_drawings else "")
        self.status = (f"Plantilla cargada ({len(pr.bones)} huesos, "
                       f"{len(pr.clips)} animaciones). Importa tu arte y asignalo "
                       "a los huesos (panel derecho)." + kept)

    def _sprite_centroid_world(self, sp):
        """Centro del CONTENIDO del sprite en mundo (mejor que el pivot para
        decidir a que hueso pertenece)."""
        wt = model.sprite_world(self.project, sp, self.pose_for())
        if sp.content_rect:
            cx, cy, cw, ch = sp.content_rect
            mx, my = cx + cw / 2.0, cy + ch / 2.0
        else:
            mx = my = 0.0
        ox, oy = model._rot((mx - sp.pivot[0]) * wt[3],
                            (my - sp.pivot[1]) * wt[3], wt[2])
        return wt[0] + ox, wt[1] + oy

    def _content_center_img(self, sp):
        """Centro del contenido en pixeles de la imagen (o el pivot si no hay)."""
        if sp.content_rect:
            cx, cy, cw, ch = sp.content_rect
            return (cx + cw / 2.0, cy + ch / 2.0)
        return (sp.pivot[0], sp.pivot[1])

    def _sprite_corners_screen(self, sp):
        """4 esquinas del contenido del sprite en pantalla (rotadas con el)."""
        if not sp.content_rect:
            return []
        wt = model.sprite_world(self.project, sp, self.pose_for())
        cx, cy, cw, ch = sp.content_rect
        out = []
        for ix, iy in ((cx, cy), (cx + cw, cy), (cx + cw, cy + ch), (cx, cy + ch)):
            ox, oy = model._rot((ix - sp.pivot[0]) * wt[3],
                                (iy - sp.pivot[1]) * wt[3], wt[2])
            out.append(self.w2s(wt[0] + ox, wt[1] + oy))
        return out

    def _near_sprite_corner(self, sp, r=13):
        return any(math.hypot(self.mouse[0] - sx, self.mouse[1] - sy) < r
                   for sx, sy in self._sprite_corners_screen(sp))

    def _set_sprite_rot_keep_center(self, sp, newrot, C):
        """Fija la rotacion MUNDO del sprite a `newrot` manteniendo fijo el punto
        `C` (centro del contenido en mundo): la pieza rota EN SU SITIO, no orbita
        un pivot lejano. Ajusta el offset (local si esta vinculado, transform si
        es libre) para compensar."""
        mx, my = self._content_center_img(sp)
        if sp.bone and self.project.bone_by_name(sp.bone) >= 0:
            bidx = self.project.bone_by_name(sp.bone)
            bx, by, brot, bscale = model.bone_world(self.project, bidx,
                                                    self.pose_for())
            wscale = bscale * sp.local.get("scale", 1.0)
            sp.local["rot"] = newrot - brot
            dx, dy = model._rot((mx - sp.pivot[0]) * wscale,
                                (my - sp.pivot[1]) * wscale, newrot)
            pwx, pwy = C[0] - dx, C[1] - dy          # pos mundo deseada del pivot
            rx, ry = model._rot(pwx - bx, pwy - by, -brot)
            sc = bscale or 1e-6
            sp.local["x"], sp.local["y"] = rx / sc, ry / sc
        else:
            t = sp.transform
            scale = t.get("scale", 1.0)
            t["rot"] = newrot
            dx, dy = model._rot((mx - sp.pivot[0]) * scale,
                                (my - sp.pivot[1]) * scale, newrot)
            t["x"], t["y"] = C[0] - dx, C[1] - dy

    def _get_rotate_cursor(self):
        """Cursor custom de rotacion (flecha circular), cacheado."""
        if self._rotate_cursor is None:
            s = pygame.Surface((28, 28), pygame.SRCALPHA)
            rect = pygame.Rect(5, 5, 18, 18)
            cx, cy, a, b = 14, 14, 9, 9

            def pt(deg):
                t = math.radians(deg)
                return (cx + a * math.cos(t), cy - b * math.sin(t))

            for col, wdt in (((20, 20, 24), 5), ((245, 245, 250), 3)):
                pygame.draw.arc(s, col, rect, math.radians(25),
                                math.radians(305), wdt)
            pe, pp = pt(305), pt(290)                # punta de flecha tangente
            ddx, ddy = pe[0] - pp[0], pe[1] - pp[1]
            L = math.hypot(ddx, ddy) or 1
            ux, uy = ddx / L, ddy / L
            px, py = -uy, ux
            for col, sz in (((20, 20, 24), 6), ((245, 245, 250), 5)):
                tip = (pe[0] + ux * sz, pe[1] + uy * sz)
                ba = (pe[0] + px * sz, pe[1] + py * sz)
                bb = (pe[0] - px * sz, pe[1] - py * sz)
                pygame.draw.polygon(s, col, [tip, ba, bb])
            self._rotate_cursor = pygame.cursors.Cursor((14, 14), s)
        return self._rotate_cursor

    def auto_assign_bones(self):
        """Vincula cada sprite al HUESO (segmento) mas cercano a su contenido, no
        al torso por defecto: asi brazos/piernas caen en su hueso."""
        if not self.project.sprites or not self.project.bones:
            self.status = "Importa arte y carga una plantilla con huesos primero."
            return
        self.snapshot()
        pose = self.pose_for()
        segs = []
        for i, b in enumerate(self.project.bones):
            bw = model.bone_world(self.project, i, pose)
            tip = model.bone_tip(self.project, i, bw)
            segs.append((b.name, (bw[0], bw[1]), tip))
        for sp in self.project.sprites:
            cwx, cwy = self._sprite_centroid_world(sp)
            best, bd = None, 1e9
            for name, head, tip in segs:
                d = _seg_dist((cwx, cwy), head, tip)
                if d < bd:
                    bd, best = d, name
            if best:
                sw = model.sprite_world(self.project, sp, pose)
                bidx = self.project.bone_by_name(best)
                bw = model.bone_world(self.project, bidx, pose)
                sp.bone = best
                sp.local = model.compute_local(bw, sw)
        self._thumbs_dirty = True
        self.status = "Arte asignado por cercania al hueso. Revisa y corrige."

    def generate_draft_anims(self):
        """Anade animaciones BORRADOR (agacharse/sentado/atacar/cortar) al
        proyecto actual, para editarlas. No vienen en la plantilla por defecto."""
        if not self.project.bones:
            self.status = "Necesitas un rig (carga una plantilla) primero."
            return
        self.snapshot()
        added = templates.build_extra_animations(self.project)
        self._thumbs_dirty = True
        if added:
            self.status = ("Animaciones borrador anadidas: " + ", ".join(added) +
                           ". Son aproximadas: ajustalas en la linea de tiempo.")
        else:
            self.status = "No se anadieron (ya existian)."

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
        for f in self.all_frames():
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
    # copiar / pegar / duplicar (Ctrl+C / Ctrl+V / Ctrl+D)
    # ====================================================================
    def copy_active(self):
        if self.mode == "paint":
            sp, layer = self._active_layer()
            if layer is None:
                return
            if self.paint.sel_mask is not None:     # copiar solo lo seleccionado
                # mask -> surface a velocidad C (sin bucle Python por pixel).
                surf = self.paint.sel_mask.to_surface(
                    setsurface=layer.surface, unsetcolor=(0, 0, 0, 0))
                self.clipboard = ("pixels", surf)
                self.status = "Seleccion copiada (pega como capa con Ctrl+V)."
            else:
                self.clipboard = ("layer", layer.clone())
                self.status = f"Capa '{layer.name}' copiada."
        else:
            if self.sel_kind == "sprite" and self.selected_sprite():
                self.clipboard = ("sprite", self.selected_sprite().to_dict())
                self.status = "Material copiado."
            elif self.sel_kind == "bone" and self.selected_bone():
                self.clipboard = ("bone", self.selected_bone().to_dict())
                self.status = "Hueso copiado."

    def paste_clipboard(self):
        cb = self.clipboard
        if not cb:
            return
        kind = cb[0]
        if kind in ("layer", "pixels"):
            if self.mode != "paint":
                self.status = "Cambia a modo Pintar (Tab) para pegar la capa."
                return
            if self.paint_target() is None:
                self.new_drawing()
            sp = self.paint_target()
            self.snapshot()
            if kind == "layer":
                lay = cb[1].clone()
            else:
                lay = model.Layer("pegado", cb[1].copy())
            sp.layers.insert(sp.active_layer + 1, lay)
            sp.active_layer += 1
            self.paint_undo.clear(); self.paint_redo.clear()
            render.flatten_sprite(sp)
            self._thumbs_dirty = True
            self.status = "Pegado como capa nueva."
        elif kind == "sprite":
            if self.mode != "animate":
                return
            self.snapshot()
            sp = model.Sprite.from_dict(cb[1])
            sp.name = self.project.unique_sprite_name(sp.name)
            sp.bone = None                      # pega libre, sin vinculo
            sp.transform = dict(sp.transform)
            sp.transform["x"] += 8; sp.transform["y"] += 8
            sp.z = len(self.project.sprites)
            render.load_sprite_surface(sp, (self.project.tile_w, self.project.tile_h))
            self.project.sprites.append(sp)
            self.sel_kind, self.sel_idx = "sprite", len(self.project.sprites) - 1
            self._thumbs_dirty = True
            self.status = f"Material '{sp.name}' pegado."
        elif kind == "bone":
            if self.mode != "animate":
                return
            self.snapshot()
            b = model.Bone.from_dict(cb[1])
            b.name = self.project.unique_bone_name(b.name)
            b.rest = dict(b.rest)
            b.rest["x"] += 8; b.rest["y"] += 8
            self.project.bones.append(b)
            self.working[b.name] = model.clone_pose(b.rest)
            self.sel_kind, self.sel_idx = "bone", len(self.project.bones) - 1
            self._thumbs_dirty = True
            self.status = f"Hueso '{b.name}' pegado."

    def duplicate_active(self):
        if self.mode == "paint":
            self.layer_duplicate()
            return
        if self.sel_kind == "sprite" and self.selected_sprite():
            self.copy_active(); self.paste_clipboard()
        elif self.sel_kind == "bone" and self.selected_bone():
            self.copy_active(); self.paste_clipboard()
        elif self.cur_frame >= 0:
            self.duplicate_frame(self.cur_frame)
        else:
            self.status = "Nada que duplicar (selecciona material, hueso o frame)."

    # ====================================================================
    # frames
    # ====================================================================
    def capture_frame(self):
        if self.project.kind == "ropa":
            self.status = ("La ropa usa las animaciones del body; no se capturan "
                           "frames (dibuja y enlaza, se hornea solo).")
            return
        self.snapshot()
        f = model.Frame(f"f{len(self.frames)+1}")
        for b in self.project.bones:
            if b.anchor:                 # los anclas no se animan (offset fijo)
                continue
            f.poses[b.name] = model.clone_pose(self.working.get(b.name, b.rest))
        f.hidden = self._current_hidden()    # guarda lo que se esta mostrando
        self.frames.append(f)
        # SELECCIONAR el frame recien creado: lo que el usuario pose a partir de
        # ahora edita ESTE frame real (no la pose 'en vivo'/reposo, que confundia
        # con editar una copia). 'working' ya es esta pose, asi no hay salto.
        # Pulsar K otra vez captura un NUEVO frame a partir de estos cambios.
        self.cur_frame = len(self.frames) - 1
        self._thumbs_dirty = True
        self.status = (f"Frame {len(self.frames)} capturado y seleccionado: "
                       "tus cambios editan ESTE frame. Pulsa K para crear otro.")

    def select_frame(self, i):
        self.cur_frame = i
        self.sync_working()

    def delete_frame(self, i):
        if self._anim_locked():
            return
        if 0 <= i < len(self.frames):
            self.snapshot()
            del self.frames[i]
            self.cur_frame = min(self.cur_frame, len(self.frames) - 1)
            self.sync_working()
            self._thumbs_dirty = True

    def duplicate_frame(self, i):
        if self._anim_locked():
            return
        if 0 <= i < len(self.frames):
            self.snapshot()
            src = self.frames[i]
            f = model.Frame(src.name + "*")
            f.poses = {k: model.clone_pose(v) for k, v in src.poses.items()}
            f.hidden = set(src.hidden)
            self.frames.insert(i + 1, f)
            self.cur_frame = i + 1
            self.sync_working()
            self._thumbs_dirty = True

    def move_frame(self, i, d):
        j = i + d
        if 0 <= i < len(self.frames) and 0 <= j < len(self.frames):
            self.snapshot()
            fr = self.frames
            fr[i], fr[j] = fr[j], fr[i]
            self.cur_frame = j
            self._thumbs_dirty = True

    def toggle_play(self):
        if not self.frames:
            return
        self.playing = not self.playing
        self.play_t = 0.0
        self.play_i = 0

    def _update_play(self, dt):
        if not self.playing or not self.frames:
            return
        n = len(self.frames)
        dur = self.clip.duration if self.clip else 1.0
        step = max(0.02, dur / max(1, n))      # reparte la duracion entre los frames
        self.play_t += dt
        if self.play_t >= step:
            self.play_t -= step
            self.play_i = (self.play_i + 1) % n

    # -- clips / animaciones ---------------------------------------------
    def _unique_clip_name(self, base, skip=-1):
        names = {c.name for j, c in enumerate(self.project.clips) if j != skip}
        return self.project._unique(base, names)

    def _pose_from_frame(self, frame):
        """working = pose del frame dado (o de reposo si frame es None)."""
        self.working = {}
        for b in self.project.bones:
            if frame is not None and b.name in frame.poses:
                self.working[b.name] = model.clone_pose(frame.poses[b.name])
            else:
                self.working[b.name] = model.clone_pose(b.rest)

    def _anim_locked(self):
        if self.project.kind == "ropa":
            self.status = "La ropa hereda las animaciones del body (no editables)."
            return True
        return False

    def add_clip(self, seed_idx=None):
        """Crea una animacion basada en un frame (sin reproceso):
        - si hay un frame seleccionado (o se indica seed_idx), parte de ese;
        - si no, parte del PRIMER frame de la animacion actual;
        - si no hay frames, parte del reposo.
        Ese frame se siembra como el primero de la nueva animacion."""
        if self._anim_locked():
            return
        src = self.frames
        if seed_idx is None:
            seed_idx = self.cur_frame if self.cur_frame >= 0 else (0 if src else None)
        base = src[seed_idx] if (seed_idx is not None and 0 <= seed_idx < len(src)) else None
        self.snapshot()
        clip = model.Clip(self._unique_clip_name("animacion"))
        if base is not None:
            f = model.Frame("f1")
            f.poses = {k: model.clone_pose(v) for k, v in base.poses.items()}
            f.hidden = set(base.hidden)
            clip.frames.append(f)
        self.project.clips.append(clip)
        self.cur_clip = len(self.project.clips) - 1
        self.cur_frame = -1
        self.playing = False
        self._pose_from_frame(base)
        self._thumbs_dirty = True
        self.status = (f"Animacion '{clip.name}' creada desde un frame base; "
                       "posa y captura los siguientes."
                       if base is not None else f"Animacion '{clip.name}' creada.")

    def duplicate_clip(self, i=None):
        """Crea una animacion NUEVA copiando una existente entera (todos sus
        frames, duracion y tamano de recuadro). Punto de partida para una
        variante sin tocar la original."""
        if self._anim_locked():
            return
        if i is None:
            i = self.cur_clip
        if not (0 <= i < len(self.project.clips)):
            return
        src = self.project.clips[i]
        self.snapshot()
        clip = model.Clip(self._unique_clip_name(src.name), src.duration)
        clip.frames = [model.Frame.from_dict(f.to_dict()) for f in src.frames]
        clip.tile_w, clip.tile_h = src.tile_w, src.tile_h
        clip.box_x, clip.box_y = src.box_x, src.box_y
        self.project.clips.insert(i + 1, clip)
        self.cur_clip = i + 1
        self.cur_frame = 0 if clip.frames else -1
        self.playing = False
        self.sync_working()
        self._thumbs_dirty = True
        self.status = (f"Animacion '{clip.name}' creada como copia de "
                       f"'{src.name}' ({len(clip.frames)} frames).")

    def select_clip(self, i):
        if 0 <= i < len(self.project.clips) and i != self.cur_clip:
            self.cur_clip = i
            self.playing = False
            # mostrar el PRIMER frame como punto de partida
            self.cur_frame = 0 if self.clip.frames else -1
            self.sync_working()
            self._thumbs_dirty = True

    def delete_clip(self, i):
        if self._anim_locked() or not (0 <= i < len(self.project.clips)):
            return
        self.snapshot()
        del self.project.clips[i]
        if not self.project.clips:                # borrar la ultima -> una vacia
            self.project.clips = [model.Clip(self._unique_clip_name("animacion"))]
            self.status = "Animacion borrada. Queda una nueva vacia."
        else:
            self.status = "Animacion borrada."
        self.cur_clip = max(0, min(self.cur_clip, len(self.project.clips) - 1))
        self.cur_frame = -1
        self.playing = False
        self.sync_working()
        self._thumbs_dirty = True

    def rename_clip(self):
        if self.clip:
            self.editing = ("rename_clip", self.cur_clip)
            self.edit_buf = self.clip.name

    def _content_box(self, clip, margin=4):
        """bbox en mundo (bx, by, w, h) que contiene TODO el contenido de todos
        los frames del clip, con margen. None si no hay contenido."""
        sprites = [s for s in self.project.sprites
                   if s.visible and s.surface is not None and s.content_rect]
        if not sprites:
            return None
        frames = clip.frames or [None]
        minx = miny = 1e9
        maxx = maxy = -1e9
        for f in frames:
            pose_for = model.pose_for_frame(self.project, f)
            for sp in sprites:
                wt = model.sprite_world(self.project, sp, pose_for)
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

    def fit_clip_to_content(self, margin=4):
        """Ajusta el recuadro de la animacion activa para contener todos sus
        frames (lo que se sale por arriba o por los lados). Sin recortes."""
        clip = self.clip
        cb = self._content_box(clip, margin) if clip else None
        if cb is None:
            self.status = "No hay contenido para ajustar."
            return
        self.snapshot()
        clip.box_x = math.floor(cb[0])
        clip.box_y = math.floor(cb[1])
        clip.tile_w = int(math.ceil(cb[0] + cb[2])) - clip.box_x
        clip.tile_h = int(math.ceil(cb[1] + cb[3])) - clip.box_y
        self._thumbs_dirty = True
        self.status = (f"'{clip.name}' ajustado a {clip.tile_w}x{clip.tile_h} "
                       "(sin recortes).")

    def ensure_clips_fit(self, margin=4):
        """Expande (nunca encoge) el recuadro de cada animacion para que el
        contenido NUNCA se recorte. Se llama al exportar. Devuelve cuantas
        animaciones se agrandaron."""
        changed = 0
        for clip in self.project.clips:
            cb = self._content_box(clip, margin)
            if cb is None:
                continue
            cur = render.clip_box(self.project, clip)
            x0, y0 = min(cur[0], cb[0]), min(cur[1], cb[1])
            x1 = max(cur[0] + cur[2], cb[0] + cb[2])
            y1 = max(cur[1] + cur[3], cb[1] + cb[3])
            nw, nh = int(math.ceil(x1 - x0)), int(math.ceil(y1 - y0))
            if (nw > int(round(cur[2])) or nh > int(round(cur[3]))
                    or x0 < cur[0] - 0.5 or y0 < cur[1] - 0.5):
                if changed == 0:
                    self.snapshot()
                clip.box_x, clip.box_y = math.floor(x0), math.floor(y0)
                clip.tile_w, clip.tile_h = nw, nh
                changed += 1
        if changed:
            self._thumbs_dirty = True
        return changed

    # ====================================================================
    # archivo
    # ====================================================================
    # ====================================================================
    # nuevo elemento: body | item (ropa / caracteristica)
    # ====================================================================
    @property
    def is_item(self):
        return self.project.kind in ("ropa", "caracteristica", "cargable")

    @property
    def is_tile(self):
        return self.project.kind == "tile"

    def new_project(self):
        # asistente: primero pregunta si es un BODY o un ITEM
        self.modal = ("newkind", None)

    def _reset_for_new(self):
        self.ref_project = None
        self.sel_kind, self.sel_idx = None, -1
        self.cur_clip = 0
        self.cur_frame = -1
        self.draw_idx = -1
        self.working = {}
        self.history.clear()
        self.dirty = False
        self.recovery_data = None
        recovery.clear()
        self._thumbs_dirty = True

    def new_blank_project(self):
        self.modal = None
        self.project = model.Project()
        self._reset_for_new()
        self.status = "Proyecto en blanco."

    def new_body_project(self):
        """Body nuevo a partir del ESTANDAR (rig + animaciones, sin arte): el
        usuario dibuja su cuerpo y lo asigna a los huesos del estandar."""
        self.modal = None
        path = os.path.join(templates.BUILTIN_DIR, "humano.pbproj")
        if not os.path.isfile(path):
            self.new_blank_project()
            self.status = "No hay plantilla estandar; proyecto en blanco."
            return
        self.load_template(path)          # carga rig+anims del estandar
        self.project.kind = "body"
        self.project.drawings = []        # taller LIMPIO (proyecto nuevo)
        self.draw_idx = -1
        self.status = ("Body nuevo desde el ESTANDAR. Dibuja tu arte (Pintar) y "
                       "asignalo a los huesos.")

    def new_item_project(self, kind):
        """Item nuevo (ropa | caracteristica): referencia el body estandar como
        guia fantasma; toma de el rig/animaciones (ropa) o solo el ancho y los
        sockets (caracteristica)."""
        self.modal = None
        ref = templates.standard_body_path()
        if not ref:
            self.status = ("No hay cuerpo estandar. Crea un body y guardalo como "
                           "estandar, o configura 'standard_body'.")
            return
        self.project = model.Project()         # taller LIMPIO (proyecto nuevo)
        self.project.kind = kind
        self.project.ref_body = "@standard"
        self._reset_for_new()
        self._attach_ref_body()
        if kind == "cargable":
            # un cargable SIEMPRE tiene 2 frames: 0 = BRAZOS/correas (van DELANTE
            # del jugador), 1 = MALETIN (va DETRAS del body). Al exportar, pixelBones
            # agrega solo un 3er frame = combinacion (el icono del item).
            c = self.project.clips[0]
            c.name = "cargable"
            c.frames = [model.Frame("brazos"), model.Frame("maletin")]
            self.cur_frame = 0
            self.sync_working()
        lbl = {"ropa": "Ropa", "caracteristica": "Caracteristica",
               "cargable": "Cargable"}.get(kind, kind)
        tip = {"ropa": "Dibuja la prenda y enlazala a los huesos.",
               "caracteristica": "Dibuja la pieza y asignale una conexion (socket).",
               "cargable": ("Frame 1 = BRAZOS/correas (delante), frame 2 = MALETIN "
                            "(detras). 'Preview en body' para verlo; el icono lo "
                            "arma pixelBones al exportar.")
               }.get(kind, "")
        self.status = f"{lbl} nuevo sobre el body estandar (fantasma). {tip}"

    def new_tile_project(self, size=64, frames=1):
        """Tile / material del juego: lienzo CUADRADO y pintura pura (SIN
        esqueleto ni body de guia). Cada DIBUJO del taller es un frame de la
        tira; se exporta plano a <root>/<assets>/tiles/<nombre>.png."""
        self.modal = None
        size = max(1, int(size))
        frames = max(1, min(16, int(frames)))
        pr = model.Project()
        pr.kind = "tile"
        pr.tile_w = pr.tile_h = size
        pr.box_x, pr.box_y = 0.0, 0.0
        pr.clips = [model.Clip("tile")]      # sin huesos ni frames de pose
        self.project = pr
        self._reset_for_new()
        for i in range(frames):              # 1 dibujo = 1 frame de la tira
            d = model.Sprite(f"frame_{i + 1}", None)
            d.layers = [model.Layer(
                "base", pygame.Surface((size, size), pygame.SRCALPHA))]
            d.pivot = [size / 2.0, size / 2.0]
            render.flatten_sprite(d)
            pr.drawings.append(d)
        self.draw_idx = 0
        self.mode = "paint"                  # el tile se pinta, no se anima
        self.playing = False
        self.paint.sel_mask = None
        self.line_anchor = None
        self.paint_undo.clear()
        self.paint_redo.clear()
        self._fit_canvas_view()
        self.status = (f"Tile nuevo {size}x{size} ({frames} frame/s): 1 dibujo "
                       "= 1 frame. Pinta y usa 'Exportar' -> assets/tiles/.")

    # ---- referencia (body fantasma) ------------------------------------
    def _resolve_ref(self, ref):
        if ref in (None, "@standard"):
            return templates.standard_body_path()
        if os.path.isabs(ref):
            return ref if os.path.isfile(ref) else templates.standard_body_path()
        # relativa al .pbproj del item
        if self.project.path:
            cand = os.path.normpath(os.path.join(
                os.path.dirname(self.project.path), ref))
            if os.path.isfile(cand):
                return cand
        return templates.standard_body_path()

    def _attach_ref_body(self):
        """Carga el body de referencia y, para ROPA, injerta su rig+animaciones
        en el proyecto (no editables). Para CARACTERISTICA solo fija el ancho."""
        self.ref_project = None
        path = self._resolve_ref(self.project.ref_body)
        if not path:
            self.status = "No se encontro el cuerpo estandar (item sin guia)."
            return
        try:
            ref = model.Project.load(path)
            render.ensure_surfaces(ref)
        except Exception as e:
            self.status = f"No se pudo cargar el body de guia: {e}"
            return
        self.ref_project = ref
        pr = self.project
        pr.tile_w = ref.tile_w
        pr.tile_h = ref.tile_h
        pr.box_x, pr.box_y = ref.box_x, ref.box_y
        if pr.kind == "ropa":
            pr.bones = ref.bones          # MISMO rig (referenciado)
            pr.clips = ref.clips          # MISMAS animaciones
        # caracteristica conserva sus propios bones (vacio) y clips (pocos frames)
        self.sync_working()
        self._thumbs_dirty = True

    def _cargable_preview_surface(self, scale=3):
        """Composicion de como queda el CARGABLE puesto: el MALETIN (frame 1) va
        DETRAS del body y los BRAZOS/correas (frame 0) DELANTE. Para el preview."""
        rp = self.ref_project
        pr = self.project
        if rp is None or not pr.clips or not pr.clips[0].frames:
            return None
        frames = pr.clips[0].frames
        ibox = (pr.box_x, pr.box_y, pr.tile_w, pr.tile_h)
        bbox = (rp.box_x, rp.box_y, rp.tile_w, rp.tile_h)
        brazos = render.render_tile(pr, frames[0], None, ibox)
        maletin = render.render_tile(pr, frames[1], None, ibox) if len(frames) > 1 else None
        body = render.render_tile(rp, self._ref_idle_frame(), None, bbox)
        w, h = int(round(pr.tile_w)), int(round(pr.tile_h))
        canvas = pygame.Surface((w, h), pygame.SRCALPHA)
        if maletin:
            canvas.blit(maletin, (0, 0))      # el maletin, DETRAS del body
        if body:
            canvas.blit(body, (0, 0))         # el cuerpo
        ov = self._shirt_overlay()            # camisa de guia, SOBRE el cuerpo
        if ov is not None:
            frame, ox, oy = ov
            canvas.blit(frame, (-rp.box_x - ox, -rp.box_y - oy))
        if brazos:
            canvas.blit(brazos, (0, 0))       # los brazos/correas, DELANTE
        s = max(1, int(scale))
        return pygame.transform.scale(canvas, (w * s, h * s))

    # -- camisa de guia para alinear el cargable (usa las YA exportadas al juego) --
    def _list_shirts(self):
        """Camisas exportadas al juego: <root>/<assets>/characters/shirts/<v>/<v>.png
        (+ .json). Lista de (nombre, png, json). Vacia si no hay project_root."""
        if not self.project_root:
            return []
        base = os.path.join(self.project_root, self.assets_dir,
                            "characters", "shirts")
        out = []
        if os.path.isdir(base):
            for name in sorted(os.listdir(base)):
                d = os.path.join(base, name)
                png = os.path.join(d, name + ".png")
                js = os.path.join(d, name + ".json")
                if os.path.isfile(png) and os.path.isfile(js):
                    out.append((name, png, js))
        return out

    def _shirt_overlay(self):
        """(surface, ox, oy) del frame de reposo de la camisa elegida, o None.
        ox/oy = origen exportado (pixel del mundo (0,0) en el frame), para alinear
        igual que el body. Cacheado por nombre."""
        shirts = self._list_shirts()
        if not (0 <= self.shirt_idx < len(shirts)):
            return None
        name, png, js = shirts[self.shirt_idx]
        if name in self._shirt_cache:
            return self._shirt_cache[name]
        try:
            import json
            meta = json.load(open(js, encoding="utf-8"))
            sheet = pygame.image.load(png).convert_alpha()
        except Exception as e:
            self.status = f"No se pudo cargar la camisa: {e}"
            self._shirt_cache[name] = None
            return None
        rows = meta.get("rows", [])
        # fila 'reposo' (o idle/caminando/primera) y su y dentro de la hoja packed
        pick, y, yc = None, 0, 0
        for r in rows:
            nm = r.get("name", "").lower()
            if pick is None and nm in ("reposo", "idle"):
                pick, yc = r, y
            y += int(round(r.get("frame_h", 0)))
        if pick is None:
            y = 0
            for r in rows:
                if "camin" in r.get("name", "").lower():
                    pick, yc = r, y
                    break
                y += int(round(r.get("frame_h", 0)))
        if pick is None and rows:
            pick, yc = rows[0], 0
        if pick is None:
            self._shirt_cache[name] = None
            return None
        fw, fh = int(round(pick["frame_w"])), int(round(pick["frame_h"]))
        try:
            frame = sheet.subsurface(pygame.Rect(0, yc, fw, fh)).copy()
        except ValueError:
            self._shirt_cache[name] = None
            return None
        # banda _frente (la manga que va SOBRE el brazo): misma maqueta, encima.
        fpng = os.path.splitext(png)[0] + "_frente.png"
        if os.path.isfile(fpng):
            try:
                fsheet = pygame.image.load(fpng).convert_alpha()
                frame.blit(fsheet.subsurface(pygame.Rect(0, yc, fw, fh)), (0, 0))
            except (ValueError, pygame.error):
                pass
        ox, oy = pick.get("origin", [0, 0])
        data = (frame, float(ox), float(oy))
        self._shirt_cache[name] = data
        return data

    def _cycle_shirt(self):
        n = len(self._list_shirts())
        self.shirt_idx = -1 if n == 0 else ((self.shirt_idx + 2) % (n + 1)) - 1

    def _toggle_shirt(self):
        """Switch quitar/poner camisa, recordando la ultima elegida."""
        shirts = self._list_shirts()
        if not shirts:
            return
        if self.shirt_idx >= 0:
            self._shirt_prev = self.shirt_idx
            self.shirt_idx = -1
        else:
            p = getattr(self, "_shirt_prev", 0)
            self.shirt_idx = p if 0 <= p < len(shirts) else 0

    def _shirt_label(self):
        shirts = self._list_shirts()
        if not shirts:
            return "Camisa: (ninguna exportada)"
        if 0 <= self.shirt_idx < len(shirts):
            return f"Camisa: {shirts[self.shirt_idx][0]}"
        return "Camisa: (sin camisa)"

    def _draw_shirt_overlay(self):
        """Dibuja la camisa de guia sobre el body fantasma en el LIENZO (semi-
        transparente), alineada por el origen exportado (mundo (0,0))."""
        ov = self._shirt_overlay()
        if ov is None:
            return
        frame, ox, oy = ov
        if self.zoom != 1.0:
            frame = pygame.transform.scale(
                frame, (max(1, int(frame.get_width() * self.zoom)),
                        max(1, int(frame.get_height() * self.zoom))))
        frame = frame.copy()
        frame.fill((255, 255, 255, self._gop(130)), special_flags=pygame.BLEND_RGBA_MULT)
        self.screen.blit(frame, self.w2s(-ox, -oy))

    def _ref_idle_frame(self):
        """Frame 'guia' del body de referencia (reposo si existe)."""
        rp = self.ref_project
        if rp is None:
            return None
        for nm in ("reposo", "idle", "caminando", "andar"):
            c = next((c for c in rp.clips if c.name == nm), None)
            if c and c.frames:
                return c.frames[0]
        return rp.clips[0].frames[0] if (rp.clips and rp.clips[0].frames) else None

    # -- proyecto por defecto (art-src <-> assets) -----------------------
    def set_project(self):
        d = dialogs.choose_dir()
        if not d:
            return
        self.project_root = d
        config.save({"project_root": d, "src_dir": self.src_dir,
                     "assets_dir": self.assets_dir})
        self.status = (f"Proyecto: {os.path.basename(d)}  (editables en "
                       f"{self.src_dir}/, export a {self.assets_dir}/)")

    def src_root(self):
        if self.project_root:
            return os.path.join(self.project_root, self.src_dir)
        return None

    def _mirror_path(self, ext):
        """Ruta espejo en <root>/<assets_dir> del .pbproj actual (si esta bajo
        <root>/<src_dir>). Devuelve None si no aplica."""
        if not (self.project_root and self.project.path):
            return None
        src = os.path.abspath(self.src_root())
        p = os.path.abspath(self.project.path)
        if not (p == src or p.startswith(src + os.sep)):
            return None
        rel = os.path.relpath(p, src)
        return os.path.join(self.project_root, self.assets_dir,
                            os.path.splitext(rel)[0] + ext)

    def _load_path(self, path):
        try:
            self.project = model.Project.load(path)
        except Exception as e:
            self.status = f"Error al abrir: {e}"
            return
        render.ensure_surfaces(self.project)
        self.ref_project = None
        self.sel_kind, self.sel_idx = None, -1
        self.cur_clip = 0
        self.cur_frame = -1
        self.draw_idx = -1
        if self.is_item:                  # re-vincula el body de guia (fantasma)
            self._attach_ref_body()
        if self.is_tile:                  # un tile se edita SIEMPRE en Pintar
            self.mode = "paint"
            self.draw_idx = 0 if self.project.drawings else -1
            self._fit_canvas_view()
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
            start = self.src_root() if (self.project_root and not path) else None
            if start and self.is_tile:       # los tiles viven en <src>/tiles/
                start = os.path.join(start, "tiles")
                try:
                    os.makedirs(start, exist_ok=True)
                except OSError:
                    pass
            path = dialogs.save_project_as(start_dir=start)
            if path and self.is_tile:
                path = self._nest_tile_path(path)
        if not path:
            return
        try:
            self._save_project_to(path)
            self.dirty = False
            recovery.clear()
            self.status = f"Guardado: {os.path.basename(path)}"
        except Exception as e:
            self.status = f"Error al guardar: {e}"

    def _save_project_to(self, path):
        """Guarda el proyecto. SOLO la ROPA toma rig+animaciones del body
        REFERENCIADO (no se persisten, se re-vinculan al abrir). Caracteristica y
        cargable tienen sus PROPIOS huesos y frames: hay que guardarlos."""
        pr = self.project
        if pr.kind == "ropa":
            bones, clips = pr.bones, pr.clips
            pr.bones, pr.clips = [], []
            try:
                pr.save(path)
            finally:
                pr.bones, pr.clips = bones, clips
        else:
            pr.save(path)

    def _nest_tile_path(self, path):
        """Convencion tile: <src>/tiles/<nombre>/<nombre>.pbproj (cada tile en
        su carpeta). Si el usuario guardo directo en .../tiles/, crea la
        carpeta del tile y anida el archivo. Fuera de ahi, no toca la ruta."""
        src = self.src_root()
        if not src:
            return path
        tiles = os.path.normcase(os.path.abspath(os.path.join(src, "tiles")))
        d = os.path.dirname(os.path.abspath(path))
        if os.path.normcase(d) != tiles:
            return path
        name = os.path.splitext(os.path.basename(path))[0]
        nested = os.path.join(d, name)
        os.makedirs(nested, exist_ok=True)
        return os.path.join(nested, name + ".pbproj")

    def _tile_export_path(self):
        """Ruta de export de un TILE: <root>/<assets>/tiles/<nombre>.png,
        PLANA (asi la consume TILE_TYPES del juego), sea cual sea la
        subcarpeta bajo <src>/ donde viva el .pbproj. None si no aplica."""
        if not (self.project_root and self.project.path):
            return None
        src = os.path.abspath(self.src_root())
        p = os.path.abspath(self.project.path)
        if not p.startswith(src + os.sep):
            return None
        name = os.path.splitext(os.path.basename(p))[0]
        return os.path.join(self.project_root, self.assets_dir, "tiles",
                            name + ".png")

    def export_tile(self):
        """Exporta el tile COMO LO CONSUME EL JUEGO: 1 frame = PNG cuadrado
        simple; N frames = tira HORIZONTAL de frames cuadrados (fogata.png =
        9x64 -> 576x64). Sin animacion.json (los tiles no lo usan)."""
        pr = self.project
        render.ensure_surfaces(pr)
        if not pr.drawings:
            self.status = "No hay frames que exportar (crea un dibujo en Pintar)."
            return
        auto = self._tile_export_path()      # espejo art-src -> assets/tiles/
        if auto:
            path = auto
            os.makedirs(os.path.dirname(path), exist_ok=True)
        else:
            path = dialogs.save_png_as()
            if not path:
                return
        try:
            sz, n = render.export_tile_strip(pr, path)
            shown = (os.path.relpath(path, self.project_root)
                     if self.project_root and auto else os.path.basename(path))
            self.status = f"Tile exportado {sz[0]}x{sz[1]} ({n} frame/s) -> {shown}"
        except Exception as e:
            self.status = f"Error export: {e}"

    def export_composite(self):
        if self.is_tile:                     # un tile solo exporta la tira
            self.export_tile()
            return
        if not self.project.sprites:
            self.status = "No hay imagenes para exportar."
            return
        pr = self.project
        # ROPA: recuadro alineado al body (overlay que se deforma, no se recorta).
        # CARACTERISTICA: se exporta RECORTADA a su contenido (el menor tamano
        # posible, ~cabeza) y el juego la coloca por su CONEXION (socket) frame a
        # frame -> ahorra recursos. BODY: expandir para no recortar nunca.
        box_override = None
        conn = None
        conn_offset = None
        warn = ""
        if self.is_item:
            nfit = 0
            hid = [s.name for s in pr.sprites if not s.visible]
            if hid:
                warn += f"  ⚠ ocultos globalmente: {', '.join(hid)}."
            if pr.kind == "cargable" and len(pr.clips[0].frames) != 2:
                warn += "  ⚠ un cargable debe tener 2 frames (atras/adelante)."
            if pr.kind == "caracteristica":
                conn = render.part_connection(pr)
                if not conn:
                    warn += "  ⚠ SIN conexion (el juego no sabra donde colocarla)."
                box_override = render.content_box(pr, margin=1)
                if box_override is None:
                    self.status = ("Nada visible para exportar (¿materiales "
                                   "ocultos?).")
                    return
                # WYSIWYG: offset del centro DIBUJADO respecto al socket del body,
                # para que en el juego quede DONDE lo dibujaste (no centrado en el
                # socket) y siga al hueso por frame.
                if conn and self.ref_project is not None:
                    sj = self.ref_project.bone_by_name(conn)
                    if sj >= 0:
                        ccx = box_override[0] + box_override[2] / 2.0
                        ccy = box_override[1] + box_override[3] / 2.0
                        pfr = model.pose_for_frame(self.ref_project,
                                                   self._ref_idle_frame())
                        sw = model.bone_world(self.ref_project, sj, pfr)
                        conn_offset = (ccx - sw[0], ccy - sw[1])
        else:
            nfit = self.ensure_clips_fit()        # nunca recortar (body)
        auto = self._mirror_path(".png")          # espejo art-src -> assets
        if auto:
            path = auto
            os.makedirs(os.path.dirname(path), exist_ok=True)
        else:
            path = dialogs.save_png_as()
            if not path:
                return
        # CARGABLE: pixelBones agrega un 3er frame de cortesia = COMBINACION
        # (brazos + maletin juntos) -> el icono del item en inventario/recogibles.
        combo_added = False
        if pr.kind == "cargable" and pr.clips and len(pr.clips[0].frames) == 2:
            combo = model.Frame("combo")          # hidden vacio -> muestra todo
            pr.clips[0].frames.append(combo)
            combo_added = True
        # Banda DELANTE-de-la-ropa: las partes con z (body) o el z del hueso que
        # siguen (ropa) por encima de clothes_z se exportan a <name>_frente.png.
        front_ids = self._front_band_ids(pr)
        main_filter = (set(range(len(pr.sprites))) - front_ids) if front_ids else None
        try:
            sz = render.export_composite(pr, path, box_override,
                                         sprites_filter=main_filter)
            render.export_meta(pr, os.path.splitext(path)[0] + ".json",
                               box_override=box_override, connection=conn,
                               conn_offset=conn_offset)
            if front_ids:                          # banda del frente (sobre ropa)
                fpath = os.path.splitext(path)[0] + "_frente.png"
                render.export_composite(pr, fpath, box_override,
                                        sprites_filter=front_ids)
            shown = (os.path.relpath(path, self.project_root)
                     if self.project_root and auto else os.path.basename(path))
            extra = f" · ajuste {nfit} anim." if nfit else ""
            if conn:
                extra += f" · conexion '{conn}'"
            if front_ids:
                extra += f" · +banda _frente ({len(front_ids)} partes)"
            if combo_added:
                extra += " · +1 frame combo (icono)"
            self.status = (f"Exportado {sz[0]}x{sz[1]} "
                           f"({len(pr.clips)} fila/s) -> {shown} + .json"
                           + extra + warn)
        except Exception as e:
            self.status = f"Error export: {e}"
        finally:
            if combo_added:                       # el combo es temporal del export
                pr.clips[0].frames.pop()

    def export_layers(self):
        if not self.project.sprites:
            self.status = "No hay imagenes para exportar."
            return
        self.ensure_clips_fit()                   # nunca recortar
        auto = self._mirror_path(".png")
        if auto:
            d = os.path.dirname(auto)             # carpeta espejo en assets/
            os.makedirs(d, exist_ok=True)
        else:
            d = dialogs.choose_dir()
            if not d:
                return
        try:
            files = render.export_per_layer(self.project, d)
            render.export_meta(self.project, os.path.join(d, "metadata.json"))
            self.status = (f"{len(files)} hojas por capa (filas = animaciones) "
                           f"+ metadata.json -> {os.path.basename(d)}/")
        except Exception as e:
            self.status = f"Error export: {e}"

    def export_connection(self):
        """Exporta el material RECORTADO a su tamano real + .json con su conexion.
        El juego centra este PNG en el punto de conexion del cuerpo."""
        if not self.project.sprites:
            self.status = "No hay imagenes para exportar."
            return
        auto = self._mirror_path(".png")              # espejo art-src -> assets
        if auto:
            path = auto
            os.makedirs(os.path.dirname(path), exist_ok=True)
        else:
            path = dialogs.save_png_as()
            if not path:
                return
        try:
            sz, conn = render.export_part(self.project, path)
            shown = (os.path.relpath(path, self.project_root)
                     if self.project_root and auto else os.path.basename(path))
            tag = f"conexion '{conn}'" if conn else "SIN conexion (asignala)"
            self.status = (f"Material {sz[0]}x{sz[1]} ({tag}) -> {shown} + .json")
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

    NODE_HIT_R = 14          # radio (px) para agarrar el NODO de un hueso

    def _hit_bone(self, sx, sy):
        """Devuelve (idx, 'head'|'body') del hueso mas cercano o None. El NODO
        (cabeza) tiene un area de agarre amplia para que mover huesos sea comodo;
        el cuerpo solo gana si el mouse esta claramente sobre el, no sobre el nodo."""
        pose = self.pose_for()
        best = None
        best_d = 1e9
        for idx in range(len(self.project.bones)):
            head, tip = self._bone_endpoints_screen(idx, pose)
            dh = math.hypot(sx - head[0], sy - head[1])
            if dh < self.NODE_HIT_R and dh < best_d:
                best, best_d = (idx, "head"), dh
            db = _seg_dist((sx, sy), head, tip)
            if db < 7 and db < best_d - 4:
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

    def _sprite_handle(self, sp, dist=40):
        """(centro_screen, manija_screen, rot). El centro es el del CONTENIDO del
        material (no el pivot del lienzo), asi el palito sale del material."""
        wt = model.sprite_world(self.project, sp, self.pose_for())
        cx, cy = self._sprite_centroid_world(sp)
        psx, psy = self.w2s(cx, cy)
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

    def _link_press(self):
        """Herramienta Enlace (2 clics): 1) un hueso, 2) una imagen."""
        if self.link_bone is None or self.link_bone >= len(self.project.bones):
            hb = self._hit_bone(*self.mouse)
            if hb is not None:
                self.link_bone = hb[0]
                self.sel_kind, self.sel_idx = "bone", hb[0]
                name = self.project.bones[hb[0]].name
                self.status = (f"Hueso '{name}' elegido. Clic en una imagen "
                               "para enlazarla. (Esc cancela)")
            else:
                self.status = "Enlace: primero haz clic en un hueso."
            return
        # segundo clic: la imagen
        hs = self._hit_sprite(*self.mouse)
        if hs >= 0:
            bone_name = self.project.bones[self.link_bone].name
            self.bind_sprite(hs, bone_name)
            self.sel_kind, self.sel_idx = "sprite", hs
            self.status = (f"'{self.project.sprites[hs].name}' enlazado a "
                           f"'{bone_name}'.")
            self.link_bone = None
            return
        hb = self._hit_bone(*self.mouse)
        if hb is not None:                       # clic en otro hueso: cambia origen
            self.link_bone = hb[0]
            self.sel_kind, self.sel_idx = "bone", hb[0]
            self.status = ("Hueso de origen cambiado. Clic en una imagen "
                           "para enlazarla.")
        else:
            self.link_bone = None
            self.status = "Enlace cancelado (clic en vacio)."

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
    # modo Pintar: capas, vista de lienzo y herramientas raster
    # ====================================================================
    def pc2s(self, cx, cy):
        c = self.r_canvas
        return (c.centerx + (cx - self.pcx) * self.pzoom,
                c.centery + (cy - self.pcy) * self.pzoom)

    def s2pc(self, sx, sy):
        c = self.r_canvas
        return (self.pcx + (sx - c.centerx) / self.pzoom,
                self.pcy + (sy - c.centery) / self.pzoom)

    def _canvas_pixel(self):
        fx, fy = self.s2pc(*self.mouse)
        return int(math.floor(fx)), int(math.floor(fy))

    def _active_layer(self):
        sp = self.paint_target()
        if sp is None or not sp.layers:
            return None, None
        i = max(0, min(sp.active_layer, len(sp.layers) - 1))
        return sp, sp.layers[i]

    def _paint_push_undo(self, sp, layer):
        self.paint_undo.append((sp, layer, layer.surface.copy()))
        if len(self.paint_undo) > 80:
            self.paint_undo.pop(0)
        self.paint_redo.clear()

    def _after_paint(self, sp, quick=False):
        # quick=True (trazo en curso): no recalcula el bounding-box (escaneo caro
        # de toda la hoja); se hace una vez al soltar el mouse.
        render.flatten_sprite(sp, recompute_bbox=not quick)
        self.dirty = True
        if not quick:
            self._thumbs_dirty = True

    def _cut_by_mask(self, surf, mask):
        """Recorta a un buffer flotante los pixeles bajo `mask` y los borra de
        `surf`, a velocidad C (sin bucle Python por pixel: clave en lienzos
        grandes). Devuelve el flotante (mismo tamano que surf)."""
        flo = mask.to_surface(setsurface=surf, unsetcolor=(0, 0, 0, 0))
        eraser = mask.to_surface(setcolor=(0, 0, 0, 0),
                                 unsetcolor=(255, 255, 255, 255))
        surf.blit(eraser, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        return flo

    def _set_color_from_hsv(self):
        import colorsys
        r, g, b = colorsys.hsv_to_rgb(self.paint.hue, self.paint.sat, self.paint.val)
        self.paint.color = (int(r * 255), int(g * 255), int(b * 255),
                            self.paint.color[3])

    def _sync_hsv_from_color(self):
        import colorsys
        r, g, b, _ = self.paint.color
        self.paint.hue, self.paint.sat, self.paint.val = \
            colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)

    def _pick_color(self, col):
        self.paint.color = tuple(col)
        self._sync_hsv_from_color()

    def _update_cursor(self):
        want = pygame.SYSTEM_CURSOR_ARROW
        over = self.r_canvas.collidepoint(self.mouse)
        # cursores de redimension sobre los bordes
        sr = self._splitter_rects()
        if self.split_drag in ("left", "right") or (self.split_drag is None and (
                sr["left"].collidepoint(self.mouse)
                or sr["right"].collidepoint(self.mouse))):
            want = pygame.SYSTEM_CURSOR_SIZEWE
        elif self.split_drag in ("time", "leftsplit") or (self.split_drag is None
                and (sr["time"].collidepoint(self.mouse)
                     or sr["leftsplit"].collidepoint(self.mouse))):
            want = pygame.SYSTEM_CURSOR_SIZENS
        elif self.mode == "paint" and over:
            if self.ptool == "hand":
                want = pygame.SYSTEM_CURSOR_HAND
            elif self.ptool == "move":
                want = pygame.SYSTEM_CURSOR_SIZEALL
            elif self.ptool == "scale":
                want = pygame.SYSTEM_CURSOR_SIZEWE
            else:
                want = pygame.SYSTEM_CURSOR_CROSSHAIR
        elif self.mode == "animate" and over and self.tool == "hand":
            want = pygame.SYSTEM_CURSOR_HAND
        elif self.mode == "animate" and over and self.tool == "link":
            want = pygame.SYSTEM_CURSOR_CROSSHAIR

        # hover sobre el NODO de un hueso (modo seleccion): resalta + cursor mover
        self._hover_node = -1
        if (self.mode == "animate" and over and self.tool == "select"
                and not self.playing):
            if self.drag is not None and self.drag.get("mode") == "bone_move":
                self._hover_node = self.drag["idx"]      # mantiene feedback al mover
            elif self.drag is None:
                hb = self._hit_bone(*self.mouse) if self.show_bones else None
                if hb is not None and hb[1] == "head":
                    self._hover_node = hb[0]
            if self._hover_node >= 0:
                want = pygame.SYSTEM_CURSOR_SIZEALL

        # hover en una ESQUINA o la manija del material seleccionado -> rotar
        if (self.mode == "animate" and over and self.tool == "select"
                and not self.playing and self.drag is None):
            ssp = self.selected_sprite()
            if ssp is not None and ssp.surface is not None:
                (_, _), (hx, hy), _ = self._sprite_handle(ssp)
                if (math.hypot(self.mouse[0] - hx, self.mouse[1] - hy) < 11
                        or self._near_sprite_corner(ssp)):
                    want = "rotate"
        if self.drag is not None and self.drag.get("mode") == "sprite_rotate":
            want = "rotate"

        if self._cursor != want:
            try:
                cur = self._get_rotate_cursor() if want == "rotate" else want
                pygame.mouse.set_cursor(cur)
            except Exception:
                pass
            self._cursor = want

    def layer_duplicate(self):
        sp = self.paint_target()
        if sp is None or not sp.layers:
            return
        self.snapshot()
        src = sp.layers[sp.active_layer]
        dup = src.clone()
        dup.name = src.name + " copia"
        sp.layers.insert(sp.active_layer + 1, dup)
        sp.active_layer += 1
        self.paint_undo.clear()
        self.paint_redo.clear()
        render.flatten_sprite(sp)
        self._thumbs_dirty = True

    # -- capas (del dibujo activo) ---------------------------------------
    def layer_add(self):
        sp = self.paint_target()
        if sp is None:
            return
        self.snapshot()
        render.ensure_layers(sp, (self.project.tile_w, self.project.tile_h))
        w, h = sp.layers[0].surface.get_size()
        lay = model.Layer(f"capa {len(sp.layers) + 1}",
                          pygame.Surface((w, h), pygame.SRCALPHA))
        sp.layers.insert(sp.active_layer + 1, lay)
        sp.active_layer += 1
        self.paint_undo.clear()
        self.paint_redo.clear()
        render.flatten_sprite(sp)
        self._thumbs_dirty = True

    def layer_delete(self, i):
        sp = self.paint_target()
        if sp is None or len(sp.layers) <= 1 or not (0 <= i < len(sp.layers)):
            return
        self.snapshot()
        del sp.layers[i]
        sp.active_layer = min(sp.active_layer, len(sp.layers) - 1)
        self.paint_undo.clear()
        self.paint_redo.clear()
        render.flatten_sprite(sp)
        self._thumbs_dirty = True

    def layer_move(self, i, d):
        sp = self.paint_target()
        if sp is None:
            return
        j = i + d
        if 0 <= i < len(sp.layers) and 0 <= j < len(sp.layers):
            self.snapshot()
            sp.layers[i], sp.layers[j] = sp.layers[j], sp.layers[i]
            if sp.active_layer == i:
                sp.active_layer = j
            elif sp.active_layer == j:
                sp.active_layer = i
            render.flatten_sprite(sp)
            self._thumbs_dirty = True

    def layer_toggle(self, i):
        sp = self.paint_target()
        if sp and 0 <= i < len(sp.layers):
            self.snapshot()
            sp.layers[i].visible = not sp.layers[i].visible
            render.flatten_sprite(sp)
            self._thumbs_dirty = True

    def layer_select(self, i):
        sp = self.paint_target()
        if sp and 0 <= i < len(sp.layers):
            sp.active_layer = i
            self.paint_undo.clear()
            self.paint_redo.clear()

    def rename_active_layer(self):
        sp = self.paint_target()
        if sp and sp.layers:
            self.editing = ("rename_layer", sp.active_layer)
            self.edit_buf = sp.layers[sp.active_layer].name

    # -- dibujos del taller (independientes de los materiales) ------------
    def _unique_drawing_name(self, base):
        names = {d.name for d in self.project.drawings}
        return self.project._unique(base, names)

    def new_drawing(self):
        self.snapshot()
        w, h = self.project.tile_w, self.project.tile_h
        base = "frame" if self.is_tile else "dibujo"
        d = model.Sprite(self._unique_drawing_name(base), None)
        d.layers = [model.Layer("base", pygame.Surface((w, h), pygame.SRCALPHA))]
        d.pivot = [w / 2.0, h / 2.0]
        render.flatten_sprite(d)
        self.project.drawings.append(d)
        self.draw_idx = len(self.project.drawings) - 1
        self.paint_undo.clear()
        self.paint_redo.clear()
        self._fit_canvas_view()
        self._thumbs_dirty = True
        self.status = ("Frame nuevo agregado a la tira del tile."
                       if self.is_tile else
                       "Dibujo nuevo. Pinta y luego 'Enviar como material'.")

    def resize_active_drawing(self, w, h):
        """Redimensiona el lienzo del dibujo activo a (w,h), conservando el
        contenido (anclado arriba-izquierda). Para sincronizar con el tile."""
        d = self.paint_target()
        if d is None:
            return
        self.snapshot()
        for lay in d.layers:
            new = pygame.Surface((w, h), pygame.SRCALPHA)
            if lay.surface is not None:
                new.blit(lay.surface, (0, 0))
            lay.surface = new
        d.pivot = [w / 2.0, h / 2.0]
        render.flatten_sprite(d)
        self.paint_undo.clear()
        self.paint_redo.clear()
        self._fit_canvas_view()
        self._thumbs_dirty = True
        self.status = f"Lienzo redimensionado a {w}x{h}."

    def draw_select(self, i):
        if 0 <= i < len(self.project.drawings):
            self.draw_idx = i
            self.paint_undo.clear()
            self.paint_redo.clear()
            self._fit_canvas_view()

    def delete_drawing(self, i):
        if not (0 <= i < len(self.project.drawings)):
            return
        self.snapshot()
        del self.project.drawings[i]
        self.draw_idx = min(self.draw_idx, len(self.project.drawings) - 1)
        self.paint_undo.clear()
        self.paint_redo.clear()
        self._thumbs_dirty = True

    def rename_drawing(self):
        d = self.paint_target()
        if d is not None:
            self.editing = ("rename_drawing", self.draw_idx)
            self.edit_buf = d.name

    @staticmethod
    def _new_lid():
        return uuid.uuid4().hex[:12]

    def send_drawing_as_material(self):
        """Envia el dibujo a Animacion: UN MATERIAL POR CAPA (paper-doll). Si una
        capa corresponde a un material EXISTENTE -por su vinculo (lid) o, en
        proyectos viejos, por su NOMBRE- ACTUALIZA ese material en sitio,
        conservando sus props de animacion (hueso, posicion, ESCALA, z, conexion)
        y solo cambiando los pixeles. Asi no duplica y el cambio se ve en todas
        las animaciones. Solo las capas sin material previo crean uno nuevo."""
        if self.is_tile:
            self.status = ("Tile: los dibujos YA son los frames de la tira; "
                           "usa 'Exportar' (no hay materiales que enviar).")
            return
        d = self.paint_target()
        if d is None or not d.layers:
            self.status = "No hay dibujo que enviar."
            return
        tw, th = self.project.tile_w, self.project.tile_h
        valid = []
        for lay in d.layers:
            if not lay.visible or lay.surface is None:
                continue
            bb = lay.surface.get_bounding_rect(min_alpha=1)
            if bb.width == 0 or bb.height == 0:
                continue                              # capa vacia: se omite
            valid.append(lay)
        if not valid:
            self.status = "El dibujo no tiene capas con contenido para enviar."
            return
        self.snapshot()
        by_origin = {s.origin: s for s in self.project.sprites if s.origin}
        created = updated = 0
        last_idx = -1
        for lay in valid:
            cw, ch = lay.surface.get_size()
            surf = lay.surface.copy()
            if lay.opacity < 0.999:                   # hornear opacidad de capa
                a = max(0, min(255, int(255 * lay.opacity)))
                surf.fill((255, 255, 255, a), special_flags=pygame.BLEND_RGBA_MULT)
            if not lay.lid:
                lay.lid = self._new_lid()
            base = d.name if lay.name in ("base", "capa") else lay.name
            target = by_origin.get(lay.lid)
            if target is None:                        # legado: adoptar por NOMBRE
                target = next((s for s in self.project.sprites
                               if s.name == base and not s.origin), None)
                if target is not None:
                    target.origin = lay.lid           # deja el vinculo para el futuro
                    by_origin[lay.lid] = target
            if target is not None:                    # ACTUALIZA: solo los pixeles
                target.layers = [model.Layer("base", surf)]
                render.flatten_sprite(target)
                target.pivot = [cw / 2.0, ch / 2.0]
                updated += 1
                last_idx = self.project.sprites.index(target)
            else:                                     # CREA un material nuevo
                sp = model.Sprite(self.project.unique_sprite_name(base), None)
                sp.origin = lay.lid
                sp.layers = [model.Layer("base", surf)]
                render.flatten_sprite(sp)
                sp.pivot = [cw / 2.0, ch / 2.0]       # centro del lienzo -> alineado
                sp.transform = {"x": self.project.box_x + tw / 2,
                                "y": self.project.box_y + th / 2,
                                "rot": 0.0, "scale": 1.0}
                sp.z = len(self.project.sprites)
                self.project.sprites.append(sp)
                by_origin[sp.origin] = sp
                created += 1
                last_idx = len(self.project.sprites) - 1
        self.mode = "animate"
        if last_idx >= 0:
            self.sel_kind, self.sel_idx = "sprite", last_idx
        self._thumbs_dirty = True
        parts = []
        if created:
            parts.append(f"{created} nueva(s)")
        if updated:
            parts.append(f"{updated} actualizada(s)")
        tail = ("Enlaza las nuevas a su hueso con 'C'." if created
                else "El cambio se aplico en todas las animaciones.")
        self.status = f"Materiales: {', '.join(parts)}. {tail}"

    def edit_material_in_paint(self, sprite_idx):
        """Trae un material existente al taller como COPIA editable (sin afectar
        al material hasta reenviar). Vincula la capa base del taller al material
        (su 'origin') para que 'Enviar' lo ACTUALICE en vez de duplicarlo."""
        if not (0 <= sprite_idx < len(self.project.sprites)):
            return
        src = self.project.sprites[sprite_idx]
        render.ensure_layers(src, (self.project.tile_w, self.project.tile_h))
        self.snapshot()
        if not src.origin:                            # material legado: dale vinculo
            src.origin = self._new_lid()
        d = model.Sprite(self._unique_drawing_name(src.name), src.image_path)
        d.layers = [l.clone() for l in src.layers]
        if d.layers:                                  # capa base -> apunta al material
            d.layers[0].lid = src.origin
        render.flatten_sprite(d)
        self.project.drawings.append(d)
        self.draw_idx = len(self.project.drawings) - 1
        self.mode = "paint"
        self.paint_undo.clear()
        self.paint_redo.clear()
        self._fit_canvas_view()
        self._thumbs_dirty = True
        self.status = f"Editando copia de '{src.name}' en el taller."

    def paint_clear_pixels(self):
        sp, layer = self._active_layer()
        if layer is None:
            return
        self._paint_push_undo(sp, layer)
        paint.clear_selection(layer.surface, self.paint.sel_mask)
        self._after_paint(sp)

    def flatten_to_base(self):
        sp = self.paint_target()
        if sp is None or sp.surface is None:
            self.status = "No hay dibujo que guardar."
            return
        if not sp.image_path:
            self.flatten_to_new()
            return
        try:
            os.makedirs(os.path.dirname(os.path.abspath(sp.image_path)),
                        exist_ok=True)
            pygame.image.save(sp.surface, sp.image_path)
            self.status = f"Imagen guardada en {os.path.basename(sp.image_path)}"
        except Exception as e:
            self.status = f"Error al guardar imagen: {e}"

    def flatten_to_new(self):
        sp = self.paint_target()
        if sp is None or sp.surface is None:
            self.status = "No hay dibujo que guardar."
            return
        path = dialogs.save_png_as()
        if not path:
            return
        try:
            pygame.image.save(sp.surface, path)
            sp.image_path = path
            self.status = f"Guardado como {os.path.basename(path)}"
        except Exception as e:
            self.status = f"Error al guardar imagen: {e}"

    # -- interaccion de pintura ------------------------------------------
    def _handle_paint_canvas(self):
        c = self.r_canvas
        over = c.collidepoint(self.mouse)
        # terminar curva con clic derecho
        if self.rmb_down and self.line_anchor and \
                self.line_anchor.get("tool") == "curve":
            self.commit_curve()
            return
        if self.wheel != 0 and over:
            if pygame.key.get_mods() & pygame.KMOD_CTRL:
                self.paint.brush = max(1, min(64,
                                              self.paint.brush + (1 if self.wheel > 0 else -1)))
            else:
                old = self.s2pc(*self.mouse)
                # min 0.05: permite alejar para ver lienzos grandes completos.
                self.pzoom = max(0.05, min(40.0, self.pzoom * (1.1 ** self.wheel)))
                new = self.s2pc(*self.mouse)
                self.pcx += old[0] - new[0]
                self.pcy += old[1] - new[1]
        if self.pan:
            if pygame.mouse.get_pressed()[1]:
                s0, _, _, pcx0, pcy0 = self.pan
                self.pcx = pcx0 - (self.mouse[0] - s0[0]) / self.pzoom
                self.pcy = pcy0 - (self.mouse[1] - s0[1]) / self.pzoom
            else:
                self.pan = None
        sp = self.paint_target()
        if sp is None or sp.surface is None:
            return
        if self.lmb_down and over and self.active_scrub is None:
            self._paint_press()
        if self.drag is not None and self.drag.get("paint"):
            if self.lmb_held:
                self._paint_drag()
            else:
                self._paint_release()

    def _paint_press(self):
        sp, layer = self._active_layer()
        if layer is None:
            return
        px, py = self._canvas_pixel()
        t = self.ptool
        if t == "hand":
            self.drag = {"paint": True, "mode": "pan",
                         "sx": self.mouse, "pcx": self.pcx, "pcy": self.pcy}
            return
        if t == "move":
            # mover toda la capa, o solo lo seleccionado si hay seleccion
            self._paint_push_undo(sp, layer)
            surf = layer.surface
            if self.paint.sel_mask is not None:
                flo = self._cut_by_mask(surf, self.paint.sel_mask)
            else:
                W, H = surf.get_size()
                flo = pygame.Surface((W, H), pygame.SRCALPHA)
                flo.blit(surf, (0, 0))
                surf.fill((0, 0, 0, 0))
            self._after_paint(sp)
            self.drag = {"paint": True, "mode": "sel_move", "float": flo,
                         "start": (px, py)}
            return
        if t == "scale":
            # escalar el contenido de la CAPA: arrastra horizontal (derecha = mas
            # grande). Reescala lo dibujado desde su centro, sin perder calidad de
            # pixel (nearest). Re-escala desde el original en cada paso.
            surf = layer.surface
            bb = surf.get_bounding_rect(min_alpha=1)
            if bb.width == 0 or bb.height == 0:
                self.status = "La capa esta vacia (nada que escalar)."
                return
            self._paint_push_undo(sp, layer)
            self.drag = {"paint": True, "mode": "lscale",
                         "content": surf.subsurface(bb).copy(),
                         "center": bb.center, "size": surf.get_size(),
                         "sx": self.mouse[0]}
            return
        if t == "select":
            W, H = layer.surface.get_size()
            mods = pygame.key.get_mods()
            add = bool(mods & pygame.KMOD_SHIFT)
            sub = bool(mods & pygame.KMOD_CTRL)
            inside = (self.paint.sel_mask is not None and 0 <= px < W
                      and 0 <= py < H and self.paint.sel_mask.get_at((px, py)))
            if inside and not add and not sub:
                # mover el contenido seleccionado (corta a un buffer flotante)
                self._paint_push_undo(sp, layer)
                flo = self._cut_by_mask(layer.surface, self.paint.sel_mask)
                self._after_paint(sp)
                self.drag = {"paint": True, "mode": "sel_move", "float": flo,
                             "start": (px, py)}
            else:
                self.drag = {"paint": True, "mode": "sel_rect", "p0": (px, py),
                             "op": "add" if add else ("sub" if sub else "replace")}
            return
        if t == "eyedropper":
            col = paint.pick(layer.surface, px, py, sp.surface)
            if col:
                self._pick_color(col)
            self.drag = {"paint": True, "mode": "none"}
            return
        if t == "bucket":
            self._paint_push_undo(sp, layer)
            paint.bucket(layer.surface, px, py, self.paint.color,
                         self.paint.sel_mask, self.paint.tolerance)
            self._after_paint(sp)
            self.drag = {"paint": True, "mode": "none"}
            return
        if t == "wand":
            self.paint.sel_mask = paint.magic_select(sp.surface, px, py,
                                                     self.paint.tolerance)
            self.drag = {"paint": True, "mode": "none"}
            return
        if t == "line":
            self.line_anchor = {"tool": "line", "p0": (px, py), "p1": (px, py)}
            self.drag = {"paint": True, "mode": "shape"}
            return
        if t == "curve":
            # B-spline multi-punto: cada clic agrega un nodo; clic derecho o
            # Enter cierra la curva; Esc la cancela.
            a = self.line_anchor
            if a and a.get("tool") == "curve":
                a["pts"].append((px, py))
            else:
                self.line_anchor = {"tool": "curve", "pts": [(px, py)]}
            self.drag = {"paint": True, "mode": "none"}
            return
        # lapiz / borrador / sombreador: trazo continuo
        self._paint_push_undo(sp, layer)
        self._stamp_at(layer, px, py)
        self.drag = {"paint": True, "mode": "stroke", "last": (px, py)}

    def _stamp_at(self, layer, px, py):
        t = self.ptool
        if t == "eraser":
            paint.stamp(layer.surface, px, py, (0, 0, 0, 0),
                        self.paint.brush, self.paint.sel_mask)
        elif t == "shade":
            paint.shade(layer.surface, px, py, self.paint.brush,
                        self.paint.shade_amount, self.paint.shade_lighten,
                        self.paint.sel_mask)
        else:
            paint.stamp(layer.surface, px, py, self.paint.color,
                        self.paint.brush, self.paint.sel_mask)

    def _stroke_to(self, layer, x0, y0, x1, y1):
        t = self.ptool
        if t == "eraser":
            paint.line(layer.surface, x0, y0, x1, y1, (0, 0, 0, 0),
                       self.paint.brush, self.paint.sel_mask)
        elif t == "shade":
            paint.shade_line(layer.surface, x0, y0, x1, y1, self.paint.brush,
                             self.paint.shade_amount, self.paint.shade_lighten,
                             self.paint.sel_mask)
        else:
            paint.line(layer.surface, x0, y0, x1, y1, self.paint.color,
                       self.paint.brush, self.paint.sel_mask)

    def _paint_drag(self):
        m = self.drag["mode"]
        if m == "pan":
            s0 = self.drag["sx"]
            self.pcx = self.drag["pcx"] - (self.mouse[0] - s0[0]) / self.pzoom
            self.pcy = self.drag["pcy"] - (self.mouse[1] - s0[1]) / self.pzoom
        elif m == "stroke":
            sp, layer = self._active_layer()
            if layer is None:
                return
            px, py = self._canvas_pixel()
            lx, ly = self.drag["last"]
            self._stroke_to(layer, lx, ly, px, py)
            self.drag["last"] = (px, py)
            self._after_paint(sp, quick=True)
        elif m == "lscale":
            sp, layer = self._active_layer()
            if layer is None:
                return
            f = max(0.1, min(8.0, 1.0 + (self.mouse[0] - self.drag["sx"]) * 0.01))
            content = self.drag["content"]
            nw = max(1, int(round(content.get_width() * f)))
            nh = max(1, int(round(content.get_height() * f)))
            scaled = pygame.transform.scale(content, (nw, nh))   # nearest (pixel)
            W, H = self.drag["size"]
            new = pygame.Surface((W, H), pygame.SRCALPHA)
            cx, cy = self.drag["center"]
            new.blit(scaled, (int(round(cx - nw / 2)), int(round(cy - nh / 2))))
            layer.surface = new
            self._after_paint(sp, quick=True)
            self.status = f"Escalar capa x{f:.2f}"
        elif m == "shape":
            self._shape_drag()

    def _paint_release(self):
        m = self.drag.get("mode")
        if m == "shape":
            self._shape_release()
        elif m == "sel_rect":
            self._commit_sel_rect()
        elif m == "sel_move":
            self._commit_sel_move()
        elif m in ("stroke", "lscale"):
            # el trazo difirio el bounding-box (quick): recalcularlo una vez ahora.
            sp = self.paint_target()
            if sp is not None:
                render.flatten_sprite(sp, recompute_bbox=True)
                self._thumbs_dirty = True
        self.drag = None

    def _rect_mask(self, x0, y0, x1, y1, w, h):
        rx0, rx1 = sorted((x0, x1))
        ry0, ry1 = sorted((y0, y1))
        s = pygame.Surface((w, h), pygame.SRCALPHA)
        rx, ry = max(0, rx0), max(0, ry0)
        rw, rh = min(w, rx1 + 1) - rx, min(h, ry1 + 1) - ry
        if rw > 0 and rh > 0:
            s.fill((255, 255, 255, 255), pygame.Rect(rx, ry, rw, rh))
        return pygame.mask.from_surface(s)

    def _commit_sel_rect(self):
        sp, layer = self._active_layer()
        if layer is None:
            return
        W, H = layer.surface.get_size()
        p0, p1 = self.drag["p0"], self._canvas_pixel()
        op = self.drag["op"]
        tiny = abs(p1[0] - p0[0]) < 1 and abs(p1[1] - p0[1]) < 1
        cur = self.paint.sel_mask
        if op == "replace" and tiny:
            self.paint.sel_mask = None        # clic simple => deseleccionar
            return
        if op == "sub" and cur is None:
            return
        rm = self._rect_mask(p0[0], p0[1], p1[0], p1[1], W, H)
        if op == "add" and cur is not None:
            cur.draw(rm, (0, 0))
            self.paint.sel_mask = cur
        elif op == "sub" and cur is not None:
            cur.erase(rm, (0, 0))
            self.paint.sel_mask = cur if cur.count() else None
        else:
            self.paint.sel_mask = rm

    def _commit_sel_move(self):
        sp, layer = self._active_layer()
        if layer is None:
            return
        flo = self.drag["float"]
        sx, sy = self.drag["start"]
        px, py = self._canvas_pixel()
        dx, dy = px - sx, py - sy
        layer.surface.blit(flo, (dx, dy))
        if (dx or dy) and self.paint.sel_mask is not None:
            W, H = layer.surface.get_size()
            nm = pygame.mask.Mask((W, H))
            nm.draw(self.paint.sel_mask, (dx, dy))
            self.paint.sel_mask = nm
        self._after_paint(sp)

    # linea: arrastra y suelta.
    def _shape_drag(self):
        a = self.line_anchor
        if a and a["tool"] == "line":
            a["p1"] = self._canvas_pixel()

    def _shape_release(self):
        a = self.line_anchor
        if a and a["tool"] == "line":
            sp, layer = self._active_layer()
            if layer is not None and a["p0"] != a["p1"]:
                self._paint_push_undo(sp, layer)
                paint.line(layer.surface, a["p0"][0], a["p0"][1],
                           a["p1"][0], a["p1"][1], self.paint.color,
                           self.paint.brush, self.paint.sel_mask)
                self._after_paint(sp)
            self.line_anchor = None

    def commit_curve(self):
        a = self.line_anchor
        if not a or a.get("tool") != "curve":
            return
        if len(a["pts"]) >= 2:
            sp, layer = self._active_layer()
            if layer is not None:
                self._paint_push_undo(sp, layer)
                paint.spline(layer.surface, a["pts"], self.paint.color,
                             self.paint.brush, self.paint.sel_mask)
                self._after_paint(sp)
        self.line_anchor = None

    # ====================================================================
    # interaccion del canvas (modo Animar)
    # ====================================================================
    def _handle_canvas(self):
        if self.modal is not None:
            return
        if self.mode == "paint":
            self._handle_paint_canvas()
            return
        c = self.r_canvas
        over = c.collidepoint(self.mouse)

        if self.pan:
            if pygame.mouse.get_pressed()[1]:
                sp, cx, cy, _, _ = self.pan
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
        if self.tool == "hand":
            self.drag = {"mode": "pan_canvas", "sx": self.mouse,
                         "cx": self.cam_x, "cy": self.cam_y}
            return
        if self.tool == "link":
            self._link_press()
            return
        if self.tool == "scale":
            rb, rm = self._scale_mode_rects()         # clic en el toggle de modo
            if rb.collidepoint(self.mouse):
                self.scale_mode = "bones"
                return
            if rm.collidepoint(self.mouse):
                self.scale_mode = "materials"
                return
            self.snapshot()
            pr = self.project
            self.drag = {"mode": "global_scale", "sx": self.mouse, "applied": 1.0,
                         "smode": self.scale_mode,
                         "pivot": (pr.box_x + pr.tile_w / 2.0,
                                   pr.box_y + pr.tile_h / 2.0)}
            return
        if self.tool == "move":
            self.snapshot()
            self.drag = {"mode": "global_move"}
            return
        if self.tool == "bone":
            if self.project.kind == "ropa":   # la ropa usa el rig del body
                self.status = ("El esqueleto es del body de referencia: no se "
                               "edita. Enlaza la prenda al hueso con 'C'.")
                return
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
        if ssp is not None and ssp.surface is not None:
            (pcx, pcy), (hx, hy), wrot = self._sprite_handle(ssp)
            on_handle = math.hypot(self.mouse[0] - hx, self.mouse[1] - hy) < 11
            if on_handle or self._near_sprite_corner(ssp):
                self.snapshot()
                ang0 = math.degrees(math.atan2(self.mouse[1] - pcy,
                                               self.mouse[0] - pcx))
                self.drag = {"mode": "sprite_rotate", "idx": self.sel_idx,
                             "ang0": ang0, "rot0": wrot,          # rot MUNDO
                             "pcx": pcx, "pcy": pcy,
                             "center": self.s2w(pcx, pcy)}        # centro fijo
                return
        hb = self._hit_bone(*self.mouse) if self.show_bones else None
        if hb is not None:
            idx, part = hb
            self.sel_kind, self.sel_idx = "bone", idx
            if self.project.kind == "ropa":   # rig del body: seleccionar, NO mover
                return
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
        m = self.drag["mode"]
        if m == "pan_canvas":
            s0 = self.drag["sx"]
            self.cam_x = self.drag["cx"] - (self.mouse[0] - s0[0]) / self.zoom
            self.cam_y = self.drag["cy"] - (self.mouse[1] - s0[1]) / self.zoom
            return
        if m == "global_scale":
            target = max(0.05, min(20.0,
                         1.0 + (self.mouse[0] - self.drag["sx"][0]) * 0.01))
            f = target / self.drag["applied"]
            if self.drag.get("smode") == "materials":
                self.apply_material_scale(f)
                lbl = "MATERIALES"
            else:
                self.apply_global_scale(f, self.drag["pivot"])
                lbl = "ESQUELETO"
            self.drag["applied"] = target
            self.status = f"Escalar {lbl} x{target:.2f} (toda la animacion)"
            return

        mwx, mwy = self.s2w(*self.mouse)
        pwx, pwy = self.s2w(*self.prev_mouse)

        if m == "global_move":
            self.apply_global_move(mwx - pwx, mwy - pwy)
            return

        if m == "sprite_rotate":
            sp = self.project.sprites[self.drag["idx"]]
            ang = math.degrees(math.atan2(self.mouse[1] - self.drag["pcy"],
                                          self.mouse[0] - self.drag["pcx"]))
            rot = self.drag["rot0"] + (ang - self.drag["ang0"])
            if pygame.key.get_mods() & pygame.KMOD_CTRL:
                rot = round(rot / 15.0) * 15.0
            self._set_sprite_rot_keep_center(sp, rot, self.drag["center"])
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

    def _switch(self, rect, on, label=""):
        """Toggle tipo pastilla (iOS): etiqueta a la izquierda + pastilla con
        knob deslizante a la derecha. Devuelve True si se hizo click."""
        hot = rect.collidepoint(self.mouse)
        if label:
            self.text(label, (rect.x, rect.centery - 7), TEXT, font=self.font_s)
        pw, ph = 46, 22
        track = pygame.Rect(rect.right - pw, rect.centery - ph // 2, pw, ph)
        base = (95, 185, 120) if on else (70, 73, 84)
        col = tuple(min(255, c + 20) for c in base) if hot else base
        pygame.draw.rect(self.screen, col, track, border_radius=ph // 2)
        pygame.draw.rect(self.screen, LINE, track, 1, border_radius=ph // 2)
        self.text("SI" if on else "NO",
                  (track.x + 13 if on else track.right - 13, track.centery),
                  (252, 254, 255) if on else DIM, font=self.font_s, center=True)
        kr = ph - 6
        kx = (track.right - kr - 3) if on else (track.x + 3)
        knob = pygame.Rect(kx, track.y + 3, kr, kr)
        pygame.draw.ellipse(self.screen, (245, 247, 250), knob)
        pygame.draw.ellipse(self.screen, (205, 209, 218), knob, 1)
        return self.lmb_down and hot

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

    def _slider(self, sid, rect, value, lo=0.0, hi=1.0):
        """Barra de progreso arrastrable (posicion absoluta). Devuelve (val, chg).
        No toca el historial (es un ajuste de vista)."""
        hot = rect.collidepoint(self.mouse)
        active = self.active_scrub == sid
        if active and not self.lmb_held:
            self.active_scrub = None
            active = False
        elif self.lmb_down and hot and self.active_scrub is None:
            self.active_scrub = sid
            active = True
        new = value
        if active:
            t = (self.mouse[0] - rect.x) / max(1, rect.w)
            new = lo + max(0.0, min(1.0, t)) * (hi - lo)
        t = (new - lo) / (hi - lo) if hi > lo else 0.0
        t = max(0.0, min(1.0, t))
        track = pygame.Rect(rect.x, rect.centery - 3, rect.w, 6)
        pygame.draw.rect(self.screen, (34, 36, 44), track, border_radius=3)
        fw = int(rect.w * t)
        if fw > 0:
            pygame.draw.rect(self.screen, ACCENT,
                             (rect.x, rect.centery - 3, fw, 6), border_radius=3)
        kx = rect.x + fw
        pygame.draw.circle(self.screen, (245, 247, 250), (kx, rect.centery), 7)
        pygame.draw.circle(self.screen, LINE, (kx, rect.centery), 7, 1)
        return new, (new != value)

    # ====================================================================
    # dibujo
    # ====================================================================
    def _draw(self):
        self.screen.fill(BG)
        self._preview = None          # se llena al pasar el mouse por una fila
        # con un modal abierto, la UI de fondo no debe recibir clicks
        saved_lmb = self.lmb_down
        if self.modal is not None:
            self.lmb_down = False
        if self.mode == "paint":
            self._draw_paint_canvas()
        else:
            self._draw_canvas()
        self._draw_toolbar()
        self._draw_topbar()
        self._draw_left()
        self._draw_right()
        self._draw_timeline()
        self._draw_splitters()
        # preview de hover ENCIMA de todo (incl. la seccion de animacion) y completo
        if self._preview is not None and self.modal is None:
            self._draw_preview(*self._preview)
        if self.recovery_data:
            self._draw_recovery_banner()
        if self.show_help:
            self._draw_help()
        if self.modal is not None:
            self.lmb_down = saved_lmb
            self._draw_modal()

    def _draw_modal(self):
        kind, data = self.modal
        # velo
        veil = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
        veil.fill((0, 0, 0, 150))
        self.screen.blit(veil, (0, 0))
        self._drawing_modal = True
        w, h = self.screen.get_size()
        if kind == "template":
            rows = data or []
            mw = 360
            mh = 92 + max(1, len(rows)) * 30 + 64
            r = pygame.Rect((w - mw) // 2, (h - mh) // 2, mw, mh)
            pygame.draw.rect(self.screen, PANEL, r, border_radius=8)
            pygame.draw.rect(self.screen, ACCENT, r, 1, border_radius=8)
            self.text("Plantillas", (r.x + 14, r.y + 12), ACCENT, font=self.font_b)
            self.text("(esqueleto + animaciones; tu dibujas y asignas)",
                      (r.x + 14, r.y + 32), DIM, font=self.font_s)
            y = r.y + 56
            if not rows:
                self.text("No hay plantillas aún.", (r.x + 14, y), DIM,
                          font=self.font_s)
                y += 28
            for name, path in rows:
                br = pygame.Rect(r.x + 12, y, mw - 24, 26)
                if self.button(br, "Cargar: " + name):
                    self.modal = None
                    self.load_template(path)
                    self._drawing_modal = False
                    return
                y += 30
            pygame.draw.line(self.screen, LINE, (r.x + 12, y + 4),
                             (r.right - 12, y + 4))
            sv = pygame.Rect(r.x + 12, y + 12, mw - 24, 26)
            if self.button(sv, "Guardar proyecto actual como plantilla"):
                self.modal = None
                self.save_current_as_template()
                self._drawing_modal = False
                return
            cr = pygame.Rect(r.x + 12, r.bottom - 34, mw - 24, 24)
            if self.button(cr, "Cancelar (Esc)"):
                self.modal = None
        elif kind == "export":
            opts = [("Exportar hoja (todo junto)", self.export_composite),
                    ("Exportar capas (una por sprite)", self.export_layers),
                    ("Exportar material (recortado + conexión)", self.export_connection)]
            mw = 360
            mh = 70 + len(opts) * 30 + 30
            r = pygame.Rect((w - mw) // 2, (h - mh) // 2, mw, mh)
            pygame.draw.rect(self.screen, PANEL, r, border_radius=8)
            pygame.draw.rect(self.screen, ACCENT, r, 1, border_radius=8)
            self.text("Exportar", (r.x + 14, r.y + 12), ACCENT, font=self.font_b)
            self.text("(elige el formato de salida)", (r.x + 14, r.y + 32), DIM,
                      font=self.font_s)
            y = r.y + 56
            for label, fn in opts:
                if self.button(pygame.Rect(r.x + 12, y, mw - 24, 26), label):
                    self.modal = None
                    fn()
                    self._drawing_modal = False
                    return
                y += 30
            cr = pygame.Rect(r.x + 12, r.bottom - 34, mw - 24, 24)
            if self.button(cr, "Cancelar (Esc)"):
                self.modal = None
        elif kind == "newkind":
            self._modal_menu("Nuevo elemento", "¿Que vas a crear?", [
                ("body", "Body nuevo",
                 "Cuerpo + animaciones, partiendo del estandar",
                 self.new_body_project),
                ("box", "Item nuevo",
                 "Ropa o caracteristica, sobre el body estandar",
                 lambda: setattr(self, "modal", ("newitem", None))),
                ("grid", "Tile / material",
                 "Terreno y construccion para el juego (pasto, piedra, muros...)",
                 lambda: setattr(self, "modal",
                                 ("newtile", {"size": 64, "frames": 1}))),
                ("page", "Proyecto en blanco",
                 "Empezar de cero, sin plantilla", self.new_blank_project),
            ])
        elif kind == "cargpreview":
            img = self._cargable_preview_surface(scale=3)
            mw = max(300, (img.get_width() if img else 200) + 40)
            mh = (img.get_height() if img else 160) + 92
            r = pygame.Rect((w - mw) // 2, (h - mh) // 2, mw, mh)
            pygame.draw.rect(self.screen, PANEL, r, border_radius=10)
            pygame.draw.rect(self.screen, ACCENT, r, 2, border_radius=10)
            self.text("Preview en el body estandar", (r.x + 16, r.y + 12), ACCENT,
                      font=self.font_b)
            self.text("maletin (frame 2) detras del body · brazos (frame 1) delante",
                      (r.x + 16, r.y + 32), DIM, font=self.font_s)
            if img is not None:
                self._draw_checker(pygame.Rect(r.x + 20, r.y + 52,
                                               img.get_width(), img.get_height()))
                self.screen.blit(img, (r.x + 20, r.y + 52))
            else:
                self.text("Sin body de referencia o sin frames.",
                          (r.x + 20, r.y + 60), DIM, font=self.font_s)
            # switch (pastilla) quitar/poner camisa de guia + cerrar
            half = (mw - 32 - 8) // 2
            sw = pygame.Rect(r.x + 16, r.bottom - 36, half, 26)
            name = self._shirt_label().split(": ", 1)[-1]
            if self._switch(sw, self.shirt_idx >= 0, f"Camisa  {name}"):
                self._toggle_shirt()
            cr = pygame.Rect(sw.right + 8, r.bottom - 34, r.right - 16 - sw.right - 8, 24)
            if self.button(cr, "Cerrar (Esc)"):
                self.modal = None
        elif kind == "newitem":
            self._modal_menu("Nuevo item",
                             "Se usa el body estandar como guia (fantasma)", [
                ("shirt", "Ropa",
                 "Sigue al cuerpo: camisa, pantalon, zapatos",
                 lambda: self.new_item_project("ropa")),
                ("face", "Caracteristica",
                 "Cara / pelo por conexion (socket)",
                 lambda: self.new_item_project("caracteristica")),
                ("box", "Cargable / Sujetable",
                 "Mochila, antorcha... 2 frames: atras + adelante",
                 lambda: self.new_item_project("cargable")),
            ], back=("newkind", None))
        elif kind == "newtile":
            self._modal_newtile(data)
        elif kind == "syncbodies":
            self._modal_syncbodies(data)
        self._drawing_modal = False

    def _modal_menu(self, title, subtitle, cards, back=None):
        """Modal con tarjetas grandes (icono + titulo + descripcion)."""
        w, h = self.screen.get_size()
        mw, ch = 460, 62
        mh = 80 + len(cards) * (ch + 10) + 40
        r = pygame.Rect((w - mw) // 2, (h - mh) // 2, mw, mh)
        sh = pygame.Surface((r.w + 16, r.h + 16), pygame.SRCALPHA)
        sh.fill((0, 0, 0, 120))
        self.screen.blit(sh, (r.x - 8, r.y - 4))
        pygame.draw.rect(self.screen, PANEL, r, border_radius=12)
        pygame.draw.rect(self.screen, ACCENT, r, 2, border_radius=12)
        self.text(title, (r.x + 20, r.y + 16), ACCENT, font=self.font_b)
        self.text(subtitle, (r.x + 20, r.y + 38), DIM, font=self.font_s)
        y = r.y + 66
        for icon, t, sub, fn in cards:
            card = pygame.Rect(r.x + 16, y, mw - 32, ch)
            hot = card.collidepoint(self.mouse)
            pygame.draw.rect(self.screen, HOVER if hot else PANEL2, card,
                             border_radius=10)
            pygame.draw.rect(self.screen, ACCENT if hot else LINE, card,
                             2 if hot else 1, border_radius=10)
            ib = pygame.Rect(card.x + 10, card.y + 10, ch - 20, ch - 20)
            pygame.draw.rect(self.screen, (28, 31, 40), ib, border_radius=8)
            pygame.draw.rect(self.screen, ACCENT if hot else LINE, ib, 1,
                             border_radius=8)
            self._draw_icon(icon, ib.inflate(-8, -8), ACCENT if hot else TEXT)
            self.text(t, (ib.right + 14, card.y + 12),
                      SELECT if hot else TEXT, font=self.font_b)
            self.text(sub, (ib.right + 14, card.y + 34), DIM, font=self.font_s)
            if self.lmb_down and hot:
                fn()
                self._drawing_modal = False
                return
            y += ch + 10
        cr = pygame.Rect(r.x + 16, r.bottom - 32, mw - 32, 24)
        if self.button(cr, "‹ Atras" if back else "Cancelar (Esc)"):
            self.modal = back

    def _modal_newtile(self, data):
        """Modal: tamano (lienzo cuadrado) y frames del nuevo tile/material."""
        w, h = self.screen.get_size()
        d = data if isinstance(data, dict) else {}
        d.setdefault("size", 64)
        d.setdefault("frames", 1)
        mw, mh = 460, 262
        r = pygame.Rect((w - mw) // 2, (h - mh) // 2, mw, mh)
        sh = pygame.Surface((r.w + 16, r.h + 16), pygame.SRCALPHA)
        sh.fill((0, 0, 0, 120))
        self.screen.blit(sh, (r.x - 8, r.y - 4))
        pygame.draw.rect(self.screen, PANEL, r, border_radius=12)
        pygame.draw.rect(self.screen, ACCENT, r, 2, border_radius=12)
        self.text("Nuevo tile / material", (r.x + 20, r.y + 16), ACCENT,
                  font=self.font_b)
        self.text("Terreno y construccion para el juego (pasto, piedra, muros...)",
                  (r.x + 20, r.y + 38), DIM, font=self.font_s)
        # -- tamano del lienzo (los tiles del juego son CUADRADOS) --
        y = r.y + 66
        self.text("Tamaño (px)", (r.x + 20, y + 1), TEXT, font=self.font_s)
        bx = r.x + 130
        bw = (r.right - 20 - bx - 3 * 8) // 4
        for s in (16, 32, 64, 128):
            if self.button(pygame.Rect(bx, y - 4, bw, 26), str(s),
                           active=d["size"] == s):
                d["size"] = s
            bx += bw + 8
        # -- frames (1 = estatico; mas = tira horizontal animada) --
        y += 40
        self.text("Frames", (r.x + 20, y + 1), TEXT, font=self.font_s)
        minus = pygame.Rect(r.x + 130, y - 4, 26, 26)
        plus = pygame.Rect(minus.right + 56, y - 4, 26, 26)
        if self.button(minus, "-", enabled=d["frames"] > 1):
            d["frames"] = max(1, d["frames"] - 1)
        self.text(str(d["frames"]), ((minus.right + plus.x) // 2, minus.centery),
                  TEXT, font=self.font_b, center=True)
        if self.button(plus, "+", enabled=d["frames"] < 16):
            d["frames"] = min(16, d["frames"] + 1)
        self.text(f"PNG: {d['frames'] * d['size']}x{d['size']}",
                  (r.right - 20, minus.centery), DIM, font=self.font_s, right=True)
        y += 34
        self.text("1 = tile estatico · 2-16 = tira animada (la fogata usa 9)",
                  (r.x + 20, y), DIM, font=self.font_s)
        # -- crear / volver --
        cr = pygame.Rect(r.x + 16, r.bottom - 66, mw - 32, 28)
        if self.button(cr, f"Crear tile {d['size']}x{d['size']} · "
                           f"{d['frames']} frame/s", active=True):
            self.new_tile_project(d["size"], d["frames"])
            return
        br = pygame.Rect(r.x + 16, r.bottom - 32, mw - 32, 24)
        if self.button(br, "‹ Atras"):
            self.modal = ("newkind", None)

    # -- sincronizar conexiones/animaciones a otros bodies ----------------
    def _open_syncbodies(self):
        """Abre el modal para copiar las conexiones (anchors) y animaciones
        nuevas de este body al resto de bodies de art-src/characters/body."""
        src = self.src_root()
        p = os.path.abspath(self.project.path) if self.project.path else None
        if not (self.project_root and src and p):
            self.status = ("Sincronizar: define el proyecto y guarda el body "
                           f"bajo {self.src_dir}/characters/body primero.")
            return
        body_dir = os.path.abspath(os.path.join(src, "characters", "body"))
        if not p.startswith(body_dir + os.sep):
            self.status = ("Sincronizar: solo disponible con un body de "
                           f"{self.src_dir}/characters/body abierto.")
            return
        bodies = [(nm, pth) for nm, pth in
                  syncbodies.list_bodies(self.project_root, self.src_dir)
                  if os.path.abspath(pth) != p]
        self.modal = ("syncbodies", {"bodies": bodies, "sel": set(),
                                     "anchors": True, "clips": True,
                                     "reexport": True, "results": None,
                                     "scroll": 0})

    def _run_syncbodies(self, data):
        """Ejecuta la sincronizacion y deja el modal en modo resultados."""
        if self.dirty:                    # el origen debe estar en disco
            self.save_project()
        paths = [pth for _, pth in data["bodies"] if pth in data["sel"]]
        try:
            res = syncbodies.sync_to_bodies(
                self.project, paths, sync_anchors=data["anchors"],
                sync_clips=data["clips"], reexport=data["reexport"],
                src_dir=self.src_dir, assets_dir=self.assets_dir)
        except Exception as e:
            self.status = f"Error al sincronizar: {e}"
            return
        data["results"] = res
        data["scroll"] = 0
        ok = sum(1 for it in res if it.get("ok"))
        exp = sum(1 for it in res if it.get("exported"))
        msg = f"{ok}/{len(res)} bodies sincronizados"
        if data["reexport"]:
            msg += (" y exportados" if exp == len(res)
                    else f" ({exp} exportados)")
        self.status = msg

    def _modal_syncbodies(self, data):
        """Modal: elegir bodies destino + opciones; luego muestra resultados."""
        w, h = self.screen.get_size()
        if data.get("plan") is None:
            data["plan"] = syncbodies.plan_sync(self.project)
        plan = data["plan"]
        origin = os.path.basename(os.path.dirname(self.project.path or "")) or "?"
        results = data["results"]
        mw = 480
        if results is None:
            vis = min(max(1, len(data["bodies"])), 8)
            list_h = vis * 34
            mh = 240 + list_h
        else:
            vis = min(max(1, len(results)), 7)
            list_h = vis * 44
            mh = 122 + list_h
        r = pygame.Rect((w - mw) // 2, (h - mh) // 2, mw, mh)
        sh = pygame.Surface((r.w + 16, r.h + 16), pygame.SRCALPHA)
        sh.fill((0, 0, 0, 120))
        self.screen.blit(sh, (r.x - 8, r.y - 4))
        pygame.draw.rect(self.screen, PANEL, r, border_radius=12)
        pygame.draw.rect(self.screen, ACCENT, r, 2, border_radius=12)
        self.text("Sincronizar conexiones", (r.x + 20, r.y + 16), ACCENT,
                  font=self.font_b)
        self.text(f"Origen: {origin} · {len(plan.get('anchors', []))} "
                  f"conexiones, {len(plan.get('clips', []))} animaciones",
                  (r.x + 20, r.y + 40), DIM, font=self.font_s)
        x = r.x + 20
        iw = mw - 40
        y = r.y + 66
        if results is None:
            # -- vista de seleccion de destinos ---------------------------
            bodies = data["bodies"]
            sel = data["sel"]
            if self.button(pygame.Rect(x, y, 90, 22), "Todos"):
                sel.clear()
                sel.update(pth for _, pth in bodies)
            if self.button(pygame.Rect(x + 96, y, 90, 22), "Ninguno"):
                sel.clear()
            y += 30
            lrect = pygame.Rect(x, y, iw, list_h)
            maxs = max(0, len(bodies) - vis)
            if self.wheel and lrect.collidepoint(self.mouse):
                data["scroll"] -= self.wheel
            data["scroll"] = max(0, min(maxs, data["scroll"]))
            sc = data["scroll"]
            if not bodies:
                self.text("No hay otros bodies en characters/body.",
                          (x, y + 8), DIM, font=self.font_s)
            for i in range(sc, min(len(bodies), sc + vis)):
                name, path = bodies[i]
                br = pygame.Rect(x, y + (i - sc) * 34, iw - 10, 30)
                on = path in sel
                hot = br.collidepoint(self.mouse)
                col = (46, 92, 64) if on else (HOVER if hot else PANEL2)
                pygame.draw.rect(self.screen, col, br, border_radius=5)
                pygame.draw.rect(self.screen,
                                 (120, 210, 150) if on else LINE, br, 1,
                                 border_radius=5)
                self.text(name, (br.x + 10, br.centery - 7), TEXT,
                          font=self.font_s)
                self.text("✓" if on else "—", (br.right - 16, br.centery),
                          (150, 220, 170) if on else DIM, font=self.font_s,
                          center=True)
                if self.lmb_down and hot:
                    if on:
                        sel.discard(path)
                    else:
                        sel.add(path)
            self._scrollbar(lrect, sc, len(bodies), vis, maxs)
            y += list_h + 10
            for key, lbl in (("anchors", "Conexiones"),
                             ("clips", "Animaciones nuevas"),
                             ("reexport", "Re-exportar al juego")):
                if self._switch(pygame.Rect(x, y, iw, 24), data[key], lbl):
                    data[key] = not data[key]
                y += 26
            pw = (iw - 8) // 2
            ob = pygame.Rect(x, r.bottom - 34, pw, 26)
            if self.button(ob, f"Sincronizar ({len(sel)})",
                           active=bool(sel), enabled=bool(sel)):
                self._run_syncbodies(data)
            if self.button(pygame.Rect(ob.right + 8, r.bottom - 34, pw, 26),
                           "Cancelar (Esc)"):
                self.modal = None
        else:
            # -- vista de resultados --------------------------------------
            lrect = pygame.Rect(x, y, iw, list_h)
            maxs = max(0, len(results) - vis)
            if self.wheel and lrect.collidepoint(self.mouse):
                data["scroll"] -= self.wheel
            data["scroll"] = max(0, min(maxs, data["scroll"]))
            sc = data["scroll"]
            for i in range(sc, min(len(results), sc + vis)):
                it = results[i]
                rr = pygame.Rect(x, y + (i - sc) * 44, iw - 10, 40)
                pygame.draw.rect(self.screen, PANEL2, rr, border_radius=5)
                pygame.draw.rect(self.screen, LINE, rr, 1, border_radius=5)
                ok = bool(it.get("ok"))
                self.text("✓" if ok else "✗", (rr.x + 14, rr.centery),
                          (120, 210, 150) if ok else (230, 110, 110),
                          font=self.font_b, center=True)
                self.text(it.get("name", "?"), (rr.x + 28, rr.y + 4), TEXT,
                          font=self.font_s)
                if ok:
                    info = (f"{it.get('anchors', 0)} conexiones · "
                            f"{it.get('clips_added', 0)} anims nuevas · "
                            + ("exportado" if it.get("exported")
                               else "sin exportar"))
                    if it.get("msg"):
                        info += f" · {it['msg']}"
                else:
                    info = it.get("msg", "error")
                self.text(info[:70], (rr.x + 28, rr.y + 21),
                          DIM if ok else (230, 140, 140), font=self.font_s)
            self._scrollbar(lrect, sc, len(results), vis, maxs)
            if self.button(pygame.Rect(x, r.bottom - 34, iw, 26),
                           "Cerrar (Esc)"):
                self.modal = None

    def _draw_canvas(self):
        c = self.r_canvas
        pygame.draw.rect(self.screen, CANVAS_BG, c)
        self.screen.set_clip(c)
        self._draw_grid()
        # recuadro de exportacion de la ANIMACION activa (puede ser mas ancho)
        cbx, cby, ccw, cch = (render.clip_box(self.project, self.clip)
                              if self.clip else
                              (self.project.box_x, self.project.box_y,
                               self.project.tile_w, self.project.tile_h))
        bx, by = self.w2s(cbx, cby)
        box = pygame.Rect(int(bx), int(by), int(ccw * self.zoom),
                          int(cch * self.zoom))
        pygame.draw.rect(self.screen, (24, 26, 32), box)
        self._draw_grid(box)
        pygame.draw.rect(self.screen, ACCENT, box, 1)

        # body de guia (fantasma). Para ROPA, si el body define clothes_z, se
        # parte: lo de ATRAS detras de la prenda y lo de ADELANTE (brazo del
        # frente) ENCIMA -> ves la profundidad real mientras editas.
        back, front = self._ghost_bands()
        self._draw_ghost_body(back)
        if self.project.kind == "cargable":      # camisa de guia sobre el body
            self._draw_shirt_overlay()
        render.draw_sprites(self.screen, self.project, self.active_frame(),
                            self.w2s, zoom=self.zoom)
        if front:
            self._draw_ghost_body(front)
        if self.show_z and not self.playing:
            self._draw_z_overlay()

        if self.show_bones:
            if self.playing:
                self._draw_bones(ghost=True)     # tenues, sin texto, al reproducir
            else:
                self._draw_links()
                self._draw_bones()
        if not self.playing:
            if self.project.kind == "caracteristica":
                self._draw_ref_sockets()      # sockets del body (rig no injertado)
            self._draw_socket_overlay()
            self._draw_sprite_gizmo()
        if self.tool == "link" and not self.playing:
            self._draw_link_gesture()
        if self.drag and self.drag["mode"] == "bone_create":
            h = self.w2s(*self.drag["head"])
            pygame.draw.line(self.screen, BONE_SEL, h, self.mouse, 2)
            pygame.draw.circle(self.screen, BONE_SEL,
                               (int(h[0]), int(h[1])), 5, 1)
        self.screen.set_clip(None)

        tool_lbl = {"select": "SELECCION (V)", "bone": "HUESO (B)",
                    "link": "ENLACE (C)", "scale": "ESCALAR (E)",
                    "move": "MOVER (M)",
                    "hand": "MANO (H)"}.get(self.tool, self.tool)
        self.text(tool_lbl, (c.x + 56, c.y + 8), ACCENT, font=self.font_b)
        if self.tool == "scale":                      # toggle de modo de escala
            rb, rm = self._scale_mode_rects()
            self._mode_pill(rb, "Esqueleto", self.scale_mode == "bones")
            self._mode_pill(rm, "Materiales", self.scale_mode == "materials")
        fr = ("Reposo" if self.cur_frame < 0
              else f"Frame {self.cur_frame+1}/{len(self.frames)}")
        self.text(fr, (c.right - 10, c.y + 8), TEXT, font=self.font_b, right=True)
        self._draw_ghost_controls()

    def _scale_mode_rects(self):
        c = self.r_canvas
        y = c.y + 4
        rb = pygame.Rect(c.x + 150, y, 82, 20)
        rm = pygame.Rect(c.x + 236, y, 86, 20)
        return rb, rm

    def _mode_pill(self, rect, label, active):
        hot = rect.collidepoint(self.mouse)
        col = ACTIVE if active else (HOVER if hot else PANEL2)
        pygame.draw.rect(self.screen, col, rect, border_radius=10)
        pygame.draw.rect(self.screen, ACCENT if active else LINE, rect, 1,
                         border_radius=10)
        self.text(label, rect.center, TEXT if active else DIM,
                  font=self.font_s, center=True)

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
        """Linea sutil SOLO del sprite seleccionado a su hueso (sin saturar)."""
        sp = self.selected_sprite()
        if sp is None or not sp.bone or sp.surface is None:
            return
        bidx = self.project.bone_by_name(sp.bone)
        if bidx < 0:
            return
        pose = self.pose_for()
        sw = model.sprite_world(self.project, sp, pose)
        bw = model.bone_world(self.project, bidx, pose)
        pygame.draw.line(self.screen, (110, 140, 110),
                         self.w2s(sw[0], sw[1]), self.w2s(bw[0], bw[1]), 1)

    def _draw_chain(self, a, b):
        """Cadena/hilo animado entre dos puntos de pantalla (guia temporal)."""
        ax, ay = a
        bx, by = b
        dx, dy = bx - ax, by - ay
        dist = math.hypot(dx, dy)
        if dist < 1:
            pygame.draw.circle(self.screen, ACCENT, (int(ax), int(ay)), 4, 1)
            return
        ux, uy = dx / dist, dy / dist
        pygame.draw.line(self.screen, (90, 80, 50), a, b, 1)
        step = 9
        d = (pygame.time.get_ticks() / 60.0) % step      # marcha animada
        i = 0
        while d < dist:
            x, y = ax + ux * d, ay + uy * d
            col = ACCENT if i % 2 == 0 else SELECT
            pygame.draw.circle(self.screen, col, (int(x), int(y)), 3, 2)
            d += step
            i += 1
        pygame.draw.circle(self.screen, ACCENT, (int(ax), int(ay)), 4)
        pygame.draw.circle(self.screen, SELECT, (int(bx), int(by)), 4, 1)

    def _draw_link_gesture(self):
        if self.link_bone is None or self.link_bone >= len(self.project.bones):
            return
        head, _ = self._bone_endpoints_screen(self.link_bone, self.pose_for())
        self._draw_chain(head, self.mouse)
        hs = self._hit_sprite(*self.mouse)      # resaltar imagen objetivo
        if hs >= 0:
            self._highlight_sprite(hs)

    def _highlight_sprite(self, idx):
        sp = self.project.sprites[idx]
        if sp.surface is None or not sp.content_rect:
            return
        wt = model.sprite_world(self.project, sp, self.pose_for())
        cx, cy, cw, ch = sp.content_rect
        pts = []
        for ix, iy in ((cx, cy), (cx + cw, cy), (cx + cw, cy + ch), (cx, cy + ch)):
            ox, oy = model._rot((ix - sp.pivot[0]) * wt[3],
                                (iy - sp.pivot[1]) * wt[3], wt[2])
            pts.append(self.w2s(wt[0] + ox, wt[1] + oy))
        pygame.draw.polygon(self.screen, (130, 220, 150), pts, 2)

    def _draw_ref_sockets(self):
        """Dibuja los SOCKETS del body de referencia (ojos/pelo/...) como guia,
        para colocar una caracteristica relativa a su conexion."""
        rp = self.ref_project
        if rp is None:
            return
        pf = model.pose_for_frame(rp, self._ref_idle_frame())
        for idx, b in enumerate(rp.bones):
            if not getattr(b, "anchor", False) or b.name not in model.SOCKETS:
                continue
            wx, wy, _, _ = model.bone_world(rp, idx, pf)
            sx, sy = self.w2s(wx, wy)
            self._socket_marker(int(sx), int(sy), b.name, False)

    def _front_band_ids(self, pr):
        """Indices de sprites que van en la banda DELANTE de la ropa.
        - body: las partes con z > clothes_z.
        - ropa: las partes cuyo HUESO del body tiene z > clothes_z (la manga
          enlazada al brazo del frente se va sola al frente). Automatico."""
        if pr.kind == "body" and pr.clothes_z is not None:
            return {i for i, s in enumerate(pr.sprites) if s.z > pr.clothes_z}
        if pr.kind == "ropa" and self.ref_project is not None \
                and self.ref_project.clothes_z is not None:
            cz = self.ref_project.clothes_z
            bone_z = {}                       # hueso -> z maximo del body en el
            for s in self.ref_project.sprites:
                if s.bone:
                    bone_z[s.bone] = max(bone_z.get(s.bone, -1e9), s.z)
            return {i for i, s in enumerate(pr.sprites)
                    if s.bone and bone_z.get(s.bone, -1e9) > cz}
        return set()

    def _ghost_bands(self):
        """(back, front): filtros de sprites del body de referencia partidos por
        su clothes_z, para dibujar lo de adelante SOBRE la prenda. (None, None) si
        no aplica (sin clothes_z o no es ropa)."""
        rp = self.ref_project
        cz = getattr(rp, "clothes_z", None) if rp else None
        if cz is None or self.project.kind != "ropa":
            return None, None
        back = {i for i, s in enumerate(rp.sprites) if s.z <= cz}
        front = {i for i, s in enumerate(rp.sprites) if s.z > cz}
        return back, (front or None)

    def _gop(self, base):
        """Alpha del fantasma escalado por el slider (base = el maximo actual)."""
        return max(0, min(255, int(base * self.ghost_op)))

    def _z_color(self, z, zmin, zmax):
        """Color por profundidad: azul (atras) -> verde -> naranja (frente)."""
        t = (z - zmin) / (zmax - zmin) if zmax > zmin else 0.5
        t = max(0.0, min(1.0, t))
        stops = [(0.0, (60, 130, 240)), (0.5, (70, 200, 150)), (1.0, (245, 140, 70))]
        for k in range(len(stops) - 1):
            t0, c0 = stops[k]
            t1, c1 = stops[k + 1]
            if t <= t1 or k == len(stops) - 2:
                f = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
                f = max(0.0, min(1.0, f))
                return tuple(int(c0[j] + (c1[j] - c0[j]) * f) for j in range(3))
        return stops[-1][1]

    def _z_pill(self, pos, z, col, front):
        """Etiqueta del z de una parte: pastilla del color de profundidad. Las
        partes DELANTE de la ropa (z > clothes_z) llevan anillo blanco."""
        txt = str(int(z))
        r = pygame.Rect(0, 0, 22 + 6 * (len(txt) - 1), 16)
        r.center = (int(pos[0]), int(pos[1]))
        pygame.draw.rect(self.screen, (16, 18, 24), r.inflate(4, 4), border_radius=8)
        pygame.draw.rect(self.screen, col, r, border_radius=8)
        if front:
            pygame.draw.rect(self.screen, (255, 255, 255), r, 2, border_radius=8)
        self.text(txt, r.center, (16, 18, 24), font=self.font_s, center=True)

    def _draw_z_overlay(self):
        """Pinta cada parte del body de referencia teñida por su z-index, con la
        etiqueta del numero, y una leyenda. Para ENTENDER la profundidad al
        dibujar ropa/maletines (que tapa a que)."""
        rp = self.ref_project
        if rp is None or not rp.sprites:
            return
        parts = [(i, s) for i, s in enumerate(rp.sprites)
                 if s.visible and s.surface is not None and s.content_rect]
        if not parts:
            return
        zs = [s.z for _, s in parts]
        zmin, zmax = min(zs), max(zs)
        cz = getattr(rp, "clothes_z", None)
        frame = self._ref_idle_frame()
        box = (rp.box_x, rp.box_y, rp.tile_w, rp.tile_h)
        bx, by = box[0], box[1]
        sw = max(1, int(rp.tile_w * self.zoom))
        sh = max(1, int(rp.tile_h * self.zoom))
        labels = []
        for i, s in sorted(parts, key=lambda t: t[1].z):     # atras -> adelante
            col = self._z_color(s.z, zmin, zmax)
            tile = render.render_tile(rp, frame, {i}, box)
            mask = pygame.mask.from_surface(tile)
            if mask.count() == 0:
                continue
            sil = mask.to_surface(setcolor=(*col, 165), unsetcolor=(0, 0, 0, 0))
            self.screen.blit(pygame.transform.scale(sil, (sw, sh)), self.w2s(bx, by))
            cen = mask.centroid()
            labels.append((self.w2s(bx + cen[0], by + cen[1]), s.z, col,
                           cz is not None and s.z > cz))
        for pos, z, col, front in labels:        # etiquetas SOBRE las siluetas
            self._z_pill(pos, z, col, front)
        self._draw_z_legend(zmin, zmax, cz)

    def _draw_z_legend(self, zmin, zmax, cz):
        c = self.r_canvas
        lw, lh = 16, 170
        lx, ly = c.right - 78, c.y + 80
        for k in range(lh):                       # arriba = frente, abajo = atras
            z = zmax - (k / lh) * (zmax - zmin)
            pygame.draw.line(self.screen, self._z_color(z, zmin, zmax),
                             (lx, ly + k), (lx + lw, ly + k))
        pygame.draw.rect(self.screen, LINE, (lx, ly, lw, lh), 1)
        self.text("frente", (lx + lw + 4, ly - 2), (245, 140, 70), font=self.font_s)
        self.text("atras", (lx + lw + 4, ly + lh - 10), (60, 130, 240),
                  font=self.font_s)
        if cz is not None and zmax > zmin:
            t = (cz - zmin) / (zmax - zmin)
            yk = ly + int((1 - max(0.0, min(1.0, t))) * lh)
            pygame.draw.line(self.screen, (255, 255, 255),
                             (lx - 5, yk), (lx + lw + 5, yk), 2)
            self.text("ropa", (lx - 7, yk - 6), TEXT, font=self.font_s, right=True)

    def _draw_ghost_controls(self):
        """Slider de opacidad del fantasma + toggle del overlay de z, junto al
        titulo 'Reposo' del lienzo. Solo al editar un item con body de guia."""
        if not (self.is_item and self.ref_project is not None):
            return
        c = self.r_canvas
        y = c.y + 7
        # toggle z-index (pastilla clickable)
        zr = pygame.Rect(c.right - 360, y - 4, 86, 22)
        hot = zr.collidepoint(self.mouse)
        active = self.show_z
        pygame.draw.rect(self.screen, ACTIVE if active else (HOVER if hot else PANEL2),
                         zr, border_radius=11)
        pygame.draw.rect(self.screen, ACCENT if active else LINE, zr, 1, border_radius=11)
        self.text("z-index", zr.center, TEXT if active else DIM,
                  font=self.font_s, center=True)
        if self.lmb_down and hot:
            self.show_z = not self.show_z
        # slider de opacidad del fantasma
        self.text("Fantasma", (c.right - 280, y), DIM, font=self.font_s)
        srect = pygame.Rect(c.right - 218, y, 74, 16)
        self.ghost_op, _ = self._slider("ghostop", srect, self.ghost_op)
        self.text(f"{int(self.ghost_op * 100)}%", (c.right - 92, y), TEXT,
                  font=self.font_s, right=True)

    def _draw_ghost_body(self, sprites_filter=None):
        """Dibuja el body de referencia (semi-transparente) como guia. Ropa: con
        el frame actual (rig compartido); caracteristica/cargable: en reposo.
        `sprites_filter` limita a una banda (atras/adelante de la prenda)."""
        rp = self.ref_project
        if rp is None or not rp.sprites:
            return
        frame = (self.active_frame() if self.project.kind == "ropa"
                 else self._ref_idle_frame())
        temp = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
        render.draw_sprites(temp, rp, frame, self.w2s, zoom=self.zoom,
                            sprites_filter=sprites_filter)
        temp.fill((255, 255, 255, self._gop(95)), special_flags=pygame.BLEND_RGBA_MULT)
        self.screen.blit(temp, (0, 0))

    def _ghost_tile_surface(self):
        """Composicion del body de referencia en reposo, en pixeles del tile
        (para el fondo-guia del modo Pintar). Cacheada por tamano."""
        rp = self.ref_project
        if rp is None or not rp.sprites:
            return None
        box = (rp.box_x, rp.box_y, rp.tile_w, rp.tile_h)
        key = (id(rp), box)
        if getattr(self, "_ghost_key", None) != key:
            self._ghost_key = key
            self._ghost_surf = render.render_tile(rp, self._ref_idle_frame(),
                                                  None, box)
        return self._ghost_surf

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

    def _draw_socket_overlay(self):
        """Feedback grafico de las conexiones: un marcador con icono+nombre por
        cada PUNTO del cuerpo (socket), y una etiqueta '-> Ojos' sobre cada
        MATERIAL que ya tiene conexion asignada."""
        pose = self.pose_for()
        # 1) puntos del cuerpo (anchors con nombre de socket)
        for idx, b in enumerate(self.project.bones):
            if not getattr(b, "anchor", False) or b.name not in model.SOCKETS:
                continue
            wx, wy, _, _ = model.bone_world(self.project, idx, pose)
            sx, sy = self.w2s(wx, wy)
            sel = (self.sel_kind == "bone" and self.sel_idx == idx)
            self._socket_marker(int(sx), int(sy), b.name, sel,
                                hover=(idx == self._hover_node))
        # 2) materiales con conexion -> etiqueta en su centro
        for idx, sp in enumerate(self.project.sprites):
            conn = getattr(sp, "connection", None)
            if not conn or sp.surface is None:
                continue
            wt = model.sprite_world(self.project, sp, pose)
            sx, sy = self.w2s(wt[0], wt[1])
            sel = (self.sel_kind == "sprite" and self.sel_idx == idx)
            self._conn_badge(int(sx), int(sy), conn, sel)

    def _socket_marker(self, sx, sy, sid, sel, hover=False):
        col = (190, 255, 210) if sel else (110, 225, 155)
        if hover:
            halo = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
            pygame.draw.circle(halo, (*SELECT, 55), (sx, sy), self.NODE_HIT_R)
            pygame.draw.circle(halo, (*SELECT, 200), (sx, sy), self.NODE_HIT_R, 2)
            self.screen.blit(halo, (0, 0))
        pygame.draw.circle(self.screen, col, (sx, sy), 10, 2)
        pygame.draw.circle(self.screen, (18, 30, 24), (sx, sy), 3)
        pygame.draw.circle(self.screen, col, (sx, sy), 1)
        for a, b in (((-13, 0), (-5, 0)), ((5, 0), (13, 0)),
                     ((0, -13), (0, -5)), ((0, 5), (0, 13))):
            pygame.draw.line(self.screen, col, (sx + a[0], sy + a[1]),
                             (sx + b[0], sy + b[1]))
        lbl = model.SOCKET_LABELS.get(sid, sid)
        tw = self.font_s.size(lbl)[0]
        pill = pygame.Rect(sx + 13, sy - 9, tw + 24, 18)
        bg = pygame.Surface(pill.size, pygame.SRCALPHA)
        bg.fill((16, 38, 26, 225))
        self.screen.blit(bg, pill)
        pygame.draw.rect(self.screen, col, pill, 1, border_radius=4)
        self._draw_icon(self._SOCKET_ICON.get(sid, "hand"),
                        pygame.Rect(pill.x + 3, pill.y + 1, 16, 16), col)
        self.text(lbl, (pill.x + 21, pill.y + 3), (225, 255, 235),
                  font=self.font_s)

    def _conn_badge(self, sx, sy, conn, sel):
        col = SELECT if sel else ACCENT
        pygame.draw.circle(self.screen, col, (sx, sy), 4, 1)
        for a, b in (((-8, 0), (8, 0)), ((0, -8), (0, 8))):
            pygame.draw.line(self.screen, col, (sx + a[0], sy + a[1]),
                             (sx + b[0], sy + b[1]))
        lbl = "→ " + model.SOCKET_LABELS.get(conn, conn)
        tw = self.font_s.size(lbl)[0]
        pill = pygame.Rect(sx - (tw + 24) // 2, sy - 26, tw + 24, 18)
        bg = pygame.Surface(pill.size, pygame.SRCALPHA)
        bg.fill((44, 36, 16, 225))
        self.screen.blit(bg, pill)
        pygame.draw.rect(self.screen, col, pill, 1, border_radius=4)
        self._draw_icon(self._SOCKET_ICON.get(conn, "hand"),
                        pygame.Rect(pill.x + 3, pill.y + 1, 16, 16), col)
        self.text(lbl, (pill.x + 21, pill.y + 3), TEXT, font=self.font_s)

    def _draw_bones(self, ghost=False):
        pose = self.pose_for()
        for idx, b in enumerate(self.project.bones):
            # los sockets se muestran como PUNTOS (en _draw_socket_overlay), no
            # como huesos: asi la cara no se llena de triangulos.
            if getattr(b, "anchor", False) and b.name in model.SOCKETS:
                continue
            head, tip = self._bone_endpoints_screen(idx, pose)
            sel = (not ghost and self.sel_kind == "bone" and self.sel_idx == idx)
            self._draw_one_bone(head, tip, sel,
                                hover=(not ghost and idx == self._hover_node),
                                ghost=ghost)

    def _draw_one_bone(self, head, tip, sel, hover=False, ghost=False):
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
        a_fill, a_line = (26, 70) if ghost else (90, 220)
        body = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
        pygame.draw.polygon(body, (*col, a_fill), poly)
        pygame.draw.polygon(body, (*col, a_line), poly, 1)
        if ghost:                        # huesos tenues durante la reproduccion
            pygame.draw.circle(body, (*col, a_line), (int(hx), int(hy)),
                               int(r) + 1, 2)
            pygame.draw.circle(body, (*col, a_line), (int(tx), int(ty)), 3)
            self.screen.blit(body, (0, 0))
            return
        self.screen.blit(body, (0, 0))
        # halo de hover en el NODO: muestra el area de agarre y que es movible
        if hover:
            halo = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
            pygame.draw.circle(halo, (*SELECT, 55), (int(hx), int(hy)),
                               self.NODE_HIT_R)
            pygame.draw.circle(halo, (*SELECT, 200), (int(hx), int(hy)),
                               self.NODE_HIT_R, 2)
            self.screen.blit(halo, (0, 0))
        pygame.draw.circle(self.screen, col, (int(hx), int(hy)),
                           int(r) + 1, 2)
        pygame.draw.circle(self.screen, (20, 20, 24), (int(hx), int(hy)), 2)
        pygame.draw.circle(self.screen, col, (int(tx), int(ty)), 3)

    PAINT_TOOLS = [("pencil", "P"), ("eraser", "E"), ("shade", "C"),
                   ("bucket", "B"), ("eyedropper", "O"), ("move", "M"),
                   ("scale", "K"), ("select", "S"), ("wand", "W"),
                   ("line", "L"), ("curve", "J"), ("hand", "H")]

    def _draw_toolbar(self):
        c = self.r_canvas
        if self.mode == "paint":
            tools = self.PAINT_TOOLS
            bar = pygame.Rect(c.x + 6, c.y + 30, 40, 8 + len(tools) * 38)
            pygame.draw.rect(self.screen, PANEL, bar, border_radius=6)
            pygame.draw.rect(self.screen, LINE, bar, 1, border_radius=6)
            for i, (t, letter) in enumerate(tools):
                r = pygame.Rect(bar.x + 4, bar.y + 4 + i * 38, 32, 32)
                self._paint_tool_btn(r, t, letter)
            return
        tools = ["select", "bone", "link", "scale", "move", "hand"]
        if self.project.kind == "ropa":   # ropa usa el rig del body: sin hueso
            tools = ["select", "link", "scale", "move", "hand"]
        bar = pygame.Rect(c.x + 6, c.y + 30, 40, 8 + len(tools) * 40)
        pygame.draw.rect(self.screen, PANEL, bar, border_radius=6)
        pygame.draw.rect(self.screen, LINE, bar, 1, border_radius=6)
        for i, t in enumerate(tools):
            self._tool_btn(pygame.Rect(bar.x + 4, bar.y + 4 + i * 40, 32, 32), t)

    def _paint_tool_btn(self, rect, tool, letter):
        active = self.ptool == tool
        hot = rect.collidepoint(self.mouse)
        col = ACTIVE if active else (HOVER if hot else PANEL2)
        pygame.draw.rect(self.screen, col, rect, border_radius=4)
        pygame.draw.rect(self.screen, LINE, rect, 1, border_radius=4)
        self._draw_icon(tool, rect, TEXT)
        # etiqueta de tecla, chiquita en la esquina
        self.text(letter, (rect.right - 7, rect.bottom - 9), DIM, font=self.font_s,
                  center=True)
        if self.lmb_down and hot:
            self.ptool = tool
            self.line_anchor = None

    def _icon_button(self, rect, name, label="", active=False, enabled=True):
        hot = rect.collidepoint(self.mouse) and enabled
        col = ACTIVE if active else (HOVER if hot else PANEL2)
        pygame.draw.rect(self.screen, col, rect, border_radius=4)
        pygame.draw.rect(self.screen, LINE, rect, 1, border_radius=4)
        ico = pygame.Rect(rect.x, rect.y, rect.h, rect.h)
        self._draw_icon(name, ico, TEXT if enabled else DIM)
        if label:
            self.text(label, (rect.x + rect.h + 2, rect.centery - 7),
                      TEXT if enabled else DIM, font=self.font_s)
        return enabled and self.lmb_down and hot

    def _draw_icon(self, name, rect, col):
        """Dibuja un icono vectorial centrado en rect (diseno sobre rejilla 32)."""
        cx, cy = rect.center
        u = min(rect.w, rect.h) / 32.0

        def P(dx, dy):
            return (cx + dx * u, cy + dy * u)

        def line(a, b, w=2):
            pygame.draw.line(self.screen, col, P(*a), P(*b), max(1, int(w * u + 0.5)))

        def poly(pts, width=0):
            pygame.draw.polygon(self.screen, col, [P(*p) for p in pts], width)

        def circ(c, r, w=0):
            pygame.draw.circle(self.screen, col, (int(P(*c)[0]), int(P(*c)[1])),
                               max(1, int(r * u)), w)

        if name == "pencil":
            poly([(-9, 9), (-4, 9), (8, -3), (3, -8), (-9, -4)], 1)
            line((-9, 9), (-9, -4)); line((-9, 9), (-4, 9))
            line((3, -8), (8, -3)); line((-6, 6), (6, -6), 1)
        elif name == "eraser":
            poly([(-9, 5), (1, -5), (9, 3), (-1, 13)], 1)
            line((-9, 5), (-9, 9)); line((-1, 13), (9, 9)); line((9, 3), (9, 9))
            line((-1, 1), (5, 7), 1)
        elif name == "shade":
            circ((0, 0), 10, 1)
            poly([(0, -10), (7, -7), (10, 0), (7, 7), (0, 10)])  # mitad sombreada
        elif name == "bucket":
            poly([(-8, -2), (2, -10), (9, -1), (-1, 7)], 1)
            line((2, -10), (5, -13)); circ((5, -13), 2, 1)
            poly([(9, 0), (12, 6), (6, 6)])               # gota
        elif name == "eyedropper":
            line((-8, 9), (4, -3), 2); circ((6, -6), 3, 1)
            line((4, -3), (9, -8), 3); poly([(-8, 9), (-10, 11), (-6, 7)])
        elif name == "wand":
            line((-8, 9), (6, -5), 2)
            for sx, sy in ((7, -9), (10, -4), (4, -11)):
                line((sx - 2, sy), (sx + 2, sy), 1); line((sx, sy - 2), (sx, sy + 2), 1)
        elif name == "move":            # cruceta (4 flechas)
            line((0, -8), (0, 8), 2)
            line((-8, 0), (8, 0), 2)
            poly([(0, -10), (4, -6), (-4, -6)])
            poly([(0, 10), (4, 6), (-4, 6)])
            poly([(-10, 0), (-6, -4), (-6, 4)])
            poly([(10, 0), (6, -4), (6, 4)])
        elif name == "scale":           # redimensionar (flecha diagonal doble)
            line((-7, 7), (7, -7), 2)
            poly([(8, -8), (2, -7), (7, -2)])     # punta arriba-derecha
            poly([(-8, 8), (-2, 7), (-7, 2)])     # punta abajo-izquierda
        elif name == "select":          # marquesina (rectangulo punteado)
            r = pygame.Rect(*P(-9, -7), 18 * u, 14 * u)
            d = max(2, int(3 * u))
            xx = r.left
            while xx < r.right:
                pygame.draw.line(self.screen, col, (xx, r.top),
                                 (min(xx + d, r.right), r.top))
                pygame.draw.line(self.screen, col, (xx, r.bottom),
                                 (min(xx + d, r.right), r.bottom))
                xx += d * 2
            yy = r.top
            while yy < r.bottom:
                pygame.draw.line(self.screen, col, (r.left, yy),
                                 (r.left, min(yy + d, r.bottom)))
                pygame.draw.line(self.screen, col, (r.right, yy),
                                 (r.right, min(yy + d, r.bottom)))
                yy += d * 2
        elif name == "line":
            line((-9, 9), (9, -9), 2); circ((-9, 9), 2); circ((9, -9), 2)
        elif name == "curve":
            pts = [(-10, 8), (-4, -10), (4, 10), (10, -8)]
            sp = paint.bspline_points(pts, 8)
            if len(sp) >= 2:
                pygame.draw.lines(self.screen, col, False,
                                  [P(*p) for p in sp], max(1, int(2 * u + 0.5)))
        elif name == "hand":
            poly([(-7, 2), (-7, 8), (6, 10), (8, 0), (8, -6), (6, -6),
                  (6, -2), (4, -10), (2, -10), (3, -2), (1, -11), (-1, -11),
                  (0, -1), (-3, -8), (-5, -7), (-2, 2)], 1)
        elif name in ("eye", "eye_off"):
            poly([(-10, 0), (-4, -5), (4, -5), (10, 0), (4, 5), (-4, 5)], 1)
            circ((0, 0), 3)
            if name == "eye_off":
                line((-10, -8), (10, 8), 1)
        elif name == "layer_add":
            pygame.draw.rect(self.screen, col,
                             pygame.Rect(*P(-9, -10), 13 * u, 18 * u), 1)
            line((4, -5), (4, 7), 2); line((-2, 1), (10, 1), 2)   # +
        elif name == "duplicate":
            pygame.draw.rect(self.screen, col,
                             pygame.Rect(*P(-10, -8), 12 * u, 14 * u), 1)
            pygame.draw.rect(self.screen, col,
                             pygame.Rect(*P(-2, -2), 12 * u, 14 * u), 1)
        elif name == "trash":
            line((-7, -6), (7, -6), 2); line((-5, -6), (-4, 9), 1)
            line((5, -6), (4, 9), 1); line((-4, 9), (4, 9), 1)
            line((-3, -6), (-2, -9), 1); line((3, -6), (2, -9), 1)
            line((-2, -9), (2, -9), 1)
        elif name == "up":
            poly([(0, -7), (7, 4), (-7, 4)], 1)
        elif name == "down":
            poly([(0, 7), (7, -4), (-7, -4)], 1)
        elif name == "capture":
            pygame.draw.rect(self.screen, col,
                             pygame.Rect(*P(-11, -5), 22 * u, 14 * u), 1)
            line((-6, -5), (-3, -8)); line((-3, -8), (3, -8)); line((3, -8), (6, -5))
            circ((0, 2), 4, 1); circ((7, -2), 1)
        elif name == "prev":
            line((4, -7), (-4, 0), 2); line((-4, 0), (4, 7), 2)
        elif name == "next":
            line((-4, -7), (4, 0), 2); line((4, 0), (-4, 7), 2)
        elif name == "play":
            poly([(-5, -8), (8, 0), (-5, 8)])
        elif name == "stop":
            pygame.draw.rect(self.screen, col, pygame.Rect(*P(-6, -6), 12 * u, 12 * u))
        elif name == "rest":
            poly([(0, -9), (9, -1), (-9, -1)])               # techo
            pygame.draw.rect(self.screen, col,
                             pygame.Rect(*P(-6, -1), 12 * u, 9 * u), 1)
        elif name in ("hand_l", "hand_r"):                   # mano (con flecha)
            sgn = -1 if name == "hand_l" else 1
            pts = [(-7, 2), (-7, 8), (6, 10), (8, 0), (8, -6), (6, -6),
                   (6, -2), (4, -10), (2, -10), (3, -2), (1, -11), (-1, -11),
                   (0, -1), (-3, -8), (-5, -7), (-2, 2)]
            poly([(sgn * dx, dy) for dx, dy in pts], 1)
        elif name == "eyes":                                 # dos ojos
            for ex in (-5, 5):
                poly([(ex - 4, 0), (ex, -3), (ex + 4, 0), (ex, 3)], 1)
                circ((ex, 0), 1.4)
        elif name == "hair":                                 # melena/flequillo
            poly([(-9, 7), (-9, -1), (-5, -7), (0, -9), (5, -7), (9, -1),
                  (9, 7), (6, 2), (3, 7), (0, 2), (-3, 7), (-6, 2)], 1)
        elif name == "nose":                                 # perfil de nariz
            poly([(0, -8), (4, 5), (-2, 5)], 1)
            line((-2, 5), (-4, 7), 1); line((4, 5), (4, 7), 1)
        elif name == "mouth":                                # sonrisa
            for a, b in (((-8, -1), (-4, 4)), ((-4, 4), (4, 4)),
                         ((4, 4), (8, -1))):
                line(a, b, 2)
        elif name == "shirt":                                # camiseta
            poly([(-4, -7), (-9, -3), (-6, 1), (-4, -1), (-4, 9), (4, 9),
                  (4, -1), (6, 1), (9, -3), (4, -7), (2, -4), (-2, -4)], 1)
        elif name == "pants":                                # pantalon
            poly([(-6, -8), (6, -8), (6, 9), (1, 9), (0, -1), (-1, 9),
                  (-6, 9)], 1)
        elif name == "shoes":                                # bota/zapato
            poly([(-9, 7), (-9, 2), (-3, 2), (-1, -2), (-1, -8), (3, -8),
                  (4, 2), (9, 4), (9, 7)], 1)
        elif name == "body":                                 # personaje (cuerpo)
            circ((0, -9), 3.4, 0)                            # cabeza
            line((0, -5), (0, 5), 2)                         # torso
            line((-7, -1), (7, -1), 2)                       # brazos
            line((0, 5), (-5, 12), 2); line((0, 5), (5, 12), 2)  # piernas
        elif name == "box":                                  # caja/paquete
            poly([(-9, -3), (0, -8), (9, -3), (0, 2)], 1)    # tapa (rombo)
            line((-9, -3), (-9, 8)); line((9, -3), (9, 8))
            line((-9, 8), (0, 12)); line((9, 8), (0, 12))
            line((0, 2), (0, 12), 1)                         # arista frontal
        elif name == "page":                                 # documento
            poly([(-7, -11), (3, -11), (7, -7), (7, 11), (-7, 11)], 1)
            line((3, -11), (3, -7)); line((3, -7), (7, -7))  # esquina doblada
            for yy in (-3, 1, 5):
                line((-4, yy), (4, yy), 1)
        elif name == "face":                                 # rostro (caracteristica)
            circ((0, 0), 9, 1)
            circ((-3, -2), 1.3, 0); circ((3, -2), 1.3, 0)    # ojos
            line((-1, 0), (-2, 3), 1)                        # nariz
            line((-3, 5), (3, 5), 1)                         # boca
        elif name == "grid":                                 # tile (rejilla 2x2)
            pygame.draw.rect(self.screen, col,
                             pygame.Rect(*P(-10, -10), 20 * u, 20 * u), 1)
            line((0, -10), (0, 10), 1)
            line((-10, 0), (10, 0), 1)
            poly([(-9, -9), (-1, -9), (-1, -1), (-9, -1)])   # celda pintada

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
        elif tool == "bone":
            pygame.draw.line(self.screen, TEXT, (cx - 6, cy + 6),
                             (cx + 6, cy - 6), 3)
            for ex, ey in ((cx - 6, cy + 6), (cx + 6, cy - 6)):
                pygame.draw.circle(self.screen, TEXT, (ex, ey), 3)
        elif tool == "link":   # dos eslabones de cadena
            pygame.draw.ellipse(self.screen, TEXT,
                                pygame.Rect(cx - 9, cy - 2, 11, 8), 2)
            pygame.draw.ellipse(self.screen, TEXT,
                                pygame.Rect(cx - 2, cy - 6, 11, 8), 2)
        elif tool == "scale":  # recuadro + flecha diagonal de expansion
            pygame.draw.rect(self.screen, TEXT,
                             pygame.Rect(cx - 8, cy - 8, 11, 11), 1)
            pygame.draw.line(self.screen, TEXT, (cx - 2, cy - 2), (cx + 8, cy + 8), 2)
            pygame.draw.polygon(self.screen, TEXT,
                                [(cx + 8, cy + 8), (cx + 8, cy + 2), (cx + 2, cy + 8)])
        elif tool == "move":   # cruceta de 4 flechas
            self._draw_icon("move", rect, TEXT)
        else:                  # hand
            self._draw_icon("hand", rect, TEXT)
        if self.lmb_down and hot:
            self.tool = tool
            self.link_bone = None

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
        x += 6
        proj = (os.path.basename(self.project_root) if self.project_root
                else "(ninguno)")
        plabel = f"Proyecto: {proj}"
        w = self.font_s.size(plabel)[0] + 16
        if self.button(pygame.Rect(x, 5, w, 26), plabel,
                       active=bool(self.project_root)):
            self.set_project()
        x += w + 8
        if self.button(pygame.Rect(x, 5, 124, 26), "+ Importar imagen",
                       active=True):
            self.import_images()
        x += 132
        # Menús desplegables (compactos) para no desbordar la barra.
        for label, fn in [("Exportar ▾", self.open_export_menu),
                          ("Plantillas ▾", self.open_template_picker)]:
            w = self.font_s.size(label)[0] + 16
            if self.button(pygame.Rect(x, 5, w, 26), label):
                fn()
            x += w + 4
        x += 8
        if self.button(pygame.Rect(x, 5, 66, 26), "Deshacer",
                       enabled=self.history.can_undo()):
            self.undo()
        x += 70
        if self.button(pygame.Rect(x, 5, 62, 26), "Rehacer",
                       enabled=self.history.can_redo()):
            self.redo()
        x += 66
        mlabel = "Pintar (Tab)" if self.mode == "animate" else "Animar (Tab)"
        if self.button(pygame.Rect(x, 5, 96, 26), mlabel,
                       active=self.mode == "paint"):
            self.toggle_mode()
        x += 100
        if self.button(pygame.Rect(x, 5, 54, 26), "Ayuda", active=self.show_help):
            self.show_help = not self.show_help

    # -- panel izquierdo: imagenes + huesos ------------------------------
    def _draw_left(self):
        if self.mode == "paint":
            self._draw_left_paint()
            return
        p = self.r_left
        pygame.draw.rect(self.screen, PANEL, p)
        half = p.y + int(p.h * self.left_split)
        pending_delete = None

        # ---- IMAGENES (materiales) ----
        self.text("IMAGENES", (p.x + 10, p.y + 8), ACCENT, font=self.font_b)
        if self.button(pygame.Rect(p.x + 8, p.y + 28, p.w - 16, 24),
                       "+ Importar imagen"):
            self.import_images()
        itop = p.y + 56
        irect = pygame.Rect(p.x, itop, p.w, max(20, half - itop - 4))
        order = sorted(range(len(self.project.sprites)),
                       key=lambda i: (self.project.sprites[i].z, i), reverse=True)
        sc, rows, maxs = self._list_scroll("scroll_img", irect, len(order), 32)
        y = itop
        for idx in order[sc:sc + rows]:
            sp = self.project.sprites[idx]
            sel = (self.sel_kind == "sprite" and self.sel_idx == idx)
            y, dele = self._list_row(
                p, y, sp.name, sel, self._sprite_visible_now(sp),
                lambda i=idx: self._sel("sprite", i),
                lambda i=idx: self._toggle_vis_sprite(i),
                tag="B" if sp.bone else "", thumb=sp.surface,
                edit=("rename_sprite", idx))
            if dele:
                pending_delete = ("sprite", idx)
        self._scrollbar(irect, sc, len(order), rows, maxs)

        # ---- HUESOS ----
        pygame.draw.line(self.screen, LINE, (p.x + 6, half), (p.right - 6, half))
        self.text("HUESOS", (p.x + 10, half + 6), ACCENT, font=self.font_b)
        btop = half + 26
        brect = pygame.Rect(p.x, btop, p.w, max(20, p.bottom - btop - 2))
        nb = len(self.project.bones)
        sc2, rows2, maxs2 = self._list_scroll("scroll_bone", brect, nb, 26)
        y = btop
        for idx in range(sc2, min(nb, sc2 + rows2)):
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
                indent=depth * 10, tag="ancla" if b.anchor else "",
                edit=("rename_bone", idx))
            if dele:
                pending_delete = ("bone", idx)
        self._scrollbar(brect, sc2, nb, rows2, maxs2)

        if pending_delete is not None:
            kind, i = pending_delete
            if kind == "sprite" and i < len(self.project.sprites):
                self.delete_sprite(i)
            elif kind == "bone" and i < len(self.project.bones):
                self.delete_bone(i)

    def _list_row(self, p, y, label, sel, visible, on_sel, on_eye,
                  indent=0, tag="", thumb=None, edit=None):
        """Dibuja una fila con iconos (lapiz/ojo/papelera) y renombrado en linea.
        Devuelve (nuevo_y, borrar_pedido). El borrado se difiere al que llama para
        no mutar la lista durante el dibujo. `edit` = tupla de edicion p.ej.
        ("rename_sprite", idx); con doble clic o el lapiz se renombra ahi mismo."""
        h = 30 if thumb is not None else 24
        row = pygame.Rect(p.x + 8, y, p.w - 16, h)
        col = ACTIVE if sel else (HOVER if row.collidepoint(self.mouse) else PANEL2)
        pygame.draw.rect(self.screen, col, row, border_radius=3)
        tx = row.x + 6 + indent
        if thumb is not None:
            box = pygame.Rect(row.x + 3, row.y + 3, 24, 24)
            pygame.draw.rect(self.screen, (26, 28, 34), box)
            self._blit_thumb(thumb, box.inflate(-2, -2))
            tx = box.right + 4

        # --- botones de la derecha: [lapiz] [ojo] [papelera] ---
        iy = row.y + (h - 18) // 2
        bx = row.right - 22
        xbtn = pygame.Rect(bx, iy, 18, 18)
        delete_requested = self._icon_button(xbtn, "trash")
        consumed = delete_requested
        eye = None
        if on_eye is not None:
            bx -= 21
            eye = pygame.Rect(bx, iy, 18, 18)
            if self._icon_button(eye, "eye" if visible else "eye_off"):
                on_eye(); consumed = True
        pen = None
        if edit is not None:
            bx -= 21
            pen = pygame.Rect(bx, iy, 18, 18)
            if self._icon_button(pen, "pencil"):
                self._begin_row_edit(edit, label); consumed = True

        # --- nombre / campo de edicion en linea ---
        editing_this = (edit is not None and self.editing == edit)
        if editing_this:
            field = pygame.Rect(tx, row.centery - 9, max(20, bx - tx - 6), 18)
            pygame.draw.rect(self.screen, (30, 32, 40), field, border_radius=3)
            pygame.draw.rect(self.screen, ACCENT, field, 1, border_radius=3)
            self._draw_edit_buf(field.x + 4, field.centery - 7)
        else:
            if tag:
                self.text(tag, (bx - 6, row.centery - 7), ACCENT,
                          font=self.font_s, right=True)
            self.text(label, (tx, row.centery - 7),
                      TEXT if visible else DIM, font=self.font_s)

        over_btn = (xbtn.collidepoint(self.mouse)
                    or (eye and eye.collidepoint(self.mouse))
                    or (pen and pen.collidepoint(self.mouse)))
        if (self.lmb_down and row.collidepoint(self.mouse) and not consumed
                and not over_btn and not editing_this):
            now = pygame.time.get_ticks()
            dbl = (edit is not None and self._last_row_click
                   and self._last_row_click[0] == edit
                   and now - self._last_row_click[1] < 350)
            if dbl:                                  # doble clic -> renombrar
                self._begin_row_edit(edit, label)
                self._last_row_click = None
            else:
                on_sel()
                self._last_row_click = (edit, now)
        # hover sobre un material (con miniatura): preview grande del contenido
        if (thumb is not None and row.collidepoint(self.mouse) and not over_btn
                and not self.lmb_held and not editing_this):
            self._preview = (thumb, label, self.r_left.right + 8, row.y)
        return y + h + 2, delete_requested

    def _begin_row_edit(self, edit, label):
        """Empieza a renombrar una fila (confirma cualquier renombrado en curso)."""
        if (self.editing and self.editing != edit
                and isinstance(self.editing[0], str)
                and self.editing[0].startswith("rename_")):
            self._commit_rename()
        self.editing = edit
        self.edit_buf = label

    def _list_scroll(self, attr, rect, count, row_h):
        """Aplica la rueda a una lista cuando el mouse esta encima y devuelve
        (scroll, filas_visibles, scroll_max)."""
        rows = max(1, rect.h // row_h)
        maxs = max(0, count - rows)
        cur = getattr(self, attr)
        if self.wheel and rect.collidepoint(self.mouse):
            cur -= self.wheel
        cur = max(0, min(maxs, cur))
        setattr(self, attr, cur)
        return cur, rows, maxs

    def _scrollbar(self, rect, scroll, count, rows, maxs):
        if maxs <= 0 or count <= 0:
            return
        bar_h = max(16, rect.h * rows // count)
        bar_y = rect.y + (rect.h - bar_h) * scroll // maxs
        pygame.draw.rect(self.screen, PANEL2, (rect.right - 5, bar_y, 3, bar_h),
                         border_radius=2)

    def _sel(self, kind, idx):
        self.sel_kind, self.sel_idx = kind, idx

    def _toggle_vis_sprite(self, idx):
        self.snapshot()
        sp = self.project.sprites[idx]
        if self.cur_frame >= 0:           # ocultar/mostrar SOLO en el frame actual
            fr = self.frames[self.cur_frame]
            if sp.name in fr.hidden:
                fr.hidden.discard(sp.name)
            else:
                fr.hidden.add(sp.name)
            self.status = (f"'{sp.name}' "
                           + ("oculto" if sp.name in fr.hidden else "visible")
                           + f" en el frame {self.cur_frame + 1}.")
        else:                             # en reposo: visibilidad global del material
            sp.visible = not sp.visible
        self._thumbs_dirty = True

    def _sprite_visible_now(self, sp):
        """Visibilidad del material AHORA: en un frame la decide ese frame
        (libre); en reposo, el visible global."""
        if self.cur_frame >= 0:
            return sp.name not in self.frames[self.cur_frame].hidden
        return sp.visible

    # ====================================================================
    # dibujo del modo Pintar
    # ====================================================================
    def _pc_center(self, px, py):
        return self.pc2s(px + 0.5, py + 0.5)

    def _draw_paint_canvas(self):
        c = self.r_canvas
        pygame.draw.rect(self.screen, (30, 32, 38), c)
        self.screen.set_clip(c)
        sp = self.paint_target()
        if sp is None or sp.surface is None:
            self.screen.set_clip(None)
            self.text("Taller vacio. Crea un 'Nuevo dibujo' (panel izquierdo).",
                      c.center, DIM, font=self.font_s, center=True)
            self.text("PINTAR", (c.x + 56, c.y + 8), ACCENT, font=self.font_b)
            return
        w, h = sp.size
        x0, y0 = self.pc2s(0, 0)
        x1, y1 = self.pc2s(w, h)
        rect = pygame.Rect(int(x0), int(y0), max(1, int(x1 - x0)),
                           max(1, int(y1 - y0)))
        self._draw_checker(rect)
        if self.is_item:                  # body de guia (fantasma) detras del dibujo
            ghost = self._ghost_tile_surface()
            if ghost is not None:
                ghost = ghost.copy()
                rp = self.ref_project
                if self.project.kind == "cargable" and rp is not None:
                    ov = self._shirt_overlay()    # camisa de guia, sobre el body
                    if ov is not None:
                        frame, ox, oy = ov
                        ghost.blit(frame, (-rp.box_x - ox, -rp.box_y - oy))
                g = pygame.transform.scale(ghost, rect.size)
                g.fill((255, 255, 255, self._gop(90)), special_flags=pygame.BLEND_RGBA_MULT)
                self.screen.blit(g, rect.topleft)
        self.screen.blit(pygame.transform.scale(sp.surface, rect.size),
                         rect.topleft)
        pygame.draw.rect(self.screen, ACCENT, rect, 1)
        if self.pzoom >= 6:
            self._draw_pixel_grid(rect, w, h)
        if self.paint.sel_mask is not None:
            self._draw_selection_overlay(rect, w, h)
        self._draw_shape_preview()
        self._draw_sel_preview()
        self._draw_brush_cursor()
        self.screen.set_clip(None)

        labels = {"pencil": "Lapiz", "eraser": "Borrador", "shade": "Sombreador",
                  "bucket": "Bote", "eyedropper": "Cuentagotas", "wand": "Vara magica",
                  "line": "Linea", "curve": "Curva", "hand": "Mano"}
        self.text(f"PINTAR — {labels.get(self.ptool, self.ptool)}",
                  (c.x + 56, c.y + 8), ACCENT, font=self.font_b)
        self.text(f"{w}x{h}px  z{self.pzoom:.0f}", (c.right - 10, c.y + 8),
                  TEXT, font=self.font_b, right=True)

    def _draw_checker(self, rect):
        a, b, cs = (60, 62, 70), (48, 50, 58), 8
        self.screen.fill(b, rect)
        for j, yy in enumerate(range(rect.y, rect.bottom, cs)):
            for i, xx in enumerate(range(rect.x, rect.right, cs)):
                if (i + j) % 2 == 0:
                    self.screen.fill(a, pygame.Rect(
                        xx, yy, min(cs, rect.right - xx), min(cs, rect.bottom - yy)))

    def _draw_pixel_grid(self, rect, w, h):
        col = (70, 73, 84)
        for i in range(w + 1):
            x = rect.x + i * rect.w / w
            pygame.draw.line(self.screen, col, (x, rect.y), (x, rect.bottom))
        for j in range(h + 1):
            y = rect.y + j * rect.h / h
            pygame.draw.line(self.screen, col, (rect.x, y), (rect.right, y))

    def _draw_selection_overlay(self, rect, w, h):
        mask = self.paint.sel_mask
        # relleno translucido de los pixeles seleccionados
        try:
            fill = pygame.Surface((w, h), pygame.SRCALPHA)
            mask.to_surface(fill, setcolor=(250, 245, 130, 70),
                            unsetcolor=(0, 0, 0, 0))
            self.screen.blit(pygame.transform.scale(fill, rect.size), rect.topleft)
        except Exception:
            pass
        # contorno (hormigas) animado
        try:
            pts = mask.outline(every=2)
        except Exception:
            pts = []
        if len(pts) >= 2:
            sp = [(rect.x + px * rect.w / w, rect.y + py * rect.h / h)
                  for px, py in pts]
            dash = (pygame.time.get_ticks() // 120) % 2
            col = (250, 245, 130) if dash else (40, 40, 40)
            pygame.draw.lines(self.screen, col, True, sp, 1)

    def _draw_shape_preview(self):
        a = self.line_anchor
        if not a:
            return
        col = self.paint.color[:3]
        if a["tool"] == "line":
            pygame.draw.line(self.screen, col, self._pc_center(*a["p0"]),
                             self._pc_center(*a["p1"]), 1)
            return
        # curva B-spline: nodos fijados + el cursor como nodo tentativo
        pts = list(a["pts"]) + [self._canvas_pixel()]
        sp = paint.bspline_points(pts)
        if len(sp) >= 2:
            pygame.draw.lines(self.screen, col, False,
                              [self._pc_center(*p) for p in sp], 1)
        for i, (px, py) in enumerate(a["pts"]):
            s = self._pc_center(px, py)
            pygame.draw.circle(self.screen, SELECT, (int(s[0]), int(s[1])), 3)
        self.text("clic: nodo | clic der/Enter: cerrar | Esc: cancelar",
                  (self.r_canvas.centerx, self.r_canvas.bottom - 8), DIM,
                  font=self.font_s, center=True)

    def _draw_sel_preview(self):
        d = self.drag
        if not d or not d.get("paint"):
            return
        if d["mode"] == "sel_rect":
            p0, p1 = d["p0"], self._canvas_pixel()
            a = self.pc2s(min(p0[0], p1[0]), min(p0[1], p1[1]))
            b = self.pc2s(max(p0[0], p1[0]) + 1, max(p0[1], p1[1]) + 1)
            pygame.draw.rect(self.screen, SELECT,
                             pygame.Rect(int(a[0]), int(a[1]),
                                         int(b[0] - a[0]), int(b[1] - a[1])), 1)
        elif d["mode"] == "sel_move":
            sp = self.paint_target()
            if sp is None:
                return
            w, h = sp.size
            x0, y0 = self.pc2s(0, 0)
            x1, y1 = self.pc2s(w, h)
            rect = pygame.Rect(int(x0), int(y0), max(1, int(x1 - x0)),
                               max(1, int(y1 - y0)))
            sx, sy = d["start"]
            px, py = self._canvas_pixel()
            pos = self.pc2s(px - sx, py - sy)
            self.screen.blit(pygame.transform.scale(d["float"], rect.size),
                             (int(pos[0]), int(pos[1])))

    def _draw_brush_cursor(self):
        if (not self.r_canvas.collidepoint(self.mouse)
                or self.ptool not in ("pencil", "eraser", "shade", "line", "curve")):
            return
        px, py = self._canvas_pixel()
        r = self.paint.brush // 2
        x0, y0 = self.pc2s(px - r, py - r)
        size = self.pzoom * self.paint.brush
        pygame.draw.rect(self.screen, (255, 255, 255),
                         pygame.Rect(int(x0), int(y0), int(size), int(size)), 1)

    def _blit_thumb(self, surface, rect):
        if surface is None:
            return
        w, h = surface.get_size()
        if not (w and h):
            return
        sc = min(rect.w / w, rect.h / h)
        tw, th = max(1, int(w * sc)), max(1, int(h * sc))
        img = pygame.transform.scale(surface, (tw, th))
        self.screen.blit(img, (rect.x + (rect.w - tw) // 2,
                               rect.y + (rect.h - th) // 2))

    def _draw_left_paint(self):
        p = self.r_left
        pygame.draw.rect(self.screen, PANEL, p)
        split = p.y + int(p.h * self.left_split)
        # ---- DIBUJOS (taller) / FRAMES (tile) ----
        self.text("FRAMES" if self.is_tile else "DIBUJOS",
                  (p.x + 10, p.y + 8), ACCENT, font=self.font_b)
        if self.button(pygame.Rect(p.x + 8, p.y + 28, 78, 24), "+ Nuevo"):
            self.new_drawing()
        if self.is_tile:                     # tile: 1 dibujo = 1 frame de la tira
            if self.button(pygame.Rect(p.x + 90, p.y + 28, p.w - 98, 24),
                           "Exportar tile", active=bool(self.project.drawings)):
                self.export_tile()
        elif self.button(pygame.Rect(p.x + 90, p.y + 28, p.w - 98, 24),
                         "Enviar capas", active=self.paint_target() is not None):
            self.send_drawing_as_material()
        dtop = p.y + 56
        drect = pygame.Rect(p.x, dtop, p.w, max(20, split - dtop - 4))
        nd = len(self.project.drawings)
        if nd == 0:
            self.text("(taller vacio)", (p.x + 12, dtop + 4), DIM, font=self.font_s)
        sc, rows, maxs = self._list_scroll("scroll_draw", drect, nd, 34)
        y = dtop
        pend_draw = None
        for i in range(sc, min(nd, sc + rows)):
            if self._drawing_row(p, y, i, self.project.drawings[i],
                                 i == self.draw_idx):
                pend_draw = i
            y += 34
        self._scrollbar(drect, sc, nd, rows, maxs)
        if pend_draw is not None:
            self.delete_drawing(pend_draw)

        # ---- CAPAS (del dibujo activo) ----
        pygame.draw.line(self.screen, LINE, (p.x + 6, split), (p.right - 6, split))
        self.text("CAPAS", (p.x + 10, split + 6), ACCENT, font=self.font_b)
        if self._icon_button(pygame.Rect(p.right - 70, split + 4, 28, 22),
                             "layer_add"):
            self.layer_add()
        if self._icon_button(pygame.Rect(p.right - 38, split + 4, 28, 22),
                             "duplicate"):
            self.layer_duplicate()
        sp = self.paint_target()
        if sp is None or not sp.layers:
            self.text("(sin dibujo)", (p.x + 12, split + 32), DIM, font=self.font_s)
            return
        act = sp.layers[sp.active_layer]
        self.text("Opac.", (p.x + 10, split + 32), TEXT, font=self.font_s)
        v, ch = self.scrub("lopac", pygame.Rect(p.x + 56, split + 28, p.w - 68, 22),
                           act.opacity * 100, 0.6, "{:.0f}")
        if ch:
            act.opacity = max(0.0, min(1.0, v / 100.0))
            render.flatten_sprite(sp)
            self._thumbs_dirty = True
        ltop = split + 56
        lrect = pygame.Rect(p.x, ltop, p.w, max(20, p.bottom - ltop - 2))
        nl = len(sp.layers)
        sc2, rows2, maxs2 = self._list_scroll("scroll_layer", lrect, nl, 30)
        order = list(range(nl - 1, -1, -1))     # tope (mayor indice) arriba
        y = ltop
        pending = None
        for i in order[sc2:sc2 + rows2]:
            if self._layer_row(p, y, i, sp.layers[i], i == sp.active_layer):
                pending = i
            y += 30
        self._scrollbar(lrect, sc2, nl, rows2, maxs2)
        if pending is not None and nl > 1:
            self.layer_delete(pending)

    def _drawing_row(self, p, y, i, d, sel):
        row = pygame.Rect(p.x + 8, y, p.w - 16, 30)
        col = ACTIVE if sel else (HOVER if row.collidepoint(self.mouse) else PANEL2)
        pygame.draw.rect(self.screen, col, row, border_radius=3)
        thumb = pygame.Rect(row.x + 3, row.y + 3, 24, 24)
        pygame.draw.rect(self.screen, (26, 28, 34), thumb)
        self._blit_thumb(d.surface, thumb.inflate(-2, -2))
        editing = (self.editing and self.editing[0] == "rename_drawing"
                   and self.editing[1] == i)
        if editing:
            self._draw_edit_buf(row.x + 32, row.centery - 7)
        else:
            self.text(d.name, (row.x + 32, row.centery - 7), TEXT, font=self.font_s)
        ren = pygame.Rect(row.right - 44, row.y + 6, 18, 18)
        dele = pygame.Rect(row.right - 22, row.y + 6, 18, 18)
        consumed = False
        if self._icon_button(ren, "pencil"):
            self.draw_select(i); self.rename_drawing(); consumed = True
        del_req = self._icon_button(dele, "trash")
        if (self.lmb_down and row.collidepoint(self.mouse) and not consumed
                and not del_req and not ren.collidepoint(self.mouse)
                and not dele.collidepoint(self.mouse)):
            self.draw_select(i)
        return del_req

    def _layer_row(self, p, y, i, lay, sel):
        row = pygame.Rect(p.x + 8, y, p.w - 16, 28)
        col = ACTIVE if sel else (HOVER if row.collidepoint(self.mouse) else PANEL2)
        pygame.draw.rect(self.screen, col, row, border_radius=3)
        # ojito para mostrar/ocultar
        eye = pygame.Rect(row.x + 4, row.y + 5, 18, 18)
        consumed = False
        if self._icon_button(eye, "eye" if lay.visible else "eye_off"):
            self.layer_toggle(i); consumed = True
        editing = (self.editing and self.editing[0] == "rename_layer"
                   and self.editing[1] == i)
        if editing:
            self._draw_edit_buf(row.x + 28, row.centery - 7)
        else:
            self.text(lay.name, (row.x + 28, row.centery - 7),
                      TEXT if lay.visible else DIM, font=self.font_s)
        dele = pygame.Rect(row.right - 24, row.y + 5, 18, 18)
        up = pygame.Rect(row.right - 46, row.y + 5, 18, 18)
        dn = pygame.Rect(row.right - 68, row.y + 5, 18, 18)
        del_req = self._icon_button(dele, "trash")
        if self._icon_button(up, "up"):
            self.layer_move(i, 1); consumed = True
        if self._icon_button(dn, "down"):
            self.layer_move(i, -1); consumed = True
        consumed = consumed or del_req
        over_btn = any(r.collidepoint(self.mouse) for r in (eye, dele, up, dn))
        if (self.lmb_down and row.collidepoint(self.mouse) and not consumed
                and not over_btn):
            self.layer_select(i)
        # hover (sin arrastrar, fuera de botones): previsualiza el contenido
        if (row.collidepoint(self.mouse) and not over_btn and not self.lmb_held
                and not editing):
            self._preview = (lay.surface, lay.name, self.r_left.right + 8, row.y)
        return del_req

    def _draw_preview(self, surf, label, anchor_x, row_y):
        """Ventana flotante (al lado del panel) con el contenido de una capa o
        material. Se dibuja al final del frame, ENCIMA de todo, y se mantiene
        completa dentro de la pantalla."""
        if surf is None or not all(surf.get_size()):
            return
        w, h = surf.get_size()
        iw, ih = (lambda sc: (max(1, int(w * sc)), max(1, int(h * sc))))(
            min(200.0 / w, 240.0 / h))
        pad = 8
        box = pygame.Rect(anchor_x, 0, iw + pad * 2, ih + pad * 2 + 18)
        # si no cabe a la derecha del panel, ponlo a la IZQUIERDA del mouse
        if box.right > self.screen.get_width() - 4:
            box.x = max(4, self.r_left.right - box.w - 8)
        box.y = max(self.r_top.bottom + 4,
                    min(row_y - 8, self.screen.get_height() - box.h - 4))
        shadow = pygame.Surface(box.inflate(8, 8).size, pygame.SRCALPHA)
        shadow.fill((0, 0, 0, 90))
        self.screen.blit(shadow, box.inflate(8, 8).topleft)
        pygame.draw.rect(self.screen, PANEL, box, border_radius=6)
        pygame.draw.rect(self.screen, ACCENT, box, 1, border_radius=6)
        img_rect = pygame.Rect(box.x + pad, box.y + pad, iw, ih)
        self._draw_checker(img_rect)
        if surf.get_bounding_rect(min_alpha=1).width == 0:
            self.text("(vacio)", img_rect.center, DIM, font=self.font_s,
                      center=True)
        else:
            self.screen.blit(pygame.transform.scale(surf, (iw, ih)),
                             img_rect.topleft)
        self.text(label, (box.x + pad, box.bottom - 16), TEXT, font=self.font_s)

    def _sv_surface(self, w, h):
        key = (round(self.paint.hue, 3), w, h)
        if self._sv_key == key and self._sv_surf is not None:
            return self._sv_surf
        import colorsys
        surf = pygame.Surface((w, h))
        for j in range(h):
            v = 1.0 - j / (h - 1)
            for i in range(w):
                s = i / (w - 1)
                r, g, b = colorsys.hsv_to_rgb(self.paint.hue, s, v)
                surf.set_at((i, j), (int(r * 255), int(g * 255), int(b * 255)))
        self._sv_key, self._sv_surf = key, surf
        return surf

    def _hue_surface(self, w, h):
        if self._hue_surf is not None and self._hue_surf.get_size() == (w, h):
            return self._hue_surf
        import colorsys
        surf = pygame.Surface((w, h))
        for j in range(h):
            r, g, b = colorsys.hsv_to_rgb(j / (h - 1), 1, 1)
            pygame.draw.line(surf, (int(r * 255), int(g * 255), int(b * 255)),
                             (0, j), (w, j))
        self._hue_surf = surf
        return surf

    def _draw_right_paint(self):
        p = self.r_right
        pygame.draw.rect(self.screen, PANEL, p)
        pygame.draw.line(self.screen, LINE, (p.x, p.y), (p.x, p.bottom))
        x, w = p.x + 10, p.w - 20
        self.text("COLOR", (x, p.y + 8), ACCENT, font=self.font_b)
        y = p.y + 30
        # --- picker HSV: cuadro Saturacion/Valor + barra de matiz ---------
        hue_w = 18
        sv = pygame.Rect(x, y, w - hue_w - 6, 92)
        hue = pygame.Rect(sv.right + 6, y, hue_w, 92)
        self.screen.blit(pygame.transform.scale(
            self._sv_surface(72, 46), sv.size), sv.topleft)
        self.screen.blit(pygame.transform.scale(
            self._hue_surface(hue_w, 64), hue.size), hue.topleft)
        pygame.draw.rect(self.screen, LINE, sv, 1)
        pygame.draw.rect(self.screen, LINE, hue, 1)
        # marcadores
        mx = sv.x + self.paint.sat * sv.w
        my = sv.y + (1 - self.paint.val) * sv.h
        pygame.draw.circle(self.screen, (255, 255, 255), (int(mx), int(my)), 4, 1)
        pygame.draw.circle(self.screen, (0, 0, 0), (int(mx), int(my)), 5, 1)
        hy = hue.y + self.paint.hue * hue.h
        pygame.draw.rect(self.screen, TEXT, (hue.x - 1, int(hy) - 1, hue.w + 2, 3), 1)
        if self.lmb_held:
            if sv.collidepoint(self.mouse):
                self.paint.sat = max(0.0, min(1.0, (self.mouse[0] - sv.x) / sv.w))
                self.paint.val = max(0.0, min(1.0, 1 - (self.mouse[1] - sv.y) / sv.h))
                self._set_color_from_hsv()
            elif hue.collidepoint(self.mouse):
                self.paint.hue = max(0.0, min(0.999, (self.mouse[1] - hue.y) / hue.h))
                self._set_color_from_hsv()
        y += 100
        # swatches activo/secundario + Alpha
        sw = pygame.Rect(x, y, 30, 30)
        pygame.draw.rect(self.screen, self.paint.color[:3], sw, border_radius=4)
        pygame.draw.rect(self.screen, LINE, sw, 1, border_radius=4)
        sw2 = pygame.Rect(x + 34, y + 8, 22, 22)
        pygame.draw.rect(self.screen, self.paint.color2[:3], sw2, border_radius=3)
        pygame.draw.rect(self.screen, LINE, sw2, 1, border_radius=3)
        if self.lmb_down and sw2.collidepoint(self.mouse):
            self.paint.color, self.paint.color2 = self.paint.color2, self.paint.color
            self._sync_hsv_from_color()
        self.text("Alpha", (x + 64, y - 1), DIM, font=self.font_s)
        v, ch = self.scrub("colA", pygame.Rect(x + 64, y + 12, w - 64, 18),
                           self.paint.color[3], 0.6, "{:.0f}")
        if ch:
            cc = list(self.paint.color)
            cc[3] = max(0, min(255, int(round(v))))
            self.paint.color = tuple(cc)
        y += 38
        self.text("PALETA", (x, y), ACCENT, font=self.font_s)
        if self.button(pygame.Rect(p.right - 78, y - 2, 68, 18), "+ color"):
            if tuple(self.paint.color) not in self.paint.palette:
                self.paint.palette.append(tuple(self.paint.color))
        y += 20
        perrow = max(1, w // 19)
        for idx, colr in enumerate(self.paint.palette):
            r = pygame.Rect(x + (idx % perrow) * 19, y + (idx // perrow) * 19, 16, 16)
            pygame.draw.rect(self.screen, colr[:3], r)
            if tuple(colr) == tuple(self.paint.color):
                pygame.draw.rect(self.screen, SELECT, r, 2)
            else:
                pygame.draw.rect(self.screen, LINE, r, 1)
            if self.lmb_down and r.collidepoint(self.mouse):
                self._pick_color(colr)
        rows = (len(self.paint.palette) + perrow - 1) // perrow
        y += rows * 19 + 8
        self.text("Pincel", (x + 4, y + 4), TEXT, font=self.font_s)
        v, ch = self.scrub("brush", pygame.Rect(x + 84, y, w - 84, 22),
                           self.paint.brush, 0.2, "{:.0f}")
        if ch:
            self.paint.brush = max(1, min(64, int(round(v))))
        self.text("Ctrl+rueda", (x + 4, y + 16), DIM, font=self.font_s)
        y += 30
        self.text("Toleranc.", (x + 4, y + 4), TEXT, font=self.font_s)
        v, ch = self.scrub("tol", pygame.Rect(x + 84, y, w - 84, 22),
                           self.paint.tolerance, 0.6, "{:.0f}")
        if ch:
            self.paint.tolerance = max(0, min(255, int(round(v))))
        y += 28
        self.text("Sombra", (x + 4, y + 4), TEXT, font=self.font_s)
        if self.button(pygame.Rect(x + 84, y, w - 84, 22),
                       "Brillo (aclarar)" if self.paint.shade_lighten
                       else "Sombra (oscurecer)"):
            self.paint.shade_lighten = not self.paint.shade_lighten
        y += 26
        self.text("Fuerza", (x + 4, y + 4), TEXT, font=self.font_s)
        v, ch = self.scrub("shamt", pygame.Rect(x + 84, y, w - 84, 22),
                           self.paint.shade_amount * 100, 0.5, "{:.0f}")
        if ch:
            self.paint.shade_amount = max(0.01, min(1.0, v / 100.0))
        y += 30
        pygame.draw.line(self.screen, LINE, (p.x + 6, y), (p.right - 6, y))
        y += 8
        self.text("LIENZO", (x, y), ACCENT, font=self.font_s)
        y += 18
        d = self.paint_target()
        tw, th = self.project.tile_w, self.project.tile_h
        if d and d.size:
            same = (d.size == (tw, th))
            self.text(f"Tamaño actual: {d.size[0]}x{d.size[1]}"
                      + ("  (= tile)" if same else ""), (x + 2, y), DIM,
                      font=self.font_s)
            y += 18
            if self.button(pygame.Rect(x, y, w, 24),
                           f"Redimensionar al tile ({tw}x{th})", enabled=not same):
                self.resize_active_drawing(tw, th)
            y += 28
        else:
            self.text("Crea un 'Nuevo dibujo' (sale al tamaño del tile).",
                      (x + 2, y), DIM, font=self.font_s)
            y += 22
        pygame.draw.line(self.screen, LINE, (p.x + 6, y), (p.right - 6, y))
        y += 8
        self.text("GUARDAR IMAGEN", (x, y), ACCENT, font=self.font_s)
        y += 20
        if self.button(pygame.Rect(x, y, w, 24), "Aplanar -> asset base"):
            self.flatten_to_base()
        y += 28
        if self.button(pygame.Rect(x, y, w, 24), "Aplanar -> PNG nuevo"):
            self.flatten_to_new()
        y += 28
        if self.button(pygame.Rect(x, y, w, 24), "Quitar seleccion (Esc)",
                       enabled=self.paint.sel_mask is not None):
            self.paint.sel_mask = None

    # -- panel derecho: propiedades --------------------------------------
    def _draw_right(self):
        if self.mode == "paint":
            self._draw_right_paint()
            return
        p = self.r_right
        pygame.draw.rect(self.screen, PANEL, p)
        pygame.draw.line(self.screen, LINE, (p.x, p.y), (p.x, p.bottom))
        x = p.x + 10
        w = p.w - 20

        # scroll del panel (rueda cuando el raton esta encima)
        content_h = getattr(self, "_right_content_h", 0)
        max_scroll = max(0, content_h - (p.h - 14))
        if self.wheel and p.collidepoint(self.mouse):
            self._right_scroll -= self.wheel * 40
            self.wheel = 0
        self._right_scroll = max(0, min(self._right_scroll, max_scroll))

        self.screen.set_clip(p)
        y0 = p.y + 8 - self._right_scroll
        y = y0

        open_, y = self._fold_header(x, w, y, p, "props", "PROPIEDADES")
        if open_:
            if self.sel_kind == "sprite" and self.selected_sprite():
                y = self._props_sprite(x, w, y, p)
            elif self.sel_kind == "bone" and self.selected_bone():
                y = self._props_bone(x, w, y, p)
            else:
                self.text("(nada seleccionado)", (x, y), DIM, font=self.font_s)
                y += 26
        y = self._divider(p, y)

        open2, y = self._fold_header(x, w, y, p, "sockets", "CONEXIONES")
        if open2:
            y = self._draw_sockets(x, w, y, p)
        y = self._divider(p, y)

        openA, y = self._fold_header(x, w, y, p, "assign", "PLANTILLA — asignar")
        if openA:
            y = self._draw_assign(x, w, y, p)
        y = self._divider(p, y)

        open3, y = self._fold_header(x, w, y, p, "tile", "TILE / PROYECTO")
        if open3:
            if self.is_item:
                self.text("Lienzo BLOQUEADO al body de referencia:", (x, y), DIM,
                          font=self.font_s)
                y += 18
                self.text(f"Ancho {self.project.tile_w}  ·  Alto "
                          f"{self.project.tile_h}", (x + 4, y), TEXT,
                          font=self.font_s)
                y += 22
                if self.project.kind == "caracteristica":
                    for ln in ("Se exporta RECORTADA al contenido (minimo",
                               "tamano) + conexion: el juego la coloca por",
                               "su socket frame a frame."):
                        self.text(ln, (x, y), DIM, font=self.font_s)
                        y += 15
                    y += 6
            else:
                self.text("Tamaño del lienzo (clic y escribe):", (x, y), DIM,
                          font=self.font_s)
                y += 18
                for key, lbl in (("tile_w", "Tile ancho"), ("tile_h", "Tile alto"),
                                 ("box_x", "Caja X"), ("box_y", "Caja Y")):
                    self._num_field(x, w, y, key, lbl, getattr(self.project, key))
                    y += 26
                if self.project.kind == "body":
                    self.text("Profundidad de la ropa (0 = off):", (x, y), DIM,
                              font=self.font_s)
                    y += 16
                    self.text("partes con z MAYOR van DELANTE de la ropa",
                              (x, y), DIM, font=self.font_s)
                    y += 16
                    self._num_field(x, w, y, "clothes_z", "Z ropa",
                                    self.project.clothes_z or 0)
                    y += 26

        self._right_content_h = y - y0 + 8
        self.screen.set_clip(None)

        # barra de scroll
        if max_scroll > 0 and content_h > 0:
            track_h = p.h - 8
            kh = max(24, int(track_h * (p.h - 14) / content_h))
            ky = p.y + 4 + int((track_h - kh) * (self._right_scroll / max_scroll))
            pygame.draw.rect(self.screen, PANEL2,
                             pygame.Rect(p.right - 7, p.y + 4, 4, track_h),
                             border_radius=2)
            pygame.draw.rect(self.screen, ACCENT,
                             pygame.Rect(p.right - 7, ky, 4, kh), border_radius=2)

    def _fold_header(self, x, w, y, p, key, title):
        """Cabecera plegable (click = recoger/desplegar). Devuelve (abierto, y)."""
        folded = self._fold.get(key, False)
        hdr = pygame.Rect(p.x + 4, y - 2, p.w - 14, 19)
        hot = hdr.collidepoint(self.mouse)
        pygame.draw.rect(self.screen, HOVER if hot else PANEL2, hdr, border_radius=3)
        cx, cy = x + 4, y + 7
        if folded:
            pts = [(cx - 2, cy - 4), (cx + 4, cy), (cx - 2, cy + 4)]
        else:
            pts = [(cx - 4, cy - 2), (cx + 4, cy - 2), (cx, cy + 4)]
        pygame.draw.polygon(self.screen, ACCENT, pts)
        self.text(title, (x + 16, y), ACCENT, font=self.font_b)
        if self.lmb_down and hot:
            self._fold[key] = not folded
            self.lmb_down = False           # no atravesar al contenido
        return (not self._fold.get(key, False)), y + 22

    def _divider(self, p, y):
        pygame.draw.line(self.screen, LINE, (p.x + 6, y), (p.right - 10, y))
        return y + 8

    def _name_header(self, x, w, y, p, kind, idx, name):
        editing = (self.editing is not None and self.editing[1] == idx
                   and self.editing[0] == ("rename_" + kind))
        if editing:
            box = pygame.Rect(x, y - 2, w, 22)
            pygame.draw.rect(self.screen, (24, 26, 32), box, border_radius=3)
            pygame.draw.rect(self.screen, ACCENT, box, 1, border_radius=3)
            self._draw_edit_buf(x + 5, y + 2)
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
        # conexion (socket): este material se PEGA por su centro a ese punto del
        # cuerpo -> el juego lo ubica solo, sin importar su tamano.
        self.text("Conexion (pegar a)", (x, y + 4), DIM, font=self.font_s)
        if self.button(pygame.Rect(x + 120, y, 22, 22), "<"):
            self.cycle_connection(idx, -1)
        cname = model.SOCKET_LABELS.get(sp.connection, "(ninguna)")
        self.text(cname, (x + 4, y + 26),
                  ACCENT if sp.connection else DIM, font=self.font_s)
        if self.button(pygame.Rect(p.right - 32, y, 22, 22), ">"):
            self.cycle_connection(idx, 1)
        y += 44
        if sp.connection:
            self.text("Su centro se pega al punto del cuerpo.",
                      (x + 4, y), DIM, font=self.font_s)
            y += 16
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
        y += 28
        if self.button(pygame.Rect(x, y, w, 22), "Editar en Pintar (copia)"):
            self.edit_material_in_paint(idx)
        y += 30
        if self.button(pygame.Rect(x, y, w, 24), "Borrar imagen (Supr)"):
            self.delete_sprite(idx)
        return y + 32

    def _set_sprite(self, sp, which, key, v):
        getattr(sp, which)[key] = v
        self.dirty = True
        self._thumbs_dirty = True

    # icono por socket (vectorial, ver _draw_icon)
    _SOCKET_ICON = {
        "mano_izq": "hand_l", "mano_der": "hand_r", "ojos": "eyes",
        "pelo": "hair", "nariz": "nose", "boca": "mouth",
        "pierna_izq": "pants", "pierna_der": "pants",
        "zapato_izq": "shoes", "zapato_der": "shoes",
    }

    def _draw_sockets(self, x, w, y, p):
        """Botones de PUNTOS DE CONEXION (cuerpo). Crean/seleccionan un anchor con
        nombre reservado (ojos, pelo, mano...) que sigue el rig por frame; los
        materiales se pegan por su centro a esos puntos en el juego."""
        self.text("Piezas que el juego pega por su centro", (x, y), DIM,
                  font=self.font_s)
        y += 16
        self.text("(ropa que se deforma: 'Sigue al hueso')", (x, y), DIM,
                  font=self.font_s)
        y += 18
        existing = {b.name for b in self.project.bones
                    if getattr(b, "anchor", False)}
        bw = (w - 6) // 2
        bh = 28
        for i, sid in enumerate(model.SOCKETS):
            col = i % 2
            row = i // 2
            r = pygame.Rect(x + col * (bw + 6), y + row * (bh + 4), bw, bh)
            has = sid in existing
            lbl = model.SOCKET_LABELS.get(sid, sid)
            if self._socket_button(r, self._SOCKET_ICON.get(sid, "hand"),
                                   lbl, active=has):
                self.create_socket(sid)
        rows = (len(model.SOCKETS) + 1) // 2
        y += rows * (bh + 4) + 4
        self.text("Verde = colocado. Click crea/selecciona.",
                  (x + 2, y), DIM, font=self.font_s)
        y += 20
        if self.button(pygame.Rect(x, y, w, 24),
                       "Sincronizar con otros bodies…"):
            self._open_syncbodies()
        return y + 30

    def _draw_assign(self, x, w, y, p):
        """Asistente: vincula tu arte a los huesos de la plantilla. Cada sprite es
        una fila; al seleccionarlo usa 'Sigue al hueso' (arriba) para elegir hueso."""
        self.text("Vincula tu arte al rig de la plantilla", (x, y), DIM,
                  font=self.font_s)
        y += 18
        if not self.project.bones:
            self.text("Carga una plantilla (toolbar).", (x, y), SELECT,
                      font=self.font_s)
            return y + 18
        if self.button(pygame.Rect(x, y, w, 24), "Auto por cercania (todos)"):
            self.auto_assign_bones()
        y += 28
        if self.button(pygame.Rect(x, y, w, 22),
                       "Generar anims borrador (opcional)"):
            self.generate_draft_anims()
        y += 24
        self.text("agacharse/sentado/atacar/cortar (aproximadas)",
                  (x + 2, y), DIM, font=self.font_s)
        y += 18
        if not self.project.sprites:
            self.text("Importa tu dibujo para asignarlo.", (x, y), DIM,
                      font=self.font_s)
            return y + 18
        for i, sp in enumerate(self.project.sprites):
            r = pygame.Rect(x, y, w, 22)
            sel = (self.sel_kind == "sprite" and self.sel_idx == i)
            ok = bool(sp.bone)
            hot = r.collidepoint(self.mouse)
            col = ACTIVE if sel else (HOVER if hot else PANEL2)
            pygame.draw.rect(self.screen, col, r, border_radius=3)
            pygame.draw.rect(self.screen, (120, 210, 150) if ok else LINE, r, 1,
                             border_radius=3)
            nm = sp.name if len(sp.name) <= 16 else sp.name[:15] + "…"
            self.text(nm, (r.x + 6, r.y + 4), TEXT, font=self.font_s)
            self.text(sp.bone or "— sin hueso", (r.right - 6, r.centery),
                      (150, 220, 170) if ok else SELECT, font=self.font_s,
                      right=True)
            if self.lmb_down and hot:
                self.sel_kind, self.sel_idx = "sprite", i
            y += 24
        self.text("Selecciona un sprite y usa 'Sigue al hueso' arriba.",
                  (x + 2, y), DIM, font=self.font_s)
        return y + 16

    def _socket_button(self, rect, icon, label, active=False):
        """Boton con icono grande + etiqueta; resalta en verde si ya existe."""
        hot = rect.collidepoint(self.mouse)
        if active:
            col, ring = (46, 92, 64), (120, 210, 150)
        else:
            col, ring = (HOVER if hot else PANEL2), LINE
        pygame.draw.rect(self.screen, col, rect, border_radius=5)
        pygame.draw.rect(self.screen, ring, rect, 1, border_radius=5)
        ico = pygame.Rect(rect.x + 3, rect.y + 3, rect.h - 6, rect.h - 6)
        self._draw_icon(icon, ico, (170, 230, 190) if active else SELECT)
        self.text(label, (rect.x + rect.h + 1, rect.centery - 7),
                  TEXT, font=self.font_s)
        return self.lmb_down and hot

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
        # anclaje de items (la mano, etc.): se exporta su transform por frame
        self.text("Anclaje item", (x + 4, y + 4), TEXT, font=self.font_s)
        if self.button(pygame.Rect(x + 90, y, w - 90, 22),
                       "SI - exporta anchor" if b.anchor else "no",
                       active=b.anchor):
            self.snapshot(); b.anchor = not b.anchor; self.dirty = True
        y += 22
        if b.anchor:
            self.text("El item seguira este hueso (pos/rot) por frame.",
                      (x + 4, y), DIM, font=self.font_s)
            y += 16
        y += 6
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
        th = getattr(self, "_thumb_h", 70)
        box = render.clip_box(self.project, self.clip) if self.clip else None
        for f in self.frames:
            tile = render.render_tile(self.project, f, box=box)
            tw, hh = tile.get_size()
            sc = th / hh if hh else 1
            self._thumbs.append(pygame.transform.smoothscale(
                tile, (max(1, int(tw * sc)), th)))
        self._thumbs_dirty = False

    def _draw_clip_tabs(self, p):
        """Pestanas de animaciones (cada una = una fila de la hoja)."""
        tx, ty = 8, p.y + 4
        for i, c in enumerate(self.project.clips):
            editing = (self.editing and self.editing[0] == "rename_clip"
                       and self.editing[1] == i)
            txt = self.edit_buf if editing else f"{c.name} ({len(c.frames)})"
            wtab = self.font_s.size(txt)[0] + 16
            tab = pygame.Rect(tx, ty, wtab, 20)
            active = (i == self.cur_clip)
            col = ACTIVE if active else (HOVER if tab.collidepoint(self.mouse)
                                         else PANEL2)
            pygame.draw.rect(self.screen, col, tab, border_radius=3)
            if editing:
                self._draw_edit_buf(tab.x + 6, tab.centery - 7)
            else:
                self.text(txt, (tab.x + 6, tab.centery - 7),
                          TEXT if active else DIM, font=self.font_s)
            if self.lmb_down and tab.collidepoint(self.mouse):
                self.rename_clip() if active else self.select_clip(i)
            tx += wtab + 4
        if self.button(pygame.Rect(tx, ty, 26, 20), "+"):
            self.add_clip()
        tx += 30
        # duplicar la animacion activa (copia entera -> variante)
        if self.clip and self._icon_button(pygame.Rect(tx, ty, 24, 20), "duplicate"):
            self.duplicate_clip()
        tx += 28
        if self._icon_button(pygame.Rect(tx, ty, 24, 20), "trash"):
            self.delete_clip(self.cur_clip)         # borrar incluso la ultima
        tx += 28
        if self.project.kind == "cargable":         # ver el cargable sobre el body
            if self.button(pygame.Rect(tx, ty, 110, 20), "Preview en body"):
                self.modal = ("cargpreview", None)
            tx += 116
            # camisa de guia: cicla (ninguna -> cada camisa exportada) para
            # alinear las correas con/sin camisa puesta.
            if self.button(pygame.Rect(tx, ty, 150, 20), self._shirt_label()):
                self._cycle_shirt()
            tx += 156
        # tamano de frame de ESTA animacion (atacar puede necesitar mas ancho)
        if self.clip:
            self.text("Frame", (tx, ty + 4), DIM, font=self.font_s)
            tx += 42
            _, _, cw, ch = render.clip_box(self.project, self.clip)
            v, chg = self.scrub("clipw", pygame.Rect(tx, ty, 44, 20), cw, 0.25, "{:.0f}")
            if chg:
                self.clip.tile_w = max(8, int(round(v))); self._thumbs_dirty = True
            tx += 46
            self.text("x", (tx, ty + 4), DIM, font=self.font_s)
            tx += 10
            v, chg = self.scrub("cliph", pygame.Rect(tx, ty, 44, 20), ch, 0.25, "{:.0f}")
            if chg:
                self.clip.tile_h = max(8, int(round(v))); self._thumbs_dirty = True
            tx += 48
            if self.button(pygame.Rect(tx, ty, 58, 20), "Ajustar"):
                self.fit_clip_to_content()
            tx += 62
        self.text("(Ajustar = recuadro que contiene todos los frames)",
                  (p.right - 8, ty + 4), DIM, font=self.font_s, right=True)

    def _draw_timeline(self):
        p = self.r_time
        pygame.draw.rect(self.screen, PANEL, p)
        pygame.draw.line(self.screen, LINE, (0, p.y), (p.right, p.y))
        self._draw_clip_tabs(p)
        x, y = 8, p.y + 28
        canf = self.cur_frame >= 0
        if self._icon_button(pygame.Rect(x, y, 54, 24), "capture", "K"):
            self.capture_frame()
        x += 58
        if self._icon_button(pygame.Rect(x, y, 28, 24), "duplicate", enabled=canf):
            self.duplicate_frame(self.cur_frame)
        x += 32
        if self._icon_button(pygame.Rect(x, y, 28, 24), "trash", enabled=canf):
            self.delete_frame(self.cur_frame)
        x += 32
        if self._icon_button(pygame.Rect(x, y, 26, 24), "prev", enabled=canf):
            self.move_frame(self.cur_frame, -1)
        x += 28
        if self._icon_button(pygame.Rect(x, y, 26, 24), "next", enabled=canf):
            self.move_frame(self.cur_frame, +1)
        x += 32
        if self._icon_button(pygame.Rect(x, y, 60, 24),
                             "stop" if self.playing else "play", "Spc",
                             active=self.playing):
            self.toggle_play()
        x += 64
        if self._icon_button(pygame.Rect(x, y, 40, 24), "rest",
                             active=self.cur_frame < 0):
            self.cur_frame = -1
            self.sync_working()
        x += 46
        # duracion (segundos) de la animacion activa
        if self.clip:
            self.text("Dur(s)", (x, y + 5), DIM, font=self.font_s)
            x += 42
            v, ch = self.scrub("clipdur", pygame.Rect(x, y, 52, 24),
                               self.clip.duration, 0.02, "{:.2f}")
            if ch:
                self.clip.duration = max(0.05, v)
            x += 56
            self.text(f"{self.clip.fps:.0f} fps", (x, y + 5), DIM, font=self.font_s)
            x += 46
        self.text(f"{len(self.frames)} frames  |  {self.status}",
                  (x, y + 5), DIM, font=self.font_s)

        sy = p.y + 56
        self._thumb_h = max(36, p.bottom - sy - 8)
        if self._thumbs_dirty:
            self._rebuild_thumbs()
        sx = 8
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
            "4) ENLACE (C): la forma facil de vincular. Clic en un HUESO y luego",
            "   clic en una IMAGEN; un hilo/cadena muestra la conexion. (Esc cancela)",
            "   Tambien sirve 'Sigue al hueso < >' en PROPIEDADES. La linea del",
            "   sprite seleccionado a su hueso confirma el vinculo.",
            "5) Mueve/rota huesos y pulsa Capturar (K) por frame. Exporta PNG.",
            "6) ESCALAR (E): arrastra horizontal para reescalar; afecta a TODAS las",
            "   animaciones ya hechas. 2 modos (toggle arriba o re-pulsar E):",
            "   ESQUELETO = reescala el rig entero (huesos + arte que cuelga);",
            "   MATERIALES = solo agranda/achica el ARTE, sin tocar los huesos.",
            "7) MOVER (M): arrastra para reubicar TODO el personaje a la vez en",
            "   todas las animaciones (sin descuadrar la altura de los frames).",
            "   Util tras escalar, si la figura se sale del recuadro.",
            "",
            "V seleccion  B hueso  C enlace  E escalar  M mover  H mano  K capturar",
            "Supr borrar   F2 renombrar (material/hueso/animacion)   Rueda zoom",
            "Ctrl+C / Ctrl+V / Ctrl+D: copiar / pegar / duplicar material o hueso.",
            "Animaciones = pestanas del timeline. '+' crea una nueva basada en el",
            "   frame seleccionado (o el 1o); el boton DUPLICAR (al lado) copia la",
            "   animacion activa ENTERA como variante; clic en la activa renombra.",
            "Ctrl+S guardar  Ctrl+Shift+S guardar como  Ctrl+O abrir",
            "Ctrl+E exportar  Ctrl+Z deshacer  Ctrl+Y rehacer",
            "",
            "MODO PINTAR (Tab): un TALLER aparte. Dibujas con CAPAS sin tocar la",
            "animacion; al terminar pulsas 'Enviar -> material' y se copia a",
            "Animacion como un sprite NUEVO (editar el dibujo ya no lo afecta).",
            "P lapiz  E borrador  C sombra/brillo  B bote  O cuentagotas  M mover",
            "L linea  J curva B-spline  S seleccion rectangular  W vara magica  H mano",
            "Mover (M): arrastra para desplazar la capa (o lo seleccionado).",
            "Escalar (K): arrastra horizontal para agrandar/achicar lo dibujado en",
            "   la capa (desde su centro, nitido). Suelta para fijar.",
            "[ ] o Ctrl+rueda = tamano de pincel    X = cambia color activo/2do",
            "Curva: clic agrega nodos; clic derecho o Enter cierra; Esc cancela.",
            "Seleccion (S): arrastra un rectangulo (Shift suma, Ctrl resta); arrastra",
            "   dentro para MOVER el contenido; clic simple o Esc deselecciona.",
            "Vara magica selecciona la region de color (Esc deselecciona).",
            "Ctrl+C/Ctrl+V copia/pega capa (o la seleccion); Ctrl+D duplica.",
            "Para retocar un material existente: en sus Propiedades, 'Editar en Pintar'.",
            "",
            "Recuadro NARANJA = area exportada (tile). Solo se exportan imagenes.",
            "",
            "F1  cerrar ayuda   |   Tab  cambiar modo",
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
