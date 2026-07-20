# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""Detector cross-platform de LibreOffice/OpenOffice (`soffice`).

Centraliza la búsqueda de `soffice`/`libreoffice` que en Linux suele estar
en PATH, pero en Windows típicamente vive en `C:\\Program Files\\LibreOffice\\
program\\soffice.exe` y no se agrega al PATH del usuario. macOS lo instala
dentro del .app bundle.

Antes este chequeo se replicaba como
``shutil.which('libreoffice') or shutil.which('soffice')`` en 13 sitios y
en Windows fallaba aunque LibreOffice estuviera instalado — por eso los
exports a ODS/ODT no funcionaban en Windows.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Optional


def _wrapper_host_soffice() -> Optional[str]:
    """Bajo Flatpak, LibreOffice vive en el HOST. Crea (una vez) un pequeño
    script que reenvía la llamada al host vía ``flatpak-spawn`` y devuelve su
    ruta. Devuelve None si el host no tiene LibreOffice instalado."""
    import subprocess
    from core.config import USER_DATA_DIR

    # flatpak-spawn --host hereda el cwd del proceso (bajo Flatpak = /app/…),
    # que NO existe en el host → falla con "Failed to change to folder". Hay
    # que fijar --directory a una ruta válida del host (el home del usuario).
    # Nota: flatpak-spawn exige la forma con «=» (--directory=DIR), no separada.
    host_dir = os.environ.get('HOME') or '/'

    exe = None
    for nombre in ('libreoffice', 'soffice'):
        try:
            r = subprocess.run(
                ['flatpak-spawn', '--host', f'--directory={host_dir}', 'which', nombre],
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode == 0 and r.stdout.strip():
                exe = nombre
                break
        except Exception:
            pass
    if not exe:
        return None

    wrapper = USER_DATA_DIR / 'soffice-host.sh'
    contenido = (
        f'#!/bin/sh\n'
        f'exec flatpak-spawn --host --directory="$HOME" {exe} "$@"\n'
    )
    try:
        if not wrapper.exists() or wrapper.read_text() != contenido:
            wrapper.write_text(contenido)
            wrapper.chmod(0o755)
    except Exception:
        return None
    return str(wrapper)


def find_soffice() -> Optional[str]:
    """Devuelve la ruta absoluta a `soffice`/`libreoffice` o None si no se
    encuentra. Busca primero en PATH (lo más rápido) y luego en las rutas
    de instalación típicas de cada plataforma."""
    # 0. Flatpak — LibreOffice está en el host; devolver el wrapper.
    from core.config import es_flatpak
    if es_flatpak():
        return _wrapper_host_soffice()

    # 1. PATH (caso normal en Linux y Windows con LibreOffice agregado al PATH)
    for nombre in ('libreoffice', 'soffice'):
        path = shutil.which(nombre)
        if path:
            return path

    # 2. Rutas típicas por plataforma
    candidatos: list[Path] = []
    if sys.platform == 'win32':
        # Windows — LibreOffice (instalador oficial) + OpenOffice fallback
        program_files = [
            os.environ.get('ProgramFiles', r'C:\Program Files'),
            os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)'),
            os.environ.get('ProgramW6432', r'C:\Program Files'),
        ]
        for pf in dict.fromkeys(program_files):  # dedupe preservando orden
            if not pf:
                continue
            candidatos.append(Path(pf) / 'LibreOffice' / 'program' / 'soffice.exe')
            candidatos.append(Path(pf) / 'OpenOffice 4' / 'program' / 'soffice.exe')
            candidatos.append(Path(pf) / 'OpenOffice' / 'program' / 'soffice.exe')
    elif sys.platform == 'darwin':
        # macOS — LibreOffice se instala como /Applications/LibreOffice.app
        candidatos.extend([
            Path('/Applications/LibreOffice.app/Contents/MacOS/soffice'),
            Path.home() / 'Applications' / 'LibreOffice.app'
                / 'Contents' / 'MacOS' / 'soffice',
        ])
    else:
        # Linux — extras por si /usr/bin no está en PATH
        candidatos.extend([
            Path('/usr/bin/libreoffice'),
            Path('/usr/bin/soffice'),
            Path('/usr/local/bin/libreoffice'),
            Path('/usr/local/bin/soffice'),
            Path('/snap/bin/libreoffice'),
            Path('/var/lib/flatpak/exports/bin/org.libreoffice.LibreOffice'),
        ])

    for c in candidatos:
        if c.exists():
            return str(c)
    return None


def soffice_disponible() -> bool:
    return find_soffice() is not None


_odf_ofrecible_cache: Optional[bool] = None


def odf_export_ofrecible() -> bool:
    """Si conviene OFRECER en la UI los botones de exportación ODT/ODS.

    Devuelve False solo en la edición Flatpak SIN acceso al LibreOffice del host
    (Flathub): allí ODT/ODS nunca pueden funcionar y no se puede instalar
    LibreOffice dentro del sandbox, así que esos botones deben ocultarse. En
    instalación nativa sin LibreOffice devuelve True: se muestran los botones con
    su aviso de cómo instalarlo (discoverability). Resultado cacheado por proceso."""
    global _odf_ofrecible_cache
    if _odf_ofrecible_cache is None:
        from core.config import es_flatpak
        _odf_ofrecible_cache = not (es_flatpak() and not soffice_disponible())
    return _odf_ofrecible_cache


def mensaje_instalacion() -> str:
    """Devuelve un mensaje user-facing con instrucciones de instalación
    según la plataforma actual."""
    if sys.platform == 'win32':
        return (
            "LibreOffice no está instalado en el sistema. La exportación "
            "a ODS/ODT usa LibreOffice headless para garantizar fidelidad "
            "visual con el PDF.\n\n"
            "Descárgalo gratis desde:\n  https://es.libreoffice.org/descarga/\n\n"
            "Mientras tanto, usa Excel (.xlsx) o Word (.docx) — abren "
            "perfectamente en LibreOffice si lo instalás más tarde."
        )
    if sys.platform == 'darwin':
        return (
            "LibreOffice no está instalado. La exportación a ODS/ODT lo "
            "necesita.\n\n"
            "Descárgalo gratis desde:\n  https://es.libreoffice.org/descarga/\n\n"
            "Mientras tanto, usa Excel (.xlsx) o Word (.docx) — Pages y "
            "Numbers los abren sin problema."
        )
    # Linux
    return (
        "LibreOffice no está instalado en el sistema. La exportación "
        "a ODS/ODT usa LibreOffice headless para garantizar fidelidad.\n\n"
        "Instálalo con:\n  sudo apt install libreoffice\n\n"
        "Mientras tanto, usa Excel (.xlsx) — también abre en LibreOffice."
    )
