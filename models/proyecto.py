# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Proyecto:
    id: int = 0
    nombre: str = ""
    cliente: str = ""
    ubicacion: str = ""
    sub_presupuesto: str = ""
    costo_al: str = ""
    plazo: int = 0
    gf_pct: float = 0.0
    utilidad_pct: float = 0.0
    igv_pct: float = 18.0
    creado_en: str = ""
    grupo_analisis: str = ""
    jornada_laboral: float = 8.0
    moneda: str = "Soles"
    modalidad: str = ""
    usuario_id: Optional[int] = None
    favorito: int = 0
    estado: str = "elaboracion"  # elaboracion|revision|aprobado|ejecutado


@dataclass
class Partida:
    id: int = 0
    proyecto_id: int = 0
    item: str = ""
    descripcion: str = ""
    unidad: str = ""
    metrado: float = 0.0
    precio_unitario: float = 0.0
    nivel: int = 1
    es_titulo: int = 0
    especificaciones: str = ""
    rendimiento: float = 0.0
    grupo: str = ""


@dataclass
class AcuItem:
    id: int = 0
    partida_id: int = 0
    recurso_id: int = 0
    cuadrilla: float = 1.0
    cantidad: float = 0.0
    precio: float = 0.0          # precio POR PROYECTO (COALESCE con recursos.precio)
    # campos join desde recursos:
    codigo: str = ""
    descripcion: str = ""
    tipo: str = ""               # MO|MAT|EQ
    unidad: str = ""
    indice_inei: str = ""


@dataclass
class GastoGeneral:
    id: int = 0
    proyecto_id: int = 0
    rubro: str = ""
    tipo: str = "item"           # 'grupo' | 'item'
    descripcion: str = ""
    unidad: str = ""
    n_personas: float = 1.0
    tiempo: float = 1.0
    pct_participacion: float = 100.0
    precio: float = 0.0
    orden: int = 0
