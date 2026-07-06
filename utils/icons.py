# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""Cargador de iconos Elementary OS para ingePresupuestos.

Prioridad:
  1. SVG propio en resources/icons/elementary/24/  (colorizable)
  2. PNG propio en resources/icons/elementary/24/  (se usa tal cual, sin colorizar)
  3. QIcon.fromTheme() del sistema
  4. Icono vacío (sin crash)

Uso:
  from utils.icons import icon
  btn.setIcon(icon("document-new"))
  btn.setIconSize(QSize(20, 20))
"""
from pathlib import Path
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtCore import QSize

_ICON_DIR = Path(__file__).parent.parent / "resources" / "icons" / "elementary" / "24"

# Mapa de aliases: nombre semántico → archivo SVG
_ALIAS: dict[str, str] = {
    # Sidebar
    "home":          "go-home",
    "nuevo":         "document-new",
    "importar":      "document-import",
    "exportar":      "document-export",
    "biblioteca":    "bibliotecacu",
    "catalogos":     "catalogo",
    "insumos":       "package",
    "ia":            "tuxia",
    "tuxia":         "tuxia",
    "asistente":     "tuxia",
    "brain":         "brain",
    "calendario":    "office-calendar",
    "configuracion": "preferences-system",
    "acerca":        "dialog-information",
    "salir":         "system-log-out",
    # Acciones de tarjeta
    "abrir":         "document-open",
    "copiar":        "edit-copy",
    "duplicar":      "edit-copy",
    "editar":        "document-edit",
    "eliminar":      "edit-delete",
    "guardar":       "document-save",
    # Estado
    "favorito_on":   "starred",
    "favorito_off":  "bookmark-new",
    # Otros / acciones generales
    "nuevo_proyecto":"document-new",
    "usuario":       "system-users",
    "ubicacion":     "mark-location",
    "fecha":         "office-calendar",
    "add":           "list-add",
    "remove":        "list-remove",
    "folder":        "folder",
    "buscar":        "edit-find",
    "limpiar":       "edit-clear",
    "cerrar":        "window-close",
    "atras":         "go-previous",
    "imprimir":      "printer",
    "ajustar":       "zoom-fit-best",
    "pdf":           "application-pdf",
    # Centro de Reportes (mapping con elementary equivalents)
    "rep-resumen":         "rep-star",
    "rep-presupuesto":     "catalogo",
    "rep-acus":            "bibliotecacu",
    "rep-metrados":        "libreoffice-calc",
    "rep-insumos":         "package",
    "rep-especificaciones":"libreoffice-writer",
    "rep-cronograma":      "office-calendar",
    "rep-valorizado":      "office-calendar",
    "rep-curva-s":         "office-chart",
    "rep-adquisiciones":   "office-calendar",
    "rep-completo":        "rep-pdf",
    # Decorativos para títulos
    "paquete":       "package",
    "calculadora":   "accessories-calculator",
    "chart":         "office-chart",
    "spreadsheet":   "x-office-spreadsheet",
    "document":      "x-office-document",
    "presentation":  "x-office-presentation",
    "addressbook":   "x-office-address-book",
    "palette":       "color-picker",
    "fullscreen":    "zoom-fit-best",
    # Iconos LibreOffice para tipos de archivo (PNG, sin colorizar)
    "xlsx":          "libreoffice-calc",
    "docx":          "libreoffice-writer",
    "sqlite":        "libreoffice-base",
}

_cache: dict[str, QIcon] = {}


def icon(nombre: str, size: int = 24) -> QIcon:
    """Devuelve QIcon para el nombre dado, usando Elementary OS icons."""
    if nombre in _cache:
        return _cache[nombre]

    # Resolver alias
    archivo = _ALIAS.get(nombre, nombre)

    # 1) SVG propio
    svg_path = _ICON_DIR / f"{archivo}.svg"
    if svg_path.exists():
        ic = QIcon(str(svg_path))
        if not ic.isNull():
            _cache[nombre] = ic
            return ic

    # 2) PNG propio (elementary-xfce u otro pack)
    png_path = _ICON_DIR / f"{archivo}.png"
    if png_path.exists():
        ic = QIcon(str(png_path))
        if not ic.isNull():
            _cache[nombre] = ic
            return ic

    # 3) Sistema (elementary theme si está instalado, si no Yaru/Adwaita)
    ic = QIcon.fromTheme(archivo)
    if not ic.isNull():
        _cache[nombre] = ic
        return ic

    # 3) Fallback con nombre alternativo
    for alt in [nombre, archivo, f"{archivo}-symbolic"]:
        ic = QIcon.fromTheme(alt)
        if not ic.isNull():
            _cache[nombre] = ic
            return ic

    _cache[nombre] = QIcon()
    return QIcon()


def colorize_svg(svg_path: Path, color: str) -> QIcon:
    """Carga un SVG y reemplaza el color currentColor para que coincida con el tema."""
    try:
        txt = svg_path.read_text()
        txt = txt.replace('currentColor', color)
        txt = txt.replace('#000000', color)
        txt = txt.replace('#000', color)
        from PySide6.QtSvg import QSvgRenderer
        from PySide6.QtCore import QByteArray
        from PySide6.QtGui import QPainter
        renderer = QSvgRenderer(QByteArray(txt.encode()))
        pix = QPixmap(24, 24)
        pix.fill(Qt.transparent)
        painter = QPainter(pix)
        renderer.render(painter)
        painter.end()
        return QIcon(pix)
    except Exception:
        return icon(svg_path.stem)


_cache_colored: dict[tuple, QIcon] = {}


def icon_colored(nombre: str, color: str = "white") -> QIcon:
    """Icono coloreado para sidebar oscuro.
    SVG: colorizable con el color dado.
    PNG: se usa tal cual (el pack ya tiene el estilo correcto).

    Cacheado por (nombre, color): sin caché, el dashboard con 400 proyectos
    re-colorizaba ~1.000 SVGs desde disco en cada construcción del Inicio."""
    key = (nombre, color)
    if key in _cache_colored:
        return _cache_colored[key]
    archivo = _ALIAS.get(nombre, nombre)

    # SVG → colorizable
    svg_path = _ICON_DIR / f"{archivo}.svg"
    if svg_path.exists():
        ic = colorize_svg(svg_path, color)
    else:
        # PNG → usar tal cual (sin colorizar; el pack ya tiene colores propios)
        png_path = _ICON_DIR / f"{archivo}.png"
        ic = QIcon(str(png_path)) if png_path.exists() else icon(nombre)
    _cache_colored[key] = ic
    return ic
