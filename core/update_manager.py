# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""Sistema simple y profesional de actualizaciones.

Funcionalidad:

* Chequea un ``version.json`` remoto vía HTTP GET (``requests`` si está
  instalado, ``urllib`` como fallback de stdlib).
* Compara versiones semver (``1.2.3`` vs ``2.0.0``).
* Persiste estado local en ``USER_DATA_DIR``:
    - ``license.json``      → tipo de licencia + clave (trial/perpetual/...).
    - ``update_state.json`` → contador de descargas, versión saltada, último check.
* Limita descargas para usuarios trial; perpetuos/suscripción tienen ilimitado.

Para hostear ``version.json`` ver el docstring abajo. Bumpea ``CURRENT_VERSION``
en cada release del binario.
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from core.config import USER_DATA_DIR


# ─────────────────────────────────────────────────────────────────────────────
# Configuración (editar antes de empaquetar para producción)
# ─────────────────────────────────────────────────────────────────────────────

#: Versión actual del binario. Bumpear en cada release.
CURRENT_VERSION = "2.8.4"

#: URL del ``version.json`` remoto.
#: Servido desde Cloudflare R2 (bucket público vía custom domain).
VERSION_URL = "https://downloads.ingepresupuestos.com/version.json"

#: Cuántas descargas permite el plan trial antes de exigir licencia.
TRIAL_MAX_DOWNLOADS = 6

#: Archivos locales de estado.
LICENSE_FILE = USER_DATA_DIR / "license.json"
UPDATE_STATE_FILE = USER_DATA_DIR / "update_state.json"


# ─────────────────────────────────────────────────────────────────────────────
# Modelos
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class VersionInfo:
    """Info de versión publicada por el servidor."""
    version: str
    release_date: str
    changelog: str
    download_url: str
    minimum_version: Optional[str] = None   # opcional: forzar update si local < esto

    @classmethod
    def from_dict(cls, d: dict) -> "VersionInfo":
        # Si el JSON trae el dict `downloads` (esquema nuevo), elegimos el
        # binario que corresponde a la plataforma del usuario. Si no, caemos
        # al campo plano `download_url` (esquema legacy).
        downloads = d.get('downloads') or {}
        if downloads:
            if sys.platform.startswith('win'):
                key = 'windows_installer'
            elif sys.platform.startswith('linux'):
                key = 'linux_appimage'
            elif sys.platform == 'darwin':
                key = 'macos'
            else:
                key = ''
            url = downloads.get(key) or d.get('download_url', '')
        else:
            url = d.get('download_url', '')
        return cls(
            version=str(d.get('version', '')),
            release_date=str(d.get('release_date', '')),
            changelog=str(d.get('changelog', '')),
            download_url=str(url),
            minimum_version=d.get('minimum_version'),
        )


@dataclass
class LicenseInfo:
    """Información de licencia del usuario.

    Tipos soportados:
        * ``trial``        — limitada (TRIAL_MAX_DOWNLOADS descargas)
        * ``perpetual``/``perpetua`` — licencia perpetua, descargas ilimitadas
        * ``subscription``/``anual`` — suscripción activa, descargas ilimitadas
    """
    tipo: str = 'trial'
    licencia_key: str = ''
    expira: str = ''        # fecha ISO, vacío = sin vencimiento
    activo: bool = True

    _TIPOS_ILIMITADOS = frozenset({
        'perpetual', 'perpetua', 'subscription', 'anual',
    })

    def es_ilimitada(self) -> bool:
        """True si la licencia permite descargas ilimitadas."""
        if not self.activo:
            return False
        if self.tipo not in self._TIPOS_ILIMITADOS:
            return False
        # Si tiene fecha de vencimiento, validarla
        if self.expira:
            try:
                fin = datetime.fromisoformat(self.expira)
                if fin < datetime.now():
                    return False
            except ValueError:
                pass
        return True


@dataclass
class UpdateState:
    """Estado persistido entre runs del check de actualizaciones."""
    downloads_count: int = 0
    skipped_version: str = ''
    last_check_iso: str = ''
    # Caché de la última info publicada por el servidor. Permite mostrar el
    # aviso al arrancar sin volver a consultar la red (el throttle de 24h solo
    # limita el re-fetch, no el mostrar el diálogo).
    cached_version: str = ''
    cached_release_date: str = ''
    cached_changelog: str = ''
    cached_url: str = ''
    cached_min_version: str = ''


@dataclass
class CheckResult:
    """Resultado del chequeo. Siempre se devuelve uno (nunca tira excepción)."""
    info: Optional[VersionInfo] = None
    es_nueva: bool = False
    error: str = ''


# ─────────────────────────────────────────────────────────────────────────────
# Semver
# ─────────────────────────────────────────────────────────────────────────────

_SEMVER_RE = re.compile(r'^\s*v?(\d+)\.(\d+)(?:\.(\d+))?(?:[-+].*)?\s*$')


def _parse_semver(v: str) -> tuple[int, int, int]:
    """Parsea ``'1.2.3'`` o ``'v1.2'`` → ``(1, 2, 3)``. Inválido → ``(0, 0, 0)``."""
    m = _SEMVER_RE.match(v or '')
    if not m:
        return (0, 0, 0)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0))


def is_newer(remote: str, local: str = CURRENT_VERSION) -> bool:
    """True si ``remote`` es semver mayor que ``local``."""
    return _parse_semver(remote) > _parse_semver(local)


_ES_MSIX: "bool | None" = None

def es_msix() -> bool:
    """True si la app corre empaquetada como MSIX (instalada desde la Microsoft
    Store). En ese caso el auto-update propio NO debe correr: la Store gestiona
    las actualizaciones y el contenedor MSIX no permite auto-reemplazar binarios.
    Usa ``GetCurrentPackageFullName`` (APPMODEL_ERROR_NO_PACKAGE = 15700)."""
    global _ES_MSIX
    if _ES_MSIX is not None:
        return _ES_MSIX
    result = False
    if sys.platform == 'win32':
        try:
            import ctypes
            from ctypes import wintypes
            length = wintypes.UINT(0)
            rc = ctypes.windll.kernel32.GetCurrentPackageFullName(
                ctypes.byref(length), None)
            result = (rc != 15700)   # != APPMODEL_ERROR_NO_PACKAGE → empaquetado
        except Exception:
            result = False
    _ES_MSIX = result
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Licencia (lectura/escritura)
# ─────────────────────────────────────────────────────────────────────────────

def cargar_licencia() -> LicenseInfo:
    """Carga la licencia desde disco. Si el archivo no existe o está corrupto,
    devuelve un trial por defecto."""
    if not LICENSE_FILE.exists():
        return LicenseInfo()
    try:
        with LICENSE_FILE.open('r', encoding='utf-8') as f:
            d = json.load(f)
        return LicenseInfo(
            tipo=str(d.get('tipo', 'trial')),
            licencia_key=str(d.get('licencia_key', '')),
            expira=str(d.get('expira', '')),
            activo=bool(d.get('activo', True)),
        )
    except (OSError, json.JSONDecodeError):
        return LicenseInfo()


def guardar_licencia(info: LicenseInfo) -> None:
    """Persiste la info de licencia (al activar o renovar una clave)."""
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    with LICENSE_FILE.open('w', encoding='utf-8') as f:
        json.dump({
            'tipo':         info.tipo,
            'licencia_key': info.licencia_key,
            'expira':       info.expira,
            'activo':       info.activo,
        }, f, indent=2, ensure_ascii=False)


# ─────────────────────────────────────────────────────────────────────────────
# Estado (descargas, versión saltada)
# ─────────────────────────────────────────────────────────────────────────────

def _cargar_state() -> UpdateState:
    if not UPDATE_STATE_FILE.exists():
        return UpdateState()
    try:
        with UPDATE_STATE_FILE.open('r', encoding='utf-8') as f:
            d = json.load(f)
        return UpdateState(
            downloads_count=int(d.get('downloads_count', 0)),
            skipped_version=str(d.get('skipped_version', '')),
            last_check_iso=str(d.get('last_check_iso', '')),
            cached_version=str(d.get('cached_version', '')),
            cached_release_date=str(d.get('cached_release_date', '')),
            cached_changelog=str(d.get('cached_changelog', '')),
            cached_url=str(d.get('cached_url', '')),
            cached_min_version=str(d.get('cached_min_version', '')),
        )
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return UpdateState()


def _guardar_state(state: UpdateState) -> None:
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    with UPDATE_STATE_FILE.open('w', encoding='utf-8') as f:
        json.dump({
            'downloads_count': state.downloads_count,
            'skipped_version': state.skipped_version,
            'last_check_iso':  state.last_check_iso,
            'cached_version':      state.cached_version,
            'cached_release_date': state.cached_release_date,
            'cached_changelog':    state.cached_changelog,
            'cached_url':          state.cached_url,
            'cached_min_version':  state.cached_min_version,
        }, f, indent=2)


def get_download_count() -> int:
    """Cuántas descargas ha iniciado el usuario."""
    return _cargar_state().downloads_count


def increment_download_count() -> int:
    """Aumenta el contador (llamar al lanzar la descarga). Returns nuevo total."""
    state = _cargar_state()
    state.downloads_count += 1
    _guardar_state(state)
    return state.downloads_count


def skip_version(version: str) -> None:
    """Marca una versión como saltada — no se avisará silenciosamente."""
    state = _cargar_state()
    state.skipped_version = version
    _guardar_state(state)


def get_skipped_version() -> str:
    return _cargar_state().skipped_version


def marcar_check(info: "VersionInfo | str") -> None:
    """Registra timestamp del último check exitoso y cachea la info publicada.

    Acepta un ``VersionInfo`` (esquema nuevo, cachea todo) o un ``str`` con la
    versión (compatibilidad). El caché permite mostrar el aviso al arrancar sin
    volver a consultar la red."""
    state = _cargar_state()
    state.last_check_iso = datetime.now().isoformat(timespec='seconds')
    if isinstance(info, VersionInfo):
        state.cached_version      = info.version
        state.cached_release_date = info.release_date
        state.cached_changelog    = info.changelog
        state.cached_url          = info.download_url
        state.cached_min_version  = info.minimum_version or ''
    _guardar_state(state)


def cached_version_info() -> Optional[VersionInfo]:
    """Devuelve la última info de versión cacheada, o ``None`` si no hay."""
    state = _cargar_state()
    if not state.cached_version:
        return None
    return VersionInfo(
        version=state.cached_version,
        release_date=state.cached_release_date,
        changelog=state.cached_changelog,
        download_url=state.cached_url,
        minimum_version=state.cached_min_version or None,
    )


def _horas_desde_ultimo_check() -> float:
    """Horas transcurridas desde el último check exitoso (∞ si nunca)."""
    state = _cargar_state()
    if not state.last_check_iso:
        return float('inf')
    try:
        ts = datetime.fromisoformat(state.last_check_iso)
        return (datetime.now() - ts).total_seconds() / 3600.0
    except ValueError:
        return float('inf')


# ─────────────────────────────────────────────────────────────────────────────
# Permisos de descarga
# ─────────────────────────────────────────────────────────────────────────────

def can_download(licencia: Optional[LicenseInfo] = None) -> tuple[bool, str]:
    """Determina si el usuario puede descargar la actualización.

    Returns:
        ``(puede, razon_si_no_puede)``
    """
    info = licencia if licencia is not None else cargar_licencia()
    if info.es_ilimitada():
        return True, ""
    count = get_download_count()
    if count >= TRIAL_MAX_DOWNLOADS:
        return False, (
            f"Tu plan trial permite hasta {TRIAL_MAX_DOWNLOADS} descargas de "
            f"actualizaciones. Ya has descargado {count} veces. "
            "Adquiere una licencia perpetua o suscripción para descargas "
            "ilimitadas."
        )
    restantes = TRIAL_MAX_DOWNLOADS - count
    razon_warning = (
        f"(plan trial — te quedan {restantes} descarga"
        f"{'s' if restantes != 1 else ''})"
    )
    # Permite pero deja el warning como segunda parte del tuple para que la
    # UI pueda mostrarlo como advertencia opcional.
    return True, razon_warning


# ─────────────────────────────────────────────────────────────────────────────
# HTTP fetch
# ─────────────────────────────────────────────────────────────────────────────

def fetch_version_info(timeout: float = 5.0) -> Optional[VersionInfo]:
    """GET al ``version.json`` remoto. Devuelve ``None`` en cualquier error.

    Usa ``requests`` si está instalado; fallback a ``urllib`` (stdlib)."""
    try:
        import requests  # type: ignore
        resp = requests.get(
            VERSION_URL,
            timeout=timeout,
            headers={'User-Agent': f'ingePresupuestos/{CURRENT_VERSION}'},
        )
        resp.raise_for_status()
        return VersionInfo.from_dict(resp.json())
    except ImportError:
        pass
    except Exception:
        return None

    # Fallback stdlib
    try:
        import urllib.request
        import urllib.error
        req = urllib.request.Request(
            VERSION_URL,
            headers={'User-Agent': f'ingePresupuestos/{CURRENT_VERSION}'},
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode('utf-8'))
        return VersionInfo.from_dict(data)
    except (urllib.error.URLError, json.JSONDecodeError, OSError, ValueError):
        return None


# ─────────────────────────────────────────────────────────────────────────────
# API alto nivel
# ─────────────────────────────────────────────────────────────────────────────

def chequear_actualizacion() -> CheckResult:
    """Chequea actualización contra el servidor. Nunca tira excepción."""
    info = fetch_version_info()
    if info is None:
        return CheckResult(
            error="No se pudo conectar al servidor de actualizaciones."
        )
    if not info.version:
        return CheckResult(error="Respuesta inválida del servidor.")
    nueva = is_newer(info.version, CURRENT_VERSION)
    marcar_check(info)
    return CheckResult(info=info, es_nueva=nueva)


def debe_chequear_silencioso(min_horas: float = 24.0) -> bool:
    """True si tocó otro check silencioso (han pasado más de ``min_horas``
    desde el último). Evita spamear al servidor en cada arranque."""
    return _horas_desde_ultimo_check() >= min_horas
