# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""core.formula_polinomica — cálculo y persistencia de la fórmula polinómica.

La fórmula polinómica expresa el reajuste de precios de obra según los
índices INEI:

    K = J·(Jr/Jo) + M·(Mr/Mo) + E·(Er/Eo)

donde J, M, E son los coeficientes (suma 1.000) y r/o son los índices del
período de reajuste / oferta. Cada monomio se guarda en
``formula_monomios`` con: orden · símbolo · descripción · indice_inei ·
coeficiente.

Funciones:
    - ``cargar_monomios(pid)``  → lista de dicts persistidos
    - ``calcular_desde_acu(pid)`` → coeficientes auto-derivados desde el ACU
    - ``guardar_monomios(pid, monomios)`` → reemplaza el set persistido

Espejo de las rutas Flask ``/api/proyecto/<pid>/formula/calcular`` y
``/api/proyecto/<pid>/formula/guardar``.
"""
from __future__ import annotations

from core.database import get_db


def cargar_monomios(proyecto_id: int) -> list[dict]:
    """Lista los monomios persistidos para el proyecto, ordenados."""
    conn = get_db()
    rows = conn.execute(
        "SELECT id, orden, simbolo, descripcion, indice_inei, coeficiente "
        "FROM formula_monomios WHERE proyecto_id=? "
        "ORDER BY orden, id",
        (proyecto_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def calcular_desde_acu(proyecto_id: int) -> dict:
    """Auto-deriva los 3 monomios MO/MAT/EQ desde los totales del ACU.

    Retorna dict con::

        {
          'ok':       bool,
          'msg':      str,                   # solo si ok=False
          'monomios': [...],                 # 3 monomios base si ok=True
          'totales':  {'MO','MAT','EQ','cd'} # totales calculados
        }
    """
    conn = get_db()

    # 1) Insumos normales (excluir overhead con unidad %)
    rows = conn.execute(
        """SELECT r.tipo, SUM(ai.cantidad * p.metrado * COALESCE(ai.precio, r.precio, 0))
                 AS parcial_total
           FROM acu_items ai
           JOIN recursos r ON r.id = ai.recurso_id
           JOIN partidas p ON p.id = ai.partida_id
           WHERE p.proyecto_id=? AND p.es_titulo=0
             AND SUBSTR(r.unidad,1,1) != '%'
           GROUP BY r.tipo""",
        (proyecto_id,)
    ).fetchall()

    totales = {'MO': 0.0, 'MAT': 0.0, 'EQ': 0.0}
    for r in rows:
        tipo = r['tipo'] if r['tipo'] in totales else 'MAT'
        totales[tipo] += r['parcial_total'] or 0

    # 2) Herramientas (% MO) — se contabilizan dentro de EQ
    pct_rows = conn.execute(
        """SELECT p.metrado,
                  SUM(CASE WHEN SUBSTR(r.unidad,1,1)!='%' AND r.tipo='MO'
                           THEN ai.cantidad * COALESCE(ai.precio, r.precio, 0)
                           ELSE 0 END) AS mo_cu,
                  SUM(CASE WHEN LOWER(r.unidad)='%mo'
                           THEN ai.cantidad ELSE 0 END) AS pct_mo
           FROM acu_items ai
           JOIN recursos r ON r.id = ai.recurso_id
           JOIN partidas p ON p.id = ai.partida_id
           WHERE p.proyecto_id=? AND p.es_titulo=0
           GROUP BY p.id""",
        (proyecto_id,)
    ).fetchall()
    for row in pct_rows:
        metrado = row['metrado'] or 0
        mo_cu   = row['mo_cu']  or 0
        totales['EQ'] += (row['pct_mo'] or 0) / 100 * mo_cu * metrado

    cd = totales['MO'] + totales['MAT'] + totales['EQ']
    conn.close()

    if cd == 0:
        return {
            'ok': False,
            'msg': "El proyecto no tiene costos en el ACU.",
            'totales': {**totales, 'cd': 0},
        }

    mo_k  = round(totales['MO']  / cd, 4)
    mat_k = round(totales['MAT'] / cd, 4)
    eq_k  = round(totales['EQ']  / cd, 4)
    # Ajustar al cuarto decimal para que sumen 1.000 exactos
    diferencia = round(1.0 - mo_k - mat_k - eq_k, 4)
    mat_k = round(mat_k + diferencia, 4)

    monomios_base = [
        {'orden': 1, 'simbolo': 'J', 'descripcion': 'Mano de Obra',
         'indice_inei': '47', 'coeficiente': mo_k},
        {'orden': 2, 'simbolo': 'M', 'descripcion': 'Materiales de Construcción',
         'indice_inei': '39', 'coeficiente': mat_k},
        {'orden': 3, 'simbolo': 'E', 'descripcion': 'Maquinaria y Equipo',
         'indice_inei': '48', 'coeficiente': eq_k},
    ]
    return {
        'ok':       True,
        'monomios': monomios_base,
        'totales':  {**totales, 'cd': cd},
    }


def guardar_monomios(proyecto_id: int, monomios: list[dict]) -> None:
    """Reemplaza los monomios del proyecto. ``monomios`` es lista de dicts
    con claves: simbolo, descripcion, indice_inei, coeficiente."""
    conn = get_db()
    try:
        conn.execute(
            "DELETE FROM formula_monomios WHERE proyecto_id=?", (proyecto_id,)
        )
        for i, m in enumerate(monomios):
            conn.execute(
                "INSERT INTO formula_monomios "
                "(proyecto_id, orden, simbolo, descripcion, indice_inei, coeficiente) "
                "VALUES (?,?,?,?,?,?)",
                (proyecto_id, i,
                 (m.get('simbolo') or '').strip(),
                 (m.get('descripcion') or '').strip(),
                 (m.get('indice_inei') or '').strip(),
                 float(m.get('coeficiente') or 0))
            )
        conn.commit()
    finally:
        conn.close()


# ─── REAJUSTE K (con valores INEI) ───────────────────────────────────────────

def cargar_periodos(proyecto_id: int) -> dict:
    """Lee los períodos (oferta/reajuste) y área INEI guardados para el
    proyecto. Si no hay registro, retorna defaults inteligentes:
        - oferta: derivado de proyectos.costo_al si se puede parsear, si no
          año actual / enero
        - reajuste: año/mes actual
        - área: '01' (Lima Metropolitana)
    """
    from datetime import date
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT oferta_anio, oferta_mes, reajuste_anio, reajuste_mes, area_inei "
            "FROM formula_periodos WHERE proyecto_id=?",
            (proyecto_id,)
        ).fetchone()
        proy = conn.execute(
            "SELECT costo_al FROM proyectos WHERE id=?", (proyecto_id,)
        ).fetchone()
    finally:
        conn.close()

    hoy = date.today()
    if row:
        return {
            'oferta_anio':   row['oferta_anio']   or hoy.year,
            'oferta_mes':    row['oferta_mes']    or 1,
            'reajuste_anio': row['reajuste_anio'] or hoy.year,
            'reajuste_mes':  row['reajuste_mes']  or hoy.month,
            'area_inei':     row['area_inei']     or '01',
        }

    # Defaults: parsear costo_al para oferta, hoy para reajuste
    oferta_anio = hoy.year
    oferta_mes = 1
    if proy and proy['costo_al']:
        try:
            from views.calendario_view import _parsear_costo_al
            d = _parsear_costo_al(proy['costo_al'])
            if d:
                oferta_anio, oferta_mes = d.year, d.month
        except Exception:
            pass
    return {
        'oferta_anio':   oferta_anio,
        'oferta_mes':    oferta_mes,
        'reajuste_anio': hoy.year,
        'reajuste_mes':  hoy.month,
        'area_inei':     '01',
    }


def guardar_periodos(proyecto_id: int, oferta_anio: int, oferta_mes: int,
                     reajuste_anio: int, reajuste_mes: int,
                     area_inei: str = '01') -> None:
    """Persiste (upsert) los períodos de reajuste del proyecto."""
    conn = get_db()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO formula_periodos "
            "(proyecto_id, oferta_anio, oferta_mes, reajuste_anio, reajuste_mes, area_inei) "
            "VALUES (?,?,?,?,?,?)",
            (proyecto_id, int(oferta_anio), int(oferta_mes),
             int(reajuste_anio), int(reajuste_mes), str(area_inei))
        )
        conn.commit()
    finally:
        conn.close()


def calcular_reajuste_k(proyecto_id: int,
                        oferta_anio: int | None = None,
                        oferta_mes: int | None = None,
                        reajuste_anio: int | None = None,
                        reajuste_mes: int | None = None,
                        area_inei: str | None = None) -> dict:
    """Calcula el coeficiente K de reajuste con los valores INEI cargados.

    Fórmula:  K = Σ k_i · (I_r / I_o)  donde I_r es el valor del índice en el
    período de reajuste y I_o en el período de oferta.

    Si algún parámetro es None, usa el guardado en ``formula_periodos`` o el
    default de ``cargar_periodos``.

    Retorna::

        {
            'ok': bool,
            'k_total': float,
            'oferta':    {'anio': int, 'mes': int},
            'reajuste':  {'anio': int, 'mes': int},
            'area':      str,
            'detalle':   [{
                'simbolo': str, 'indice_inei': str, 'descripcion': str,
                'coeficiente': float,
                'valor_o': float|None, 'valor_r': float|None,
                'ratio':   float|None,
                'aporte':  float|None,    # k × ratio
                'falta_dato': bool,
            }, ...],
            'monomios_sin_datos': int,
        }
    """
    from core.indices_inei import obtener_valor

    per = cargar_periodos(proyecto_id)
    oa = oferta_anio   or per['oferta_anio']
    om = oferta_mes    or per['oferta_mes']
    ra = reajuste_anio or per['reajuste_anio']
    rm = reajuste_mes  or per['reajuste_mes']
    area = area_inei   or per['area_inei']

    monomios = cargar_monomios(proyecto_id)
    detalle = []
    k_total = 0.0
    sin_datos = 0
    for m in monomios:
        cod = (m.get('indice_inei') or '').strip().zfill(2)[:2]
        k = float(m.get('coeficiente') or 0)
        vo = obtener_valor(cod, oa, om, area) if cod else None
        vr = obtener_valor(cod, ra, rm, area) if cod else None
        ratio = (vr / vo) if (vo and vr and vo > 0) else None
        aporte = (k * ratio) if ratio is not None else None
        falta = (ratio is None)
        if not falta:
            k_total += aporte
        else:
            sin_datos += 1
        detalle.append({
            'simbolo':     m.get('simbolo'),
            'indice_inei': cod,
            'descripcion': m.get('descripcion') or '',
            'coeficiente': k,
            'valor_o':     vo,
            'valor_r':     vr,
            'ratio':       ratio,
            'aporte':      aporte,
            'falta_dato':  falta,
        })

    return {
        'ok':       True,
        'k_total':  round(k_total, 4),
        'oferta':   {'anio': oa, 'mes': om},
        'reajuste': {'anio': ra, 'mes': rm},
        'area':     area,
        'detalle':  detalle,
        'monomios_sin_datos': sin_datos,
    }
