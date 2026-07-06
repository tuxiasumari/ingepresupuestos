# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""core.catalogos_json — Import/Export en JSON del Catálogo de Insumos y de
la Biblioteca de Costos Unitarios.

Equivalente a la funcionalidad "Importación/Exportación del Diccionario de
Elementos (JSON)" de Delphin Express 2026.

Diseño:
    - Cada recurso se identifica por su ``codigo`` (clave natural de 7
      dígitos con prefijo INEI).
    - Cada CU se identifica por la combinación
      (``descripcion``, ``unidad``, ``grupo``) — no hay clave natural.
    - Los ACU items dentro de un CU referencian recursos por ``codigo``;
      si el código no existe en el destino, se crea el recurso con los
      datos embebidos (``recurso_descripcion``, ``recurso_tipo``, etc.).
    - Estrategia de import por defecto: **MERGE** (actualiza existentes,
      inserta nuevos). El llamador puede pedir "insert-only" si prefiere
      duplicar.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from core.database import get_db


# ── Catálogo de Insumos (recursos) ───────────────────────────────────────────
def exportar_recursos_json(filepath: str,
                            filtro_ids: list[int] | None = None) -> int:
    """Exporta el catálogo de recursos a JSON.

    Si ``filtro_ids`` es no-None, exporta solo esos. Retorna el número de
    recursos exportados.
    """
    conn = get_db()
    try:
        if filtro_ids:
            placeholders = ','.join('?' * len(filtro_ids))
            rows = conn.execute(
                f"SELECT codigo, descripcion, tipo, unidad, precio, indice_inei "
                f"FROM recursos WHERE id IN ({placeholders}) "
                f"ORDER BY tipo, codigo",
                filtro_ids
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT codigo, descripcion, tipo, unidad, precio, indice_inei "
                "FROM recursos ORDER BY tipo, codigo"
            ).fetchall()
    finally:
        conn.close()

    items = []
    for r in rows:
        items.append({
            'codigo':      r['codigo'] or '',
            'descripcion': r['descripcion'] or '',
            'tipo':        r['tipo'] or 'MAT',
            'unidad':      r['unidad'] or '',
            'precio':      float(r['precio'] or 0),
            'indice_inei': r['indice_inei'] or '',
        })

    payload = {
        'version':      1,
        'tipo':         'catalogo_insumos',
        'exportado_en': datetime.now().isoformat(timespec='seconds'),
        'n_items':      len(items),
        'recursos':     items,
    }
    Path(filepath).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding='utf-8'
    )
    return len(items)


def importar_recursos_json(filepath: str,
                            modo: str = 'merge') -> dict:
    """Importa recursos desde JSON. Retorna dict con n_creados, n_actualizados,
    n_ignorados, n_total. ``modo`` puede ser:

        - 'merge'        (default): existentes se actualizan por código
        - 'solo_nuevos'  : ignora los que ya existen por código
    """
    try:
        payload = json.loads(Path(filepath).read_text(encoding='utf-8'))
    except Exception as e:
        return {'ok': False, 'msg': f"No se pudo leer JSON: {e}",
                'n_creados': 0, 'n_actualizados': 0, 'n_ignorados': 0}

    if payload.get('tipo') != 'catalogo_insumos':
        return {'ok': False,
                'msg': f"El archivo no es de tipo catalogo_insumos "
                       f"(tipo='{payload.get('tipo')}')",
                'n_creados': 0, 'n_actualizados': 0, 'n_ignorados': 0}

    recursos = payload.get('recursos') or []
    n_creados = 0
    n_actualizados = 0
    n_ignorados = 0
    conn = get_db()
    try:
        for r in recursos:
            codigo = str(r.get('codigo') or '').strip()
            desc = str(r.get('descripcion') or '').strip()
            if not desc:
                n_ignorados += 1
                continue
            tipo = (r.get('tipo') or 'MAT').upper()
            if tipo not in ('MO', 'MAT', 'EQ'):
                tipo = 'MAT'
            unidad = str(r.get('unidad') or '')
            precio = float(r.get('precio') or 0)
            inei = str(r.get('indice_inei') or '').zfill(2)[:2] if r.get('indice_inei') else ''

            existente = None
            if codigo:
                existente = conn.execute(
                    "SELECT id FROM recursos WHERE codigo=?", (codigo,)
                ).fetchone()

            if existente:
                if modo == 'solo_nuevos':
                    n_ignorados += 1
                    continue
                conn.execute(
                    "UPDATE recursos SET descripcion=?, tipo=?, unidad=?, "
                    "precio=?, indice_inei=? WHERE id=?",
                    (desc, tipo, unidad, precio, inei, existente['id'])
                )
                n_actualizados += 1
            else:
                conn.execute(
                    "INSERT INTO recursos (codigo, descripcion, tipo, unidad, "
                    "precio, indice_inei) VALUES (?,?,?,?,?,?)",
                    (codigo, desc, tipo, unidad, precio, inei)
                )
                n_creados += 1
        conn.commit()
    finally:
        conn.close()

    return {
        'ok':             True,
        'n_creados':      n_creados,
        'n_actualizados': n_actualizados,
        'n_ignorados':    n_ignorados,
        'n_total':        len(recursos),
        'msg':            (f"{n_creados} nuevos · {n_actualizados} "
                           f"actualizados · {n_ignorados} ignorados"),
    }


# ── Biblioteca de Costos Unitarios ───────────────────────────────────────────
def exportar_biblioteca_json(filepath: str,
                              filtro_ids: list[int] | None = None) -> int:
    """Exporta la biblioteca de CU a JSON. Cada CU incluye sus ACU items
    con el código del recurso (no el id local).

    Si ``filtro_ids`` es no-None, exporta solo esos CU. Retorna el número
    exportado.
    """
    conn = get_db()
    try:
        if filtro_ids:
            placeholders = ','.join('?' * len(filtro_ids))
            cu_rows = conn.execute(
                f"SELECT id, descripcion, unidad, rendimiento, costo_unitario, "
                f"grupo, especificaciones, usos "
                f"FROM biblioteca_cu WHERE id IN ({placeholders}) "
                f"ORDER BY grupo, descripcion",
                filtro_ids
            ).fetchall()
        else:
            cu_rows = conn.execute(
                "SELECT id, descripcion, unidad, rendimiento, costo_unitario, "
                "grupo, especificaciones, usos "
                "FROM biblioteca_cu ORDER BY grupo, descripcion"
            ).fetchall()

        items = []
        for cu in cu_rows:
            acu_rows = conn.execute(
                """SELECT i.cuadrilla, i.cantidad, i.precio AS bib_precio,
                          r.codigo, r.descripcion, r.tipo, r.unidad, r.precio,
                          r.indice_inei
                   FROM biblioteca_acu_items i
                   JOIN recursos r ON r.id = i.recurso_id
                   WHERE i.cu_id = ?
                   ORDER BY CASE r.tipo WHEN 'MO' THEN 1 WHEN 'MAT' THEN 2 ELSE 3 END,
                            r.descripcion""",
                (cu['id'],)
            ).fetchall()
            acu_items = []
            for a in acu_rows:
                acu_items.append({
                    'recurso_codigo':       a['codigo'] or '',
                    'recurso_descripcion':  a['descripcion'] or '',
                    'recurso_tipo':         a['tipo'] or 'MAT',
                    'recurso_unidad':       a['unidad'] or '',
                    'recurso_precio':       float(a['precio'] or 0),
                    'recurso_indice_inei':  a['indice_inei'] or '',
                    'cuadrilla':            float(a['cuadrilla'] or 0),
                    'cantidad':             float(a['cantidad'] or 0),
                    'precio':               (float(a['bib_precio'])
                                             if a['bib_precio'] is not None else None),
                })
            items.append({
                'descripcion':       cu['descripcion'] or '',
                'unidad':            cu['unidad'] or '',
                'rendimiento':       float(cu['rendimiento'] or 1),
                'costo_unitario':    float(cu['costo_unitario'] or 0),
                'grupo':             cu['grupo'] or '',
                'especificaciones':  cu['especificaciones'] or '',
                'acu_items':         acu_items,
            })
    finally:
        conn.close()

    payload = {
        'version':      1,
        'tipo':         'biblioteca_cu',
        'exportado_en': datetime.now().isoformat(timespec='seconds'),
        'n_items':      len(items),
        'n_acu_total':  sum(len(it['acu_items']) for it in items),
        'cu':           items,
    }
    Path(filepath).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding='utf-8'
    )
    return len(items)


def importar_biblioteca_json(filepath: str,
                              modo: str = 'merge') -> dict:
    """Importa la biblioteca de CU desde JSON. Resuelve los recursos por
    código (los crea si no existen). Retorna dict con conteos.

    ``modo``:
        - 'merge'       : actualiza CU existentes que matchean por
                          (descripcion, unidad, grupo). Crea nuevos
                          los que no matcheen.
        - 'solo_nuevos' : ignora los CU que ya existen, solo inserta nuevos
        - 'duplicar'    : siempre inserta, no hace dedup (genera duplicados)
    """
    try:
        payload = json.loads(Path(filepath).read_text(encoding='utf-8'))
    except Exception as e:
        return {'ok': False, 'msg': f"No se pudo leer JSON: {e}",
                'n_creados': 0, 'n_actualizados': 0, 'n_ignorados': 0,
                'n_recursos_creados': 0}

    if payload.get('tipo') != 'biblioteca_cu':
        return {'ok': False,
                'msg': f"El archivo no es de tipo biblioteca_cu "
                       f"(tipo='{payload.get('tipo')}')",
                'n_creados': 0, 'n_actualizados': 0, 'n_ignorados': 0,
                'n_recursos_creados': 0}

    cu_items = payload.get('cu') or []
    n_creados = 0
    n_actualizados = 0
    n_ignorados = 0
    n_recursos_creados = 0

    conn = get_db()
    try:
        for cu in cu_items:
            desc = str(cu.get('descripcion') or '').strip()
            if not desc:
                n_ignorados += 1
                continue
            unidad = str(cu.get('unidad') or '').strip()
            rendimiento = float(cu.get('rendimiento') or 1)
            costo = float(cu.get('costo_unitario') or 0)
            grupo = str(cu.get('grupo') or '').strip()
            specs = str(cu.get('especificaciones') or '')

            # Resolver existencia
            existente = None
            if modo in ('merge', 'solo_nuevos'):
                existente = conn.execute(
                    "SELECT id FROM biblioteca_cu "
                    "WHERE descripcion=? AND unidad=? AND grupo=?",
                    (desc, unidad, grupo)
                ).fetchone()

            if existente and modo == 'solo_nuevos':
                n_ignorados += 1
                continue

            if existente and modo == 'merge':
                cu_id = existente['id']
                conn.execute(
                    "UPDATE biblioteca_cu SET rendimiento=?, costo_unitario=?, "
                    "especificaciones=? WHERE id=?",
                    (rendimiento, costo, specs, cu_id)
                )
                # Limpiar ACU items existentes (los reemplazamos completamente)
                conn.execute(
                    "DELETE FROM biblioteca_acu_items WHERE cu_id=?",
                    (cu_id,)
                )
                n_actualizados += 1
            else:
                cur = conn.execute(
                    "INSERT INTO biblioteca_cu "
                    "(descripcion, unidad, rendimiento, costo_unitario, grupo, "
                    "especificaciones, usos) VALUES (?,?,?,?,?,?,0)",
                    (desc, unidad, rendimiento, costo, grupo, specs)
                )
                cu_id = cur.lastrowid
                n_creados += 1

            # Resolver/crear recursos y agregar ACU items
            for ai in (cu.get('acu_items') or []):
                cod = str(ai.get('recurso_codigo') or '').strip()
                if not cod:
                    continue
                rec = conn.execute(
                    "SELECT id FROM recursos WHERE codigo=?", (cod,)
                ).fetchone()
                if not rec:
                    # Crear recurso desde los datos embebidos
                    r_desc = str(ai.get('recurso_descripcion') or '').strip()
                    if not r_desc:
                        continue
                    r_tipo = (ai.get('recurso_tipo') or 'MAT').upper()
                    if r_tipo not in ('MO', 'MAT', 'EQ'):
                        r_tipo = 'MAT'
                    r_unidad = str(ai.get('recurso_unidad') or '')
                    r_precio = float(ai.get('recurso_precio') or 0)
                    r_inei = (str(ai.get('recurso_indice_inei') or '')
                              .zfill(2)[:2])
                    cur = conn.execute(
                        "INSERT INTO recursos "
                        "(codigo, descripcion, tipo, unidad, precio, indice_inei) "
                        "VALUES (?,?,?,?,?,?)",
                        (cod, r_desc, r_tipo, r_unidad, r_precio, r_inei)
                    )
                    rec_id = cur.lastrowid
                    n_recursos_creados += 1
                else:
                    rec_id = rec['id']

                precio = ai.get('precio')
                if precio in (None, '', 0):
                    precio = ai.get('recurso_precio')
                conn.execute(
                    "INSERT INTO biblioteca_acu_items "
                    "(cu_id, recurso_id, cuadrilla, cantidad, precio) "
                    "VALUES (?,?,?,?,?)",
                    (cu_id, rec_id,
                     float(ai.get('cuadrilla') or 0),
                     float(ai.get('cantidad') or 0),
                     float(precio) if precio not in (None, '') else None)
                )

        conn.commit()
    finally:
        conn.close()

    return {
        'ok': True,
        'n_creados':           n_creados,
        'n_actualizados':      n_actualizados,
        'n_ignorados':         n_ignorados,
        'n_recursos_creados':  n_recursos_creados,
        'n_total':             len(cu_items),
        'msg': (f"{n_creados} CU nuevos · {n_actualizados} actualizados · "
                f"{n_ignorados} ignorados · "
                f"{n_recursos_creados} recursos auto-creados"),
    }
