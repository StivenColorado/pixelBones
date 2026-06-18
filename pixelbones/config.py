"""Config persistente de PixelBones (~/.pixelbones/config.json).

Guarda el 'proyecto por defecto': una carpeta raiz (p.ej. TrashGame) con dos
arboles espejo, uno para los editables (.pbproj) y otro para lo exportado
(PNG). Al guardar, el editable va en <root>/<src_dir>/...; al exportar, el PNG
va al MISMO path relativo pero en <root>/<assets_dir>/...
"""
from __future__ import annotations
import json
import os

CONFIG_DIR = os.path.expanduser("~/.pixelbones")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")


def load():
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save(d):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False
