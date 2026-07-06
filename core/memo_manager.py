# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""Manager de la memoria de Tuxia (bloc de notas persistente).

La memoria es un texto libre por proyecto + un texto global cross-proyecto.
A diferencia del modelo previo de "memos" (items granulares con id), la
memoria es UN bloc editable — el usuario lo abre, escribe/borra libremente
y guarda. Más natural y permite formato libre.

Esquemas relacionados:
  - `tuxia_memoria(id, proyecto_id, texto, fecha_modif)` — bloc actual.
    NULL en proyecto_id = bloc global. Una sola fila por proyecto/global
    (garantizado en código vía UPSERT manual).
  - `tuxia_memos(...)` — modelo legacy de items individuales. Se migra
    on-demand al primer get_memoria() del proyecto si está vacío y hay
    memos legacy.

Compatibilidad: `detectar_captura` se mantiene para capturar "recuérdame
que X" desde el chat — pero ahora hace APPEND al bloc del proyecto en vez
de crear un item.
"""
from __future__ import annotations

from core.database import get_db


# ── Bloc de memoria (modelo nuevo) ───────────────────────────────────────────

def get_memoria(proyecto_id: int | None) -> str:
    """Devuelve el texto del bloc de notas. `proyecto_id=None` → bloc global.

    Si el bloc no existe, intenta migrar desde `tuxia_memos` (legacy)
    concatenando los memos en líneas con bullet. Devuelve '' si no hay nada.
    """
    conn = get_db()
    try:
        if proyecto_id is None:
            row = conn.execute(
                "SELECT texto FROM tuxia_memoria WHERE proyecto_id IS NULL"
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT texto FROM tuxia_memoria WHERE proyecto_id=?",
                (proyecto_id,)
            ).fetchone()
    finally:
        conn.close()
    if row is not None:
        return row['texto'] or ''
    # Migración on-demand desde tuxia_memos (legacy)
    return _migrar_legacy_si_aplica(proyecto_id)


def _migrar_legacy_si_aplica(proyecto_id: int | None) -> str:
    """Si hay memos legacy para este alcance y el bloc nuevo está vacío,
    los concatena en un solo texto con bullets y lo guarda."""
    conn = get_db()
    try:
        if proyecto_id is None:
            memos = conn.execute(
                "SELECT texto FROM tuxia_memos WHERE proyecto_id IS NULL"
                " ORDER BY id"
            ).fetchall()
        else:
            memos = conn.execute(
                "SELECT texto FROM tuxia_memos WHERE proyecto_id=? ORDER BY id",
                (proyecto_id,)
            ).fetchall()
    finally:
        conn.close()
    if not memos:
        # Crear fila vacía para evitar re-migrar (idempotencia)
        set_memoria(proyecto_id, '')
        return ''
    texto = "\n".join(f"• {(m['texto'] or '').strip()}" for m in memos
                       if (m['texto'] or '').strip())
    set_memoria(proyecto_id, texto)
    return texto


def set_memoria(proyecto_id: int | None, texto: str) -> None:
    """UPSERT — garantiza 1 sola fila por proyecto_id (incluyendo NULL global)."""
    texto = texto or ''
    conn = get_db()
    try:
        if proyecto_id is None:
            existing = conn.execute(
                "SELECT id FROM tuxia_memoria WHERE proyecto_id IS NULL"
            ).fetchone()
        else:
            existing = conn.execute(
                "SELECT id FROM tuxia_memoria WHERE proyecto_id=?",
                (proyecto_id,)
            ).fetchone()
        if existing:
            conn.execute(
                "UPDATE tuxia_memoria SET texto=?,"
                " fecha_modif=CURRENT_TIMESTAMP WHERE id=?",
                (texto, existing['id'])
            )
        else:
            conn.execute(
                "INSERT INTO tuxia_memoria(proyecto_id, texto) VALUES(?, ?)",
                (proyecto_id, texto)
            )
        conn.commit()
    finally:
        conn.close()


def append_memoria(proyecto_id: int | None, linea: str) -> None:
    """Agrega una línea al final del bloc con bullet."""
    linea = (linea or '').strip()
    if not linea:
        return
    actual = get_memoria(proyecto_id)
    sep = '\n' if actual else ''
    set_memoria(proyecto_id, actual + sep + f"• {linea}")


def search_memoria(query: str, proyecto_id: int | None,
                   limit: int = 5) -> list[tuple[float, str, str]]:
    """Busca líneas relevantes en el bloc del proyecto + global.

    Devuelve top-N como `(score, alcance, linea)`. Score ≥ 65 = match
    razonable. Alcance ∈ {'proyecto', 'global'}.
    """
    query = (query or '').strip()
    if not query:
        return []
    try:
        from rapidfuzz import fuzz
    except ImportError:
        return []
    blocs: list[tuple[str, str]] = []
    if proyecto_id is not None:
        t = get_memoria(proyecto_id)
        if t:
            blocs.append(('proyecto', t))
    g = get_memoria(None)
    if g:
        blocs.append(('global', g))
    if not blocs:
        return []
    q_norm = _norm(query)
    hits: list[tuple[float, str, str]] = []
    for alcance, texto in blocs:
        for raw in texto.split('\n'):
            ln = raw.strip().lstrip('•').lstrip('-').strip()
            if not ln or len(ln) < 3:
                continue
            score = fuzz.WRatio(q_norm, _norm(ln))
            if alcance == 'proyecto':
                score += 5   # leve bonus para memoria del proyecto activo
            if score >= 65:
                hits.append((score, alcance, ln))
    hits.sort(key=lambda x: -x[0])
    return hits[:limit]


# ── Helpers comunes ──────────────────────────────────────────────────────────

def _norm(s: str) -> str:
    s = (s or '').lower().strip()
    for o, r in (('á','a'),('é','e'),('í','i'),('ó','o'),('ú','u'),('ñ','n')):
        s = s.replace(o, r)
    return s


# ── Detección de captura en lenguaje natural ─────────────────────────────────

_CAPTURA_PREFIXES = (
    'recuerdame que ', 'recuérdame que ',
    'recuerda que ', 'recuérda que ',
    'anota que ', 'anótame que ', 'anotame que ',
    'apunta que ', 'apúntame que ', 'apuntame que ',
    'memo: ', 'recordatorio: ', 'guarda esto: ', 'guarda que ',
    'no olvides que ',
)


def detectar_captura(mensaje: str) -> str | None:
    """Si el mensaje es 'recuérdame que X', devuelve X. Si no, None."""
    if not mensaje:
        return None
    m = mensaje.strip().lower()
    while m and m[0] in ',;:':
        m = m[1:].strip()
    if m.startswith('tuxia '):
        m = m[6:].strip()
    elif m.startswith('tuxia, '):
        m = m[7:].strip()
    for pref in _CAPTURA_PREFIXES:
        if m.startswith(pref):
            idx = _find_payload_start(mensaje, pref)
            if idx is not None:
                payload = mensaje[idx:].strip()
                if payload:
                    return payload
            return m[len(pref):].strip() or None
    return None


def _find_payload_start(mensaje: str, prefijo: str) -> int | None:
    m_norm = _norm(mensaje)
    idx = m_norm.find(prefijo)
    if idx < 0:
        return None
    return idx + len(prefijo)


# ── Legacy: mantengo stubs por si algo más los usa ───────────────────────────
# (los comandos del chat ya migran a get/set_memoria; estos stubs evitan que
# código antiguo rompa si todavía importa add_memo/list_memos/etc.)

def add_memo(texto: str, proyecto_id: int | None = None) -> int:
    """Legacy: ahora hace append al bloc de memoria."""
    append_memoria(proyecto_id, texto)
    return 0


def list_memos(proyecto_id: int | None = None,
               include_global: bool = True) -> list:
    return []


def delete_memo(memo_id: int) -> bool:
    return False


def search_memos(query: str, proyecto_id: int | None = None,
                 limit: int = 5):
    """Legacy adapter: ahora busca en el bloc de memoria."""
    hits = search_memoria(query, proyecto_id, limit)
    return [(s, {'id': 0, 'proyecto_id': None if alc == 'global' else proyecto_id,
                 'texto': ln, 'fecha': ''})
            for s, alc, ln in hits]
