"""Autosave / recuperacion ante cierre brusco.

Escribe periodicamente el estado del proyecto a ~/.pixelbones/recovery.json.
Si el programa se cierra de golpe (kill, corte de luz, crash), al reabrir se
detecta ese archivo y se ofrece recuperar. Las rutas de imagen se guardan
absolutas para que la recuperacion funcione sin el .pbproj.
"""

from __future__ import annotations
import json
import os

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".pixelbones")
RECOVERY_FILE = os.path.join(CONFIG_DIR, "recovery.json")


def _ensure_dir():
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        return True
    except OSError:
        return False


def write(project_dict, source_path):
    """Escritura atomica del estado de recuperacion."""
    if not _ensure_dir():
        return
    payload = {"source_path": source_path, "data": project_dict}
    tmp = RECOVERY_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
        os.replace(tmp, RECOVERY_FILE)
    except OSError:
        pass


def exists():
    return os.path.isfile(RECOVERY_FILE)


def read():
    try:
        with open(RECOVERY_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def clear():
    try:
        if os.path.isfile(RECOVERY_FILE):
            os.remove(RECOVERY_FILE)
    except OSError:
        pass
