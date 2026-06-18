"""Dialogos de archivo. Usa el explorador propio en pygame (filebrowser),
que es fiable en todas las plataformas. La app registra su 'host' (la App)
al iniciar para que los dialogos puedan dibujarse sobre la ventana.
"""

from __future__ import annotations
import os
from .filebrowser import FileBrowser, IMG_EXTS

HOST = None
_LAST_DIR = None


def set_host(app):
    global HOST
    HOST = app


def _run(start_dir=None, **kw):
    global _LAST_DIR
    fb = FileBrowser(HOST.screen, HOST.clock, HOST.font, HOST.font_s,
                     start_dir=start_dir or _LAST_DIR, **kw)
    res = fb.run()
    # recordar la carpeta usada para el proximo dialogo
    ref = res[0] if isinstance(res, list) and res else res
    if isinstance(ref, str):
        _LAST_DIR = ref if os.path.isdir(ref) else os.path.dirname(ref)
    return res


def open_images():
    if HOST is None:
        return []
    return _run(title="Importar imagenes", mode="open", multi=True,
                exts=IMG_EXTS) or []


def open_project():
    if HOST is None:
        return None
    return _run(title="Abrir proyecto", mode="open", multi=False,
                exts=(".pbproj",))


def save_project_as(start_dir=None):
    if HOST is None:
        return None
    cur = getattr(getattr(HOST, "project", None), "path", None)
    name = os.path.basename(cur) if cur else "animacion.pbproj"
    return _run(start_dir=start_dir, title="Guardar proyecto como", mode="save",
                exts=(".pbproj",), default_name=name)


def save_png_as():
    if HOST is None:
        return None
    return _run(title="Exportar spritesheet PNG", mode="save",
                exts=(".png",), default_name="spritesheet.png")


def choose_dir():
    if HOST is None:
        return None
    return _run(title="Carpeta para hojas por capa", mode="dir")
