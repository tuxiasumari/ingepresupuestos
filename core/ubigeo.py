# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""ubigeo — base UBIGEO del Perú (INEI) para autocompletar la ubicación.

Dataset: `resources/ubigeo_peru.json` (1,893 distritos · 196 provincias ·
25 departamentos), derivado de jmcastagnetto/ubigeo-peru-aumentado (INEI).
Cada registro: {u: ubigeo, d: distrito, p: provincia, r: departamento}.

Uso típico (vista Nuevo Proyecto): `cargar_ubigeo()` devuelve la lista de
distritos con una etiqueta legible «Distrito, Provincia, Departamento» y una
clave normalizada (sin tildes/mayúsculas) para el autocompletado.
"""
from __future__ import annotations

import json
from functools import lru_cache

from core.config import BASE_DIR
from utils.formatting import norm_busqueda

_RUTA = BASE_DIR / "resources" / "ubigeo_peru.json"

# Partículas que en español van en minúscula dentro de un nombre propio.
_PARTICULAS = {"de", "del", "la", "las", "los", "y", "e"}


def _titular(nombre: str) -> str:
    """Title-case respetando partículas (San Juan de Lurigancho)."""
    palabras = (nombre or "").strip().lower().split()
    out = []
    for i, w in enumerate(palabras):
        out.append(w if (i > 0 and w in _PARTICULAS) else w.capitalize())
    return " ".join(out)


@lru_cache(maxsize=1)
def cargar_ubigeo() -> list[dict]:
    """Lista de distritos: {ubigeo, distrito, provincia, departamento,
    etiqueta, norm}. `etiqueta` = «Distrito, Provincia, Departamento»
    (title-case); `norm` = etiqueta sin tildes/mayúsculas para matching.
    Cacheada. Si el archivo falta, devuelve []."""
    try:
        with open(_RUTA, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return []
    out = []
    for r in raw:
        dis = _titular(r.get("d", ""))
        pro = _titular(r.get("p", ""))
        dep = _titular(r.get("r", ""))
        if not (dis and pro and dep):
            continue
        etiqueta = f"{dis}, {pro}, {dep}"
        out.append({
            "ubigeo": r.get("u", ""),
            "distrito": dis, "provincia": pro, "departamento": dep,
            "etiqueta": etiqueta,
            "norm": norm_busqueda(etiqueta),
            "altitud": r.get("alt"),       # msnm (capital del distrito)
            "latitud": r.get("lat"),       # WGS84
            "longitud": r.get("lon"),
            "capital": _titular(r.get("cap", "")) or dis,
        })
    return out


@lru_cache(maxsize=1)
def _indice_por_triple() -> dict:
    """{(norm_distrito, norm_provincia, norm_departamento): registro}."""
    idx = {}
    for d in cargar_ubigeo():
        clave = (norm_busqueda(d["distrito"]), norm_busqueda(d["provincia"]),
                 norm_busqueda(d["departamento"]))
        idx[clave] = d
    return idx


def latlon_a_utm(lat: float, lon: float) -> dict | None:
    """Convierte coordenadas geográficas WGS84 (lat/lon en grados) a UTM
    WGS84 (zona + hemisferio + Este/Norte en metros) — el sistema que se usa
    en ingeniería en el Perú. Fórmula estándar de Transverse Mercator, sin
    dependencias externas. Devuelve {zona, hemisferio, este, norte, etiqueta}."""
    import math
    try:
        lat = float(lat); lon = float(lon)
    except (TypeError, ValueError):
        return None
    a = 6378137.0                 # semieje mayor WGS84
    f = 1 / 298.257223563         # achatamiento
    e2 = f * (2 - f)
    ep2 = e2 / (1 - e2)
    k0 = 0.9996
    zona = int((lon + 180) / 6) + 1
    lon0 = math.radians((zona - 1) * 6 - 180 + 3)
    latr = math.radians(lat)
    lonr = math.radians(lon)
    N = a / math.sqrt(1 - e2 * math.sin(latr) ** 2)
    T = math.tan(latr) ** 2
    C = ep2 * math.cos(latr) ** 2
    A = math.cos(latr) * (lonr - lon0)
    M = a * ((1 - e2 / 4 - 3 * e2**2 / 64 - 5 * e2**3 / 256) * latr
             - (3 * e2 / 8 + 3 * e2**2 / 32 + 45 * e2**3 / 1024) * math.sin(2 * latr)
             + (15 * e2**2 / 256 + 45 * e2**3 / 1024) * math.sin(4 * latr)
             - (35 * e2**3 / 3072) * math.sin(6 * latr))
    este = (k0 * N * (A + (1 - T + C) * A**3 / 6
            + (5 - 18 * T + T**2 + 72 * C - 58 * ep2) * A**5 / 120) + 500000)
    norte = (k0 * (M + N * math.tan(latr) * (A**2 / 2
             + (5 - T + 9 * C + 4 * C**2) * A**4 / 24
             + (61 - 58 * T + T**2 + 600 * C - 330 * ep2) * A**6 / 720)))
    hemi = 'N'
    if lat < 0:
        norte += 10000000
        hemi = 'S'
    return {
        'zona': zona, 'hemisferio': hemi,
        'este': round(este, 2), 'norte': round(norte, 2),
        'etiqueta': f"Zona {zona}{hemi}, Este {este:.2f} m, Norte {norte:.2f} m",
    }


def coords_de_ubicacion(texto: str) -> dict | None:
    """Dada una ubicación «Distrito, Provincia, Departamento» (como la guarda
    el proyecto), devuelve el registro UBIGEO con altitud/lat/lon/capital, o
    None si no se reconoce el distrito. Tolera tildes/mayúsculas."""
    partes = [p.strip() for p in (texto or "").split(",") if p.strip()]
    if len(partes) < 3:
        return None
    clave = (norm_busqueda(partes[0]), norm_busqueda(partes[1]),
             norm_busqueda(partes[2]))
    return _indice_por_triple().get(clave)


def buscar(texto: str, limite: int = 20) -> list[dict]:
    """Distritos cuya etiqueta contiene `texto` (sin tildes/mayúsculas).
    Prioriza los que EMPIEZAN por el distrito. Para uso programático/tests;
    la UI usa el modelo + proxy directamente."""
    q = norm_busqueda(texto or "")
    if not q:
        return []
    datos = cargar_ubigeo()
    empiezan, contienen = [], []
    for d in datos:
        if d["norm"].startswith(q):
            empiezan.append(d)
        elif q in d["norm"]:
            contienen.append(d)
    return (empiezan + contienen)[:limite]
