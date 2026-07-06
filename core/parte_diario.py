# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""Control de Obra · Fase A — Parte diario / cuaderno de obra.

El residente registra, por día, el metrado ejecutado por partida (más adelante:
incidencias, MO/equipo presente e insumos consumidos). El metrado del día se
ACUMULA (push) hacia el ``metrado_periodo`` de la valorización cuyo período
contiene la fecha, marcándolo con ``origen='diario'``.

Modelo MIXTO (decisión 2026-06-24): el parte diario es opcional. Si una partida
no tiene partes en el período, su metrado del mes se sigue tecleando a mano en la
grilla de Valorizaciones (``origen='manual'``). Cuando hay partes, la celda
mensual pasa a ser de solo lectura y la alimenta el cuaderno.

SOLO LEE del presupuesto/ACU, nunca lo modifica. Ver `[[project_modulo_ejecucion_obra]]`.
"""

import math

from core.database import get_db


# ── Sincronización parte diario → valorización ───────────────────────────────

def _sincronizar_val(conn, val):
    """Recalcula el ``metrado_periodo`` de las partidas de una valorización a
    partir de los partes diarios cuya fecha cae en su período. Usa la conexión
    abierta (no hace commit). Las partidas con partes quedan ``origen='diario'``;
    las que dejaron de tener partes vuelven a ``'manual'`` (conservan su valor)."""
    desde = val['periodo_desde'] or ''
    hasta = val['periodo_hasta'] or ''
    if not desde or not hasta:
        return   # sin período no se puede mapear por fecha
    pid = val['proyecto_id']
    rows = conn.execute(
        "SELECT pdm.partida_id AS pid, SUM(pdm.metrado_dia) AS m "
        "FROM parte_diario_metrado pdm "
        "JOIN parte_diario pd ON pd.id = pdm.parte_id "
        "WHERE pd.proyecto_id=? AND pd.fecha>=? AND pd.fecha<=? "
        "GROUP BY pdm.partida_id", (pid, desde, hasta)
    ).fetchall()
    con_partes = set()
    for r in rows:
        con_partes.add(r['pid'])
        conn.execute(
            "INSERT INTO valorizacion_detalle "
            "(valorizacion_id, partida_id, metrado_periodo, origen) "
            "VALUES (?,?,?, 'diario') "
            "ON CONFLICT(valorizacion_id, partida_id) DO UPDATE SET "
            "metrado_periodo=excluded.metrado_periodo, origen='diario'",
            (val['id'], r['pid'], float(r['m'] or 0))
        )
    # Las que eran 'diario' y ya no tienen partes → vuelven a 'manual'.
    diarios = conn.execute(
        "SELECT partida_id FROM valorizacion_detalle "
        "WHERE valorizacion_id=? AND origen='diario'", (val['id'],)
    ).fetchall()
    for d in diarios:
        if d['partida_id'] not in con_partes:
            conn.execute(
                "UPDATE valorizacion_detalle SET origen='manual' "
                "WHERE valorizacion_id=? AND partida_id=?",
                (val['id'], d['partida_id']))


def _val_que_cubre(conn, proyecto_id, fecha):
    """Valorización (fila) cuyo período contiene ``fecha``, o None."""
    return conn.execute(
        "SELECT * FROM valorizaciones WHERE proyecto_id=? AND periodo_desde!='' "
        "AND periodo_hasta!='' AND periodo_desde<=? AND periodo_hasta>=? "
        "ORDER BY numero LIMIT 1", (proyecto_id, fecha, fecha)
    ).fetchone()


def sincronizar_valorizacion(val_id: int):
    """Recalcula una valorización desde los partes diarios (se llama al crearla
    o cambiar su período, para arrastrar partes ya registrados)."""
    conn = get_db()
    try:
        val = conn.execute("SELECT * FROM valorizaciones WHERE id=?",
                           (val_id,)).fetchone()
        if val:
            _sincronizar_val(conn, val)
            conn.commit()
    finally:
        conn.close()


# ── Cabecera del parte: crear / listar / cerrar / eliminar ───────────────────

def crear_parte(proyecto_id: int, fecha: str) -> int:
    """Crea (o devuelve, si ya existe) el parte del día. Un parte por fecha."""
    conn = get_db()
    try:
        ex = conn.execute(
            "SELECT id FROM parte_diario WHERE proyecto_id=? AND fecha=?",
            (proyecto_id, fecha)).fetchone()
        if ex:
            return ex['id']
        cur = conn.execute(
            "INSERT INTO parte_diario (proyecto_id, fecha) VALUES (?,?)",
            (proyecto_id, fecha))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_partes(proyecto_id: int) -> list[dict]:
    """Partes del proyecto ordenados por fecha (con conteo de partidas con metrado)."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT pd.*, "
            "(SELECT COUNT(*) FROM parte_diario_metrado m "
            "  WHERE m.parte_id=pd.id AND m.metrado_dia>0) AS n_partidas "
            "FROM parte_diario pd WHERE pd.proyecto_id=? ORDER BY pd.fecha",
            (proyecto_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_parte(parte_id: int) -> dict | None:
    conn = get_db()
    try:
        r = conn.execute("SELECT * FROM parte_diario WHERE id=?",
                         (parte_id,)).fetchone()
        return dict(r) if r else None
    finally:
        conn.close()


def set_observaciones(parte_id: int, texto: str) -> bool:
    conn = get_db()
    try:
        v = conn.execute("SELECT estado FROM parte_diario WHERE id=?",
                         (parte_id,)).fetchone()
        if not v or v['estado'] == 'cerrado':
            return False
        conn.execute("UPDATE parte_diario SET observaciones=? WHERE id=?",
                     (texto or '', parte_id))
        conn.commit()
        return True
    finally:
        conn.close()


def cerrar_parte(parte_id: int):
    conn = get_db()
    try:
        conn.execute("UPDATE parte_diario SET estado='cerrado' WHERE id=?",
                     (parte_id,))
        conn.commit()
    finally:
        conn.close()


def reabrir_parte(parte_id: int):
    conn = get_db()
    try:
        conn.execute("UPDATE parte_diario SET estado='abierto' WHERE id=?",
                     (parte_id,))
        conn.commit()
    finally:
        conn.close()


def eliminar_parte(parte_id: int) -> bool:
    """Elimina el parte (y su detalle, por cascade) y re-sincroniza la
    valorización que lo contenía. Solo si está abierto."""
    conn = get_db()
    try:
        pd = conn.execute("SELECT proyecto_id, fecha, estado FROM parte_diario "
                         "WHERE id=?", (parte_id,)).fetchone()
        if not pd or pd['estado'] == 'cerrado':
            return False
        val = _val_que_cubre(conn, pd['proyecto_id'], pd['fecha'])
        conn.execute("DELETE FROM parte_diario WHERE id=?", (parte_id,))
        if val:
            _sincronizar_val(conn, val)
        conn.commit()
        return True
    finally:
        conn.close()


# ── Detalle del parte: metrado ejecutado del día ─────────────────────────────

def set_metrado_dia(parte_id: int, partida_id: int, metrado) -> bool:
    """Registra el metrado ejecutado de una partida en este parte y arrastra el
    cambio a la valorización del período. Metrado ≤ 0 borra la fila."""
    conn = get_db()
    try:
        pd = conn.execute("SELECT proyecto_id, fecha, estado FROM parte_diario "
                         "WHERE id=?", (parte_id,)).fetchone()
        if not pd or pd['estado'] == 'cerrado':
            return False
        m = float(metrado or 0)
        if m <= 0:
            conn.execute("DELETE FROM parte_diario_metrado "
                         "WHERE parte_id=? AND partida_id=?",
                         (parte_id, partida_id))
        else:
            conn.execute(
                "INSERT INTO parte_diario_metrado (parte_id, partida_id, metrado_dia) "
                "VALUES (?,?,?) ON CONFLICT(parte_id, partida_id) "
                "DO UPDATE SET metrado_dia=excluded.metrado_dia",
                (parte_id, partida_id, m))
        val = _val_que_cubre(conn, pd['proyecto_id'], pd['fecha'])
        if val:
            _sincronizar_val(conn, val)
        conn.commit()
        return True
    finally:
        conn.close()


_DIM_COLS = ('n_estructuras', 'n_elementos', 'area', 'largo', 'ancho', 'alto')


def _parcial_dims(fila: dict) -> float:
    """Parcial = producto de las dimensiones LLENAS — mismo criterio que la
    planilla de metrados del proyecto (`metrados_detalle`). Las celdas vacías y
    los **0** se ignoran (en la planilla del proyecto las vacías se guardan como
    0; tomarlas como factor anularía el parcial)."""
    parc = 1.0
    usadas = 0
    for c in _DIM_COLS:
        v = fila.get(c)
        if v is not None and float(v) != 0:
            parc *= float(v)
            usadas += 1
    return parc if usadas else 0.0


def get_metrado_detalle_proyecto(partida_id: int) -> tuple[list[dict], float]:
    """Planilla de metrados del PROYECTO para una partida (referencia, solo
    lectura). Devuelve (filas, total)."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT descripcion, n_estructuras, n_elementos, area, largo, ancho, "
            "alto, parcial FROM metrados_detalle WHERE partida_id=? ORDER BY orden, id",
            (partida_id,)).fetchall()
        filas = [dict(r) for r in rows]
        total = sum((r['parcial'] or 0) for r in filas)
        return filas, total
    finally:
        conn.close()


def get_metrado_detalle_dia(parte_id: int, partida_id: int) -> tuple[list[dict], float]:
    """Planilla de metrados del DÍA para una partida. Devuelve (filas, total)."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT descripcion, n_estructuras, n_elementos, area, largo, ancho, "
            "alto, parcial FROM parte_diario_metrado_detalle "
            "WHERE parte_id=? AND partida_id=? ORDER BY orden, id",
            (parte_id, partida_id)).fetchall()
        filas = [dict(r) for r in rows]
        total = sum((r['parcial'] or 0) for r in filas)
        return filas, total
    finally:
        conn.close()


def claves_con_detalle(proyecto_id: int) -> set:
    """Conjunto de (parte_id, partida_id) que tienen planilla de metrados del día
    (para marcar esas celdas de la grilla como derivadas/solo-lectura)."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT DISTINCT d.parte_id, d.partida_id "
            "FROM parte_diario_metrado_detalle d "
            "JOIN parte_diario pd ON pd.id = d.parte_id "
            "WHERE pd.proyecto_id=?", (proyecto_id,)).fetchall()
        return {(r['parte_id'], r['partida_id']) for r in rows}
    finally:
        conn.close()


def save_metrado_detalle_dia(parte_id: int, partida_id: int,
                             filas: list[dict]) -> float | None:
    """Reemplaza la planilla del día de una partida y fija su `metrado_dia` =
    Σ parcial, arrastrándolo a la valorización del período. Devuelve el total, o
    None si el parte está cerrado. Filas vacías (sin descripción ni dimensiones)
    se ignoran."""
    conn = get_db()
    try:
        pd = conn.execute("SELECT proyecto_id, fecha, estado FROM parte_diario "
                         "WHERE id=?", (parte_id,)).fetchone()
        if not pd or pd['estado'] == 'cerrado':
            return None
        conn.execute("DELETE FROM parte_diario_metrado_detalle "
                     "WHERE parte_id=? AND partida_id=?", (parte_id, partida_id))
        total = 0.0
        orden = 0
        for f in filas:
            tiene = (f.get('descripcion') or '').strip() or any(
                f.get(c) is not None for c in _DIM_COLS)
            if not tiene:
                continue
            parc = _parcial_dims(f)
            total += parc
            orden += 1
            conn.execute(
                "INSERT INTO parte_diario_metrado_detalle "
                "(parte_id, partida_id, orden, descripcion, n_estructuras, "
                "n_elementos, area, largo, ancho, alto, parcial) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (parte_id, partida_id, orden, (f.get('descripcion') or ''),
                 f.get('n_estructuras'), f.get('n_elementos'), f.get('area'),
                 f.get('largo'), f.get('ancho'), f.get('alto'), parc))
        # Metrado del día = total (0 → borrar la fila resumen).
        if total <= 0:
            conn.execute("DELETE FROM parte_diario_metrado "
                         "WHERE parte_id=? AND partida_id=?", (parte_id, partida_id))
        else:
            conn.execute(
                "INSERT INTO parte_diario_metrado (parte_id, partida_id, metrado_dia) "
                "VALUES (?,?,?) ON CONFLICT(parte_id, partida_id) "
                "DO UPDATE SET metrado_dia=excluded.metrado_dia",
                (parte_id, partida_id, total))
        val = _val_que_cubre(conn, pd['proyecto_id'], pd['fecha'])
        if val:
            _sincronizar_val(conn, val)
        conn.commit()
        return total
    finally:
        conn.close()


# ── Fase B: mano de obra e insumos del día (estimados desde el ACU) ──────────

_TIPO_CLASE = {'MO': 'mo', 'MAT': 'mat', 'EQ': 'eq', 'SC': 'sc'}


def _redondear_pedido(cantidad, unidad) -> float:
    """Redondea hacia arriba las unidades discretas (bolsa, varilla, galón, und…)
    reutilizando la regla de los requerimientos; deja decimales en las continuas
    (kg, m³, ml). Import perezoso para evitar ciclos."""
    from core.requerimientos import redondear_para_pedido
    return round(float(redondear_para_pedido(cantidad, unidad) or 0), 2)


def estimar_consumo_dia(parte_id: int, enteros: bool = False) -> dict[str, list[dict]]:
    """Estima, desde el ACU y el metrado del día, los recursos por clase.

    - mano de obra ('mo') = Σ cuadrilla · metrado_día / rendimiento, REDONDEADA
      HACIA ARRIBA a días enteros (unidad «día»): en el cuaderno la MO se anota
      por personas/jornadas enteras (ej. «01 Oficial, 11 Peones»), no en
      fracciones de hora-hombre.
    - materiales ('mat'), equipos ('eq'), servicios ('sc') = Σ cantidad_ACU ·
      metrado_día, redondeados a 2 decimales. Se omiten los overheads (unidad «%»).
    Si ``enteros=True``, MAT/EQ/SC se redondean a unidades enteras de pedido
    (bolsas, varillas, galones, und…) igual que en los requerimientos, dejando
    decimales solo en las unidades continuas (kg, m³, ml).
    Devuelve ``{'mo':[...], 'mat':[...], 'eq':[...], 'sc':[...]}`` (cada fila
    ``{recurso_id, descripcion, unidad, cantidad}`` agregada por recurso). Es un
    estimado base: el residente edita y agrega lo que falte (maestro de obra,
    topógrafo, herramientas, etc.).
    """
    conn = get_db()
    try:
        metr = conn.execute(
            "SELECT partida_id, metrado_dia FROM parte_diario_metrado "
            "WHERE parte_id=? AND metrado_dia>0", (parte_id,)).fetchall()
        buckets = {'mo': {}, 'mat': {}, 'eq': {}, 'sc': {}}
        for m in metr:
            part = conn.execute("SELECT rendimiento FROM partidas WHERE id=?",
                               (m['partida_id'],)).fetchone()
            rend = (part['rendimiento'] if part and part['rendimiento'] else 1) or 1
            M = m['metrado_dia'] or 0
            items = conn.execute(
                "SELECT ai.recurso_id, ai.cuadrilla, ai.cantidad, r.descripcion, "
                "r.unidad, r.tipo FROM acu_items ai "
                "JOIN recursos r ON r.id = ai.recurso_id "
                "WHERE ai.partida_id=?", (m['partida_id'],)).fetchall()
            for it in items:
                if (it['unidad'] or '').strip().startswith('%'):
                    continue   # overhead, no es recurso físico
                clase = _TIPO_CLASE.get(it['tipo'], 'mat')
                if clase == 'mo':
                    cu = it['cuadrilla'] or 0
                    aporte = (cu / rend * M) if cu else (it['cantidad'] or 0) * M
                else:
                    aporte = (it['cantidad'] or 0) * M
                d = buckets[clase]
                k = it['recurso_id']
                if k not in d:
                    d[k] = {'recurso_id': k, 'descripcion': it['descripcion'],
                            'unidad': it['unidad'] or '', 'cantidad': 0.0}
                d[k]['cantidad'] += aporte
        # MO → días enteros hacia arriba (0.25→1, 5.5→6), unidad «día».
        for x in buckets['mo'].values():
            c = x['cantidad']
            x['cantidad'] = float(math.ceil(c - 1e-9)) if c > 0 else 0.0
            x['unidad'] = 'día'
        # Materiales/equipos/servicios → cantidad real (2 decimales) o redondeada
        # a unidades enteras de pedido si enteros=True.
        for clase in ('mat', 'eq', 'sc'):
            for x in buckets[clase].values():
                x['cantidad'] = (_redondear_pedido(x['cantidad'], x['unidad'])
                                 if enteros else round(x['cantidad'], 2))
        orden = lambda x: (x['descripcion'] or '')
        return {clase: sorted(d.values(), key=orden)
                for clase, d in buckets.items()}
    finally:
        conn.close()


def estimar_consumo_requerimientos(parte_id: int, req_ids: list,
                                   enteros: bool = False) -> dict[str, list[dict]]:
    """Estima el consumo del día con las CANTIDADES del metrado del día (ACU ×
    metrado, proporcional a lo realmente ejecutado), pero limitado a los insumos
    que figuran en los Requerimientos seleccionados.

    Es decir: el requerimiento decide QUÉ insumos registrar; el metrado del día
    decide CUÁNTO. Así, 3 m³ de concreto dan las bolsas de cemento de ESE metrado
    (no el total pedido del proyecto), y solo entran insumos que se hayan
    requerido (no, p. ej., accesorios de tubería si no se trabajó tubería). Para
    cantidades enteras de pedido usar ``enteros=True``.

    La mano de obra se deriva del metrado del día (los requerimientos no llevan
    MO). Sin requerimientos seleccionados equivale a estimar del metrado.
    """
    from core import requerimientos as RQ
    base = estimar_consumo_dia(parte_id, enteros=enteros)
    if not req_ids:
        return base
    # Conjunto de insumos pedidos en los requerimientos elegidos (whitelist).
    pedidos = set()
    for clase in ('mat', 'eq', 'sc'):
        for rid in req_ids:
            for f in RQ.get_detalle(rid, clase):
                rec = f.get('recurso_id')
                if rec is not None:
                    pedidos.add(rec)
    # Conserva del estimado del día solo los insumos que se hayan requerido.
    for clase in ('mat', 'eq', 'sc'):
        base[clase] = [x for x in base[clase] if x.get('recurso_id') in pedidos]
    return base


def get_actividades_dia(parte_id: int) -> list[dict]:
    """Partidas con metrado ejecutado en este parte (las «actividades realizadas»
    del día), con su metrado. Para armar el asiento del cuaderno."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT p.item, p.descripcion, p.unidad, m.metrado_dia "
            "FROM parte_diario_metrado m JOIN partidas p ON p.id = m.partida_id "
            "WHERE m.parte_id=? AND m.metrado_dia>0 ORDER BY p.item",
            (parte_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_recursos_dia(parte_id: int, clase: str) -> list[dict]:
    """Recursos registrados del día por clase ('mo' | 'insumo')."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT recurso_id, descripcion, unidad, cantidad FROM "
            "parte_diario_recurso WHERE parte_id=? AND clase=? ORDER BY orden, id",
            (parte_id, clase)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def save_recursos_dia(parte_id: int, clase: str, filas: list[dict]) -> bool:
    """Reemplaza los recursos del día de una clase. Filas vacías se ignoran.
    Devuelve False si el parte está cerrado."""
    conn = get_db()
    try:
        pd = conn.execute("SELECT estado FROM parte_diario WHERE id=?",
                         (parte_id,)).fetchone()
        if not pd or pd['estado'] == 'cerrado':
            return False
        conn.execute("DELETE FROM parte_diario_recurso WHERE parte_id=? AND clase=?",
                     (parte_id, clase))
        orden = 0
        for f in filas:
            desc = (f.get('descripcion') or '').strip()
            cant = f.get('cantidad')
            if not desc and not cant:
                continue
            orden += 1
            conn.execute(
                "INSERT INTO parte_diario_recurso (parte_id, clase, recurso_id, "
                "descripcion, unidad, cantidad, orden) VALUES (?,?,?,?,?,?,?)",
                (parte_id, clase, f.get('recurso_id'), desc,
                 (f.get('unidad') or ''), float(cant or 0), orden))
        conn.commit()
        return True
    finally:
        conn.close()


_CLASE_TIPO = {'mat': 'MAT', 'eq': 'EQ', 'sc': 'SC'}


def _resolver_recurso_manual(conn, descripcion: str, unidad: str, tipo: str) -> int:
    """Resuelve (o crea) un recurso del catálogo para un insumo escrito a mano en
    el cuaderno, reutilizando por (tipo, descripción, unidad) — misma política que
    los importadores. Sirve para que el insumo manual fluya al Almacén / control
    de materiales, que se llavea por recurso_id."""
    from core.importer import _resolve_recurso
    from core.database import _siguiente_codigo_inei
    codigo = _siguiente_codigo_inei(conn, '00')
    return _resolve_recurso(conn, codigo, descripcion, tipo, unidad or '', 0.0)


def normalizar_recursos_manuales(proyecto_id: int) -> int:
    """Enlaza a un recurso REAL los insumos del cuaderno escritos a mano (sin
    recurso_id) de un proyecto, para que aparezcan en el control de materiales.
    Idempotente (solo toca filas con recurso_id NULL). Devuelve cuántas enlazó."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT pr.id, pr.clase, pr.descripcion, pr.unidad "
            "FROM parte_diario_recurso pr "
            "JOIN parte_diario pd ON pd.id = pr.parte_id "
            "WHERE pd.proyecto_id=? AND pr.recurso_id IS NULL "
            "AND pr.clase IN ('mat','eq','sc') "
            "AND TRIM(COALESCE(pr.descripcion,'')) <> ''",
            (proyecto_id,)).fetchall()
        n = 0
        for r in rows:
            tipo = _CLASE_TIPO.get(r['clase'])
            if not tipo:
                continue
            rid = _resolver_recurso_manual(conn, r['descripcion'],
                                           r['unidad'] or '', tipo)
            conn.execute("UPDATE parte_diario_recurso SET recurso_id=? WHERE id=?",
                         (rid, r['id']))
            n += 1
        if n:
            conn.commit()
        return n
    finally:
        conn.close()


def consumido_acumulado(proyecto_id: int) -> dict[int, float]:
    """{recurso_id: Σ cantidad consumida} sumando los recursos materiales (mat/eq/
    sc) registrados en TODOS los partes diarios del proyecto. La mano de obra no
    entra (no es de almacén). Base del control de saldos de materiales."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT pr.recurso_id, SUM(pr.cantidad) AS cant "
            "FROM parte_diario_recurso pr "
            "JOIN parte_diario pd ON pd.id = pr.parte_id "
            "WHERE pd.proyecto_id=? AND pr.recurso_id IS NOT NULL "
            "AND pr.clase IN ('mat','eq','sc') "
            "GROUP BY pr.recurso_id", (proyecto_id,)).fetchall()
        return {r['recurso_id']: (r['cant'] or 0.0) for r in rows}
    finally:
        conn.close()


def consumo_por_dia(proyecto_id: int, recurso_id: int) -> list[dict]:
    """Movimientos diarios de un insumo (kárdex por día): por fecha, la cantidad
    consumida ese día, ordenados cronológicamente. Suma los partes de la misma
    fecha. Solo materiales/equipos/servicios (mat/eq/sc)."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT pd.fecha, SUM(pr.cantidad) AS cant "
            "FROM parte_diario_recurso pr "
            "JOIN parte_diario pd ON pd.id = pr.parte_id "
            "WHERE pd.proyecto_id=? AND pr.recurso_id=? "
            "AND pr.clase IN ('mat','eq','sc') "
            "GROUP BY pd.fecha ORDER BY pd.fecha", (proyecto_id, recurso_id)).fetchall()
        return [{'fecha': r['fecha'], 'cantidad': (r['cant'] or 0.0)} for r in rows]
    finally:
        conn.close()


def get_metrados_dia(parte_id: int) -> dict[int, float]:
    """{partida_id: metrado_dia} de este parte."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT partida_id, metrado_dia FROM parte_diario_metrado "
            "WHERE parte_id=?", (parte_id,)).fetchall()
        return {r['partida_id']: (r['metrado_dia'] or 0) for r in rows}
    finally:
        conn.close()


def partidas_proyecto(proyecto_id: int) -> list[dict]:
    """Partidas del proyecto (incl. títulos) en orden de ítem, con lo necesario
    para la grilla del cuaderno."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, item, descripcion, unidad, nivel, es_titulo, metrado, "
            "precio_unitario FROM partidas WHERE proyecto_id=? ORDER BY item",
            (proyecto_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
