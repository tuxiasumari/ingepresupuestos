# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""Importador selectivo de proyectos desde una BD .db de ingePresupuestos.

Caso de uso: el usuario tiene un backup `.db` y solo quiere traer algunos
proyectos a su BD activa, sin reemplazar todo.

A diferencia del flujo genérico `core.importer.guardar_importacion()`, este
importador copia el proyecto COMPLETO (especificaciones técnicas, metrados
detallados, metrados de acero, cronograma, imágenes de specs, pie de
presupuesto, gastos generales, sub-presupuestos, fórmula polinómica) usando
SQL directo entre las dos bases vía ATTACH DATABASE.

API pública:
  - listar_proyectos_db(filepath) -> list[dict]
  - importar_proyecto_db_directo(filepath, pid_origen) -> pid_destino
"""
import os
import sqlite3
from typing import Optional

from core.database import get_db


def listar_proyectos_db(filepath: str) -> list[dict]:
    """Lista los proyectos en una BD ingePresupuestos para que el usuario
    elija. Retorna lista de dicts ordenada por nombre."""
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"No existe: {filepath}")
    src = sqlite3.connect(filepath)
    src.row_factory = sqlite3.Row
    try:
        tablas = {r['name'] for r in src.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        for t in ('proyectos', 'partidas', 'acu_items', 'recursos'):
            if t not in tablas:
                raise ValueError(
                    f"La BD no tiene la tabla '{t}'. ¿Es realmente una BD de "
                    f"ingePresupuestos?"
                )
        rows = src.execute(
            "SELECT p.id AS id_ppto, p.nombre, p.cliente, p.ubicacion, "
            "       p.costo_al AS fecha, "
            "       COALESCE(pf.nombre, '') AS portafolio_nombre, "
            "       COALESCE(pf.color, '#667885') AS portafolio_color, "
            "       (SELECT COUNT(*) FROM partidas WHERE proyecto_id=p.id "
            "        AND es_titulo=0) AS n_partidas, "
            "       (SELECT SUM(COALESCE(metrado,0) * COALESCE(precio_unitario,0)) "
            "        FROM partidas WHERE proyecto_id=p.id AND es_titulo=0) AS cd "
            "FROM proyectos p "
            "LEFT JOIN portafolios pf ON pf.id = p.portafolio_id "
            "ORDER BY p.nombre"
        ).fetchall()
        return [
            {
                'id_ppto':   r['id_ppto'],
                'nombre':    r['nombre'] or '',
                'cliente':   r['cliente'] or '',
                'fecha':     r['fecha'] or '',
                'localidad': r['ubicacion'] or '',
                'cd':        float(r['cd'] or 0),
                'ct':        float(r['cd'] or 0),
                'portafolio_nombre': r['portafolio_nombre'],
                'portafolio_color':  r['portafolio_color'],
                'n_partidas': r['n_partidas'] or 0,
            }
            for r in rows
        ]
    finally:
        src.close()


# ── Helpers de copia ────────────────────────────────────────────────────────

def _cols(conn: sqlite3.Connection, tabla: str) -> list[str]:
    """Devuelve la lista de columnas de la tabla en orden del esquema."""
    return [r[1] for r in conn.execute(f"PRAGMA table_info({tabla})").fetchall()]


def _cols_comunes(conn: sqlite3.Connection, src_db: str, tabla: str,
                   excluir: set | None = None) -> list[str]:
    """Columnas que existen en AMBAS bases para la tabla. Necesario porque
    las versiones de BD pueden diferir levemente."""
    excluir = excluir or set()
    dst = set(r[1] for r in conn.execute(f"PRAGMA table_info({tabla})").fetchall())
    src = set(r[1] for r in conn.execute(
        f"PRAGMA {src_db}.table_info({tabla})"
    ).fetchall())
    # Mantener orden del destino
    return [c for c in _cols(conn, tabla) if c in dst and c in src and c not in excluir]


def _tabla_existe(conn: sqlite3.Connection, src_db: str, tabla: str) -> bool:
    r = conn.execute(
        f"SELECT 1 FROM {src_db}.sqlite_master WHERE type='table' AND name=?",
        (tabla,)
    ).fetchone()
    return r is not None


# ── Importador principal ────────────────────────────────────────────────────

def importar_proyecto_db_directo(filepath: str, pid_origen: int) -> int:
    """Copia un proyecto completo desde otra BD .db a la BD activa.

    Preserva: partidas con descripciones, especificaciones técnicas, ACUs con
    cuadrillas/cantidades/precios, metrados detallados, metrados de acero,
    cronograma, imágenes de specs, pie de presupuesto, gastos generales,
    sub-presupuestos, fórmula polinómica. Los recursos se mergean en el
    catálogo por código (no se duplican) y los portafolios por nombre.

    Devuelve el `id` del nuevo proyecto en la BD destino.
    """
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"No existe: {filepath}")

    conn = get_db()
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        # ATTACH del archivo origen como 'src'
        conn.execute(f"ATTACH DATABASE ? AS src", (filepath,))
        try:
            return _do_import(conn, pid_origen)
        finally:
            conn.commit()
            conn.execute("DETACH DATABASE src")
    finally:
        conn.close()


def _do_import(conn: sqlite3.Connection, pid_origen: int) -> int:
    # ── 1. PROYECTO ────────────────────────────────────────────────────
    proy_src = conn.execute(
        "SELECT * FROM src.proyectos WHERE id=?", (pid_origen,)
    ).fetchone()
    if not proy_src:
        raise ValueError(f"No existe el proyecto id={pid_origen} en el origen")
    proy_src = dict(zip(_cols(conn, 'proyectos') if False else
                          [d[0] for d in conn.execute(
                              "SELECT * FROM src.proyectos WHERE 1=0"
                          ).description],
                          proy_src))

    # Resolver portafolio_id: si el proyecto venía con uno, buscar/crear
    # por nombre en destino.
    new_portafolio_id = None
    src_pid_pf = proy_src.get('portafolio_id')
    if src_pid_pf:
        pf_src = conn.execute(
            "SELECT nombre, color, descripcion FROM src.portafolios WHERE id=?",
            (src_pid_pf,)
        ).fetchone()
        if pf_src:
            pf_nombre = pf_src[0]
            existing = conn.execute(
                "SELECT id FROM portafolios WHERE nombre=?", (pf_nombre,)
            ).fetchone()
            if existing:
                new_portafolio_id = existing[0]
            else:
                cur_pf = conn.execute(
                    "INSERT INTO portafolios (nombre, color, descripcion) "
                    "VALUES (?,?,?)",
                    (pf_nombre, pf_src[1] or '#667885',
                     pf_src[2] or '')
                )
                new_portafolio_id = cur_pf.lastrowid

    # usuario_id pertenece a la BD ORIGEN: si ese usuario no existe en la
    # destino la FK falla (típico al compartir un .db entre instalaciones).
    # Se conserva solo si el id existe acá; si no → NULL.
    usuario_dst = None
    if proy_src.get('usuario_id'):
        if conn.execute("SELECT 1 FROM usuarios WHERE id=?",
                        (proy_src['usuario_id'],)).fetchone():
            usuario_dst = proy_src['usuario_id']

    # Inserción de proyecto con todas las columnas comunes
    cols_proy = _cols_comunes(conn, 'src', 'proyectos', excluir={'id'})
    # Forzar portafolio_id mapeado
    valores = []
    for c in cols_proy:
        if c == 'portafolio_id':
            valores.append(new_portafolio_id)
        elif c == 'usuario_id':
            valores.append(usuario_dst)
        else:
            valores.append(proy_src.get(c))
    placeholders = ",".join("?" * len(cols_proy))
    cur = conn.execute(
        f"INSERT INTO proyectos ({','.join(cols_proy)}) VALUES ({placeholders})",
        valores
    )
    pid_dst = cur.lastrowid

    # ── 2. SUB-PRESUPUESTOS (mapeo id_orig → id_dst) ──────────────────
    map_subppto: dict[int, int] = {}
    if _tabla_existe(conn, 'src', 'sub_presupuestos'):
        cols_sp = _cols_comunes(conn, 'src', 'sub_presupuestos',
                                  excluir={'id', 'proyecto_id'})
        for r in conn.execute(
            "SELECT * FROM src.sub_presupuestos WHERE proyecto_id=?",
            (pid_origen,)
        ).fetchall():
            d = dict(zip([c[0] for c in conn.execute(
                "SELECT * FROM src.sub_presupuestos WHERE 1=0"
            ).description], r))
            sub_id_orig = d['id']
            vals = [d.get(c) for c in cols_sp] + [pid_dst]
            cur = conn.execute(
                f"INSERT INTO sub_presupuestos ({','.join(cols_sp)},proyecto_id) "
                f"VALUES ({','.join('?'*len(cols_sp))},?)", vals
            )
            map_subppto[sub_id_orig] = cur.lastrowid

    # ── 3. PARTIDAS (mapeo id_orig → id_dst) ──────────────────────────
    map_partida: dict[int, int] = {}
    cols_part = _cols_comunes(conn, 'src', 'partidas',
                               excluir={'id', 'proyecto_id', 'sub_presupuesto_id'})
    src_cols_partidas = [c[0] for c in conn.execute(
        "SELECT * FROM src.partidas WHERE 1=0"
    ).description]
    tiene_subppto_col = 'sub_presupuesto_id' in src_cols_partidas and \
                         'sub_presupuesto_id' in _cols(conn, 'partidas')

    for r in conn.execute(
        "SELECT * FROM src.partidas WHERE proyecto_id=? ORDER BY id",
        (pid_origen,)
    ).fetchall():
        d = dict(zip(src_cols_partidas, r))
        part_id_orig = d['id']
        vals = [d.get(c) for c in cols_part]
        cols_insert = list(cols_part) + ['proyecto_id']
        vals.append(pid_dst)
        if tiene_subppto_col:
            cols_insert.append('sub_presupuesto_id')
            vals.append(map_subppto.get(d.get('sub_presupuesto_id')))
        ph = ",".join("?" * len(cols_insert))
        cur = conn.execute(
            f"INSERT INTO partidas ({','.join(cols_insert)}) VALUES ({ph})",
            vals
        )
        map_partida[part_id_orig] = cur.lastrowid

    # ── 4. RECURSOS (merge por código) ────────────────────────────────
    # Antes de tocar acu_items, asegurar que todos los recursos referenciados
    # existan en destino. Si no, crear desde origen.
    map_recurso: dict[int, int] = {}
    # Reúso por insumo (tipo, desc_norm, unidad) en el catálogo destino: un
    # mismo insumo se mantiene como UN solo recurso compartido (estilo
    # PowerCost), aunque venga con otro código. Evita que cada import sume
    # otra copia (PEON con otro código, etc.). El precio NO se comparte —
    # vive por línea en acu_items.precio, así que cada proyecto conserva el
    # suyo. `scope_rec` es caché de esta importación.
    scope_rec: dict = {}
    recursos_referenciados = conn.execute(
        "SELECT DISTINCT r.* FROM src.acu_items ai "
        "JOIN src.recursos r ON r.id=ai.recurso_id "
        "JOIN src.partidas p ON p.id=ai.partida_id "
        "WHERE p.proyecto_id=?", (pid_origen,)
    ).fetchall()
    src_cols_rec = [c[0] for c in conn.execute(
        "SELECT * FROM src.recursos WHERE 1=0"
    ).description]
    cols_rec_comunes = _cols_comunes(conn, 'src', 'recursos', excluir={'id'})
    for r in recursos_referenciados:
        d = dict(zip(src_cols_rec, r))
        rec_orig_id = d['id']
        cod = (d.get('codigo') or '').strip()
        desc_n = (d.get('descripcion') or '').strip().upper()
        und_n = (d.get('unidad') or '').strip()
        skey = (d.get('tipo'), desc_n, und_n)
        # 1. Caché de la importación en curso.
        if desc_n and skey in scope_rec:
            map_recurso[rec_orig_id] = scope_rec[skey]
            continue
        # 2. Reúso por insumo en el catálogo destino (tipo+desc+unidad).
        match = None
        if desc_n:
            match = conn.execute(
                "SELECT id FROM recursos WHERE tipo=? "
                "AND UPPER(TRIM(descripcion))=? AND TRIM(unidad)=? "
                "ORDER BY id LIMIT 1",
                (d.get('tipo'), desc_n, und_n)
            ).fetchone()
        # 3. Si no, por código exacto en destino.
        if not match and cod:
            match = conn.execute(
                "SELECT id FROM recursos WHERE codigo=?", (cod,)
            ).fetchone()
        if match:
            map_recurso[rec_orig_id] = match[0]
        else:
            vals = [d.get(c) for c in cols_rec_comunes]
            ph = ",".join("?" * len(cols_rec_comunes))
            cur = conn.execute(
                f"INSERT INTO recursos ({','.join(cols_rec_comunes)}) "
                f"VALUES ({ph})", vals
            )
            map_recurso[rec_orig_id] = cur.lastrowid
        if desc_n:
            scope_rec[skey] = map_recurso[rec_orig_id]

    # ── 5. ACU_ITEMS ──────────────────────────────────────────────────
    cols_acu = _cols_comunes(conn, 'src', 'acu_items',
                              excluir={'id', 'partida_id', 'recurso_id'})
    src_cols_acu = [c[0] for c in conn.execute(
        "SELECT * FROM src.acu_items WHERE 1=0"
    ).description]
    for r in conn.execute(
        "SELECT ai.* FROM src.acu_items ai "
        "JOIN src.partidas p ON p.id=ai.partida_id "
        "WHERE p.proyecto_id=?", (pid_origen,)
    ).fetchall():
        d = dict(zip(src_cols_acu, r))
        new_part_id = map_partida.get(d['partida_id'])
        new_rec_id = map_recurso.get(d['recurso_id'])
        if not new_part_id or not new_rec_id:
            continue
        cols_insert = list(cols_acu) + ['partida_id', 'recurso_id']
        vals = [d.get(c) for c in cols_acu] + [new_part_id, new_rec_id]
        ph = ",".join("?" * len(cols_insert))
        conn.execute(
            f"INSERT INTO acu_items ({','.join(cols_insert)}) VALUES ({ph})",
            vals
        )

    # ── 6. TABLAS DEPENDIENTES DE PARTIDA ─────────────────────────────
    for tabla in ('metrados_detalle', 'acero_detalle', 'cronograma_partidas',
                   'spec_imagenes'):
        if not _tabla_existe(conn, 'src', tabla):
            continue
        cols_t = _cols_comunes(conn, 'src', tabla,
                                excluir={'id', 'partida_id'})
        src_cols_t = [c[0] for c in conn.execute(
            f"SELECT * FROM src.{tabla} WHERE 1=0"
        ).description]
        rows = conn.execute(
            f"SELECT t.* FROM src.{tabla} t "
            f"JOIN src.partidas p ON p.id=t.partida_id "
            f"WHERE p.proyecto_id=?", (pid_origen,)
        ).fetchall()
        for r in rows:
            d = dict(zip(src_cols_t, r))
            new_part_id = map_partida.get(d['partida_id'])
            if not new_part_id:
                continue
            cols_insert = list(cols_t) + ['partida_id']
            vals = [d.get(c) for c in cols_t] + [new_part_id]
            ph = ",".join("?" * len(cols_insert))
            try:
                conn.execute(
                    f"INSERT INTO {tabla} ({','.join(cols_insert)}) "
                    f"VALUES ({ph})", vals
                )
            except sqlite3.IntegrityError:
                # cronograma_partidas tiene UNIQUE(partida_id) — saltar duplicado
                pass

    # ── 7. TABLAS DEPENDIENTES DE PROYECTO ────────────────────────────
    for tabla in ('pie_rubros', 'gastos_generales', 'formula_monomios',
                   'formula_periodos'):
        if not _tabla_existe(conn, 'src', tabla):
            continue
        # formula_periodos tiene proyecto_id como PK → INSERT OR REPLACE
        is_pk_proy = (tabla == 'formula_periodos')
        cols_t = _cols_comunes(conn, 'src', tabla,
                                excluir={'id', 'proyecto_id'})
        src_cols_t = [c[0] for c in conn.execute(
            f"SELECT * FROM src.{tabla} WHERE 1=0"
        ).description]
        rows = conn.execute(
            f"SELECT * FROM src.{tabla} WHERE proyecto_id=?",
            (pid_origen,)
        ).fetchall()
        for r in rows:
            d = dict(zip(src_cols_t, r))
            cols_insert = list(cols_t) + ['proyecto_id']
            vals = [d.get(c) for c in cols_t] + [pid_dst]
            ph = ",".join("?" * len(cols_insert))
            verb = "INSERT OR REPLACE INTO" if is_pk_proy else "INSERT INTO"
            try:
                conn.execute(
                    f"{verb} {tabla} ({','.join(cols_insert)}) VALUES ({ph})",
                    vals
                )
            except sqlite3.IntegrityError:
                pass

    # ── 8. ENRIQUECER BIBLIOTECA CU ───────────────────────────────────
    # Para cada partida-hoja con ACU que NO esté ya en biblioteca, agregar
    # con sus items.
    for r in conn.execute(
        "SELECT id, descripcion, unidad, rendimiento, precio_unitario "
        "FROM partidas WHERE proyecto_id=? AND es_titulo=0",
        (pid_dst,)
    ).fetchall():
        new_part_id = r[0]
        desc = (r[1] or '').strip()
        und  = (r[2] or '').strip()
        if not desc:
            continue
        # ¿Tiene items? Si no, omitir
        n_items = conn.execute(
            "SELECT COUNT(*) FROM acu_items WHERE partida_id=?",
            (new_part_id,)
        ).fetchone()[0]
        if n_items == 0:
            continue
        # Dedup biblioteca
        ex = conn.execute(
            "SELECT id FROM biblioteca_cu "
            "WHERE descripcion=? AND unidad=? AND grupo=''",
            (desc, und)
        ).fetchone()
        if ex:
            cu_id = ex[0]
            # ¿Ya tiene items? Si sí, respetar
            n_bi = conn.execute(
                "SELECT COUNT(*) FROM biblioteca_acu_items WHERE cu_id=?",
                (cu_id,)
            ).fetchone()[0]
            if n_bi > 0:
                continue
        else:
            cur = conn.execute(
                "INSERT INTO biblioteca_cu "
                "(descripcion, unidad, rendimiento, costo_unitario, grupo, "
                " especificaciones, usos) VALUES (?,?,?,?,'','',0)",
                (desc, und, float(r[3] or 1.0), float(r[4] or 0))
            )
            cu_id = cur.lastrowid
        # Copiar items (con precio efectivo: COALESCE precio-proyecto / catálogo)
        for ai in conn.execute(
            "SELECT a.recurso_id, a.cuadrilla, a.cantidad, "
            "       COALESCE(a.precio, r.precio) AS precio "
            "FROM acu_items a JOIN recursos r ON r.id = a.recurso_id "
            "WHERE a.partida_id=?",
            (new_part_id,)
        ).fetchall():
            conn.execute(
                "INSERT INTO biblioteca_acu_items "
                "(cu_id, recurso_id, cuadrilla, cantidad, precio) VALUES (?,?,?,?,?)",
                (cu_id, ai[0], float(ai[1] or 0), float(ai[2] or 0),
                 ai[3] if ai[3] is not None else None)
            )

    return pid_dst
