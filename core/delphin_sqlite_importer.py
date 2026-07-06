# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""Importador de proyectos desde una base de datos SQLite de Delphin Express.

Delphin tiene dos universos paralelos de datos:

  1. BIBLIOTECA (independiente del proyecto):
     - `partida` + `costo_partida` + `analisis_costo` + `composicion_analisiscosto`
     Aquí viven los ACUs "plantilla" que el usuario puede arrastrar.

  2. PROYECTO ACTIVO (lo que el usuario realmente cargó al presupuesto):
     - `costo_unitario` con `id_presupuesto`         ← partidas del proyecto
     - `subtotal_costounitario`                       ← subtotales MO/MAT/EQ
     - `composicion_costounitario`                    ← insumos del ACU
     - El campo `costo_unitario.id_costopadre` arma la jerarquía recursiva.

El importador trabaja sobre el grupo 2 (proyecto activo), que es lo único
relevante para reproducir un presupuesto en ingePresupuestos.
"""
import os
import re
import sqlite3
from typing import Optional


# ── Helpers ────────────────────────────────────────────────────────────────

def _str(v) -> str:
    if v is None:
        return ''
    return str(v).strip()


def _num(v, default: float = 0.0) -> float:
    if v is None or v == '':
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _fecha_iso(fecha_str: str) -> str:
    if not fecha_str:
        return ''
    return _str(fecha_str)


def _codigo_recurso(codigo_clase: str, codigo_subclase: str,
                    codigo_listaprecio: str, id_listaprecio: str) -> str:
    """Construye un código de 7 dígitos a partir de los campos Delphin.

    Convención ingePresupuestos: 7 dígitos = 2 INEI + 5 correlativo.

    Delphin guarda: codigo_clase (2d INEI) + codigo_subclase (3d) +
    codigo_listaprecio (4d). Aplastamos subclase+listaprecio a 5 dígitos
    derivados (subclase·1000 + listaprecio) para conservar la identidad
    única de cada recurso dentro de su clase INEI.
    """
    cc_raw = (codigo_clase or '').strip()
    if not cc_raw or cc_raw == '00':
        # Sin clase: derivar todo el código del id_listaprecio
        m = re.search(r'(\d+)', id_listaprecio or '')
        if m:
            return str(int(m.group(1))).zfill(7)[-7:]
        return '0000000'

    # Tomar los dos primeros dígitos de la clase (INEI 01..80)
    try:
        cc = int(cc_raw) % 100
    except ValueError:
        cc = 0
    try:
        ss = int((codigo_subclase or '0').strip())
    except ValueError:
        ss = 0
    try:
        pp = int((codigo_listaprecio or '0').strip())
    except ValueError:
        pp = 0

    # 5 dígitos del correlativo (subclase · 1000 + listaprecio)
    correlativo = (ss * 1000 + pp) % 100000
    return f"{cc:02d}{correlativo:05d}"


# ── Parser principal ───────────────────────────────────────────────────────

def import_delphin_sqlite(filepath: str,
                          proyecto_id_delphin: Optional[str] = None,
                          presupuesto_id_delphin: Optional[str] = None):
    """Lee la DB Delphin y devuelve (info, partidas, acus, recursos, None)."""
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"No existe: {filepath}")

    src = sqlite3.connect(filepath)
    src.row_factory = sqlite3.Row

    try:
        # ── 1. Proyecto + presupuesto ───────────────────────────────────────
        if proyecto_id_delphin:
            proy = src.execute(
                "SELECT * FROM proyecto WHERE id_proyecto=?",
                (proyecto_id_delphin,)
            ).fetchone()
        else:
            proy = src.execute("SELECT * FROM proyecto LIMIT 1").fetchone()
        if not proy:
            raise ValueError("La base de datos no contiene proyectos.")

        if presupuesto_id_delphin:
            pres = src.execute(
                "SELECT * FROM presupuesto WHERE id_presupuesto=?",
                (presupuesto_id_delphin,)
            ).fetchone()
        else:
            pres = src.execute(
                "SELECT * FROM presupuesto WHERE id_proyecto=? "
                "ORDER BY COALESCE(costo_directo, 0) DESC LIMIT 1",
                (proy['id_proyecto'],)
            ).fetchone()
        if not pres:
            raise ValueError(
                f"El proyecto {proy['id_proyecto']} no tiene presupuestos."
            )

        info = {
            'nombre':          _str(proy['nombre_proyecto'])
                                or _str(pres['nombre_presupuesto']),
            'cliente':         '',
            'ubicacion':       _str(proy['id_ubicacion']),
            'sub_presupuesto': _str(pres['nombre_presupuesto']) or 'Presupuesto',
            'costo_al':        _fecha_iso(_str(proy['fecha_proyecto'])),
            # Porcentajes del pie de presupuesto (Delphin los guarda en
            # la tabla `presupuesto`). Si vienen 0 deben respetarse.
            'gf_pct':          _num(pres['porcentaje_gasto']),
            'utilidad_pct':    _num(pres['porcentaje_utilidad']),
            'igv_pct':         _num(pres['porcentaje_igv']),
        }

        # ── 2. Catálogos de mapeo ───────────────────────────────────────────
        tipos_raw = {
            r['id_tipocosto']: _str(r['descripcion_tipocosto']).upper()
            for r in src.execute("SELECT * FROM tipo_costo").fetchall()
        }

        def map_tipo(id_tipocosto: str) -> str:
            """Mapea tipo_costo Delphin → MO/MAT/EQ/SC ingePresupuestos.

            Delphin distingue 5 tipos:
              TC01 MANO DE OBRA   → MO
              TC02 MATERIALES     → MAT
              TC03 EQUIPO         → EQ
              TC04 SUB-CONTRATOS  → SC
              TC05 SUB-PARTIDAS   → SC (también servicios)
            """
            d = tipos_raw.get(id_tipocosto, '')
            if 'MANO' in d or 'OBRA' in d:
                return 'MO'
            if 'EQUIP' in d or 'MAQUIN' in d or 'HERRAMIENTA' in d:
                return 'EQ'
            if 'SUB' in d or 'CONTRATO' in d or 'SERVICIO' in d:
                return 'SC'
            return 'MAT'

        unidades = {
            r['id_unidad']: _str(r['descripcion_unidad'])
                            or _str(r['abreviatura_unidad'])
            for r in src.execute("SELECT * FROM unidad").fetchall()
        }

        # Subtotales del proyecto activo: id_subtotal → tipo MO/MAT/EQ/SC
        subtotales = {
            r['id_subtotal']: map_tipo(r['id_tipocosto'])
            for r in src.execute("SELECT * FROM subtotal_costounitario").fetchall()
        }

        # ── 3. Cargar partidas del proyecto (todos los costo_unitario) ──────
        # Si se pasa presupuesto_id_delphin tomamos sólo ese; si no, tomamos
        # TODOS los costo_unitario del proyecto (que pueden estar repartidos
        # en varios sub-presupuestos como Estructura/Arquitectura/Eléctricas/
        # Sanitarias). Las numeraciones de cada sub-presupuesto van con
        # prefijo distinto (1.x, 2.x, 3.x...) así que no chocan al unirlas.
        if presupuesto_id_delphin:
            cus = src.execute(
                "SELECT * FROM costo_unitario WHERE id_presupuesto=?",
                (presupuesto_id_delphin,)
            ).fetchall()
        else:
            pres_ids = [r['id_presupuesto'] for r in src.execute(
                "SELECT id_presupuesto FROM presupuesto WHERE id_proyecto=?",
                (proy['id_proyecto'],)
            ).fetchall()]
            if not pres_ids:
                cus = []
            else:
                placeholders = ",".join("?" * len(pres_ids))
                cus = src.execute(
                    f"SELECT * FROM costo_unitario WHERE id_presupuesto "
                    f"IN ({placeholders})",
                    pres_ids
                ).fetchall()
        cus_by_id = {r['id_costounitario']: dict(r) for r in cus}

        # Identificar quién es padre (es título) — los que aparecen como id_costopadre
        padres_set = set()
        for r in cus_by_id.values():
            if r['id_costopadre']:
                padres_set.add(r['id_costopadre'])

        # Profundidad para nivel
        def nivel(cuid: str) -> int:
            n, cur = 0, cuid
            seen = set()
            while cur:
                cur = cus_by_id.get(cur, {}).get('id_costopadre') or None
                if not cur or cur in seen:
                    break
                seen.add(cur)
                n += 1
            return n

        # Orden DFS: raíces primero, hijos en orden de posicion_costo
        def hijos_de(parent_id: Optional[str]) -> list[str]:
            r = [cuid for cuid, row in cus_by_id.items()
                 if (row.get('id_costopadre') or None) == parent_id]
            r.sort(key=lambda x: (cus_by_id[x].get('posicion_costo') or 0,
                                   cus_by_id[x].get('numeracion_costo') or ''))
            return r

        # ── 4. Construir partidas_data + mapa item_de ───────────────────────
        partidas_data: list = []
        item_de: dict[str, str] = {}     # id_costounitario → item visible
        usados: set[str] = set()

        def emit(cuid: str):
            row = cus_by_id[cuid]
            base = _str(row['numeracion_costo']) or _str(cuid)
            item = base
            n = 1
            while item in usados:
                n += 1
                item = f"{base}/{n}"
            usados.add(item)
            item_de[cuid] = item

            # Criterio robusto: es título si tiene hijos. En MINICOMPLEJO el
            # campo id_analisiscosto está vacío incluso para hojas con ACU,
            # así que ya no lo usamos como criterio.
            es_titulo = cuid in padres_set
            und = unidades.get(row['id_unidad'], '') or ''
            if not es_titulo and not und:
                und = 'und'

            partidas_data.append({
                'item':            item,
                'descripcion':     _str(row['descripcion_costo']),
                'unidad':          und,
                'metrado':         _num(row['cantidad_metrado']) or _num(row['cantidad']),
                'precio_unitario': _num(row['costo_unitario']),
                'nivel':           min(nivel(cuid) + 1, 4),
                'es_titulo':       1 if es_titulo else 0,
            })

            for child in hijos_de(cuid):
                emit(child)

        for root in hijos_de(None):
            emit(root)

        # ── 5. ACUs (composiciones del proyecto activo) ─────────────────────
        acus_data: dict = {}
        recursos_uniq: dict[str, dict] = {}

        for cuid, row in cus_by_id.items():
            if cuid in padres_set:
                continue   # es título, no tiene ACU propio
            # Subtotales y composiciones de ESTE costo_unitario
            subs = src.execute(
                "SELECT * FROM subtotal_costounitario WHERE id_costounitario=?",
                (cuid,)
            ).fetchall()
            if not subs:
                continue
            sub_ids = [s['id_subtotal'] for s in subs]
            placeholders = ",".join("?" * len(sub_ids))
            comps = src.execute(
                f"SELECT * FROM composicion_costounitario "
                f"WHERE id_subtotal IN ({placeholders}) "
                f"ORDER BY posicion_composicion",
                sub_ids
            ).fetchall()

            items_acu = []
            for cmp_ in comps:
                tipo = subtotales.get(cmp_['id_subtotal'], 'MAT')
                unidad = unidades.get(cmp_['id_unidad'], '') or 'und'
                codigo = _codigo_recurso(
                    cmp_['codigo_clase'], cmp_['codigo_subclase'],
                    cmp_['codigo_listaprecio'], cmp_['id_listaprecio']
                )
                descripcion = _str(cmp_['descripcion_composicion']) \
                              or '(sin descripción)'
                precio = _num(cmp_['costo_composicion'])
                cantidad = _num(cmp_['cantidad_composicion'])
                cuadrilla = _num(cmp_['personal_base'])

                items_acu.append({
                    'tipo':        tipo,
                    'codigo':      codigo,
                    'descripcion': descripcion,
                    'unidad':      unidad,
                    'cuadrilla':   cuadrilla,
                    'cantidad':    cantidad,
                    'precio':      precio,
                })

                if codigo not in recursos_uniq or (
                        precio > 0 and recursos_uniq[codigo]['precio'] == 0):
                    recursos_uniq[codigo] = {
                        'codigo':      codigo,
                        'descripcion': descripcion,
                        'tipo':        tipo,
                        'unidad':      unidad,
                        'precio':      precio,
                    }

            item = item_de.get(cuid)
            if item is None or not items_acu:
                continue
            rendimiento = _num(row['productividad'], 1.0)
            acus_data[item] = {
                'rendimiento': rendimiento,
                'items':       items_acu,
            }

        recursos_data = list(recursos_uniq.values())

        # ── 6. Metrados detallados (tabla `metrado`) ────────────────────────
        # Delphin guarda el detalle del cómputo en `metrado` con FK a
        # costo_unitario.id_costounitario. Cada fila tiene unidades, largo,
        # ancho, alto, parcial. Lo agrupamos por item del proyecto.
        metrados_data: dict[str, list[dict]] = {}
        try:
            met_rows = src.execute(
                "SELECT id_costounitario, descripcion_metrado, unidades, "
                "       cantidadxunidad, largo, ancho, alto, parcial_metrado, "
                "       posicion "
                "FROM metrado "
                "ORDER BY id_costounitario, COALESCE(posicion, 0)"
            ).fetchall()
        except sqlite3.OperationalError:
            met_rows = []

        for r in met_rows:
            cuid = r['id_costounitario']
            item = item_de.get(cuid)
            if not item:
                continue   # metrado huérfano (apunta a costo_unitario fuera del presupuesto)
            metrados_data.setdefault(item, []).append({
                'descripcion':   _str(r['descripcion_metrado']),
                'n_estructuras': _num(r['unidades']),
                'n_elementos':   _num(r['cantidadxunidad']),
                'area':          None,   # Delphin no tiene 'area' separada
                'largo':         _num(r['largo']),
                'ancho':         _num(r['ancho']),
                'alto':          _num(r['alto']),
                'parcial':       _num(r['parcial_metrado']),
            })

        return info, partidas_data, acus_data, recursos_data, (metrados_data or None)

    finally:
        src.close()


# ── API pública para listar proyectos/presupuestos ─────────────────────────

# ── Importador de Índices INEI históricos ─────────────────────────────────

# Mapeo numero_region Delphin → codigo area ingePresupuestos.
# Delphin sigue las 6 regiones CAPECO; ingePresupuestos usa las 6 áreas INEI.
# El mapeo es por correspondencia geográfica más cercana:
#   D1 Costa Norte         (Tumbes..San Martín)        → 02 Norte
#   D2 Costa Central       (Lima, Ancash, Ica)         → 01 Lima Metropolitana
#   D3 Sierra Centro       (Huánuco..Ucayali)          → 03 Centro
#   D4 Sur Costa           (Arequipa, Moquegua, Tacna) → 05 Sur
#   D5 Selva Baja          (Loreto)                    → 04 Sur Medio y Selva
#   D6 Sierra Sur          (Cusco..Madre de Dios)      → 06 Nacional (*)
# (*) D6 no tiene equivalente directo en el catálogo de ingePresupuestos;
#     se aparca en "Nacional" para no perder los datos ni sobreescribir D4/D5.
_MAPEO_REGION_DELPHIN_A_AREA = {
    1: '02',
    2: '01',
    3: '03',
    4: '05',
    5: '04',
    6: '06',
}


def import_inei_delphin_sqlite(filepath: str) -> dict:
    """Lee los índices INEI históricos de una DB Delphin y los carga a la
    tabla `indices_inei_valores` de ingePresupuestos.

    Retorna un dict con estadísticas: {n_filas_origen, n_insertadas,
    n_ignoradas, anios, codigos, areas_destino, mapeo_regiones}.
    """
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"No existe: {filepath}")

    src = sqlite3.connect(filepath)
    src.row_factory = sqlite3.Row
    try:
        rows_src = src.execute(
            "SELECT codigo_clase, numero_anio, numero_mes, numero_region, "
            "       valor_indice "
            "FROM indice_precio "
            "WHERE valor_indice > 0 AND numero_anio >= 1900"
        ).fetchall()
    finally:
        src.close()

    # Convertir filas Delphin a formato ingePresupuestos
    rows_dst: list[dict] = []
    for r in rows_src:
        codigo = str(r['codigo_clase'] or '').strip().zfill(2)[:2]
        try:
            anio = int(r['numero_anio'])
            mes  = int(r['numero_mes'])
            region = int(r['numero_region'])
            valor = float(r['valor_indice'])
        except (TypeError, ValueError):
            continue
        if not codigo or codigo == '00' or anio < 1900:
            continue
        if not (1 <= mes <= 12):
            continue
        if valor <= 0:
            continue
        area = _MAPEO_REGION_DELPHIN_A_AREA.get(region)
        if not area:
            continue
        rows_dst.append({
            'codigo': codigo,
            'anio':   anio,
            'mes':    mes,
            'area':   area,
            'valor':  valor,
        })

    # Persistir vía el helper existente
    from core.indices_inei import guardar_valores
    ok, err = guardar_valores(rows_dst)

    # Estadísticas
    anios = sorted({r['anio'] for r in rows_dst})
    codigos = sorted({r['codigo'] for r in rows_dst})
    areas_destino = sorted({r['area'] for r in rows_dst})
    regiones_origen = sorted({int(r['numero_region']) for r in rows_src
                              if r['numero_region'] is not None})

    return {
        'n_filas_origen': len(rows_src),
        'n_insertadas':   ok,
        'n_ignoradas':    err,
        'anios':          anios,
        'codigos':        codigos,
        'areas_destino':  areas_destino,
        'regiones_origen': regiones_origen,
        'mapeo_regiones': _MAPEO_REGION_DELPHIN_A_AREA,
    }


# ── Importador de Biblioteca de ACU ────────────────────────────────────────

def import_biblioteca_delphin_sqlite(filepath: str,
                                     modo: str = 'merge') -> dict:
    """Importa la biblioteca de ACU desde una DB Delphin.

    Lee la biblioteca (no el proyecto activo): `analisis_costo`,
    `subtotal_analisiscosto` y `composicion_analisiscosto`. Inserta los ACU
    en `biblioteca_cu` y sus insumos en `biblioteca_acu_items`. Los recursos
    que no existan en `recursos` se crean automáticamente.

    ``modo``:
        - 'merge'       : si existe (descripcion, unidad, grupo), actualiza
                          rendimiento/costo/especificaciones y reemplaza
                          completamente los ACU items.
        - 'solo_nuevos' : ignora los CU que ya existen, sólo agrega nuevos.
        - 'duplicar'    : inserta sin dedup (puede generar duplicados).
    """
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"No existe: {filepath}")

    src = sqlite3.connect(filepath)
    src.row_factory = sqlite3.Row

    try:
        # ── Catálogos de mapeo ──
        tipos_raw = {
            r['id_tipocosto']: _str(r['descripcion_tipocosto']).upper()
            for r in src.execute("SELECT * FROM tipo_costo").fetchall()
        }

        def map_tipo(id_tipocosto: str) -> str:
            d = tipos_raw.get(id_tipocosto, '')
            if 'MANO' in d or 'OBRA' in d:
                return 'MO'
            if 'EQUIP' in d or 'MAQUIN' in d or 'HERRAMIENTA' in d:
                return 'EQ'
            if 'SUB' in d or 'CONTRATO' in d or 'SERVICIO' in d:
                return 'SC'
            return 'MAT'

        unidades = {
            r['id_unidad']: _str(r['descripcion_unidad'])
                            or _str(r['abreviatura_unidad'])
            for r in src.execute("SELECT * FROM unidad").fetchall()
        }

        # Subtotales: id_subtotal → (tipo MO/MAT/EQ, id_analisiscosto)
        subtotales = {
            r['id_subtotal']: (map_tipo(r['id_tipocosto']), r['id_analisiscosto'])
            for r in src.execute("SELECT * FROM subtotal_analisiscosto").fetchall()
        }

        # ── Lectura de la biblioteca ──
        acs = src.execute(
            "SELECT * FROM analisis_costo ORDER BY descripcion_costo"
        ).fetchall()

        # Pre-fetch de TODAS las composiciones agrupadas por id_analisiscosto
        comps_por_ac: dict[str, list] = {}
        for cmp_ in src.execute(
            "SELECT c.*, s.id_analisiscosto FROM composicion_analisiscosto c "
            "JOIN subtotal_analisiscosto s ON s.id_subtotal=c.id_subtotal "
            "ORDER BY c.posicion_composicion"
        ).fetchall():
            comps_por_ac.setdefault(cmp_['id_analisiscosto'], []).append(cmp_)

    finally:
        src.close()

    # ── Persistir en ingePresupuestos ──
    from core.database import get_db
    n_creados = 0
    n_actualizados = 0
    n_ignorados = 0
    n_recursos_creados = 0
    n_items = 0

    conn = get_db()
    try:
        for ac in acs:
            desc = _str(ac['descripcion_costo'])
            if not desc:
                n_ignorados += 1
                continue
            unidad = unidades.get(ac['id_unidad'], '') or ''
            rendimiento = _num(ac['productividad'], 1.0)
            costo = _num(ac['costo_unitario'])
            grupo = ''   # Delphin no tiene grupo de ACU equivalente; queda vacío
            specs = _str(ac['especificaciones'])

            # Dedup
            existente = None
            if modo in ('merge', 'solo_nuevos'):
                existente = conn.execute(
                    "SELECT id FROM biblioteca_cu "
                    "WHERE descripcion=? AND unidad=? AND grupo=?",
                    (desc, unidad, grupo)
                ).fetchone()

            if existente and modo == 'solo_nuevos':
                n_ignorados += 1
                continue

            if existente and modo == 'merge':
                cu_id = existente['id']
                conn.execute(
                    "UPDATE biblioteca_cu SET rendimiento=?, costo_unitario=?, "
                    "especificaciones=? WHERE id=?",
                    (rendimiento, costo, specs, cu_id)
                )
                conn.execute(
                    "DELETE FROM biblioteca_acu_items WHERE cu_id=?",
                    (cu_id,)
                )
                n_actualizados += 1
            else:
                cur = conn.execute(
                    "INSERT INTO biblioteca_cu "
                    "(descripcion, unidad, rendimiento, costo_unitario, grupo, "
                    " especificaciones, usos) VALUES (?,?,?,?,?,?,0)",
                    (desc, unidad, rendimiento, costo, grupo, specs)
                )
                cu_id = cur.lastrowid
                n_creados += 1

            # Insertar los items del ACU
            for cmp_ in comps_por_ac.get(ac['id_analisiscosto'], []):
                tipo = subtotales.get(cmp_['id_subtotal'], ('MAT', None))[0]
                u = unidades.get(cmp_['id_unidad'], '') or 'und'
                codigo = _codigo_recurso(
                    cmp_['codigo_clase'], cmp_['codigo_subclase'],
                    cmp_['codigo_listaprecio'], cmp_['id_listaprecio']
                )
                r_desc = _str(cmp_['descripcion_composicion']) or '(sin descripción)'
                r_precio = _num(cmp_['costo_composicion'])

                # Crear/obtener recurso
                rec = conn.execute(
                    "SELECT id FROM recursos WHERE codigo=?", (codigo,)
                ).fetchone()
                if not rec:
                    inei = (codigo[:2] if len(codigo) >= 2 else '')
                    cur = conn.execute(
                        "INSERT INTO recursos "
                        "(codigo, descripcion, tipo, unidad, precio, indice_inei) "
                        "VALUES (?,?,?,?,?,?)",
                        (codigo, r_desc, tipo, u, r_precio, inei)
                    )
                    rec_id = cur.lastrowid
                    n_recursos_creados += 1
                else:
                    rec_id = rec['id']

                conn.execute(
                    "INSERT INTO biblioteca_acu_items "
                    "(cu_id, recurso_id, cuadrilla, cantidad, precio) VALUES (?,?,?,?,?)",
                    (cu_id, rec_id,
                     _num(cmp_['personal_base']),
                     _num(cmp_['cantidad_composicion']),
                     r_precio)
                )
                n_items += 1
        conn.commit()
    finally:
        conn.close()

    return {
        'ok':                 True,
        'msg':                f"Biblioteca importada desde Delphin.",
        'n_acs_origen':       len(acs),
        'n_creados':          n_creados,
        'n_actualizados':     n_actualizados,
        'n_ignorados':        n_ignorados,
        'n_items':            n_items,
        'n_recursos_creados': n_recursos_creados,
    }


# ── Proyectos / presupuestos ──────────────────────────────────────────────

def listar_proyectos_delphin(filepath: str) -> list[dict]:
    """Lista los proyectos+presupuestos disponibles en la DB."""
    src = sqlite3.connect(filepath)
    src.row_factory = sqlite3.Row
    try:
        rows = src.execute(
            "SELECT p.id_proyecto, p.nombre_proyecto, p.fecha_proyecto, "
            "       b.id_presupuesto, b.nombre_presupuesto, b.costo_directo, "
            "       b.total_presupuesto "
            "FROM proyecto p "
            "LEFT JOIN presupuesto b ON b.id_proyecto = p.id_proyecto "
            "ORDER BY p.id_proyecto, b.costo_directo DESC"
        ).fetchall()
        return [
            {
                'id_proyecto':       r['id_proyecto'],
                'nombre_proyecto':   _str(r['nombre_proyecto']) or '(sin nombre)',
                'fecha':             _str(r['fecha_proyecto']),
                'id_presupuesto':    r['id_presupuesto'],
                'nombre_presupuesto':_str(r['nombre_presupuesto']),
                'cd':                _num(r['costo_directo']),
                'total':             _num(r['total_presupuesto']),
            }
            for r in rows
        ]
    finally:
        src.close()
