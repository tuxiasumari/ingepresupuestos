# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""
pdf_importer.py — Importa presupuestos PowerCost desde PDF.
Soporta: Presupuesto, ACU (Análisis de Costos Unitarios), Insumos.
Usa pdfplumber para extracción de texto por palabras con coordenadas.
"""
import re
from collections import defaultdict

try:
    import pdfplumber
except ImportError:
    pdfplumber = None


# ─── UTILS ────────────────────────────────────────────────────────────────────

def _get_lines(page):
    """Extrae líneas de texto como listas de tokens, agrupando por posición Y."""
    words = page.extract_words(x_tolerance=3, y_tolerance=3)
    buckets = defaultdict(list)
    for w in words:
        y = round(w['top'], 0)
        buckets[y].append(w['text'])
    return [buckets[y] for y in sorted(buckets.keys())]


def _is_item(tok):
    """True si el token parece un código de ítem (01, 01.01, 01.01.01.01, etc.)."""
    return bool(re.match(r'^\d{2}(\.\d{2,})+$', tok) or re.match(r'^\d{2}$', tok))


def _is_number(tok):
    """True si el token es un número o fragmento de número."""
    clean = tok.replace(',', '').replace(' ', '')
    return bool(re.match(r'^-?\d+\.?\d*$', clean))


def _safe_float(tok):
    """Convierte un token numérico a float."""
    try:
        return float(str(tok).replace(',', '').replace(' ', ''))
    except Exception:
        return 0.0


def _reconstruct_numbers(tokens):
    """
    Reconstruye números que el PDF ha partido en tokens separados.
    Casos comunes de PowerCost:
      ['2', '19.84']    → [219.84]     (219.84 partido como '2' + '19.84')
      ['1', ',413.41']  → [1413.41]    (1,413.41 partido como '1' + ',413.41')
      ['5', ',478.33']  → [5478.33]
    """
    numbers = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        combined = tok

        # Seguir combinando mientras el siguiente token parezca continuación
        while i + 1 < len(tokens):
            nxt = tokens[i + 1]
            # Caso: siguiente empieza con coma  → "1" + ",413.41" → "1413.41"
            if nxt.startswith(','):
                combined += nxt
                i += 1
            # Caso: combinar "2" + "19.84" → "219.84" (el actual no tiene punto)
            elif '.' not in combined and re.match(r'^\d+\.\d+$', nxt):
                candidate = combined.replace(',', '') + nxt
                if re.match(r'^\d+\.\d+$', candidate):
                    combined = candidate
                    i += 1
                else:
                    break
            else:
                break

        try:
            numbers.append(float(combined.replace(',', '')))
        except Exception:
            pass
        i += 1

    return numbers


def _parse_resource_line(tokens):
    """
    Parsea una línea de recurso del ACU.
    Formato: IU codigo DESCRIPCION... UNIDAD [cuadrilla] cantidad precio [parcial]
    Retorna dict o None.
    """
    if len(tokens) < 5:
        return None

    # Los dos primeros tokens: IU (1-2 dígitos) y código (alfanumérico)
    if not re.match(r'^\d{1,3}$', tokens[0]):
        return None
    iu = tokens[0]
    codigo = tokens[1]

    rest = tokens[2:]

    # Separar texto de números desde el final
    # Buscar desde el final los tokens numéricos (o fragmentos)
    num_start = len(rest)
    for j in range(len(rest) - 1, -1, -1):
        tok = rest[j]
        is_num = _is_number(tok) or tok.startswith(',')
        is_possible_unit = (not _is_number(tok) and len(tok) <= 6
                            and re.search(r'[a-zA-Z%]', tok))
        if is_num:
            num_start = j
        elif is_possible_unit:
            # Puede ser la unidad — parar aquí
            break
        else:
            break

    if num_start >= len(rest):
        return None

    num_tokens = rest[num_start:]
    desc_und   = rest[:num_start]

    # Reconstruir números
    numbers = _reconstruct_numbers(num_tokens)
    if len(numbers) < 2:
        return None

    # Encontrar la unidad: último token no-número de desc_und
    unidad = ''
    desc_parts = []
    for tok in reversed(desc_und):
        if not unidad and re.search(r'[a-zA-Z%]', tok) and not _is_number(tok):
            unidad = tok
        else:
            desc_parts.insert(0, tok)

    if not unidad:
        # Fallback: último token de desc_und
        if desc_und:
            unidad = desc_und[-1]
            desc_parts = desc_und[:-1]

    descripcion = ' '.join(desc_parts)

    # Determinar campos según cantidad de números y si hay cuadrilla
    # Para %MO: tiene precio_base como 3er número (no es un precio unitario real)
    es_pct = unidad.startswith('%')

    if es_pct:
        # %MO, %mat, %eq: cantidad=pct, resto irrelevante, precio=0
        cantidad  = numbers[0] if numbers else 0
        cuadrilla = 0
        precio    = 0
    elif len(numbers) >= 4:
        # MO o EQ con cuadrilla: cuadrilla, cantidad, precio, parcial
        cuadrilla = numbers[0]
        cantidad  = numbers[1]
        precio    = numbers[2]
    elif len(numbers) == 3:
        # MAT o EQ sin cuadrilla: cantidad, precio, parcial
        cuadrilla = 0
        cantidad  = numbers[0]
        precio    = numbers[1]
    else:
        cuadrilla = 0
        cantidad  = numbers[0]
        precio    = numbers[1] if len(numbers) > 1 else 0

    return {
        'codigo'     : codigo,
        'descripcion': descripcion or codigo,
        'unidad'     : unidad,
        'cuadrilla'  : round(cuadrilla, 4),
        'cantidad'   : round(cantidad,  4),
        'precio'     : round(precio,    4),
    }


# ─── PRESUPUESTO PDF ──────────────────────────────────────────────────────────

def import_powercost_presupuesto_pdf(filepath):
    """
    Importa presupuesto desde PDF PowerCost.
    Retorna (info, partidas) igual que import_powercost_presupuesto() de importer.py.
    """
    if pdfplumber is None:
        return {}, []

    info = {
        'nombre': '', 'cliente': '', 'ubicacion': '',
        'sub_presupuesto': '', 'costo_al': ''
    }
    partidas = []

    # Descripción pendiente para ítems que tienen la descripción en línea separada
    _pending_desc = ''

    _MESES = {'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
               'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre'}

    with pdfplumber.open(filepath) as pdf:
        # ── PRIMERA PASADA: extraer metadatos de la primera página ──
        if pdf.pages:
            lines0 = _get_lines(pdf.pages[0])
            nombre_parts = []
            in_nombre    = False
            for line in lines0:
                if not line:
                    continue
                tok0 = line[0]
                if tok0 == 'Proyecto':
                    in_nombre = True
                    parts = line[1:]
                    if parts and re.match(r'^\d+$', parts[0]):
                        parts = parts[1:]
                    nombre_parts.extend(parts)
                    continue
                if in_nombre:
                    if tok0 in ('Sub', 'Cliente', 'Ubicación', 'Ubicacion'):
                        info['nombre'] = ' '.join(nombre_parts).strip()
                        in_nombre = False
                    else:
                        nombre_parts.extend(line)
                        continue
                if tok0 in ('Cliente',) and not info['cliente']:
                    info['cliente'] = ' '.join(line[1:]).strip()
                    continue
                if tok0 in ('Ubicación', 'Ubicacion') and not info['ubicacion']:
                    parts = line[1:]
                    costo_idx = next((k for k, t in enumerate(parts) if t == 'Costo'), None)
                    ub = ' '.join(parts[:costo_idx] if costo_idx else parts).strip(' -')
                    info['ubicacion'] = ub
                    continue
                if tok0 in _MESES and not info['costo_al']:
                    info['costo_al'] = ' '.join(line).replace('-', '').strip()
                    continue
            if in_nombre and nombre_parts:
                info['nombre'] = ' '.join(nombre_parts).strip()

        # ── SEGUNDA PASADA: extraer partidas ──
        for page in pdf.pages:
            lines = _get_lines(page)

            for line in lines:
                if not line:
                    continue
                tok0 = line[0]

                # ── Paginación, saltar ──
                if tok0 == 'P.' or re.match(r'^P\.\d+/\d+$', tok0):
                    continue

                # ── Línea de ítem ──
                if _is_item(tok0):
                    rest = line[1:]

                    # Extraer números del final
                    num_end = []
                    text_end = list(rest)
                    while text_end:
                        candidate = text_end[-1]
                        if _is_number(candidate) or candidate.startswith(','):
                            num_end.insert(0, candidate)
                            text_end.pop()
                        else:
                            break

                    numbers = _reconstruct_numbers(num_end)

                    # Descripción: del texto + pending
                    desc_tokens = text_end
                    desc = ' '.join(desc_tokens).strip()
                    if not desc and _pending_desc:
                        desc = _pending_desc
                    _pending_desc = ''

                    nivel = len(tok0.split('.'))

                    # ── Título / Subtítulo (solo 1 número = subtotal) ──
                    if len(numbers) <= 1:
                        partidas.append({
                            'item'           : tok0,
                            'descripcion'    : desc,
                            'unidad'         : '',
                            'metrado'        : 0.0,
                            'precio_unitario': 0.0,
                            'nivel'          : nivel,
                            'es_titulo'      : 1,
                        })
                        continue

                    # ── Partida hoja (3 números: metrado, precio, parcial) ──
                    if len(numbers) >= 2:
                        # Encontrar unidad: último token texto antes de los números
                        unidad = ''
                        desc_parts = list(text_end)
                        for j in range(len(desc_parts) - 1, -1, -1):
                            t = desc_parts[j]
                            if not _is_number(t) and re.search(r'[a-zA-Z]', t):
                                unidad = t
                                desc_parts = desc_parts[:j]
                                break
                        if not unidad and desc_parts:
                            unidad = desc_parts.pop()

                        desc = ' '.join(desc_parts).strip() or desc

                        metrado = numbers[0] if len(numbers) >= 2 else 0.0
                        precio  = numbers[1] if len(numbers) >= 2 else 0.0

                        partidas.append({
                            'item'           : tok0,
                            'descripcion'    : desc,
                            'unidad'         : unidad,
                            'metrado'        : round(metrado, 4),
                            'precio_unitario': round(precio,  4),
                            'nivel'          : nivel,
                            'es_titulo'      : 0,
                        })
                    continue

                # ── Línea sin ítem: posible descripción para el siguiente ítem ──
                # Filtrar líneas de encabezado repetitivo
                skip_words = {'Item', 'Descripción', 'Descripcion', 'Unidad', 'Metrado',
                              'Precio', 'Parcial', 'Subtotal', 'Total', 'Costo', 'Unitario',
                              'MUNICIPALIDAD', 'Presupuesto', 'Proyecto', 'Sub', 'Cliente',
                              'Ubicación', 'Ubicacion', 'P.', 'TOTAL', 'COSTO', 'DIRECTO'}
                if tok0 in skip_words:
                    continue
                # Si empieza con letra y no tiene números → descripción pendiente
                joined = ' '.join(line)
                if re.search(r'[a-zA-Z]', tok0) and not re.match(r'^\d', tok0):
                    if not any(_is_number(t) for t in line):
                        _pending_desc = joined

    return info, partidas


# ─── ACU PDF ──────────────────────────────────────────────────────────────────

def import_powercost_acu_pdf(filepath):
    """
    Importa ACUs desde PDF PowerCost.
    Retorna dict {item_code: {'rendimiento': float, 'items': [...]}}
    igual que import_powercost_acus() de importer.py.
    """
    if pdfplumber is None:
        return {}

    acus = {}
    current_item   = None
    current_desc   = ''
    current_tipo   = None   # 'MO' | 'MAT' | 'EQ'
    pending_item   = None   # item que viene en línea previa al "Partida"

    _TIPO_MAP = {
        'mano': 'MO', 'obra': 'MO',
        'materiales': 'MAT', 'material': 'MAT',
        'equipo': 'EQ', 'equipos': 'EQ',
    }

    _SKIP_START = {'Código', 'Codigo', 'Descripción', 'Descripcion',
                   'Insumo', 'Unidad', 'Cuadrilla', 'Cantidad',
                   'Precio', 'Parcial', 'Costo', 'Unitario', 'Sub',
                   'MUNICIPALIDAD', 'Análisis', 'Analisis', 'Proyecto',
                   'Cliente', 'Ubicación', 'Ubicacion', 'P.'}

    with pdfplumber.open(filepath) as pdf:
        for page in pdf.pages:
            lines = _get_lines(page)

            for line in lines:
                if not line:
                    continue
                tok0 = line[0]

                # Paginación
                if re.match(r'^P\.\d+/\d+$', tok0):
                    continue

                # ── Cabecera de partida ──
                # Caso A: ['Partida', item, 'Rend:', ...]
                # Caso B: ['Partida', desc..., 'Rend:', rend, 'unit/DIA']  (item en línea anterior)
                if tok0 in ('Partida', 'Sub') and len(line) > 1:
                    # Detectar si el siguiente token es un ítem
                    idx = 1
                    if line[idx] == 'Partida':
                        idx = 2  # "Sub Partida"

                    # Buscar 'Rend:' para extraer rendimiento y unidad
                    rend_idx = None
                    for k, t in enumerate(line):
                        if t == 'Rend:':
                            rend_idx = k
                            break

                    if rend_idx is None:
                        continue

                    # ¿Tiene item propio?
                    if _is_item(line[idx]):
                        current_item = line[idx]
                        desc_tokens  = line[idx + 1:rend_idx]
                    else:
                        # El item estaba en la línea previa
                        current_item = pending_item
                        desc_tokens  = line[idx:rend_idx]

                    current_desc = ' '.join(desc_tokens).strip()

                    # Rendimiento y unidad
                    rend  = 1.0
                    rnd_unit = ''
                    if rend_idx + 1 < len(line):
                        rend_str = line[rend_idx + 1]
                        try:
                            rend = float(rend_str.replace(',', ''))
                        except Exception:
                            pass
                    if rend_idx + 2 < len(line):
                        rnd_unit = line[rend_idx + 2]

                    if current_item:
                        acus[current_item] = {
                            'rendimiento': rend,
                            'items'      : [],
                        }

                    current_tipo = None
                    pending_item = None
                    continue

                # ── Descripción multi-línea del nombre de partida (entre Partida y columnas) ──
                if current_item and tok0 not in _SKIP_START:
                    # Si es solo texto y la siguiente línea tiene "Código Descripción"
                    # podría ser descripción adicional — ignorar (ya la tenemos)
                    pass

                # ── Item solitario (en línea propia, antes de "Partida ...") ──
                if _is_item(tok0) and len(line) == 1:
                    pending_item = tok0
                    continue

                # ── Sección (Mano de Obra / Materiales / Equipo) ──
                joined_lower = ' '.join(line).lower()
                tipo_det = None
                for kw, tipo in _TIPO_MAP.items():
                    if kw in joined_lower:
                        tipo_det = tipo
                        break
                if tipo_det and len(line) <= 4:
                    current_tipo = tipo_det
                    continue

                # ── Saltar encabezados y subtotales ──
                if tok0 in _SKIP_START:
                    continue
                if len(line) == 1 and _is_number(tok0):
                    # Subtotal de sección, saltar
                    continue

                # ── Línea de recurso ──
                if current_item and current_tipo and re.match(r'^\d{1,3}$', tok0):
                    rec = _parse_resource_line(line)
                    if rec:
                        rec['tipo'] = current_tipo
                        acus[current_item]['items'].append(rec)
                    continue

    return acus


# ─── INSUMOS PDF ──────────────────────────────────────────────────────────────

def import_powercost_insumos_pdf(filepath):
    """
    Importa lista de insumos desde PDF PowerCost.
    Retorna lista de {codigo, descripcion, tipo, unidad, precio}.
    """
    if pdfplumber is None:
        return []

    recursos = []
    current_tipo = None

    _TIPO_MAP = {
        'MANO': 'MO', 'OBRA': 'MO',
        'MATERIALES': 'MAT', 'MATERIAL': 'MAT',
        'EQUIPO': 'EQ', 'EQUIPOS': 'EQ',
        'SERVICIOS': 'MAT',   # tratar servicios como material
    }

    _SKIP_START = {'IU', 'Código', 'Codigo', 'Descripción', 'Descripcion',
                   'Unidad', 'Cantidad', 'Precio', 'Parcial', 'Sub', 'Total',
                   'TOTAL', 'MANO', 'MATERIALES', 'EQUIPO', 'EQUIPOS', 'SERVICIOS',
                   'MUNICIPALIDAD', 'Listado', 'Proyecto', 'Cliente',
                   'Ubicación', 'Ubicacion', 'P.'}

    with pdfplumber.open(filepath) as pdf:
        for page in pdf.pages:
            lines = _get_lines(page)
            for line in lines:
                if not line:
                    continue
                tok0 = line[0]

                if re.match(r'^P\.\d+/\d+$', tok0):
                    continue

                # Detectar sección
                upper0 = tok0.upper()
                if upper0 in _TIPO_MAP and len(line) <= 3:
                    current_tipo = _TIPO_MAP[upper0]
                    continue
                joined_upper = ' '.join(line).upper()
                if 'MANO DE OBRA' in joined_upper and len(line) <= 5:
                    current_tipo = 'MO'
                    continue
                if tok0 in _SKIP_START:
                    continue
                if len(line) == 1 and _is_number(tok0):
                    continue

                # Línea de recurso: IU codigo desc... unidad cantidad precio [parcial]
                if current_tipo and re.match(r'^\d{1,3}$', tok0) and len(line) >= 5:
                    rec = _parse_resource_line(line)
                    if rec:
                        recursos.append({
                            'codigo'     : rec['codigo'],
                            'descripcion': rec['descripcion'],
                            'tipo'       : current_tipo,
                            'unidad'     : rec['unidad'],
                            'precio'     : rec['precio'],
                        })

    return recursos


# ─── DETECCIÓN AUTOMÁTICA ─────────────────────────────────────────────────────

def detectar_tipo_pdf(filepath):
    """
    Detecta si es PDF de Presupuesto, ACU o Insumos leyendo la primera página.
    Retorna 'presupuesto' | 'acu' | 'insumos' | 'desconocido'.
    """
    if pdfplumber is None:
        return 'desconocido'
    try:
        with pdfplumber.open(filepath) as pdf:
            if not pdf.pages:
                return 'desconocido'
            txt = pdf.pages[0].extract_text() or ''
            txt_lower = txt.lower()
            if 'análisis de costos unitarios' in txt_lower or 'analisis de costos unitarios' in txt_lower:
                return 'acu'
            if 'listado de insumos' in txt_lower or 'relación de insumos' in txt_lower:
                return 'insumos'
            if 'presupuesto' in txt_lower:
                return 'presupuesto'
    except Exception:
        pass
    return 'desconocido'
