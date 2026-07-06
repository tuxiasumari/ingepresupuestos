# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""
ifc_importer.py — Importador de archivos IFC (BIM) sin dependencias externas.

Parsea el formato STEP (ISO 10303-21) directamente con expresiones regulares,
extrae elementos constructivos y sus cantidades (área, volumen, longitud, unidades)
y genera partidas de presupuesto agrupadas por tipo de elemento.
"""

import re


# ─── PARSER STEP BÁSICO ──────────────────────────────────────────────────────

def _parse_step_lines(text):
    """
    Lee el bloque DATA del archivo IFC y devuelve un dict:
      {id_int: (tipo_str, attrs_str)}
    Maneja líneas que continúan en la siguiente (STEP permite eso).
    """
    # Unir líneas que no empiezan con # (continuaciones)
    lines = []
    buf = ''
    for raw in text.splitlines():
        s = raw.strip()
        if not s or s.startswith('/*'):
            continue
        if s.startswith('#'):
            if buf:
                lines.append(buf)
            buf = s
        else:
            buf += s
    if buf:
        lines.append(buf)

    entities = {}
    pat = re.compile(r'^#(\d+)\s*=\s*([A-Z0-9_]+)\s*\((.*)\)\s*;?\s*$', re.DOTALL)
    for line in lines:
        m = pat.match(line)
        if m:
            eid   = int(m.group(1))
            etype = m.group(2).upper()
            attrs = m.group(3)
            entities[eid] = (etype, attrs)
    return entities


def _split_attrs(s):
    """
    Divide los atributos de nivel superior de una entidad STEP.
    Respeta paréntesis anidados y cadenas entre comillas.
    Devuelve lista de strings.
    """
    parts = []
    depth = 0
    in_str = False
    cur = []
    i = 0
    while i < len(s):
        c = s[i]
        if c == "'" and not in_str:
            in_str = True; cur.append(c)
        elif c == "'" and in_str:
            in_str = False; cur.append(c)
        elif in_str:
            cur.append(c)
        elif c == '(':
            depth += 1; cur.append(c)
        elif c == ')':
            depth -= 1; cur.append(c)
        elif c == ',' and depth == 0:
            parts.append(''.join(cur).strip())
            cur = []
        else:
            cur.append(c)
        i += 1
    if cur:
        parts.append(''.join(cur).strip())
    return parts


def _str_val(s):
    """Extrae texto de una cadena STEP: 'texto' → texto"""
    s = s.strip()
    if s.startswith("'") and s.endswith("'"):
        return s[1:-1].replace("\\X2\\", "").replace("\\X0\\", "").strip()
    return s if s not in ('$', '*') else ''


def _float_val(s):
    s = s.strip()
    if s in ('$', '*', ''):
        return 0.0
    try:
        return float(s)
    except:
        return 0.0


def _ref_ids(attrs_str):
    """Extrae todos los #ID referenciados en un string de atributos."""
    return [int(x) for x in re.findall(r'#(\d+)', attrs_str)]


# ─── MAPPING IFC → PARTIDAS ──────────────────────────────────────────────────

# Tipo IFC → (grupo_presupuesto, descripcion, unidad_preferida)
IFC_MAP = {
    'IFCWALL':          ('02', 'MUROS Y TABIQUES',         'MURO',       'm2'),
    'IFCWALLSTANDARDCASE': ('02', 'MUROS Y TABIQUES',      'MURO',       'm2'),
    'IFCCURTAINWALL':   ('02', 'MUROS CORTINA',            'MURO CORTINA','m2'),
    'IFCSLAB':          ('03', 'LOSAS',                    'LOSA',       'm2'),
    'IFCBEAM':          ('04', 'VIGAS',                    'VIGA',       'm3'),
    'IFCBEAMSTANDARDCASE': ('04', 'VIGAS',                 'VIGA',       'm3'),
    'IFCCOLUMN':        ('05', 'COLUMNAS',                 'COLUMNA',    'm3'),
    'IFCCOLUMNSTANDARDCASE': ('05', 'COLUMNAS',            'COLUMNA',    'm3'),
    'IFCROOF':          ('06', 'TECHOS Y COBERTURAS',      'TECHO',      'm2'),
    'IFCSTAIR':         ('07', 'ESCALERAS',                'ESCALERA',   'm2'),
    'IFCSTAIRFLIGHT':   ('07', 'ESCALERAS',                'TRAMO ESCALERA','m2'),
    'IFCRAMP':          ('07', 'RAMPAS',                   'RAMPA',      'm2'),
    'IFCDOOR':          ('08', 'PUERTAS',                  'PUERTA',     'und'),
    'IFCWINDOW':        ('09', 'VENTANAS',                 'VENTANA',    'und'),
    'IFCFOOTING':       ('01', 'CIMENTACIONES',            'ZAPATA',     'm3'),
    'IFCPILE':          ('01', 'PILOTES',                  'PILOTE',     'm'),
    'IFCPLATE':         ('10', 'PLACAS',                   'PLACA',      'm2'),
    'IFCMEMBER':        ('10', 'ELEMENTOS ESTRUCTURALES',  'ELEMENTO',   'm'),
    'IFCFURNISHINGELEMENT': ('11', 'MOBILIARIO',           'MOBILIARIO', 'und'),
    'IFCSANITARYTERMINAL':  ('12', 'APARATOS SANITARIOS',  'APARATO',    'und'),
    'IFCFLOWSEGMENT':   ('13', 'TUBERÍAS',                 'TUBERIA',    'm'),
    'IFCPIPESEGMENT':   ('13', 'TUBERÍAS',                 'TUBERIA',    'm'),
    'IFCDUCTSEGMENT':   ('13', 'DUCTOS',                   'DUCTO',      'm'),
    'IFCLIGHTFIXTURE':  ('14', 'ILUMINACIÓN',              'LUMINARIA',  'und'),
    'IFCOUTLET':        ('14', 'SALIDAS ELÉCTRICAS',       'SALIDA',     'und'),
    'IFCFLOWFITTING':   ('13', 'ACCESORIOS',               'ACCESORIO',  'und'),
    'IFCSPACE':         None,  # Se usa solo para info del proyecto
    'IFCSITE':          None,
    'IFCBUILDING':      None,
    'IFCBUILDINGSTOREY':None,
}

# Nombres de quantity sets estándar en IFC
QSET_NAMES = {
    'Qto_WallBaseQuantities', 'Qto_SlabBaseQuantities',
    'Qto_BeamBaseQuantities', 'Qto_ColumnBaseQuantities',
    'Qto_RoofBaseQuantities', 'Qto_DoorBaseQuantities',
    'Qto_WindowBaseQuantities', 'Qto_StairBaseQuantities',
    'Qto_FootingBaseQuantities', 'Qto_PileBaseQuantities',
    'BaseQuantities', 'Quantities',
}

# Nombres de cantidades en orden de preferencia
AREA_NAMES  = {'NetSideArea','GrossArea','NetArea','NetFloorArea','GrossFloorArea',
               'FootPrintArea','OuterSurfaceArea'}
VOL_NAMES   = {'NetVolume','GrossVolume','NetVolumeSolid','GrossVolumeSolid'}
LEN_NAMES   = {'Length','Depth','Height','Width','Perimeter'}
COUNT_NAMES = {'Count','NumberOf','Quantity'}


# ─── EXTRACTOR PRINCIPAL ────────────────────────────────────────────────────

def parse_ifc(filepath):
    """
    Lee un archivo .ifc y devuelve:
      (info_proyecto, partidas_list)

    info_proyecto: {'nombre', 'cliente', 'ubicacion'}
    partidas_list: lista de dicts con keys:
        item, descripcion, unidad, metrado, precio_unitario, nivel, es_titulo
    """
    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        content = f.read()

    # Extraer solo bloque DATA
    m = re.search(r'DATA\s*;(.*?)ENDSEC', content, re.DOTALL | re.IGNORECASE)
    data_block = m.group(1) if m else content

    entities = _parse_step_lines(data_block)

    # ── 1. Extraer info del proyecto ──────────────────────────────────────────
    info = {'nombre': '', 'cliente': '', 'ubicacion': '', 'sub_presupuesto': '', 'costo_al': ''}
    for eid, (etype, attrs) in entities.items():
        if etype == 'IFCPROJECT':
            parts = _split_attrs(attrs)
            info['nombre'] = _str_val(parts[2]) if len(parts) > 2 else ''
        elif etype == 'IFCSITE':
            parts = _split_attrs(attrs)
            if len(parts) > 2:
                info['ubicacion'] = _str_val(parts[2])
        elif etype == 'IFCORGANIZATION':
            parts = _split_attrs(attrs)
            if len(parts) > 1 and not info['cliente']:
                info['cliente'] = _str_val(parts[1])

    if not info['nombre']:
        import os
        info['nombre'] = os.path.basename(filepath).replace('.ifc','').replace('_',' ')

    # ── 2. Construir mapa de cantidades ───────────────────────────────────────
    # Mapa: id_elemento → {tipo_qty: valor}
    elem_quantities = {}   # {elem_id: {'area': x, 'volume': x, 'length': x, 'count': x}}

    # Primero indexar todas las cantidades
    qty_map = {}  # {qty_id: (tipo, nombre, valor)}
    for eid, (etype, attrs) in entities.items():
        parts = _split_attrs(attrs)
        if etype == 'IFCQUANTITYAREA' and len(parts) >= 4:
            qty_map[eid] = ('area', _str_val(parts[0]), _float_val(parts[3]))
        elif etype == 'IFCQUANTITYVOLUME' and len(parts) >= 4:
            qty_map[eid] = ('volume', _str_val(parts[0]), _float_val(parts[3]))
        elif etype == 'IFCQUANTITYLENGTH' and len(parts) >= 4:
            qty_map[eid] = ('length', _str_val(parts[0]), _float_val(parts[3]))
        elif etype == 'IFCQUANTITYCOUNT' and len(parts) >= 4:
            qty_map[eid] = ('count', _str_val(parts[0]), _float_val(parts[3]))

    # Indexar IfcElementQuantity: qset_id → list of qty_ids
    qset_map = {}
    for eid, (etype, attrs) in entities.items():
        if etype == 'IFCELEMENTQUANTITY':
            parts = _split_attrs(attrs)
            # attrs: GlobalId, OwnerHistory, Name, Description, MethodOfMeasurement, Quantities
            qty_ids = []
            if len(parts) > 5:
                refs = re.findall(r'#(\d+)', parts[5])
                qty_ids = [int(r) for r in refs]
            qset_map[eid] = qty_ids

    # IfcRelDefinesByProperties enlaza elementos con qsets
    # attrs: GlobalId, OwnerHistory, Name, Desc, RelatedObjects(lista #ids), RelatingPropertyDefinition(#id)
    for eid, (etype, attrs) in entities.items():
        if etype == 'IFCRELDEFINESBYPROPERTIES':
            parts = _split_attrs(attrs)
            if len(parts) < 6:
                continue
            # RelatedObjects: (# id1, #id2, ...)
            elem_ids = [int(x) for x in re.findall(r'#(\d+)', parts[4])]
            prop_id_refs = re.findall(r'#(\d+)', parts[5])
            if not prop_id_refs:
                continue
            prop_id = int(prop_id_refs[0])
            if prop_id not in qset_map:
                continue
            for elem_id in elem_ids:
                if elem_id not in elem_quantities:
                    elem_quantities[elem_id] = {'area': 0, 'volume': 0, 'length': 0, 'count': 1}
                for qty_id in qset_map[prop_id]:
                    if qty_id in qty_map:
                        qtype, qname, qval = qty_map[qty_id]
                        if qval <= 0:
                            continue
                        eq = elem_quantities[elem_id]
                        # Priorizar nombres estándar
                        if qtype == 'area' and (qname in AREA_NAMES or eq['area'] == 0):
                            eq['area'] = max(eq['area'], qval)
                        elif qtype == 'volume' and (qname in VOL_NAMES or eq['volume'] == 0):
                            eq['volume'] = max(eq['volume'], qval)
                        elif qtype == 'length' and (qname in LEN_NAMES or eq['length'] == 0):
                            eq['length'] = max(eq['length'], qval)

    # ── 3. Agrupar elementos por tipo IFC ──────────────────────────────────────
    # grupos: {ifc_type: {'nombre': str, 'grupo': str, 'unidad': str, 'items': [{name, qty}]}}
    grupos = {}

    for eid, (etype, attrs) in entities.items():
        mapping = IFC_MAP.get(etype)
        if mapping is None:
            continue  # tipo no mapeado o ignorado

        grupo_cod, grupo_nom, elem_nom, unidad_pref = mapping
        parts = _split_attrs(attrs)
        # Nombre del elemento: attr 2 (Name) o attr 0 (GlobalId)
        nombre = ''
        if len(parts) > 2:
            nombre = _str_val(parts[2])
        if not nombre and len(parts) > 0:
            nombre = _str_val(parts[0])
        if not nombre:
            nombre = f'{elem_nom} #{eid}'

        # Cantidades
        eq = elem_quantities.get(eid, {'area': 0, 'volume': 0, 'length': 0, 'count': 1})

        # Decidir metrado según unidad preferida
        if unidad_pref == 'm2':
            metrado = eq['area']
            unidad  = 'm2'
        elif unidad_pref == 'm3':
            metrado = eq['volume']
            unidad  = 'm3'
        elif unidad_pref == 'm':
            metrado = eq['length']
            unidad  = 'm'
        else:  # und
            metrado = 1.0
            unidad  = 'und'

        if metrado == 0 and eq['area'] > 0:
            metrado, unidad = eq['area'], 'm2'
        elif metrado == 0 and eq['volume'] > 0:
            metrado, unidad = eq['volume'], 'm3'
        elif metrado == 0 and eq['length'] > 0:
            metrado, unidad = eq['length'], 'm'
        elif metrado == 0:
            metrado = 1.0

        key = (grupo_cod, etype)
        if key not in grupos:
            grupos[key] = {
                'codigo': grupo_cod, 'nombre': grupo_nom,
                'elem_nom': elem_nom, 'unidad': unidad,
                'total_metrado': 0.0, 'count': 0,
            }
        grupos[key]['total_metrado'] += metrado
        grupos[key]['count'] += 1

    # ── 4. Construir lista de partidas ────────────────────────────────────────
    if not grupos:
        return info, []

    # Ordenar por código de grupo
    sorted_groups = sorted(grupos.items(), key=lambda x: x[0][0])

    partidas = []
    titulos_usados = set()
    item_counter = {}   # grupo_cod → counter

    for (grupo_cod, _etype), g in sorted_groups:
        # Agregar título de sección si no existe
        if grupo_cod not in titulos_usados:
            titulos_usados.add(grupo_cod)
            item_counter[grupo_cod] = 0
            partidas.append({
                'item': grupo_cod,
                'descripcion': g['nombre'],
                'unidad': '', 'metrado': 0,
                'precio_unitario': 0,
                'nivel': 1, 'es_titulo': 1,
            })

        item_counter[grupo_cod] += 1
        sub_item = f"{grupo_cod}.{item_counter[grupo_cod]:02d}"
        desc = f"{g['elem_nom']} ({g['count']} elementos)"
        partidas.append({
            'item': sub_item,
            'descripcion': desc,
            'unidad': g['unidad'],
            'metrado': round(g['total_metrado'], 4),
            'precio_unitario': 0,
            'nivel': 2, 'es_titulo': 0,
        })

    return info, partidas
