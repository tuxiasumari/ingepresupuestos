# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""Control de Obra · Requerimientos.

Documentos numerados (Req N°1, N°2…) donde el residente solicita los insumos para
la obra. Pensado sobre todo para administración directa: lo requerido VARÍA del
presupuesto (se pide más por actividades extra, menos o nada de lo que hay en
almacén, y se agregan insumos no presupuestados). Se lleva el **requerido
acumulado** por insumo y se compara contra lo **presupuestado** (ACU × metrados).

Tipos: 'mat' (materiales) · 'eq' (equipos) · 'sc' (servicios/subcontratos). La
mano de obra NO va por requerimiento (se maneja por planilla).

Futuro: vincular con el cuaderno de obra (consumo real) y con la valorización AD
(se valoriza lo requerido/gastado). Ver `[[project_modulo_ejecucion_obra]]`.
"""

import math

from core.database import get_db
from core import clasificador

_TIPO_CLASE = {'MAT': 'mat', 'EQ': 'eq', 'SC': 'sc'}

# Unidades que se compran/piden en cantidades ENTERAS (no se pide media bolsa de
# cemento ni 12.3 galones). Se redondea hacia ARRIBA (necesitas al menos eso).
_UNIDADES_ENTERAS = {
    'BOL', 'BLS', 'BOLSA', 'SAC', 'SACO',
    'GLN', 'GAL', 'GALON', 'GALONES',
    'UND', 'UNI', 'UNID', 'UNIDAD', 'PZA', 'PIEZA', 'PZ',
    'VAR', 'VARILLA', 'PLN', 'PLANCHA', 'ROLLO', 'ROL', 'PLA',
    'BALDE', 'LATA', 'CIL', 'CILINDRO', 'JGO', 'JUEGO', 'PAR',
    'MILLAR', 'CIENTO', 'PQT', 'PAQUETE', 'TUBO', 'BARRA', 'KIT',
    'DOC', 'DOCENA', 'CJA', 'CAJA',
}


def redondear_para_pedido(cantidad, unidad) -> float:
    """Redondea hacia ARRIBA si la unidad se pide en enteros (bolsa, galón,
    unidad, varilla…); si no, deja la cantidad tal cual."""
    try:
        c = float(cantidad or 0)
    except (TypeError, ValueError):
        return cantidad
    u = (unidad or '').strip().upper().rstrip('.')
    if u.endswith('S') and u[:-1] in _UNIDADES_ENTERAS:
        u = u[:-1]
    if u in _UNIDADES_ENTERAS and c > 0:
        return float(math.ceil(c - 1e-9))
    return cantidad


# ── Cabecera: crear / listar / cerrar / eliminar ─────────────────────────────

def crear_requerimiento(proyecto_id: int, fecha: str = '',
                        categoria: str = '', tipo: str = '') -> int:
    """Crea un requerimiento. El `tipo` ('mat'|'eq'|'sc') se fija aquí y NO cambia
    al renombrar la categoría (así no se pierde el detalle ya cargado). Si no se
    pasa, se deriva de la categoría."""
    tipo = (tipo or clasificador.tipo_de_categoria(categoria or '')).strip() or 'mat'
    conn = get_db()
    try:
        n = conn.execute(
            "SELECT COALESCE(MAX(numero), 0) + 1 AS n FROM requerimientos "
            "WHERE proyecto_id=?", (proyecto_id,)).fetchone()['n']
        cur = conn.execute(
            "INSERT INTO requerimientos (proyecto_id, numero, fecha, categoria, tipo) "
            "VALUES (?,?,?,?,?)",
            (proyecto_id, n, fecha or '', categoria or '', tipo))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def tipo_de_requerimiento(req: dict) -> str:
    """Tipo ('mat'|'eq'|'sc') de un requerimiento: el guardado, o derivado de la
    categoría para registros antiguos sin la columna `tipo`."""
    t = (req.get('tipo') or '').strip()
    if t:
        return t
    return clasificador.tipo_de_categoria((req.get('categoria') or '').strip())


def set_categoria(req_id: int, categoria: str):
    """Renombra la categoría (etiqueta libre) del requerimiento. NO toca el tipo."""
    conn = get_db()
    try:
        conn.execute("UPDATE requerimientos SET categoria=? WHERE id=?",
                     (categoria or '', req_id))
        conn.commit()
    finally:
        conn.close()


def listar_requerimientos(proyecto_id: int) -> list[dict]:
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM requerimientos WHERE proyecto_id=? ORDER BY numero",
            (proyecto_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_requerimiento(req_id: int) -> dict | None:
    conn = get_db()
    try:
        r = conn.execute("SELECT * FROM requerimientos WHERE id=?",
                         (req_id,)).fetchone()
        return dict(r) if r else None
    finally:
        conn.close()


def set_notas(req_id: int, notas: str):
    conn = get_db()
    try:
        conn.execute("UPDATE requerimientos SET notas=? WHERE id=?",
                     (notas or '', req_id))
        conn.commit()
    finally:
        conn.close()


def cerrar_requerimiento(req_id: int):
    conn = get_db()
    try:
        conn.execute("UPDATE requerimientos SET estado='cerrado' WHERE id=?",
                     (req_id,))
        conn.commit()
    finally:
        conn.close()


def reabrir_requerimiento(req_id: int):
    conn = get_db()
    try:
        conn.execute("UPDATE requerimientos SET estado='abierto' WHERE id=?",
                     (req_id,))
        conn.commit()
    finally:
        conn.close()


def eliminar_requerimiento(req_id: int) -> bool:
    """Elimina CUALQUIER requerimiento abierto (no hay correlatividad como en las
    valorizaciones; el requerido acumulado solo descuenta su aporte)."""
    conn = get_db()
    try:
        v = conn.execute("SELECT proyecto_id, estado FROM requerimientos WHERE id=?",
                         (req_id,)).fetchone()
        if not v or v['estado'] == 'cerrado':
            return False
        pid = v['proyecto_id']
        conn.execute("DELETE FROM requerimientos WHERE id=?", (req_id,))
        # Recompacta la numeración: los que quedan vuelven a ser correlativos
        # (1, 2, 3…) sin huecos, conservando su orden actual.
        restantes = conn.execute(
            "SELECT id FROM requerimientos WHERE proyecto_id=? ORDER BY numero, id",
            (pid,)).fetchall()
        for i, r in enumerate(restantes, start=1):
            conn.execute("UPDATE requerimientos SET numero=? WHERE id=?",
                         (i, r['id']))
        conn.commit()
        return True
    finally:
        conn.close()


# ── Detalle: insumos solicitados por tipo ────────────────────────────────────

def get_detalle(req_id: int, tipo: str) -> list[dict]:
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT recurso_id, descripcion, unidad, cantidad FROM "
            "requerimiento_detalle WHERE requerimiento_id=? AND tipo=? "
            "ORDER BY orden, id", (req_id, tipo)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def save_detalle(req_id: int, tipo: str, filas: list[dict]) -> bool:
    """Reemplaza el detalle de un tipo. Devuelve False si el requerimiento está
    cerrado. Filas vacías se ignoran."""
    conn = get_db()
    try:
        rq = conn.execute("SELECT estado FROM requerimientos WHERE id=?",
                         (req_id,)).fetchone()
        if not rq or rq['estado'] == 'cerrado':
            return False
        conn.execute("DELETE FROM requerimiento_detalle WHERE requerimiento_id=? "
                     "AND tipo=?", (req_id, tipo))
        orden = 0
        for f in filas:
            desc = (f.get('descripcion') or '').strip()
            cant = f.get('cantidad')
            if not desc and not cant:
                continue
            orden += 1
            conn.execute(
                "INSERT INTO requerimiento_detalle (requerimiento_id, tipo, "
                "recurso_id, descripcion, unidad, cantidad, orden) "
                "VALUES (?,?,?,?,?,?,?)",
                (req_id, tipo, f.get('recurso_id'), desc, (f.get('unidad') or ''),
                 float(cant or 0), orden))
        conn.commit()
        return True
    finally:
        conn.close()


# ── Presupuesto vs requerido ─────────────────────────────────────────────────

def _insumos_presupuesto_filas(proyecto_id: int) -> list[dict]:
    """Insumos presupuestados (ACU × metrados), uno por recurso, con su categoría
    (override de `recursos.categoria` o heurística del clasificador)."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT r.id AS recurso_id, r.descripcion, r.unidad, r.tipo, "
            "r.categoria AS cat_override, r.indice_inei AS indice, "
            "SUM(ai.cantidad * COALESCE(p.metrado, 0)) AS cantidad "
            "FROM acu_items ai "
            "JOIN partidas p ON p.id = ai.partida_id "
            "JOIN recursos r ON r.id = ai.recurso_id "
            "WHERE p.proyecto_id=? AND p.es_titulo=0 AND r.tipo IN ('MAT','EQ','SC') "
            "AND SUBSTR(TRIM(COALESCE(r.unidad,'')),1,1) != '%' "
            "GROUP BY r.id HAVING cantidad > 0 ORDER BY r.descripcion",
            (proyecto_id,)).fetchall()
        out = []
        for r in rows:
            cat = (r['cat_override'] or '').strip() or clasificador.categoria_de(
                r['descripcion'], r['tipo'])
            out.append({'recurso_id': r['recurso_id'],
                        'descripcion': r['descripcion'],
                        'unidad': r['unidad'] or '', 'tipo': r['tipo'],
                        'categoria': cat, 'indice': (r['indice'] or '').strip(),
                        'cantidad': round(r['cantidad'], 2)})
        return out
    finally:
        conn.close()


def insumos_presupuesto(proyecto_id: int) -> dict[str, list[dict]]:
    """Insumos presupuestados agrupados por tipo ('mat'|'eq'|'sc')."""
    out: dict[str, list[dict]] = {'mat': [], 'eq': [], 'sc': []}
    for x in _insumos_presupuesto_filas(proyecto_id):
        clase = _TIPO_CLASE.get(x['tipo'])
        if clase:
            out[clase].append(x)
    return out


def insumos_arbol(proyecto_id: int, por: str = 'categoria') -> list[tuple[str, list[dict]]]:
    """Insumos del proyecto agrupados para el panel izquierdo (arrastrar al
    requerimiento). `por` = 'categoria' (orden del catálogo) o 'indice' (índice
    unificado, alfabético). Devuelve [(grupo, [insumos])]."""
    filas = _insumos_presupuesto_filas(proyecto_id)
    grupos: dict[str, list[dict]] = {}
    for x in filas:
        if por == 'indice':
            g = x.get('indice') or '(sin índice)'
        else:
            g = x.get('categoria') or clasificador.CAT_OTROS
        grupos.setdefault(g, []).append(x)
    if por == 'indice':
        orden = sorted(grupos.keys(),
                       key=lambda g: (g == '(sin índice)', g))
    else:
        orden = [c for c in clasificador.CATEGORIAS if c in grupos]
        orden += [g for g in grupos if g not in orden]
    return [(g, sorted(grupos[g], key=lambda x: x['descripcion'])) for g in orden]


def categorias_disponibles(proyecto_id: int) -> list[tuple[str, int]]:
    """Categorías que tienen insumos presupuestados: [(categoria, n_insumos)],
    en el orden del catálogo."""
    cuenta: dict[str, int] = {}
    for x in _insumos_presupuesto_filas(proyecto_id):
        cuenta[x['categoria']] = cuenta.get(x['categoria'], 0) + 1
    return [(c, cuenta[c]) for c in clasificador.CATEGORIAS if c in cuenta]


def presupuesto_por_recurso(proyecto_id: int) -> dict[int, float]:
    """{recurso_id: cantidad presupuestada} (para mostrar la referencia por fila)."""
    res = insumos_presupuesto(proyecto_id)
    return {x['recurso_id']: x['cantidad']
            for lst in res.values() for x in lst if x['recurso_id'] is not None}


def acero_varillas_por_diametro(proyecto_id: int) -> list[dict]:
    """Desglose del acero corrugado del proyecto en VARILLAS de 9 m por diámetro,
    leído de la planilla de acero (`acero_detalle`). El insumo de acero en el ACU
    suele venir como un solo recurso en kg sin diámetro; el diámetro/kg está en
    los metrados de acero. varillas = ⌈kg / (kg_ml × 9)⌉."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT ad.diametro AS d, ad.kg_ml AS kgml, SUM(ad.parcial) AS kg "
            "FROM acero_detalle ad JOIN partidas p ON p.id = ad.partida_id "
            "WHERE p.proyecto_id=? AND TRIM(COALESCE(ad.diametro,'')) <> '' "
            "AND COALESCE(ad.kg_ml,0) > 0 "
            "GROUP BY ad.diametro, ad.kg_ml ORDER BY ad.kg_ml",
            (proyecto_id,)).fetchall()
        out = []
        for r in rows:
            kg = r['kg'] or 0
            kgml = r['kgml'] or 0
            if kg <= 0 or kgml <= 0:
                continue
            out.append({'diametro': r['d'], 'kg': round(kg, 2), 'kg_ml': kgml,
                        'varillas': int(math.ceil(kg / (kgml * 9.0) - 1e-9))})
        return out
    finally:
        conn.close()


def precio_por_recurso(proyecto_id: int) -> dict[int, float]:
    """{recurso_id: precio del recurso en el proyecto} (referencial para el TDR).
    El precio por proyecto vive en `acu_items.precio` (COALESCE con `recursos.precio`)."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT r.id AS rid, COALESCE(("
            "  SELECT ai.precio FROM acu_items ai JOIN partidas p ON p.id=ai.partida_id "
            "  WHERE ai.recurso_id=r.id AND p.proyecto_id=? AND ai.precio IS NOT NULL "
            "  LIMIT 1), r.precio, 0) AS precio "
            "FROM recursos r WHERE r.id IN ("
            "  SELECT DISTINCT ai.recurso_id FROM acu_items ai "
            "  JOIN partidas p ON p.id=ai.partida_id WHERE p.proyecto_id=?)",
            (proyecto_id, proyecto_id)).fetchall()
        return {r['rid']: (r['precio'] or 0) for r in rows}
    finally:
        conn.close()


def guardar_tdr(req_id: int, texto: str, datos_json: str = None):
    """Persiste el TDR (cuerpo, editable). Si `datos_json` no es None, también
    guarda los datos del encabezado (JSON) que la app usa para componer el
    encabezado SOLO en el PDF."""
    conn = get_db()
    try:
        if datos_json is None:
            conn.execute("UPDATE requerimientos SET tdr=? WHERE id=?",
                         (texto or '', req_id))
        else:
            conn.execute("UPDATE requerimientos SET tdr=?, tdr_datos=? WHERE id=?",
                         (texto or '', datos_json or '', req_id))
        conn.commit()
    finally:
        conn.close()


def recursos_en_requerimientos(proyecto_id: int) -> set:
    """Conjunto de recurso_ids ya incluidos en ALGÚN requerimiento del proyecto
    (para marcar con check los insumos ya pedidos en el panel izquierdo)."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT DISTINCT rd.recurso_id FROM requerimiento_detalle rd "
            "JOIN requerimientos rq ON rq.id = rd.requerimiento_id "
            "WHERE rq.proyecto_id=? AND rd.recurso_id IS NOT NULL",
            (proyecto_id,)).fetchall()
        return {r['recurso_id'] for r in rows}
    finally:
        conn.close()


def requerido_acumulado(proyecto_id: int, excluir_req: int = None) -> dict[int, float]:
    """{recurso_id: Σ cantidad requerida} sumando todos los requerimientos del
    proyecto (opcionalmente excluyendo uno)."""
    conn = get_db()
    try:
        sql = ("SELECT rd.recurso_id, SUM(rd.cantidad) AS cant "
               "FROM requerimiento_detalle rd "
               "JOIN requerimientos rq ON rq.id = rd.requerimiento_id "
               "WHERE rq.proyecto_id=? AND rd.recurso_id IS NOT NULL ")
        params = [proyecto_id]
        if excluir_req is not None:
            sql += "AND rq.id != ? "
            params.append(excluir_req)
        sql += "GROUP BY rd.recurso_id"
        rows = conn.execute(sql, params).fetchall()
        return {r['recurso_id']: (r['cant'] or 0) for r in rows}
    finally:
        conn.close()


def precargar_saldo(req_id: int) -> bool:
    """Llena el requerimiento con los insumos presupuestados de SU CATEGORÍA que
    estén pendientes (saldo = presupuestado − requerido en OTROS requerimientos,
    solo saldos > 0). Conserva las filas manuales (extras sin recurso_id). False
    si cerrado."""
    conn = get_db()
    try:
        rq = conn.execute("SELECT proyecto_id, estado, categoria, tipo FROM "
                         "requerimientos WHERE id=?", (req_id,)).fetchone()
        if not rq or rq['estado'] == 'cerrado':
            return False
        pid, categoria = rq['proyecto_id'], (rq['categoria'] or '')
        tipo = tipo_de_requerimiento(dict(rq))
    finally:
        conn.close()
    otros = requerido_acumulado(pid, excluir_req=req_id)
    manuales = [f for f in get_detalle(req_id, tipo) if not f.get('recurso_id')]
    nuevos = []
    for x in _insumos_presupuesto_filas(pid):
        if categoria and x['categoria'] != categoria:
            continue
        saldo = round(x['cantidad'] - otros.get(x['recurso_id'], 0), 2)
        if saldo > 0:
            nuevos.append({'recurso_id': x['recurso_id'],
                           'descripcion': x['descripcion'],
                           'unidad': x['unidad'],
                           'cantidad': redondear_para_pedido(saldo, x['unidad'])})
    save_detalle(req_id, tipo, nuevos + manuales)
    return True


def control_almacen(proyecto_id: int) -> list[dict]:
    """Kárdex de obra de MATERIALES (solo tipo MAT; equipos por hora y servicios
    no son de almacén). Por insumo: PEDIDO (Σ requerimientos), INGRESADO (Σ
    entradas al almacén), CONSUMIDO (Σ salidas del cuaderno), STOCK (ingresado −
    consumido) y POR LLEGAR (pedido − ingresado, nunca negativo). Stock < 0 = se
    consumió más de lo que llegó (faltante/ajuste). Ordenado por descripción."""
    from core.parte_diario import consumido_acumulado, normalizar_recursos_manuales
    from core.almacen import ingresado_acumulado
    # Los insumos escritos a mano en el cuaderno nacen sin recurso_id; enlázalos
    # a un recurso real para que aparezcan en el control de materiales.
    normalizar_recursos_manuales(proyecto_id)
    req = requerido_acumulado(proyecto_id)
    cons = consumido_acumulado(proyecto_id)
    ingr = ingresado_acumulado(proyecto_id)
    ids = set(req) | set(cons) | set(ingr)
    if not ids:
        return []
    conn = get_db()
    try:
        info = {}
        ids_list = list(ids)
        for k in range(0, len(ids_list), 900):   # límite SQLITE_MAX_VARIABLE_NUMBER
            lote = ids_list[k:k + 900]
            marks = ",".join("?" * len(lote))
            for r in conn.execute(
                    f"SELECT id, descripcion, unidad, tipo FROM recursos "
                    f"WHERE id IN ({marks}) AND tipo='MAT'", tuple(lote)).fetchall():
                info[r['id']] = r
    finally:
        conn.close()
    out = []
    for rid in ids:
        r = info.get(rid)
        if not r:
            continue   # no es material (equipo/servicio/MO) → fuera del almacén
        rq = round(float(req.get(rid, 0) or 0), 2)
        ig = round(float(ingr.get(rid, 0) or 0), 2)
        cn = round(float(cons.get(rid, 0) or 0), 2)
        out.append({'recurso_id': rid, 'descripcion': r['descripcion'],
                    'unidad': r['unidad'] or '', 'tipo': r['tipo'],
                    'pedido': rq, 'ingresado': ig, 'consumido': cn,
                    'stock': round(ig - cn, 2),
                    'por_llegar': round(max(rq - ig, 0.0), 2)})
    # En AD solo se rinde lo pedido: los insumos CON requerimiento (pedido > 0)
    # van primero; los que no se pidieron (solo ingreso/consumo) quedan abajo.
    out.sort(key=lambda x: (0 if x['pedido'] > 1e-6 else 1, x['descripcion'] or ''))
    return out
