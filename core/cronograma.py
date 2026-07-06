# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""Cronograma: CPM (Critical Path Method) y distribución semanal/mensual.

Equivalente a las funciones _cpm_python() y _semanas_dist() del Flask.
"""
import re
import math
import json
from typing import Optional


# Filas virtuales del Gantt (NO existen en la tabla `partidas`).
PROYECTO_PID = -1   # resumen del proyecto (nombre de la obra) → siempre #1
INICIO_PID = -2     # «Inicio de Obra» → siempre #2
FIN_PID = -3        # «Termino de Obra» → siempre la última fila

_GRUPO_INICIAL = object()   # sentinela para detectar el primer grupo


def filas_slots(partidas: list) -> list:
    """Secuencia ORDENADA de filas del Gantt estilo MS Project, como lista de
    tuplas (tipo, clave):
      ('proyecto', PROYECTO_PID)  → resumen del proyecto / nombre de la obra
      ('inicio',   INICIO_PID)    → hito «Inicio de Obra»
      ('sub', sub_presupuesto_id) → cabecera de subpresupuesto (una por grupo)
      ('partida',  partida_id)    → título o partida real
      ('fin',      FIN_PID)       → hito «Termino de Obra»
    `partidas` debe venir AGRUPADO por subpresupuesto (Principal/NULL primero,
    luego cada subpresupuesto por `orden`) y, dentro de cada grupo, por item.
    Se inserta una cabecera de subpresupuesto al inicio de cada grupo."""
    slots = [('proyecto', PROYECTO_PID), ('inicio', INICIO_PID)]
    prev = _GRUPO_INICIAL
    for p in partidas:
        g = p.get('sub_presupuesto_id') if hasattr(p, 'get') else p['sub_presupuesto_id']
        if g != prev:
            slots.append(('sub', g))
            prev = g
        slots.append(('partida', p['id']))
    slots.append(('fin', FIN_PID))
    return slots


def numerar_filas(partidas: list) -> dict:
    """Devuelve {clave: nº de fila} estilo Id de MS Project:
      #1            → resumen del proyecto ([[PROYECTO_PID]])
      #2            → hito «Inicio de Obra» ([[INICIO_PID]])
      #3 …          → cabecera de subpresupuesto + sus títulos/partidas
      último        → hito «Termino de Obra» ([[FIN_PID]])
    Las cabeceras de subpresupuesto OCUPAN un número (cuentan posición) pero NO
    se registran aquí (no son referenciables como predecesora). Es la numeración
    canónica del "#", las predecesoras y los auto-programadores. `partidas` debe
    venir AGRUPADO por subpresupuesto (ver [[filas_slots]]). Como #2 queda
    reservado al hito de inicio, las partidas cuelgan de él escribiendo "2"."""
    rownum = {}
    for i, (tipo, clave) in enumerate(filas_slots(partidas), start=1):
        if tipo != 'sub':   # proyecto/inicio/fin/partida → registrables
            rownum[clave] = i
    return rownum


def contar_laborables(a: int, b: int, non_working: set = None) -> int:
    """Cuenta los días laborables en el rango calendario [a, b] (inclusive,
    1-indexed), descontando los días en `non_working` (domingos + feriados)."""
    if not a or not b or b < a:
        return 0
    non_working = non_working or set()
    return sum(1 for d in range(a, b + 1) if d not in non_working)


# Tipos de dependencia. Internamente se usan los códigos ingleses
# {FS,SS,FF,SF}; en la UI se acepta y se muestra la notación de MS Project en
# español: FC (Fin→Comienzo=FS), CC (Comienzo→Comienzo=SS), FF (Fin→Fin),
# CF (Comienzo→Fin=SF).
_TIPO_NORM = {'FS': 'FS', 'SS': 'SS', 'FF': 'FF', 'SF': 'SF',
              'FC': 'FS', 'CC': 'SS', 'CF': 'SF'}   # acepta ambas notaciones
_TIPO_ES = {'FS': 'FC', 'SS': 'CC', 'FF': 'FF', 'SF': 'CF'}  # interno → español

# Regex compartido: base | tipo opcional (es/en) | lag ±N(%) | tgt_pct TN%
_PAT_PRED = re.compile(
    r'^\s*([^+\-FfSsCcTt%]+?)\s*'                          # base
    r'(FS|SS|FF|SF|FC|CC|CF|fs|ss|ff|sf|fc|cc|cf)?\s*'     # tipo (opcional)
    r'(?:'                                                 # uno de:
      r'([+-])\s*(\d+\.?\d*)(%)?'                           #   ±N(%)
      r'|'
      r'[Tt]\s*(\d+\.?\d*)\s*%?'                            #   TN%
    r')?\s*$'
)


def formatear_pred_es(s: str) -> str:
    """Traduce los códigos de tipo de una cadena de predecesoras a la notación
    MS Project en español para mostrar: FS→FC, SS→CC, SF→CF (FF igual). Deja
    intactos números, lags y porcentajes. Las cadenas ya en español no cambian."""
    if not s:
        return s or ''
    def _repl(m):
        return _TIPO_ES.get(m.group(1).upper(), m.group(1))
    # Solo traduce un código de tipo inglés que siga inmediatamente a un dígito.
    return re.sub(r'(?<=\d)(FS|SS|SF|FF|fs|ss|sf|ff)', _repl, s)


def parse_predecesoras(s: str, rownum_inv: dict, item_map: dict) -> list:
    """Parsea referencias de predecesoras y devuelve lista de
    {pid, tipo, lag, pct, tgt_pct}.

    Formatos soportados (notación MS Project español/inglés + extensión tgt_pct):
      - '5'           → FS/FC (default, sin lag)
      - '5+3'         → FS + 3 días lag (legacy)
      - '5+50%'       → arrancar cuando pred lleva 50% (pct lado pred)
      - '5FC' / '5FS' → Fin→Comienzo explícito
      - '5CC' / '5SS' → Comienzo→Comienzo: inicia cuando pred inicia
      - '5FF'         → Fin→Fin: termina cuando pred termina
      - '5CF' / '5SF' → Comienzo→Fin: termina cuando pred inicia (raro)
      - '5CC+2'       → CC con 2 días de lag
      - '5FF-1'       → FF con 1 día de lead (negativo)
      - '5T50%'       → cuando pred termina, sucesor está al 50% (NUEVO)

    'tipo' ∈ {'FS','SS','FF','SF'} (interno); default FS si no se especifica.
    'pct' (lado pred) y 'tgt_pct' (lado sucesor) son mutuamente excluyentes."""
    if not s:
        return []
    out = []
    pat = _PAT_PRED
    for ref in re.split(r'[,;]+', s):
        ref = ref.strip()
        if not ref:
            continue
        m = pat.match(ref)
        lag, pct, tgt_pct, tipo, base = 0, 0, 0, 'FS', ref
        if m:
            base = (m.group(1) or '').strip()
            t = m.group(2)
            if t:
                tipo = _TIPO_NORM.get(t.upper(), 'FS')
            sig = m.group(3)
            num = m.group(4)
            pctmark = m.group(5)
            num_tgt = m.group(6)
            if num:
                v = float(num)
                if sig == '-':
                    v = -v
                if pctmark:
                    pct = v
                else:
                    lag = v
            elif num_tgt:
                tgt_pct = float(num_tgt)
        if not base:
            continue
        # Resolver base: primero número de fila, luego item
        try:
            n = int(base)
            if str(n) == base and n in rownum_inv:
                out.append({'pid': rownum_inv[n], 'tipo': tipo,
                            'lag': lag, 'pct': pct, 'tgt_pct': tgt_pct})
                continue
        except Exception:
            pass
        if base in item_map:
            out.append({'pid': item_map[base], 'tipo': tipo,
                        'lag': lag, 'pct': pct, 'tgt_pct': tgt_pct})
    return out


def migrar_predecesoras_msproject(partidas: list, cronograma_map: dict,
                                   desde: str = 'leaf') -> dict:
    """Reescribe las cadenas `predecesoras` a la numeración final estilo MS
    Project (#1 = hito Inicio, partidas reales = 2..N+1).

    Las cadenas VIEJAS estaban numeradas en orden PLANO (ORDER BY item).
    `desde` indica su esquema:
      'leaf'      → solo partidas hoja (esquema original).
      'allrows'   → todas las filas reales 1..N (migración v1).
      'msproject' → reales 2..N+1, con #1 hito de inicio (migración v2).
      'msp_v2'    → reales 3..N+2, con #1 resumen + #2 inicio (migración v3, plano).
    La numeración NUEVA es AGRUPADA por subpresupuesto (ver [[numerar_filas]]).

    Devuelve {partida_id: nueva_cadena} solo para las que cambian. Preserva
    sufijos FS/SS/FF/SF, ±lag, %, TN%; solo sustituye el entero base de cada
    referencia. Refs por item-code o que no resuelvan se dejan intactas.
    `partidas` debe venir AGRUPADO por subpresupuesto (orden de visualización)."""
    # Numeración VIEJA: en orden PLANO por item (como se guardó).
    flat = sorted(partidas, key=lambda p: (p['item'] or ''))
    allrows_flat = {}
    i = 0
    for p in flat:
        i += 1
        allrows_flat[p['id']] = i
    if desde == 'allrows':
        old_n = dict(allrows_flat)
    elif desde == 'msproject':
        old_n = {pid: pos + 1 for pid, pos in allrows_flat.items()}
    elif desde == 'msp_v2':
        old_n = {pid: pos + 2 for pid, pos in allrows_flat.items()}
    else:  # 'leaf' (solo hojas, orden plano)
        old_n = {}
        rn = 0
        for p in flat:
            if not p['es_titulo']:
                rn += 1
                old_n[p['id']] = rn
    old_inv = {v: k for k, v in old_n.items()}
    # Numeración NUEVA (final): AGRUPADA por subpresupuesto, con cabeceras.
    new_rownum = numerar_filas(partidas)
    new_n = {p['id']: new_rownum[p['id']] for p in partidas if p['id'] in new_rownum}

    def _reescribir(s: str) -> str:
        partes = []
        for ref in re.split(r'([,;]+)', s):  # conserva los separadores
            if re.fullmatch(r'[,;]+', ref) or not ref.strip():
                partes.append(ref)
                continue
            m = re.match(r'^(\s*)(\d+)(.*)$', ref)
            if not m:
                partes.append(ref)
                continue
            pre, base, resto = m.group(1), int(m.group(2)), m.group(3)
            pid = old_inv.get(base)
            if pid is not None and pid in new_n:
                partes.append(f"{pre}{new_n[pid]}{resto}")
            else:
                partes.append(ref)  # no resuelve: intacto
        return ''.join(partes)

    out = {}
    for p in partidas:
        cd = cronograma_map.get(p['id'], {})
        s = (cd.get('predecesoras', '') or '').strip()
        if not s:
            continue
        nuevo = _reescribir(s)
        if nuevo != s:
            out[p['id']] = nuevo
    return out


def cpm(cronograma_map: dict, partidas: list, plazo: int,
        non_working: set = None) -> dict:
    """Critical Path Method. Devuelve {partida_id: {ES,EF,LS,LF,float,critical}}.

    `non_working` (opcional): conjunto de días (int, 1-indexed) que son no
    laborables (domingos + feriados). Si se proporciona, las tareas no
    inician ni terminan en esos días, y la duración se cuenta en días
    laborables (los no laborables intermedios se saltan)."""
    non_working = non_working or set()

    def _next_working(day: int) -> int:
        """Empuja `day` hacia adelante hasta el siguiente día laborable."""
        while day in non_working:
            day += 1
        return day

    def _prev_working(day: int) -> int:
        """Empuja `day` hacia atrás hasta el anterior día laborable."""
        while day > 1 and day in non_working:
            day -= 1
        return day

    def _end_skipping(start_day: int, dur: int) -> int:
        """Día final consumiendo `dur` días LABORABLES desde `start_day`."""
        if dur <= 0:
            return start_day - 1
        cur = start_day
        consumed = 0
        while True:
            if cur not in non_working:
                consumed += 1
                if consumed == dur:
                    return cur
            cur += 1

    def _start_skipping(end_day: int, dur: int) -> int:
        """Día de inicio para terminar en `end_day` consumiendo `dur` laborables."""
        if dur <= 0:
            return end_day + 1
        cur = end_day
        consumed = 0
        while cur >= 1:
            if cur not in non_working:
                consumed += 1
                if consumed == dur:
                    return cur
            cur -= 1
        return 1

    order = [p for p in partidas if not p['es_titulo']]
    # Numeración estilo MS Project Id: cuenta TODAS las filas (títulos incluidos).
    rownum = numerar_filas(partidas)
    rownum_inv = {v: k for k, v in rownum.items()}
    item_map = {p['item']: p['id'] for p in partidas if not p['es_titulo']}

    tasks = {}
    for p in order:
        cd = cronograma_map.get(p['id'], {})
        ini = max(1, int(cd.get('inicio_dia', 1) or 1))
        tasks[p['id']] = {
            'dur': cd.get('duracion', 0) or 0,
            'preds': parse_predecesoras(cd.get('predecesoras', '') or '',
                                         rownum_inv, item_map),
            'inicio_dia': ini,    # constraint "no antes de"
            'es_hito': cd.get('es_hito', 0) or 0,
            'segmentos': cd.get('segmentos', '') or '',
            'ES': ini, 'EF': 0, 'LS': 0, 'LF': 0,
            'float': 0, 'critical': False,
        }

    # ── Títulos/subtítulos como predecesores (estilo MS Project) ──────────────
    # Un título puede ser predecesor: el sucesor se ancla al INICIO del grupo
    # (CC/SS) o al FIN del grupo (FC/FS). El grupo = sus partidas hoja
    # descendientes (por prefijo de item). `title_leaves[pid_título]` = set de
    # ids hoja; `title_ids` = títulos referenciables.
    title_leaves: dict = {}
    for tt in partidas:
        if not tt['es_titulo']:
            continue
        titem = (tt['item'] or '')
        if not titem:
            continue
        kids = {p['id'] for p in order
                if (p['item'] or '').startswith(titem + '.')}
        if kids:
            title_leaves[tt['id']] = kids
    title_ids = set(title_leaves.keys())

    def _title_es_ef(tpid):
        """(ES, EF) resumen del título = min(ES hijas) .. max(EF hijas).
        None si ninguna hija está programada todavía."""
        kids = title_leaves.get(tpid, ())
        es_vals = [tasks[k]['ES'] for k in kids if tasks[k]['EF'] > 0]
        ef_vals = [tasks[k]['EF'] for k in kids if tasks[k]['EF'] > 0]
        if not ef_vals:
            return None
        return min(es_vals), max(ef_vals)

    def _resolver_pred(succ_id, pr):
        """Devuelve un pseudo-pred {ES,EF,dur} para el predecesor `pr`, sea una
        partida real o un título (resumen del grupo). None si no aplica o si
        sería ciclo (el sucesor es hija del título)."""
        pid_pred = pr['pid']
        if pid_pred in title_ids:
            if succ_id in title_leaves.get(pid_pred, ()):
                return None   # anti-ciclo: un grupo no es predecesor de su hija
            span = _title_es_ef(pid_pred)
            if span is None:
                return None
            pES, pEF = span
            return {'ES': pES, 'EF': pEF, 'dur': pEF - pES + 1}
        pt = tasks.get(pid_pred)
        if not pt or pt['EF'] <= 0:
            return None
        return pt

    # Forward pass — soporta FS/SS/FF/SF + lag (formato MS Project)
    for _ in range(len(order) + 5):
        chg = False
        for p in order:
            t = tasks[p['id']]
            if t['dur'] <= 0:
                t['EF'] = 0
                continue
            es = t['inicio_dia']   # constraint mínimo
            for pr in t['preds']:
                pt = _resolver_pred(p['id'], pr)
                if not pt or pt['EF'] <= 0:
                    continue
                lag = round(pr.get('lag', 0))
                tipo = pr.get('tipo', 'FS')
                if pr.get('tgt_pct', 0) > 0:
                    # NUEVO: cuando pred termina, este sucesor debe estar al
                    # tgt_pct% completado. → ES = EF_pred - dur*pct/100 + 1.
                    es = max(es,
                              pt['EF'] - math.ceil(t['dur'] * pr['tgt_pct'] / 100) + 1)
                elif pr.get('pct', 0) > 0:
                    # Legacy: arrancar cuando pred lleva X% completado
                    es = max(es, pt['ES'] + math.ceil(pt['dur'] * pr['pct'] / 100))
                elif tipo == 'SS':
                    # Start-to-Start: B inicia cuando A inicia (+ lag)
                    es = max(es, pt['ES'] + lag)
                elif tipo == 'FF':
                    # Finish-to-Finish: B termina cuando A termina (+ lag)
                    # → ES = pt.EF + lag - dur + 1
                    es = max(es, pt['EF'] + lag - t['dur'] + 1)
                elif tipo == 'SF':
                    # Start-to-Finish: B termina cuando A inicia (+ lag) — raro
                    es = max(es, pt['ES'] + lag - t['dur'] + 1)
                else:  # FS (default)
                    # Finish-to-Start: B inicia un día después de que A termina
                    es = max(es, pt['EF'] + 1 + lag)
            # Empujar ES al siguiente día laborable y calcular EF saltando no laborables
            es = _next_working(es)
            ef = _end_skipping(es, t['dur'])
            if es != t['ES'] or ef != t['EF']:
                t['ES'] = es
                t['EF'] = ef
                chg = True
        if not chg:
            break

    proj_end = max((t['EF'] for t in tasks.values() if t['EF'] > 0),
                    default=plazo)
    proj_end = max(proj_end, plazo)
    # proj_end debe caer en un día laborable
    proj_end = _prev_working(proj_end)

    # Backward pass — inicializar LF al final del proyecto y calcular LS
    # consumiendo dur días LABORABLES hacia atrás (no calendario).
    for p in order:
        t = tasks[p['id']]
        if t['dur'] > 0:
            t['LF'] = proj_end
            t['LS'] = _start_skipping(proj_end, t['dur'])

    # Backward pass — recorre los sucesores de cada tarea y aplica la regla
    # inversa según el tipo de dependencia (FS/SS/FF/SF + lag), respetando
    # días no laborables (LS se computa restando duración LABORABLE).
    for _ in range(len(order) + 5):
        chg = False
        for p in reversed(order):
            t = tasks[p['id']]
            if t['dur'] <= 0:
                continue
            lf = proj_end
            for s_id, s in tasks.items():
                if s['dur'] <= 0:
                    continue
                for pr in s['preds']:
                    tgt = pr['pid']
                    tipo = pr.get('tipo', 'FS')
                    if tgt in title_ids:
                        # Título como predecesor: la fecha límite del FIN del
                        # grupo (FS/FF) recae en cada hija. SS/SF/% se omiten
                        # (la programación ya la fija el forward; el fin del
                        # grupo = techo de fin de cada hija).
                        kids = title_leaves.get(tgt, ())
                        # Anti-ciclo: si el sucesor pertenece al grupo, la
                        # dependencia se ignoró en el forward → ignorar aquí.
                        if s_id in kids:
                            continue
                        if p['id'] not in kids:
                            continue
                        if tipo not in ('FS', 'FF'):
                            continue
                    elif tgt != p['id']:
                        continue
                    lag = round(pr.get('lag', 0))
                    if pr.get('pct', 0) > 0:
                        continue
                    if pr.get('tgt_pct', 0) > 0:
                        # B llega al tgt_pct% cuando A termina.
                        # A.LF debe ser ≤ B.LS + B.dur * tgt_pct/100 - 1
                        cand_lf = s['LS'] + math.ceil(s['dur'] * pr['tgt_pct'] / 100) - 1
                        cand_lf = _prev_working(cand_lf)
                        if cand_lf < lf:
                            lf = cand_lf
                        continue
                    if tipo == 'SS':
                        cand_ls = s['LS'] - lag
                        cand_lf = _end_skipping(cand_ls, t['dur'])
                    elif tipo == 'FF':
                        cand_lf = s['LF'] - lag
                    elif tipo == 'SF':
                        cand_ls = s['LF'] - lag
                        cand_lf = _end_skipping(cand_ls, t['dur'])
                    else:  # FS
                        cand_lf = s['LS'] - 1 - lag
                    cand_lf = _prev_working(cand_lf)
                    if cand_lf < lf:
                        lf = cand_lf
            ls = _start_skipping(lf, t['dur'])
            if lf != t['LF'] or ls != t['LS']:
                t['LF'] = lf
                t['LS'] = ls
                chg = True
        if not chg:
            break

    for t in tasks.values():
        if t['dur'] > 0:
            t['float'] = t['LS'] - t['ES']
            t['critical'] = t['float'] <= 0

    # Propagación de criticidad por predecesor "conductor".
    # El ajuste de un lead/lag a día laborable puede dejar a un predecesor que
    # de hecho gobierna una tarea crítica con 1-2 días de holgura artificial
    # (varios fines de A mapean al mismo inicio de B por el salto de fin de
    # semana), por lo que no se marca crítico aunque la ruta pase por él. Si la
    # restricción del predecesor cae justo en el ES de un sucesor crítico,
    # entonces es conductor y también es crítico → ruta crítica contigua.
    def _nominal_es(a, b, pr):
        """ES de `b` que impone el predecesor `a` (sin ajustar a laborable)."""
        lag = round(pr.get('lag', 0))
        tipo = pr.get('tipo', 'FS')
        if tipo == 'SS':
            return a['ES'] + lag
        if tipo == 'FF':
            return a['EF'] + lag - b['dur'] + 1
        if tipo == 'SF':
            return a['ES'] + lag - b['dur'] + 1
        return a['EF'] + 1 + lag   # FS

    for _ in range(len(order) + 5):
        chg = False
        for p in order:
            b = tasks[p['id']]
            if not b['critical'] or b['dur'] <= 0:
                continue
            for pr in b['preds']:
                if pr.get('pct', 0) > 0 or pr.get('tgt_pct', 0) > 0:
                    continue   # modos %/CC% conservan criticidad por holgura
                a = tasks.get(pr['pid'])
                if not a or a['dur'] <= 0 or a['critical']:
                    continue
                if _next_working(_nominal_es(a, b, pr)) == b['ES']:
                    a['critical'] = True
                    a['float'] = min(a['float'], 0)
                    chg = True
        if not chg:
            break

    return tasks


def distribuir_periodos(segs_json: str, ini: int, dur: int, parcial: float,
                          n_periods: int, period_days: int = 7) -> list:
    """Distribuye `parcial` en n_periods según el schedule (soporta segmentos).

    period_days: 7 = semanas, 30 = meses
    """
    segs = []
    if segs_json:
        try:
            segs = json.loads(segs_json)
        except Exception:
            pass
    if not segs and (dur or 0) > 0:
        segs = [{'inicio_dia': ini or 1, 'duracion': dur}]

    total_dur = sum(s.get('duracion', 0) for s in segs)
    weekly = [0.0] * n_periods
    if total_dur <= 0 or not segs:
        return weekly

    for seg in segs:
        s_ini = seg.get('inicio_dia', 1)
        s_dur = seg.get('duracion', 0)
        if s_dur <= 0:
            continue
        sp = parcial * s_dur / total_dur
        for w in range(n_periods):
            wS = w * period_days + 1
            wE = wS + period_days - 1
            tE = s_ini + s_dur - 1
            ov = max(0, min(wE, tE) - max(wS, s_ini) + 1)
            if ov > 0:
                weekly[w] += sp * ov / s_dur
    return weekly


def get_cronograma_map(conn, pid: int) -> dict:
    """Devuelve {partida_id: {duracion, inicio_dia, predecesoras, es_hito, segmentos}}."""
    rows = conn.execute(
        """SELECT cp.* FROM cronograma_partidas cp
           JOIN partidas p ON p.id = cp.partida_id
           WHERE p.proyecto_id = ?""", (pid,)
    ).fetchall()
    return {r['partida_id']: dict(r) for r in rows}


def auto_programar(partidas: list, cronograma_map: dict) -> dict:
    """Asigna predecesoras secuenciales a partidas sin predecesoras configuradas.
    Cada partida sin pred. usa la anterior como predecesora — referenciada por
    su NÚMERO DE FILA (#) para que el usuario pueda digitar números cortos."""
    # Número de fila = posición entre TODAS las filas (alineado con cpm/# y MS Project).
    rownum = numerar_filas(partidas)
    order = [p for p in partidas if not p['es_titulo']]
    out = {}
    prev_n = None
    for p in order:
        cd = cronograma_map.get(p['id'], {})
        new_pred = cd.get('predecesoras', '') or ''
        if not new_pred and prev_n is not None:
            new_pred = str(prev_n)
        out[p['id']] = {
            'duracion': cd.get('duracion', 1) or 1,
            'inicio_dia': cd.get('inicio_dia', 1) or 1,
            'predecesoras': new_pred,
            'es_hito': cd.get('es_hito', 0) or 0,
            'segmentos': cd.get('segmentos', '') or '',
        }
        prev_n = rownum[p['id']]
    return out


# Fases típicas de construcción peruana en orden constructivo lógico.
# Cada fase tiene keywords que se buscan en la descripción de la partida.
# La primera fase cuyo keyword matchea es la asignada (orden = prioridad).
# Las fases marcadas `paralelo` no entran en la ruta crítica: corren desde
# el día 1 (sin anchor) y NO son anchor de la siguiente fase. Típicamente:
# obras provisionales, fletes/movilización, SST, limpieza permanente.
_FASES_CONSTRUCTIVAS = [
    # (clave, keywords, paralelo?)
    ('obras_prov', [
        'cartel de obra', 'cartel de identif', 'caseta de guardian',
        'almacén y oficina', 'almacen y oficina', 'comedor y vestuario',
        'baño químico', 'baño quimico', 'agua para consumo humano',
        'energía para la obra', 'energia para la obra',
        'plan de seguridad', 'equipos de protección', 'equipos de proteccion',
        'señalización', 'senalizacion', 'movilización', 'movilizacion',
        'flete', 'fletes', 'transporte de equipo', 'desmovilización',
        'desmovilizacion', 'seguridad y salud', 'sst',
    ], True),
    ('preliminares', [
        'trazo y replanteo', 'replanteo', 'trazo',
        'demolición', 'demolicion',
        'limpieza inicial', 'limpieza del terreno', 'limpieza de terreno',
        'desbroce', 'remoción', 'remocion',
    ], False),
    ('movimiento_tierras', [
        'excavación', 'excavacion', 'relleno', 'compactación', 'compactacion',
        'eliminación de material', 'eliminacion de material',
        'corte de terreno', 'nivelación', 'nivelacion',
        'perfilado', 'refine', 'conformación', 'conformacion',
    ], False),
    ('concreto_simple', [
        'solado', 'falsa zapata', 'cimiento corrido', 'sobrecimiento',
        'concreto simple', 'concreto ciclópeo', 'concreto ciclopeo',
    ], False),
    # ── ESTRUCTURAS — orden interno: ACERO → ENCOFRADO → CONCRETO ──
    ('acero', [
        'acero corrugado', 'acero de refuerzo', 'acero estructural',
        'habilitación de acero', 'habilitacion de acero',
        'acero fy', 'acero grado',
    ], False),
    ('encofrado', [
        'encofrado y desencofrado', 'encofrado',
        'desencofrado',
    ], False),
    ('concreto_armado', [
        'concreto armado', 'concreto fc', "concreto f'c",
        'concreto premezclado', 'concreto en zapata', 'concreto en columna',
        'concreto en viga', 'concreto en losa', 'concreto en placa',
        'concreto en escalera', 'vaciado de concreto',
        'zapata', 'columna', 'viga', 'losa', 'placa',
        'escalera', 'cisterna', 'tanque elevado',
        'muro de contención', 'muro de contencion',
    ], False),
    ('albanileria', [
        'muro de ladrillo', 'tabique', 'asentado', 'albañilería', 'albanileria',
        'ladrillo king kong', 'ladrillo pandereta',
    ], False),
    ('revoques', [
        'tarrajeo', 'vestidura', 'contrazócalo', 'contrazocalo', 'derrame',
        'enlucido', 'estucado', 'revoque',
    ], False),
    ('cobertura', [
        'cobertura', 'calamina', 'teja andina', 'impermeabilización',
        'impermeabilizacion', 'techo metálico', 'techo metalico',
    ], False),
    ('pisos', [
        'contrapiso', 'piso de cerámico', 'piso ceramico', 'porcelanato',
        'cemento pulido', 'vinílico', 'vinilico', 'parquet', 'losetas',
        'piso de cemento', 'piso ',
    ], False),
    ('carpinteria', [
        'puerta de madera', 'puerta metálica', 'puerta metalica', 'puerta',
        'ventana', 'mampara', 'mueble', 'baranda',
        'carpintería', 'carpinteria',
    ], False),
    ('vidrios', ['vidrio', 'cristal'], False),
    ('cerrajeria', [
        'chapa para puerta', 'cerradura', 'bisagra', 'cerrajería', 'cerrajeria',
        'manija',
    ], False),
    ('pintura', [
        'pintura', 'pintado', 'látex', 'latex', 'esmalte', 'barniz', 'pinturas',
    ], False),
    ('sanit', [
        'salida de agua', 'salida de desagüe', 'salida de desague',
        'red de distribución', 'red de distribucion',
        'inodoro', 'lavatorio', 'aparato sanitario',
        'ducha', 'lavadero', 'urinario',
        'tubería pvc-sap', 'tuberia pvc-sap', 'tubería de pvc',
        'caja de registro', 'medidor de agua',
        'red de agua', 'red de desagüe', 'red de desague',
        'instalaciones sanitarias', 'instalación sanitaria',
    ], False),
    ('electr', [
        'salida para centro', 'salida para tomacorriente', 'salida de fuerza',
        'tablero general', 'tablero de distribución', 'tablero',
        'luminaria', 'lámpara', 'lampara', 'interruptor', 'tomacorriente',
        'conduit', 'cable thw', 'cable nyy', 'pozo a tierra',
        'instalación eléctrica', 'instalacion electrica',
        'instalaciones eléctricas', 'instalaciones electricas',
    ], False),
    ('limpieza', [
        'limpieza final', 'limpieza permanente', 'limpieza de obra final',
        'limpieza general',
    ], True),
]


def _asignar_fase(descripcion: str) -> int:
    """Devuelve el índice de la fase constructiva que matchea, o len(FASES)
    como 'otros' (último)."""
    desc = (descripcion or '').lower()
    for idx, fase_def in enumerate(_FASES_CONSTRUCTIVAS):
        kws = fase_def[1]
        for kw in kws:
            if kw in desc:
                return idx
    return len(_FASES_CONSTRUCTIVAS)


def _fase_es_paralela(idx: int) -> bool:
    """¿Esta fase corre en paralelo sin entrar a la ruta crítica?
    (obras provisionales, fletes, SST, limpieza permanente)."""
    if idx < 0 or idx >= len(_FASES_CONSTRUCTIVAS):
        return False
    fase_def = _FASES_CONSTRUCTIVAS[idx]
    return bool(fase_def[2]) if len(fase_def) > 2 else False


def auto_programar_local(partidas: list, cronograma_map: dict) -> dict:
    """Auto-programa agrupando partidas en fases constructivas típicas
    (preliminares, mov.tierras, ACERO, ENCOFRADO, CONCRETO, albañilería,
    revoques, instalaciones, acabados...) y haciendo que cada fase arranque
    al final de la anterior, con paralelismo DENTRO de cada fase.

    Las fases marcadas como paralelas (obras provisionales, fletes, SST,
    limpieza permanente) NO entran en la ruta crítica: arrancan desde el
    día 1 sin predecesoras y no son anchor de la siguiente fase.

    Más realista que el secuencial puro — sin necesidad de IA. Las partidas
    que ya tienen predecesoras configuradas se respetan."""
    order = [p for p in partidas if not p['es_titulo']]
    # Mapa partida_id → número de fila (#) — numera TODAS las filas (alineado
    # con cpm/# y MS Project), para referenciar predecesoras con números cortos.
    rownum = numerar_filas(partidas)
    asign = {p['id']: _asignar_fase(p['descripcion']) for p in order}

    # Agrupar por fase, preservando orden de aparición
    fases = {}
    for p in order:
        fases.setdefault(asign[p['id']], []).append(p)

    # Anchor de cada fase = NÚMERO DE FILA de la última partida de la fase
    # anterior NO PARALELA. Las fases paralelas no anclan ni se anclan.
    fase_idx_sorted = sorted(fases.keys())
    anchors = {}
    prev_last_n = ''
    for f in fase_idx_sorted:
        if _fase_es_paralela(f):
            anchors[f] = ''   # paralela: arranca al día 1, sin anchor
        else:
            anchors[f] = prev_last_n
            prev_last_n = str(rownum[fases[f][-1]['id']])

    out = {}
    for p in order:
        cd = cronograma_map.get(p['id'], {})
        existing = (cd.get('predecesoras', '') or '').strip()
        if existing:
            new_pred = existing   # respetar lo que ya estaba
        else:
            new_pred = anchors.get(asign[p['id']], '')
        out[p['id']] = {
            'duracion': cd.get('duracion', 1) or 1,
            'inicio_dia': cd.get('inicio_dia', 1) or 1,
            'predecesoras': new_pred,
            'es_hito': cd.get('es_hito', 0) or 0,
            'segmentos': cd.get('segmentos', '') or '',
        }
    return out


def auto_programar_ia(partidas: list, cronograma_map: dict):
    """Auto-programa usando IA: el LLM analiza los nombres de las partidas
    y devuelve dependencias realistas (precedencias y paralelismos).

    Retorna (out_dict, error_str). En caso de éxito, error_str=None; en caso
    de falla retorna (None, mensaje) para que el caller haga fallback."""
    from core.ai_specs import _llamar_ia
    from core.database import get_config

    order = [p for p in partidas if not p['es_titulo']]
    if not order:
        return None, "No hay partidas hoja en el proyecto."

    api_key = get_config('api_key', '')

    # Numeración estilo MS Project Id (todas las filas) — alineada con el "#"
    # de la tabla y con las predecesoras que edita/lee el usuario.
    rownum = numerar_filas(partidas)
    lines = [f"#{rownum[p['id']]}  [{p['item']}]  {p['descripcion']}" for p in order]
    partidas_text = '\n'.join(lines)

    prompt = (
        "Eres un ingeniero civil residente de obra peruano con años de "
        "experiencia en cronogramas Gantt. A continuación tienes la lista de "
        "partidas de una obra numeradas (#1, #2, ...) con su código de item "
        "y descripción. Tu tarea es determinar las DEPENDENCIAS DE PRECEDENCIA "
        "para construir un cronograma realista, identificando la RUTA CRÍTICA "
        "correctamente.\n\n"
        f"PARTIDAS:\n{partidas_text}\n\n"
        "Devuelve un objeto JSON con este formato (las llaves son los NÚMEROS "
        "de partida, los valores son las predecesoras también como NÚMEROS):\n"
        '{\n'
        '  "<numero>": "<numeros predecesores separados por coma>",\n'
        '  ...\n'
        '}\n\n'
        "REGLAS CRÍTICAS:\n"
        "1. Para las partidas que arrancan el día 1, deja predecesoras como "
        "cadena vacía.\n"
        "2. Las predecesoras son NÚMEROS de fila (no items). Ejemplos: "
        "'5' o '3,4'. No uses ceros a la izquierda.\n\n"
        "3. ORDEN INTERNO EN ESTRUCTURAS (CRÍTICO — no invertir):\n"
        "   acero corrugado/refuerzo  →  encofrado  →  concreto armado/vaciado\n"
        "   Primero se ARMA el acero, luego se ENCOFRA, después se VACÍA concreto.\n\n"
        "4. ORDEN CONSTRUCTIVO GLOBAL:\n"
        "   preliminares (trazo, replanteo, demolición)\n"
        "   → movimiento de tierras (excavación, relleno)\n"
        "   → concreto simple (solado, falsa zapata, cimiento corrido)\n"
        "   → estructuras (acero → encofrado → concreto armado)\n"
        "   → albañilería (muros de ladrillo, tabiques)\n"
        "   → instalaciones sanitarias y eléctricas EN PARALELO\n"
        "   → revoques/tarrajeos\n"
        "   → pisos (contrapiso, cerámico)\n"
        "   → carpintería, vidrios, cerrajería (en paralelo)\n"
        "   → pintura\n"
        "   → limpieza final\n\n"
        "5. PARTIDAS NO CRÍTICAS (corren en paralelo DESDE EL DÍA 1, sin "
        "depender de nada, y NO son predecesoras de nadie):\n"
        "   - Obras provisionales (cartel de obra, caseta de guardianía, almacén, "
        "comedor, baños químicos, agua/energía para la obra)\n"
        "   - Fletes, movilización y desmovilización de equipos\n"
        "   - Seguridad y salud en obra (SST), señalización, EPPs\n"
        "   - Limpieza permanente / limpieza durante la obra\n"
        "   Estas partidas son administrativas/logísticas: NO deben formar "
        "parte de la ruta crítica.\n\n"
        "6. La ruta crítica debe pasar por las partidas estructurales y de "
        "mayor incidencia: movimiento de tierras → cimentación → estructuras → "
        "albañilería → acabados.\n\n"
        "7. Partidas similares del mismo nivel (ej. varios tipos de zapatas, "
        "varios muros) pueden tener la misma predecesora y ejecutarse en paralelo.\n\n"
        "8. Incluye TODOS los números recibidos en el JSON de salida.\n\n"
        "Responde ÚNICAMENTE con el JSON puro, sin texto adicional, sin "
        "comentarios, sin bloques de código markdown."
    )

    text, err = _llamar_ia(prompt, api_key, max_tokens=4000)
    if err:
        return None, f"Error IA: {err}"
    if not text:
        return None, "La IA no devolvió respuesta."

    # Limpiar posibles markdown blocks
    text = text.strip()
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    try:
        deps = json.loads(text)
    except json.JSONDecodeError as e:
        return None, f"La respuesta de IA no es JSON válido: {e}"

    out = {}
    for p in order:
        cd = cronograma_map.get(p['id'], {})
        # La IA devolvió predecesoras indexadas por número de fila; aceptamos
        # también el item como fallback en caso de que el LLM lo confunda.
        n = rownum[p['id']]
        pred = deps.get(str(n)) or deps.get(n) or deps.get(p['item'], '')
        if not isinstance(pred, str):
            pred = ''
        out[p['id']] = {
            'duracion': cd.get('duracion', 1) or 1,
            'inicio_dia': cd.get('inicio_dia', 1) or 1,
            'predecesoras': pred,
            'es_hito': cd.get('es_hito', 0) or 0,
            'segmentos': cd.get('segmentos', '') or '',
        }
    return out, None


def cargar_feriados_ia(anios: list):
    """Le pide a la IA los feriados oficiales de Perú para los años indicados.
    Retorna (lista_fechas, error_str). En éxito error_str=None."""
    from core.ai_specs import _llamar_ia
    from core.database import get_config

    if not anios:
        return None, "Sin años para consultar."

    api_key = get_config('api_key', '')
    anios_txt = ', '.join(str(a) for a in sorted(set(anios)))

    prompt = (
        "Necesito la lista oficial de FERIADOS NACIONALES de Perú para los "
        f"años {anios_txt}. Incluye TODOS los feriados nacionales declarados "
        "(no solo los principales). Considera tanto feriados fijos (Año Nuevo, "
        "Fiestas Patrias, Navidad…) como móviles (Jueves Santo, Viernes Santo).\n\n"
        "Responde ÚNICAMENTE con un objeto JSON, sin texto adicional, con "
        "este formato:\n"
        '{\n'
        '  "feriados": [\n'
        '    {"fecha": "YYYY-MM-DD", "nombre": "Nombre del feriado"},\n'
        '    ...\n'
        '  ]\n'
        '}\n\n'
        "Sin bloques de markdown, sin explicación, solo el JSON puro."
    )

    text, err = _llamar_ia(prompt, api_key, max_tokens=2000)
    if err:
        return None, f"Error IA: {err}"
    if not text:
        return None, "La IA no devolvió respuesta."

    text = text.strip()
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return None, f"Respuesta IA no es JSON válido: {e}"

    feriados = data.get('feriados') if isinstance(data, dict) else data
    if not isinstance(feriados, list):
        return None, "Formato inesperado de respuesta IA."

    fechas = []
    for f in feriados:
        if isinstance(f, dict):
            d = f.get('fecha') or f.get('date') or ''
        else:
            d = str(f)
        d = d.strip()
        if re.match(r'^\d{4}-\d{2}-\d{2}$', d):
            fechas.append(d)
    return sorted(set(fechas)), None


def calcular_duraciones_desde_metrado(partidas: list, jornada_horas: float = 8) -> dict:
    """Calcula duración estimada desde metrado/rendimiento.
    duracion_dias ≈ ceil(metrado / (rendimiento × jornada))"""
    out = {}
    for p in partidas:
        if p['es_titulo']:
            continue
        met = p['metrado'] or 0
        rend = p['rendimiento'] or 0
        if met > 0 and rend > 0:
            dur = max(1, math.ceil(met / rend))
            out[p['id']] = dur
    return out
