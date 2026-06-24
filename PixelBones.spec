# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec para PixelBones. Genera un unico ejecutable (onefile) con el
# icono de la app.  Compilar:  pyinstaller PixelBones.spec
# (En Windows produce PixelBones.exe; en Linux/macOS, el binario nativo.)

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    # Empacar las plantillas builtin (body estandar/humano) que usa el modo
    # fantasma; sin esto, en el ejecutable no hay body de guia para los items.
    datas=[('pixelbones/templates', 'pixelbones/templates')],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=['numpy', 'PIL'],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='PixelBones',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    runtime_tmpdir=None,
    console=False,
    icon='docs/icon.ico',
)
