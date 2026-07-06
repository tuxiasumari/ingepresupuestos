# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""Reportes en formato ODS (OpenDocument Spreadsheet) — editables.

Mismo patrón pragmático que `odt_reports.py`: reutiliza el .xlsx de
`core/exporter.py` y lo convierte a .ods vía LibreOffice headless.
Garantiza fidelidad visual sin duplicar la lógica de layout.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from core import exporter
from core.soffice import find_soffice, mensaje_instalacion


def _convertir_xlsx_a_ods(xlsx_path: str, ods_archivo: str) -> str:
    """Convierte un .xlsx existente a .ods en la ruta indicada."""
    binario = find_soffice()
    if not binario:
        raise RuntimeError(mensaje_instalacion())
    out_dir = str(Path(ods_archivo).parent)
    result = subprocess.run(
        [binario, '--headless', '--convert-to', 'ods',
         '--outdir', out_dir, xlsx_path],
        capture_output=True, timeout=60,
    )
    ods_out = str(Path(out_dir) / (Path(xlsx_path).stem + '.ods'))
    if Path(ods_out).exists():
        if ods_out != ods_archivo:
            shutil.move(ods_out, ods_archivo)
        return ods_archivo
    raise RuntimeError(
        "La conversión a ODS falló.\n"
        f"stderr: {result.stderr.decode('utf-8', errors='ignore')[:300]}"
    )


def _generar_via_xlsx(exporter_fn, pid: int, archivo: str,
                      stem: str) -> str:
    """Genera un .ods reusando un exportador .xlsx existente."""
    with tempfile.TemporaryDirectory() as tmp:
        xlsx_path = str(Path(tmp) / f'{stem}.xlsx')
        buf = exporter_fn(pid)
        with open(xlsx_path, 'wb') as f:
            f.write(buf.getvalue())
        return _convertir_xlsx_a_ods(xlsx_path, archivo)


def generar_ods_valorizacion(val_id: int, archivo: str) -> str:
    """Valorización en ODS (vía .xlsx → .ods)."""
    with tempfile.TemporaryDirectory() as tmp:
        xlsx_path = str(Path(tmp) / 'valorizacion.xlsx')
        buf = exporter.exportar_valorizacion(val_id)
        with open(xlsx_path, 'wb') as f:
            f.write(buf.getvalue())
        return _convertir_xlsx_a_ods(xlsx_path, archivo)


def generar_ods_presupuesto(pid: int, archivo: str) -> str:
    return _generar_via_xlsx(exporter.exportar_presupuesto, pid, archivo,
                              'presupuesto')


def generar_ods_acus(pid: int, archivo: str) -> str:
    return _generar_via_xlsx(exporter.exportar_acus, pid, archivo, 'acus')


def generar_ods_insumos(pid: int, archivo: str) -> str:
    return _generar_via_xlsx(exporter.exportar_insumos, pid, archivo, 'insumos')


def generar_ods_metrados(pid: int, archivo: str) -> str:
    return _generar_via_xlsx(exporter.exportar_metrados, pid, archivo, 'metrados')


def generar_ods_completo(pid: int, archivo: str) -> str:
    return _generar_via_xlsx(exporter.exportar_reporte_completo, pid, archivo,
                              'reporte_completo')


def generar_ods_gastos_generales(pid: int, archivo: str) -> str:
    return _generar_via_xlsx(exporter.exportar_gastos_generales, pid, archivo,
                              'gastos_generales')


_GENERADORES = {
    'presupuesto':      generar_ods_presupuesto,
    'acus':             generar_ods_acus,
    'insumos':          generar_ods_insumos,
    'metrados':         generar_ods_metrados,
    'gastos_generales': generar_ods_gastos_generales,
    'completo':         generar_ods_completo,
}


def tipos_soportados() -> set[str]:
    """Tipos de reporte con export ODS disponible."""
    return set(_GENERADORES.keys())


def generar_ods(tipo: str, pid: int, archivo: str) -> str:
    fn = _GENERADORES.get(tipo)
    if fn is None:
        raise NotImplementedError(
            f"ODS export para tipo «{tipo}» aún no implementado. "
            "Usa Excel (.xlsx) que también abre en LibreOffice."
        )
    return fn(pid, archivo)
