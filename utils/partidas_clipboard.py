# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""Clipboard de partidas — copia/pega entre proyectos y sub-presupuestos.

Estado en memoria de sesión (módulo singleton). No se persiste a BD.
"""

from typing import Optional


# ── Estado global del clipboard ────────────────────────────────────────────────

_CLIPBOARD: Optional[dict] = None
# Clipboard de un sub-presupuesto COMPLETO (nombre + sus subárboles), para
# copiarlo de un proyecto a otro. Separado del de partidas.
_SUBPPTO_CLIP: Optional[dict] = None


def hay_clipboard() -> bool:
    return _CLIPBOARD is not None and bool(_CLIPBOARD.get('subarboles'))


def descripcion_clipboard() -> str:
    """Texto resumen del contenido del clipboard para mostrar al usuario."""
    if not hay_clipboard():
        return ''
    n_raices = len(_CLIPBOARD['subarboles'])
    n_partidas = sum(len(s) for s in _CLIPBOARD['subarboles'])
    return (f"{n_raices} raíz{'es' if n_raices != 1 else ''} "
            f"({n_partidas} ítem{'s' if n_partidas != 1 else ''})")


# ── Helpers internos ───────────────────────────────────────────────────────────

def _serializar_partida(conn, part_id: int) -> dict:
    """Serializa una partida con todas sus relaciones a un dict."""
    p = conn.execute("SELECT * FROM partidas WHERE id=?", (part_id,)).fetchone()
    if not p:
        return {}
    out = dict(p)

    # ACU items con descripción/tipo/unidad del recurso
    acu = conn.execute(
        """SELECT ai.cuadrilla, ai.cantidad,
                  COALESCE(ai.precio, r.precio, 0) AS precio,
                  r.codigo, r.descripcion, r.tipo, r.unidad, r.indice_inei
           FROM acu_items ai JOIN recursos r ON r.id = ai.recurso_id
           WHERE ai.partida_id = ?""",
        (part_id,)
    ).fetchall()
    out['acu_items'] = [dict(r) for r in acu]

    out['metrados_detalle'] = [dict(r) for r in conn.execute(
        "SELECT * FROM metrados_detalle WHERE partida_id=? ORDER BY orden",
        (part_id,)
    ).fetchall()]

    # Acero (tabla opcional)
    try:
        out['acero_detalle'] = [dict(r) for r in conn.execute(
            "SELECT * FROM acero_detalle WHERE partida_id=? ORDER BY id",
            (part_id,)
        ).fetchall()]
    except Exception:
        out['acero_detalle'] = []

    try:
        out['spec_imagenes'] = [dict(r) for r in conn.execute(
            "SELECT * FROM spec_imagenes WHERE partida_id=? ORDER BY orden",
            (part_id,)
        ).fetchall()]
    except Exception:
        out['spec_imagenes'] = []

    return out


def _subarbol_ids(conn, root_id: int) -> list[int]:
    """Devuelve [root_id, hijo1, hijo2, ...] en orden DFS de árbol por prefijo
    de item dentro del mismo proyecto+sub_presupuesto.
    """
    root = conn.execute(
        "SELECT proyecto_id, sub_presupuesto_id, item, es_titulo "
        "FROM partidas WHERE id=?", (root_id,)
    ).fetchone()
    if not root:
        return []
    if not root['es_titulo']:
        return [root_id]

    pid = root['proyecto_id']
    sub = root['sub_presupuesto_id']
    pref = root['item'] + '.'
    if sub is None:
        rows = conn.execute(
            "SELECT id FROM partidas "
            "WHERE proyecto_id=? AND sub_presupuesto_id IS NULL "
            "  AND (item=? OR item LIKE ?) "
            "ORDER BY item",
            (pid, root['item'], pref + '%')
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id FROM partidas "
            "WHERE proyecto_id=? AND sub_presupuesto_id=? "
            "  AND (item=? OR item LIKE ?) "
            "ORDER BY item",
            (pid, sub, root['item'], pref + '%')
        ).fetchall()
    return [r['id'] for r in rows]


# ── API pública ────────────────────────────────────────────────────────────────

def copiar(conn, root_ids: list[int], pid_origen: int) -> int:
    """Llena el clipboard con los subárboles enraizados en root_ids.

    Si un id es título trae todos sus descendientes; si es partida hoja trae
    solo esa fila. Devuelve número total de partidas serializadas.
    """
    global _CLIPBOARD
    subarboles: list[list[dict]] = []
    total = 0
    for rid in root_ids:
        ids = _subarbol_ids(conn, rid)
        if not ids:
            continue
        partidas_ser = [_serializar_partida(conn, pid) for pid in ids]
        subarboles.append(partidas_ser)
        total += len(partidas_ser)
    _CLIPBOARD = {
        'origen_pid': pid_origen,
        'subarboles': subarboles,
    }
    return total


# ── Sub-presupuesto completo ────────────────────────────────────────────────────

def hay_subppto_clipboard() -> bool:
    return _SUBPPTO_CLIP is not None and bool(_SUBPPTO_CLIP.get('subarboles'))


def nombre_subppto_clipboard() -> str:
    return _SUBPPTO_CLIP.get('nombre', '') if hay_subppto_clipboard() else ''


def copiar_subppto(conn, pid_origen: int, sub_ppto_id: int | None,
                   nombre: str) -> int:
    """Copia un sub-presupuesto entero (su nombre + todos sus ítems raíz con
    subárboles, metrados, ACU, acero y specs) al clipboard de sub-presupuestos.
    Devuelve el número de partidas serializadas."""
    global _SUBPPTO_CLIP
    if sub_ppto_id is None:
        rows = conn.execute(
            "SELECT id FROM partidas WHERE proyecto_id=? "
            "AND sub_presupuesto_id IS NULL AND nivel=1 ORDER BY item",
            (pid_origen,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id FROM partidas WHERE proyecto_id=? "
            "AND sub_presupuesto_id=? AND nivel=1 ORDER BY item",
            (pid_origen, sub_ppto_id)
        ).fetchall()
    subarboles: list[list[dict]] = []
    for r in rows:
        ids = _subarbol_ids(conn, r[0])
        if ids:
            subarboles.append([_serializar_partida(conn, p) for p in ids])
    _SUBPPTO_CLIP = {'nombre': nombre or 'Sub-presupuesto', 'subarboles': subarboles}
    return sum(len(s) for s in subarboles)


def pegar_subppto(conn, pid_destino: int, sub_ppto_id: int | None) -> list[int]:
    """Pega los subárboles del sub-presupuesto del clipboard como raíces en el
    sub-presupuesto destino indicado. Reutiliza `pegar` (renumeración +
    metrados/ACU/acero/specs). Devuelve los ids de las raíces nuevas."""
    global _CLIPBOARD
    if not hay_subppto_clipboard():
        return []
    saved = _CLIPBOARD
    _CLIPBOARD = {'origen_pid': None, 'subarboles': _SUBPPTO_CLIP['subarboles']}
    try:
        return pegar(conn, pid_destino, sub_ppto_id)
    finally:
        _CLIPBOARD = saved


def pegar_datos(conn, subarboles: list, pid_destino: int, sub_ppto_id: int | None,
                contexto_item: str | None = None,
                contexto_es_titulo: bool = False) -> list[int]:
    """Pega subárboles YA serializados (p. ej. cargados de una plantilla) en el
    proyecto destino, reutilizando `pegar()` SIN tocar el clipboard del usuario."""
    global _CLIPBOARD
    saved = _CLIPBOARD
    _CLIPBOARD = {'origen_pid': None, 'subarboles': subarboles}
    try:
        return pegar(conn, pid_destino, sub_ppto_id,
                     contexto_item=contexto_item,
                     contexto_es_titulo=contexto_es_titulo)
    finally:
        _CLIPBOARD = saved


def _siguiente_root(conn, pid_destino: int, sub_id: int | None) -> int:
    """Siguiente número de partida raíz disponible (CAST a int)."""
    if sub_id is None:
        row = conn.execute(
            "SELECT MAX(CAST(item AS INTEGER)) FROM partidas "
            "WHERE proyecto_id=? AND sub_presupuesto_id IS NULL "
            "  AND instr(item,'.')=0",
            (pid_destino,)
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT MAX(CAST(item AS INTEGER)) FROM partidas "
            "WHERE proyecto_id=? AND sub_presupuesto_id=? "
            "  AND instr(item,'.')=0",
            (pid_destino, sub_id)
        ).fetchone()
    return int((row[0] or 0)) + 1


def _resolve_recurso_dst(conn, codigo: str, descripcion: str, tipo: str,
                         unidad: str, precio: float) -> int:
    """Resuelve recurso_id en la BD destino reutilizando el catálogo (estilo
    PowerCost), igual que el importador (`core.importer._resolve_recurso`): un
    mismo insumo `(tipo, descripción, unidad)` se mantiene como UN solo
    recurso compartido aunque el código difiera. El precio NO se comparte
    entre proyectos vía catálogo: vive en `acu_items.precio`; si el recurso
    ya se usa en el proyecto destino, el pegado adopta ESE precio
    (`precio_recurso_en_proyecto`) para mantener un precio único por insumo.

    Orden: match por insumo en catálogo → código exacto + misma desc → crear
    con su código → código alternativo si el código ya lo usa otra desc.
    """
    desc_n = (descripcion or '').strip().upper()
    und_n = (unidad or '').strip()
    # 1. Reúso por insumo (tipo+descripción+unidad) en TODO el catálogo.
    if desc_n:
        match = conn.execute(
            "SELECT id FROM recursos WHERE tipo=? "
            "AND UPPER(TRIM(descripcion))=? AND TRIM(unidad)=? "
            "ORDER BY id LIMIT 1",
            (tipo, desc_n, und_n)
        ).fetchone()
        if match:
            return match['id']
    ex = conn.execute(
        "SELECT id, descripcion FROM recursos WHERE codigo=?", (codigo,)
    ).fetchone()
    # 2. Mismo código + misma descripción.
    if ex and (ex['descripcion'] or '').strip().upper() == desc_n:
        return ex['id']
    # 3. Código libre → crear con el código pedido.
    if not ex:
        indice = codigo[:2] if codigo and len(codigo) >= 2 else ''
        c = conn.execute(
            "INSERT INTO recursos (codigo, descripcion, tipo, unidad, "
            "precio, indice_inei) VALUES (?,?,?,?,?,?)",
            (codigo, descripcion, tipo, unidad, precio, indice)
        )
        return c.lastrowid
    # 4. Colisión: código ocupado por otra descripción → código alternativo.
    indice = codigo[:2] if codigo and len(codigo) >= 2 else '99'
    row = conn.execute(
        "SELECT MAX(CAST(SUBSTR(codigo,3) AS INTEGER)) FROM recursos "
        "WHERE SUBSTR(codigo,1,2)=?", (indice,)
    ).fetchone()
    seq = (row[0] or 0) + 1
    nuevo_codigo = f"{indice}{seq:05d}"
    c = conn.execute(
        "INSERT INTO recursos (codigo, descripcion, tipo, unidad, "
        "precio, indice_inei) VALUES (?,?,?,?,?,?)",
        (nuevo_codigo, descripcion, tipo, unidad, precio, indice)
    )
    return c.lastrowid


def pegar(conn, pid_destino: int, sub_ppto_id: int | None,
          contexto_item: str | None = None,
          contexto_es_titulo: bool = False) -> list[int]:
    """Vuelca el clipboard en el proyecto+sub-presupuesto destino.

    Si contexto_item apunta a un título, inserta dentro de él como hijos.
    Si apunta a una partida, inserta como hermanos al mismo nivel.
    Sin contexto, inserta como raíces al final.
    Devuelve los `partida_id` de las raíces nuevas.
    """
    if not hay_clipboard():
        return []

    nuevos_root_ids: list[int] = []

    existing = {r[0] for r in conn.execute(
        "SELECT item FROM partidas WHERE proyecto_id=?", (pid_destino,)
    ).fetchall()}

    if contexto_item and contexto_es_titulo:
        prefijo = contexto_item
        nivel_base = prefijo.count('.') + 2
        counter = [0]
        def _next_item():
            counter[0] += 1
            for n in range(counter[0], 10000):
                candidate = f"{prefijo}.{n:02d}"
                if candidate not in existing:
                    existing.add(candidate)
                    counter[0] = n
                    return candidate
            return f"{prefijo}.99"
    elif contexto_item and not contexto_es_titulo:
        partes = contexto_item.split('.')
        nivel_base = len(partes)
        counter = [0]
        def _next_item():
            counter[0] += 1
            for n in range(counter[0], 10000):
                partes[-1] = f"{n:02d}"
                candidate = '.'.join(partes)
                if candidate not in existing:
                    existing.add(candidate)
                    counter[0] = n
                    return candidate
            return '.'.join(partes[:-1] + ['99'])
    else:
        nivel_base = 1
        next_root = _siguiente_root(conn, pid_destino, sub_ppto_id)
        def _next_item():
            nonlocal next_root
            base = f"{next_root:02d}"
            next_root += 1
            existing.add(base)
            return base

    for subarbol in _CLIPBOARD['subarboles']:
        if not subarbol:
            continue
        base_origen = subarbol[0]['item']
        nivel_origen = int(subarbol[0]['nivel'] or 1)
        base_destino = _next_item()

        # Mapeo item_origen → item_destino y mapping id_origen → id_destino
        id_map: dict[int, int] = {}

        for p in subarbol:
            item_o = p['item'] or ''
            if item_o == base_origen:
                item_n = base_destino
            elif item_o.startswith(base_origen + '.'):
                item_n = base_destino + item_o[len(base_origen):]
            else:
                item_n = base_destino
            existing.add(item_n)

            nuevo_nivel = max(1, nivel_base + (int(p['nivel'] or 1) - nivel_origen))

            # Insertar partida
            cur = conn.execute(
                """INSERT INTO partidas
                   (proyecto_id, sub_presupuesto_id, item, descripcion, unidad,
                    metrado, precio_unitario, nivel, es_titulo, rendimiento,
                    especificaciones)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (pid_destino, sub_ppto_id, item_n,
                 p.get('descripcion') or '',
                 p.get('unidad') or '',
                 p.get('metrado') or 0,
                 p.get('precio_unitario') or 0,
                 nuevo_nivel,
                 1 if p.get('es_titulo') else 0,
                 p.get('rendimiento'),
                 p.get('especificaciones') or '')
            )
            new_pid = cur.lastrowid
            id_map[p['id']] = new_pid
            if item_n == base_destino:
                nuevos_root_ids.append(new_pid)

            # ACU items
            for ai in p.get('acu_items') or []:
                rec_id = _resolve_recurso_dst(
                    conn, ai.get('codigo') or '',
                    ai.get('descripcion') or '',
                    ai.get('tipo') or 'MAT',
                    ai.get('unidad') or 'und',
                    float(ai.get('precio') or 0),
                )
                # Un insumo = un precio por proyecto: si el recurso ya se usa
                # en el proyecto destino, el pegado adopta ese precio.
                from core.database import precio_recurso_en_proyecto
                precio_dst = precio_recurso_en_proyecto(conn, pid_destino, rec_id)
                if precio_dst is None:
                    precio_dst = ai.get('precio')
                conn.execute(
                    "INSERT INTO acu_items (partida_id, recurso_id, cuadrilla,"
                    " cantidad, precio) VALUES (?,?,?,?,?)",
                    (new_pid, rec_id, ai.get('cuadrilla'),
                     ai.get('cantidad'), precio_dst)
                )

            # Metrados detalle
            for m in p.get('metrados_detalle') or []:
                conn.execute(
                    "INSERT INTO metrados_detalle"
                    " (partida_id, orden, descripcion, n_estructuras,"
                    "  n_elementos, largo, ancho, alto, parcial, area)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (new_pid, m.get('orden') or 0, m.get('descripcion') or '',
                     m.get('n_estructuras'), m.get('n_elementos'),
                     m.get('largo'), m.get('ancho'), m.get('alto'),
                     m.get('parcial'), m.get('area'))
                )

            # Acero detalle
            for a in p.get('acero_detalle') or []:
                cols = [k for k in a.keys() if k not in ('id', 'partida_id')]
                placeholders = ','.join(['?'] * (len(cols) + 1))
                conn.execute(
                    f"INSERT INTO acero_detalle (partida_id, {','.join(cols)})"
                    f" VALUES ({placeholders})",
                    (new_pid, *[a.get(c) for c in cols])
                )

            # Specs imágenes
            for si in p.get('spec_imagenes') or []:
                cols = [k for k in si.keys() if k not in ('id', 'partida_id')]
                placeholders = ','.join(['?'] * (len(cols) + 1))
                try:
                    conn.execute(
                        f"INSERT INTO spec_imagenes (partida_id, "
                        f"{','.join(cols)}) VALUES ({placeholders})",
                        (new_pid, *[si.get(c) for c in cols])
                    )
                except Exception:
                    pass

    return nuevos_root_ids
