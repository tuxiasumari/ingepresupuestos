# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""Editor de formato de reportes — logo, encabezado, color de marca, pie.

Persiste en la tabla `configuracion` mediante core.pdf_reports.set_formato().
"""
from __future__ import annotations

import base64
import os
from typing import Optional

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import (
    QColorDialog, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QSizePolicy,
    QSpacerItem, QToolButton, QVBoxLayout, QWidget,
)

from core import pdf_reports

ORANGE      = "#F37329"
ORANGE_DARK = "#C0621A"
SLATE_700   = "#2E3C52"
SLATE_500   = "#485A6C"
SLATE_300   = "#94A3B8"
SLATE_100   = "#E2E8F0"
SILVER_50   = "#FAFBFC"
SILVER_100  = "#F8F9FA"
WHITE       = "#FFFFFF"


class FormatoReporteDialog(QDialog):
    """Diálogo para editar la configuración de formato de reportes."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configurar formato de reportes")
        self.setMinimumWidth(560)
        self.resize(620, 660)
        self.setStyleSheet(f"QDialog {{ background:{SILVER_100}; }}")

        self._formato = pdf_reports.get_formato()
        self._build_ui()
        self._load_values()

    # ─── UI ──────────────────────────────────────────────────────────────────

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Header
        hdr = QFrame()
        hdr.setFixedHeight(44)
        hdr.setStyleSheet(f"background:{SLATE_700};")
        hdr_l = QHBoxLayout(hdr)
        hdr_l.setContentsMargins(18, 0, 18, 0)
        ico = QLabel("🎨")
        ico.setStyleSheet(
            "color:white; font-size:18px;"
            " background:transparent; border:none;"
        )
        hdr_l.addWidget(ico)
        t = QLabel("Configurar formato de reportes")
        t.setStyleSheet(
            "color:white; font-size:14px; font-weight:700;"
            " background:transparent; border:none;"
        )
        hdr_l.addWidget(t)
        hdr_l.addStretch(1)
        outer.addWidget(hdr)

        # Form scrollable
        body = QFrame()
        body.setStyleSheet(f"background:{SILVER_100};")
        body_l = QVBoxLayout(body)
        body_l.setContentsMargins(20, 16, 20, 16)
        body_l.setSpacing(12)

        # ── Marca / empresa ──
        body_l.addWidget(self._section_title("Marca / Empresa"))
        form1 = QFormLayout()
        form1.setSpacing(10)
        form1.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.inp_empresa = QLineEdit()
        self.inp_empresa.setPlaceholderText("ingePresupuestos")
        self.inp_empresa.setStyleSheet(self._le_ss())
        form1.addRow("Nombre de empresa:", self.inp_empresa)

        self.inp_subtitulo = QLineEdit()
        self.inp_subtitulo.setPlaceholderText("Sistema de Presupuestos de Obra Pública")
        self.inp_subtitulo.setStyleSheet(self._le_ss())
        form1.addRow("Subtítulo / lema:", self.inp_subtitulo)

        body_l.addLayout(form1)

        # ── Logo ──
        body_l.addWidget(self._section_title("Logo"))
        logo_row = QHBoxLayout()
        self._lbl_logo = QLabel()
        self._lbl_logo.setFixedSize(180, 60)
        self._lbl_logo.setAlignment(Qt.AlignCenter)
        self._lbl_logo.setStyleSheet(
            f"background:{WHITE}; border:1px dashed {SLATE_100};"
            f" border-radius:6px; color:{SLATE_300}; font-size:11px;"
        )
        logo_row.addWidget(self._lbl_logo)

        logo_btns = QVBoxLayout()
        logo_btns.setSpacing(6)
        btn_logo = QPushButton("Elegir imagen…")
        btn_logo.setCursor(Qt.PointingHandCursor)
        btn_logo.setStyleSheet(self._btn_ss())
        btn_logo.clicked.connect(self._choose_logo)
        logo_btns.addWidget(btn_logo)

        self.btn_clear_logo = QPushButton("Quitar logo")
        self.btn_clear_logo.setCursor(Qt.PointingHandCursor)
        self.btn_clear_logo.setStyleSheet(self._btn_ss(danger=True))
        self.btn_clear_logo.clicked.connect(self._clear_logo)
        logo_btns.addWidget(self.btn_clear_logo)
        logo_btns.addStretch(1)
        logo_row.addLayout(logo_btns)
        logo_row.addStretch(1)
        body_l.addLayout(logo_row)

        body_l.addWidget(self._hint(
            "Recomendado: PNG con fondo transparente, máx. ~240×60 px."
        ))

        # ── Color de marca ──
        body_l.addWidget(self._section_title("Color de marca"))
        col_row = QHBoxLayout()
        col_row.setSpacing(10)
        self._color_swatch = QFrame()
        self._color_swatch.setFixedSize(60, 28)
        self._color_swatch.setStyleSheet(
            f"background:{ORANGE}; border:1px solid {SLATE_100}; border-radius:6px;"
        )
        col_row.addWidget(self._color_swatch)

        self.inp_color = QLineEdit()
        self.inp_color.setPlaceholderText("#F37329")
        self.inp_color.setMaxLength(7)
        self.inp_color.setStyleSheet(self._le_ss())
        self.inp_color.setFixedWidth(120)
        self.inp_color.textChanged.connect(self._on_color_text)
        col_row.addWidget(self.inp_color)

        btn_pick = QPushButton("Elegir…")
        btn_pick.setCursor(Qt.PointingHandCursor)
        btn_pick.setStyleSheet(self._btn_ss())
        btn_pick.clicked.connect(self._pick_color)
        col_row.addWidget(btn_pick)
        col_row.addStretch(1)
        body_l.addLayout(col_row)

        body_l.addWidget(self._hint(
            "Color principal usado en bandas, títulos y barras del Gantt. "
            "El color oscuro se calcula automáticamente."
        ))

        # ── Pie de página personalizado ──
        body_l.addWidget(self._section_title("Pie de página (opcional)"))
        form2 = QFormLayout()
        form2.setSpacing(10)
        form2.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.inp_pie_izq = QLineEdit()
        self.inp_pie_izq.setPlaceholderText("Por defecto: Cliente del proyecto")
        self.inp_pie_izq.setStyleSheet(self._le_ss())
        form2.addRow("Texto izquierdo:", self.inp_pie_izq)

        self.inp_pie_cen = QLineEdit()
        self.inp_pie_cen.setPlaceholderText("Por defecto: fecha de generación")
        self.inp_pie_cen.setStyleSheet(self._le_ss())
        form2.addRow("Texto central:", self.inp_pie_cen)

        self.inp_pie_der = QLineEdit()
        self.inp_pie_der.setPlaceholderText("Por defecto: Página X de N")
        self.inp_pie_der.setStyleSheet(self._le_ss())
        form2.addRow("Texto derecho:", self.inp_pie_der)
        body_l.addLayout(form2)

        body_l.addStretch(1)
        outer.addWidget(body, stretch=1)

        # Botones
        bar = QFrame()
        bar.setFixedHeight(56)
        bar.setStyleSheet(f"background:{WHITE}; border-top:1px solid {SLATE_100};")
        bar_l = QHBoxLayout(bar)
        bar_l.setContentsMargins(18, 8, 18, 8)
        bar_l.setSpacing(10)

        btn_reset = QPushButton("Restaurar valores por defecto")
        btn_reset.setCursor(Qt.PointingHandCursor)
        btn_reset.setStyleSheet(self._btn_ss())
        btn_reset.clicked.connect(self._reset_defaults)
        bar_l.addWidget(btn_reset)
        bar_l.addStretch(1)

        btn_cancel = QPushButton("Cancelar")
        btn_cancel.setCursor(Qt.PointingHandCursor)
        btn_cancel.setStyleSheet(self._btn_ss())
        btn_cancel.clicked.connect(self.reject)
        bar_l.addWidget(btn_cancel)

        btn_ok = QPushButton("Guardar")
        btn_ok.setCursor(Qt.PointingHandCursor)
        btn_ok.setStyleSheet(self._btn_ss(primary=True))
        btn_ok.clicked.connect(self._save_and_accept)
        bar_l.addWidget(btn_ok)

        outer.addWidget(bar)

    def _section_title(self, text: str) -> QLabel:
        l = QLabel(text)
        l.setStyleSheet(
            f"color:{SLATE_700}; font-size:11px; font-weight:700;"
            f" letter-spacing:1px; text-transform:uppercase;"
            f" padding:4px 0; border-bottom:1px solid {SLATE_100};"
        )
        return l

    def _hint(self, text: str) -> QLabel:
        l = QLabel(text)
        l.setStyleSheet(f"color:{SLATE_300}; font-size:10px; font-style:italic;")
        l.setWordWrap(True)
        return l

    def _le_ss(self) -> str:
        return (
            f"QLineEdit {{ background:{WHITE}; border:1px solid {SLATE_100};"
            f" border-radius:6px; padding:6px 8px; font-size:12px; }}"
            f"QLineEdit:focus {{ border-color:{ORANGE}; }}"
        )

    def _btn_ss(self, primary: bool = False, danger: bool = False) -> str:
        if primary:
            from utils.theme import BTN_PRIMARY_SS
            return BTN_PRIMARY_SS
        if danger:
            return (
                f"QPushButton {{ background:{WHITE}; color:#C6262E;"
                f" border:1px solid {SLATE_100}; border-radius:6px;"
                f" padding:6px 12px; font-size:11px; }}"
                f"QPushButton:hover {{ background:#FFEDED; border-color:#C6262E; }}"
            )
        return (
            f"QPushButton {{ background:{WHITE}; color:{SLATE_700};"
            f" border:1px solid {SLATE_100}; border-radius:6px;"
            f" padding:6px 12px; font-size:11px; }}"
            f"QPushButton:hover {{ background:{SILVER_100}; border-color:{ORANGE};"
            f" color:{ORANGE_DARK}; }}"
        )

    # ─── Carga de valores ────────────────────────────────────────────────────

    def _load_values(self):
        f = self._formato
        self.inp_empresa.setText(f.get('rep_empresa_nombre') or '')
        self.inp_subtitulo.setText(f.get('rep_empresa_subtitulo') or '')
        self.inp_color.setText(f.get('rep_color_marca') or '#F37329')
        self.inp_pie_izq.setText(f.get('rep_pie_izquierdo') or '')
        self.inp_pie_cen.setText(f.get('rep_pie_central') or '')
        self.inp_pie_der.setText(f.get('rep_pie_derecho') or '')
        self._update_color_swatch(self.inp_color.text())
        self._update_logo_preview(f.get('rep_logo_b64') or '')

    # ─── Logo ────────────────────────────────────────────────────────────────

    def _choose_logo(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Seleccionar logo",
            os.path.expanduser("~"),
            "Imágenes (*.png *.jpg *.jpeg *.svg *.bmp)"
        )
        if not path:
            return
        try:
            img = QImage(path)
            if img.isNull():
                raise ValueError("No se pudo leer la imagen")
            # Escalar a tamaño razonable (max 480 ancho)
            if img.width() > 480:
                img = img.scaledToWidth(480, Qt.SmoothTransformation)
            ba = QByteArray()
            from PySide6.QtCore import QBuffer, QIODevice
            buf = QBuffer(ba)
            buf.open(QIODevice.WriteOnly)
            img.save(buf, "PNG")
            b64 = bytes(ba.toBase64()).decode('ascii')
            self._formato['rep_logo_b64'] = b64
            self._update_logo_preview(b64)
        except Exception as e:
            QMessageBox.critical(self, "Logo", f"No se pudo cargar la imagen:\n{e}")

    def _clear_logo(self):
        self._formato['rep_logo_b64'] = ''
        self._update_logo_preview('')

    def _update_logo_preview(self, b64: str):
        if not b64:
            self._lbl_logo.setPixmap(QPixmap())
            self._lbl_logo.setText("Sin logo")
            self.btn_clear_logo.setEnabled(False)
            return
        try:
            ba = QByteArray.fromBase64(b64.encode('ascii'))
            img = QImage()
            if img.loadFromData(ba):
                pm = QPixmap.fromImage(img.scaled(
                    178, 58, Qt.KeepAspectRatio, Qt.SmoothTransformation
                ))
                self._lbl_logo.setPixmap(pm)
                self._lbl_logo.setText("")
                self.btn_clear_logo.setEnabled(True)
                return
        except Exception:
            pass
        self._lbl_logo.setPixmap(QPixmap())
        self._lbl_logo.setText("Logo inválido")

    # ─── Color ───────────────────────────────────────────────────────────────

    def _pick_color(self):
        actual = QColor(self.inp_color.text() or ORANGE)
        c = QColorDialog.getColor(actual, self, "Color de marca")
        if c.isValid():
            self.inp_color.setText(c.name().upper())

    def _on_color_text(self, txt: str):
        self._update_color_swatch(txt)

    def _update_color_swatch(self, txt: str):
        c = QColor(txt or ORANGE)
        if not c.isValid():
            c = QColor(ORANGE)
        self._color_swatch.setStyleSheet(
            f"background:{c.name()}; border:1px solid {SLATE_100}; border-radius:6px;"
        )

    # ─── Restaurar / Guardar ─────────────────────────────────────────────────

    def _reset_defaults(self):
        for k, default in pdf_reports.FORMATO_CLAVES.items():
            self._formato[k] = default
        self._load_values()

    def _save_and_accept(self):
        # Recoger valores actuales
        color = (self.inp_color.text() or '').strip().upper()
        if color and not (color.startswith('#') and len(color) == 7):
            QMessageBox.warning(self, "Color",
                                "Ingresa un color HEX válido (ej. #F37329).")
            return

        self._formato['rep_empresa_nombre']    = self.inp_empresa.text().strip()
        self._formato['rep_empresa_subtitulo'] = self.inp_subtitulo.text().strip()
        self._formato['rep_color_marca']       = color or '#F37329'
        self._formato['rep_color_marca_dk']    = self._darken(color or '#F37329')
        self._formato['rep_pie_izquierdo']     = self.inp_pie_izq.text().strip()
        self._formato['rep_pie_central']       = self.inp_pie_cen.text().strip()
        self._formato['rep_pie_derecho']       = self.inp_pie_der.text().strip()

        pdf_reports.set_formato(self._formato)
        self.accept()

    @staticmethod
    def _darken(hex_color: str, factor: float = 0.78) -> str:
        c = QColor(hex_color)
        if not c.isValid():
            return ORANGE_DARK
        h, s, v, a = c.getHsv()
        v = int(max(0, min(255, v * factor)))
        c.setHsv(h, s, v, a)
        return c.name().upper()
