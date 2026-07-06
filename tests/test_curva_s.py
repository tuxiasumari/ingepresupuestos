"""Tests del Control de Obra · Curva S real — sin GUI.

Corre con:  venv/bin/python3 tests/test_curva_s.py

Verifica helpers de ventanas (rodante y fin de mes), distribución, interpolación,
overrides por período (prog/reprog/real, monto↔%ejec vía acumulado derivado) y la
curva comparada de punta a punta con un cronograma mínimo + valorización.
Ver `[[project_modulo_ejecucion_obra]]`.
"""
import sys, os, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import core.database as d

_tmpdb = None
_PID = None


def _setup():
    """Proyecto: inicio 2026-06-01, plazo 90, 1 partida (metrado 100, PU 100 →
    base 10 000) con cronograma día 1..90. Valorización N°1 jun (avance 30%)."""
    global _tmpdb, _PID
    if _PID is not None:
        return _PID
    fd, _tmpdb = tempfile.mkstemp(suffix='_curvatest.db')
    os.close(fd)
    d.DB_PATH = _tmpdb
    d.set_decimales_metrado(2); d.set_decimales_ppto(2)
    d.init_db()
    conn = d.get_db()
    _PID = conn.execute(
        "INSERT INTO proyectos (nombre, estado, fecha_inicio, plazo) "
        "VALUES ('OBRA CURVA','ejecutado','2026-06-01',90)").lastrowid
    part = conn.execute(
        "INSERT INTO partidas (proyecto_id, item, descripcion, unidad, metrado, "
        "precio_unitario, nivel, es_titulo) VALUES (?,'01','MURO','m2',100,100,1,0)",
        (_PID,)).lastrowid
    conn.execute("INSERT INTO cronograma_partidas (partida_id, duracion, "
                 "inicio_dia) VALUES (?,90,1)", (part,))
    conn.commit(); conn.close()
    import core.valorizacion as V
    v1 = V.crear_valorizacion(_PID, '2026-06-01', '2026-06-30')
    V.set_metrado_ejecutado(v1, part, 30)   # 30 m2 → 30% del avance
    return _PID


import core.curva_s as CS


def test_ventanas_rodante():
    v, lab = CS._ventanas('mes', None, 90)
    assert v == [(1, 30), (31, 60), (61, 90)]
    assert lab == ['Mes1', 'Mes2', 'Mes3']


def test_ventanas_mes_calendario():
    from datetime import date
    # Obra arranca a mitad de mes: primer mes parcial (15..30 jun = 16 días).
    v, lab = CS._ventanas('mes_cal', date(2026, 6, 15), 90)
    assert v[0] == (1, 16)             # 15→30 jun
    assert lab[0] == 'Jun 26'
    assert v[1][0] == 17 and lab[1] == 'Jul 26'


def test_distribuir_ventanas():
    # Partida de 900 repartida en 90 días, ventanas de 30 → 300 cada una.
    out = CS._distribuir_ventanas('', 1, 90, 900.0, [(1, 30), (31, 60), (61, 90)])
    assert [round(x, 2) for x in out] == [300.0, 300.0, 300.0]


def test_interp_pts():
    pts = [(0.0, 0.0), (1.0, 50.0), (2.0, 80.0)]
    assert CS._interp_pts(pts, 0.5) == 25.0
    assert CS._interp_pts(pts, 1.5) == 65.0
    assert CS._interp_pts(pts, 3.0) == 80.0    # más allá → último


def test_override_crud():
    pid = _setup()
    CS.limpiar_reprogramacion(pid)
    CS.set_override(pid, 'mes', 1, 'reprog', 40)
    CS.set_override(pid, 'mes', 1, 'label', 'PRIMERO')
    ov = CS.get_overrides(pid, 'mes')
    assert ov[1]['reprog'] == 40 and ov[1]['label'] == 'PRIMERO'
    assert ov[1]['prog'] is None
    # Borrar el reprog deja la fila (aún tiene label).
    CS.set_override(pid, 'mes', 1, 'reprog', None)
    ov = CS.get_overrides(pid, 'mes')
    assert ov[1]['reprog'] is None and ov[1]['label'] == 'PRIMERO'
    # Borrar el label también → fila desaparece (vacía).
    CS.set_override(pid, 'mes', 1, 'label', None)
    assert 1 not in CS.get_overrides(pid, 'mes')
    CS.limpiar_reprogramacion(pid)


def test_curva_comparada_programado_y_real():
    pid = _setup()
    CS.limpiar_reprogramacion(pid)
    d_ = CS.curva_s_comparada(pid, 'mes')
    assert round(d_['total_general'], 2) == 10000.0
    # Programado acumula a 100% al final.
    assert round(d_['filas'][-1]['p_acu'], 1) == 100.0
    # Real: valorización de junio (30%) cae en el período 1.
    f1 = d_['filas'][0]
    assert round(f1['x_acu'], 1) == 30.0
    assert round(f1['x_mon'], 0) == 3000.0     # 30% de 10 000


def test_reprog_por_periodo_y_montos():
    pid = _setup()
    CS.limpiar_reprogramacion(pid)
    # Reprogramado por período: 20% y 50% (acumula 20, 70).
    CS.set_override(pid, 'mes', 1, 'reprog', 20)
    CS.set_override(pid, 'mes', 2, 'reprog', 50)
    d_ = CS.curva_s_comparada(pid, 'mes')
    f = d_['filas']
    assert round(f[0]['r_acu'], 1) == 20.0 and round(f[1]['r_acu'], 1) == 70.0
    assert round(f[0]['r_mon'], 0) == 2000.0   # 20% de 10 000
    # Período 3 sin valor → acumulado se mantiene plano.
    assert round(f[2]['r_acu'], 1) == 70.0 and f[2]['r_eje'] is None
    CS.limpiar_reprogramacion(pid)


def test_override_real_manual():
    pid = _setup()
    CS.limpiar_reprogramacion(pid)
    # Override manual del real en el período 2 (+25%). Junio real = 30% (valoriz).
    CS.set_override(pid, 'mes', 2, 'real', 25)
    d_ = CS.curva_s_comparada(pid, 'mes')
    assert round(d_['filas'][0]['x_acu'], 1) == 30.0
    assert round(d_['filas'][1]['x_acu'], 1) == 55.0   # 30 + 25
    CS.limpiar_reprogramacion(pid)


def test_denominador_presupuesto_completo():
    """Partida sin cronograma: total_general = presupuesto COMPLETO (comparable con
    el real); la programada no llega a 100% por el trabajo sin programar."""
    conn = d.get_db()
    pid2 = conn.execute("INSERT INTO proyectos (nombre, fecha_inicio, plazo) "
                        "VALUES ('MIXTA','2026-06-01',60)").lastrowid
    p1 = conn.execute("INSERT INTO partidas (proyecto_id, item, descripcion, "
                      "metrado, precio_unitario, nivel, es_titulo) "
                      "VALUES (?,'01','A',100,100,1,0)", (pid2,)).lastrowid
    conn.execute("INSERT INTO partidas (proyecto_id, item, descripcion, metrado, "
                 "precio_unitario, nivel, es_titulo) VALUES (?,'02','B',100,100,1,0)",
                 (pid2,))            # B sin cronograma
    conn.execute("INSERT INTO cronograma_partidas (partida_id, duracion, "
                 "inicio_dia) VALUES (?,60,1)", (p1,))
    conn.commit(); conn.close()
    dd = CS.curva_s_comparada(pid2, 'mes')
    assert round(dd['total_general'], 2) == 20000.0     # A + B, no solo A
    assert round(dd['filas'][-1]['p_acu'], 1) == 50.0   # solo A programada → 50%


def test_sin_cronograma_no_rompe():
    """Proyecto sin cronograma ni valorizaciones: total 0, sin excepciones."""
    conn = d.get_db()
    pid2 = conn.execute("INSERT INTO proyectos (nombre, fecha_inicio, plazo) "
                        "VALUES ('SIN CRON','', 0)").lastrowid
    conn.commit(); conn.close()
    d_ = CS.curva_s_comparada(pid2, 'mes_cal')
    assert d_['total_general'] == 0
    assert isinstance(d_['filas'], list)   # no revienta


if __name__ == "__main__":
    fallos = 0
    orden = [test_ventanas_rodante, test_ventanas_mes_calendario,
             test_distribuir_ventanas, test_interp_pts, test_override_crud,
             test_curva_comparada_programado_y_real, test_reprog_por_periodo_y_montos,
             test_override_real_manual, test_denominador_presupuesto_completo,
             test_sin_cronograma_no_rompe]
    for fn in orden:
        try:
            fn(); print(f"  OK  {fn.__name__}")
        except AssertionError as e:
            fallos += 1; print(f"  FAIL {fn.__name__}: {e}")
        except Exception as e:
            fallos += 1
            import traceback; traceback.print_exc()
            print(f"  ERROR {fn.__name__}: {e!r}")
    if _tmpdb and os.path.exists(_tmpdb):
        os.unlink(_tmpdb)
    print("OK" if not fallos else f"{fallos} fallo(s)")
    sys.exit(1 if fallos else 0)
