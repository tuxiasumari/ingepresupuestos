# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""Control de Obra · Almacén — ingresos (entradas) de materiales.

Kárdex de obra: **Entradas** (lo que llega al almacén, por fecha; el material
puede llegar en varias entregas) − **Salidas** (consumo registrado en el cuaderno
de obra) = **Stock**. Aparte se compara con el **Pedido** (requerimientos):
«Por llegar» = Pedido − Ingresado.

Tabla `almacen_ingreso`. Las salidas viven en `parte_diario_recurso` (cuaderno).
Ver `[[project_modulo_ejecucion_obra]]`.
"""

from core.database import get_db


def listar_ingresos(proyecto_id: int, recurso_id: int = None) -> list[dict]:
    """Ingresos del proyecto (o de un insumo), por fecha y luego id."""
    conn = get_db()
    try:
        sql = ("SELECT id, recurso_id, descripcion, unidad, fecha, cantidad, "
               "observacion FROM almacen_ingreso WHERE proyecto_id=? ")
        params = [proyecto_id]
        if recurso_id is not None:
            sql += "AND recurso_id=? "
            params.append(recurso_id)
        sql += "ORDER BY fecha, id"
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def agregar_ingreso(proyecto_id: int, recurso_id, fecha: str, cantidad: float,
                    descripcion: str = '', unidad: str = '',
                    observacion: str = '') -> int:
    """Registra una entrada de material. Devuelve el id creado."""
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO almacen_ingreso (proyecto_id, recurso_id, descripcion, "
            "unidad, fecha, cantidad, observacion) VALUES (?,?,?,?,?,?,?)",
            (proyecto_id, recurso_id, descripcion or '', unidad or '',
             fecha or '', float(cantidad or 0), observacion or ''))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def actualizar_ingreso(ingreso_id: int, fecha: str, cantidad: float,
                       observacion: str = None) -> bool:
    """Modifica fecha, cantidad y (opcional) observación de una entrada."""
    conn = get_db()
    try:
        if observacion is None:
            conn.execute(
                "UPDATE almacen_ingreso SET fecha=?, cantidad=? WHERE id=?",
                (fecha or '', float(cantidad or 0), ingreso_id))
        else:
            conn.execute(
                "UPDATE almacen_ingreso SET fecha=?, cantidad=?, observacion=? "
                "WHERE id=?",
                (fecha or '', float(cantidad or 0), observacion or '', ingreso_id))
        conn.commit()
        return True
    finally:
        conn.close()


def actualizar_observacion(ingreso_id: int, observacion: str) -> bool:
    """Actualiza solo la observación de una entrada (edición inline del kárdex)."""
    conn = get_db()
    try:
        conn.execute("UPDATE almacen_ingreso SET observacion=? WHERE id=?",
                     (observacion or '', ingreso_id))
        conn.commit()
        return True
    finally:
        conn.close()


def eliminar_ingreso(ingreso_id: int) -> bool:
    conn = get_db()
    try:
        conn.execute("DELETE FROM almacen_ingreso WHERE id=?", (ingreso_id,))
        conn.commit()
        return True
    finally:
        conn.close()


def ingresado_acumulado(proyecto_id: int) -> dict:
    """{recurso_id: Σ cantidad ingresada} de todos los ingresos del proyecto."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT recurso_id, SUM(cantidad) AS cant FROM almacen_ingreso "
            "WHERE proyecto_id=? AND recurso_id IS NOT NULL GROUP BY recurso_id",
            (proyecto_id,)).fetchall()
        return {r['recurso_id']: (r['cant'] or 0.0) for r in rows}
    finally:
        conn.close()


def kardex(proyecto_id: int, recurso_id: int) -> list[dict]:
    """Kárdex clásico de un material: por movimiento (fecha) con
    ENTRADA · SALIDA · SALDO corrido + OBSERVACIÓN. Entradas de `almacen_ingreso`
    (con su observación); salidas del consumo del cuaderno. Cada fila:
    ``{fecha, entrada, salida, saldo, observacion}``."""
    from core.parte_diario import consumo_por_dia
    movs = []
    for i in listar_ingresos(proyecto_id, recurso_id):
        movs.append({'fecha': i['fecha'], 'entrada': i['cantidad'] or 0.0,
                     'salida': 0.0, 'observacion': i.get('observacion') or ''})
    for s in consumo_por_dia(proyecto_id, recurso_id):
        movs.append({'fecha': s['fecha'], 'entrada': 0.0,
                     'salida': s['cantidad'] or 0.0, 'observacion': ''})
    # Ordenar por fecha; en la misma fecha la entrada va antes que la salida.
    movs.sort(key=lambda x: (x['fecha'] or '', 0 if x['entrada'] else 1))
    saldo = 0.0
    for mm in movs:
        saldo += (mm['entrada'] or 0.0) - (mm['salida'] or 0.0)
        mm['saldo'] = round(saldo, 2)
    return movs


def movimientos(proyecto_id: int, recurso_id: int) -> list[dict]:
    """Kárdex por día de un insumo: entradas (individuales, con su id) + salidas
    (consumo agregado por fecha del cuaderno), ordenados por fecha (la entrada va
    antes que la salida del mismo día). Cada fila:
    ``{fecha, tipo:'entrada'|'salida', cantidad, ingreso_id}``."""
    from core.parte_diario import consumo_por_dia
    mov = [{'fecha': i['fecha'], 'tipo': 'entrada', 'cantidad': i['cantidad'],
            'ingreso_id': i['id'], 'observacion': i.get('observacion') or ''}
           for i in listar_ingresos(proyecto_id, recurso_id)]
    mov += [{'fecha': s['fecha'], 'tipo': 'salida', 'cantidad': s['cantidad'],
             'ingreso_id': None, 'observacion': ''}
            for s in consumo_por_dia(proyecto_id, recurso_id)]
    mov.sort(key=lambda x: (x['fecha'] or '', 0 if x['tipo'] == 'entrada' else 1))
    return mov
