# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""Backups automáticos atómicos con rotación.

Estrategia:

* ``daily-YYYY-MM-DD.db``               — uno por día (retención 7)
* ``on-exit-YYYY-MM-DDTHH-MM-SS.db``    — al cerrar la app (retención 10)
* ``manual-YYYY-MM-DDTHH-MM-SS.db``     — a demanda (retención 10)

Usa ``sqlite3.Connection.backup()``, la API oficial de SQLite — atómica
incluso con la BD abierta y con writes pendientes (a diferencia de
``shutil.copy`` que puede capturar un WAL intermedio).

Vive en ``USER_DATA_DIR/backups/`` (ver ``core/config.py``).
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from core.config import DB_PATH, BACKUPS_DIR


# Cuántos backups retener por etiqueta
RETENCION: dict[str, int] = {
    'daily':    7,
    'on-exit':  10,
    'manual':   10,
}


def _ensure_dir() -> None:
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)


def _nombre(label: str) -> str:
    """Genera el nombre del archivo según la etiqueta."""
    now = datetime.now()
    if label == 'daily':
        return f"daily-{now.strftime('%Y-%m-%d')}.db"
    return f"{label}-{now.strftime('%Y-%m-%dT%H-%M-%S')}.db"


def crear_backup(label: str = 'manual') -> Path | None:
    """Crea un backup atómico de la BD activa.

    Args:
        label: 'daily', 'on-exit', 'manual' u otra etiqueta arbitraria.

    Returns:
        ``Path`` del backup creado, o ``None`` si:
        - falló la conexión a la BD original;
        - el backup ``daily`` de hoy ya existía (no se duplica);
        - hubo error de I/O (el archivo parcial se elimina).
    """
    _ensure_dir()
    dst = BACKUPS_DIR / _nombre(label)
    if label == 'daily' and dst.exists():
        return None
    if not DB_PATH.exists():
        return None
    try:
        src = sqlite3.connect(str(DB_PATH))
        bkp = sqlite3.connect(str(dst))
        try:
            with bkp:
                src.backup(bkp)
        finally:
            bkp.close()
            src.close()
    except sqlite3.Error:
        try:
            dst.unlink(missing_ok=True)
        except OSError:
            pass
        return None
    return dst


def rotar_backups() -> int:
    """Aplica la política de retención: borra los archivos más antiguos
    según el prefijo de cada label en ``RETENCION``.

    Returns:
        Número de archivos eliminados."""
    if not BACKUPS_DIR.exists():
        return 0
    eliminados = 0
    for label, max_n in RETENCION.items():
        archivos = sorted(
            BACKUPS_DIR.glob(f"{label}-*.db"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for viejo in archivos[max_n:]:
            try:
                viejo.unlink()
                eliminados += 1
            except OSError:
                pass
    return eliminados


def info_backups() -> dict:
    """Métricas para la UI: último backup, conteo, tamaño total."""
    _ensure_dir()
    archivos = sorted(
        BACKUPS_DIR.glob("*.db"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    ultimo = archivos[0] if archivos else None
    return {
        'carpeta':       BACKUPS_DIR,
        'cantidad':      len(archivos),
        'ultimo':        ultimo,
        'ultimo_mtime':  (datetime.fromtimestamp(ultimo.stat().st_mtime)
                          if ultimo else None),
        'tamano_total':  sum(p.stat().st_size for p in archivos),
    }
