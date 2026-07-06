"""Tests del Control de Obra · Almacén (kárdex de materiales) — sin GUI.

Corre con:  venv/bin/python3 tests/test_almacen.py

BD temporal limpia. Verifica: ingresado/consumido acumulado, control_almacen
(Pedido·Ingresado·Consumido·Stock·Por llegar, solo tipo MAT) y el kárdex por día
(movimientos entrada/salida). Ver `[[project_modulo_ejecucion_obra]]`.
"""
import sys, os, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import core.database as d

_tmpdb = None
_PID = None
_R = {}   # nombre → recurso_id


def _setup():
    """Proyecto con 1 material (CEMENTO, MAT) y 1 equipo (MEZCLADORA, EQ).
    Requerido 1000 (req N°1), ingresado 600+400, consumido 700 (cuaderno)."""
    global _tmpdb, _PID
    if _PID is not None:
        return _PID
    fd, _tmpdb = tempfile.mkstemp(suffix='_almtest.db')
    os.close(fd)
    d.DB_PATH = _tmpdb
    d.init_db()
    conn = d.get_db()
    _PID = conn.execute("INSERT INTO proyectos (nombre, estado) VALUES "
                        "('OBRA ALM','ejecutado')").lastrowid
    for nom, tipo, und in [('CEMENTO', 'MAT', 'BOL'), ('MEZCLADORA', 'EQ', 'HM')]:
        rid = conn.execute("INSERT INTO recursos (descripcion, tipo, unidad, "
                           "precio) VALUES (?,?,?,0)", (nom, tipo, und)).lastrowid
        _R[nom] = rid
    conn.commit(); conn.close()

    import core.almacen as ALM
    ALM.agregar_ingreso(_PID, _R['CEMENTO'], '2026-06-10', 600, 'CEMENTO', 'BOL')
    ALM.agregar_ingreso(_PID, _R['CEMENTO'], '2026-06-20', 400, 'CEMENTO', 'BOL')

    # Requerimiento (pedido 1000 de cemento).
    conn = d.get_db()
    rq = conn.execute("INSERT INTO requerimientos (proyecto_id, numero, tipo) "
                      "VALUES (?,1,'mat')", (_PID,)).lastrowid
    conn.execute("INSERT INTO requerimiento_detalle (requerimiento_id, tipo, "
                 "recurso_id, cantidad) VALUES (?,'mat',?,1000)", (rq, _R['CEMENTO']))
    # Consumo: 2 partes de cemento (700 total) + 1 de equipo (no debe entrar).
    p1 = conn.execute("INSERT INTO parte_diario (proyecto_id, fecha, estado) "
                      "VALUES (?,'2026-06-15','abierto')", (_PID,)).lastrowid
    p2 = conn.execute("INSERT INTO parte_diario (proyecto_id, fecha, estado) "
                      "VALUES (?,'2026-06-25','abierto')", (_PID,)).lastrowid
    conn.execute("INSERT INTO parte_diario_recurso (parte_id, clase, recurso_id, "
                 "cantidad) VALUES (?,'mat',?,400)", (p1, _R['CEMENTO']))
    conn.execute("INSERT INTO parte_diario_recurso (parte_id, clase, recurso_id, "
                 "cantidad) VALUES (?,'mat',?,300)", (p2, _R['CEMENTO']))
    conn.execute("INSERT INTO parte_diario_recurso (parte_id, clase, recurso_id, "
                 "cantidad) VALUES (?,'eq',?,5)", (p1, _R['MEZCLADORA']))
    conn.commit(); conn.close()
    return _PID


import core.almacen as ALM
import core.requerimientos as REQ
import core.parte_diario as PD


def test_ingresado_acumulado():
    pid = _setup()
    assert ALM.ingresado_acumulado(pid)[_R['CEMENTO']] == 1000.0


def test_consumido_acumulado_solo_recurso():
    pid = _setup()
    cons = PD.consumido_acumulado(pid)
    assert cons[_R['CEMENTO']] == 700.0
    # El equipo (eq) SÍ está en consumido_acumulado (mat/eq/sc)...
    assert _R['MEZCLADORA'] in cons


def test_control_almacen_solo_materiales():
    pid = _setup()
    filas = REQ.control_almacen(pid)
    # Solo el material (MAT); el equipo queda fuera del almacén.
    assert [f['descripcion'] for f in filas] == ['CEMENTO']
    f = filas[0]
    assert f['pedido'] == 1000 and f['ingresado'] == 1000
    assert f['consumido'] == 700
    assert f['stock'] == 300           # ingresado − consumido
    assert f['por_llegar'] == 0        # pedido − ingresado (no negativo)


def test_kardex_movimientos_y_stock():
    pid = _setup()
    mov = ALM.movimientos(pid, _R['CEMENTO'])
    # Orden por fecha; entrada antes que salida el mismo día.
    tipos = [(m['fecha'], m['tipo'], m['cantidad']) for m in mov]
    assert tipos == [
        ('2026-06-10', 'entrada', 600.0),
        ('2026-06-15', 'salida', 400.0),
        ('2026-06-20', 'entrada', 400.0),
        ('2026-06-25', 'salida', 300.0),
    ]
    # Stock corrido: 600, 200, 600, 300.
    stock = 0.0; corr = []
    for m in mov:
        stock += m['cantidad'] if m['tipo'] == 'entrada' else -m['cantidad']
        corr.append(stock)
    assert corr == [600.0, 200.0, 600.0, 300.0]


def test_eliminar_ingreso():
    pid = _setup()
    ings = ALM.listar_ingresos(pid, _R['CEMENTO'])
    ALM.eliminar_ingreso(ings[0]['id'])   # borra el de 600
    assert ALM.ingresado_acumulado(pid)[_R['CEMENTO']] == 400.0
    # Restaurar para no afectar otros tests.
    ALM.agregar_ingreso(pid, _R['CEMENTO'], '2026-06-10', 600, 'CEMENTO', 'BOL')


def test_proyecto_vacio():
    """Sin ingresos/consumo/requerimientos → control_almacen vacío, sin errores."""
    d2 = d.get_db()
    pid2 = d2.execute("INSERT INTO proyectos (nombre) VALUES ('VACIO')").lastrowid
    d2.commit(); d2.close()
    assert REQ.control_almacen(pid2) == []
    assert ALM.ingresado_acumulado(pid2) == {}
    assert ALM.movimientos(pid2, 999) == []


if __name__ == "__main__":
    fallos = 0
    orden = [test_ingresado_acumulado, test_consumido_acumulado_solo_recurso,
             test_control_almacen_solo_materiales, test_kardex_movimientos_y_stock,
             test_eliminar_ingreso, test_proyecto_vacio]
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
