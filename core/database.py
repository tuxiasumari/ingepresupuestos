# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
import sqlite3
import os
from decimal import Decimal, ROUND_HALF_UP
from werkzeug.security import generate_password_hash, check_password_hash

def _r2(val):
    """Redondeo comercial a 2 decimales (round half up)."""
    return float(Decimal(f'{float(val or 0):.10f}').quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))

def _rn(val, n: int = 2):
    """Redondeo comercial a n decimales (round half up)."""
    q = Decimal(10) ** -n
    return float(Decimal(f'{float(val or 0):.10f}').quantize(q, rounding=ROUND_HALF_UP))

# Decimales globales (se cargan desde configuracion al iniciar).
# Tres ámbitos separados, mismo criterio que S10 «Datos Adicionales»:
#   _DECIMALES_PPTO     → montos: PU, parciales, totales      (def 2)
#   _DECIMALES_METRADO  → metrados (partida y planilla)       (def 2)
#   _DECIMALES_CANT_ACU → cantidad de insumo en el ACU        (def 4)
_DECIMALES_PPTO: int = 2
_DECIMALES_METRADO: int = 2
_DECIMALES_CANT_ACU: int = 4


def parcial_wysiwyg(metrado, pu, n: int | None = None) -> float:
    """Parcial = metrado × PU usando el metrado *como se ve en pantalla*.

    Redondea el metrado a los decimales de metrado ANTES de multiplicar,
    para que metrado_visible × PU = parcial mostrado coincida exactamente
    con la multiplicación manual del usuario. Igual criterio que Delphin
    Express / S10. `n` = decimales del monto resultante.
    """
    if n is None:
        n = _DECIMALES_PPTO
    m = _rn(metrado or 0, _DECIMALES_METRADO)
    return _rn(m * (pu or 0), n)

def get_decimales_ppto() -> int:
    return _DECIMALES_PPTO

def set_decimales_ppto(n: int):
    global _DECIMALES_PPTO
    _DECIMALES_PPTO = max(0, min(6, int(n)))

def get_decimales_metrado() -> int:
    return _DECIMALES_METRADO

def set_decimales_metrado(n: int):
    global _DECIMALES_METRADO
    _DECIMALES_METRADO = max(0, min(6, int(n)))

def get_decimales_cant_acu() -> int:
    return _DECIMALES_CANT_ACU

def set_decimales_cant_acu(n: int):
    global _DECIMALES_CANT_ACU
    _DECIMALES_CANT_ACU = max(0, min(6, int(n)))


# ── Derivación de cantidad desde la cuadrilla (reglas canónicas peruanas) ──
# Únicas funciones de verdad para decidir si la cantidad de un insumo se deriva
# de la cuadrilla. Mantener en sync con las copias de views/proyecto_view.py y
# views/recurso_selector_dialog.py.

def recurso_por_hora(tipo, unidad) -> bool:
    """True si la cantidad se deriva de la cuadrilla: MO y equipo por hora
    (hh/hm). Fórmula: cant = cuadrilla / rendimiento × jornada."""
    u = (unidad or '').strip().lower()
    return (tipo == 'MO'
            or u in ('hh', 'hm', 'h-h', 'h-m', 'jph', 'jh')
            or 'hora' in u)


def recurso_por_dia(tipo, unidad) -> bool:
    """True si la cantidad se deriva de la cuadrilla SIN jornada: MO/EQ con
    unidad día/jor (el rendimiento ya es por día): cant = cuadrilla / rend."""
    u = (unidad or '').strip().rstrip('.').lower()
    return (tipo in ('MO', 'EQ')
            and u in ('día', 'dia', 'días', 'dias', 'jor', 'jornada'))


def partida_global(unidad) -> bool:
    """True si la PARTIDA es global (glb/est/serv): cantidad directa, sin
    cuadrilla/rendimiento (comportamiento PowerCost)."""
    u = (unidad or '').strip().rstrip('.').lower()
    return u in ('glb', 'gbl', 'est', 'serv')


# Palabras clave de acero en la descripción de una partida.
_ACERO_KEYS = ('ACERO', 'FIERRO', 'REFUERZO', 'CORRUGAD', 'VARILLA')


def es_partida_acero(descripcion, unidad) -> bool:
    """True si una partida (aún SIN planilla) es claramente de acero: unidad kg
    y descripción con ACERO/FIERRO/REFUERZO/CORRUGAD/VARILLA. Sirve para que una
    partida nueva de acero abra/aparezca directo en la planilla de acero (no en
    metrados normales). Único lugar de esta heurística — usado por la vista de
    proyecto y la Hoja de Metrados."""
    u = (unidad or '').strip().lower()
    if u not in ('kg', 'kg.', 'kgf', 'kg/m', 'kg/ml'):
        return False
    d = (descripcion or '').upper()
    return any(k in d for k in _ACERO_KEYS)


def partida_usa_acero(tiene_acero, tiene_met, flag, descripcion, unidad) -> bool:
    """¿Una partida usa la planilla de ACERO? Prioridad (único lugar de esta
    decisión):
      1. Tiene datos de acero        → sí
      2. Tiene datos de metrado normal → no
      3. flag explícito (`metrado_tipo`: 'acero'/'met', p.ej. clic derecho
         «Usar planilla de acero») → según el flag
      4. Heurística (kg + descripción de acero) → sí
      5. En cualquier otro caso → no (metrados normal)"""
    if tiene_acero:
        return True
    if tiene_met:
        return False
    if flag == 'acero':
        return True
    if flag == 'met':
        return False
    return es_partida_acero(descripcion, unidad)


def _orden_mo(desc) -> int:
    """Rango jerárquico de una mano de obra según el régimen de construcción
    civil (Perú): Capataz < Operario < Oficial < Peón < (otros: topógrafo,
    operador, controlador…). Devuelve 0..4. Insensible a may/min y acentos.

    Se usa para ordenar la MO por jerarquía (no alfabético) tanto en el panel
    ACU como en los reportes finales. Disponible en SQL como `mo_rank(desc)`.
    """
    d = (desc or '').lower()
    for a, b in (('á', 'a'), ('é', 'e'), ('í', 'i'),
                 ('ó', 'o'), ('ú', 'u'), ('ü', 'u')):
        d = d.replace(a, b)
    if 'capataz' in d:
        return 0
    if 'operario' in d:
        return 1
    if 'oficial' in d:
        return 2
    if 'peon' in d:
        return 3
    return 4


from core.config import DB_PATH  # path resuelto cross-platform por config

def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # Función escalar para ordenar mano de obra por jerarquía en SQL.
    conn.create_function("mo_rank", 1, _orden_mo, deterministic=True)
    return conn

def init_db():
    conn = get_db()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS proyectos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            cliente TEXT DEFAULT '',
            ubicacion TEXT DEFAULT '',
            sub_presupuesto TEXT DEFAULT '',
            costo_al TEXT DEFAULT '',
            plazo INTEGER DEFAULT 60,
            gf_pct REAL DEFAULT 10.0,
            utilidad_pct REAL DEFAULT 5.0,
            igv_pct REAL DEFAULT 18.0,
            grupo_analisis TEXT DEFAULT '',
            jornada_laboral REAL DEFAULT 8.0,
            moneda TEXT DEFAULT 'Soles',
            modalidad TEXT DEFAULT 'Contrata',
            creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS partidas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            proyecto_id INTEGER NOT NULL REFERENCES proyectos(id) ON DELETE CASCADE,
            item TEXT NOT NULL,
            descripcion TEXT NOT NULL,
            unidad TEXT DEFAULT '',
            metrado REAL DEFAULT 0,
            precio_unitario REAL DEFAULT 0,
            nivel INTEGER DEFAULT 1,
            es_titulo INTEGER DEFAULT 0,
            especificaciones TEXT DEFAULT '',
            rendimiento REAL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS recursos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo TEXT DEFAULT '',
            descripcion TEXT NOT NULL,
            tipo TEXT NOT NULL,
            unidad TEXT DEFAULT '',
            precio REAL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS acu_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            partida_id INTEGER NOT NULL REFERENCES partidas(id) ON DELETE CASCADE,
            recurso_id INTEGER NOT NULL REFERENCES recursos(id),
            cuadrilla REAL DEFAULT 0,
            cantidad REAL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS configuracion (
            clave TEXT PRIMARY KEY,
            valor TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS sub_presupuestos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            proyecto_id INTEGER NOT NULL REFERENCES proyectos(id) ON DELETE CASCADE,
            nombre TEXT NOT NULL,
            orden INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS biblioteca_cu (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            descripcion TEXT NOT NULL,
            unidad TEXT DEFAULT '',
            rendimiento REAL DEFAULT 1.0,
            costo_unitario REAL DEFAULT 0,
            grupo TEXT DEFAULT '',
            especificaciones TEXT DEFAULT '',
            usos INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS biblioteca_acu_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cu_id INTEGER NOT NULL REFERENCES biblioteca_cu(id) ON DELETE CASCADE,
            recurso_id INTEGER NOT NULL REFERENCES recursos(id) ON DELETE CASCADE,
            cuadrilla REAL DEFAULT 0,
            cantidad REAL DEFAULT 0,
            precio REAL
        );
        CREATE TABLE IF NOT EXISTS pie_presupuesto (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            proyecto_id INTEGER NOT NULL REFERENCES proyectos(id) ON DELETE CASCADE,
            rol TEXT NOT NULL,
            nombre TEXT DEFAULT '',
            cargo TEXT DEFAULT '',
            cip TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS metrados_detalle (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            partida_id INTEGER NOT NULL REFERENCES partidas(id) ON DELETE CASCADE,
            orden INTEGER DEFAULT 0,
            descripcion TEXT DEFAULT '',
            n_estructuras REAL,
            n_elementos REAL,
            largo REAL,
            ancho REAL,
            alto REAL,
            parcial REAL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS cronograma_partidas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            partida_id INTEGER NOT NULL REFERENCES partidas(id) ON DELETE CASCADE UNIQUE,
            duracion INTEGER DEFAULT 1,
            inicio_dia INTEGER DEFAULT 1,
            predecesoras TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS spec_imagenes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            partida_id INTEGER NOT NULL REFERENCES partidas(id) ON DELETE CASCADE,
            orden INTEGER DEFAULT 0,
            filename TEXT NOT NULL,
            caption TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS gastos_generales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            proyecto_id INTEGER NOT NULL REFERENCES proyectos(id) ON DELETE CASCADE,
            rubro TEXT DEFAULT 'GG',
            tipo TEXT DEFAULT 'item',
            descripcion TEXT DEFAULT '',
            unidad TEXT DEFAULT 'MES',
            n_personas REAL DEFAULT 1,
            tiempo REAL DEFAULT 1,
            pct_participacion REAL DEFAULT 100,
            precio REAL DEFAULT 0,
            orden INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS pie_rubros (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            proyecto_id INTEGER NOT NULL REFERENCES proyectos(id) ON DELETE CASCADE,
            codigo TEXT NOT NULL,
            nombre TEXT NOT NULL,
            pct REAL DEFAULT 0,
            activo INTEGER DEFAULT 1,
            orden INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            username TEXT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            rol TEXT DEFAULT 'usuario',
            activo INTEGER DEFAULT 1,
            creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS formula_monomios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            proyecto_id INTEGER NOT NULL REFERENCES proyectos(id) ON DELETE CASCADE,
            orden INTEGER DEFAULT 0,
            simbolo TEXT DEFAULT 'A',
            descripcion TEXT DEFAULT '',
            indice_inei TEXT DEFAULT '',
            coeficiente REAL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS acero_detalle (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            partida_id INTEGER NOT NULL REFERENCES partidas(id) ON DELETE CASCADE,
            orden INTEGER DEFAULT 0,
            descripcion TEXT DEFAULT '',
            diametro TEXT DEFAULT '',
            n_veces REAL,
            n_elementos REAL,
            longitud REAL,
            kg_ml REAL,
            parcial REAL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS tuxia_memos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            proyecto_id INTEGER REFERENCES proyectos(id) ON DELETE CASCADE,
            texto TEXT NOT NULL,
            fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS tuxia_memoria (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            proyecto_id INTEGER REFERENCES proyectos(id) ON DELETE CASCADE,
            texto TEXT NOT NULL DEFAULT '',
            fecha_modif TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS dashboard_tot_cache (
            proyecto_id INTEGER PRIMARY KEY REFERENCES proyectos(id) ON DELETE CASCADE,
            modificado_en TEXT,
            total REAL
        );
        CREATE TABLE IF NOT EXISTS portafolios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL UNIQUE,
            color TEXT DEFAULT '#667885',
            descripcion TEXT DEFAULT '',
            orden INTEGER DEFAULT 0,
            creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS indices_inei (
            codigo TEXT PRIMARY KEY,
            nombre TEXT NOT NULL,
            activo INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS indices_inei_areas (
            codigo TEXT PRIMARY KEY,
            nombre TEXT NOT NULL,
            orden INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS indices_inei_valores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo TEXT NOT NULL,
            anio INTEGER NOT NULL,
            mes INTEGER NOT NULL,
            area TEXT DEFAULT '01',
            valor REAL NOT NULL,
            UNIQUE(codigo, anio, mes, area)
        );
        CREATE TABLE IF NOT EXISTS formula_periodos (
            proyecto_id INTEGER PRIMARY KEY REFERENCES proyectos(id) ON DELETE CASCADE,
            oferta_anio INTEGER,
            oferta_mes INTEGER,
            reajuste_anio INTEGER,
            reajuste_mes INTEGER,
            area_inei TEXT DEFAULT '01'
        );
        CREATE TABLE IF NOT EXISTS pie_plantillas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL UNIQUE,
            items_json TEXT NOT NULL DEFAULT '[]',
            creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        -- Control de Obra · Fase 1: valorizaciones de avance. La cabecera es el
        -- período; el detalle guarda SOLO el metrado ejecutado por partida
        -- (todo lo demás —valor, anterior, acumulado, %, saldo— se deriva).
        CREATE TABLE IF NOT EXISTS valorizaciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            proyecto_id INTEGER NOT NULL REFERENCES proyectos(id) ON DELETE CASCADE,
            numero INTEGER NOT NULL,
            periodo_desde TEXT DEFAULT '',
            periodo_hasta TEXT DEFAULT '',
            estado TEXT DEFAULT 'abierta',
            notas TEXT DEFAULT '',
            creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS valorizacion_detalle (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            valorizacion_id INTEGER NOT NULL REFERENCES valorizaciones(id) ON DELETE CASCADE,
            partida_id INTEGER NOT NULL REFERENCES partidas(id) ON DELETE CASCADE,
            metrado_periodo REAL DEFAULT 0,
            UNIQUE(valorizacion_id, partida_id)
        );
        -- Control de Obra · Fase A: parte diario / cuaderno de obra. El metrado
        -- ejecutado por día se acumula (push) hacia el metrado_periodo de la
        -- valorización cuyo período contiene la fecha. Modelo MIXTO: si una
        -- partida no tiene partes, su metrado del mes se sigue tecleando a mano.
        CREATE TABLE IF NOT EXISTS parte_diario (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            proyecto_id INTEGER NOT NULL REFERENCES proyectos(id) ON DELETE CASCADE,
            fecha TEXT NOT NULL,
            observaciones TEXT DEFAULT '',
            estado TEXT DEFAULT 'abierto',
            creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(proyecto_id, fecha)
        );
        CREATE TABLE IF NOT EXISTS parte_diario_metrado (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            parte_id INTEGER NOT NULL REFERENCES parte_diario(id) ON DELETE CASCADE,
            partida_id INTEGER NOT NULL REFERENCES partidas(id) ON DELETE CASCADE,
            metrado_dia REAL DEFAULT 0,
            UNIQUE(parte_id, partida_id)
        );
        -- Planilla de metrados POR DÍA (misma estructura que metrados_detalle):
        -- el metrado del día de una partida = Σ parcial de sus filas aquí.
        CREATE TABLE IF NOT EXISTS parte_diario_metrado_detalle (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            parte_id INTEGER NOT NULL REFERENCES parte_diario(id) ON DELETE CASCADE,
            partida_id INTEGER NOT NULL REFERENCES partidas(id) ON DELETE CASCADE,
            orden INTEGER DEFAULT 0,
            descripcion TEXT DEFAULT '',
            n_estructuras REAL,
            n_elementos REAL,
            area REAL,
            largo REAL,
            ancho REAL,
            alto REAL,
            parcial REAL DEFAULT 0
        );
        -- Recursos del día (Fase B): clase 'mo' = mano de obra (personas) ·
        -- 'insumo' = materiales/equipo usados. recurso_id opcional (puede ser una
        -- entrada manual); se guarda snapshot de descripcion/unidad.
        CREATE TABLE IF NOT EXISTS parte_diario_recurso (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            parte_id INTEGER NOT NULL REFERENCES parte_diario(id) ON DELETE CASCADE,
            clase TEXT NOT NULL,
            recurso_id INTEGER,
            descripcion TEXT DEFAULT '',
            unidad TEXT DEFAULT '',
            cantidad REAL DEFAULT 0,
            orden INTEGER DEFAULT 0
        );
        -- Control de Obra · Requerimientos (sobre todo AD): documentos numerados
        -- (Req N°1, N°2…) con los insumos solicitados. Lo requerido (acumulado)
        -- se compara contra lo presupuestado (ACU × metrados). recurso_id opcional
        -- (extras no presupuestados). tipo: 'mat'|'eq'|'sc'.
        CREATE TABLE IF NOT EXISTS requerimientos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            proyecto_id INTEGER NOT NULL REFERENCES proyectos(id) ON DELETE CASCADE,
            numero INTEGER NOT NULL,
            fecha TEXT DEFAULT '',
            notas TEXT DEFAULT '',
            estado TEXT DEFAULT 'abierto',
            creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS requerimiento_detalle (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            requerimiento_id INTEGER NOT NULL REFERENCES requerimientos(id) ON DELETE CASCADE,
            tipo TEXT NOT NULL,
            recurso_id INTEGER,
            descripcion TEXT DEFAULT '',
            unidad TEXT DEFAULT '',
            cantidad REAL DEFAULT 0,
            orden INTEGER DEFAULT 0
        );
        -- Control de Obra · Almacén: ingresos (entradas) de materiales al almacén
        -- de obra, por fecha. El material puede llegar en varias entregas/días.
        -- Kárdex: Entradas (esta tabla) − Salidas (parte_diario_recurso) = Stock.
        CREATE TABLE IF NOT EXISTS almacen_ingreso (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            proyecto_id INTEGER NOT NULL REFERENCES proyectos(id) ON DELETE CASCADE,
            recurso_id INTEGER,
            descripcion TEXT DEFAULT '',
            unidad TEXT DEFAULT '',
            fecha TEXT DEFAULT '',
            cantidad REAL DEFAULT 0,
            observacion TEXT DEFAULT '',
            creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        -- Control de Obra · Curva S — overrides manuales por período: % meta
        -- reprogramado (pct), % programado editado (pct_prog) y etiqueta del
        -- período (label). period_days distingue base: 7 semana · 30 mes rodante
        -- · 31 fin de mes calendario. Cualquier columna NULL = usar el derivado.
        CREATE TABLE IF NOT EXISTS curva_reprogramada (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            proyecto_id INTEGER NOT NULL REFERENCES proyectos(id) ON DELETE CASCADE,
            period_days INTEGER NOT NULL,
            periodo_idx INTEGER NOT NULL,
            pct REAL,
            pct_prog REAL,
            pct_real REAL,
            label TEXT,
            UNIQUE(proyecto_id, period_days, periodo_idx)
        );
    ''')
    conn.commit()
    # Migración: agregar columnas nuevas si no existen (SQLite no soporta IF NOT EXISTS en ALTER)
    for col, ddl in [
        ('grupo_analisis',  "ALTER TABLE proyectos ADD COLUMN grupo_analisis TEXT DEFAULT ''"),
        ('jornada_laboral', "ALTER TABLE proyectos ADD COLUMN jornada_laboral REAL DEFAULT 8.0"),
        ('moneda',          "ALTER TABLE proyectos ADD COLUMN moneda TEXT DEFAULT 'Soles'"),
        ('modalidad',       "ALTER TABLE proyectos ADD COLUMN modalidad TEXT DEFAULT 'Contrata'"),
        ('grupo',           "ALTER TABLE partidas ADD COLUMN grupo TEXT DEFAULT ''"),
        ('es_hito',         "ALTER TABLE cronograma_partidas ADD COLUMN es_hito INTEGER DEFAULT 0"),
        ('segmentos',       "ALTER TABLE cronograma_partidas ADD COLUMN segmentos TEXT DEFAULT ''"),
        ('rubro',    "ALTER TABLE gastos_generales ADD COLUMN rubro TEXT DEFAULT 'GG'"),
        ('tipo_rub',    "ALTER TABLE pie_rubros ADD COLUMN tipo TEXT DEFAULT 'rubro'"),
        ('usuario_id',  "ALTER TABLE proyectos ADD COLUMN usuario_id INTEGER REFERENCES usuarios(id)"),
        ('username',    "ALTER TABLE usuarios ADD COLUMN username TEXT"),
        ('favorito',    "ALTER TABLE proyectos ADD COLUMN favorito INTEGER DEFAULT 0"),
        ('indice_inei', "ALTER TABLE recursos ADD COLUMN indice_inei TEXT DEFAULT ''"),
        ('estado',      "ALTER TABLE proyectos ADD COLUMN estado TEXT DEFAULT 'elaboracion'"),
        ('mostrar_pct', "ALTER TABLE pie_rubros ADD COLUMN mostrar_pct INTEGER DEFAULT 1"),
        ('area_met',    "ALTER TABLE metrados_detalle ADD COLUMN area REAL"),
        ('n_estr_acero',"ALTER TABLE acero_detalle ADD COLUMN n_estructuras REAL"),
        ('precio_acu',        "ALTER TABLE acu_items ADD COLUMN precio REAL"),
        ('sub_presupuesto_id', "ALTER TABLE partidas ADD COLUMN sub_presupuesto_id INTEGER REFERENCES sub_presupuestos(id) ON DELETE SET NULL"),
        ('portafolio_id', "ALTER TABLE proyectos ADD COLUMN portafolio_id INTEGER REFERENCES portafolios(id) ON DELETE SET NULL"),
        ('fecha_inicio',  "ALTER TABLE proyectos ADD COLUMN fecha_inicio TEXT DEFAULT ''"),
        ('feriados',      "ALTER TABLE proyectos ADD COLUMN feriados TEXT DEFAULT ''"),
        ('salta_no_lab',  "ALTER TABLE proyectos ADD COLUMN salta_no_laborables INTEGER DEFAULT 1"),
        ('cron_color',    "ALTER TABLE cronograma_partidas ADD COLUMN color TEXT DEFAULT ''"),
        ('notas',         "ALTER TABLE proyectos ADD COLUMN notas TEXT DEFAULT ''"),
        ('modificado_en', "ALTER TABLE proyectos ADD COLUMN modificado_en TIMESTAMP"),
        ('cantidad_gg',   "ALTER TABLE gastos_generales ADD COLUMN cantidad REAL"),
        ('memoria_desc',  "ALTER TABLE proyectos ADD COLUMN memoria_descriptiva TEXT DEFAULT ''"),
        ('latitud',       "ALTER TABLE proyectos ADD COLUMN latitud REAL"),
        ('longitud',      "ALTER TABLE proyectos ADD COLUMN longitud REAL"),
        ('altitud',       "ALTER TABLE proyectos ADD COLUMN altitud REAL"),
        ('bib_precio',    "ALTER TABLE biblioteca_acu_items ADD COLUMN precio REAL"),
        ('metrado_tipo',  "ALTER TABLE partidas ADD COLUMN metrado_tipo TEXT"),
        ('vd_origen',     "ALTER TABLE valorizacion_detalle ADD COLUMN origen TEXT DEFAULT 'manual'"),
        ('req_categoria', "ALTER TABLE requerimientos ADD COLUMN categoria TEXT DEFAULT ''"),
        ('req_tipo',      "ALTER TABLE requerimientos ADD COLUMN tipo TEXT DEFAULT ''"),
        ('req_tdr',       "ALTER TABLE requerimientos ADD COLUMN tdr TEXT DEFAULT ''"),
        ('req_tdr_datos', "ALTER TABLE requerimientos ADD COLUMN tdr_datos TEXT DEFAULT ''"),
        ('rec_categoria', "ALTER TABLE recursos ADD COLUMN categoria TEXT DEFAULT ''"),
        ('curva_prog_ov', "ALTER TABLE curva_reprogramada ADD COLUMN pct_prog REAL"),
        ('curva_real_ov', "ALTER TABLE curva_reprogramada ADD COLUMN pct_real REAL"),
        ('curva_label_ov', "ALTER TABLE curva_reprogramada ADD COLUMN label TEXT"),
    ]:
        try:
            conn.execute(ddl)
            conn.commit()
        except Exception:
            pass  # columna ya existe
    try:
        conn.execute("UPDATE proyectos SET modificado_en = creado_en WHERE modificado_en IS NULL")
        conn.commit()
    except Exception:
        pass
    # parte_diario_recurso: recrear si quedó el esquema viejo (Fase A, sin
    # 'descripcion'). La tabla aún no se usaba, así que el DROP no pierde datos.
    try:
        _cols = [r[1] for r in conn.execute(
            "PRAGMA table_info(parte_diario_recurso)").fetchall()]
        if _cols and 'descripcion' not in _cols:
            conn.execute("DROP TABLE parte_diario_recurso")
            conn.execute("""
                CREATE TABLE parte_diario_recurso (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    parte_id INTEGER NOT NULL REFERENCES parte_diario(id) ON DELETE CASCADE,
                    clase TEXT NOT NULL,
                    recurso_id INTEGER,
                    descripcion TEXT DEFAULT '',
                    unidad TEXT DEFAULT '',
                    cantidad REAL DEFAULT 0,
                    orden INTEGER DEFAULT 0
                )""")
            conn.commit()
    except Exception:
        pass
    # gemini-2.0-flash quedó sin cuota gratuita (429 limit:0). Migrar el viejo
    # default al modelo que sí tiene free tier. Solo afecta a quien tenía guardado
    # exactamente ese valor (el default anterior); no toca otras elecciones.
    try:
        conn.execute(
            "UPDATE configuracion SET valor='gemini-2.5-flash' "
            "WHERE clave='gemini_modelo' AND valor='gemini-2.0-flash'"
        )
        conn.commit()
    except Exception:
        pass
    # Poblar gastos_generales.cantidad desde el modelo viejo (n_personas × tiempo)
    # para filas existentes. No destructivo: n_personas/tiempo se conservan.
    try:
        conn.execute(
            "UPDATE gastos_generales SET cantidad = COALESCE(n_personas,0)*COALESCE(tiempo,1) "
            "WHERE cantidad IS NULL AND tipo='item' "
            "AND (n_personas IS NOT NULL OR tiempo IS NOT NULL)"
        )
        conn.commit()
    except Exception:
        pass

    # Poblar acu_items.precio desde recursos para filas existentes (migración única)
    try:
        conn.execute(
            """UPDATE acu_items SET precio = (SELECT r.precio FROM recursos r WHERE r.id = acu_items.recurso_id)
               WHERE precio IS NULL"""
        )
        conn.commit()
    except Exception:
        pass

    # Insertar configuración de decimales si no existe.
    # decimales_metrado hereda el valor que el usuario ya tenía en
    # decimales_presupuesto (antes una sola clave controlaba ambos).
    try:
        conn.execute("INSERT OR IGNORE INTO configuracion (clave, valor) VALUES ('decimales_presupuesto', '2')")
        conn.execute(
            """INSERT OR IGNORE INTO configuracion (clave, valor)
               SELECT 'decimales_metrado', valor FROM configuracion WHERE clave='decimales_presupuesto'"""
        )
        conn.execute("INSERT OR IGNORE INTO configuracion (clave, valor) VALUES ('decimales_cantidad_acu', '4')")
        conn.commit()
    except Exception:
        pass

    # Cargar decimales en las variables globales
    for clave, setter in (('decimales_presupuesto', set_decimales_ppto),
                          ('decimales_metrado', set_decimales_metrado),
                          ('decimales_cantidad_acu', set_decimales_cant_acu)):
        try:
            row = conn.execute("SELECT valor FROM configuracion WHERE clave=?", (clave,)).fetchone()
            if row:
                setter(int(row['valor']))
        except Exception:
            pass

    # ── Trigger: actualizar modificado_en automáticamente ────────────────
    for trg in [
        """CREATE TRIGGER IF NOT EXISTS trg_proy_upd AFTER UPDATE ON proyectos WHEN NEW.modificado_en IS OLD.modificado_en OR NEW.modificado_en IS NULL
           BEGIN UPDATE proyectos SET modificado_en=CURRENT_TIMESTAMP WHERE id=NEW.id; END""",
        """CREATE TRIGGER IF NOT EXISTS trg_part_ins AFTER INSERT ON partidas
           BEGIN UPDATE proyectos SET modificado_en=CURRENT_TIMESTAMP WHERE id=NEW.proyecto_id; END""",
        """CREATE TRIGGER IF NOT EXISTS trg_part_upd AFTER UPDATE ON partidas
           BEGIN UPDATE proyectos SET modificado_en=CURRENT_TIMESTAMP WHERE id=NEW.proyecto_id; END""",
        """CREATE TRIGGER IF NOT EXISTS trg_part_del AFTER DELETE ON partidas
           BEGIN UPDATE proyectos SET modificado_en=CURRENT_TIMESTAMP WHERE id=OLD.proyecto_id; END""",
        """CREATE TRIGGER IF NOT EXISTS trg_acu_ins AFTER INSERT ON acu_items
           BEGIN UPDATE proyectos SET modificado_en=CURRENT_TIMESTAMP
             WHERE id=(SELECT proyecto_id FROM partidas WHERE id=NEW.partida_id); END""",
        """CREATE TRIGGER IF NOT EXISTS trg_acu_upd AFTER UPDATE ON acu_items
           BEGIN UPDATE proyectos SET modificado_en=CURRENT_TIMESTAMP
             WHERE id=(SELECT proyecto_id FROM partidas WHERE id=NEW.partida_id); END""",
        """CREATE TRIGGER IF NOT EXISTS trg_acu_del AFTER DELETE ON acu_items
           BEGIN UPDATE proyectos SET modificado_en=CURRENT_TIMESTAMP
             WHERE id=(SELECT proyecto_id FROM partidas WHERE id=OLD.partida_id); END""",
        """CREATE TRIGGER IF NOT EXISTS trg_gg_ins AFTER INSERT ON gastos_generales
           BEGIN UPDATE proyectos SET modificado_en=CURRENT_TIMESTAMP WHERE id=NEW.proyecto_id; END""",
        """CREATE TRIGGER IF NOT EXISTS trg_gg_upd AFTER UPDATE ON gastos_generales
           BEGIN UPDATE proyectos SET modificado_en=CURRENT_TIMESTAMP WHERE id=NEW.proyecto_id; END""",
        """CREATE TRIGGER IF NOT EXISTS trg_gg_del AFTER DELETE ON gastos_generales
           BEGIN UPDATE proyectos SET modificado_en=CURRENT_TIMESTAMP WHERE id=OLD.proyecto_id; END""",
    ]:
        try:
            conn.execute(trg)
        except Exception:
            pass
    conn.commit()

    # ── Índices de rendimiento ────────────────────────────────────────────
    # Sin estos, cada consulta filtrada hace full table scan. Críticos cuando
    # la BD crece a 100+ proyectos / decenas de miles de partidas. Usamos
    # IF NOT EXISTS para que sea idempotente.
    _INDICES = [
        # ── FK más usadas (recálculo de totales, apertura de proyecto) ──
        "CREATE INDEX IF NOT EXISTS idx_partidas_proyecto    ON partidas(proyecto_id)",
        "CREATE INDEX IF NOT EXISTS idx_partidas_sub         ON partidas(sub_presupuesto_id)",
        "CREATE INDEX IF NOT EXISTS idx_acu_items_partida    ON acu_items(partida_id)",
        "CREATE INDEX IF NOT EXISTS idx_acu_items_recurso    ON acu_items(recurso_id)",
        "CREATE INDEX IF NOT EXISTS idx_metrados_partida     ON metrados_detalle(partida_id)",
        "CREATE INDEX IF NOT EXISTS idx_acero_partida        ON acero_detalle(partida_id)",
        "CREATE INDEX IF NOT EXISTS idx_pie_proyecto         ON pie_rubros(proyecto_id)",
        "CREATE INDEX IF NOT EXISTS idx_gg_proyecto          ON gastos_generales(proyecto_id)",
        "CREATE INDEX IF NOT EXISTS idx_cron_partida         ON cronograma_partidas(partida_id)",
        "CREATE INDEX IF NOT EXISTS idx_subppto_proyecto     ON sub_presupuestos(proyecto_id)",
        "CREATE INDEX IF NOT EXISTS idx_formula_proyecto     ON formula_monomios(proyecto_id)",
        "CREATE INDEX IF NOT EXISTS idx_formperiodo_proy     ON formula_periodos(proyecto_id)",
        "CREATE INDEX IF NOT EXISTS idx_specimg_partida      ON spec_imagenes(partida_id)",
        # ── Catálogos / búsquedas ─────────────────────────────────────────
        "CREATE INDEX IF NOT EXISTS idx_recursos_codigo      ON recursos(codigo)",
        "CREATE INDEX IF NOT EXISTS idx_recursos_inei        ON recursos(indice_inei)",
        "CREATE INDEX IF NOT EXISTS idx_biblioteca_grupo     ON biblioteca_cu(grupo)",
        "CREATE INDEX IF NOT EXISTS idx_biblioteca_acu_cu    ON biblioteca_acu_items(cu_id)",
        "CREATE INDEX IF NOT EXISTS idx_inei_codigo          ON indices_inei_valores(codigo, anio, mes, area)",
        # ── Dashboard (filtros por portafolio + ordenamiento) ─────────────
        "CREATE INDEX IF NOT EXISTS idx_proyectos_portafolio ON proyectos(portafolio_id)",
        "CREATE INDEX IF NOT EXISTS idx_proyectos_usuario    ON proyectos(usuario_id)",
        "CREATE INDEX IF NOT EXISTS idx_memos_proyecto       ON tuxia_memos(proyecto_id)",
        "CREATE INDEX IF NOT EXISTS idx_memoria_proyecto     ON tuxia_memoria(proyecto_id)",
    ]
    for sql in _INDICES:
        try:
            conn.execute(sql)
        except Exception:
            pass   # tabla aún no existe (migración futura) o columna ausente
    conn.commit()

    # ANALYZE recolecta estadísticas para que el query planner elija el
    # mejor camino (índice vs scan). Barato y se ejecuta una sola vez al
    # arrancar después de crear los índices.
    try:
        conn.execute("ANALYZE")
        conn.commit()
    except Exception:
        pass

    # ── Migración única: predecesoras a numeración estilo MS Project ──────
    # El "#" y las predecesoras numeran como el Id de MS Project: #1 = resumen
    # del proyecto, #2 = hito «Inicio de Obra», luego cada subpresupuesto como
    # cabecera con sus títulos/partidas, y al final «Termino de Obra».
    # Reescribimos las cadenas guardadas para que sigan apuntando a la partida
    # correcta, partiendo del esquema en que estén. Backup previo. Flag: 'msp_v3'.
    _FLAG_FINAL = 'msp_v3'
    try:
        row = conn.execute(
            "SELECT valor FROM configuracion WHERE clave='cron_pred_numbering'"
        ).fetchone()
        estado = row['valor'] if row else None
    except Exception:
        estado = _FLAG_FINAL  # tabla aún no lista; no arriesgar
    if estado != _FLAG_FINAL:
        try:
            from core.cronograma import migrar_predecesoras_msproject
            desde = estado if estado in ('allrows', 'msproject', 'msp_v2') else 'leaf'
            # Respaldo antes de tocar datos del usuario.
            try:
                from core.backup import crear_backup
                crear_backup('pre_migracion_predecesoras')
            except Exception:
                pass
            proy_ids = [r['id'] for r in conn.execute("SELECT id FROM proyectos")]
            for pid in proy_ids:
                # Orden AGRUPADO por subpresupuesto (Principal/NULL primero,
                # luego cada subpresupuesto por `orden`), dentro por item.
                partidas = [dict(r) for r in conn.execute(
                    """SELECT p.* FROM partidas p
                       LEFT JOIN sub_presupuestos s ON s.id = p.sub_presupuesto_id
                       WHERE p.proyecto_id=?
                       ORDER BY (CASE WHEN p.sub_presupuesto_id IS NULL THEN 0 ELSE 1 END),
                                COALESCE(s.orden, 0), p.sub_presupuesto_id, p.item""",
                    (pid,)
                )]
                if not partidas:
                    continue
                cmap = {r['partida_id']: dict(r) for r in conn.execute(
                    """SELECT cp.* FROM cronograma_partidas cp
                       JOIN partidas p ON p.id = cp.partida_id
                       WHERE p.proyecto_id=?""", (pid,)
                )}
                cambios = migrar_predecesoras_msproject(partidas, cmap, desde)
                for part_id, nuevo in cambios.items():
                    conn.execute(
                        "UPDATE cronograma_partidas SET predecesoras=? WHERE partida_id=?",
                        (nuevo, part_id)
                    )
            conn.execute(
                "INSERT OR REPLACE INTO configuracion (clave, valor) VALUES ('cron_pred_numbering','msp_v3')"
            )
            conn.commit()
        except Exception:
            pass

    conn.close()

# ─── HELPERS DE USUARIOS ──────────────────────────────────────────────────────

def crear_usuario(nombre, email, password, rol='usuario', username=None):
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO usuarios (nombre, username, email, password_hash, rol) VALUES (?,?,?,?,?)",
            (nombre, username, email, generate_password_hash(password), rol)
        )
        conn.commit()
        return True, None
    except sqlite3.IntegrityError:
        return False, 'El correo ya está registrado.'
    finally:
        conn.close()

def verificar_usuario(login, password):
    """Acepta nombre de usuario (username), nombre o correo electrónico."""
    conn = get_db()
    u = conn.execute(
        "SELECT * FROM usuarios WHERE (email=? OR username=? OR nombre=?) AND activo=1",
        (login, login, login)
    ).fetchone()
    conn.close()
    if u and check_password_hash(u['password_hash'], password):
        return u
    return None

def hay_usuarios():
    conn = get_db()
    n = conn.execute("SELECT COUNT(*) FROM usuarios WHERE rol != 'invitado'").fetchone()[0]
    conn.close()
    return n > 0

def get_usuario_invitado():
    """Devuelve (o crea) el usuario invitado del sistema."""
    conn = get_db()
    u = conn.execute("SELECT * FROM usuarios WHERE rol='invitado'").fetchone()
    if not u:
        conn.execute(
            "INSERT INTO usuarios (nombre, email, password_hash, rol, activo) VALUES (?,?,?,?,1)",
            ('Invitado', 'invitado@sistema.local', generate_password_hash('invitado'), 'invitado')
        )
        conn.commit()
        u = conn.execute("SELECT * FROM usuarios WHERE rol='invitado'").fetchone()
    conn.close()
    return u

def get_config(clave, default=''):
    conn = get_db()
    row = conn.execute("SELECT valor FROM configuracion WHERE clave=?", (clave,)).fetchone()
    conn.close()
    return row['valor'] if row else default

def set_config(clave, valor):
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO configuracion(clave,valor) VALUES(?,?)", (clave, valor))
    conn.commit()
    conn.close()

def calcular_totales(proyecto_id):
    conn = get_db()
    partidas = conn.execute(
        "SELECT * FROM partidas WHERE proyecto_id=? ORDER BY item", (proyecto_id,)
    ).fetchall()
    proyecto = conn.execute("SELECT * FROM proyectos WHERE id=?", (proyecto_id,)).fetchone()
    conn.close()

    # Calcular parciales WYSIWYG: metrado se redondea a los decimales del
    # presupuesto ANTES de multiplicar, para que coincida con la multiplicación
    # manual de lo que ve el usuario (criterio Delphin/S10).
    parciales = {}
    for p in partidas:
        if not p['es_titulo']:
            parciales[p['item']] = parcial_wysiwyg(p['metrado'], p['precio_unitario'])

    # Calcular subtotales de secciones
    def subtotal_de(prefijo):
        total = 0
        for item, val in parciales.items():
            if item.startswith(prefijo + '.') or item == prefijo:
                total += val
        return total

    items_con_total = []
    for p in partidas:
        if p['es_titulo']:
            total = subtotal_de(p['item'])
        else:
            total = parciales.get(p['item'], 0)
        items_con_total.append({'partida': dict(p), 'total': total})

    cd = sum(parciales.values())

    # Intentar calcular total desde pie_rubros (sistema dinámico).
    # Si existe CUALQUIER pie_rubros para el proyecto (aunque todos estén
    # inactivos), usar el sistema dinámico — los inactivos suman 0. Sin esta
    # distinción, "todo desactivado" caía al fallback legacy y aplicaba
    # silenciosamente `proyectos.utilidad_pct` / `igv_pct`.
    conn2 = get_db()
    rubros = conn2.execute(
        "SELECT * FROM pie_rubros WHERE proyecto_id=? AND activo=1 ORDER BY orden",
        (proyecto_id,)
    ).fetchall()
    tiene_pie = conn2.execute(
        "SELECT 1 FROM pie_rubros WHERE proyecto_id=? LIMIT 1", (proyecto_id,)
    ).fetchone() is not None

    if rubros or tiene_pie:
        acum = cd
        last_sub = cd
        gf = utilidad = subtotal_val = igv = 0
        for r in rubros:
            tipo = r['tipo']; pct = r['pct'] or 0; codigo = r['codigo']
            if tipo == 'subtotal':
                last_sub = acum
                subtotal_val = acum
            elif tipo == 'pct_sub':
                val = last_sub * pct / 100
                acum += val
                if codigo == 'IGV': igv = val
            else:  # rubro o pct_cd
                if tipo == 'rubro':
                    manual = conn2.execute(
                        "SELECT precio FROM gastos_generales"
                        " WHERE proyecto_id=? AND rubro=? AND tipo='manual'",
                        (proyecto_id, codigo)
                    ).fetchone()
                    if manual:
                        val = manual['precio'] or 0
                    else:
                        gg_items = conn2.execute(
                            "SELECT * FROM gastos_generales"
                            " WHERE proyecto_id=? AND rubro=? AND tipo='item'",
                            (proyecto_id, codigo)
                        ).fetchall()
                        if gg_items:
                            val = sum(
                                (i['cantidad'] or 0)
                                * ((i['pct_participacion'] or 100) / 100)
                                * (i['precio'] or 0)
                                for i in gg_items
                            )
                        else:
                            val = cd * pct / 100
                else:
                    val = cd * pct / 100
                acum += val
                if codigo == 'GG':      gf = val
                elif codigo == 'UTIL':  utilidad = val
        total_obra = acum
        subtotal = subtotal_val if subtotal_val else cd + gf + utilidad
    else:
        # Fallback: fórmula simple desde campos del proyecto
        gf = cd * (proyecto['gf_pct'] or 0) / 100
        utilidad = cd * (proyecto['utilidad_pct'] or 0) / 100
        subtotal = cd + gf + utilidad
        igv = subtotal * (proyecto['igv_pct'] or 0) / 100
        total_obra = subtotal + igv

    conn2.close()
    return items_con_total, {
        'cd': cd, 'gf': gf, 'utilidad': utilidad,
        'subtotal': subtotal, 'igv': igv, 'total': total_obra
    }


def _pu_desde_items(items) -> float:
    """Suma el costo unitario a partir de filas (cantidad, precio, unidad, tipo)
    del ACU. Mismas reglas que la app: parciales redondeados a decimales de
    montos; overhead %MO/%MAT al final sobre el subtotal de su tipo."""
    totales_tipo = {'MO': 0.0, 'MAT': 0.0, 'EQ': 0.0}
    pct_pending = []
    for it in items:
        if (it['unidad'] or '').startswith('%'):
            pct_pending.append(it)
        else:
            parcial = _rn((it['cantidad'] or 0) * (it['precio'] or 0), _DECIMALES_PPTO)
            tipo = it['tipo'] if it['tipo'] in totales_tipo else 'MAT'
            totales_tipo[tipo] += parcial
    cu = sum(totales_tipo.values())
    for it in pct_pending:
        unidad_l = (it['unidad'] or '').lower()
        base = totales_tipo.get('MO' if '%mo' in unidad_l else 'MAT' if '%mat' in unidad_l else 'MO', 0)
        cu += _rn((it['cantidad'] or 0) / 100 * base, _DECIMALES_PPTO)
    return _rn(cu, _DECIMALES_PPTO)


def _recalcular_pu(conn, part_id: int) -> float:
    """Recalcula precio_unitario de una partida sumando todos los parciales del ACU.
    Actualiza partidas.precio_unitario en la misma conexión (sin commit).
    Retorna el nuevo precio unitario."""
    items = conn.execute(
        """SELECT ai.cantidad, COALESCE(ai.precio, r.precio, 0) as precio, r.unidad, r.tipo
           FROM acu_items ai JOIN recursos r ON r.id=ai.recurso_id WHERE ai.partida_id=?""",
        (part_id,)
    ).fetchall()
    cu = _pu_desde_items(items)
    conn.execute("UPDATE partidas SET precio_unitario=? WHERE id=?", (cu, part_id))
    return cu


def partidas_pu_inconsistente(conn, pid: int) -> list[dict]:
    """Detecta partidas cuyo PU guardado NO coincide con la suma de su ACU.

    Causa típica: importaciones antiguas con sub-análisis sin resolver
    (insumos «---» a precio 0) o ediciones con versiones viejas del cálculo.
    El PU guardado puede ser el correcto (fiel al software origen) — la
    decisión de recalcular es del usuario.

    Una sola query agregada (proyectos de 3.000+ items); retorna
    ``[{'partida_id', 'item', 'descripcion', 'pu_guardado', 'pu_acu'}, ...]``
    ordenado por ítem."""
    rows = conn.execute(
        """SELECT ai.partida_id, ai.cantidad,
                  COALESCE(ai.precio, r.precio, 0) AS precio, r.unidad, r.tipo,
                  p.item, p.descripcion, p.precio_unitario
           FROM acu_items ai
             JOIN partidas p ON p.id = ai.partida_id
             JOIN recursos r ON r.id = ai.recurso_id
           WHERE p.proyecto_id = ? AND p.es_titulo = 0
           ORDER BY ai.partida_id""",
        (pid,)
    ).fetchall()
    grupos: dict[int, list] = {}
    meta: dict[int, dict] = {}
    for x in rows:
        grupos.setdefault(x['partida_id'], []).append(x)
        meta[x['partida_id']] = x
    out = []
    for part_id, items in grupos.items():
        cu = _pu_desde_items(items)
        guardado = meta[part_id]['precio_unitario'] or 0
        # Tolerancia 0.02: PowerCost/Delphin/S10 suman parciales sin redondear
        # cada uno — ±1-2 céntimos de PU es criterio de redondeo entre
        # softwares, no un desglose incompleto. Margen 0.0205 (no 0.02+1e-9):
        # una dif de exactamente 2 céntimos da 0.020000000000000018 en float
        # y con el epsilon fino se marcaban 147 partidas borde (LLAMKASUN).
        if abs(cu - guardado) > 0.0205:
            out.append({'partida_id': part_id,
                        'item': meta[part_id]['item'] or '',
                        'descripcion': meta[part_id]['descripcion'] or '',
                        'pu_guardado': float(guardado), 'pu_acu': cu})
    out.sort(key=lambda d: [int(s) if s.isdigit() else 0 for s in d['item'].split('.')])
    return out


def _siguiente_codigo_inei(conn, indice: str) -> str:
    """Retorna el siguiente código de 7 dígitos para un índice INEI dado (IU(2)+seq(5))."""
    indice = str(indice).zfill(2)[:2]
    row = conn.execute(
        "SELECT MAX(CAST(SUBSTR(codigo,3) AS INTEGER)) as mx FROM recursos WHERE SUBSTR(codigo,1,2)=?",
        (indice,)
    ).fetchone()
    seq = (row['mx'] or 0) + 1
    return f"{indice}{seq:05d}"


def get_acu_items(conn, part_id: int) -> list[dict]:
    """Devuelve los ACU items de una partida con parciales calculados (incluyendo overhead %)."""
    items = conn.execute(
        """SELECT ai.id, ai.recurso_id, ai.cuadrilla, ai.cantidad,
                  r.codigo, r.descripcion, r.tipo, r.unidad, r.indice_inei,
                  COALESCE(ai.precio, r.precio, 0) as precio,
                  r.precio as precio_catalogo
           FROM acu_items ai
           JOIN recursos r ON r.id = ai.recurso_id
           WHERE ai.partida_id = ?
           ORDER BY CASE r.tipo WHEN 'MO' THEN 1 WHEN 'MAT' THEN 2 ELSE 3 END,
                    CASE WHEN r.tipo='MO' THEN mo_rank(r.descripcion) ELSE 0 END,
                    r.descripcion""",
        (part_id,)
    ).fetchall()

    result = [dict(i) for i in items]
    totales_tipo = {'MO': 0.0, 'MAT': 0.0, 'EQ': 0.0}
    pct_pending = []

    for it in result:
        if (it['unidad'] or '').startswith('%'):
            it['parcial'] = 0.0
            pct_pending.append(it)
        else:
            parcial = _r2((it['cantidad'] or 0) * (it['precio'] or 0))
            it['parcial'] = parcial
            tipo = it['tipo'] if it['tipo'] in totales_tipo else 'MAT'
            totales_tipo[tipo] += parcial

    for it in pct_pending:
        unidad_l = (it['unidad'] or '').lower()
        base = totales_tipo.get('MO' if '%mo' in unidad_l else 'MAT' if '%mat' in unidad_l else 'MO', 0)
        it['parcial'] = _r2((it['cantidad'] or 0) / 100 * base)
        it['precio'] = _r2(base)
        tipo = it['tipo'] if it['tipo'] in totales_tipo else 'EQ'
        totales_tipo[tipo] += it['parcial']

    return result, totales_tipo


def get_insumos_para_partidas(conn, partida_ids: list[int]) -> list[dict]:
    """Devuelve insumos agrupados por recurso para una lista de partidas hoja.
    INCLUYE items con unidad `%MO`/`%MAT`.

    **Distribución proporcional**: por cada partida, distribuye su
    `parcial_wysiwyg(metrado, PU)` (= contribución al CD) entre los recursos
    según `parcial_unitario_i / sum(parcial_unitario)`. Esto garantiza que
    `sum(parcial_total de Insumos) == CD del Presupuesto` exactamente,
    sin diferencias por redondeos intermedios.
    """
    insumos: dict[int, dict] = {}
    for pid_p in partida_ids:
        meta = conn.execute(
            "SELECT metrado, precio_unitario FROM partidas WHERE id=?",
            (pid_p,)
        ).fetchone()
        if not meta:
            continue
        metrado = float(meta['metrado'] or 0)
        pu      = float(meta['precio_unitario'] or 0)
        items, _ = get_acu_items(conn, pid_p)
        # Total de la partida para el CD (mismo cálculo que `calcular_totales`).
        partida_total = parcial_wysiwyg(metrado, pu) if (metrado and pu) else 0.0
        # Suma de parciales unitarios desde get_acu_items (incluye % calculados).
        sum_p = sum((it.get('parcial') or 0) for it in items)

        for it in items:
            rid = it['recurso_id']
            if rid not in insumos:
                insumos[rid] = {
                    'recurso_id': rid,
                    'codigo':      it.get('codigo')      or '',
                    'descripcion': it.get('descripcion') or '',
                    'tipo':        it.get('tipo')        or 'MAT',
                    'unidad':      it.get('unidad')      or '',
                    'precio':      float(it.get('precio') or 0),
                    'cantidad_total': 0.0,
                    'parcial_total':  0.0,
                }
            ins = insumos[rid]
            ins['cantidad_total'] += (it.get('cantidad') or 0) * metrado
            # Distribución proporcional del partida_total entre recursos.
            # Si sum_p = 0 (partida sin acu_items útiles) → contribución 0.
            if sum_p > 0:
                ratio = (it.get('parcial') or 0) / sum_p
                ins['parcial_total'] += partida_total * ratio
            # Para items `%` el precio varía por partida. Conservar el máx.
            precio = float(it.get('precio') or 0)
            if precio > ins['precio']:
                ins['precio'] = precio

    # Total objetivo (= sum de partida_totals = CD del Presupuesto) usando
    # los mismos valores raw antes del redondeo final.
    target_total = sum(ins['parcial_total'] for ins in insumos.values())

    # Redondeo final único (los valores intermedios fueron raw).
    for ins in insumos.values():
        ins['parcial_total']  = _r2(ins['parcial_total'])
        ins['cantidad_total'] = _r2(ins['cantidad_total'])

    # Ajuste de cuadre: el redondeo individual de cada `parcial_total` deja
    # una diferencia residual (~0.01-0.05 S/). Aplicar el delta al insumo
    # con mayor parcial para que `sum(insumos) == _r2(target_total) == CD`
    # exactamente — es la práctica estándar en reportes financieros.
    if insumos:
        suma_redondeada = sum(ins['parcial_total'] for ins in insumos.values())
        delta = _r2(target_total - suma_redondeada)
        if delta != 0:
            mayor = max(insumos.values(), key=lambda r: r['parcial_total'])
            mayor['parcial_total'] = _r2(mayor['parcial_total'] + delta)

    # Ordenar: MO=1 (por jerarquía: capataz>operario>oficial>peón), EQ=2,
    # otros=3, luego por descripcion.
    tipo_orden = {'MO': 1, 'EQ': 2}
    return sorted(
        insumos.values(),
        key=lambda r: (tipo_orden.get(r['tipo'], 3),
                       _orden_mo(r['descripcion']) if r['tipo'] == 'MO' else 0,
                       (r['descripcion'] or '').lower()),
    )


def get_insumos_proyecto(conn, pid: int) -> list[dict]:
    """Devuelve insumos totales del proyecto agrupados por recurso.
    INCLUYE overhead `%MO`/`%MAT` (ver `get_insumos_para_partidas`)."""
    rows = conn.execute(
        "SELECT id FROM partidas WHERE proyecto_id=? AND es_titulo=0",
        (pid,)
    ).fetchall()
    return get_insumos_para_partidas(conn, [r['id'] for r in rows])


# ── Pool unificado para el RAG de «Sugerir partidas» ─────────────────────────
# El RAG (fuzzy + semántico) y el enganche de ACU al importar NO miran solo
# biblioteca_cu: también los ACUs de los proyectos PROPIOS del usuario (partidas
# con acu_items). Así el trabajo acumulado de cada usuario alimenta las
# sugerencias y enlaza sus propios costos sin tener que «Guardar en biblioteca».

_POOL_RAG_CACHE = None   # (firma, lista) — caché en proceso del pool deduplicado


def pool_partidas_rag(conn) -> list[dict]:
    """Candidatos del RAG = biblioteca_cu + partidas propias CON ACU,
    DEDUPLICADO por (descripción normalizada, unidad). El dedup es clave para que
    NO se degrade con cientos de proyectos: las partidas se repiten muchísimo
    entre obras, así el pool queda acotado a la terminología única.
    Cada item: {descripcion, unidad, origen 'bib'|'proj', ref_id, _norm}.
    En empates gana 'proj' (los costos reales del usuario) y luego el más reciente
    (mayor ref_id). Cacheado en proceso por firma → se reusa en las ~50 llamadas
    del enganche al importar y entre consultas."""
    global _POOL_RAG_CACHE
    firma = firma_pool_rag(conn)
    if _POOL_RAG_CACHE and _POOL_RAG_CACHE[0] == firma:
        return _POOL_RAG_CACHE[1]
    from core.ai_specs import _normalizar_desc
    best = {}   # (norm, unidad) -> item

    def _considerar(desc, unidad, origen, ref_id):
        nrm = _normalizar_desc(desc)
        if not nrm:
            return
        key = (nrm, unidad)
        prev = best.get(key)
        gana = (prev is None
                or ((origen == 'proj') and prev['origen'] == 'bib')
                or (origen == prev['origen'] and ref_id > prev['ref_id']))
        if gana:
            best[key] = {'descripcion': desc, 'unidad': unidad,
                         'origen': origen, 'ref_id': ref_id, '_norm': nrm}

    for r in conn.execute(
        "SELECT id, descripcion, unidad FROM biblioteca_cu "
        "WHERE descripcion IS NOT NULL AND descripcion != ''"
    ):
        _considerar(r['descripcion'], r['unidad'] or '', 'bib', r['id'])
    for r in conn.execute(
        "SELECT p.id, p.descripcion, p.unidad FROM partidas p "
        "WHERE p.es_titulo = 0 AND p.descripcion IS NOT NULL AND p.descripcion != '' "
        "AND EXISTS (SELECT 1 FROM acu_items a WHERE a.partida_id = p.id)"
    ):
        _considerar(r['descripcion'], r['unidad'] or '', 'proj', r['id'])
    out = list(best.values())
    _POOL_RAG_CACHE = (firma, out)
    return out


def firma_pool_rag(conn) -> str:
    """Firma para invalidar el índice semántico cuando cambia el pool — sea la
    biblioteca o los proyectos del usuario (nº filas + max id de cada fuente)."""
    bn, bx = conn.execute(
        "SELECT COUNT(*), COALESCE(MAX(id),0) FROM biblioteca_cu").fetchone()
    pn, px = conn.execute(
        "SELECT COUNT(*), COALESCE(MAX(id),0) FROM partidas WHERE es_titulo=0"
    ).fetchone()
    return f"{bn}:{bx}:{pn}:{px}"


def acu_de_pool(conn, origen: str, ref_id: int) -> dict | None:
    """ACU de un candidato del pool, sea de biblioteca o de un proyecto propio.
    Retorna {rendimiento, costo_unitario, items:[{recurso_id,cuadrilla,cantidad,
    precio}]} — composición compatible para copiar a acu_items al importar."""
    if origen == 'bib':
        cu = conn.execute(
            "SELECT rendimiento, costo_unitario FROM biblioteca_cu WHERE id=?",
            (ref_id,)).fetchone()
        if not cu:
            return None
        items = conn.execute(
            "SELECT recurso_id, cuadrilla, cantidad, precio "
            "FROM biblioteca_acu_items WHERE cu_id=?", (ref_id,)).fetchall()
        return {'rendimiento': cu['rendimiento'],
                'costo_unitario': cu['costo_unitario'],
                'items': [dict(i) for i in items]}
    p = conn.execute(
        "SELECT rendimiento, precio_unitario FROM partidas WHERE id=?",
        (ref_id,)).fetchone()
    if not p:
        return None
    items = conn.execute(
        "SELECT recurso_id, cuadrilla, cantidad, precio "
        "FROM acu_items WHERE partida_id=?", (ref_id,)).fetchall()
    return {'rendimiento': p['rendimiento'],
            'costo_unitario': p['precio_unitario'],
            'items': [dict(i) for i in items]}


def precios_inconsistentes(conn, pid: int) -> dict[int, dict]:
    """Detecta recursos cuyo precio efectivo `COALESCE(ai.precio, r.precio)` varía
    entre las líneas de ACU del proyecto. Excluye overhead (`%MO`/`%MAT`), cuyo
    "precio" es derivado y por diseño varía por partida.

    Retorna ``{recurso_id: {...}}`` SOLO para recursos con >1 variante::

        {'descripcion', 'unidad', 'precio_catalogo',
         'variantes': [(precio, n_lineas), ...],   # orden desc por n_lineas
         'sugerido': float}                          # modal; empate -> catálogo
    """
    rows = conn.execute(
        """SELECT ai.recurso_id rid, r.descripcion d, r.unidad u, r.precio cat,
                  ROUND(COALESCE(ai.precio, r.precio, 0), 2) eff
           FROM acu_items ai
             JOIN partidas p ON p.id = ai.partida_id
             JOIN recursos r ON r.id = ai.recurso_id
           WHERE p.proyecto_id = ?
             AND SUBSTR(COALESCE(r.unidad, ''), 1, 1) != '%'""",
        (pid,)
    ).fetchall()
    agg: dict[int, dict] = {}
    for x in rows:
        info = agg.setdefault(x['rid'], {
            'descripcion': x['d'] or '', 'unidad': x['u'] or '',
            'precio_catalogo': float(x['cat'] or 0), '_cnt': {}})
        eff = x['eff'] or 0.0
        info['_cnt'][eff] = info['_cnt'].get(eff, 0) + 1
    out: dict[int, dict] = {}
    for rid, info in agg.items():
        cnt = info.pop('_cnt')
        if len(cnt) <= 1:
            continue
        maxn = max(cnt.values())
        top = sorted(p for p, n in cnt.items() if n == maxn)
        info['sugerido'] = top[0] if len(top) == 1 else _r2(info['precio_catalogo'])
        info['variantes'] = sorted(cnt.items(), key=lambda kv: (-kv[1], kv[0]))
        out[rid] = info
    return out


def unificar_precio_recurso(conn, pid: int, recurso_id: int, precio: float) -> list[int]:
    """Fija ``acu_items.precio = precio`` en TODAS las líneas de ACU del recurso
    dentro del proyecto y recalcula el PU de las partidas afectadas (sin commit;
    el llamador hace ``conn.commit()``). Retorna los ``partida_id`` afectados.

    Mismo mecanismo que la edición de precio en el panel ACU / tab Insumos
    (project-wide), por lo que garantiza un precio único por insumo en el proyecto.
    """
    conn.execute(
        """UPDATE acu_items SET precio=?
           WHERE recurso_id=?
             AND partida_id IN (SELECT id FROM partidas WHERE proyecto_id=?)""",
        (precio, recurso_id, pid)
    )
    afectadas = [r[0] for r in conn.execute(
        """SELECT DISTINCT ai.partida_id FROM acu_items ai
           JOIN partidas p ON p.id = ai.partida_id
           WHERE ai.recurso_id=? AND p.proyecto_id=?""",
        (recurso_id, pid)
    ).fetchall()]
    for pa in afectadas:
        _recalcular_pu(conn, pa)
    return afectadas


def precio_recurso_en_proyecto(conn, pid: int, recurso_id: int):
    """Precio vigente de un recurso DENTRO de un proyecto: el más usado
    (modal) entre sus líneas de ACU, o ``None`` si el recurso aún no se usa
    en el proyecto.

    Regla «un insumo = un precio por proyecto»: toda inserción de un recurso
    ya presente (agregar del catálogo, pegar ACU, pegar partidas) debe entrar
    con este precio y NO con el del catálogo/origen, para no crear el mismo
    insumo con precios diferentes.

    Excluye overhead (`%MO`/`%MAT`): su "precio" es derivado y varía por
    partida por diseño (mismo criterio que `precios_inconsistentes`)."""
    row = conn.execute(
        """SELECT COALESCE(ai.precio, r.precio, 0) eff, COUNT(*) n
           FROM acu_items ai
             JOIN partidas p ON p.id = ai.partida_id
             JOIN recursos r ON r.id = ai.recurso_id
           WHERE p.proyecto_id = ? AND ai.recurso_id = ?
             AND SUBSTR(COALESCE(r.unidad, ''), 1, 1) != '%'
           GROUP BY eff ORDER BY n DESC, eff DESC LIMIT 1""",
        (pid, recurso_id)
    ).fetchone()
    return float(row['eff']) if row else None


# ─── PLANTILLAS DEL PIE (guardadas por el usuario, reutilizables) ──────────────

def guardar_plantilla_pie(nombre: str, items: list) -> None:
    """Guarda (o reemplaza por nombre) una plantilla de detalle del pie.
    `items` = lista de dicts {tipo,descripcion,unidad,cantidad,pct_participacion,
    precio}. Se persiste como JSON en la tabla `pie_plantillas` (global, sirve
    para cualquier proyecto)."""
    import json
    js = json.dumps(items, ensure_ascii=False)
    conn = get_db()
    try:
        cur = conn.execute(
            "UPDATE pie_plantillas SET items_json=?, creado_en=CURRENT_TIMESTAMP"
            " WHERE nombre=?", (js, nombre)
        )
        if cur.rowcount == 0:
            conn.execute(
                "INSERT INTO pie_plantillas (nombre, items_json) VALUES (?,?)",
                (nombre, js)
            )
        conn.commit()
    finally:
        conn.close()


def listar_plantillas_pie_guardadas() -> list[tuple[int, str]]:
    """Lista (id, nombre) de las plantillas del pie guardadas por el usuario."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, nombre FROM pie_plantillas ORDER BY LOWER(nombre)"
        ).fetchall()
        return [(r['id'], r['nombre']) for r in rows]
    finally:
        conn.close()


def obtener_plantilla_pie_guardada(plantilla_id: int) -> list:
    """Devuelve la lista de ítems de una plantilla guardada (o [] si no existe)."""
    import json
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT items_json FROM pie_plantillas WHERE id=?", (plantilla_id,)
        ).fetchone()
        return json.loads(row['items_json']) if row else []
    finally:
        conn.close()


def eliminar_plantilla_pie_guardada(plantilla_id: int) -> None:
    conn = get_db()
    try:
        conn.execute("DELETE FROM pie_plantillas WHERE id=?", (plantilla_id,))
        conn.commit()
    finally:
        conn.close()


# ─── PORTAFOLIOS ──────────────────────────────────────────────────────────────

def listar_portafolios(conn=None) -> list[dict]:
    """Lista de portafolios con conteo de proyectos asociados.
    Si ``conn`` es None, abre/cierra la conexión internamente."""
    own = conn is None
    if own:
        conn = get_db()
    rows = conn.execute(
        """SELECT p.id, p.nombre, p.color, p.descripcion, p.orden,
                  COALESCE((SELECT COUNT(*) FROM proyectos
                            WHERE portafolio_id=p.id), 0) AS n_proyectos
           FROM portafolios p ORDER BY p.orden, LOWER(p.nombre)"""
    ).fetchall()
    if own:
        conn.close()
    return [dict(r) for r in rows]


def crear_portafolio(nombre: str, color: str = '#667885',
                     descripcion: str = '') -> int:
    """Crea un portafolio nuevo. Retorna su id. Lanza si nombre duplicado."""
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO portafolios (nombre, color, descripcion) VALUES (?,?,?)",
            (nombre.strip(), color, descripcion.strip())
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def actualizar_portafolio(portafolio_id: int, nombre: str | None = None,
                          color: str | None = None,
                          descripcion: str | None = None) -> None:
    """Actualiza campos no-None de un portafolio existente."""
    if nombre is None and color is None and descripcion is None:
        return
    sets, args = [], []
    if nombre is not None:
        sets.append("nombre=?"); args.append(nombre.strip())
    if color is not None:
        sets.append("color=?"); args.append(color)
    if descripcion is not None:
        sets.append("descripcion=?"); args.append(descripcion.strip())
    args.append(portafolio_id)
    conn = get_db()
    try:
        conn.execute(f"UPDATE portafolios SET {', '.join(sets)} WHERE id=?", args)
        conn.commit()
    finally:
        conn.close()


def eliminar_portafolio(portafolio_id: int) -> None:
    """Elimina el portafolio. Los proyectos quedan con portafolio_id=NULL
    (ON DELETE SET NULL en la FK)."""
    conn = get_db()
    try:
        conn.execute("DELETE FROM portafolios WHERE id=?", (portafolio_id,))
        conn.commit()
    finally:
        conn.close()


def mover_proyecto_portafolio(proyecto_id: int,
                              portafolio_id: int | None) -> None:
    """Asigna ``portafolio_id`` (o NULL para sin clasificar) al proyecto."""
    conn = get_db()
    try:
        conn.execute(
            "UPDATE proyectos SET portafolio_id=? WHERE id=?",
            (portafolio_id, proyecto_id)
        )
        conn.commit()
    finally:
        conn.close()
