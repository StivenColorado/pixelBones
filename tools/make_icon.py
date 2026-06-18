"""Genera los archivos de icono (docs/icon.png y docs/icon.ico) a partir del
icono dibujado por codigo. Uso:  python tools/make_icon.py
Necesita pygame y Pillow."""
import os
import sys

import pygame

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pixelbones.appicon import make_icon

pygame.init()
pygame.display.set_mode((1, 1))

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")
os.makedirs(OUT, exist_ok=True)

# PNG grande
big = make_icon(512)
png_path = os.path.join(OUT, "icon.png")
pygame.image.save(big, png_path)

# ICO multi-resolucion (para el .exe de Windows) via Pillow
from PIL import Image
raw = pygame.image.tobytes(big, "RGBA")
img = Image.frombytes("RGBA", big.get_size(), raw)
ico_path = os.path.join(OUT, "icon.ico")
img.save(ico_path, sizes=[(16, 16), (32, 32), (48, 48), (64, 64),
                          (128, 128), (256, 256)])

print("generado:", png_path, "y", ico_path)
