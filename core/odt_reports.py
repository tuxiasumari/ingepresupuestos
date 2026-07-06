# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""Reportes en formato ODT (OpenDocument Text) — editables.

Reutiliza la lógica de cómputo del módulo `pdf_reports` y genera un
documento ODT con odfpy. Abre nativamente en LibreOffice Writer y
también en MS Word (con compatibilidad).

Mismo set de reportes que `word_reports`. Funciona como alternativa
abierta de formato.
"""
from __future__ import annotations

from odf.opendocument import OpenDocumentText
from odf.style import (
    Style, TextProperties, ParagraphProperties, TableColumnProperties,
    TableProperties, TableCellProperties,
)
from odf.text import P, H, Span
from odf.table import Table, TableColumn, TableRow, TableCell

from core.database import (
    get_db, calcular_totales, get_decimales_ppto, get_insumos_proyecto,
)
from core.pdf_reports import (
    _moneda_simbolo, _fmt, _build_pie_rows, _monto_en_letras,
)


def _add_style(doc, name: str, **kwargs):
    """Helper: crea un estilo de texto/párrafo."""
    style = Style(name=name, family='paragraph')
    text_props = kwargs.pop('text', None)
    para_props = kwargs.pop('para', None)
    if text_props:
        style.addElement(TextProperties(**text_props))
    if para_props:
        style.addElement(ParagraphProperties(**para_props))
    doc.styles.addElement(style)
    return style


def _add_cell_style(doc, name: str, bg: str | None = None,
                    border: str = '0.5pt solid #cbd5e1'):
    style = Style(name=name, family='table-cell')
    attrs = {'border': border, 'padding': '0.1cm'}
    if bg:
        attrs['backgroundcolor'] = bg
    style.addElement(TableCellProperties(**attrs))
    doc.styles.addElement(style)
    return style


def _p(text: str, style: str = 'Default', bold: bool = False,
       italic: bool = False, size: str | None = None,
       color: str | None = None, align: str = 'left') -> P:
    """Crea un párrafo formateado."""
    p = P(stylename=style)
    span = Span()
    if any([bold, italic, size, color]):
        # Aplicar formato inline via Span style
        pass
    span.addText(text)
    p.addElement(span)
    return p


def generar_odt_resumen_ejecutivo(pid: int, archivo: str) -> str:
    """Genera el Resumen Ejecutivo en ODT.

    Versión simplificada: usa el módulo `word_reports` y luego convierte
    el .docx a .odt usando LibreOffice headless si está instalado,
    cayendo a una versión nativa odfpy si no.
    """
    # Approach pragmático: como duplicar el layout en odfpy es invasivo
    # (poco API ergonómica para tablas con borders), generamos primero el
    # .docx con python-docx (ya tenemos código pulido) y convertimos a .odt
    # con LibreOffice en modo headless si está disponible. Si no, devolvemos
    # error pidiendo instalar LibreOffice (uso ocasional, no crítico).
    import shutil
    import subprocess
    import tempfile
    from pathlib import Path
    from core.word_reports import generar_word_resumen_ejecutivo
    from core.soffice import find_soffice, mensaje_instalacion

    binario = find_soffice()
    if not binario:
        raise RuntimeError(mensaje_instalacion())
    with tempfile.TemporaryDirectory() as tmp:
        docx_path = str(Path(tmp) / 'resumen.docx')
        generar_word_resumen_ejecutivo(pid, docx_path)
        # Convertir a ODT
        out_dir = str(Path(archivo).parent)
        result = subprocess.run(
            [binario, '--headless', '--convert-to', 'odt',
             '--outdir', out_dir, docx_path],
            capture_output=True, timeout=60,
        )
        # LibreOffice nombra el archivo como el docx pero con extensión odt
        odt_out = str(Path(out_dir) / 'resumen.odt')
        if Path(odt_out).exists():
            # Si el usuario eligió un nombre distinto, renombrar
            if odt_out != archivo:
                shutil.move(odt_out, archivo)
            return archivo
        raise RuntimeError(
            "La conversión a ODT falló.\n"
            f"stderr: {result.stderr.decode('utf-8', errors='ignore')[:300]}"
        )


def generar_odt_especificaciones(pid: int, archivo: str) -> str:
    """Genera Especificaciones Técnicas en ODT (vía .docx → .odt)."""
    import shutil, subprocess, tempfile
    from pathlib import Path
    from core.word_reports import generar_word_especificaciones
    from core.soffice import find_soffice, mensaje_instalacion

    binario = find_soffice()
    if not binario:
        raise RuntimeError(mensaje_instalacion())
    with tempfile.TemporaryDirectory() as tmp:
        docx_path = str(Path(tmp) / 'especificaciones.docx')
        generar_word_especificaciones(pid, docx_path)
        out_dir = str(Path(archivo).parent)
        result = subprocess.run(
            [binario, '--headless', '--convert-to', 'odt',
             '--outdir', out_dir, docx_path],
            capture_output=True, timeout=60,
        )
        odt_out = str(Path(out_dir) / 'especificaciones.odt')
        if Path(odt_out).exists():
            if odt_out != archivo:
                shutil.move(odt_out, archivo)
            return archivo
        raise RuntimeError(
            "La conversión a ODT falló.\n"
            f"stderr: {result.stderr.decode('utf-8', errors='ignore')[:300]}"
        )


def _convertir_docx_a_odt(gen_docx, archivo: str, stem: str):
    """Genera un .docx con `gen_docx(docx_path)` y lo convierte a .odt."""
    import shutil, subprocess, tempfile
    from pathlib import Path
    from core.soffice import find_soffice, mensaje_instalacion
    binario = find_soffice()
    if not binario:
        raise RuntimeError(mensaje_instalacion())
    with tempfile.TemporaryDirectory() as tmp:
        docx_path = str(Path(tmp) / f'{stem}.docx')
        gen_docx(docx_path)
        out_dir = str(Path(archivo).parent)
        result = subprocess.run(
            [binario, '--headless', '--convert-to', 'odt', '--outdir', out_dir,
             docx_path], capture_output=True, timeout=90)
        odt_out = str(Path(out_dir) / f'{stem}.odt')
        if Path(odt_out).exists():
            if odt_out != archivo:
                shutil.move(odt_out, archivo)
            return archivo
        raise RuntimeError("La conversión a ODT falló.\n"
                           f"stderr: {result.stderr.decode('utf-8', errors='ignore')[:300]}")


def generar_odt_almacen(pid: int, archivo: str) -> str:
    """Control de materiales (kárdex) en ODT (vía .docx → .odt)."""
    from core.word_reports import generar_word_almacen
    return _convertir_docx_a_odt(
        lambda p: generar_word_almacen(pid, p), archivo, 'control_materiales')


def generar_odt_curva_s(pid: int, archivo: str, *, base: str = 'mes_cal',
                        vis: dict = None) -> str:
    """Curva S real en ODT (vía .docx → .odt)."""
    from core.word_reports import generar_word_curva_s
    return _convertir_docx_a_odt(
        lambda p: generar_word_curva_s(pid, p, base=base, vis=vis), archivo, 'curva_s')


def generar_odt_cuaderno(pid: int, parte_ids: list, archivo: str) -> str:
    """Cuaderno de obra (días seleccionados) en ODT (vía .docx → .odt)."""
    from core.word_reports import generar_word_cuaderno
    return _convertir_docx_a_odt(
        lambda p: generar_word_cuaderno(pid, parte_ids, p), archivo, 'cuaderno')


def generar_odt_tdr(req_id: int, archivo: str) -> str:
    """Requerimiento + TDR / EE.TT. en ODT (vía .docx → .odt)."""
    from core.word_reports import generar_word_tdr
    return _convertir_docx_a_odt(
        lambda p: generar_word_tdr(req_id, p), archivo, 'requerimiento_tdr')


def generar_odt_memoria_descriptiva(pid: int, archivo: str) -> str:
    """Genera la Memoria Descriptiva en ODT (vía .docx → .odt)."""
    import shutil, subprocess, tempfile
    from pathlib import Path
    from core.word_reports import generar_word_memoria_descriptiva
    from core.soffice import find_soffice, mensaje_instalacion

    binario = find_soffice()
    if not binario:
        raise RuntimeError(mensaje_instalacion())
    with tempfile.TemporaryDirectory() as tmp:
        docx_path = str(Path(tmp) / 'memoria_descriptiva.docx')
        generar_word_memoria_descriptiva(pid, docx_path)
        out_dir = str(Path(archivo).parent)
        result = subprocess.run(
            [binario, '--headless', '--convert-to', 'odt',
             '--outdir', out_dir, docx_path],
            capture_output=True, timeout=60,
        )
        odt_out = str(Path(out_dir) / 'memoria_descriptiva.odt')
        if Path(odt_out).exists():
            if odt_out != archivo:
                shutil.move(odt_out, archivo)
            return archivo
        raise RuntimeError(
            "La conversión a ODT falló.\n"
            f"stderr: {result.stderr.decode('utf-8', errors='ignore')[:300]}"
        )


_GENERADORES = {
    'resumen':              generar_odt_resumen_ejecutivo,
    'especificaciones':     generar_odt_especificaciones,
    'memoria_descriptiva':  generar_odt_memoria_descriptiva,
}


def tipos_soportados() -> set[str]:
    """Tipos de reporte con export ODT disponible."""
    return set(_GENERADORES.keys())


def generar_odt(tipo: str, pid: int, archivo: str) -> str:
    fn = _GENERADORES.get(tipo)
    if fn is None:
        raise NotImplementedError(
            f"ODT export para tipo «{tipo}» aún no implementado. "
            "Usa Word (.docx) que también abre en LibreOffice."
        )
    return fn(pid, archivo)
