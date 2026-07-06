# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""Formateo de números y monedas (equivale a fmt()/parseFmt() del JS + _parse_num() de Flask)."""
import unicodedata as _ud
from core.config import moneda_cfg


def norm_busqueda(s: str) -> str:
    return ''.join(
        c for c in _ud.normalize('NFKD', s.lower())
        if not _ud.combining(c)
    )


def fmt_num(valor: float, moneda: str = 'Soles', decimales: int = 2) -> str:
    cfg = moneda_cfg(moneda)
    sep_miles = cfg['sep_miles']
    sep_dec   = cfg['sep_dec']
    try:
        entero = int(round(abs(valor) * (10 ** decimales)))
        dec_part = str(entero % (10 ** decimales)).zfill(decimales)
        miles_part = entero // (10 ** decimales)
        miles_str = f"{miles_part:,}".replace(',', sep_miles)
        signo = '-' if valor < 0 else ''
        return f"{signo}{miles_str}{sep_dec}{dec_part}"
    except (TypeError, ValueError):
        return f"0{sep_dec}{'0' * decimales}"


def fmt(valor: float, moneda: str = 'Soles', decimales: int = 2) -> str:
    cfg = moneda_cfg(moneda)
    sep_miles = cfg['sep_miles']
    sep_dec   = cfg['sep_dec']
    simbolo   = cfg['simbolo']

    try:
        entero = int(round(abs(valor) * (10 ** decimales)))
        dec_part = str(entero % (10 ** decimales)).zfill(decimales)
        miles_part = entero // (10 ** decimales)
        miles_str = f"{miles_part:,}".replace(',', sep_miles)
        signo = '-' if valor < 0 else ''
        return f"{signo}{simbolo} {miles_str}{sep_dec}{dec_part}"
    except (TypeError, ValueError):
        return f"{simbolo} 0{sep_dec}{'0' * decimales}"


def parse_num(val: str) -> float:
    """Acepta '21.36' y '21,36' como decimales válidos (equivale a _parse_num de app.py)."""
    if not val:
        return 0.0
    val = str(val).strip()
    # Si tiene punto Y coma, el último es el decimal
    if ',' in val and '.' in val:
        if val.rfind(',') > val.rfind('.'):
            val = val.replace('.', '').replace(',', '.')
        else:
            val = val.replace(',', '')
    elif ',' in val:
        val = val.replace(',', '.')
    try:
        return float(val)
    except ValueError:
        return 0.0


def pad_codigo(codigo: str) -> str:
    """Normaliza código de recurso a 7 dígitos (right-pad ceros)."""
    return str(codigo).ljust(7, '0')[:7]
