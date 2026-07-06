# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""Control de Obra · Fase 1 — Valorización de avance.

Lógica de negocio de las valorizaciones de obra. Se apoya en el presupuesto
existente (partidas: metrado contractual + PU) y SOLO lee de él; nunca lo
modifica. El único dato que se captura por período/partida es el
``metrado_periodo`` (metrado ejecutado en ese período); todo lo demás —valor,
anterior, acumulado, %, saldo— se deriva aquí.

Modelo (núcleo común AD/Contrata):
    valor   = parcial_wysiwyg(metrado, PU)         (mismo criterio que el ppto)
    anterior = Σ valor de los períodos con número < el actual
    actual   = valor del período actual
    acumulado = anterior + actual
    %        = acumulado_valor / base_valor · 100
    saldo    = base − acumulado

Ver `[[project_modulo_ejecucion_obra]]`.
"""

from core.database import get_db, parcial_wysiwyg, _r2


# ── Cabecera: crear / listar / cerrar / eliminar ─────────────────────────────

def crear_valorizacion(proyecto_id: int, periodo_desde: str = '',
                       periodo_hasta: str = '') -> int:
    """Crea una valorización nueva con número correlativo. Devuelve su id."""
    conn = get_db()
    try:
        n = conn.execute(
            "SELECT COALESCE(MAX(numero), 0) + 1 AS n FROM valorizaciones "
            "WHERE proyecto_id=?", (proyecto_id,)
        ).fetchone()['n']
        cur = conn.execute(
            "INSERT INTO valorizaciones (proyecto_id, numero, periodo_desde, "
            "periodo_hasta) VALUES (?,?,?,?)",
            (proyecto_id, n, periodo_desde or '', periodo_hasta or '')
        )
        conn.commit()
        new_id = cur.lastrowid
    finally:
        conn.close()
    # Arrastrar partes diarios ya registrados que caigan en este período
    # (modelo mixto: el cuaderno alimenta la valorización del mes).
    from core import parte_diario
    parte_diario.sincronizar_valorizacion(new_id)
    return new_id


def listar_valorizaciones(proyecto_id: int) -> list[dict]:
    """Lista las valorizaciones del proyecto ordenadas por número."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM valorizaciones WHERE proyecto_id=? ORDER BY numero",
            (proyecto_id,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_valorizacion(val_id: int) -> dict | None:
    conn = get_db()
    try:
        r = conn.execute("SELECT * FROM valorizaciones WHERE id=?",
                         (val_id,)).fetchone()
        return dict(r) if r else None
    finally:
        conn.close()


def cerrar_valorizacion(val_id: int):
    """Congela la valorización (no se puede editar su metrado)."""
    conn = get_db()
    try:
        conn.execute("UPDATE valorizaciones SET estado='cerrada' WHERE id=?",
                     (val_id,))
        conn.commit()
    finally:
        conn.close()


def reabrir_valorizacion(val_id: int):
    conn = get_db()
    try:
        conn.execute("UPDATE valorizaciones SET estado='abierta' WHERE id=?",
                     (val_id,))
        conn.commit()
    finally:
        conn.close()


def set_periodo(val_id: int, periodo_desde: str, periodo_hasta: str) -> bool:
    """Cambia el período (fechas) de una valorización ABIERTA y re-sincroniza el
    metrado que le empujan los partes del cuaderno (el período define qué partes
    caen dentro). Devuelve False si está cerrada."""
    import core.parte_diario as parte_diario
    conn = get_db()
    try:
        v = conn.execute("SELECT estado FROM valorizaciones WHERE id=?",
                         (val_id,)).fetchone()
        if not v or v['estado'] == 'cerrada':
            return False
        conn.execute("UPDATE valorizaciones SET periodo_desde=?, periodo_hasta=? "
                     "WHERE id=?", (periodo_desde or '', periodo_hasta or '', val_id))
        conn.commit()
    finally:
        conn.close()
    parte_diario.sincronizar_valorizacion(val_id)
    return True


def eliminar_valorizacion(val_id: int) -> bool:
    """Elimina una valorización. Solo se permite borrar la ÚLTIMA (mayor
    número) y si está abierta, para no romper la correlatividad / el acumulado.
    Devuelve True si se borró."""
    conn = get_db()
    try:
        v = conn.execute("SELECT proyecto_id, numero, estado FROM valorizaciones "
                         "WHERE id=?", (val_id,)).fetchone()
        if not v or v['estado'] == 'cerrada':
            return False
        ultimo = conn.execute(
            "SELECT MAX(numero) AS n FROM valorizaciones WHERE proyecto_id=?",
            (v['proyecto_id'],)
        ).fetchone()['n']
        if v['numero'] != ultimo:
            return False
        conn.execute("DELETE FROM valorizaciones WHERE id=?", (val_id,))
        conn.commit()
        return True
    finally:
        conn.close()


# ── Detalle: registrar metrado ejecutado ─────────────────────────────────────

def set_metrado_ejecutado(val_id: int, partida_id: int, metrado) -> bool:
    """Registra (o actualiza) el metrado ejecutado de una partida en esta
    valorización. No permite editar si la valorización está cerrada."""
    conn = get_db()
    try:
        v = conn.execute("SELECT estado FROM valorizaciones WHERE id=?",
                         (val_id,)).fetchone()
        if not v or v['estado'] == 'cerrada':
            return False
        # Edición manual del metrado mensual (origen='manual'). Cuando una
        # partida tiene parte diario, la grilla bloquea su celda y esto no se
        # llama; aquí se garantiza el marcado por si acaso.
        conn.execute(
            "INSERT INTO valorizacion_detalle (valorizacion_id, partida_id, "
            "metrado_periodo, origen) VALUES (?,?,?, 'manual') "
            "ON CONFLICT(valorizacion_id, partida_id) "
            "DO UPDATE SET metrado_periodo=excluded.metrado_periodo, origen='manual'",
            (val_id, partida_id, float(metrado or 0))
        )
        conn.commit()
        return True
    finally:
        conn.close()


# ── Cálculo derivado: base / anterior / actual / acumulado / saldo ───────────

def get_valorizacion_detalle(val_id: int) -> tuple[list[dict], dict]:
    """Devuelve ``(filas, resumen)`` de la valorización.

    Cada fila (en orden de ítem) incluye los datos de la partida + los bloques
    base/anterior/actual/acumulado/saldo (metrado y valor) + %. Las filas de
    título traen el subtotal agregado de sus partidas hijas (por prefijo de
    ítem). El resumen trae los totales globales y el % de avance físico.
    """
    conn = get_db()
    try:
        val = conn.execute("SELECT * FROM valorizaciones WHERE id=?",
                           (val_id,)).fetchone()
        if not val:
            return [], {}
        pid = val['proyecto_id']
        numero = val['numero']
        partidas = conn.execute(
            "SELECT * FROM partidas WHERE proyecto_id=? ORDER BY item", (pid,)
        ).fetchall()
        # Metrados ejecutados del proyecto hasta este período, con su número de
        # valorización (para separar «anterior» de «actual»).
        ejec = conn.execute(
            "SELECT vd.partida_id, v.numero AS num, vd.metrado_periodo AS m "
            "FROM valorizacion_detalle vd "
            "JOIN valorizaciones v ON v.id = vd.valorizacion_id "
            "WHERE v.proyecto_id=? AND v.numero <= ?", (pid, numero)
        ).fetchall()
        # Origen del metrado de ESTA valorización por partida ('manual'|'diario')
        # para que la grilla bloquee las celdas alimentadas por el parte diario.
        orig = conn.execute(
            "SELECT partida_id, origen FROM valorizacion_detalle "
            "WHERE valorizacion_id=?", (val_id,)
        ).fetchall()
    finally:
        conn.close()
    origen_map = {r['partida_id']: (r['origen'] or 'manual') for r in orig}

    # partida_id -> {numero: metrado_periodo}
    por_partida: dict[int, dict[int, float]] = {}
    for r in ejec:
        por_partida.setdefault(r['partida_id'], {})[r['num']] = r['m'] or 0

    # 1) Calcular las partidas reales (no títulos).
    calc: dict[int, dict] = {}
    for p in partidas:
        if p['es_titulo']:
            continue
        pu = p['precio_unitario'] or 0
        base_metr = p['metrado'] or 0
        base_val = parcial_wysiwyg(base_metr, pu)
        periodos = por_partida.get(p['id'], {})
        ant_metr = sum(m for n, m in periodos.items() if n < numero)
        ant_val = _r2(sum(parcial_wysiwyg(m, pu)
                          for n, m in periodos.items() if n < numero))
        act_metr = periodos.get(numero, 0)
        act_val = parcial_wysiwyg(act_metr, pu)
        acu_metr = ant_metr + act_metr
        acu_val = _r2(ant_val + act_val)
        calc[p['id']] = {
            'base_metr': base_metr, 'base_val': base_val,
            'ant_metr': ant_metr, 'ant_val': ant_val,
            'act_metr': act_metr, 'act_val': act_val,
            'acu_metr': acu_metr, 'acu_val': acu_val,
            'sal_metr': base_metr - acu_metr,
            'sal_val': _r2(base_val - acu_val),
            'pct': (acu_val / base_val * 100) if base_val else 0.0,
        }

    # 2) Agregar títulos (subtotal de las partidas cuyo ítem cuelga del título).
    def _subtotal(prefijo: str, campo: str) -> float:
        tot = 0.0
        for p in partidas:
            if p['es_titulo']:
                continue
            it = p['item'] or ''
            if it == prefijo or it.startswith(prefijo + '.'):
                tot += calc[p['id']][campo]
        return tot

    filas: list[dict] = []
    for p in partidas:
        fila = {
            'id': p['id'], 'item': p['item'], 'descripcion': p['descripcion'],
            'unidad': p['unidad'], 'nivel': p['nivel'],
            'es_titulo': p['es_titulo'], 'precio_unitario': p['precio_unitario'] or 0,
            'origen': origen_map.get(p['id'], 'manual'),
        }
        if p['es_titulo']:
            base_val = _subtotal(p['item'], 'base_val')
            acu_val = _subtotal(p['item'], 'acu_val')
            fila.update({
                'base_metr': None, 'base_val': base_val,
                'ant_metr': None, 'ant_val': _subtotal(p['item'], 'ant_val'),
                'act_metr': None, 'act_val': _subtotal(p['item'], 'act_val'),
                'acu_metr': None, 'acu_val': acu_val,
                'sal_metr': None, 'sal_val': _r2(base_val - acu_val),
                'pct': (acu_val / base_val * 100) if base_val else 0.0,
            })
        else:
            fila.update(calc[p['id']])
        filas.append(fila)

    # 3) Resumen global.
    base_tot = sum(c['base_val'] for c in calc.values())
    acu_tot = _r2(sum(c['acu_val'] for c in calc.values()))
    resumen = {
        'numero': numero,
        'periodo_desde': val['periodo_desde'], 'periodo_hasta': val['periodo_hasta'],
        'estado': val['estado'],
        'base_val': _r2(base_tot),
        'ant_val': _r2(sum(c['ant_val'] for c in calc.values())),
        'act_val': _r2(sum(c['act_val'] for c in calc.values())),
        'acu_val': acu_tot,
        'sal_val': _r2(base_tot - acu_tot),
        'pct_fisico': (acu_tot / base_tot * 100) if base_tot else 0.0,
    }
    return filas, resumen
