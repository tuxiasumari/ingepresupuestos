# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""Bridge a IngeConverter (complemento separado para `.S2K`/`.bak`/`.bkf` de S10).

IngeConverter vive en otro repo (`~/ingeconverter/`) y se distribuye como
complemento descargable. Esta capa lo invoca como subprocess.

**Decisión arquitectónica**: IngeConverter NO se integra dentro de
IngePresupuestos (ver `[[project-ingeconverter-iniciado]]`). La frontera entre
productos es un archivo `.db` SQLite con el schema de IngePresupuestos —
exactamente el mismo que importa `ingepresupuestos_db_importer`.

**Flujo típico:**
    bridge = IngeConverterBridge()
    if not bridge.esta_instalado():
        # mostrar diálogo de descarga
        ...
    presupuestos = bridge.listar_presupuestos(archivo_s2k)  # [{cod, descripcion}]
    db_temp = bridge.convertir(archivo_s2k, cod_presupuesto=presupuestos[0]['cod'])
    # → ahora db_temp se importa con ingepresupuestos_db_importer
    db_temp.unlink()  # cleanup
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional


_IC_VERSION = "0.2.6"
_IC_BASE = f"https://downloads.ingepresupuestos.com/ingeconverter/v{_IC_VERSION}"

if sys.platform == 'win32':
    DOWNLOAD_URL = f"{_IC_BASE}/ingeconverter-setup-v{_IC_VERSION}.exe"
else:
    DOWNLOAD_URL = f"{_IC_BASE}/ingeconverter-v{_IC_VERSION}-linux-x86_64.tar.gz"


class IngeConverterError(Exception):
    """Error genérico del bridge (no instalado, falla del subprocess, etc.)."""


class IngeConverterNotInstalled(IngeConverterError):
    """IngeConverter no se detectó. El caller debe mostrar el diálogo de descarga."""


class BackupVersionTooOld(IngeConverterError):
    """El backup viene de SQL Server <2005 — IngeConverter no puede restaurarlo."""


@dataclass(frozen=True)
class PresupuestoS10:
    """Una entrada listada por IngeConverter sobre lo que contiene un .S2K."""
    cod: str
    descripcion: str


class IngeConverterBridge:
    """Cliente del CLI de IngeConverter como subprocess.

    El binario/script invocado se resuelve por (en orden):
    1. `INGECONVERTER_BIN` en el entorno (override manual)
    2. Ejecutable empaquetado por plataforma:
       - Linux:  `ingeconverter` en PATH o `~/.local/bin/ingeconverter`
       - Windows: `%LOCALAPPDATA%/Programs/IngeConverter/ingeconverter.exe`
       - macOS:  `~/Applications/IngeConverter.app/Contents/MacOS/ingeconverter`
    3. Modo dev: `~/ingeconverter/venv/bin/python -m core.convertir`
       (permite que Marco itere hoy mismo, antes de empaquetar)
    """

    def __init__(self, bin_path: Optional[list[str]] = None):
        self._bin: Optional[list[str]] = bin_path or self._detectar_bin()

    # ── Detección ────────────────────────────────────────────────────────────

    @staticmethod
    def _detectar_bin() -> Optional[list[str]]:
        # 1. Override por env var
        env = os.environ.get("INGECONVERTER_BIN")
        if env:
            return [env]

        # 2. Empaquetado por plataforma
        if sys.platform == "win32":
            cand = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/IngeConverter/ingeconverter.exe"
            if cand.exists():
                return [str(cand)]
        elif sys.platform == "darwin":
            cand = Path.home() / "Applications/IngeConverter.app/Contents/MacOS/ingeconverter"
            if cand.exists():
                return [str(cand)]
        else:  # linux
            for cand in ("ingeconverter", str(Path.home() / ".local/bin/ingeconverter")):
                if Path(cand).is_file() or shutil.which(cand):
                    return [cand]

        # 3. Dev fallback: repo en ~/ingeconverter con venv
        dev_repo = Path.home() / "ingeconverter"
        dev_py = dev_repo / "venv/bin/python"
        if sys.platform == "win32":
            dev_py = dev_repo / "venv/Scripts/python.exe"
        if dev_py.exists() and (dev_repo / "core/convertir.py").exists():
            return [str(dev_py), "-m", "core.convertir"]

        return None

    def esta_instalado(self) -> bool:
        if not self._bin:
            return False
        # Si la primera entrada es un path de archivo, debe existir en disco.
        # Si es un nombre de comando, lo busca en PATH (shutil.which).
        primero = self._bin[0]
        if "/" in primero or "\\" in primero:
            return Path(primero).is_file()
        return shutil.which(primero) is not None

    @property
    def cmd_base(self) -> list[str]:
        if self._bin is None:
            raise IngeConverterNotInstalled(
                "IngeConverter no está instalado.\n\n"
                "Es un complemento gratuito necesario para importar archivos "
                "`.S2K`/`.bak`/`.bkf` de S10 directamente (sin pasar por Excel).\n\n"
                f"Descargalo de: {DOWNLOAD_URL}"
            )
        return list(self._bin)

    def cwd(self) -> Optional[str]:
        """Working directory para el subprocess (necesario en modo dev del repo)."""
        if self._bin is None:
            return None
        # Si invocamos `python -m core.convertir`, el cwd debe ser el repo
        if len(self._bin) >= 3 and self._bin[1] == "-m":
            return str(Path(self._bin[0]).parent.parent.parent)
        return None

    # ── API ──────────────────────────────────────────────────────────────────

    def listar_presupuestos(self, archivo: Path | str) -> list[PresupuestoS10]:
        """Restaura el .S2K y lista los presupuestos que contiene.

        Esto ya levanta el container Docker (Linux/Mac) o la instancia LocalDB
        (Windows). La primera vez puede tardar minutos por el `docker pull`.
        """
        archivo = Path(archivo)
        cmd = [*self.cmd_base, "--archivo", str(archivo), "--listar", "--json"]
        proc = self._run(cmd)
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            raise IngeConverterError(
                f"Salida inválida de IngeConverter (no es JSON): {proc.stdout[:200]}"
            ) from e
        return [PresupuestoS10(cod=d["cod"], descripcion=d["descripcion"]) for d in data]

    def convertir(
        self,
        archivo: Path | str,
        *,
        cod_presupuesto: Optional[str] = None,
        out: Optional[Path] = None,
        on_log: Optional[Callable[[str], None]] = None,
    ) -> Path:
        """Convierte un .S2K a un .db SQLite y retorna su path.

        Args:
            archivo: ruta al .S2K/.bak/.bkf
            cod_presupuesto: si se omite, convierte TODOS los presupuestos al
                directorio `out`. Si se pasa, convierte solo ese a `out`.
            out: archivo .db destino (o directorio si cod_presupuesto=None).
                Si se omite, se crea uno en `tempfile.gettempdir()`.
            on_log: callback que recibe cada línea de stderr de IngeConverter
                (útil para mostrar progreso en una UI).

        Returns:
            Path al .db generado (o al directorio si fue --todos).
        """
        archivo = Path(archivo)
        if out is None:
            tmp_dir = Path(tempfile.mkdtemp(prefix="ingeconv_"))
            out = (tmp_dir / "salida.db") if cod_presupuesto else tmp_dir
        cmd = [*self.cmd_base, "--archivo", str(archivo), "--out", str(out)]
        if cod_presupuesto:
            cmd += ["--presupuesto", cod_presupuesto]
        else:
            cmd += ["--todos"]
        self._run(cmd, on_log=on_log)
        return Path(out)

    # ── Subprocess plumbing ──────────────────────────────────────────────────

    def _run(
        self, cmd: list[str], *, on_log: Optional[Callable[[str], None]] = None,
    ) -> subprocess.CompletedProcess:
        if not self.esta_instalado():
            raise IngeConverterNotInstalled(self.cmd_base)  # raises inside cmd_base

        # Si hay callback de log, capturamos línea a línea desde stderr.
        # Si no, simplemente esperamos a que termine.
        kwargs = dict(cwd=self.cwd(), encoding='utf-8', errors='replace')
        if on_log is None:
            proc = subprocess.run(cmd, capture_output=True, **kwargs)
            self._check(proc)
            return proc

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **kwargs,
        )
        stderr_lines: list[str] = []
        # Leer stderr línea a línea para reportar progreso
        assert proc.stderr is not None
        for line in proc.stderr:
            stderr_lines.append(line)
            on_log(line.rstrip())
        stdout, _ = proc.communicate()
        completed = subprocess.CompletedProcess(
            args=cmd, returncode=proc.returncode,
            stdout=stdout, stderr="".join(stderr_lines),
        )
        self._check(completed)
        return completed

    @staticmethod
    def _check(proc: subprocess.CompletedProcess) -> None:
        if proc.returncode == 0:
            return
        msg = (proc.stderr or proc.stdout or "").strip()
        if proc.returncode == 2 or "muy antiguo" in msg.lower() or "older version" in msg.lower():
            raise BackupVersionTooOld(msg)
        if 'MSSQLLocalDB' in msg or 'LocalDB' in msg:
            extra = ""
            if sys.platform == 'win32' and (
                'stack overflow' in msg.lower()
                or 'misaligned' in msg.lower()
                or 'no se pudo iniciar' in msg.lower()
                or 'recovery handle' in msg.lower()
            ):
                extra = (
                    "\n\n"
                    "POSIBLE CAUSA: tu disco SSD/NVMe usa sectores mayores "
                    "a 4 KB, lo cual SQL Server no soporta.\n\n"
                    "SOLUCIÓN: abre PowerShell como Administrador y ejecuta:\n"
                    '  New-ItemProperty -Path "HKLM:\\SYSTEM\\CurrentControlSet'
                    '\\Services\\stornvme\\Parameters\\Device" '
                    '-Name "ForcedPhysicalSectorSizeInBytes" '
                    '-PropertyType MultiString -Force -Value "* 4095"\n\n'
                    "Después reinicia Windows e intenta de nuevo."
                )
            raise IngeConverterError(
                "SQL Server LocalDB no pudo iniciar.\n\n"
                "Los archivos .S2K son backups de SQL Server y necesitan "
                "LocalDB para restaurarse. Reinstala IngeConverter para "
                "que LocalDB se instale automáticamente.\n\n"
                "IMPORTANTE: después de instalar, reinicia Windows antes "
                "de intentar importar. LocalDB necesita el reinicio para "
                "quedar operativo."
                + extra
            )
        raise IngeConverterError(
            f"IngeConverter falló (código {proc.returncode}):\n{msg or '<sin output>'}"
        )
