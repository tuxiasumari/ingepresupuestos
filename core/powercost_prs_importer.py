# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""Importador de proyectos desde un archivo .prs (PowerCost).

PowerCost almacena sus proyectos en un MS Access database (Jet 4.0).
- Linux: usamos ``mdbtools`` (paquete del sistema).
- Windows: usamos ``pyodbc`` con el driver ODBC de Microsoft Access
  (viene con Office o se instala gratis: "Microsoft Access Database
  Engine Redistributable").

Estructura PowerCost relevante:

  Pptos               (1 fila)            ← proyecto principal
  SubPptos            (N filas)           ← sub-presupuestos
  EstSubPpto          (árbol jerárquico)  ← partidas y títulos del proyecto
                                            usa IdPartidaPadre para anidar
  Titulos             (catálogo)          ← nombres de los títulos
  Analisis            (catálogo)          ← ACUs: NomAnalisis, Unidad, Rend
  EstAnalisis         (composiciones)     ← insumos del ACU con Tipo, Cuad,
                                            Cantidad
  Insumos             (catálogo)          ← recursos del proyecto, con
                                            NomInsumo, Unidad, IdIU (INEI),
                                            IdTipoIns
  PreciosIns          (precios)           ← precio por insumo en el proyecto
  EstMetradoNorm4     (metrados)          ← planilla de metrados detallados
                                            enlazada via IdMetrado4
"""
import csv
import io
import os
import shutil
import subprocess
import sys
from typing import Optional

_IS_WINDOWS = sys.platform == 'win32'


class AccessPasswordError(Exception):
    """El archivo .mdb/.prs está protegido con contraseña."""
    pass


# ── Helpers ─────────────────────────────────────────────────────────────────

# Jet 4.0 XOR key — la "contraseña" de base de datos Access 2000/XP/2003
# está en el header del archivo en offset 0x42, XOR'd con esta clave.
# mdbtools en Linux la ignora (lee datos crudos); ODBC la exige.
_JET4_PWD_KEY = bytes([
    0x86, 0xfb, 0xec, 0x37, 0x5d, 0x44, 0x9c, 0xfa,
    0xc6, 0x5e, 0x28, 0xe6, 0x13, 0xb6, 0x8a, 0x60,
    0x54, 0x94,
])


def _extract_jet_password(filepath: str) -> str:
    """Extrae la contraseña de un .mdb Jet 4.0 desde el header del archivo."""
    try:
        with open(filepath, 'rb') as f:
            header = f.read(0x80)
        if len(header) < 0x6A:
            return ''
        enc = header[0x42:0x42 + 40]
        key = _JET4_PWD_KEY
        dec = bytes(b ^ key[i % len(key)] for i, b in enumerate(enc))
        return dec.decode('utf-16-le').split('\x00')[0]
    except Exception:
        return ''


def _get_access_odbc_driver() -> str | None:
    """Busca un driver ODBC de Microsoft Access instalado en Windows."""
    try:
        import pyodbc
        drivers = pyodbc.drivers()
        for name in drivers:
            if 'Microsoft Access Driver' in name:
                return name
    except ImportError:
        pass
    return None


def _verificar_backend() -> None:
    """Lanza RuntimeError si no hay backend disponible para leer .mdb."""
    if _IS_WINDOWS:
        driver = _get_access_odbc_driver()
        if not driver:
            raise RuntimeError(
                "No se encontro el driver ODBC de Microsoft Access.\n\n"
                "Si tienes Office instalado, ya deberia estar disponible.\n"
                "Si no, instala gratis el 'Microsoft Access Database Engine':\n"
                "  https://www.microsoft.com/en-us/download/details.aspx?id=54920\n\n"
                "(es necesario para leer archivos .prs de PowerCost)"
            )
    else:
        if not _mdb_disponible():
            raise RuntimeError(
                "mdbtools no esta instalado. Instalalo con:\n"
                "  sudo apt install -y mdbtools\n"
                "(es necesario para leer archivos .prs de PowerCost)"
            )


def _en_flatpak_host(cmd: list[str]) -> list[str]:
    """Enruta un comando de mdbtools. Prefiere el binario LOCAL: el embebido en
    la edición Flathub (``/app/bin/mdb-export``) o el del sistema en instalación
    nativa. Solo si NO hay mdb-export local y corremos en un Flatpak con acceso
    al host (edición sideload, con ``--talk-name=org.freedesktop.Flatpak``) lo
    enruta con ``flatpak-spawn --host`` (allí mdbtools vive en el host).

    Distinguir por la presencia del binario local es clave: en Flathub
    ``flatpak-spawn --host`` está BLOQUEADO, así que enrutar al host rompería la
    importación .prs pese al mdbtools embebido.

    Se fija ``--directory`` al home del usuario porque flatpak-spawn hereda el
    cwd del proceso (bajo Flatpak = ``/app/…``, inexistente en el host)."""
    import os
    from core.config import es_flatpak
    if shutil.which('mdb-export'):
        return cmd                       # binario local (embebido o nativo)
    if es_flatpak():
        # flatpak-spawn exige --directory=DIR (con «=», no separado).
        host_dir = os.environ.get('HOME') or '/'
        return ['flatpak-spawn', '--host', f'--directory={host_dir}'] + cmd
    return cmd


def _mdb_disponible() -> bool:
    """True si mdb-export está disponible: primero el local (embebido en la
    edición Flathub o del sistema); si no, el del host (Flatpak sideload)."""
    if shutil.which('mdb-export'):
        return True
    from core.config import es_flatpak
    if es_flatpak():
        try:
            r = subprocess.run(
                _en_flatpak_host(['which', 'mdb-export']),
                capture_output=True, text=True, timeout=10,
            )
            return r.returncode == 0 and bool(r.stdout.strip())
        except Exception:
            return False
    return False


def _query_mdbtools(filepath: str, table: str) -> list[dict]:
    """Lee una tabla del .mdb via mdb-export (Linux)."""
    proc = subprocess.run(
        _en_flatpak_host(['mdb-export', '-D', '%Y-%m-%d %H:%M:%S', filepath, table]),
        capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        return []
    return list(csv.DictReader(io.StringIO(proc.stdout)))


def _patch_access_parser():
    """Corrige dos bugs en access_parser 0.0.6:
    1. Null bitmap: se calcula con column_count (columnas lógicas) pero
       field_count incluye columnas de sistema → desalinea el metadata.
    2. Variable offsets: usa índice secuencial (enumerate) pero debe usar
       variable_column_number para indexar la tabla de offsets."""
    import struct
    import access_parser.access_parser as _ap
    from access_parser.access_parser import AccessTable
    if getattr(AccessTable, '_patched', False):
        return

    _orig_row = AccessTable._parse_row

    def _parse_row_fixed(self, record):
        if self.version > 3 and len(record) >= 2:
            field_count = struct.unpack_from('h', record)[0]
            real_len = (field_count + 7) // 8
            hdr_len = (self.table_header.column_count + 7) // 8
            if real_len > hdr_len:
                self.table_header.column_count = field_count
        return _orig_row(self, record)

    def _parse_dynamic_fixed(self, original_record, metadata,
                             col_map, null_table):
        offsets = list(metadata.variable_length_field_offsets)
        var_len_count = metadata.var_len_count
        for column_index in col_map:
            column = col_map[column_index]
            col_name = column.col_name_str
            has_value = True
            if column.column_id < len(null_table):
                has_value = null_table[column.column_id]
            if not has_value:
                self.parsed_table[col_name].append(None)
                continue
            vn = column.variable_column_number
            if vn >= len(offsets):
                self.parsed_table[col_name].append(None)
                continue
            start = offsets[vn]
            end = offsets[vn + 1] if vn + 1 < len(offsets) else var_len_count
            if start == end:
                self.parsed_table[col_name].append('')
                continue
            data = original_record[start:end]
            if column.type == _ap.TYPE_MEMO:
                try:
                    val = self._parse_memo(data)
                except Exception:
                    val = data
            else:
                val = _ap.parse_type(column.type, data, len(data),
                                     version=self.version)
            self.parsed_table[col_name].append(val)

    AccessTable._parse_row = _parse_row_fixed
    AccessTable._parse_dynamic_length_data = _parse_dynamic_fixed
    AccessTable._patched = True


def _query_access_parser(filepath: str, table: str,
                         _db_cache: dict = {}) -> list[dict]:
    """Lee una tabla del .mdb via access_parser (fallback sin ODBC/password)."""
    _patch_access_parser()
    from access_parser import AccessParser
    cache_key = os.path.normcase(os.path.abspath(filepath))
    if cache_key not in _db_cache:
        _db_cache[cache_key] = AccessParser(filepath)
    db = _db_cache[cache_key]
    try:
        tbl = db.parse_table(table)
    except Exception:
        return []
    cols = list(tbl.keys())
    if not cols:
        return []
    n_rows = len(tbl[cols[0]])
    return [{col: (tbl[col][i] if tbl[col][i] is not None else '')
             for col in cols}
            for i in range(n_rows)]


def _query_odbc(filepath: str, table: str, password: str = '',
                _conn_cache: dict = {}) -> list[dict]:
    """Lee una tabla del .mdb via pyodbc (Windows).
    Si ODBC falla por contraseña, usa access_parser como fallback."""
    import pyodbc
    cache_key = (os.path.normcase(os.path.abspath(filepath)), password)
    if cache_key not in _conn_cache:
        driver = _get_access_odbc_driver()
        conn_str = (
            f"DRIVER={{{driver}}};"
            f"DBQ={filepath};"
            "ReadOnly=1;"
        )
        if password:
            conn_str += f"PWD={password};"
        try:
            _conn_cache[cache_key] = pyodbc.connect(conn_str)
        except pyodbc.Error as exc:
            if '-1905' in str(exc):
                return _query_access_parser(filepath, table)
            raise
    conn = _conn_cache[cache_key]
    try:
        cursor = conn.cursor()
        cursor.execute(f"SELECT * FROM [{table}]")
        cols = [desc[0] for desc in cursor.description]
        rows = []
        for row in cursor.fetchall():
            rows.append({col: (val if val is not None else '')
                         for col, val in zip(cols, row)})
        return rows
    except pyodbc.ProgrammingError:
        return []


def _query(filepath: str, table: str) -> list[dict]:
    """Lee toda una tabla del .prs como lista de dicts."""
    if _IS_WINDOWS:
        return _query_odbc(filepath, table)
    return _query_mdbtools(filepath, table)


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


def _int(v, default: int = 0) -> int:
    if v is None or v == '':
        return default
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def _codigo_recurso(id_iu: int, id_tipo: int, id_insumo: int) -> str:
    """Construye un código de 7 dígitos: 2 INEI + 5 correlativo.

    El INEI viene de IdIU (1..80). Si el insumo es overhead/herramientas
    (%MO/%MAT/%EQ) el INEI se mantiene en 37 (Herramientas Manuales).
    """
    inei = max(0, id_iu) % 100
    corr = id_insumo % 100000
    return f"{inei:02d}{corr:05d}"


# ── Parser principal ───────────────────────────────────────────────────────

def import_powercost_prs(filepath: str,
                          id_ppto: Optional[int] = None,
                          id_subppto: Optional[int] = None):
    """Lee un .prs de PowerCost y devuelve (info, partidas, acus, recursos,
    metrados) compatible con ``core.importer.guardar_importacion()``.

    Argumentos:
      filepath: ruta al .prs
      id_ppto: opcional, ID del proyecto a importar. Si no se pasa y la
        base tiene varios proyectos, se importa el primero. Para archivos
        con cientos de proyectos, usar `listar_proyectos_powercost()` y
        pedirle al usuario que elija.
      id_subppto: opcional, ID del sub-presupuesto. Si no se pasa, se usa
        el primero con IdSubPpto>0 (el total IdSubPpto=0 no se usa).
    """
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"No existe: {filepath}")
    _verificar_backend()

    # ── 1. Lectura de tablas ────────────────────────────────────────────
    q = lambda tbl: _query(filepath, tbl)

    pptos = q('Pptos')
    if not pptos:
        raise ValueError("El archivo no contiene presupuestos (tabla Pptos vacía).")
    if id_ppto is not None:
        proy = next((p for p in pptos if _int(p['IdPpto']) == id_ppto), None)
        if not proy:
            raise ValueError(
                f"No se encontró el proyecto IdPpto={id_ppto} en la base."
            )
    else:
        proy = pptos[0]
    id_ppto_real = _int(proy['IdPpto'])

    subpptos = q('SubPptos')
    subs_del_proy = [s for s in subpptos
                     if _int(s['IdPpto']) == id_ppto_real]
    if id_subppto is not None:
        sp = next((s for s in subs_del_proy
                   if _int(s['IdSubPpto']) == id_subppto), None)
    else:
        sp = next((s for s in subs_del_proy
                   if _int(s['IdSubPpto']) > 0), None)
    if not sp:
        raise ValueError(
            f"El proyecto IdPpto={id_ppto_real} no tiene sub-presupuesto activo."
        )
    sp_id = _int(sp['IdSubPpto'])
    id_ppto = id_ppto_real

    titulos    = q('Titulos')
    analisis   = q('Analisis')
    est_anal   = q('EstAnalisis')
    insumos    = q('Insumos')
    precios    = q('PreciosIns')
    est_sub    = q('EstSubPpto')
    metr_norm  = q('EstMetradoNorm4')

    # Mapeos
    tit_by_id = {_int(r['IdTitulo']): _str(r['NomTitulo']) for r in titulos}
    anl_by_id = {_int(r['IdAnalisis']): r for r in analisis}
    ins_by_id = {_int(r['IdInsumo']): r for r in insumos}
    # Precios: (IdPpto, IdInsumo) → Precio
    precio_de = {
        (_int(r['IdPpto']), _int(r['IdInsumo'])): _num(r['Precio'])
        for r in precios if _int(r.get('Activo', 0) or 0) == 1
    }

    # Composiciones del ACU agrupadas por IdAnalisis
    comps_por_acu: dict[int, list[dict]] = {}
    for r in est_anal:
        aid = _int(r['IdAnalisis'])
        comps_por_acu.setdefault(aid, []).append(r)

    # Metrados detallados: agrupados por IdMetrado4
    met_por_id: dict[int, list[dict]] = {}
    for r in metr_norm:
        mid = _int(r['IdMetrado4'])
        met_por_id.setdefault(mid, []).append(r)
    for mid in met_por_id:
        met_por_id[mid].sort(key=lambda x: _int(x['Orden']))

    # ── 2. Construir info del proyecto ──────────────────────────────────
    info = {
        'nombre':          _str(proy.get('NomPpto')) or 'Proyecto importado',
        'cliente':         '',
        'ubicacion':       _str(proy.get('Localidad')),
        'sub_presupuesto': _str(sp.get('NomSubPpto')) or '',
        # Pie de presupuesto: por ahora se siembra inactivo (igual que
        # Delphin). PowerCost tiene tablas PiePpto/ValoresPieP con la
        # estructura real del pie, pero parsearlas se aplazó a v2.
        # Ref: [[project-pie-import-v2]]
        'costo_al':        _str(proy.get('Fecha')),
    }

    # ── 3. Construir árbol de partidas ──────────────────────────────────
    # Filtrar las filas del sub-presupuesto seleccionado
    filas = [r for r in est_sub
             if _int(r['IdPpto']) == id_ppto and _int(r['IdSubPpto']) == sp_id]

    # Mapa: IdPartida → fila
    by_id = {_int(r['IdPartida']): r for r in filas}

    def nivel(idp: int) -> int:
        n, cur = 0, idp
        seen = set()
        while cur:
            cur_padre = _int(by_id.get(cur, {}).get('IdPartidaPadre', 0))
            if not cur_padre or cur_padre in seen:
                break
            seen.add(cur_padre)
            cur = cur_padre
            n += 1
        return n

    def hijos(parent_id: int) -> list[int]:
        r = [pid for pid, row in by_id.items()
             if _int(row['IdPartidaPadre']) == parent_id]
        r.sort(key=lambda x: (_int(by_id[x]['IdItem']),
                               _str(by_id[x]['TxItem'])))
        return r


    # Descripciones de partidas (preferir IdAnalisis.NomAnalisis o IdTitulo)
    def descripcion(row: dict) -> str:
        t = _int(row['Tipo'])
        if t == 1:   # título
            return tit_by_id.get(_int(row['IdTitulo']), '') or '(sin nombre)'
        # partida con análisis
        aid = _int(row['IdAnalisis'])
        an = anl_by_id.get(aid)
        if an:
            return _str(an['NomAnalisis']) or '(sin análisis)'
        return '(partida sin análisis)'

    def unidad_part(row: dict) -> str:
        if _int(row['Tipo']) == 1:
            return ''
        an = anl_by_id.get(_int(row['IdAnalisis']))
        return _str(an['Unidad']) if an else ''

    # DFS desde las raíces (IdPartidaPadre=0)
    partidas_data: list[dict] = []
    item_de: dict[int, str] = {}

    def emit(idp: int, prefijo: str, indice: int):
        # Numeración JERÁRQUICA por posición de hermano: 01, 01.01, 01.02,
        # 02, … NO usar TxItem/IdItem del .prs: en el .prs masivo TxItem
        # viene vacío y el fallback a IdItem (contador global) producía
        # numeración saltada (01, 04, 06, 13…). El orden de hermanos lo da
        # hijos() (por IdItem documental).
        row = by_id[idp]
        item = (prefijo + '.' if prefijo else '') + f"{indice:02d}"
        item_de[idp] = item

        es_titulo = (_int(row['Tipo']) == 1)
        partidas_data.append({
            'item':            item,
            'descripcion':     descripcion(row),
            'unidad':          unidad_part(row),
            'metrado':         _num(row['Metrado']),
            'precio_unitario': _num(row['Precio']),
            'nivel':           min(nivel(idp) + 1, 4),
            'es_titulo':       1 if es_titulo else 0,
        })
        for i, child in enumerate(hijos(idp), 1):
            emit(child, item, i)

    for i, r in enumerate(hijos(0), 1):
        emit(r, '', i)

    # ── 4. ACUs (rendimiento + items) ───────────────────────────────────
    # Tipos de costo en PowerCost: 1=MO, 2=MAT, 3=EQ + IdCategoria 2=SUB CONTRATO.
    # PowerCost no tiene tipo SC explícito, pero clasifica insumos en
    # Categoria SUB CONTRATO (cat_id=2) → los mapeamos a SC.
    def map_tipo(t: int) -> str:
        # IdTipoIns: 1=MO, 2=MAT, 3=EQ. NO usar IdCategoria: la categoría 2
        # incluye OPERARIO/OFICIAL/CEMENTO (verificado en bases reales) — no
        # significa subcontrato. Los SC reales entran como sub-análisis.
        return {1: 'MO', 2: 'MAT', 3: 'EQ'}.get(t, 'MAT')

    acus_data: dict = {}
    recursos_uniq: dict[str, dict] = {}

    def _es_global_anl(an: dict) -> bool:
        """Análisis global (glb/est/serv): cantidades directas, sin cuadrilla."""
        u = _str(an.get('Unidad', '')).strip().rstrip('.').lower()
        return u in ('glb', 'gbl', 'est', 'serv')

    def _filas_acu(aid: int, _stack: frozenset = frozenset()) -> list[dict]:
        """Filas del ACU de `aid` con cantidad efectiva y precio resueltos.

        Una fila de EstAnalisis con IdSubAnalisis != 0 es una SUB-PARTIDA
        (análisis anidado): se importa como recurso SC cuyo precio es el
        costo unitario del sub-análisis, calculado recursivamente (la tabla
        PreciosSubAnl suele venir vacía). `_stack` evita ciclos."""
        an = anl_by_id.get(aid)
        if not an:
            return []
        rend_acu = _num(an['Rend'], 1.0) or 1.0
        jornada  = _num(an.get('NumHrs') if isinstance(an, dict) else None, 8.0)
        if not jornada:
            jornada = 8.0
        part_global = _es_global_anl(an)

        out = []
        for c in comps_por_acu.get(aid, []):
            said = _int(c.get('IdSubAnalisis') or 0)
            if said and said != aid and said not in _stack:
                sub = anl_by_id.get(said)
                if not sub:
                    continue
                out.append({
                    'tipo':        'SC',
                    'codigo':      f"99{said % 100000:05d}",
                    'descripcion': _str(sub.get('NomAnalisis')) or f'Sub-análisis {said}',
                    'unidad':      _str(sub.get('Unidad', '')) or 'und',
                    'cuadrilla':   0.0,
                    'cantidad':    _num(c['Cantidad']),
                    'precio':      _cu_analisis(said, _stack | {aid}),
                })
                continue

            id_ins = _int(c['IdInsumo'])
            ins = ins_by_id.get(id_ins)
            if not ins:
                continue
            # El tipo real (MO/MAT/EQ/SC) viene del INSUMO, no de la composición.
            # EstAnalisis.Tipo se refiere a algo distinto (sub-tipo interno).
            id_tipo_ins = _int(ins['IdTipoIns'])
            tipo = map_tipo(id_tipo_ins)
            id_iu = _int(ins['IdIU'])
            codigo = _codigo_recurso(id_iu, id_tipo_ins, id_ins)
            r_unidad = _str(ins.get('Unidad', '')) or 'und'
            r_desc = _str(ins.get('NomInsumo', '')) or f'Recurso {id_ins}'
            precio = precio_de.get((id_ppto, id_ins), 0.0)

            cuad = _num(c['Cuadrilla'])
            cant = _num(c['Cantidad'])
            # Para MO y EQ por hora (hh/hm), la cantidad SIEMPRE se deriva
            # de la cuadrilla mediante la fórmula canónica peruana:
            #     cant = cuadrilla / rendimiento * jornada
            # PowerCost almacena valores inconsistentes (a veces 0, a veces
            # truncados con jornada parcial). Sobreescribir asegura que el
            # ACU sea coherente con el editor de la app.
            unidad_lower = (r_unidad or '').strip().rstrip('.').lower()
            # MO/EQ por día (día/jor): el rendimiento ya es por día → la
            # fórmula NO lleva jornada (cant = cuadrilla / rend). La MO en
            # día NO debe caer en la fórmula horaria (inflaría ×jornada).
            es_por_dia = (
                tipo in ('MO', 'EQ')
                and unidad_lower in ('día', 'dia', 'días', 'dias', 'jor', 'jornada')
            )
            es_por_hora = not es_por_dia and (
                tipo == 'MO'
                or unidad_lower in ('hh', 'hm', 'h-h', 'h-m', 'jph', 'jh')
                or 'hora' in unidad_lower
            )
            if cuad and rend_acu > 0 and not part_global:
                if es_por_hora:
                    cant = (cuad / rend_acu) * jornada
                elif es_por_dia and tipo == 'MO':
                    # Solo MO-día se normaliza; EQ-día conserva la cantidad
                    # original de PowerCost (fidelidad de totales validada)…
                    cant = cuad / rend_acu
                elif es_por_dia and tipo == 'EQ' and not cant:
                    # …EXCEPTO equipo-día con cantidad 0: PowerCost la deriva
                    # de la cuadrilla (caso «ESTACION TOTAL» cuad=1, cant=0).
                    # Sin esto el equipo entra al ACU con parcial 0.
                    cant = cuad / rend_acu

            out.append({
                'tipo':        tipo,
                'codigo':      codigo,
                'descripcion': r_desc,
                'unidad':      r_unidad,
                'cuadrilla':   cuad,
                'cantidad':    cant,
                'precio':      precio,
            })
        return out

    _cu_memo: dict[int, float] = {}

    def _cu_analisis(aid: int, _stack: frozenset = frozenset()) -> float:
        """Costo unitario de un análisis (para sub-partidas anidadas), con las
        mismas reglas de suma que la app (parciales a 2 dec, %MO/%MAT sobre
        el subtotal del tipo)."""
        if aid in _cu_memo:
            return _cu_memo[aid]
        from core.database import _pu_desde_items
        cu = _pu_desde_items(_filas_acu(aid, _stack))
        _cu_memo[aid] = cu
        return cu

    for idp, row in by_id.items():
        if _int(row['Tipo']) != 0:
            continue  # solo partidas, no títulos
        aid = _int(row['IdAnalisis'])
        if not aid:
            continue
        an = anl_by_id.get(aid)
        if not an:
            continue
        item = item_de.get(idp)
        if not item:
            continue

        items_acu = _filas_acu(aid)
        for it in items_acu:
            if it['codigo'] not in recursos_uniq:
                recursos_uniq[it['codigo']] = {
                    'codigo':      it['codigo'],
                    'descripcion': it['descripcion'],
                    'tipo':        it['tipo'],
                    'unidad':      it['unidad'],
                    'precio':      it['precio'],
                }

        if items_acu:
            acus_data[item] = {
                'rendimiento': _num(an['Rend'], 1.0),
                'items':       items_acu,
            }

    recursos_data = list(recursos_uniq.values())

    # ── 5. Metrados detallados ───────────────────────────────────────────
    metrados_data: dict[str, list[dict]] = {}
    for idp, row in by_id.items():
        mid = _int(row.get('IdMetrado4', 0))
        if mid <= 0:
            continue
        item = item_de.get(idp)
        if not item:
            continue
        filas_m = met_por_id.get(mid, [])
        if not filas_m:
            continue
        det = []
        for f in filas_m:
            det.append({
                'descripcion':   _str(f.get('Descripcion')),
                'n_estructuras': _num(f.get('NEstr')),
                'n_elementos':   _num(f.get('NElem')),
                'area':          _num(f.get('Area')) or None,
                'largo':         _num(f.get('Largo')),
                'ancho':         _num(f.get('Ancho')),
                'alto':          _num(f.get('Alto')),
                'parcial':       _num(f.get('Parcial')),
            })
        if det:
            metrados_data[item] = det

    # ── 6. Conciliar PU con la suma del ACU ──────────────────────────────
    # PowerCost suma los parciales SIN redondear cada uno; la app los
    # redondea a 2 (criterio S10). Eso deja diferencias de ±1-2 céntimos.
    # Se adopta la suma de la app SOLO si el impacto monetario en el CD
    # (dif × metrado) es despreciable (≤ 1 sol): presupuesto autoconsistente
    # sin alterar el total. Con metrados grandes se conserva el PU del
    # archivo (fidelidad del total ante todo); la diferencia de céntimos
    # restante queda dentro de la tolerancia del detector PU≠ACU (0.02).
    from core.database import _pu_desde_items
    _EPS = 0.0005   # absorbe el ruido float de una dif de exactamente 0.02
    for p in partidas_data:
        if p.get('es_titulo'):
            continue
        acu = acus_data.get(p['item'])
        if not acu:
            continue
        cu_app = _pu_desde_items(acu['items'])
        dif = abs(cu_app - (p.get('precio_unitario') or 0))
        impacto = dif * abs(p.get('metrado') or 0)
        if dif <= 0.02 + _EPS and impacto <= 1.0:
            p['precio_unitario'] = cu_app

    return info, partidas_data, acus_data, recursos_data, (metrados_data or None)


# ── API pública para listar proyectos ──────────────────────────────────────

def listar_proyectos_powercost(filepath: str) -> list[dict]:
    """Lista los proyectos disponibles en un .prs (para que el usuario
    elija cuando hay varios). Retorna lista ordenada por nombre con:
    id_ppto, nombre, fecha, cd, ct, localidad.
    """
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"No existe: {filepath}")
    _verificar_backend()
    pptos = _query(filepath, 'Pptos')
    out = []
    for p in pptos:
        nombre = _str(p.get('NomPpto'))
        if not nombre:
            continue
        out.append({
            'id_ppto':   _int(p['IdPpto']),
            'nombre':    nombre,
            'fecha':     _str(p.get('Fecha')),
            'cd':        _num(p.get('CD')),
            'ct':        _num(p.get('CT')),
            'localidad': _str(p.get('Localidad')),
        })
    out.sort(key=lambda x: x['nombre'])
    return out
