# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""formula_view — Editor de Fórmula Polinómica (≈ formula_polinomica.html).

Vista anclada al ``_root_stack`` de ProyectoView. Layout:
    - Topbar:          ← Presupuesto · Fórmula Polinómica · nombre proyecto
    - Card "Expresión": muestra la fórmula textualmente con badge Σk
    - Card "Monomios":  tabla editable (Símbolo · Descripción · INEI · k · %)
    - Sidebar:          info proyecto · costos ACU (después de calcular) ·
                        explicación · listado INEI frecuentes
    - Acciones:         Auto-calcular · Agregar · Guardar · Exportar Excel
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QSize, Signal, QTimer
from PySide6.QtGui import QFont, QColor, QShortcut, QKeySequence
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QFileDialog, QMessageBox, QSizePolicy, QSpinBox, QComboBox,
)

from core.database import get_db
from core.formula_polinomica import (
    cargar_monomios, calcular_desde_acu, guardar_monomios,
    cargar_periodos, guardar_periodos, calcular_reajuste_k,
)
from core.indices_inei import listar_areas
from utils.formatting import fmt, parse_num
from utils.icons import icon


# ── Paleta — aliases de tokens centralizados (utils/theme.py) ────────────────
from utils.theme import C

ORANGE       = C.brand
ORANGE_DARK  = C.brand_hover
ORANGE_SOFT  = C.brand_soft
SLATE_700    = C.text
SLATE_500    = C.text_secondary
SLATE_400    = "#5C6B7A"
SLATE_300    = C.text_muted
SLATE_100    = C.text_faint
SILVER_50    = C.bg_alt
SILVER_100   = C.bg
SILVER_200   = C.surface_subtle
SILVER_300   = C.border
WHITE        = C.surface
GREEN_700    = C.success
GREEN_SOFT   = C.success_soft
GREEN_DARK   = C.success_dark
RED_500      = C.error
RED_SOFT     = C.error_soft
RED_DARK     = C.error_dark
BLUE_700     = C.info
PAGE_BG      = "#EEF2F7"   # fondo de la vista (canvas detrás de cards)

# Algunos índices INEI que aparecen con frecuencia en proyectos de obra
INEI_FRECUENTES = [
    ("04", "Agregado fino"),
    ("05", "Agregado grueso"),
    ("21", "Cemento Portland tipo I"),
    ("30", "Dólar + inflación (importados)"),
    ("32", "Flete terrestre"),
    ("37", "Herramienta manual"),
    ("38", "Hormigón"),
    ("39", "Índice general de precios (IPC)"),
    ("43", "Madera nacional encofrado"),
    ("47", "Mano de obra inc. leyes sociales"),
    ("48", "Maquinaria y equipo nacional"),
    ("49", "Maquinaria y equipo importado"),
    ("53", "Petróleo diesel"),
    ("54", "Pintura látex"),
    ("65", "Tubería de acero negro/galvanizado"),
    ("72", "Tubería de PVC para agua"),
]


class FormulaView(QWidget):
    """Editor de fórmula polinómica para un proyecto."""

    def __init__(self, proyecto_id: int, proyecto_nombre: str = "",
                 on_back=None, parent=None):
        super().__init__(parent)
        self.pid = proyecto_id
        self.proyecto_nombre = proyecto_nombre
        self._on_back = on_back
        self._monomios: list[dict] = []
        self._proyecto_meta: dict = {}
        self._totales_acu: dict | None = None
        self._build()

    # ── construcción UI ─────────────────────────────────────────────────────
    def _build(self):
        # Canvas slate-100 detrás de los cards (mismo patrón que Cronograma /
        # Hoja de Metrados).
        self.setObjectName("formulaRoot")
        self.setStyleSheet(
            f"QWidget#formulaRoot {{ background:{PAGE_BG}; }}"
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Topbar oscuro slate-700 (mismo patrón que Cronograma) ───────────
        # Barra única compacta (mismo patrón que Cronograma/Metrados/Pie): sin
        # título grande ni nombre de proyecto repetido (ya está en las pestañas).
        hdr = QFrame()
        hdr.setFixedHeight(36)
        hdr.setStyleSheet(f"background:{SLATE_500}; border:none;")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(8, 4, 10, 4)
        hl.setSpacing(6)

        btn_back = QPushButton("← Presupuesto")
        btn_back.setCursor(Qt.PointingHandCursor)
        btn_back.setStyleSheet(
            f"QPushButton {{ background:rgba(255,255,255,0.12); color:white;"
            f" border:1px solid rgba(255,255,255,0.25); border-radius:6px;"
            f" font-size:11px; padding:3px 10px; }}"
            f"QPushButton:hover {{ background:rgba(255,255,255,0.22); }}"
        )
        btn_back.clicked.connect(lambda: self._on_back() if self._on_back else None)
        hl.addWidget(btn_back)
        hl.addSpacing(8)

        lbl_title = QLabel("Fórmula Polinómica")
        lbl_title.setStyleSheet(
            "color:white; font-size:12px; font-weight:700;"
            " background:transparent; border:none;")
        hl.addWidget(lbl_title)

        hl.addStretch(1)

        root.addWidget(hdr)

        # ── Área de contenido con márgenes y canvas slate-100 ───────────────
        content = QWidget()
        content_vl = QVBoxLayout(content)
        content_vl.setContentsMargins(20, 14, 20, 14)
        content_vl.setSpacing(0)

        body = QHBoxLayout()
        body.setSpacing(12)
        body.addLayout(self._build_col_principal(), 7)
        body.addLayout(self._build_col_lateral(), 3)

        content_vl.addLayout(body, 1)
        root.addWidget(content, 1)

    # ── columna principal: fórmula + tabla ──────────────────────────────────
    def _build_col_principal(self) -> QVBoxLayout:
        from utils.theme import apply_shadow
        col = QVBoxLayout()
        col.setSpacing(12)

        # Card: Expresión de la fórmula
        card_expr = QFrame()
        card_expr.setStyleSheet(
            f"QFrame {{ background:{WHITE}; border:1px solid {SILVER_300};"
            f"  border-radius:8px; }}"
        )
        apply_shadow(card_expr, 'sm')
        ev = QVBoxLayout(card_expr)
        ev.setContentsMargins(0, 0, 0, 0)
        ev.setSpacing(0)

        head = QFrame()
        head.setStyleSheet(f"QFrame {{ background:{SLATE_500};"
                            f"  border-radius:8px 8px 0 0; }}")
        hl = QHBoxLayout(head); hl.setContentsMargins(12, 8, 12, 8); hl.setSpacing(6)
        ti_h = QLabel(); ti_h.setPixmap(icon("rep-acus").pixmap(16, 16))
        ti_h.setStyleSheet("background:transparent; border:none;")
        hl.addWidget(ti_h)
        ttl = QLabel("Expresión de la fórmula")
        ttl.setStyleSheet(
            "color:white; font-weight:600; font-size:13px;"
            " background:transparent; border:none;"
        )
        hl.addWidget(ttl)
        hl.addStretch(1)

        self.lbl_suma_badge = QLabel("Σk = 0.0000")
        self.lbl_suma_badge.setStyleSheet(
            f"background:{WHITE}; color:{SLATE_500}; padding:3px 10px;"
            f"  border-radius:4px; font-weight:600; font-size:11px;"
        )
        hl.addWidget(self.lbl_suma_badge)
        ev.addWidget(head)

        self.lbl_expr = QLabel("K = …")
        self.lbl_expr.setWordWrap(True)
        self.lbl_expr.setTextFormat(Qt.RichText)
        f_mono = QFont("monospace"); f_mono.setPointSize(11)
        self.lbl_expr.setFont(f_mono)
        self.lbl_expr.setStyleSheet(
            f"padding:14px 16px; color:#1E2635; line-height:1.8;"
            f" background:transparent; border:none;"
        )
        ev.addWidget(self.lbl_expr)

        # Validación normativa (D.S. 011-79-VC): suma=1, incidencia ≥5%, máx 8.
        self.lbl_validacion = QLabel("")
        self.lbl_validacion.setWordWrap(True)
        self.lbl_validacion.setTextFormat(Qt.RichText)
        self.lbl_validacion.setStyleSheet(
            "padding:0 16px 12px 16px; font-size:11px;"
            " background:transparent; border:none;"
        )
        self.lbl_validacion.setVisible(False)
        ev.addWidget(self.lbl_validacion)

        col.addWidget(card_expr)

        # Card: tabla de monomios
        card_tbl = QFrame()
        card_tbl.setStyleSheet(
            f"QFrame {{ background:{WHITE}; border:1px solid {SILVER_300};"
            f"  border-radius:8px; }}"
        )
        apply_shadow(card_tbl, 'sm')
        tv = QVBoxLayout(card_tbl)
        tv.setContentsMargins(0, 0, 0, 0)
        tv.setSpacing(0)

        head2 = QFrame()
        head2.setStyleSheet(f"QFrame {{ background:{SLATE_500};"
                             f"  border-radius:8px 8px 0 0; }}")
        hl2 = QHBoxLayout(head2); hl2.setContentsMargins(12, 6, 8, 6); hl2.setSpacing(6)
        ti_h2 = QLabel(); ti_h2.setPixmap(icon("rep-presupuesto").pixmap(16, 16))
        ti_h2.setStyleSheet("background:transparent; border:none;")
        hl2.addWidget(ti_h2)
        ttl2 = QLabel("Monomios")
        ttl2.setStyleSheet(
            "color:white; font-weight:600; font-size:13px;"
            " background:transparent; border:none;"
        )
        hl2.addWidget(ttl2)
        hl2.addStretch(1)

        self.btn_calcular = QPushButton("Auto-calcular desde ACU")
        self.btn_calcular.setIcon(icon("rep-acus"))
        self.btn_calcular.setIconSize(QSize(16, 16))
        self.btn_calcular.setCursor(Qt.PointingHandCursor)
        self.btn_calcular.setStyleSheet(
            f"QPushButton {{ background:{ORANGE}; color:white; border:none;"
            f"  border-radius:6px; padding:5px 12px; font-weight:600;"
            f"  font-size:11px; }}"
            f"QPushButton:hover {{ background:{ORANGE_DARK}; }}"
        )
        self.btn_calcular.clicked.connect(self._calcular_desde_acu)
        hl2.addWidget(self.btn_calcular)
        tv.addWidget(head2)

        # Tabla
        self.tbl = QTableWidget(0, 7)
        self.tbl.setHorizontalHeaderLabels(
            ["#", "Símbolo", "Descripción", "Índice INEI", "Coef. k", "% Partic.", ""]
        )
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setAlternatingRowColors(True)
        self.tbl.setEditTriggers(
            QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
            | QAbstractItemView.AnyKeyPressed
        )
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl.setShowGrid(False)
        self.tbl.itemChanged.connect(self._on_item_changed)

        h = self.tbl.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.Fixed); h.resizeSection(0, 36)
        h.setSectionResizeMode(1, QHeaderView.Fixed); h.resizeSection(1, 76)
        h.setSectionResizeMode(2, QHeaderView.Stretch)
        h.setSectionResizeMode(3, QHeaderView.Fixed); h.resizeSection(3, 110)
        h.setSectionResizeMode(4, QHeaderView.Fixed); h.resizeSection(4, 100)
        h.setSectionResizeMode(5, QHeaderView.Fixed); h.resizeSection(5, 90)
        h.setSectionResizeMode(6, QHeaderView.Fixed); h.resizeSection(6, 36)
        tv.addWidget(self.tbl)

        # Footer con total + botones
        foot = QFrame()
        foot.setStyleSheet(
            f"QFrame {{ background:{SILVER_50};"
            f"  border-top:1px solid {SILVER_300};"
            f"  border-radius:0 0 8px 8px; }}"
        )
        fl = QHBoxLayout(foot); fl.setContentsMargins(12, 8, 12, 8); fl.setSpacing(8)

        btn_add = QPushButton("Agregar monomio")
        btn_add.setIcon(icon("add"))
        btn_add.setIconSize(QSize(16, 16))
        btn_add.setCursor(Qt.PointingHandCursor)
        btn_add.setStyleSheet(
            f"QPushButton {{ background:{WHITE}; color:{SLATE_700};"
            f"  border:1px solid {SILVER_300}; border-radius:6px;"
            f"  padding:5px 12px; font-size:11px; }}"
            f"QPushButton:hover {{ background:{ORANGE_SOFT};"
            f"  border-color:{ORANGE}; color:{ORANGE_DARK}; }}"
        )
        btn_add.clicked.connect(self._agregar_monomio)
        fl.addWidget(btn_add)
        fl.addStretch(1)

        self.lbl_suma_foot = QLabel("Σ = 0.0000  ·  0.00%")
        self.lbl_suma_foot.setStyleSheet(
            f"color:{SLATE_500}; font-size:11px; font-weight:600;"
            f"  padding:0 8px; background:transparent; border:none;"
        )
        fl.addWidget(self.lbl_suma_foot)

        self.btn_guardar = QPushButton("Guardar")
        self.btn_guardar.setIcon(icon("guardar"))
        self.btn_guardar.setIconSize(QSize(16, 16))
        self.btn_guardar.setCursor(Qt.PointingHandCursor)
        self.btn_guardar.setStyleSheet(
            f"QPushButton {{ background:{ORANGE}; color:white; border:none;"
            f"  border-radius:6px; padding:5px 14px; font-weight:600;"
            f"  font-size:11px; }}"
            f"QPushButton:hover {{ background:{ORANGE_DARK}; }}"
        )
        self.btn_guardar.clicked.connect(self._guardar)
        fl.addWidget(self.btn_guardar)

        self.btn_export = QPushButton("Exportar Excel")
        self.btn_export.setIcon(icon("exportar"))
        self.btn_export.setIconSize(QSize(16, 16))
        self.btn_export.setCursor(Qt.PointingHandCursor)
        self.btn_export.setStyleSheet(
            f"QPushButton {{ background:{WHITE}; color:{SLATE_700};"
            f"  border:1px solid {SILVER_300}; border-radius:6px;"
            f"  padding:5px 12px; font-size:11px; }}"
            f"QPushButton:hover {{ background:{ORANGE_SOFT};"
            f"  border-color:{ORANGE}; color:{ORANGE_DARK}; }}"
        )
        self.btn_export.clicked.connect(self._exportar_excel)
        fl.addWidget(self.btn_export)

        self.btn_export_pdf = QPushButton("Exportar PDF")
        self.btn_export_pdf.setIcon(icon("exportar"))
        self.btn_export_pdf.setIconSize(QSize(16, 16))
        self.btn_export_pdf.setCursor(Qt.PointingHandCursor)
        self.btn_export_pdf.setStyleSheet(
            f"QPushButton {{ background:{WHITE}; color:{SLATE_700};"
            f"  border:1px solid {SILVER_300}; border-radius:6px;"
            f"  padding:5px 12px; font-size:11px; }}"
            f"QPushButton:hover {{ background:{ORANGE_SOFT};"
            f"  border-color:{ORANGE}; color:{ORANGE_DARK}; }}"
        )
        self.btn_export_pdf.clicked.connect(self._exportar_pdf)
        fl.addWidget(self.btn_export_pdf)

        tv.addWidget(foot)
        col.addWidget(card_tbl, 3)

        # Card 3: Cálculo de Reajuste K con valores INEI
        col.addWidget(self._build_card_reajuste(), 2)

        return col

    # ── card "Cálculo de Reajuste K" ────────────────────────────────────────
    def _build_card_reajuste(self) -> QFrame:
        from utils.theme import apply_shadow
        fr = QFrame()
        fr.setStyleSheet(
            f"QFrame {{ background:{WHITE}; border:1px solid {SILVER_300};"
            f"  border-radius:8px; }}"
        )
        apply_shadow(fr, 'sm')
        v = QVBoxLayout(fr)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        head = QFrame()
        head.setStyleSheet(f"QFrame {{ background:{SLATE_500};"
                            f"  border-radius:8px 8px 0 0; }}")
        hl = QHBoxLayout(head); hl.setContentsMargins(12, 6, 12, 6); hl.setSpacing(8)
        ti = QLabel(); ti.setPixmap(icon("rep-resumen").pixmap(16, 16))
        ti.setStyleSheet("background:transparent; border:none;")
        hl.addWidget(ti)
        ttl = QLabel("Cálculo de Reajuste K (con valores INEI)")
        ttl.setStyleSheet(
            "color:white; font-weight:600; font-size:13px;"
            " background:transparent; border:none;"
        )
        hl.addWidget(ttl)
        hl.addStretch(1)

        self.lbl_k_badge = QLabel("K = —")
        self.lbl_k_badge.setStyleSheet(
            f"background:{WHITE}; color:{SLATE_500}; padding:4px 12px;"
            f"  border-radius:4px; font-weight:700; font-size:12px;"
            f"  font-family: monospace;"
        )
        hl.addWidget(self.lbl_k_badge)
        v.addWidget(head)

        # Fila de períodos + área
        per_row = QFrame()
        per_row.setStyleSheet(f"QFrame {{ background:{SILVER_50};"
                               f"  border-bottom:1px solid {SILVER_300}; }}")
        pl = QHBoxLayout(per_row)
        pl.setContentsMargins(12, 8, 12, 8)
        pl.setSpacing(10)

        # Oferta
        lbl_o = QLabel("Oferta:")
        lbl_o.setStyleSheet(
            f"color:{SLATE_500}; font-weight:600; font-size:12px;"
            f" background:transparent; border:none;"
        )
        pl.addWidget(lbl_o)
        self.cmb_oferta_mes = QComboBox()
        for i in range(1, 13):
            self.cmb_oferta_mes.addItem(
                ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                 "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre",
                 "Diciembre"][i - 1], i
            )
        self.cmb_oferta_mes.setFixedWidth(110)
        pl.addWidget(self.cmb_oferta_mes)

        self.inp_oferta_anio = QSpinBox()
        self.inp_oferta_anio.setRange(1990, 2100)
        self.inp_oferta_anio.setFixedWidth(80)
        pl.addWidget(self.inp_oferta_anio)

        # Separador visual con flecha
        from utils.theme import accent_color as _acc
        flecha = QLabel("→")
        flecha.setStyleSheet(
            f"color:{_acc()}; font-weight:700; font-size:16px;"
            f"  padding:0 8px; background:transparent; border:none;"
        )
        pl.addWidget(flecha)

        # Reajuste
        lbl_r = QLabel("Reajuste:")
        lbl_r.setStyleSheet(
            f"color:{SLATE_500}; font-weight:600; font-size:12px;"
            f" background:transparent; border:none;"
        )
        pl.addWidget(lbl_r)
        self.cmb_reajuste_mes = QComboBox()
        for i in range(1, 13):
            self.cmb_reajuste_mes.addItem(
                ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                 "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre",
                 "Diciembre"][i - 1], i
            )
        self.cmb_reajuste_mes.setFixedWidth(110)
        pl.addWidget(self.cmb_reajuste_mes)

        self.inp_reajuste_anio = QSpinBox()
        self.inp_reajuste_anio.setRange(1990, 2100)
        self.inp_reajuste_anio.setFixedWidth(80)
        pl.addWidget(self.inp_reajuste_anio)

        pl.addSpacing(14)

        # Área
        lbl_a = QLabel("Área:")
        lbl_a.setStyleSheet(
            f"color:{SLATE_500}; font-weight:600; font-size:12px;"
            f" background:transparent; border:none;"
        )
        pl.addWidget(lbl_a)
        self.cmb_area = QComboBox()
        self.cmb_area.setMinimumWidth(180)
        for a in listar_areas():
            txt = f"{a['codigo']} — {a['nombre'][:36]}"
            self.cmb_area.addItem(txt, a['codigo'])
        pl.addWidget(self.cmb_area)

        pl.addStretch(1)

        self.btn_recalcular_k = QPushButton("Recalcular")
        self.btn_recalcular_k.setIcon(icon("rep-acus"))
        self.btn_recalcular_k.setIconSize(QSize(16, 16))
        self.btn_recalcular_k.setCursor(Qt.PointingHandCursor)
        self.btn_recalcular_k.setStyleSheet(
            f"QPushButton {{ background:{ORANGE}; color:white; border:none;"
            f"  border-radius:6px; padding:5px 12px; font-weight:600;"
            f"  font-size:11px; }}"
            f"QPushButton:hover {{ background:{ORANGE_DARK}; }}"
        )
        self.btn_recalcular_k.clicked.connect(self._calcular_k)
        pl.addWidget(self.btn_recalcular_k)

        # Auto-recálculo al cambiar período/área
        self.cmb_oferta_mes.currentIndexChanged.connect(self._calcular_k)
        self.inp_oferta_anio.valueChanged.connect(self._calcular_k)
        self.cmb_reajuste_mes.currentIndexChanged.connect(self._calcular_k)
        self.inp_reajuste_anio.valueChanged.connect(self._calcular_k)
        self.cmb_area.currentIndexChanged.connect(self._calcular_k)

        v.addWidget(per_row)

        # Tabla de detalle
        self.tbl_k = QTableWidget(0, 7)
        self.tbl_k.setHorizontalHeaderLabels([
            "Símbolo", "INEI", "Coef. k", "Io (oferta)", "Ir (reajuste)",
            "Ir / Io", "k × (Ir/Io)"
        ])
        self.tbl_k.verticalHeader().setVisible(False)
        self.tbl_k.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl_k.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl_k.setShowGrid(False)
        self.tbl_k.setStyleSheet(
            "QTableWidget { background:white; border:none; font-size:12px; }"
            "QTableWidget::item { padding:5px 8px; }"
            f"QHeaderView::section {{ background:{SILVER_100};"
            f"  color:{SLATE_500}; padding:5px 8px; border:none;"
            f"  border-bottom:1px solid {SILVER_300};"
            f"  font-size:11px; font-weight:700; }}"
        )
        h2 = self.tbl_k.horizontalHeader()
        h2.setSectionResizeMode(0, QHeaderView.Fixed); h2.resizeSection(0, 70)
        h2.setSectionResizeMode(1, QHeaderView.Fixed); h2.resizeSection(1, 60)
        h2.setSectionResizeMode(2, QHeaderView.Fixed); h2.resizeSection(2, 90)
        h2.setSectionResizeMode(3, QHeaderView.Stretch)
        h2.setSectionResizeMode(4, QHeaderView.Stretch)
        h2.setSectionResizeMode(5, QHeaderView.Fixed); h2.resizeSection(5, 90)
        h2.setSectionResizeMode(6, QHeaderView.Fixed); h2.resizeSection(6, 110)
        v.addWidget(self.tbl_k, 1)

        # Footer
        foot = QFrame()
        foot.setStyleSheet(
            f"QFrame {{ background:{SILVER_50};"
            f"  border-top:1px solid {SILVER_300};"
            f"  border-radius:0 0 8px 8px; }}"
        )
        fl = QHBoxLayout(foot); fl.setContentsMargins(12, 6, 12, 6); fl.setSpacing(8)

        self.lbl_alerta_k = QLabel("")
        self.lbl_alerta_k.setStyleSheet(
            f"color:{RED_500}; font-size:11px; font-weight:600;"
        )
        self.lbl_alerta_k.setWordWrap(True)
        fl.addWidget(self.lbl_alerta_k, 1)

        from utils.theme import accent_hover as _acc_h
        self.lbl_k_grande = QLabel("K = —")
        f_k = QFont("monospace"); f_k.setPointSize(14); f_k.setBold(True)
        self.lbl_k_grande.setFont(f_k)
        self.lbl_k_grande.setStyleSheet(f"color:{_acc_h()}; padding:0 12px;")
        fl.addWidget(self.lbl_k_grande)

        btn_ir_inei = QPushButton("Cargar valores INEI →")
        btn_ir_inei.setCursor(Qt.PointingHandCursor)
        btn_ir_inei.setStyleSheet(
            f"QPushButton {{ background:transparent; color:{BLUE_700};"
            f"  border:none; padding:5px 10px; font-size:11px;"
            f"  font-weight:600; text-decoration:underline; }}"
            f"QPushButton:hover {{ color:{ORANGE_DARK}; }}"
        )
        btn_ir_inei.clicked.connect(self._ir_a_indices_inei)
        fl.addWidget(btn_ir_inei)
        v.addWidget(foot)

        return fr

    def _ir_a_indices_inei(self):
        """Navega al editor de Índices INEI a través de MainWindow."""
        w = self
        while w is not None:
            if hasattr(w, "_ir_a_indices_inei"):
                w._ir_a_indices_inei()
                return
            w = w.parent()
        QMessageBox.information(
            self, "Índices INEI",
            "Para abrir el editor: sidebar → INEI"
        )

    # ── columna lateral: info / costos / ayuda ──────────────────────────────
    def _build_col_lateral(self) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(12)

        # Card info proyecto
        self.card_proy = self._mk_card("Proyecto", "rep-presupuesto")
        col.addWidget(self.card_proy['frame'])
        self.lbl_proy_meta = QLabel("")
        self.lbl_proy_meta.setWordWrap(True)
        self.lbl_proy_meta.setTextFormat(Qt.RichText)
        self.lbl_proy_meta.setStyleSheet(
            f"color:{SLATE_500}; font-size:12px; line-height:1.6;"
            f"  padding:10px 12px;"
        )
        self.card_proy['body'].addWidget(self.lbl_proy_meta)

        # Card costos ACU (oculta hasta calcular)
        self.card_acu = self._mk_card("Costos ACU", "rep-acus")
        self.card_acu['frame'].setVisible(False)
        col.addWidget(self.card_acu['frame'])
        self.lbl_acu = QLabel("")
        self.lbl_acu.setTextFormat(Qt.RichText)
        self.lbl_acu.setStyleSheet(
            f"color:{SLATE_500}; font-size:12px; padding:8px 12px;"
        )
        self.card_acu['body'].addWidget(self.lbl_acu)

        # Card ¿Qué es?
        card_q = self._mk_card("¿Qué es?", "acerca")
        col.addWidget(card_q['frame'])
        ayuda = QLabel(
            "<p>La <b>fórmula polinómica</b> expresa el reajuste de precios "
            "de obra según índices INEI:</p>"
            "<p style='font-family:monospace; background:#F4F6FB;"
            " padding:6px 8px; border-radius:4px; color:#0F172A;'>"
            "K = J·(Jr/Jo) + M·(Mr/Mo) + E·(Er/Eo)</p>"
            "<p>J, M, E son los coeficientes (deben sumar 1.000), y los "
            "índices r/o son los del período de reajuste vs. el de oferta.</p>"
        )
        ayuda.setWordWrap(True)
        ayuda.setTextFormat(Qt.RichText)
        ayuda.setStyleSheet(
            f"color:{SLATE_500}; font-size:11px; padding:10px 12px;"
        )
        card_q['body'].addWidget(ayuda)

        # Card INEI frecuentes
        card_inei = self._mk_card("Índices INEI frecuentes", "rep-resumen")
        col.addWidget(card_inei['frame'])
        tbl_inei = QTableWidget(len(INEI_FRECUENTES), 2)
        tbl_inei.setHorizontalHeaderLabels(["Cód.", "Descripción"])
        tbl_inei.verticalHeader().setVisible(False)
        tbl_inei.setEditTriggers(QAbstractItemView.NoEditTriggers)
        tbl_inei.setShowGrid(False)
        tbl_inei.setStyleSheet(
            "QTableWidget { background:white; border:none; font-size:11px; }"
            "QTableWidget::item { padding:3px 6px; }"
            f"QHeaderView::section {{ background:{SILVER_100};"
            f"  color:{SLATE_500}; font-size:10px; padding:4px;"
            f"  border:none; border-bottom:1px solid {SILVER_300}; }}"
        )
        h = tbl_inei.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.Fixed); h.resizeSection(0, 50)
        h.setSectionResizeMode(1, QHeaderView.Stretch)
        for i, (cod, desc) in enumerate(INEI_FRECUENTES):
            it_c = QTableWidgetItem(cod)
            it_c.setForeground(QColor(SLATE_700))
            f = QFont("monospace"); f.setBold(True); f.setPointSize(9)
            it_c.setFont(f)
            it_c.setTextAlignment(Qt.AlignCenter)
            tbl_inei.setItem(i, 0, it_c)
            it_d = QTableWidgetItem(desc)
            it_d.setForeground(QColor(SLATE_500))
            tbl_inei.setItem(i, 1, it_d)
        tbl_inei.setMaximumHeight(min(220, 24 * len(INEI_FRECUENTES) + 30))
        card_inei['body'].addWidget(tbl_inei)

        col.addStretch(1)
        return col

    def _mk_card(self, titulo: str, ico_alias: str) -> dict:
        from utils.theme import apply_shadow
        fr = QFrame()
        fr.setStyleSheet(
            f"QFrame {{ background:{WHITE}; border:1px solid {SILVER_300};"
            f"  border-radius:8px; }}"
        )
        apply_shadow(fr, 'sm')
        v = QVBoxLayout(fr)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        head = QFrame()
        head.setStyleSheet(f"QFrame {{ background:{SLATE_500};"
                            f"  border-radius:8px 8px 0 0; }}")
        hl = QHBoxLayout(head); hl.setContentsMargins(12, 6, 12, 6); hl.setSpacing(6)
        ico_h = QLabel(); ico_h.setPixmap(icon(ico_alias).pixmap(14, 14))
        ico_h.setStyleSheet("background:transparent; border:none;")
        hl.addWidget(ico_h)
        ttl = QLabel(titulo)
        ttl.setStyleSheet(
            "color:white; font-weight:600; font-size:12px;"
            " background:transparent; border:none;"
        )
        hl.addWidget(ttl)
        hl.addStretch(1)
        v.addWidget(head)
        body = QVBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        v.addLayout(body)
        return {'frame': fr, 'body': body}

    # ── Carga / persistencia ────────────────────────────────────────────────
    def cargar(self):
        """Carga proyecto + monomios persistidos. Llamar al mostrar la vista."""
        conn = get_db()
        proy = conn.execute(
            "SELECT id, nombre, cliente, ubicacion, moneda "
            "FROM proyectos WHERE id=?", (self.pid,)
        ).fetchone()
        conn.close()
        self._proyecto_meta = dict(proy) if proy else {}

        partes = []
        if proy and proy['nombre']:
            partes.append(f"<b>{proy['nombre']}</b>")
        if proy and proy['cliente']:
            partes.append(f"<span style='color:#95A3AB'>{proy['cliente']}</span>")
        if proy and proy['ubicacion']:
            partes.append(f"<span style='color:#95A3AB'>{proy['ubicacion']}</span>")
        if proy and proy['moneda']:
            partes.append(
                f"<span style='background:#485A6C;color:white;"
                f"padding:2px 8px;border-radius:4px;font-size:10px;"
                f"font-weight:600;'>{proy['moneda']}</span>"
            )
        self.lbl_proy_meta.setText("<br>".join(partes) or "—")

        self._monomios = cargar_monomios(self.pid)
        self._render_tabla()
        self._cargar_periodos_ui()
        self._calcular_k()

    def _render_tabla(self):
        self.tbl.blockSignals(True)
        self.tbl.setRowCount(0)
        for i, m in enumerate(self._monomios):
            self._add_row(i, m)
        self.tbl.blockSignals(False)
        self._actualizar_totales()
        self._render_expr()

    def _add_row(self, i: int, m: dict):
        row = self.tbl.rowCount()
        self.tbl.insertRow(row)

        # # de fila (no editable)
        it_n = QTableWidgetItem(str(i + 1))
        it_n.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        it_n.setForeground(QColor(SLATE_300))
        it_n.setTextAlignment(Qt.AlignCenter)
        self.tbl.setItem(row, 0, it_n)

        it_s = QTableWidgetItem(m.get('simbolo', ''))
        f = QFont(); f.setBold(True); f.setPointSize(11)
        it_s.setFont(f)
        it_s.setTextAlignment(Qt.AlignCenter)
        it_s.setForeground(QColor(SLATE_700))
        self.tbl.setItem(row, 1, it_s)

        it_d = QTableWidgetItem(m.get('descripcion', ''))
        self.tbl.setItem(row, 2, it_d)

        it_i = QTableWidgetItem(m.get('indice_inei', ''))
        it_i.setTextAlignment(Qt.AlignCenter)
        f_mono = QFont("monospace"); f_mono.setBold(True)
        it_i.setFont(f_mono)
        self.tbl.setItem(row, 3, it_i)

        coef = float(m.get('coeficiente') or 0)
        it_k = QTableWidgetItem(f"{coef:.4f}")
        it_k.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        f2 = QFont(); f2.setBold(True)
        it_k.setFont(f2)
        self.tbl.setItem(row, 4, it_k)

        it_p = QTableWidgetItem(f"{coef * 100:.2f}%")
        it_p.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        it_p.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        it_p.setForeground(QColor(SLATE_500))
        self.tbl.setItem(row, 5, it_p)

        # Resaltar en rojo si la incidencia está por debajo del 5% (mínimo legal).
        self._resaltar_incidencia(it_k, it_p, coef)

        # botón eliminar
        btn_del = QPushButton()
        btn_del.setIcon(icon("eliminar"))
        btn_del.setIconSize(QSize(14, 14))
        btn_del.setCursor(Qt.PointingHandCursor)
        btn_del.setFixedWidth(28)
        btn_del.setToolTip("Eliminar monomio")
        btn_del.setStyleSheet(
            "QPushButton { background:transparent; border:none; }"
            f"QPushButton:hover {{ background:{RED_SOFT}; border-radius:4px; }}"
        )
        btn_del.clicked.connect(lambda _=False, r=row: self._eliminar_fila(r))
        self.tbl.setCellWidget(row, 6, btn_del)

    def _resaltar_incidencia(self, it_k, it_p, coef: float):
        """Pinta de rojo el coeficiente (y su %) si la incidencia está por
        debajo del 5% (mínimo legal D.S. 011-79-VC); lo limpia si cumple."""
        bajo = 0 < coef < 0.050
        tip = "Incidencia menor al 5% (mínimo legal 0.050)" if bajo else ""
        for it, fg_normal in ((it_k, None), (it_p, QColor(SLATE_500))):
            if it is None:
                continue
            if bajo:
                it.setBackground(QColor(RED_SOFT))
                it.setForeground(QColor(RED_DARK))
            else:
                it.setData(Qt.BackgroundRole, None)   # respeta el zebra
                if fg_normal is None:
                    it.setData(Qt.ForegroundRole, None)
                else:
                    it.setForeground(fg_normal)
            it.setToolTip(tip)

    def _on_item_changed(self, item: QTableWidgetItem):
        row = item.row()
        col = item.column()
        if row >= len(self._monomios):
            return
        m = self._monomios[row]
        if col == 1:
            m['simbolo'] = item.text().strip()
        elif col == 2:
            m['descripcion'] = item.text().strip()
        elif col == 3:
            m['indice_inei'] = item.text().strip()
        elif col == 4:
            m['coeficiente'] = max(0.0, parse_num(item.text()))
            self.tbl.blockSignals(True)
            item.setText(f"{m['coeficiente']:.4f}")
            it_p = self.tbl.item(row, 5)
            if it_p:
                it_p.setText(f"{m['coeficiente'] * 100:.2f}%")
            self._resaltar_incidencia(item, it_p, m['coeficiente'])
            self.tbl.blockSignals(False)

        self._actualizar_totales()
        self._render_expr()

    def _eliminar_fila(self, row: int):
        if 0 <= row < len(self._monomios):
            del self._monomios[row]
            self._render_tabla()

    def _agregar_monomio(self):
        # Primer símbolo libre comenzando por A
        usados = {m.get('simbolo', '').upper() for m in self._monomios}
        simbolo = next(
            (chr(c) for c in range(ord('A'), ord('Z') + 1) if chr(c) not in usados),
            'X'
        )
        self._monomios.append({
            'simbolo': simbolo, 'descripcion': '',
            'indice_inei': '', 'coeficiente': 0.0,
        })
        self._render_tabla()
        # Foco en la celda de descripción del último
        last = self.tbl.rowCount() - 1
        if last >= 0:
            self.tbl.setCurrentCell(last, 2)
            self.tbl.editItem(self.tbl.item(last, 2))

    def _validar_formula(self) -> list:
        """Validaciones del D.S. 011-79-VC para la fórmula polinómica:
          - suma de coeficientes = 1.000,
          - incidencia (coeficiente) mínima 0.050 (5%) por monomio,
          - máximo 8 monomios por fórmula.
        Devuelve la lista de mensajes de incumplimiento (vacía = válida)."""
        monos = self._monomios
        n = len(monos)
        issues = []
        if n == 0:
            return issues
        suma = sum(float(m.get('coeficiente') or 0) for m in monos)
        if abs(suma - 1.0) >= 0.001:
            issues.append(
                f"La suma de coeficientes debe ser 1.000 (actual: {suma:.4f}).")
        if n > 8:
            issues.append(f"Máximo 8 monomios por fórmula (tienes {n}).")
        bajos = [(m.get('simbolo') or '?') for m in monos
                 if 0 < float(m.get('coeficiente') or 0) < 0.050]
        if bajos:
            issues.append(
                "Incidencia menor al 5% (mínimo legal 0.050): "
                + ", ".join(bajos) + ".")
        return issues

    def _actualizar_totales(self):
        suma = sum(float(m.get('coeficiente') or 0) for m in self._monomios)
        ok = abs(suma - 1.0) < 0.001
        bg = GREEN_SOFT if ok else RED_SOFT
        fg = GREEN_DARK if ok else RED_DARK
        self.lbl_suma_badge.setText(f"Σk = {suma:.4f}")
        self.lbl_suma_badge.setStyleSheet(
            f"background:{bg}; color:{fg}; padding:3px 10px;"
            f"  border-radius:4px; font-weight:600; font-size:11px;"
        )
        col_suma = GREEN_DARK if ok else RED_500
        self.lbl_suma_foot.setText(f"Σ = {suma:.4f}  ·  {suma * 100:.2f}%")
        self.lbl_suma_foot.setStyleSheet(
            f"color:{col_suma}; font-size:11px; font-weight:600; padding:0 8px;"
        )

        # ── Validación normativa (D.S. 011-79-VC) ──────────────────────────
        from html import escape as _esc
        issues = self._validar_formula()
        if not self._monomios:
            self.lbl_validacion.setVisible(False)
        elif issues:
            self.lbl_validacion.setText(
                "⚠ " + "<br>⚠ ".join(_esc(i) for i in issues))
            self.lbl_validacion.setStyleSheet(
                f"padding:0 16px 12px 16px; font-size:11px; color:{RED_DARK};"
                f" background:transparent; border:none; font-weight:600;")
            self.lbl_validacion.setVisible(True)
        else:
            self.lbl_validacion.setText("✓ Fórmula válida (D.S. 011-79-VC)")
            self.lbl_validacion.setStyleSheet(
                f"padding:0 16px 12px 16px; font-size:11px; color:{GREEN_DARK};"
                f" background:transparent; border:none; font-weight:600;")
            self.lbl_validacion.setVisible(True)

    def _render_expr(self):
        partes = []
        for m in self._monomios:
            k = float(m.get('coeficiente') or 0)
            if k <= 0:
                continue
            s = m.get('simbolo') or '?'
            partes.append(
                f"<span style='color:{ORANGE_DARK}'>{k:.4f}</span>"
                f"·(<b>{s}</b>r/<b>{s}</b>o)"
            )
        if not partes:
            self.lbl_expr.setText("<span style='color:#95A3AB'>K = …</span>")
        else:
            self.lbl_expr.setText("<b>K</b> = " + " + ".join(partes))

    # ── Acciones ───────────────────────────────────────────────────────────
    def _calcular_desde_acu(self):
        self.btn_calcular.setEnabled(False)
        self.btn_calcular.setText("Calculando…")
        try:
            r = calcular_desde_acu(self.pid)
        finally:
            self.btn_calcular.setEnabled(True)
            self.btn_calcular.setText("Auto-calcular desde ACU")

        if not r.get('ok'):
            QMessageBox.warning(self, "Auto-calcular",
                                r.get('msg') or "No se pudo calcular.")
            return

        # Reemplazar los monomios existentes
        if self._monomios:
            res = QMessageBox.question(
                self, "Auto-calcular",
                "Esto reemplazará los monomios actuales por 3 monomios "
                "base (J/M/E) calculados desde el ACU.\n\n¿Continuar?",
                QMessageBox.Yes | QMessageBox.No
            )
            if res != QMessageBox.Yes:
                return

        self._monomios = [dict(m) for m in r['monomios']]
        self._totales_acu = r['totales']
        self._render_tabla()
        self._actualizar_panel_acu()

    def _actualizar_panel_acu(self):
        if not self._totales_acu:
            return
        t = self._totales_acu
        cd = t['cd'] or 1
        moneda = self._proyecto_meta.get('moneda', 'Soles')
        rows = [
            ("Mano de Obra", t['MO'] / cd),
            ("Materiales",   t['MAT'] / cd),
            ("Equipos",      t['EQ'] / cd),
        ]
        html = "<table cellspacing='0' cellpadding='4' width='100%'>"
        for k, v in rows:
            html += (
                f"<tr><td>{k}</td>"
                f"<td align='right'><b>{v * 100:.1f}%</b></td></tr>"
            )
        html += (
            f"<tr style='border-top:1px solid #D4D4D4;'>"
            f"<td><b>C.D. Total</b></td>"
            f"<td align='right'><b>{fmt(cd, moneda)}</b></td></tr>"
        )
        html += "</table>"
        self.lbl_acu.setText(html)
        self.card_acu['frame'].setVisible(True)

    def _guardar(self):
        suma = sum(float(m.get('coeficiente') or 0) for m in self._monomios)
        if self._monomios and abs(suma - 1.0) > 0.005:
            res = QMessageBox.question(
                self, "Confirmar",
                f"Los coeficientes suman {suma:.4f} (debería ser 1.000).\n"
                f"¿Guardar de todas formas?",
                QMessageBox.Yes | QMessageBox.No
            )
            if res != QMessageBox.Yes:
                return
        try:
            guardar_monomios(self.pid, self._monomios)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo guardar:\n{e}")
            return
        QMessageBox.information(
            self, "Guardado",
            f"Fórmula polinómica guardada ({len(self._monomios)} monomios)."
        )

    def _exportar_excel(self):
        """Exporta la fórmula a Excel usando exporter.exportar_formula_polinomica."""
        nombre = self._proyecto_meta.get('nombre', '') or "proyecto"
        import re
        slug = re.sub(r'[^\w\s-]', '', nombre)[:40].strip()
        slug = re.sub(r'\s+', '_', slug) or "proyecto"
        from datetime import datetime
        fecha = datetime.now().strftime("%Y%m%d_%H%M")
        sugerido = f"{slug}_formula_{fecha}.xlsx"

        path, _ = QFileDialog.getSaveFileName(
            self, "Exportar Fórmula Polinómica", sugerido, "Excel (*.xlsx)"
        )
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"

        try:
            # Asegurar que esté guardada antes de exportar
            guardar_monomios(self.pid, self._monomios)
            from core.exporter import exportar_formula_polinomica
            buf = exportar_formula_polinomica(self.pid)
            with open(path, "wb") as f:
                f.write(buf.getvalue())
        except Exception as e:
            import traceback; traceback.print_exc()
            QMessageBox.critical(self, "Error",
                                 f"No se pudo exportar:\n{e}")
            return
        QMessageBox.information(self, "Exportado",
                                f"Archivo guardado:\n{path}")

    def _exportar_pdf(self):
        """Exporta la fórmula polinómica a PDF (mismo pipeline/estilo que los
        demás reportes: portada, encabezado y pie compartidos)."""
        nombre = self._proyecto_meta.get('nombre', '') or "proyecto"
        import re
        slug = re.sub(r'[^\w\s-]', '', nombre)[:40].strip()
        slug = re.sub(r'\s+', '_', slug) or "proyecto"
        from datetime import datetime
        fecha = datetime.now().strftime("%Y%m%d_%H%M")
        sugerido = f"{slug}_formula_{fecha}.pdf"

        path, _ = QFileDialog.getSaveFileName(
            self, "Exportar Fórmula Polinómica a PDF", sugerido, "PDF (*.pdf)"
        )
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"

        try:
            # Asegurar que esté guardada antes de exportar
            guardar_monomios(self.pid, self._monomios)
            from core.pdf_reports import generar_pdf_archivo
            generar_pdf_archivo('formula_polinomica', self.pid, path)
        except Exception as e:
            import traceback; traceback.print_exc()
            QMessageBox.critical(self, "Error",
                                 f"No se pudo exportar:\n{e}")
            return
        QMessageBox.information(self, "Exportado",
                                f"Archivo guardado:\n{path}")

    # ── Períodos y cálculo de K (con valores INEI) ──────────────────────────
    def _cargar_periodos_ui(self):
        """Lee los períodos persistidos y los aplica a los widgets."""
        per = cargar_periodos(self.pid)
        self.cmb_oferta_mes.blockSignals(True)
        self.inp_oferta_anio.blockSignals(True)
        self.cmb_reajuste_mes.blockSignals(True)
        self.inp_reajuste_anio.blockSignals(True)
        self.cmb_area.blockSignals(True)
        try:
            for i in range(self.cmb_oferta_mes.count()):
                if self.cmb_oferta_mes.itemData(i) == per['oferta_mes']:
                    self.cmb_oferta_mes.setCurrentIndex(i); break
            self.inp_oferta_anio.setValue(int(per['oferta_anio']))
            for i in range(self.cmb_reajuste_mes.count()):
                if self.cmb_reajuste_mes.itemData(i) == per['reajuste_mes']:
                    self.cmb_reajuste_mes.setCurrentIndex(i); break
            self.inp_reajuste_anio.setValue(int(per['reajuste_anio']))
            for i in range(self.cmb_area.count()):
                if self.cmb_area.itemData(i) == per['area_inei']:
                    self.cmb_area.setCurrentIndex(i); break
        finally:
            self.cmb_oferta_mes.blockSignals(False)
            self.inp_oferta_anio.blockSignals(False)
            self.cmb_reajuste_mes.blockSignals(False)
            self.inp_reajuste_anio.blockSignals(False)
            self.cmb_area.blockSignals(False)

    def _calcular_k(self):
        """Calcula K con los períodos/área actuales y los monomios guardados.
        Persiste los períodos para preservarlos entre sesiones."""
        if not self._monomios:
            self.tbl_k.setRowCount(0)
            self.lbl_k_badge.setText("K = —")
            self.lbl_k_grande.setText("K = —")
            self.lbl_alerta_k.setText(
                "No hay monomios definidos. Crea o auto-calcula la fórmula primero."
            )
            return

        oa = self.inp_oferta_anio.value()
        om = self.cmb_oferta_mes.currentData()
        ra = self.inp_reajuste_anio.value()
        rm = self.cmb_reajuste_mes.currentData()
        area = self.cmb_area.currentData() or '01'

        # Persistir períodos
        try:
            guardar_periodos(self.pid, oa, om, ra, rm, area)
        except Exception:
            pass

        # Calcular
        r = calcular_reajuste_k(
            self.pid,
            oferta_anio=oa, oferta_mes=om,
            reajuste_anio=ra, reajuste_mes=rm,
            area_inei=area,
        )

        # Renderear tabla
        self.tbl_k.setRowCount(0)
        flag = Qt.ItemIsSelectable | Qt.ItemIsEnabled
        for d in r['detalle']:
            row = self.tbl_k.rowCount()
            self.tbl_k.insertRow(row)

            # Símbolo (bold + naranja)
            it_s = QTableWidgetItem(d.get('simbolo') or '?')
            it_s.setFlags(flag)
            f = QFont(); f.setBold(True); f.setPointSize(11)
            it_s.setFont(f)
            it_s.setTextAlignment(Qt.AlignCenter)
            it_s.setForeground(QColor(ORANGE_DARK))
            self.tbl_k.setItem(row, 0, it_s)

            # INEI
            it_i = QTableWidgetItem(d.get('indice_inei') or '—')
            it_i.setFlags(flag)
            it_i.setTextAlignment(Qt.AlignCenter)
            fmono = QFont("monospace"); fmono.setBold(True)
            it_i.setFont(fmono)
            self.tbl_k.setItem(row, 1, it_i)

            # k
            it_k = QTableWidgetItem(f"{d['coeficiente']:.4f}")
            it_k.setFlags(flag)
            it_k.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.tbl_k.setItem(row, 2, it_k)

            # Io
            vo = d.get('valor_o')
            txt_o = f"{vo:.4f}".rstrip('0').rstrip('.') if vo else "— sin dato"
            it_o = QTableWidgetItem(txt_o)
            it_o.setFlags(flag)
            it_o.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            if not vo:
                it_o.setForeground(QColor(RED_500))
            self.tbl_k.setItem(row, 3, it_o)

            # Ir
            vr = d.get('valor_r')
            txt_r = f"{vr:.4f}".rstrip('0').rstrip('.') if vr else "— sin dato"
            it_r = QTableWidgetItem(txt_r)
            it_r.setFlags(flag)
            it_r.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            if not vr:
                it_r.setForeground(QColor(RED_500))
            self.tbl_k.setItem(row, 4, it_r)

            # Ir/Io
            rt = d.get('ratio')
            txt_rt = f"{rt:.4f}" if rt is not None else "—"
            it_rt = QTableWidgetItem(txt_rt)
            it_rt.setFlags(flag)
            it_rt.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            fr_b = QFont(); fr_b.setBold(True)
            it_rt.setFont(fr_b)
            if rt is not None:
                # Verde si ratio > 1, rojo si < 1
                it_rt.setForeground(
                    QColor(GREEN_700 if rt > 1 else (RED_500 if rt < 1 else SLATE_500))
                )
            self.tbl_k.setItem(row, 5, it_rt)

            # k * ratio
            ap = d.get('aporte')
            txt_ap = f"{ap:.4f}" if ap is not None else "—"
            it_a = QTableWidgetItem(txt_ap)
            it_a.setFlags(flag)
            it_a.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            fa = QFont(); fa.setBold(True)
            it_a.setFont(fa)
            it_a.setForeground(QColor(SLATE_700) if ap is not None
                               else QColor(SLATE_300))
            self.tbl_k.setItem(row, 6, it_a)

        # Actualizar badges
        kt = r['k_total']
        sin = r['monomios_sin_datos']
        if sin > 0:
            self.lbl_k_badge.setText(f"K parcial = {kt:.4f}")
            self.lbl_k_badge.setStyleSheet(
                f"background:{RED_SOFT}; color:{RED_DARK}; padding:4px 12px;"
                f"  border-radius:4px; font-weight:700; font-size:12px;"
                f"  font-family:monospace;"
            )
            self.lbl_k_grande.setText(f"K = {kt:.4f}*")
            self.lbl_k_grande.setStyleSheet(
                f"color:{RED_500}; padding:0 12px;"
            )
            self.lbl_alerta_k.setText(
                f"⚠  Faltan valores INEI para {sin} monomio(s). "
                f"El K mostrado es parcial. "
                f"Carga valores en el editor de INEI."
            )
        else:
            self.lbl_k_badge.setText(f"K = {kt:.4f}")
            color_b = GREEN_SOFT
            color_t = GREEN_DARK
            self.lbl_k_badge.setStyleSheet(
                f"background:{color_b}; color:{color_t}; padding:4px 12px;"
                f"  border-radius:4px; font-weight:700; font-size:12px;"
                f"  font-family:monospace;"
            )
            from utils.theme import accent_hover as _acc_h
            self.lbl_k_grande.setText(f"K = {kt:.4f}")
            self.lbl_k_grande.setStyleSheet(
                f"color:{_acc_h()}; padding:0 12px;"
            )
            pct = (kt - 1.0) * 100
            if abs(pct) < 0.001:
                self.lbl_alerta_k.setText(
                    "K = 1.0000 → sin reajuste (oferta = reajuste)."
                )
            else:
                signo = "incremento" if pct > 0 else "decremento"
                self.lbl_alerta_k.setText(
                    f"Reajuste resultante: {signo} de {abs(pct):.2f}% sobre el monto contractual."
                )
