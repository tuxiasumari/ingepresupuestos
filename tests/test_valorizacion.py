"""Tests del Control de Obra · Fase 1 — valorización de avance (sin GUI).

Corre con:  venv/bin/python3 tests/test_valorizacion.py

Usa una BD temporal LIMPIA (no el seed ni la BD activa) con un proyecto
controlado, para verificar la derivación base/anterior/actual/acumulado/saldo/%
y las reglas de cabecera (correlativo, cerrar bloquea, borrar solo la última).
Ver `[[project_modulo_ejecucion_obra]]`.
"""
import sys, os, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import core.database as d

_tmpdb = None
_PID = None


def _setup():
    """BD temporal limpia + proyecto con 1 título y 2 partidas conocidas.
        01      MOVIMIENTO DE TIERRAS      (título)
        01.01   Excavación   m3  metr 100  PU 50  → base 5000
        01.02   Relleno      m3  metr 200  PU 20  → base 4000
                                              base total = 9000
    """
    global _tmpdb, _PID
    if _PID is not None:
        return _PID
    fd, _tmpdb = tempfile.mkstemp(suffix='_valtest.db')
    os.close(fd)
    d.DB_PATH = _tmpdb
    d.set_decimales_metrado(2); d.set_decimales_ppto(2)
    d.init_db()
    conn = d.get_db()
    cur = conn.execute("INSERT INTO proyectos (nombre, estado) VALUES ('OBRA TEST','ejecutado')")
    _PID = cur.lastrowid
    parts = [
        ('01',    'MOVIMIENTO DE TIERRAS', '',   0,   0, 1, 1),
        ('01.01', 'EXCAVACIÓN',            'm3', 100, 50, 2, 0),
        ('01.02', 'RELLENO',               'm3', 200, 20, 2, 0),
    ]
    for item, desc, und, metr, pu, niv, tit in parts:
        conn.execute(
            "INSERT INTO partidas (proyecto_id, item, descripcion, unidad, "
            "metrado, precio_unitario, nivel, es_titulo) VALUES (?,?,?,?,?,?,?,?)",
            (_PID, item, desc, und, metr, pu, niv, tit))
    conn.commit(); conn.close()
    return _PID


def _fila(filas, item):
    return next(f for f in filas if f['item'] == item)


import core.valorizacion as V


# ── Cabecera: correlativo ────────────────────────────────────────────────────

def test_correlativo():
    pid = _setup()
    assert V.listar_valorizaciones(pid) == []
    v1 = V.crear_valorizacion(pid, '2026-02-01', '2026-02-28')
    v2 = V.crear_valorizacion(pid, '2026-03-01', '2026-03-31')
    nums = [v['numero'] for v in V.listar_valorizaciones(pid)]
    assert nums == [1, 2]
    assert V.get_valorizacion(v1)['numero'] == 1
    assert V.get_valorizacion(v2)['numero'] == 2


# ── Cálculo de un único período (actual = acumulado, anterior = 0) ───────────

def test_valorizacion_periodo_1():
    pid = _setup()
    v1 = V.listar_valorizaciones(pid)[0]['id']
    # 01.01 ejecuta 40 (→2000), 01.02 ejecuta 50 (→1000)
    assert V.set_metrado_ejecutado(v1, _fila(_partidas(pid), '01.01')['id'], 40)
    assert V.set_metrado_ejecutado(v1, _fila(_partidas(pid), '01.02')['id'], 50)
    filas, resumen = V.get_valorizacion_detalle(v1)

    f1 = _fila(filas, '01.01')
    assert f1['base_val'] == 5000 and f1['ant_val'] == 0
    assert f1['act_metr'] == 40 and f1['act_val'] == 2000
    assert f1['acu_val'] == 2000 and f1['sal_val'] == 3000
    assert round(f1['pct'], 2) == 40.00            # 2000/5000

    f2 = _fila(filas, '01.02')
    assert f2['act_val'] == 1000 and f2['sal_val'] == 3000

    # Título 01 = suma de hijos
    t = _fila(filas, '01')
    assert t['es_titulo'] == 1
    assert t['base_val'] == 9000 and t['acu_val'] == 3000

    # Resumen global
    assert resumen['base_val'] == 9000 and resumen['acu_val'] == 3000
    assert round(resumen['pct_fisico'], 2) == 33.33   # 3000/9000


# ── Dos períodos: anterior + actual = acumulado ─────────────────────────────

def test_valorizacion_periodo_2_acumula():
    pid = _setup()
    vals = V.listar_valorizaciones(pid)
    v2 = vals[1]['id']
    # Período 2: 01.01 ejecuta 30 (→1500), 01.02 ejecuta 100 (→2000)
    V.set_metrado_ejecutado(v2, _fila(_partidas(pid), '01.01')['id'], 30)
    V.set_metrado_ejecutado(v2, _fila(_partidas(pid), '01.02')['id'], 100)
    filas, resumen = V.get_valorizacion_detalle(v2)

    f1 = _fila(filas, '01.01')   # anterior 40(2000) + actual 30(1500)
    assert f1['ant_val'] == 2000 and f1['act_val'] == 1500
    assert f1['acu_metr'] == 70 and f1['acu_val'] == 3500
    assert f1['sal_val'] == 1500 and round(f1['pct'], 2) == 70.00

    f2 = _fila(filas, '01.02')   # anterior 50(1000) + actual 100(2000)
    assert f2['acu_metr'] == 150 and f2['acu_val'] == 3000
    assert f2['sal_val'] == 1000 and round(f2['pct'], 2) == 75.00

    # Resumen acumulado del período 2
    assert resumen['ant_val'] == 3000 and resumen['act_val'] == 3500
    assert resumen['acu_val'] == 6500 and resumen['sal_val'] == 2500
    assert round(resumen['pct_fisico'], 2) == 72.22   # 6500/9000


# ── Cerrar bloquea edición; borrar solo la última y abierta ─────────────────

def test_cerrar_y_eliminar():
    pid = _setup()
    vals = V.listar_valorizaciones(pid)
    v1, v2 = vals[0]['id'], vals[1]['id']
    pid_part = _fila(_partidas(pid), '01.01')['id']

    # No se puede borrar la N°1 (no es la última)
    assert V.eliminar_valorizacion(v1) is False
    # Cerrar la N°1 → no admite más edición
    V.cerrar_valorizacion(v1)
    assert V.set_metrado_ejecutado(v1, pid_part, 99) is False
    V.reabrir_valorizacion(v1)
    assert V.set_metrado_ejecutado(v1, pid_part, 40) is True   # restaura valor
    # La última (N°2) abierta sí se borra
    assert V.eliminar_valorizacion(v2) is True
    assert [v['numero'] for v in V.listar_valorizaciones(pid)] == [1]
    # Recrear la N°2 para no afectar otros tests si se reordenan
    V.crear_valorizacion(pid, '2026-03-01', '2026-03-31')


def _partidas(pid):
    conn = d.get_db()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM partidas WHERE proyecto_id=? ORDER BY item", (pid,))]
    finally:
        conn.close()


if __name__ == "__main__":
    fallos = 0
    # Orden explícito: el correlativo y los períodos dependen del estado previo.
    orden = [test_correlativo, test_valorizacion_periodo_1,
             test_valorizacion_periodo_2_acumula, test_cerrar_y_eliminar]
    for fn in orden:
        try:
            fn()
            print(f"  OK  {fn.__name__}")
        except AssertionError as e:
            fallos += 1
            print(f"  FAIL {fn.__name__}: {e}")
        except Exception as e:
            fallos += 1
            import traceback; traceback.print_exc()
            print(f"  ERROR {fn.__name__}: {e!r}")
    if _tmpdb and os.path.exists(_tmpdb):
        os.unlink(_tmpdb)
    sys.exit(1 if fallos else 0)
