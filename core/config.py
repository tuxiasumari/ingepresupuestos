# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""Configuración global de la aplicación (equivale a constantes de app.py Flask).

Separación de paths (cross-platform):

* ``BASE_DIR``       — raíz del código / assets read-only (íconos, QSS, seed
  DB, traducciones). Apunta al directorio de instalación. Bajo PyInstaller
  apunta al directorio temporal de extracción → **NO escribir aquí**.

* ``USER_DATA_DIR``  — datos editables del usuario (BD activa, backups,
  uploads, archivo de sesión). Persiste entre upgrades de la app. Se crea
  automáticamente al primer arranque y, si existe una BD legacy en
  ``BASE_DIR/presupuestos.db`` (instalación desde fuentes), se copia
  one-shot al nuevo destino.

Convención cross-platform:

* Linux:   ``~/.local/share/ingepresupuestos/`` (respeta ``$XDG_DATA_HOME``)
* Windows: ``%APPDATA%/ingepresupuestos/``
* macOS:   ``~/Library/Application Support/ingepresupuestos/``
"""
import os
import shutil
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent


def es_flatpak() -> bool:
    """True si la app corre dentro de un sandbox Flatpak.

    Bajo Flatpak los programas externos (LibreOffice, mdbtools) viven en el
    HOST y solo se alcanzan vía ``flatpak-spawn --host``; además ``/tmp`` es
    privado del sandbox. Varios módulos ajustan su comportamiento con esto.
    """
    return bool(os.environ.get("FLATPAK_ID")) or Path("/.flatpak-info").exists()


def _resolver_user_data_dir() -> Path:
    """Devuelve la carpeta de datos del usuario para esta plataforma."""
    app = "ingepresupuestos"
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(
            Path.home() / "AppData" / "Roaming"
        )
        return Path(base) / app
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / app
    # Linux y otros UNIX — respetar XDG_DATA_HOME si existe
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / app
    return Path.home() / ".local" / "share" / app


USER_DATA_DIR = _resolver_user_data_dir()
USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

# Datos editables — viven en la carpeta del usuario
DB_PATH      = USER_DATA_DIR / "presupuestos.db"
UPLOADS_DIR  = USER_DATA_DIR / "uploads"
BACKUPS_DIR  = USER_DATA_DIR / "backups"
SESSION_FILE = USER_DATA_DIR / ".session"

# Assets read-only — viven en el directorio de instalación
SPEC_IMG_DIR = BASE_DIR / "resources" / "spec_img"


def get_product_icon_path() -> Path | None:
    """Devuelve la ruta al ícono del producto (PNG/ICO), buscando por fallback.

    El path se resuelve dinámicamente para que funcione bajo PyInstaller
    (donde BASE_DIR apunta al bundle) y desde fuente (donde apunta al repo).

    Usar este helper en cualquier setWindowIcon / QPixmap del ícono del
    producto para evitar paths hardcoded que dejan de funcionar al reorganizar.
    """
    candidates = (
        "resources/icons/elementary/24/ingepresupuestos.png",
        "resources/icons/elementary/24/ingepresupuestos.ico",
        # Fallbacks legacy — paths antiguos que aparecen en código viejo
        "resources/icons/icon-256.png",
        "resources/icons/icon-64.png",
    )
    for rel in candidates:
        p = BASE_DIR / rel
        if p.exists():
            return p
    return None


def _sembrar_db_si_falta() -> None:
    """Primer arranque: si NO existe ``DB_PATH`` y SÍ existe la base semilla
    ``BASE_DIR/presupuestos_seed.db`` (parte del producto, bundleada con
    PyInstaller), la copia al destino del usuario. Idempotente: si la BD
    del usuario ya existe, no hace nada (no sobrescribe sus datos).

    Esto da al usuario una BD inicial con catálogos pre-cargados (INEI,
    biblioteca CAPECO, etc.) en lugar de empezar con tablas vacías.
    """
    if DB_PATH.exists():
        return
    seed = BASE_DIR / "presupuestos_seed.db"
    if not seed.exists():
        return
    try:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(seed, DB_PATH)
    except OSError:
        pass


def _migrar_paths_legacy() -> None:
    """Migración one-shot de instalaciones anteriores.

    Si encuentra ``BASE_DIR/presupuestos.db`` (instalación desde fuentes,
    pre-empaquetado) y no existe la nueva BD en ``USER_DATA_DIR``, copia
    los datos al nuevo destino para que el usuario no pierda nada al
    actualizar. NO borra el archivo legacy — el usuario puede limpiarlo
    cuando confirme que todo funciona.

    Idempotente: si la BD nueva ya existe, no hace nada."""
    legacy_db = BASE_DIR / "presupuestos.db"
    if legacy_db.exists() and not DB_PATH.exists():
        try:
            shutil.copy2(legacy_db, DB_PATH)
        except OSError:
            pass
    legacy_session = BASE_DIR / ".session"
    if legacy_session.exists() and not SESSION_FILE.exists():
        try:
            shutil.copy2(legacy_session, SESSION_FILE)
        except OSError:
            pass
    # Carpetas opcionales — solo si tenían contenido en la instalación vieja
    for nombre, destino in (("uploads", UPLOADS_DIR), ("backups", BACKUPS_DIR)):
        legacy = BASE_DIR / nombre
        if legacy.is_dir() and not destino.exists():
            try:
                shutil.copytree(legacy, destino)
            except OSError:
                pass


_migrar_paths_legacy()
# Sembrar la BD del usuario con datos iniciales en el primer arranque.
# DEBE ir DESPUÉS de _migrar_paths_legacy (que migra desde instalaciones
# viejas) — solo siembra si AÚN no hay DB del usuario.
_sembrar_db_si_falta()

MONEDAS = {
    'Soles':             {'simbolo': 'S/',    'sep_miles': ',', 'sep_dec': '.'},
    'Dólares':           {'simbolo': 'US$',   'sep_miles': ',', 'sep_dec': '.'},
    'Euros':             {'simbolo': '€',     'sep_miles': '.', 'sep_dec': ','},
    'Pesos Chilenos':    {'simbolo': 'CLP$',  'sep_miles': '.', 'sep_dec': ','},
    'Pesos Colombianos': {'simbolo': 'COP$',  'sep_miles': '.', 'sep_dec': ','},
    'Bolivianos':        {'simbolo': 'Bs.',   'sep_miles': ',', 'sep_dec': '.'},
    'Reales':            {'simbolo': 'R$',    'sep_miles': '.', 'sep_dec': ','},
    'Pesos Argentinos':  {'simbolo': 'ARS$',  'sep_miles': '.', 'sep_dec': ','},
    'Guaraníes':         {'simbolo': '₲',     'sep_miles': '.', 'sep_dec': ','},
    'Pesos Uruguayos':   {'simbolo': 'UYU$',  'sep_miles': '.', 'sep_dec': ','},
    'Pesos Mexicanos':   {'simbolo': 'MXN$',  'sep_miles': ',', 'sep_dec': '.'},
}

ESTADOS_PROYECTO = ['elaboracion', 'revision', 'aprobado', 'ejecutado']

# Nombre largo para mostrar en UI
ESTADOS_PROYECTO_NOMBRE = {
    'elaboracion': 'En elaboración',
    'revision':    'En revisión',
    'aprobado':    'Aprobado',
    'ejecutado':   'En ejecución',
}

# Niveles bloqueados por estado (espejo del original Flask).
# Cada `nivel` se desactiva si el `estado` está en su tupla.
#
#   presupuesto → tree, ACU, metrados, sub-presupuestos
#   pie         → pie_rubros, GG, IGV
#   specs       → especificaciones técnicas
#   cronograma  → barras Gantt, valorizado
ESTADOS_BLOQUEADOS = {
    'presupuesto': ('revision', 'aprobado', 'ejecutado'),
    'pie':         ('revision', 'aprobado', 'ejecutado'),
    'specs':       ('aprobado', 'ejecutado'),
    'cronograma':  ('ejecutado',),
}


def puede_editar(estado: str | None, nivel: str) -> bool:
    """True si en este `estado` se puede modificar contenido de `nivel`
    (presupuesto / pie / specs / cronograma)."""
    estado = estado or 'elaboracion'
    return estado not in ESTADOS_BLOQUEADOS.get(nivel, ())


def proyecto_editable(estado: str | None) -> bool:
    """Alias legacy — True solo si el proyecto está en elaboración (todos
    los niveles editables). Para chequeos granulares usar `puede_editar`."""
    return (estado or 'elaboracion') == 'elaboracion'

ROLES_USUARIO = ['admin', 'usuario', 'invitado']

TIPOS_RECURSO = ['MO', 'MAT', 'EQ', 'SC']

# Nombres largos legibles para UI
TIPOS_RECURSO_LARGOS = {
    'MO':  'Mano de Obra',
    'MAT': 'Materiales',
    'EQ':  'Equipos',
    'SC':  'Sub-contratos / Servicios',
}

# Índices INEI por tipo de recurso por defecto.
# 47 = Mano de Obra (incluido leyes sociales)
# 48 = Maquinaria y Equipo Nacional
# 39 = Índice General de Precios al Consumidor (genérico para materiales)
# 32 = Flete Terrestre (genérico razonable para sub-contratos/servicios)
INEI_DEFAULT = {'MO': '47', 'EQ': '48', 'MAT': '39', 'SC': '32'}

def moneda_cfg(moneda: str) -> dict:
    return MONEDAS.get(moneda, MONEDAS['Soles'])
