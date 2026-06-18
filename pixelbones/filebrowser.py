"""Explorador de archivos propio (en pygame). Reemplaza a tkinter, que da
problemas de foco/cuelgue al mezclarse con pygame en algunos sistemas Linux.

Es un modal sincrono: FileBrowser(...).run() corre su propio bucle dibujandose
sobre la pantalla y devuelve el resultado (lista de rutas, ruta, carpeta o
None si se cancela). Asi los puntos de llamada siguen siendo sencillos.
"""

from __future__ import annotations
import os
import pygame

BG_DIM   = (0, 0, 0, 170)
PANEL    = (40, 42, 50)
PANEL2   = (54, 57, 68)
HOVER    = (70, 74, 88)
ACTIVE   = (90, 120, 180)
ACCENT   = (240, 190, 90)
TEXT     = (225, 228, 235)
DIM      = (150, 155, 165)
LINE     = (60, 63, 74)
DIRCOL   = (150, 195, 245)
SEL      = (250, 210, 120)

IMG_EXTS = (".png", ".gif", ".bmp", ".jpg", ".jpeg")


class FileBrowser:
    def __init__(self, screen, clock, font, font_s, *, title="Archivos",
                 mode="open", multi=False, exts=None, default_name="",
                 start_dir=None):
        # mode: open | save | dir
        self.screen = screen
        self.clock = clock
        self.font = font
        self.font_s = font_s
        self.title = title
        self.mode = mode
        self.multi = multi
        self.exts = tuple(e.lower() for e in exts) if exts else None
        self.filename = default_name
        # nombre "seleccionado": la primera tecla lo reemplaza (como en cualquier
        # dialogo de guardar). Se apaga al editar o al elegir un archivo.
        self._fresh = (mode == "save" and bool(default_name))

        start = start_dir or os.path.expanduser("~")
        if not os.path.isdir(start):
            start = os.path.expanduser("~")
        self.cwd = start

        self.scroll = 0
        self.sel_names = set()      # nombres seleccionados en el dir actual
        self.result = None
        self.done = False
        self.confirm = None         # ruta pendiente de confirmar sobrescritura
        self.row_h = 24
        self.entries = []
        self._refresh()

        # input por frame
        self.mouse = (0, 0)
        self.lmb_down = False
        self.wheel = 0
        self._last_click = (-1, 0)  # (indice, ticks) para doble click

    # -- datos -----------------------------------------------------------
    def _refresh(self):
        try:
            items = os.listdir(self.cwd)
        except OSError:
            items = []
        dirs, files = [], []
        for name in items:
            if name.startswith("."):
                continue
            full = os.path.join(self.cwd, name)
            if os.path.isdir(full):
                dirs.append(name)
            elif self.mode != "dir" and os.path.isfile(full):
                if self.exts is None or os.path.splitext(name)[1].lower() in self.exts:
                    files.append(name)
        dirs.sort(key=str.lower)
        files.sort(key=str.lower)
        self.entries = [("..", "up")] + [(d, "dir") for d in dirs] + \
                       [(f, "file") for f in files]
        self.scroll = 0
        self.sel_names.clear()

    def _enter(self, name):
        if name == "..":
            self.cwd = os.path.dirname(self.cwd.rstrip(os.sep)) or os.sep
        else:
            self.cwd = os.path.join(self.cwd, name)
        self._refresh()

    def _confirm(self):
        if self.mode == "dir":
            self.result = self.cwd
        elif self.mode == "save":
            name = self.filename.strip()
            if not name:
                return
            if self.exts and os.path.splitext(name)[1].lower() not in self.exts:
                name += self.exts[0]
            target = os.path.join(self.cwd, name)
            if os.path.exists(target) and self.confirm != target:
                self.confirm = target       # pedir confirmacion de sobrescritura
                return
            self.result = target
            self.done = True
            return
        else:  # open
            sel = [os.path.join(self.cwd, n) for n in sorted(self.sel_names)]
            if not sel and self.filename:
                sel = [os.path.join(self.cwd, self.filename)]
            if not sel:
                return
            self.result = sel if self.multi else sel[0]
        self.done = True

    def _click_entry(self, idx):
        name, kind = self.entries[idx]
        now = pygame.time.get_ticks()
        dbl = (self._last_click[0] == idx and now - self._last_click[1] < 400)
        self._last_click = (idx, now)
        if kind in ("up", "dir"):
            self._enter(name)
            return
        # archivo
        if self.multi:
            if name in self.sel_names:
                self.sel_names.discard(name)
            else:
                self.sel_names.add(name)
        else:
            self.sel_names = {name}
        self.filename = name
        self._fresh = False
        if dbl:
            self._confirm()

    # -- bucle -----------------------------------------------------------
    def run(self):
        bg = self.screen.copy()
        while not self.done:
            self.clock.tick(60)
            self.lmb_down = False
            self.wheel = 0
            for e in pygame.event.get():
                if e.type == pygame.QUIT:
                    pygame.event.post(pygame.event.Event(pygame.QUIT))
                    self.done = True
                    self.result = None
                elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                    self.lmb_down = True
                elif e.type == pygame.MOUSEWHEEL:
                    self.wheel += e.y
                elif e.type == pygame.KEYDOWN:
                    self._key(e)
            self.mouse = pygame.mouse.get_pos()
            self._draw(bg)
            pygame.display.flip()
        return self.result

    def _key(self, e):
        if self.confirm is not None:       # modal de sobrescritura activo
            if e.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self.result = self.confirm
                self.done = True
            elif e.key == pygame.K_ESCAPE:
                self.confirm = None
            return
        if e.key == pygame.K_ESCAPE:
            self.result = None
            self.done = True
        elif e.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self._confirm()
        elif self.mode == "save":
            if e.key == pygame.K_BACKSPACE:
                if self._fresh:
                    self.filename = ""
                self._fresh = False
                self.filename = self.filename[:-1]
            elif e.unicode and e.unicode.isprintable():
                if self._fresh:
                    self.filename = ""
                    self._fresh = False
                if len(self.filename) < 60:
                    self.filename += e.unicode

    # -- widgets ---------------------------------------------------------
    def _text(self, s, pos, color=TEXT, font=None, center=False, right=False):
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

    def _button(self, rect, label, active=False):
        hot = rect.collidepoint(self.mouse)
        col = ACTIVE if active else (HOVER if hot else PANEL2)
        pygame.draw.rect(self.screen, col, rect, border_radius=4)
        pygame.draw.rect(self.screen, LINE, rect, 1, border_radius=4)
        self._text(label, rect.center, TEXT, font=self.font_s, center=True)
        return self.lmb_down and hot

    # -- dibujo ----------------------------------------------------------
    def _draw(self, bg):
        # si hay confirmacion de sobrescritura, desactivar la interaccion de
        # fondo (la lista/botones) mientras el modal este visible
        real_click = self.lmb_down
        if self.confirm is not None:
            self.lmb_down = False
        self.screen.blit(bg, (0, 0))
        ov = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
        ov.fill(BG_DIM)
        self.screen.blit(ov, (0, 0))

        sw, sh = self.screen.get_size()
        pw, ph = min(760, sw - 40), min(560, sh - 40)
        panel = pygame.Rect((sw - pw) // 2, (sh - ph) // 2, pw, ph)
        pygame.draw.rect(self.screen, PANEL, panel, border_radius=8)
        pygame.draw.rect(self.screen, ACCENT, panel, 2, border_radius=8)

        self._text(self.title, (panel.x + 16, panel.y + 12), ACCENT, self.font)
        # barra de ruta
        path_r = pygame.Rect(panel.x + 16, panel.y + 38, panel.w - 32, 24)
        pygame.draw.rect(self.screen, (24, 26, 32), path_r, border_radius=3)
        shown = self.cwd
        while self.font_s.size(shown)[0] > path_r.w - 16 and len(shown) > 8:
            shown = "..." + shown[4:]
        self._text(shown, (path_r.x + 6, path_r.centery - 7), DIM, self.font_s)

        # lista
        list_r = pygame.Rect(panel.x + 16, panel.y + 70, panel.w - 32,
                             panel.h - 70 - 64)
        pygame.draw.rect(self.screen, (28, 30, 36), list_r, border_radius=4)
        self.screen.set_clip(list_r)
        rows = max(1, list_r.h // self.row_h)
        maxscroll = max(0, len(self.entries) - rows)
        self.scroll = max(0, min(maxscroll, self.scroll - self.wheel))
        clicked = None
        y = list_r.y
        for i in range(self.scroll, min(len(self.entries), self.scroll + rows)):
            name, kind = self.entries[i]
            row = pygame.Rect(list_r.x, y, list_r.w, self.row_h)
            selected = (kind == "file" and name in self.sel_names)
            if row.collidepoint(self.mouse):
                pygame.draw.rect(self.screen, HOVER, row)
            if selected:
                pygame.draw.rect(self.screen, ACTIVE, row)
            icon = "[..]" if kind == "up" else ("[D]" if kind == "dir" else "  ")
            col = DIRCOL if kind in ("dir", "up") else TEXT
            label = ".. (subir)" if kind == "up" else name
            self._text(f"{icon} {label}", (row.x + 8, row.centery - 7),
                       SEL if selected else col, self.font_s)
            # diferir: NO mutar self.entries dentro del bucle de dibujo
            if self.lmb_down and row.collidepoint(self.mouse):
                clicked = i
            y += self.row_h
        self.screen.set_clip(None)
        # barra de scroll
        if maxscroll > 0:
            bar_h = max(20, list_r.h * rows // len(self.entries))
            bar_y = list_r.y + (list_r.h - bar_h) * self.scroll // maxscroll
            pygame.draw.rect(self.screen, PANEL2,
                             (list_r.right - 6, bar_y, 4, bar_h),
                             border_radius=2)

        # pie: nombre (save) + botones
        foot_y = panel.bottom - 52
        if self.mode == "save":
            self._text("Nombre:", (panel.x + 16, foot_y + 6), DIM, self.font_s)
            fr = pygame.Rect(panel.x + 80, foot_y, panel.w - 96 - 180, 26)
            pygame.draw.rect(self.screen, (24, 26, 32), fr, border_radius=3)
            pygame.draw.rect(self.screen, ACCENT, fr, 1, border_radius=3)
            if self._fresh:        # nombre "seleccionado": fondo resaltado
                tw = self.font_s.size(self.filename)[0]
                pygame.draw.rect(self.screen, (60, 80, 130),
                                 (fr.x + 5, fr.y + 4, min(tw + 2, fr.w - 10), 18))
                self._text(self.filename, (fr.x + 6, fr.centery - 7), TEXT,
                           self.font_s)
                self._text("(escribe para reemplazar)",
                           (fr.right + 6, fr.centery - 7), DIM, self.font_s)
            else:
                caret = "|" if (pygame.time.get_ticks() // 400) % 2 else ""
                self._text(self.filename + caret, (fr.x + 6, fr.centery - 7),
                           TEXT, self.font_s)
            if self.lmb_down and fr.collidepoint(self.mouse):
                self.filename = ""      # clic en el campo: limpiar para escribir
                self._fresh = False
        elif self.mode == "open" and self.multi:
            self._text(f"{len(self.sel_names)} seleccionada(s) — clic para "
                       f"marcar, doble clic para abrir", (panel.x + 16,
                       foot_y + 6), DIM, self.font_s)
        else:
            self._text("Doble clic para abrir, o selecciona y pulsa Aceptar",
                       (panel.x + 16, foot_y + 6), DIM, self.font_s)

        ok_label = {"save": "Guardar", "dir": "Usar carpeta"}.get(
            self.mode, "Abrir")
        if self._button(pygame.Rect(panel.right - 180, foot_y, 80, 28),
                        "Cancelar"):
            self.result = None
            self.done = True
        if self._button(pygame.Rect(panel.right - 92, foot_y, 80, 28),
                        ok_label, active=True):
            self._confirm()

        # procesar el clic en la lista AHORA (fuera del bucle de dibujo),
        # asi _refresh() puede reemplazar self.entries sin romper la iteracion
        if clicked is not None and clicked < len(self.entries):
            self._click_entry(clicked)

        # modal de sobrescritura encima de todo
        if self.confirm is not None:
            self.lmb_down = real_click
            self._draw_confirm()

    def _draw_confirm(self):
        sw, sh = self.screen.get_size()
        box = pygame.Rect(sw // 2 - 220, sh // 2 - 70, 440, 140)
        shade = pygame.Surface((sw, sh), pygame.SRCALPHA)
        shade.fill((0, 0, 0, 120))
        self.screen.blit(shade, (0, 0))
        pygame.draw.rect(self.screen, PANEL, box, border_radius=8)
        pygame.draw.rect(self.screen, ACCENT, box, 2, border_radius=8)
        self._text("El archivo ya existe", (box.centerx, box.y + 24), ACCENT,
                   self.font, center=True)
        self._text(os.path.basename(self.confirm), (box.centerx, box.y + 52),
                   TEXT, self.font_s, center=True)
        self._text("Se va a sobrescribir. Continuar?", (box.centerx, box.y + 74),
                   DIM, self.font_s, center=True)
        if self._button(pygame.Rect(box.centerx - 150, box.bottom - 38, 140, 28),
                        "Cancelar"):
            self.confirm = None
        if self._button(pygame.Rect(box.centerx + 10, box.bottom - 38, 140, 28),
                        "Sobrescribir", active=True):
            self.result = self.confirm
            self.done = True
