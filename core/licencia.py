# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""Sistema de licencias premium de IngePresupuestos.

Modelo (decidido sesión 2026-05-22):

* **Trial 30 días full** desde el primer arranque — sin registro, sin email.
  Se crea ``license.json`` con ``tipo='trial'`` y ``expira=hoy+30``. Durante
  el trial los exports editables están desbloqueados.
* Tras vencer el trial → solo se bloquean los **exports editables**. La app
  sigue 100% funcional para crear/editar proyectos, importar de cualquier
  software, generar reportes PDF, usar Tuxia con API key del usuario, etc.
* **Siempre libre (sin trial, sin licencia):** todos los reportes PDF,
  imágenes derivadas, importadores nativos (Delphin/PowerCost/S10), Tuxia
  con la API key que configure el usuario, y la app entera.
* **Requiere licencia activa (tras los 30 días de trial):** exports
  editables — Excel (.xlsx), ODS, Word (.docx), ODT, MS Project (.xml).
  Precios: **USD 30 anual / USD 150 perpetua**.

Validación de claves: **RSA-2048 firmada offline** con la clave privada
de Marco (vive en su máquina, NUNCA en el repo). El binario tiene
``resources/license_public.pem`` bundleada y verifica la firma de cada
clave antes de aceptarla. Una clave es bytes JSON + firma:

    {
        "v": 1,                    # versión del formato
        "tipo": "anual"|"perpetua",
        "nombre": "Juan Pérez",
        "email": "juan@correo.com",
        "machine_id": "ab12cd34…", # binding 1 máquina
        "emitida": "2026-05-20",
        "expira": "2027-05-20"     # solo para anuales; perpetuas vacío
    }
    |
    <firma RSA-PSS SHA-256 base64>

Formato user-facing: base64url(payload_json) + "." + base64url(firma).

Estado runtime se guarda en ``license.json`` (mismo archivo que usa
``update_manager.py``, extendido con campos de premium).
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from core.config import BASE_DIR, USER_DATA_DIR


# ─────────────────────────────────────────────────────────────────────────────
# Configuración
# ─────────────────────────────────────────────────────────────────────────────

#: Duración del trial automático al primer arranque.
TRIAL_DIAS = 30

#: Archivo de estado de licencia (compartido con update_manager).
LICENSE_FILE = USER_DATA_DIR / "license.json"

#: Clave pública para verificar firmas. Bundleada en el binario.
#: Bajo PyInstaller `BASE_DIR` apunta al directorio temporal de extracción.
PUBLIC_KEY_PATH = BASE_DIR / "resources" / "license_public.pem"

#: URLs para los CTAs del diálogo "Comprar licencia".
URL_COMPRA = "https://ingepresupuestos.com/licencia"
URL_WHATSAPP = "https://wa.me/51998839090?text=Hola%2C%20quiero%20comprar%20una%20licencia%20de%20IngePresupuestos"
EMAIL_CONTACTO = "ing.sumari@gmail.com"

#: Versión del formato de clave. Bumpear si cambia el JSON payload.
LICENSE_FORMAT_VERSION = 1


# ─────────────────────────────────────────────────────────────────────────────
# Machine ID — binding 1 licencia / 1 máquina
# ─────────────────────────────────────────────────────────────────────────────

def _get_physical_macs() -> list[str]:
    """Enumerate Ethernet + WiFi MACs only, sorted.

    Excludes Bluetooth, virtual adapters, Docker bridges, VPNs, and
    locally-administered MACs.  The result must be identical on Linux
    and Windows for the same hardware.
    """
    raw_macs: set[str] = set()

    if sys.platform == "win32":
        # Hasta 2 intentos: `getmac` puede tardar/fallar transitoriamente
        # bajo carga (típico justo al arrancar la app). Leemos BYTES y
        # decodificamos con errors='replace' porque la salida viene en la
        # code-page del sistema; un byte no-UTF8 rompería `text=True` →
        # set vacío → fallback frágil. La regex de MAC es ASCII, así que
        # reemplazar bytes inválidos es inocuo.
        for _intento in range(2):
            try:
                out_b = subprocess.check_output(
                    ["getmac", "/v", "/fo", "csv", "/nh"],
                    timeout=15,
                    creationflags=0x08000000,
                )
            except Exception:
                continue
            out = out_b.decode("utf-8", errors="replace")
            for line in out.strip().splitlines():
                if "bluetooth" in line.lower():
                    continue
                m = re.search(
                    r"([0-9A-Fa-f]{2}(?:-[0-9A-Fa-f]{2}){5})", line
                )
                if m:
                    raw_macs.add(m.group(1).replace("-", "").lower())
            if raw_macs:
                break
    else:
        net_dir = "/sys/class/net"
        if os.path.isdir(net_dir):
            for iface in os.listdir(net_dir):
                iface_dir = os.path.join(net_dir, iface)
                if not os.path.islink(os.path.join(iface_dir, "device")):
                    continue
                try:
                    with open(os.path.join(iface_dir, "address")) as f:
                        mac = f.read().strip().lower().replace(":", "")
                        if mac and len(mac) == 12:
                            raw_macs.add(mac)
                except Exception:
                    pass

    physical: list[str] = []
    for mac in raw_macs:
        if mac == "0" * 12:
            continue
        first_byte = int(mac[:2], 16)
        if first_byte & 0x02:
            continue
        physical.append(mac)

    return sorted(physical)


#: Cache en disco del último ``machine_id`` calculado con éxito (set de MACs
#: físicas NO vacío). Se reusa si una lectura posterior falla (p.ej. `getmac`
#: lento/ilegible o `/sys` vacío), evitando caer al fallback frágil de
#: ``uuid.getnode()`` — que en algunas PCs devuelve la MAC de Bluetooth/virtual
#: → otro ID → bloqueo espurio de premium con licencia válida.
#: Es per-SO (vive en ``USER_DATA_DIR``, particiones distintas en dualboot);
#: cada SO cachea el MISMO valor por su lado, así que no hay contaminación
#: cruzada y la paridad Linux↔Windows se mantiene.
MACHINE_ID_CACHE = USER_DATA_DIR / ".machine_id"


def _leer_cache_machine_id() -> str:
    """Devuelve el ID cacheado si existe y tiene formato válido; si no, ''."""
    try:
        txt = MACHINE_ID_CACHE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    return txt if re.fullmatch(r"[0-9a-f]{16}", txt) else ""


def _escribir_cache_machine_id(mid: str) -> None:
    """Persiste el ID bueno. Best-effort: nunca lanza."""
    try:
        USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
        MACHINE_ID_CACHE.write_text(mid, encoding="utf-8")
    except OSError:
        pass


def machine_id() -> str:
    """Cross-OS stable machine identifier.

    Enumerates all physical (universally-administered) MACs on this
    machine, sorts them, and hashes the combination.  This produces the
    same ID on Linux and Windows for the same hardware, regardless of
    which NIC each OS enumerates first.

    Robustez: si la enumeración de MACs físicas falla (set vacío), se
    reutiliza el último ID calculado con éxito (cacheado en disco) en vez
    de caer al fallback de ``uuid.getnode()`` — que puede devolver una MAC
    de Bluetooth/virtual y producir un ID distinto → bloqueo espurio de
    premium. El camino de éxito es byte-idéntico al histórico, así que NO
    cambia el binding existente ni la paridad Linux↔Windows en dualboot.
    """
    macs = _get_physical_macs()
    if macs:
        base = "|".join(macs)
        mid = hashlib.sha256(base.encode("utf-8")).hexdigest()[:16]
        _escribir_cache_machine_id(mid)   # solo cacheamos cálculos buenos
        return mid
    # Lectura de MACs físicas falló → reusar el último ID bueno conocido.
    cached = _leer_cache_machine_id()
    if cached:
        return cached
    # Último recurso (primer arranque sin cache y sin MACs legibles):
    # comportamiento histórico con uuid.getnode().
    base = f"{uuid.getnode():012x}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:16]


def machine_id_pretty() -> str:
    """`machine_id()` formateado en grupos de 4 para mostrar al usuario."""
    mid = machine_id()
    return "-".join(mid[i:i+4] for i in range(0, len(mid), 4))


# ─────────────────────────────────────────────────────────────────────────────
# Estado runtime
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Licencia:
    """Estado actual de licencia leído del disco.

    Tipos:
      * ``trial``      — auto-creada al primer arranque, 30 días
      * ``anual``      — licencia comprada, vencimiento explícito
      * ``perpetua``   — licencia comprada, sin vencimiento
    """
    tipo: str = 'trial'
    nombre: str = ''
    email: str = ''
    machine_id: str = ''        # bindado a esta PC en la activación
    emitida: str = ''           # YYYY-MM-DD
    expira: str = ''            # YYYY-MM-DD, vacío = perpetua
    licencia_key: str = ''      # firma base64 (para auditar)

    @classmethod
    def trial_nuevo(cls, dias: int = TRIAL_DIAS) -> "Licencia":
        hoy = datetime.now().date()
        return cls(
            tipo='trial',
            machine_id=machine_id(),
            emitida=hoy.isoformat(),
            expira=(hoy + timedelta(days=dias)).isoformat(),
        )

    def dias_restantes(self) -> Optional[int]:
        """Días hasta vencer; None si perpetua. Negativo si ya venció."""
        if not self.expira:
            return None
        try:
            fin = datetime.fromisoformat(self.expira).date()
        except ValueError:
            return None
        return (fin - datetime.now().date()).days

    def vigente(self) -> bool:
        """True si la licencia está activa y no vencida."""
        if not self.expira:
            return self.tipo in ('perpetua',)
        dr = self.dias_restantes()
        return dr is not None and dr >= 0

    def puede_premium(self) -> bool:
        """IngePresupuestos es SOFTWARE LIBRE (GPL-3.0-or-later): todas las
        funciones están disponibles para todos, sin candado premium. Se
        conserva el método por compatibilidad con los call-sites, que siempre
        reciben acceso concedido."""
        return True

    def estado_str(self) -> str:
        """Línea descriptiva del estado, para banner/diálogo."""
        if not self.vigente():
            if self.tipo == 'trial':
                return "Período de prueba vencido"
            return "Licencia vencida"
        if self.tipo == 'trial':
            dr = self.dias_restantes() or 0
            if dr == 0:
                return "Último día de prueba"
            if dr == 1:
                return "Queda 1 día de prueba"
            return f"Quedan {dr} días de prueba"
        if self.tipo == 'perpetua':
            return f"Licencia perpetua activa  ·  {self.nombre or self.email or 'titular'}"
        # anual
        dr = self.dias_restantes() or 0
        return f"Licencia activa hasta {self.expira}  ·  {self.nombre or self.email}"


# ─────────────────────────────────────────────────────────────────────────────
# Persistencia (lectura/escritura de license.json)
# ─────────────────────────────────────────────────────────────────────────────

def cargar() -> Licencia:
    """Lee la licencia del disco. Si no existe o está corrupta, devuelve
    un objeto trial "vacío" (NO la persiste — eso lo hace
    ``iniciar_trial_si_falta``)."""
    if not LICENSE_FILE.exists():
        return Licencia()
    try:
        with LICENSE_FILE.open('r', encoding='utf-8') as f:
            d = json.load(f)
    except (OSError, json.JSONDecodeError):
        return Licencia()
    return Licencia(
        tipo=str(d.get('tipo', 'trial')),
        nombre=str(d.get('nombre', '')),
        email=str(d.get('email', '')),
        machine_id=str(d.get('machine_id', '')),
        emitida=str(d.get('emitida', d.get('fecha_inicio', ''))),
        expira=str(d.get('expira', '')),
        licencia_key=str(d.get('licencia_key', '')),
    )


def guardar(lic: Licencia) -> None:
    """Persiste la licencia. Atomic write."""
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        'tipo':         lic.tipo,
        'nombre':       lic.nombre,
        'email':        lic.email,
        'machine_id':   lic.machine_id,
        'emitida':      lic.emitida,
        'expira':       lic.expira,
        'licencia_key': lic.licencia_key,
        # Compat con update_manager.LicenseInfo
        'activo':       True,
    }
    tmp = LICENSE_FILE.with_suffix('.json.tmp')
    with tmp.open('w', encoding='utf-8') as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    os.replace(tmp, LICENSE_FILE)


def iniciar_trial_si_falta() -> Licencia:
    """Llamada desde ``main.py`` al arrancar. Si no hay licencia, crea
    un trial de 30 días bindado a esta máquina. Si ya hay, no hace nada.
    Retorna la licencia (nueva o existente)."""
    if LICENSE_FILE.exists():
        return cargar()
    lic = Licencia.trial_nuevo()
    guardar(lic)
    return lic


# ─────────────────────────────────────────────────────────────────────────────
# Validación de claves firmadas (RSA-PSS)
# ─────────────────────────────────────────────────────────────────────────────

def _cargar_clave_publica():
    """Carga la clave pública bundleada. Cached."""
    from cryptography.hazmat.primitives import serialization
    with PUBLIC_KEY_PATH.open('rb') as f:
        return serialization.load_pem_public_key(f.read())


def _b64u_dec(s: str) -> bytes:
    """Decode base64url tolerando padding faltante."""
    s = s.strip()
    pad = (-len(s)) % 4
    return base64.urlsafe_b64decode(s + ("=" * pad))


def _b64u_enc(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode('ascii').rstrip('=')


def empaquetar_clave(payload: dict, firma: bytes) -> str:
    """Helper para `scripts/gen_license.py`: empaqueta payload + firma
    en un string user-facing single-line."""
    payload_bytes = json.dumps(
        payload, separators=(',', ':'), sort_keys=True, ensure_ascii=False
    ).encode('utf-8')
    return _b64u_enc(payload_bytes) + "." + _b64u_enc(firma)


def parsear_clave(clave: str) -> tuple[dict, bytes]:
    """Parsea una clave en (payload_dict, firma_bytes).

    Acepta:
      - String con formato 'base64url.base64url' (lo emitido por
        ``empaquetar_clave``),
      - Espacios y saltos de línea (el usuario los puede haber metido
        al copiar/pegar) — se eliminan.

    Lanza ValueError si el formato es inválido (la firma no se valida
    todavía; eso lo hace ``activar_clave``).
    """
    clean = "".join(clave.split())   # elimina espacios y newlines
    if "." not in clean:
        raise ValueError("Formato inválido: falta el separador '.'")
    payload_b64, firma_b64 = clean.split(".", 1)
    try:
        payload_bytes = _b64u_dec(payload_b64)
        firma = _b64u_dec(firma_b64)
    except (ValueError, TypeError) as e:
        raise ValueError(f"No se pudo decodificar base64: {e}")
    try:
        payload = json.loads(payload_bytes.decode('utf-8'))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Payload JSON inválido: {e}")
    if not isinstance(payload, dict):
        raise ValueError("Payload debe ser un objeto JSON.")
    return payload, firma


def _verificar_firma(payload: dict, firma: bytes) -> bool:
    """Verifica que `firma` corresponda a `payload` firmado con la
    clave privada del par bundleado. RSA-PSS + SHA-256."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    try:
        pubkey = _cargar_clave_publica()
    except (OSError, ValueError):
        return False

    # Re-serializar payload del MISMO modo que `empaquetar_clave`
    payload_bytes = json.dumps(
        payload, separators=(',', ':'), sort_keys=True, ensure_ascii=False
    ).encode('utf-8')
    try:
        pubkey.verify(
            firma,
            payload_bytes,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH,
            ),
            hashes.SHA256(),
        )
        return True
    except InvalidSignature:
        return False
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Activación
# ─────────────────────────────────────────────────────────────────────────────

def activar_clave(clave: str) -> tuple[bool, str, Optional[Licencia]]:
    """Intenta activar una clave de licencia.

    Returns:
        (ok, mensaje_user_facing, licencia_si_ok)
    """
    # 1. Parsear formato
    try:
        payload, firma = parsear_clave(clave)
    except ValueError as e:
        return False, f"Clave con formato inválido.\n{e}", None

    # 2. Verificar firma
    if not _verificar_firma(payload, firma):
        return False, (
            "La firma de la clave no es válida. Verifica que la clave "
            "esté completa y sin modificaciones.\n\n"
            "Si copiaste la clave, asegurate de no haber agregado o "
            "quitado caracteres."
        ), None

    # 3. Versión del formato
    if int(payload.get('v', 0)) != LICENSE_FORMAT_VERSION:
        return False, (
            "Esta clave fue emitida para una versión incompatible "
            "del sistema de licencias. Contactá al autor para que "
            "te emita una clave nueva."
        ), None

    # 4. Tipo
    tipo = str(payload.get('tipo', '')).lower()
    if tipo not in ('anual', 'perpetua'):
        return False, f"Tipo de licencia desconocido: {tipo!r}", None

    # 5. Machine binding
    mid_clave = str(payload.get('machine_id', ''))
    if mid_clave and mid_clave != machine_id():
        return False, (
            "Esta clave está bindada a otra máquina.\n\n"
            f"ID de tu máquina: {machine_id_pretty()}\n"
            f"ID de la clave:   {'-'.join(mid_clave[i:i+4] for i in range(0,len(mid_clave),4))}\n\n"
            "Si compraste esta clave para esta PC, contactá al autor "
            "indicando tu ID de máquina para que te emita una clave "
            "actualizada."
        ), None

    # 6. Vencimiento (solo anual)
    expira = str(payload.get('expira', ''))
    if tipo == 'anual' and expira:
        try:
            fin = datetime.fromisoformat(expira).date()
            if fin < datetime.now().date():
                return False, (
                    f"Esta clave ya venció el {expira}.\n\n"
                    "Adquirí una renovación o una licencia perpetua."
                ), None
        except ValueError:
            return False, f"Fecha de expiración con formato inválido: {expira}", None

    # 7. OK — construir y guardar Licencia
    lic = Licencia(
        tipo=tipo,
        nombre=str(payload.get('nombre', '')),
        email=str(payload.get('email', '')),
        machine_id=mid_clave or machine_id(),
        emitida=str(payload.get('emitida', datetime.now().date().isoformat())),
        expira=expira,
        licencia_key=clave.strip(),
    )
    guardar(lic)
    msg = f"Licencia {tipo} activada"
    if lic.nombre:
        msg += f" a nombre de {lic.nombre}"
    return True, msg + ".", lic


# ─────────────────────────────────────────────────────────────────────────────
# Gating de features premium
# ─────────────────────────────────────────────────────────────────────────────

#: Etiquetas user-facing para cada feature premium. Las llaves son los
#: ``feature`` que se pasan a ``require_premium`` desde los handlers.
FEATURE_LABELS = {
    'export_editable':  "Exportar reportes editables (Excel · ODS · Word · ODT · MS Project)",
}


def puede_usar(feature: str) -> bool:
    """Chequeo silencioso — devuelve True si el usuario tiene acceso.
    Útil para deshabilitar botones en la UI."""
    return cargar().puede_premium()


def require_premium(feature: str, parent_widget=None) -> bool:
    """Gate principal — llamalo al inicio de cada handler premium.

    Returns:
        True  si el usuario puede usar la feature → continuar.
        False si NO puede → ya se mostró el diálogo, el handler debe
              hacer ``return`` inmediatamente.

    Uso típico::

        def _guardar_xlsx(self):
            from core.licencia import require_premium
            if not require_premium('export_editable', self):
                return
            ...  # resto del handler
    """
    lic = cargar()
    if lic.puede_premium():
        return True
    # Sin permisos — mostrar diálogo (lazy import: PySide6 puede no
    # estar cargado si esto se llama desde un test).
    _mostrar_dialogo_bloqueo(feature, lic, parent_widget)
    return False


def _mostrar_dialogo_bloqueo(feature: str, lic: Licencia, parent) -> None:
    """Diálogo standard de 'Licencia requerida'."""
    try:
        from views.licencia_dialog import mostrar_bloqueo_premium
        mostrar_bloqueo_premium(parent, feature, lic)
    except ImportError:
        # Fallback ultra-defensivo si la vista no está disponible
        try:
            from PySide6.QtWidgets import QMessageBox
            label = FEATURE_LABELS.get(feature, feature)
            QMessageBox.warning(
                parent, "Licencia requerida",
                f"«{label}» requiere una licencia activa.\n\n"
                f"Estado actual: {lic.estado_str()}\n\n"
                f"Adquirí una licencia en {URL_COMPRA}"
            )
        except ImportError:
            pass
