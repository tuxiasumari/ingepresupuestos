# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""Plantillas de ESTRUCTURA de presupuesto.

Guarda la estructura de un proyecto (o de un sub-presupuesto) como plantilla
reutilizable en otros proyectos: ítems, descripción, unidad, jerarquía, el ACU
(análisis: recursos con cuadrilla/rendimiento/precio de referencia) y las
especificaciones. Por defecto NO incluye metrados (las cantidades son propias de
cada obra).

Reutiliza la serialización/pegado del clipboard de partidas
(`utils.partidas_clipboard`): una plantilla es, en esencia, una entrada de
clipboard con nombre y persistida en la tabla `plantillas`.
"""

import json

from core.database import get_db
import utils.partidas_clipboard as CLIP


def ensure_table(conn=None):
    """Crea la tabla `plantillas` si no existe."""
    propio = conn is None
    conn = conn or get_db()
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS plantillas (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   nombre    TEXT NOT NULL,
                   tipo      TEXT,
                   notas     TEXT,
                   creada_en TEXT DEFAULT (datetime('now','localtime')),
                   payload   TEXT NOT NULL)""")
        if propio:
            conn.commit()
    finally:
        if propio:
            conn.close()


def _subarboles_proyecto(conn, pid: int, sub_ppto_id='__all__') -> list:
    """Serializa las raíces (nivel 1) del proyecto entero (`'__all__'`) o de un
    sub-presupuesto (`None` = el que no tiene sub-presupuesto; o su id)."""
    if sub_ppto_id == '__all__':
        rows = conn.execute(
            "SELECT id FROM partidas WHERE proyecto_id=? AND nivel=1 "
            "ORDER BY sub_presupuesto_id, item", (pid,)).fetchall()
    elif sub_ppto_id is None:
        rows = conn.execute(
            "SELECT id FROM partidas WHERE proyecto_id=? "
            "AND sub_presupuesto_id IS NULL AND nivel=1 ORDER BY item",
            (pid,)).fetchall()
    else:
        rows = conn.execute(
            "SELECT id FROM partidas WHERE proyecto_id=? "
            "AND sub_presupuesto_id=? AND nivel=1 ORDER BY item",
            (pid, sub_ppto_id)).fetchall()
    subarboles = []
    for r in rows:
        ids = CLIP._subarbol_ids(conn, r[0])
        if ids:
            subarboles.append([CLIP._serializar_partida(conn, p) for p in ids])
    return subarboles


def _sin_metrados(subarboles: list) -> list:
    """Quita las cantidades (metrado, planilla de metrados y acero) — deja la
    estructura + ACU + especificaciones."""
    for sub in subarboles:
        for p in sub:
            p['metrado'] = 0
            p['metrados_detalle'] = []
            p['acero_detalle'] = []
    return subarboles


def guardar_plantilla(pid: int, nombre: str, tipo: str = '', notas: str = '',
                      sub_ppto_id='__all__', incluir_metrados: bool = False) -> int:
    """Serializa el proyecto (o un sub-presupuesto) y lo guarda como plantilla.
    Devuelve el id de la plantilla creada."""
    conn = get_db()
    try:
        ensure_table(conn)
        subarboles = _subarboles_proyecto(conn, pid, sub_ppto_id)
        if not incluir_metrados:
            subarboles = _sin_metrados(subarboles)
        n_part = sum(len(s) for s in subarboles)
        payload = json.dumps({'subarboles': subarboles, 'n_partidas': n_part},
                             ensure_ascii=False)
        cur = conn.execute(
            "INSERT INTO plantillas (nombre, tipo, notas, payload) "
            "VALUES (?,?,?,?)",
            ((nombre or '').strip(), (tipo or '').strip(),
             (notas or '').strip(), payload))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_plantillas() -> list[dict]:
    """Plantillas guardadas (sin el payload), con el conteo de partidas."""
    conn = get_db()
    try:
        ensure_table(conn)
        rows = conn.execute(
            "SELECT id, nombre, tipo, notas, creada_en, payload FROM plantillas "
            "ORDER BY nombre COLLATE NOCASE").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d['n_partidas'] = json.loads(d.pop('payload')).get('n_partidas', 0)
            except Exception:   # noqa: BLE001
                d['n_partidas'] = 0
                d.pop('payload', None)
            out.append(d)
        return out
    finally:
        conn.close()


def subarboles_de_plantilla(plantilla_id: int) -> list:
    """Devuelve los subárboles serializados de una plantilla (para pegarlos)."""
    conn = get_db()
    try:
        ensure_table(conn)
        r = conn.execute("SELECT payload FROM plantillas WHERE id=?",
                         (plantilla_id,)).fetchone()
    finally:
        conn.close()
    if not r:
        return []
    try:
        return json.loads(r['payload']).get('subarboles') or []
    except Exception:   # noqa: BLE001
        return []


def eliminar_plantilla(plantilla_id: int) -> None:
    conn = get_db()
    try:
        conn.execute("DELETE FROM plantillas WHERE id=?", (plantilla_id,))
        conn.commit()
    finally:
        conn.close()


# ── Compartir: exportar / importar una plantilla como archivo .db ──────────────

def exportar_plantilla_db(plantilla_id: int, ruta: str) -> str:
    """Guarda una plantilla como un archivo .db (mini SQLite con la tabla
    `plantillas` y esa fila), para compartirla con otros usuarios."""
    import sqlite3
    src = get_db()
    try:
        r = src.execute(
            "SELECT nombre, tipo, notas, creada_en, payload FROM plantillas "
            "WHERE id=?", (plantilla_id,)).fetchone()
    finally:
        src.close()
    if not r:
        raise ValueError("Plantilla no encontrada")
    dst = sqlite3.connect(ruta)
    try:
        dst.execute(
            """CREATE TABLE IF NOT EXISTS plantillas (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   nombre TEXT NOT NULL, tipo TEXT, notas TEXT,
                   creada_en TEXT, payload TEXT NOT NULL)""")
        dst.execute("DELETE FROM plantillas")
        dst.execute(
            "INSERT INTO plantillas (nombre, tipo, notas, creada_en, payload) "
            "VALUES (?,?,?,?,?)",
            (r['nombre'], r['tipo'], r['notas'], r['creada_en'], r['payload']))
        dst.commit()
    finally:
        dst.close()
    return ruta


def importar_plantillas_db(ruta: str) -> int:
    """Importa las plantillas de un archivo .db compartido. Devuelve cuántas
    importó. Lanza ValueError si el archivo no es una plantilla válida."""
    import sqlite3
    src = sqlite3.connect(ruta)
    src.row_factory = sqlite3.Row
    try:
        try:
            rows = src.execute(
                "SELECT nombre, tipo, notas, payload FROM plantillas").fetchall()
        except sqlite3.DatabaseError:
            # Sin tabla `plantillas`, o el archivo no es un .db válido.
            raise ValueError("El archivo no es una plantilla de ingePresupuestos.")
    finally:
        src.close()
    conn = get_db()
    try:
        ensure_table(conn)
        existentes = {(x['nombre'], x['payload']) for x in
                      conn.execute("SELECT nombre, payload FROM plantillas")}
        n = 0
        for r in rows:
            if not (r['payload'] or '').strip():
                continue
            if (r['nombre'], r['payload']) in existentes:
                continue   # ya la tiene (evita duplicado exacto)
            conn.execute(
                "INSERT INTO plantillas (nombre, tipo, notas, payload) "
                "VALUES (?,?,?,?)",
                (r['nombre'], r['tipo'], r['notas'], r['payload']))
            n += 1
        conn.commit()
        return n
    finally:
        conn.close()
