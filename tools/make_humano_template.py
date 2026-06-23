"""Regenera la plantilla builtin 'humano' a partir de un proyecto .pbproj real
(el cuerpo riggeado del juego), quitando TODO el arte: una plantilla = solo rig
(huesos + sockets) + animaciones (clips), sin sprites ni dibujos.

Uso:
    py tools/make_humano_template.py [ruta_proyecto.pbproj]

Por defecto toma el cuerpo del juego en TrashGame/art-src/.../character.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
from pixelbones import model

DEFAULT_SRC = (r"C:\Users\stiven\Desktop\juego\TrashGame\art-src"
               r"\characters\body\character\animacion.pbproj")
DEST = os.path.join(os.path.dirname(__file__), "..", "pixelbones",
                    "templates", "humano.pbproj")


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SRC
    pr = model.Project.load(src)
    pr.sprites = []          # sin materiales (el usuario dibuja y asigna)
    pr.drawings = []         # sin lienzos del taller
    pr.path = None
    pr.save(os.path.normpath(DEST))
    print(f"Plantilla escrita: {os.path.normpath(DEST)}")
    print(f"  tile {pr.tile_w}x{pr.tile_h}  box ({pr.box_x},{pr.box_y})")
    print(f"  huesos: {len(pr.bones)}  (sockets: "
          f"{sum(1 for b in pr.bones if b.anchor)})")
    print(f"  animaciones: {[ (c.name, len(c.frames)) for c in pr.clips ]}")


if __name__ == "__main__":
    main()
