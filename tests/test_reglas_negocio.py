"""Tests de las reglas críticas de negocio (sin GUI).

Corre con:  venv/bin/python3 tests/test_reglas_negocio.py

Usa una COPIA temporal de presupuestos_seed.db (nunca la BD activa).
Protege las reglas de «Reglas críticas de negocio» de CLAUDE.md:
redondeo comercial, parcial WYSIWYG, decimales por ámbito, suma del ACU
(incl. overhead %MO/%MAT), recálculo de PU, detector PU≠ACU y coherencia
de calcular_totales.
"""
import sys, os, shutil, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import core.database as d

SEED = os.path.join(os.path.dirname(__file__), '..', 'presupuestos_seed.db')

_tmpdb = None

def _db_seed():
    """Copia temporal del seed; get_db() queda apuntando a ella."""
    global _tmpdb
    if _tmpdb is None:
        fd, _tmpdb = tempfile.mkstemp(suffix='_test.db')
        os.close(fd)
        shutil.copy(SEED, _tmpdb)
        d.DB_PATH = _tmpdb
    return d.get_db()


# ── Redondeo comercial (half-up, criterio S10/Delphin) ──────────────────────

def test_redondeo_half_up():
    assert d._r2(2.675) == 2.68          # float binario 2.674999… debe subir
    assert d._r2(0.125) == 0.13
    assert d._r2(1.004) == 1.00
    assert d._rn(2.67449, 3) == 2.674
    assert d._rn(None) == 0.0
    assert d._rn(0.00005, 4) == 0.0001


# ── parcial_wysiwyg: metrado y monto con decimales propios ──────────────────

def test_parcial_wysiwyg_separa_ambitos():
    dm, dp = d._DECIMALES_METRADO, d._DECIMALES_PPTO
    try:
        d.set_decimales_metrado(2); d.set_decimales_ppto(2)
        # metrado visible 12.35 × 10.555 = 130.35385 → 130.35
        assert d.parcial_wysiwyg(12.34567, 10.555) == 130.35
        d.set_decimales_metrado(4)
        # metrado visible 12.3457 × 10.555 → 130.31
        assert d.parcial_wysiwyg(12.34567, 10.555) == 130.31
        # None / 0 no rompen
        assert d.parcial_wysiwyg(None, 10) == 0.0
        assert d.parcial_wysiwyg(10, None) == 0.0
    finally:
        d.set_decimales_metrado(dm); d.set_decimales_ppto(dp)


# ── Derivación de cantidad ACU: cuadrilla / rendimiento (× jornada) ─────────

def test_cantidad_derivada_cuadrilla():
    dc = d._DECIMALES_CANT_ACU
    try:
        d.set_decimales_cant_acu(4)
        n = d.get_decimales_cant_acu()
        # MO/EQ por hora: cant = cuadrilla / rendimiento × jornada
        assert d._rn(2 / 25 * 8, n) == 0.64
        assert d._rn(1 / 3.5 * 8, n) == 2.2857
        # MO/EQ por día: sin jornada
        assert d._rn(1 / 3.5, n) == 0.2857
    finally:
        d.set_decimales_cant_acu(dc)


# ── Clasificación canónica de insumos derivados de la cuadrilla ─────────────

def test_clasificacion_cantidad_cuadrilla():
    # MO y equipo por hora (hh/hm) → cantidad derivada de la cuadrilla.
    assert d.recurso_por_hora('MO', 'hh')
    assert d.recurso_por_hora('EQ', 'hm')          # ← el bug: hm DEBE contar
    assert d.recurso_por_hora('MO', 'día')         # MO siempre, cualquier unidad
    assert not d.recurso_por_hora('MAT', 'm3')
    assert not d.recurso_por_hora('EQ', 'día')     # equipo-día NO es por hora
    # Por día (día/jor) → derivado SIN jornada.
    assert d.recurso_por_dia('EQ', 'día')
    assert d.recurso_por_dia('MO', 'jor')
    assert not d.recurso_por_dia('MAT', 'día')     # material nunca se deriva
    # Partida global (glb/est/serv) → cantidad directa.
    assert d.partida_global('glb') and d.partida_global('EST')
    assert not d.partida_global('m3')


# ── Recálculo al cambiar rendimiento / jornada (incluye equipo por hora) ────

def _recalc_item(it, rend, jornada):
    """Réplica de la regla canónica de los handlers de rendimiento/jornada
    (proyecto_view._guardar_rendimiento, nuevo_proyecto_view, proyecto_form_dialog):
    devuelve la nueva cantidad, o la original si el insumo es de cantidad directa."""
    cuad = it['cuadrilla'] or 0
    if cuad <= 0:
        return it['cantidad']
    por_dia = d.recurso_por_dia(it['tipo'], it['unidad'])
    if not (por_dia or d.recurso_por_hora(it['tipo'], it['unidad'])):
        return it['cantidad']
    factor = 1 if por_dia else jornada
    return d._rn(cuad / rend * factor, d.get_decimales_cant_acu())


def test_recalculo_incluye_equipo_por_hora():
    """Regresión del bug hm: al cambiar rendimiento/jornada se recalculan MO Y
    equipo por hora (hm); MAT, equipo-día sin cuadrilla y overhead conservan su
    cantidad; la MO/EQ por día se recalcula SIN multiplicar por la jornada."""
    dc = d._DECIMALES_CANT_ACU
    try:
        d.set_decimales_cant_acu(4)
        items = [
            {'tipo': 'MO',  'unidad': 'hh',  'cuadrilla': 1.0, 'cantidad': 0.0267},  # quedó en rend 300
            {'tipo': 'EQ',  'unidad': 'hm',  'cuadrilla': 1.0, 'cantidad': 0.0267},  # ← el caso del bug
            {'tipo': 'MAT', 'unidad': 'gln', 'cuadrilla': 0.0, 'cantidad': 0.1202},  # directo
            {'tipo': 'EQ',  'unidad': 'día', 'cuadrilla': 0.0, 'cantidad': 5.0},     # equipo-día directo
            {'tipo': 'MO',  'unidad': 'día', 'cuadrilla': 1.0, 'cantidad': 99.0},    # MO-día (sin jornada)
            {'tipo': 'EQ',  'unidad': '%MO', 'cuadrilla': 0.0, 'cantidad': 3.0},     # overhead
        ]
        out = [_recalc_item(it, 200.0, 8) for it in items]
        assert out[0] == 0.04                  # MO hh:  1/200×8
        assert out[1] == 0.04                  # EQ hm:  recalculado igual que MO  ← clave
        assert out[2] == 0.1202                # MAT:    intacto
        assert out[3] == 5.0                   # EQ-día sin cuadrilla: intacto
        assert out[4] == d._rn(1 / 200, 4)     # MO-día: cuad/rend SIN jornada
        assert out[5] == 3.0                   # overhead %: intacto
    finally:
        d.set_decimales_cant_acu(dc)


# ── Suma del ACU: parciales redondeados + overhead %MO/%MAT al final ────────

def test_pu_desde_items_overhead():
    items = [
        {'cantidad': 2.0,  'precio': 10.0, 'unidad': 'hh',  'tipo': 'MO'},   # 20.00
        {'cantidad': 1.0,  'precio': 50.0, 'unidad': 'kg',  'tipo': 'MAT'},  # 50.00
        {'cantidad': 5.0,  'precio': 0.0,  'unidad': '%MO', 'tipo': 'EQ'},   # 5% de MO = 1.00
    ]
    assert d._pu_desde_items(items) == 71.0
    # %MAT usa la base de materiales
    items[2]['unidad'] = '%MAT'
    assert d._pu_desde_items(items) == 72.5
    # cada parcial se redondea ANTES de sumar (0.333×3 = 1.00, no 0.999→1.0)
    items3 = [{'cantidad': 0.333, 'precio': 1.0, 'unidad': 'u', 'tipo': 'MAT'}] * 3
    assert d._pu_desde_items(items3) == 0.99
    # tipo desconocido cae a MAT, no se pierde
    assert d._pu_desde_items([{'cantidad': 1, 'precio': 7, 'unidad': 'u', 'tipo': 'XX'}]) == 7.0


# ── _recalcular_pu y detector PU≠ACU sobre datos reales del seed ────────────

def _proyecto_sano(conn):
    """Primer proyecto del seed sin inconsistencias PU↔ACU."""
    for (prid,) in conn.execute("SELECT id FROM proyectos ORDER BY id"):
        if not d.partidas_pu_inconsistente(conn, prid):
            n = conn.execute(
                """SELECT COUNT(*) FROM partidas p WHERE p.proyecto_id=? AND p.es_titulo=0
                   AND EXISTS (SELECT 1 FROM acu_items ai WHERE ai.partida_id=p.id)""",
                (prid,)).fetchone()[0]
            if n > 5:
                return prid
    raise AssertionError("el seed no tiene ningún proyecto consistente PU↔ACU")

def test_detector_y_recalculo_pu():
    conn = _db_seed()
    try:
        prid = _proyecto_sano(conn)
        part = conn.execute(
            """SELECT p.id, p.precio_unitario FROM partidas p
               WHERE p.proyecto_id=? AND p.es_titulo=0
               AND EXISTS (SELECT 1 FROM acu_items ai WHERE ai.partida_id=p.id)
               AND p.precio_unitario > 1 LIMIT 1""", (prid,)).fetchone()
        pu_bueno = part['precio_unitario']

        # 1. romper el PU → el detector lo encuentra
        conn.execute("UPDATE partidas SET precio_unitario=? WHERE id=?",
                     (pu_bueno + 100, part['id']))
        inc = d.partidas_pu_inconsistente(conn, prid)
        assert any(x['partida_id'] == part['id'] for x in inc), "detector no vio el PU roto"
        roto = next(x for x in inc if x['partida_id'] == part['id'])
        assert roto['pu_acu'] == pu_bueno

        # 2. _recalcular_pu lo repara y el detector vuelve a 0
        nuevo = d._recalcular_pu(conn, part['id'])
        assert nuevo == pu_bueno
        assert not any(x['partida_id'] == part['id']
                       for x in d.partidas_pu_inconsistente(conn, prid))

        # 3. partida sin ACU (PU manual) nunca aparece en el detector
        conn.execute("UPDATE partidas SET precio_unitario=? WHERE id=?",
                     (pu_bueno + 100, part['id']))
        conn.execute("DELETE FROM acu_items WHERE partida_id=?", (part['id'],))
        assert not any(x['partida_id'] == part['id']
                       for x in d.partidas_pu_inconsistente(conn, prid))
        conn.rollback()
    finally:
        conn.close()


# ── calcular_totales: coherencia CD / total ─────────────────────────────────

def test_calcular_totales_coherente():
    conn = _db_seed()
    try:
        prid = _proyecto_sano(conn)
    finally:
        conn.close()
    items, t = d.calcular_totales(prid)
    assert t['cd'] > 0
    # CD = suma de parciales WYSIWYG de las partidas hoja
    cd_manual = sum(d.parcial_wysiwyg(e['partida']['metrado'],
                                      e['partida']['precio_unitario'])
                    for e in items if not e['partida']['es_titulo'])
    assert abs(t['cd'] - cd_manual) < 0.01, (t['cd'], cd_manual)
    # Presupuesto Total = CD + GG + utilidad + IGV — nunca menor que el CD
    assert t['total'] >= t['cd'] - 0.01
    assert t['igv'] >= 0 and t['subtotal'] >= t['cd'] - 0.01


# ── Precios por proyecto: COALESCE(ai.precio, r.precio, 0) ──────────────────

def test_precio_coalesce():
    conn = _db_seed()
    try:
        prid = _proyecto_sano(conn)
        row = conn.execute(
            """SELECT ai.id, ai.partida_id, ai.precio, r.precio AS cat
               FROM acu_items ai
                 JOIN partidas p ON p.id=ai.partida_id
                 JOIN recursos r ON r.id=ai.recurso_id
               WHERE p.proyecto_id=? AND r.precio > 0
                 AND SUBSTR(COALESCE(r.unidad,''),1,1) != '%' LIMIT 1""",
            (prid,)).fetchone()
        # ai.precio NULL → rige el precio del catálogo
        conn.execute("UPDATE acu_items SET precio=NULL WHERE id=?", (row['id'],))
        eff = conn.execute(
            """SELECT COALESCE(ai.precio, r.precio, 0) e FROM acu_items ai
               JOIN recursos r ON r.id=ai.recurso_id WHERE ai.id=?""",
            (row['id'],)).fetchone()['e']
        assert eff == row['cat']
        # ai.precio puesto → rige el del proyecto aunque difiera del catálogo
        conn.execute("UPDATE acu_items SET precio=? WHERE id=?",
                     (row['cat'] + 7, row['id']))
        eff = conn.execute(
            """SELECT COALESCE(ai.precio, r.precio, 0) e FROM acu_items ai
               JOIN recursos r ON r.id=ai.recurso_id WHERE ai.id=?""",
            (row['id'],)).fetchone()['e']
        assert eff == row['cat'] + 7
        conn.rollback()
    finally:
        conn.close()


# ── Estados: matriz de bloqueo por nivel ────────────────────────────────────

def test_estados_bloqueo():
    from core.config import puede_editar
    # Solo «elaboracion» permite editar el presupuesto (partidas/ACU/PU);
    # el detector PU≠ACU y «unificar precios» dependen de esta matriz.
    for estado in ('revision', 'aprobado', 'ejecutado'):
        assert not puede_editar(estado, 'presupuesto'), estado
        assert not puede_editar(estado, 'pie'), estado
    assert puede_editar('elaboracion', 'presupuesto')
    assert puede_editar('revision', 'specs')        # specs editable en revisión
    assert puede_editar('aprobado', 'cronograma')   # cronograma hasta ejecutado
    assert not puede_editar('ejecutado', 'cronograma')
    assert puede_editar(None, 'presupuesto')        # sin estado = elaboración


# ── Importador .prs: ACU completo y CD fiel (solo si hay archivos reales) ───

def test_importador_prs_reconcilia():
    import shutil as _sh
    archivos = [p for p in (
        os.path.expanduser('~/Descargas/TROCHA CHICHAS.prs'),
        os.path.expanduser('~/Documentos/ET Plaza Yanque/Base de datos Plaza Yanque.prs'),
    ) if os.path.isfile(p)]
    if not archivos or not _sh.which('mdb-export'):
        print("      (saltado: sin archivos .prs de prueba o sin mdbtools)")
        return
    from core.powercost_prs_importer import import_powercost_prs
    for prs in archivos:
        info, partidas, acus, recursos, metrados = import_powercost_prs(prs)
        for p in partidas:
            if p.get('es_titulo') or p['item'] not in acus:
                continue
            cu = d._pu_desde_items(acus[p['item']]['items'])
            dif = abs(cu - (p['precio_unitario'] or 0))
            # ≤ 2 céntimos: criterio de redondeo PowerCost vs app (tolerado
            # por el detector). Más que eso = desglose incompleto (regresión).
            assert dif <= 0.0205, \
                f"{os.path.basename(prs)} {p['item']}: PU={p['precio_unitario']} vs ACU={cu}"


if __name__ == "__main__":
    fallos = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print(f"  OK  {name}")
            except AssertionError as e:
                fallos += 1
                print(f"  FAIL {name}: {e}")
    if _tmpdb and os.path.exists(_tmpdb):
        os.unlink(_tmpdb)
    sys.exit(1 if fallos else 0)
