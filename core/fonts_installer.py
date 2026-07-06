# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""Instala la fuente Inter (bundleada en `resources/fonts/`) en el directorio
de fuentes del usuario para que otros programas — LibreOffice, MS Word,
Excel, etc. — también puedan usarla al abrir los reportes .docx/.odt/.xlsx
exportados por ingePresupuestos.

Idempotente: usa un archivo marker en USER_DATA_DIR para no reintentar en
cada arranque. Per-user install, no requiere admin.

- Linux:   ~/.local/share/fonts/ (+ fc-cache para refrescar fontconfig)
- macOS:   ~/Library/Fonts/
- Windows: %LOCALAPPDATA%/Microsoft/Windows/Fonts/
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from .config import BASE_DIR, USER_DATA_DIR

# v2 — bumpeado porque la v1 en Windows solo copiaba el TTF sin
# registrar en el registro de fuentes per-user, así que Word/LibreOffice
# no veían Inter y la sustituían por Times New Roman/Calibri. La v2
# registra en HKCU\...\Fonts y broadcasta WM_FONTCHANGE.
# v3 — agregadas Inter-Bold + Inter-BoldItalic (faltaban). Bumpeado
# marker para que usuarios viejos vuelvan a correr el installer y se
# registren los 2 archivos nuevos.
_MARKER = USER_DATA_DIR / '.fonts_installed_v3'
_FUENTES = (
    ('Inter.ttf',            'Inter (TrueType)'),
    ('Inter-Italic.ttf',     'Inter Italic (TrueType)'),
    ('Inter-Bold.ttf',       'Inter Bold (TrueType)'),
    ('Inter-BoldItalic.ttf', 'Inter Bold Italic (TrueType)'),
)


def _user_fonts_dir() -> Path:
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Fonts'
    if sys.platform == 'win32':
        appdata = os.environ.get('LOCALAPPDATA') or str(
            Path.home() / 'AppData' / 'Local'
        )
        return Path(appdata) / 'Microsoft' / 'Windows' / 'Fonts'
    return Path.home() / '.local' / 'share' / 'fonts'


def _registrar_windows(nombre_amigable: str, ruta_ttf: Path) -> bool:
    """En Windows, registra la fuente en HKCU para que Word/LibreOffice/etc.
    la vean sin necesidad de privilegios admin. Devuelve True si OK."""
    if sys.platform != 'win32':
        return False
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r'Software\Microsoft\Windows NT\CurrentVersion\Fonts',
            0, winreg.KEY_SET_VALUE
        )
        try:
            # El value puede ser solo el nombre del archivo (si la fuente
            # está en el dir per-user estándar de Windows 10+) o la ruta
            # completa. Usamos ruta completa para garantizar resolución.
            winreg.SetValueEx(key, nombre_amigable, 0,
                              winreg.REG_SZ, str(ruta_ttf))
        finally:
            winreg.CloseKey(key)
        return True
    except (ImportError, OSError):
        return False


def _broadcast_font_change_windows() -> None:
    """En Windows, notifica a TODAS las apps abiertas que la lista de
    fuentes cambió (WM_FONTCHANGE = 0x001D, HWND_BROADCAST = 0xFFFF).
    Sin esto, Word/LibreOffice que YA estaban abiertos no ven la fuente
    nueva hasta reiniciarlos."""
    if sys.platform != 'win32':
        return
    try:
        import ctypes
        # SendMessageTimeoutW para no bloquear si una app no responde.
        # SMTO_ABORTIFHUNG = 0x0002, timeout 1000 ms.
        ctypes.windll.user32.SendMessageTimeoutW(
            0xFFFF, 0x001D, 0, 0, 0x0002, 1000, ctypes.byref(ctypes.c_long())
        )
    except (OSError, AttributeError):
        pass


def instalar_fuentes_si_falta() -> bool:
    """Copia Inter.ttf y Inter-Italic.ttf al directorio de fuentes del usuario
    y, en Windows, las registra en HKCU para que apps externas (Word,
    LibreOffice, etc.) las puedan usar al abrir los reportes exportados.

    Idempotente: marker en USER_DATA_DIR evita reintentar.
    """
    if _MARKER.exists():
        return False
    src_dir = BASE_DIR / 'resources' / 'fonts'
    if not src_dir.exists():
        return False
    dst_dir = _user_fonts_dir()
    try:
        dst_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False

    copiadas: list[str] = []
    registradas_win: list[str] = []
    for nombre_archivo, nombre_amigable in _FUENTES:
        src = src_dir / nombre_archivo
        if not src.exists():
            continue
        dst = dst_dir / nombre_archivo
        if not dst.exists():
            try:
                shutil.copy2(src, dst)
                copiadas.append(nombre_archivo)
            except OSError:
                continue
        # En Windows, registrar en HKCU aunque el archivo ya existía
        # (puede que se haya copiado en una versión anterior sin registrar).
        if sys.platform == 'win32':
            if _registrar_windows(nombre_amigable, dst):
                registradas_win.append(nombre_archivo)

    # Linux: refrescar fontconfig (opcional — la mayoría de apps escanean
    # ~/.local/share/fonts/ al arrancar igual).
    if sys.platform.startswith('linux') and copiadas:
        try:
            subprocess.run(
                ['fc-cache', '-f', str(dst_dir)],
                capture_output=True, timeout=10,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass

    # Windows: notificar a apps abiertas que la lista de fuentes cambió.
    if registradas_win:
        _broadcast_font_change_windows()

    # Marker — incluso si nada se copió/registró (ya estaba todo), para no
    # reintentar en cada arranque.
    try:
        USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
        _MARKER.touch()
    except OSError:
        pass

    return bool(copiadas or registradas_win)
