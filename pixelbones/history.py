"""Historial de deshacer/rehacer basado en snapshots (dicts serializables).

Robusto y simple: cada punto de restauracion es una copia del estado del
proyecto (lo que devuelve Project.to_dict). No guarda surfaces, asi que es
ligero. La app decide CUANDO crear un punto (al inicio de cada gesto/accion)
para no inundar el historial durante arrastres continuos.
"""

from __future__ import annotations


class History:
    def __init__(self, limit=120):
        self.limit = limit
        self._undo = []
        self._redo = []

    def clear(self):
        self._undo.clear()
        self._redo.clear()

    def push(self, snapshot):
        """Registra un estado ANTERIOR a una modificacion."""
        self._undo.append(snapshot)
        if len(self._undo) > self.limit:
            self._undo.pop(0)
        self._redo.clear()

    def can_undo(self):
        return bool(self._undo)

    def can_redo(self):
        return bool(self._redo)

    def undo(self, current):
        """Devuelve el estado a restaurar; 'current' va a la pila de rehacer."""
        if not self._undo:
            return None
        self._redo.append(current)
        return self._undo.pop()

    def redo(self, current):
        if not self._redo:
            return None
        self._undo.append(current)
        return self._redo.pop()
