# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""Helper para usar Bootstrap Icons como fuente cargada en QFontDatabase.

La fuente `bootstrap-icons.woff2` se carga una vez al arranque (main.py).
Todas las vistas la usan con `bi("nombre")` que retorna el carácter Unicode.

Por qué Bootstrap Icons (vs emojis):
    - Los emojis se ven distinto en cada SO (Segoe UI Emoji / Apple Color
      Emoji / Noto Color Emoji). Aquí queremos un look idéntico en
      Windows / macOS / Linux, así que empaquetamos la fuente.
    - Bootstrap Icons coincide con la versión Flask original (clases
      ``bi bi-...`` en los templates).
"""
from __future__ import annotations

import json
from pathlib import Path
from PySide6.QtGui import QFontDatabase, QFont, QFontInfo

# Nombre de la familia que reporta el WOFF2 cargado
BOOTSTRAP_FAMILY = "bootstrap-icons"

_FONT_PATH = Path(__file__).parent.parent / "resources" / "fonts" / "bootstrap-icons.woff2"
_JSON_PATH = Path(__file__).parent.parent / "resources" / "fonts" / "bootstrap-icons.json"

_codepoints: dict[str, int] | None = None
_font_id: int | None = None


def cargar_fuente() -> bool:
    """Registra la fuente en QFontDatabase. Llamar una sola vez en main.py.

    Retorna True si la fuente quedó disponible, False si falló (la app sigue
    funcionando con un fallback de emojis Unicode genéricos).
    """
    global _font_id
    if _font_id is not None:
        return _font_id >= 0
    if not _FONT_PATH.exists():
        _font_id = -1
        return False
    fid = QFontDatabase.addApplicationFont(str(_FONT_PATH))
    _font_id = fid
    return fid >= 0


def _ensure_codepoints() -> dict[str, int]:
    global _codepoints
    if _codepoints is None:
        try:
            with _JSON_PATH.open(encoding="utf-8") as f:
                _codepoints = json.load(f)
        except Exception:
            _codepoints = {}
    return _codepoints


def bi(nombre: str) -> str:
    """Retorna el carácter Unicode del icono ``nombre`` de Bootstrap Icons.

    Ejemplos:
        bi("plus-lg")  -> "\\uF64D"
        bi("pencil")   -> "\\uF4CB"

    Si la fuente no está cargada o el nombre no existe, devuelve un fallback
    de emoji que al menos comunica la intención.
    """
    cp = _ensure_codepoints().get(nombre)
    if cp is None:
        return _FALLBACK.get(nombre, "•")
    return chr(cp)


def font(size_pt: int = 12) -> QFont:
    """QFont configurado con la familia Bootstrap Icons al tamaño dado."""
    f = QFont(BOOTSTRAP_FAMILY)
    f.setPointSize(size_pt)
    f.setStyleStrategy(QFont.NoFontMerging)
    return f


# Fallback de emojis si la fuente no carga (uso en desarrollo / fallback)
_FALLBACK = {
    "plus-lg": "+", "pencil": "✏", "trash": "🗑", "search": "🔎",
    "x-lg": "✕", "arrow-left": "←", "arrow-right": "→",
    "download": "📥", "upload": "📤", "files": "📋",
    "box-seam": "📦", "graph-up": "📈", "list-task": "📋",
    "calculator": "🧮", "rulers": "📐", "file-text": "📝",
    "calendar3": "📅", "cash-coin": "💰", "bar-chart": "📊",
    "cart": "🛒", "book": "📚", "palette": "🎨",
    "lock": "🔒", "unlock": "🔓", "stars": "✨",
    "check-lg": "✓", "filter": "▾",
}
