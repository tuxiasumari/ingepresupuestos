# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""
biblioteca_embeddings.py — RAG Fase 2: recuperación SEMÁNTICA de partidas de la
biblioteca (la semilla) usando embeddings estáticos de model2vec.

A diferencia del fuzzy (Fase 1, `ai_specs.recuperar_partidas_biblioteca`), capta
sinónimos que no comparten palabras: «revestimiento» ≈ «enlucido», «vereda» ≈
«acera», «tubería de agua» ≈ «línea de conducción».

Sin PyTorch ni ONNX: model2vec produce embeddings estáticos (lookup + promedio)
y la búsqueda es un coseno con NumPy sobre ~7.500 vectores (instantáneo, faiss
innecesario). El índice se cachea en USER_DATA_DIR y se reconstruye solo cuando
cambia la biblioteca (firma = nº filas + max id).
"""
from __future__ import annotations
import json
import numpy as np

from core.database import get_db
from core.config import USER_DATA_DIR, BASE_DIR

# Modelo bundleado (al empaquetar) → fallback a descarga HF (en dev).
_MODEL_DIR   = BASE_DIR / "resources" / "models" / "potion-multilingual-128M"
_HF_MODELOS  = ["minishlab/potion-multilingual-128M",
                "minishlab/M2V_multilingual_output"]

_INDEX_NPY   = USER_DATA_DIR / "biblioteca_emb.npy"
_INDEX_META  = USER_DATA_DIR / "biblioteca_emb.json"

# Versión del esquema de embeddings: súbela si cambia la normalización o el
# modelo → invalida los índices cacheados en disco automáticamente.
# v3 = modelo potion-multilingual-128M int8 (147 MB).
# v4 = pool unificado (biblioteca_cu + ACUs de proyectos propios del usuario).
# v5 = pool deduplicado por (desc normalizada, unidad) — acota tamaño a escala.
_EMB_VERSION = "v5"

_MODEL = None          # StaticModel cacheado en proceso
_INDEX = None          # (ids, descs, unidades, matriz_normalizada) cacheado


def _norm(s: str) -> str:
    """Misma normalización que el fuzzy (minúsculas, sin tildes/signos) para que
    índice y consulta vivan en el MISMO espacio — model2vec es sensible al case."""
    from core.ai_specs import _normalizar_desc
    return _normalizar_desc(s)


def disponible() -> bool:
    """¿Está model2vec instalado? (para degradar a fuzzy si no)."""
    try:
        import model2vec  # noqa: F401
        return True
    except Exception:
        return False


def _modelo():
    global _MODEL
    if _MODEL is None:
        from model2vec import StaticModel
        if _MODEL_DIR.exists():
            _MODEL = StaticModel.from_pretrained(str(_MODEL_DIR))
        else:
            ultimo = None
            for nombre in _HF_MODELOS:
                try:
                    _MODEL = StaticModel.from_pretrained(nombre)
                    break
                except Exception as e:
                    ultimo = e
            if _MODEL is None:
                raise ultimo or RuntimeError("No se pudo cargar model2vec")
    return _MODEL


def _firma(conn) -> str:
    from core.database import firma_pool_rag
    return f"{_EMB_VERSION}:{firma_pool_rag(conn)}"


def _normaliza(mat: np.ndarray) -> np.ndarray:
    return mat / (np.linalg.norm(mat, axis=1, keepdims=True) + 1e-9)


def _indice():
    """Carga (o construye y cachea) el índice de embeddings de la biblioteca.
    Retorna (ids, descs, unidades, matriz_normalizada float32)."""
    global _INDEX
    conn = get_db()
    firma = _firma(conn)
    if _INDEX is not None and _INDEX[4] == firma:
        conn.close()
        return _INDEX[:4]
    # ¿caché en disco válido?
    if _INDEX_NPY.exists() and _INDEX_META.exists():
        try:
            meta = json.loads(_INDEX_META.read_text(encoding="utf-8"))
            if meta.get("firma") == firma:
                mat = np.load(_INDEX_NPY)
                conn.close()
                _INDEX = (meta["ids"], meta["descs"], meta["unidades"], mat, firma)
                return _INDEX[:4]
        except Exception:
            pass
    # construir — pool unificado (biblioteca + proyectos propios del usuario)
    from core.database import pool_partidas_rag
    pool = pool_partidas_rag(conn)
    conn.close()
    ids      = list(range(len(pool)))           # solo placeholder; no se usa al recuperar
    descs    = [p["descripcion"] for p in pool]
    unidades = [p["unidad"] for p in pool]
    # embeber la descripción NORMALIZADA (ya viene en `_norm`, mismo espacio que
    # la consulta); `descs` originales se guardan solo para mostrar.
    textos = [p["_norm"] for p in pool]
    mat = _normaliza(np.asarray(_modelo().encode(textos), dtype=np.float32))
    try:
        USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
        np.save(_INDEX_NPY, mat)
        _INDEX_META.write_text(json.dumps(
            {"firma": firma, "ids": ids, "descs": descs, "unidades": unidades},
            ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    _INDEX = (ids, descs, unidades, mat, firma)
    return _INDEX[:4]


def recuperar_partidas_semantico(terminos: list, k: int = 50,
                                 por_termino: int = 8,
                                 umbral: float = 0.40) -> list:
    """Stage 2 (semántico) del RAG: por cada término toma las top `por_termino`
    partidas de la biblioteca por similitud coseno, deduplica y corta en `k`.
    Misma firma de salida que el fuzzy: [{descripcion, unidad, grupo, _score}].
    Retorna [] ante cualquier fallo (degradación a fuzzy)."""
    if not terminos:
        return []
    try:
        ids, descs, unidades, mat = _indice()
        if mat.size == 0:
            return []
        Q = _normaliza(np.asarray(_modelo().encode([_norm(t) for t in terminos]),
                                  dtype=np.float32))
        sims = mat @ Q.T                       # (N, T)
        mejor = {}                             # idx_fila -> score
        for ti in range(sims.shape[1]):
            col = sims[:, ti]
            top = np.argpartition(-col, min(por_termino, len(col) - 1))[:por_termino]
            for i in top:
                s = float(col[i])
                if s >= umbral and s > mejor.get(i, -1.0):
                    mejor[i] = s
        ordenado = sorted(mejor.items(), key=lambda kv: kv[1], reverse=True)
        out, seen = [], set()
        for i, s in ordenado:
            clave = descs[i].strip().lower()
            if clave in seen:
                continue
            seen.add(clave)
            out.append({"descripcion": descs[i], "unidad": unidades[i],
                        "grupo": "", "_score": round(s, 4)})
            if len(out) >= k:
                break
        return out
    except Exception:
        return []
