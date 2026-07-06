# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""Control de Obra · Curva S real — programado vs reprogramado vs ejecutado.

La curva **programada** sale del cronograma (CPM + distribución por período). La
**real** sale de las valorizaciones (% acumulado valorizado de cada una, ubicado
en el tiempo por su fecha). La **reprogramada** la fija el residente por período
(tabla `curva_reprogramada`). Las tres comparten denominador (monto contractual)
y se anclan al INICIO REAL de la obra (lo más temprano entre el inicio del
cronograma y la primera valorización), subiendo desde el día 0.

Base de períodos (`base`):
- ``'semana'``  → ventanas rodantes de 7 días desde el inicio.
- ``'mes'``     → ventanas rodantes de 30 días desde el inicio.
- ``'mes_cal'`` → cortes a FIN DE MES CALENDARIO (la valorización mensual típica);
  si la obra empezó a mitad de mes, el primer corte es parcial.

Ver `[[project_modulo_ejecucion_obra]]`.
"""

import json
from calendar import monthrange
from datetime import date

from core.database import get_db, parcial_wysiwyg
from core.cronograma import get_cronograma_map, cpm

_MESES_ABR = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun',
              'Jul', 'Ago', 'Set', 'Oct', 'Nov', 'Dic']


def _parse_iso(s):
    try:
        y, m, d = str(s).split('-')[:3]
        return date(int(y), int(m), int(d))
    except (ValueError, AttributeError, TypeError):
        return None


def _clave_base(base: str) -> int:
    """Clave entera para guardar la reprogramación por base (columna period_days).
    31 = mes calendario (no choca con 7 ni 30 rodantes)."""
    return {'semana': 7, 'mes': 30, 'mes_cal': 31}.get(base, 30)


def _ventanas(base: str, origen, n_dias: int):
    """Lista de ventanas (dia_ini, dia_fin) 1-indexed desde el origen + etiquetas.
    Para 'mes_cal' usa los meses calendario reales (primer mes parcial)."""
    n_dias = max(1, int(n_dias))
    if base == 'mes_cal' and origen:
        ventanas, labels = [], []
        start, cur = 1, origen
        while start <= n_dias:
            last = monthrange(cur.year, cur.month)[1]
            fin = date(cur.year, cur.month, last)
            end = max(start, (fin - origen).days + 1)
            ventanas.append((start, end))
            labels.append(f"{_MESES_ABR[cur.month - 1]} {cur.year % 100:02d}")
            start = end + 1
            cur = date(cur.year + 1, 1, 1) if cur.month == 12 \
                else date(cur.year, cur.month + 1, 1)
        return ventanas, labels
    pd = 7 if base == 'semana' else 30
    unidad = 'Sem' if base == 'semana' else 'Mes'
    n = max(1, (n_dias + pd - 1) // pd)
    return ([(w * pd + 1, w * pd + pd) for w in range(n)],
            [f"{unidad}{i + 1}" for i in range(n)])


def _distribuir_ventanas(segs_json, ini, dur, parcial, ventanas) -> list:
    """Distribuye `parcial` en ventanas arbitrarias (s, e) según el schedule,
    proporcional a la superposición con los segmentos (generaliza
    cronograma.distribuir_periodos a ventanas de largo variable)."""
    segs = []
    if segs_json:
        try:
            segs = json.loads(segs_json)
        except (ValueError, TypeError):
            pass
    if not segs and (dur or 0) > 0:
        segs = [{'inicio_dia': ini or 1, 'duracion': dur}]
    total_dur = sum(s.get('duracion', 0) for s in segs)
    out = [0.0] * len(ventanas)
    if total_dur <= 0:
        return out
    for seg in segs:
        s_ini = seg.get('inicio_dia', 1)
        s_dur = seg.get('duracion', 0)
        if s_dur <= 0:
            continue
        sp = parcial * s_dur / total_dur
        tE = s_ini + s_dur - 1
        for i, (wS, wE) in enumerate(ventanas):
            ov = max(0, min(wE, tE) - max(wS, s_ini) + 1)
            if ov > 0:
                out[i] += sp * ov / s_dur
    return out


def _label_mes_cal(origen, i: int) -> str:
    """Etiqueta de mes calendario del período i (1-based) desde el origen."""
    m0 = (origen.month - 1) + (i - 1)
    return f"{_MESES_ABR[m0 % 12]} {(origen.year + m0 // 12) % 100:02d}"


def _x_de_dia(dia: int, ventanas) -> float:
    """Posición fraccional en el eje de períodos de un día (fin de ventana i → i+1)."""
    for i, (s, e) in enumerate(ventanas):
        if dia <= e:
            span = max(1, e - s + 1)
            return i + (dia - s + 1) / span
    return float(len(ventanas))


def _idx_de_dia(dia: int, ventanas) -> int:
    """Índice 1-based de la ventana que contiene el día."""
    for i, (s, e) in enumerate(ventanas):
        if dia <= e:
            return i + 1
    return len(ventanas)


def _interp_pts(pts: list, x: float) -> float:
    """Interpola y(x) sobre puntos (x, y) ordenados por x creciente."""
    if not pts:
        return 0.0
    if x <= pts[0][0]:
        return pts[0][1]
    if x >= pts[-1][0]:
        return pts[-1][1]
    for i in range(1, len(pts)):
        x0, y0 = pts[i - 1]
        x1, y1 = pts[i]
        if x <= x1:
            return y1 if x1 == x0 else y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return pts[-1][1]


def curva_s_comparada(proyecto_id: int, base: str = 'mes') -> dict:
    """Curva programada vs reprogramada vs real sobre una línea de tiempo común.
    Devuelve: unidad/labels, n_periods, prog_pts/reprog_pts ([(x,%)]), reales
    ([{numero, desde, hasta, pct_real, pct_prog, x, desviacion}]), filas (por
    período para la tabla) y total_general."""
    from core.valorizacion import listar_valorizaciones, get_valorizacion_detalle

    conn = get_db()
    try:
        proy = conn.execute("SELECT * FROM proyectos WHERE id=?",
                            (proyecto_id,)).fetchone()
        partidas = [dict(p) for p in conn.execute(
            "SELECT * FROM partidas WHERE proyecto_id=? ORDER BY item",
            (proyecto_id,)).fetchall()]
        cmap = get_cronograma_map(conn, proyecto_id)
    finally:
        conn.close()
    proy = dict(proy) if proy else {}
    fecha_inicio = proy.get('fecha_inicio') or proy.get('costo_al') or ''
    fi = _parse_iso(fecha_inicio)
    plazo = (proy.get('plazo') or 0)
    tasks = cpm(cmap, partidas, plazo)
    max_ef = max((t['EF'] for t in tasks.values() if t['EF'] > 0), default=plazo)

    # Valorizaciones (para el origen real y los puntos reales).
    detalles, fechas = [], []
    for v in listar_valorizaciones(proyecto_id):
        _, res = get_valorizacion_detalle(v['id'])
        if not res:
            continue
        detalles.append((v, res))
        d = _parse_iso(res.get('periodo_desde'))
        if d:
            fechas.append(d)

    candidatos = [d for d in ([fi] + fechas) if d]
    origen = min(candidatos) if candidatos else None
    n_dias = max(max_ef, plazo, 1)
    ventanas, labels = _ventanas(base, origen, n_dias)
    unidad = 'Sem' if base == 'semana' else 'Mes'

    # Distribución programada sobre las ventanas. El denominador es el PRESUPUESTO
    # COMPLETO (Σ parciales de todas las partidas, igual base que el pct_fisico de
    # la valorización) para que programado, reprogramado y real sean comparables;
    # las partidas sin cronograma no se distribuyen (la curva programada no llega
    # a 100% si quedó trabajo sin programar).
    total_per = [0.0] * len(ventanas)
    total_general = 0.0
    for p in partidas:
        if p['es_titulo']:
            continue
        cd = cmap.get(p['id'], {})
        ini = tasks.get(p['id'], {}).get('ES', cd.get('inicio_dia', 1) or 1)
        dur = cd.get('duracion', 0) or 0
        parcial = parcial_wysiwyg(p['metrado'], p['precio_unitario'])
        total_general += parcial
        for i, val in enumerate(_distribuir_ventanas(
                cd.get('segmentos', '') or '', ini, dur, parcial, ventanas)):
            total_per[i] += val
    acum, run = [], 0.0
    for v in total_per:
        run += v
        acum.append(run)
    acum_pct = [(x / total_general * 100 if total_general > 0 else 0) for x in acum]

    # Puntos reales (por fecha) + bucket por período (el pct_prog se completa luego
    # con la curva efectiva, que puede tener overrides).
    reales, real_por_periodo, val_por_periodo = [], {}, {}
    for v, res in detalles:
        dh = _parse_iso(res.get('periodo_hasta'))
        if dh and origen:
            dia = (dh - origen).days + 1
            x = _x_de_dia(dia, ventanas); idx = _idx_de_dia(dia, ventanas)
        else:
            x = float(v['numero']); idx = v['numero']
        pct_real = res.get('pct_fisico', 0.0)
        acu_val = res.get('acu_val', 0.0)
        reales.append({'numero': v['numero'],
                       'desde': res.get('periodo_desde') or '',
                       'hasta': res.get('periodo_hasta') or '',
                       'pct_real': pct_real, 'x': x, 'acu_val': acu_val})
        # Si dos valorizaciones caen en el mismo período, gana la de mayor
        # acumulado (la más reciente).
        k = max(1, idx)
        if pct_real >= real_por_periodo.get(k, float('-inf')):
            real_por_periodo[k] = pct_real
            val_por_periodo[k] = acu_val

    # Overrides manuales POR PERÍODO (etiqueta · % ejecución programado · %
    # ejecución reprogramado). El % acumulado y los montos se DERIVAN.
    overrides = get_overrides(proyecto_id, base)
    n_tabla = max([len(ventanas)] + list(overrides) + list(real_por_periodo) + [1])
    while len(labels) < n_tabla:
        i = len(labels) + 1
        labels.append(_label_mes_cal(origen, i) if (base == 'mes_cal' and origen)
                      else f"{unidad}{i}")
    # ¿Hay reprogramación? (algún % de ejecución reprogramado fijado).
    reprog_activo = any(o.get('reprog') is not None for o in overrides.values())

    prog_pts = [(0.0, 0.0)]
    reprog_pts = [(0.0, 0.0)]
    filas = []
    p_acc = r_acc = x_prev = val_prev = 0.0
    for i in range(1, n_tabla + 1):
        ov = overrides.get(i, {})
        label = ov['label'] if ov.get('label') else labels[i - 1]
        # Programado: % de ejecución del período (override o derivado del cronograma).
        if i <= len(acum_pct):
            derived_eje = acum_pct[i - 1] - (acum_pct[i - 2] if i >= 2 else 0.0)
        else:
            derived_eje = None
        p_eje = ov['prog'] if ov.get('prog') is not None else derived_eje
        if p_eje is not None:
            p_acc += p_eje
            p_acu, p_mon = p_acc, p_eje / 100.0 * total_general
            prog_pts.append((float(i), p_acu))
        else:
            p_acu = p_mon = None
        # Reprogramado: % de ejecución del período (solo si hay reprogramación). En
        # blanco = 0 en ese período (el residente llena los meses que reprograma);
        # así el acumulado no puede pasarse de 100% por herencias.
        if reprog_activo:
            r_eje = ov.get('reprog')
            r_acc += (r_eje or 0.0)
            r_acu = r_acc
            r_mon = (r_eje / 100.0 * total_general) if r_eje is not None else None
            reprog_pts.append((float(i), r_acu))
        else:
            r_eje = r_acu = r_mon = None
        # Real: del bucket de valorizaciones, o override manual (% ejec del período).
        derived_acu = real_por_periodo.get(i)
        if ov.get('real') is not None:
            x_eje = ov['real']
            x_prev += x_eje
            x_acu = x_prev
            x_mon = x_eje / 100.0 * total_general
            val_prev += x_mon   # mantener coherente el valorizado corrido
        elif derived_acu is not None:
            x_eje = derived_acu - x_prev
            x_prev = derived_acu
            x_acu = derived_acu
            val = val_por_periodo.get(i)
            x_mon = (val - val_prev) if val is not None else x_eje / 100.0 * total_general
            if val is not None:
                val_prev = val
        else:
            x_eje = x_acu = x_mon = None
        objetivo = r_acu if reprog_activo else p_acu
        desv = (x_acu - objetivo) if (x_acu is not None
                                      and objetivo is not None) else None
        filas.append({
            'idx': i, 'label': label,
            'p_eje': p_eje, 'p_acu': p_acu, 'p_mon': p_mon,
            'r_eje': r_eje, 'r_acu': r_acu, 'r_mon': r_mon,
            'x_eje': x_eje, 'x_acu': x_acu, 'x_mon': x_mon,
            # alias para compat (resumen/chart interpolación):
            'pct_prog': p_acu, 'pct_reprog': r_acu, 'pct_real': x_acu,
            'desviacion': desv,
        })

    # Completar pct_prog/desviación de los puntos reales con la curva efectiva.
    for r in reales:
        pp = _interp_pts(prog_pts, r['x'])
        r['pct_prog'] = pp
        r['desviacion'] = r['pct_real'] - pp

    # Curva real por período (incluye overrides manuales) para el gráfico.
    real_pts = [(0.0, 0.0)] + [(float(f['idx']), f['x_acu'])
                               for f in filas if f['x_acu'] is not None]

    max_x = max([p[0] for p in prog_pts] + [p[0] for p in real_pts]
                + [p[0] for p in reprog_pts] + [1.0])
    # Etiquetas efectivas (con los overrides de «Período»), para tabla y gráfico.
    labels = [f['label'] for f in filas]
    return {
        'base': base, 'unidad': unidad, 'labels': labels,
        'n_periods': max(1, int(max_x + 0.999)),
        'total_general': total_general,
        'fecha_inicio': fecha_inicio,
        'prog_pts': prog_pts, 'reprog_pts': reprog_pts, 'real_pts': real_pts,
        'reales': reales, 'filas': filas,
    }


# ── Reprogramación: % acumulado meta por período ─────────────────────────────

def get_overrides(proyecto_id: int, base: str) -> dict:
    """{periodo_idx: {reprog, prog, label}} con los overrides manuales (None = usar
    el derivado del cronograma)."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT periodo_idx, pct, pct_prog, pct_real, label "
            "FROM curva_reprogramada "
            "WHERE proyecto_id=? AND period_days=? ORDER BY periodo_idx",
            (proyecto_id, _clave_base(base))).fetchall()
        return {r['periodo_idx']: {'reprog': r['pct'], 'prog': r['pct_prog'],
                                   'real': r['pct_real'], 'label': r['label']}
                for r in rows}
    finally:
        conn.close()


def set_override(proyecto_id: int, base: str, periodo_idx: int, campo: str,
                 valor) -> bool:
    """Fija un override de período. campo: 'reprog' | 'prog' | 'real' | 'label'.
    valor None/'' borra ese override (y la fila si queda totalmente vacía)."""
    col = {'reprog': 'pct', 'prog': 'pct_prog', 'real': 'pct_real',
           'label': 'label'}.get(campo)
    if not col:
        return False
    if campo == 'label':
        v = (str(valor).strip() or None) if valor is not None else None
    else:
        try:
            v = None if (valor is None or valor == '') else max(0.0, float(valor))
        except (TypeError, ValueError):
            v = None
    clave = _clave_base(base)
    vals = {'pct': None, 'pct_prog': None, 'pct_real': None, 'label': None}
    vals[col] = v   # NULL explícito en las otras (la columna pct trae DEFAULT 0)
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO curva_reprogramada (proyecto_id, period_days, "
            "periodo_idx, pct, pct_prog, pct_real, label) VALUES (?,?,?,?,?,?,?) "
            f"ON CONFLICT(proyecto_id, period_days, periodo_idx) "
            f"DO UPDATE SET {col}=excluded.{col}",
            (proyecto_id, clave, periodo_idx, vals['pct'], vals['pct_prog'],
             vals['pct_real'], vals['label']))
        conn.execute(
            "DELETE FROM curva_reprogramada WHERE proyecto_id=? AND period_days=? "
            "AND periodo_idx=? AND pct IS NULL AND pct_prog IS NULL "
            "AND pct_real IS NULL "
            "AND (label IS NULL OR label='')",
            (proyecto_id, clave, periodo_idx))
        conn.commit()
        return True
    finally:
        conn.close()


def get_reprogramacion(proyecto_id: int, base: str) -> dict:
    """{periodo_idx: pct_reprog} (solo los reprogramados). Compat/atajo."""
    return {i: o['reprog'] for i, o in get_overrides(proyecto_id, base).items()
            if o['reprog'] is not None}


def limpiar_reprogramacion(proyecto_id: int, base: str = None) -> bool:
    """Borra TODOS los overrides (de una base, o de todas si base es None)."""
    conn = get_db()
    try:
        if base is None:
            conn.execute("DELETE FROM curva_reprogramada WHERE proyecto_id=?",
                         (proyecto_id,))
        else:
            conn.execute("DELETE FROM curva_reprogramada WHERE proyecto_id=? "
                         "AND period_days=?", (proyecto_id, _clave_base(base)))
        conn.commit()
        return True
    finally:
        conn.close()
