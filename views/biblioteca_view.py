# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""biblioteca_view — Biblioteca de Costos Unitarios (≈ biblioteca.html de Flask).

Catálogo de CU reutilizables: cada entrada es una "plantilla" de partida con
unidad, rendimiento, costo unitario, grupo, especificaciones y opcionalmente
sus ACU items (mano de obra, materiales, equipo) referenciando recursos del
catálogo de insumos.

Columnas:
    Descripción · Unidad · Rendimiento · Costo Unit. · Grupo · ACU · Usos

Panel inferior (splitter) muestra los recursos del CU seleccionado.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QSize, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QWidget, QFrame, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QComboBox,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QMessageBox, QMenu, QSplitter, QDialog, QDialogButtonBox, QFormLayout,
    QSizePolicy, QTextEdit, QStackedWidget, QApplication,
)

from core.database import get_db
from utils.formatting import fmt, parse_num
from utils.icons import icon
from utils.theme import C


# ── Paleta — aliases de tokens centralizados (utils/theme.py) ────────────────
ORANGE_500  = C.brand
ORANGE_700  = C.brand_hover
ORANGE_SOFT = C.brand_soft
SLATE_700   = C.text
SLATE_500   = C.text_secondary
SLATE_300   = C.text_muted
SILVER_100  = C.bg
SILVER_200  = C.surface_subtle
SILVER_300  = C.border
WHITE       = C.surface
RED_500     = C.error

# Tonos para los badges MO/MAT/EQ del panel inferior (canónicos del tema)
TIPO_FONDO = {'MO': C.mo_bg, 'MAT': C.mat_bg, 'EQ': C.eq_bg}
TIPO_TEXTO = {'MO': C.mo_fg, 'MAT': C.mat_fg, 'EQ': C.eq_fg, 'SC': C.sc_fg}


# ── Diálogo de edición / creación de CU ──────────────────────────────────────
class CUFormDialog(QDialog):
    """Form para crear/editar una entrada en la biblioteca."""

    def __init__(self, parent=None, cu: dict | None = None):
        super().__init__(parent)
        self.cu = cu or {}
        self.es_edicion = bool(cu and cu.get('id'))
        self.setWindowTitle("Editar costo unitario" if self.es_edicion else "Nuevo costo unitario")
        self.setMinimumWidth(560)
        self._build()
        if self.es_edicion:
            self._cargar()

    def _build(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 18, 20, 16)
        v.setSpacing(10)

        head = QFrame()
        head.setStyleSheet(
            f"QFrame {{ background:{SLATE_500}; border-radius:6px; }}"
        )
        hl = QHBoxLayout(head)
        hl.setContentsMargins(10, 8, 12, 8)
        hl.setSpacing(8)
        ico = QLabel()
        ico.setPixmap(icon("editar" if self.es_edicion else "add").pixmap(20, 20))
        hl.addWidget(ico)
        ttl = QLabel("Editar costo unitario" if self.es_edicion else "Nuevo costo unitario")
        ttl.setStyleSheet(
            "color:white; font-weight:600; font-size:13px;"
            " background:transparent; border:none;"
        )
        hl.addWidget(ttl)
        hl.addStretch(1)
        v.addWidget(head)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setSpacing(8)
        form.setContentsMargins(0, 4, 0, 4)

        self.inp_desc = QLineEdit()
        self.inp_desc.setPlaceholderText("Descripción de la partida")
        form.addRow("Descripción *:", self.inp_desc)

        self.inp_unidad = QLineEdit()
        self.inp_unidad.setMaximumWidth(120)
        self.inp_unidad.setPlaceholderText("m, m², m³, kg, hh, glb…")
        self.inp_unidad.textEdited.connect(self._auto_superindice_unidad)
        form.addRow("Unidad:", self.inp_unidad)

        self.inp_rend = QLineEdit("1.0")
        self.inp_rend.setMaximumWidth(120)
        form.addRow("Rendimiento:", self.inp_rend)

        self.inp_costo = QLineEdit("0.00")
        self.inp_costo.setMaximumWidth(140)
        form.addRow("Costo Unitario:", self.inp_costo)

        self.inp_grupo = QLineEdit()
        self.inp_grupo.setPlaceholderText("Ej: TRABAJOS PRELIMINARES")
        form.addRow("Grupo:", self.inp_grupo)

        self.txt_specs = QTextEdit()
        self.txt_specs.setMinimumHeight(110)
        self.txt_specs.setStyleSheet(
            "QTextEdit { background:white; border:1px solid #C5CDD3; "
            "border-radius:4px; padding:6px; font-size:12px; }"
        )
        form.addRow("Especificaciones:", self.txt_specs)

        v.addLayout(form)

        self.lbl_err = QLabel("")
        self.lbl_err.setStyleSheet(f"color:{RED_500}; font-size:12px; padding:2px 0;")
        v.addWidget(self.lbl_err)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Ok).setText(
            "Guardar cambios" if self.es_edicion else "Crear CU"
        )
        btns.accepted.connect(self._aceptar)
        btns.rejected.connect(self.reject)
        v.addWidget(btns)

    def _auto_superindice_unidad(self, txt: str):
        import re
        m = re.match(r'^([a-zA-Z/]+)([23])$', txt)
        if not m:
            return
        sup = '²' if m.group(2) == '2' else '³'
        self.inp_unidad.blockSignals(True)
        self.inp_unidad.setText(m.group(1) + sup)
        self.inp_unidad.blockSignals(False)

    def _cargar(self):
        c = self.cu
        self.inp_desc.setText(c.get('descripcion', '') or '')
        self.inp_unidad.setText(c.get('unidad', '') or '')
        rend = float(c.get('rendimiento') or 1)
        self.inp_rend.setText((f"{rend:.4f}".rstrip('0').rstrip('.')) or '1')
        self.inp_costo.setText(f"{float(c.get('costo_unitario') or 0):.2f}")
        self.inp_grupo.setText(c.get('grupo', '') or '')
        self.txt_specs.setPlainText(c.get('especificaciones', '') or '')

    def _aceptar(self):
        desc = self.inp_desc.text().strip()
        if not desc:
            self.lbl_err.setText("La descripción es obligatoria.")
            self.inp_desc.setFocus()
            return
        unidad = self.inp_unidad.text().strip()
        rend = parse_num(self.inp_rend.text()) or 1.0
        costo = parse_num(self.inp_costo.text())
        grupo = self.inp_grupo.text().strip()
        specs = self.txt_specs.toPlainText().strip()

        conn = get_db()
        try:
            if self.es_edicion:
                conn.execute(
                    "UPDATE biblioteca_cu SET descripcion=?, unidad=?, rendimiento=?, "
                    "costo_unitario=?, grupo=?, especificaciones=? WHERE id=?",
                    (desc, unidad, rend, costo, grupo, specs, self.cu['id'])
                )
                self.cu_id = self.cu['id']
            else:
                cur = conn.execute(
                    "INSERT INTO biblioteca_cu "
                    "(descripcion, unidad, rendimiento, costo_unitario, grupo, especificaciones, usos) "
                    "VALUES (?,?,?,?,?,?,0)",
                    (desc, unidad, rend, costo, grupo, specs)
                )
                self.cu_id = cur.lastrowid
            conn.commit()
        finally:
            conn.close()
        self.accept()


# ── Vista principal ─────────────────────────────────────────────────────────
class BibliotecaView(QWidget):
    """Catálogo navegable de costos unitarios reutilizables."""

    volver = Signal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setProperty("vista_nombre", "biblioteca")
        self._cu_id_actual: int | None = None
        self._build()
        self.cargar()

    # ── construcción UI ─────────────────────────────────────────────────────
    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)

        # ── Topbar ──
        top = QHBoxLayout()
        top.setSpacing(10)

        ico_t = QLabel()
        ico_t.setPixmap(icon("biblioteca").pixmap(28, 28))
        top.addWidget(ico_t)

        title = QLabel("Biblioteca de Costos Unitarios")
        f = QFont()
        f.setPointSize(15)
        f.setWeight(QFont.DemiBold)
        title.setFont(f)
        title.setStyleSheet(f"color:{SLATE_700};")
        top.addWidget(title)

        self.lbl_subt = QLabel("0 CU")
        self.lbl_subt.setStyleSheet(f"color:{SLATE_300}; padding-left:6px;")
        top.addWidget(self.lbl_subt)
        top.addStretch(1)

        self.btn_nuevo = self._mk_btn("Nuevo CU", primary=True, icon_name="add")
        self.btn_nuevo.clicked.connect(self._nuevo)
        top.addWidget(self.btn_nuevo)

        # Import / Export JSON (Diccionario de Elementos)
        from PySide6.QtWidgets import QMenu as _QMenu
        self.btn_import = self._mk_btn("Importar ▾", icon_name="importar")
        self.btn_import.setToolTip("Importar Biblioteca CU")
        menu_imp = _QMenu(self.btn_import)
        a_json = menu_imp.addAction(icon("rep-presupuesto"),
                                     "Desde JSON (.json)")
        a_json.triggered.connect(self._importar_json)
        a_delphin = menu_imp.addAction(icon("sqlite"),
                                        "Desde Delphin (base .sqlite)")
        a_delphin.triggered.connect(self._importar_delphin_sqlite)
        self.btn_import.setMenu(menu_imp)
        top.addWidget(self.btn_import)

        self.btn_export_json = self._mk_btn("Exportar JSON", icon_name="exportar")
        self.btn_export_json.setToolTip(
            "Exportar toda la Biblioteca CU a archivo JSON"
        )
        self.btn_export_json.clicked.connect(self._exportar_json)
        top.addWidget(self.btn_export_json)
        layout.addLayout(top)

        # ── KPIs ──
        kpis = QHBoxLayout()
        kpis.setSpacing(10)
        self.kpi_total = self._mk_kpi("Total CU", "0", SLATE_500)
        self.kpi_grupos = self._mk_kpi("Grupos", "0", TIPO_TEXTO['MAT'])
        self.kpi_con_acu = self._mk_kpi("Con ACU detallado", "0", TIPO_TEXTO['MO'])
        from utils.theme import accent_color as _acc
        self.kpi_usados = self._mk_kpi("Más reutilizado (usos)", "0", _acc())
        for k in (self.kpi_total, self.kpi_grupos, self.kpi_con_acu, self.kpi_usados):
            kpis.addWidget(k, 1)
        layout.addLayout(kpis)

        # ── Filtros ──
        filt = QFrame()
        filt.setStyleSheet(
            f"QFrame {{ background:white; border:1px solid {SILVER_300};"
            f"  border-radius:6px; }}"
        )
        fl = QHBoxLayout(filt)
        fl.setContentsMargins(10, 8, 10, 8)
        fl.setSpacing(8)

        ico_search = QLabel()
        ico_search.setPixmap(icon("buscar").pixmap(18, 18))
        ico_search.setFixedSize(20, 20)
        fl.addWidget(ico_search)

        self.inp_q = QLineEdit()
        self.inp_q.setPlaceholderText("Buscar costo unitario por descripción…")
        self.inp_q.setClearButtonEnabled(True)
        self._timer_q = QTimer(self)
        self._timer_q.setSingleShot(True)
        self._timer_q.timeout.connect(self.cargar)
        self.inp_q.textChanged.connect(lambda _: self._timer_q.start(250))
        fl.addWidget(self.inp_q, 2)

        self.cmb_grupo = QComboBox()
        self.cmb_grupo.setMinimumWidth(220)
        self.cmb_grupo.currentIndexChanged.connect(self.cargar)
        fl.addWidget(self.cmb_grupo)

        self.cmb_acu = QComboBox()
        self.cmb_acu.addItem("Todos", "")
        self.cmb_acu.addItem("Con ACU detallado", "con_acu")
        self.cmb_acu.addItem("Sin ACU detallado", "sin_acu")
        self.cmb_acu.currentIndexChanged.connect(self.cargar)
        fl.addWidget(self.cmb_acu)

        self.btn_limpiar = self._mk_btn("Limpiar", icon_name="limpiar")
        self.btn_limpiar.clicked.connect(self._limpiar_filtros)
        fl.addWidget(self.btn_limpiar)

        layout.addWidget(filt)

        # ── Splitter: tabla CU arriba + panel detalle abajo ──
        self.splitter = QSplitter(Qt.Vertical)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setStyleSheet(
            "QSplitter::handle { background: #D4D4D4; }"
            "QSplitter::handle:vertical { height: 1px; }"
            "QSplitter::handle:hover { background: #F37329; }"
        )

        # Tabla principal
        self.tbl = QTableWidget(0, 7)
        self.tbl.setHorizontalHeaderLabels(
            ["Descripción", "Unidad", "Rendimiento", "Costo Unit.", "Grupo", "ACU", "Usos"]
        )
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setAlternatingRowColors(True)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl.setSortingEnabled(True)
        self.tbl.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tbl.customContextMenuRequested.connect(self._menu_contextual)
        self.tbl.cellDoubleClicked.connect(self._on_double_click)
        self.tbl.itemSelectionChanged.connect(self._on_seleccion)
        self.tbl.setToolTip("Doble clic: editar  ·  Clic derecho: menú  ·  Selecciona para ver ACU")

        h = self.tbl.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        h.setSectionResizeMode(1, QHeaderView.Fixed); h.resizeSection(1, 70)
        h.setSectionResizeMode(2, QHeaderView.Fixed); h.resizeSection(2, 110)
        h.setSectionResizeMode(3, QHeaderView.Fixed); h.resizeSection(3, 110)
        h.setSectionResizeMode(4, QHeaderView.Fixed); h.resizeSection(4, 220)
        h.setSectionResizeMode(5, QHeaderView.Fixed); h.resizeSection(5, 60)
        h.setSectionResizeMode(6, QHeaderView.Fixed); h.resizeSection(6, 60)
        self.splitter.addWidget(self.tbl)

        # Panel inferior — detalle de ACU items del CU seleccionado
        self._panel_detalle = self._build_panel_detalle()
        self.splitter.addWidget(self._panel_detalle)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)
        self.splitter.setSizes([500, 280])
        layout.addWidget(self.splitter, 1)

        # Atajos
        QShortcut(QKeySequence("Ctrl+N"), self, activated=self._nuevo)
        QShortcut(QKeySequence("Delete"), self, activated=self._eliminar_seleccion)
        QShortcut(QKeySequence("F5"), self, activated=self.cargar)
        QShortcut(QKeySequence("Ctrl+F"), self, activated=lambda: self.inp_q.setFocus())

    def _build_panel_detalle(self) -> QFrame:
        fr = QFrame()
        fr.setStyleSheet(
            f"QFrame {{ background:white; border:1px solid {SILVER_300};"
            f"  border-top:none; }}"
        )
        v = QVBoxLayout(fr)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # Cabecera del panel
        hdr = QFrame()
        hdr.setStyleSheet(
            f"QFrame {{ background:{SILVER_200}; border-bottom:1px solid {SILVER_300}; }}"
        )
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(10, 6, 10, 6)
        hl.setSpacing(8)
        ico = QLabel()
        ico.setPixmap(icon("rep-acus").pixmap(16, 16))
        ico.setStyleSheet("background:transparent; border:none;")
        hl.addWidget(ico)

        self.lbl_panel_titulo = QLabel("Detalle ACU")
        self.lbl_panel_titulo.setStyleSheet(
            f"color:{SLATE_700}; font-weight:600; font-size:12px;"
            f" background:transparent; border:none;"
        )
        hl.addWidget(self.lbl_panel_titulo)

        self.lbl_panel_meta = QLabel("")
        self.lbl_panel_meta.setStyleSheet(f"color:{SLATE_300}; font-size:11px; background:transparent; border:none;")
        hl.addWidget(self.lbl_panel_meta)
        hl.addStretch(1)
        v.addWidget(hdr)

        # Stack: vacío | con datos | sin ACU
        self._stack_detalle = QStackedWidget()

        # Página 0 — empty (sin selección)
        empty = QLabel("Selecciona un CU en la tabla para ver su ACU.")
        empty.setAlignment(Qt.AlignCenter)
        empty.setStyleSheet(f"color:{SLATE_300}; padding:24px; font-style:italic;")
        self._stack_detalle.addWidget(empty)

        # Página 1 — con detalle
        self.tbl_acu = QTableWidget(0, 6)
        self.tbl_acu.setHorizontalHeaderLabels(
            ["Tipo", "Código", "Descripción", "Unidad", "Cuadrilla", "Cantidad"]
        )
        self.tbl_acu.verticalHeader().setVisible(False)
        self.tbl_acu.setAlternatingRowColors(True)
        self.tbl_acu.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl_acu.setSelectionBehavior(QAbstractItemView.SelectRows)
        ha = self.tbl_acu.horizontalHeader()
        ha.setSectionResizeMode(0, QHeaderView.Fixed); ha.resizeSection(0, 60)
        ha.setSectionResizeMode(1, QHeaderView.Fixed); ha.resizeSection(1, 100)
        ha.setSectionResizeMode(2, QHeaderView.Stretch)
        ha.setSectionResizeMode(3, QHeaderView.Fixed); ha.resizeSection(3, 70)
        ha.setSectionResizeMode(4, QHeaderView.Fixed); ha.resizeSection(4, 90)
        ha.setSectionResizeMode(5, QHeaderView.Fixed); ha.resizeSection(5, 100)
        self._stack_detalle.addWidget(self.tbl_acu)

        # Página 2 — sin ACU disponible
        no_acu = QLabel(
            "Este CU no tiene ACU detallado en la biblioteca.\n"
            "Solo guarda costo unitario, rendimiento y especificaciones."
        )
        no_acu.setAlignment(Qt.AlignCenter)
        no_acu.setWordWrap(True)
        no_acu.setStyleSheet(f"color:{SLATE_300}; padding:24px;")
        self._stack_detalle.addWidget(no_acu)

        v.addWidget(self._stack_detalle, 1)
        return fr

    def _mk_btn(self, text: str, primary: bool = False,
                icon_name: str | None = None) -> QPushButton:
        b = QPushButton(text)
        b.setCursor(Qt.PointingHandCursor)
        b.setMinimumHeight(32)
        if icon_name:
            b.setIcon(icon(icon_name))
            b.setIconSize(QSize(18, 18))
        if primary:
            b.setStyleSheet(
                f"QPushButton {{ background:{ORANGE_500}; color:white; border:none;"
                f"  border-radius:6px; padding:6px 14px; font-weight:600; }}"
                f"QPushButton:hover {{ background:{ORANGE_700}; }}"
            )
        return b

    def _mk_kpi(self, etiqueta: str, valor: str, color: str) -> QFrame:
        from utils.theme import apply_shadow
        card = QFrame()
        card.setObjectName("kpiCard")
        card.setAttribute(Qt.WA_StyledBackground, True)
        card.setStyleSheet(
            f"QFrame#kpiCard {{ background:white; border:1px solid {SILVER_300};"
            f"  border-radius:8px; }}"
        )
        apply_shadow(card, 'sm')
        v = QVBoxLayout(card)
        v.setContentsMargins(14, 10, 14, 10)
        v.setSpacing(2)
        l_e = QLabel(etiqueta)
        l_e.setStyleSheet(
            f"color:{SLATE_300}; font-size:11px; letter-spacing:0.4px; "
            f"background:transparent; border:none;"
        )
        l_v = QLabel(valor)
        f = QFont()
        f.setPointSize(14)
        f.setWeight(QFont.DemiBold)
        l_v.setFont(f)
        l_v.setStyleSheet(f"color:{color}; background:transparent; border:none;")
        v.addWidget(l_e)
        v.addWidget(l_v)
        card.lbl_etiqueta = l_e
        card.lbl_valor = l_v
        return card

    def _rid_at(self, row: int) -> int | None:
        if row < 0 or row >= self.tbl.rowCount():
            return None
        it = self.tbl.item(row, 0)
        v = it.data(Qt.UserRole) if it else None
        return int(v) if v is not None else None

    # ── carga y filtrado ────────────────────────────────────────────────────
    def cargar(self):
        # Refrescar combo grupo (sin perder selección)
        self._refrescar_combo_grupos()

        q = self.inp_q.text().strip().lower() if hasattr(self, 'inp_q') else ''
        grupo = self.cmb_grupo.currentData() if hasattr(self, 'cmb_grupo') else ''
        acu_filt = self.cmb_acu.currentData() if hasattr(self, 'cmb_acu') else ''

        sql = (
            "SELECT cu.id, cu.descripcion, cu.unidad, cu.rendimiento, "
            "       cu.costo_unitario, cu.grupo, cu.especificaciones, cu.usos, "
            "       (SELECT COUNT(*) FROM biblioteca_acu_items i "
            "        WHERE i.cu_id = cu.id) AS n_acu "
            "FROM biblioteca_cu cu WHERE 1=1"
        )
        params: list = []
        if q:
            sql += " AND LOWER(cu.descripcion) LIKE ?"
            params.append(f"%{q}%")
        if grupo:
            sql += " AND cu.grupo = ?"
            params.append(grupo)
        if acu_filt == 'con_acu':
            sql += " AND EXISTS (SELECT 1 FROM biblioteca_acu_items i WHERE i.cu_id=cu.id)"
        elif acu_filt == 'sin_acu':
            sql += " AND NOT EXISTS (SELECT 1 FROM biblioteca_acu_items i WHERE i.cu_id=cu.id)"
        sql += " ORDER BY cu.usos DESC, cu.descripcion LIMIT 1000"

        conn = get_db()
        rows = conn.execute(sql, params).fetchall()
        kpis = conn.execute(
            "SELECT COUNT(*) AS total, "
            "       COUNT(DISTINCT NULLIF(grupo,'')) AS n_grupos, "
            "       (SELECT COUNT(DISTINCT cu_id) FROM biblioteca_acu_items) AS n_con_acu, "
            "       MAX(usos) AS max_usos "
            "FROM biblioteca_cu"
        ).fetchone()
        conn.close()

        # Llenar tabla con la misma optimización que recursos_view
        col_muted = QColor(SLATE_300)
        font_pre = QFont(); font_pre.setWeight(QFont.DemiBold)
        align_center = Qt.AlignCenter
        align_right = Qt.AlignRight | Qt.AlignVCenter
        flag = Qt.ItemIsSelectable | Qt.ItemIsEnabled

        self.tbl.setUpdatesEnabled(False)
        self.tbl.blockSignals(True)
        try:
            self.tbl.setSortingEnabled(False)
            self.tbl.clearContents()
            self.tbl.setRowCount(len(rows))
            for row, r in enumerate(rows):
                desc = r['descripcion'] or ''
                desc_tooltip = (r['especificaciones'] or '')[:300]
                it_d = QTableWidgetItem(desc)
                it_d.setFlags(flag)
                it_d.setData(Qt.UserRole, r['id'])
                if desc_tooltip:
                    it_d.setToolTip(desc_tooltip)
                self.tbl.setItem(row, 0, it_d)

                it_u = QTableWidgetItem(r['unidad'] or '')
                it_u.setTextAlignment(align_center)
                it_u.setFlags(flag)
                self.tbl.setItem(row, 1, it_u)

                rend = float(r['rendimiento'] or 0)
                rend_txt = f"{rend:.4f}".rstrip('0').rstrip('.') or '0'
                it_r = QTableWidgetItem(rend_txt)
                it_r.setTextAlignment(align_right)
                it_r.setFlags(flag)
                self.tbl.setItem(row, 2, it_r)

                cu_val = float(r['costo_unitario'] or 0)
                it_c = QTableWidgetItem(fmt(cu_val))
                it_c.setTextAlignment(align_right)
                it_c.setFlags(flag)
                it_c.setFont(font_pre)
                self.tbl.setItem(row, 3, it_c)

                it_g = QTableWidgetItem(r['grupo'] or '—')
                it_g.setFlags(flag)
                if not r['grupo']:
                    it_g.setForeground(col_muted)
                self.tbl.setItem(row, 4, it_g)

                n_acu = r['n_acu'] or 0
                it_a = QTableWidgetItem(str(n_acu) if n_acu else '—')
                it_a.setTextAlignment(align_center)
                it_a.setFlags(flag)
                if n_acu == 0:
                    it_a.setForeground(col_muted)
                self.tbl.setItem(row, 5, it_a)

                usos = r['usos'] or 0
                it_us = QTableWidgetItem(str(usos) if usos else '—')
                it_us.setTextAlignment(align_center)
                it_us.setFlags(flag)
                if usos == 0:
                    it_us.setForeground(col_muted)
                self.tbl.setItem(row, 6, it_us)

            self.tbl.setSortingEnabled(True)
        finally:
            self.tbl.blockSignals(False)
            self.tbl.setUpdatesEnabled(True)

        # KPIs
        self.kpi_total.lbl_valor.setText(str(kpis['total'] or 0))
        self.kpi_grupos.lbl_valor.setText(str(kpis['n_grupos'] or 0))
        self.kpi_con_acu.lbl_valor.setText(str(kpis['n_con_acu'] or 0))
        self.kpi_usados.lbl_valor.setText(str(kpis['max_usos'] or 0))

        n_filt = len(rows)
        n_total = kpis['total'] or 0
        if n_filt == n_total:
            self.lbl_subt.setText(f"{n_total} CU")
        elif n_filt == 1000:
            self.lbl_subt.setText(f"primeros 1000 de {n_total} (filtra para afinar)")
        else:
            self.lbl_subt.setText(f"{n_filt} de {n_total} CU")

        # Resetear panel detalle
        self._cu_id_actual = None
        self._stack_detalle.setCurrentIndex(0)
        self.lbl_panel_titulo.setText("Detalle ACU")
        self.lbl_panel_meta.setText("")

    def _refrescar_combo_grupos(self):
        if not hasattr(self, 'cmb_grupo'):
            return
        actual = self.cmb_grupo.currentData() if self.cmb_grupo.count() else ''
        conn = get_db()
        rows = conn.execute(
            "SELECT DISTINCT grupo FROM biblioteca_cu "
            "WHERE grupo IS NOT NULL AND grupo!='' "
            "ORDER BY grupo"
        ).fetchall()
        conn.close()

        self.cmb_grupo.blockSignals(True)
        self.cmb_grupo.clear()
        self.cmb_grupo.addItem("Todos los grupos", "")
        idx_actual = 0
        for i, r in enumerate(rows, 1):
            self.cmb_grupo.addItem(r['grupo'], r['grupo'])
            if r['grupo'] == actual:
                idx_actual = i
        self.cmb_grupo.setCurrentIndex(idx_actual)
        self.cmb_grupo.blockSignals(False)

    # ── selección y panel detalle ───────────────────────────────────────────
    def _on_seleccion(self):
        rows = sorted({i.row() for i in self.tbl.selectedIndexes()})
        if not rows:
            return
        cu_id = self._rid_at(rows[0])
        if cu_id == self._cu_id_actual:
            return
        self._cu_id_actual = cu_id
        self._cargar_detalle(cu_id)

    def _cargar_detalle(self, cu_id: int | None):
        if cu_id is None:
            self._stack_detalle.setCurrentIndex(0)
            self.lbl_panel_titulo.setText("Detalle ACU")
            self.lbl_panel_meta.setText("")
            return
        conn = get_db()
        cu = conn.execute(
            "SELECT descripcion, unidad, costo_unitario, rendimiento "
            "FROM biblioteca_cu WHERE id=?", (cu_id,)
        ).fetchone()
        items = conn.execute(
            """SELECT i.cuadrilla, i.cantidad,
                      r.codigo, r.descripcion, r.tipo, r.unidad
               FROM biblioteca_acu_items i
               JOIN recursos r ON r.id = i.recurso_id
               WHERE i.cu_id = ?
               ORDER BY CASE r.tipo WHEN 'MO' THEN 1 WHEN 'MAT' THEN 2 ELSE 3 END,
                        r.descripcion""",
            (cu_id,)
        ).fetchall()
        conn.close()

        if not cu:
            self._stack_detalle.setCurrentIndex(0)
            return

        rend = float(cu['rendimiento'] or 1)
        rend_txt = f"{rend:.4f}".rstrip('0').rstrip('.') or '1'
        self.lbl_panel_titulo.setText(cu['descripcion'])
        self.lbl_panel_meta.setText(
            f"  ·  {cu['unidad'] or '?'}  ·  Rend.: {rend_txt}  ·  CU: {fmt(cu['costo_unitario'] or 0)}"
        )

        if not items:
            self._stack_detalle.setCurrentIndex(2)
            return

        # Llenar tabla detalle
        self.tbl_acu.setRowCount(0)
        flag = Qt.ItemIsSelectable | Qt.ItemIsEnabled
        for r in items:
            row = self.tbl_acu.rowCount()
            self.tbl_acu.insertRow(row)

            t = (r['tipo'] or '').strip()
            it_t = QTableWidgetItem(t)
            it_t.setTextAlignment(Qt.AlignCenter)
            it_t.setFlags(flag)
            if t in TIPO_FONDO:
                it_t.setBackground(QColor(TIPO_FONDO[t]))
                it_t.setForeground(QColor(TIPO_TEXTO[t]))
                f = QFont(); f.setBold(True); f.setPointSize(10)
                it_t.setFont(f)
            self.tbl_acu.setItem(row, 0, it_t)

            it_c = QTableWidgetItem(r['codigo'] or '—')
            it_c.setFlags(flag)
            self.tbl_acu.setItem(row, 1, it_c)

            it_d = QTableWidgetItem(r['descripcion'] or '')
            it_d.setFlags(flag)
            self.tbl_acu.setItem(row, 2, it_d)

            it_u = QTableWidgetItem(r['unidad'] or '')
            it_u.setTextAlignment(Qt.AlignCenter)
            it_u.setFlags(flag)
            self.tbl_acu.setItem(row, 3, it_u)

            cu_v = float(r['cuadrilla'] or 0)
            cant_v = float(r['cantidad'] or 0)
            it_q = QTableWidgetItem(f"{cu_v:g}" if cu_v else "—")
            it_q.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            it_q.setFlags(flag)
            self.tbl_acu.setItem(row, 4, it_q)

            it_n = QTableWidgetItem(f"{cant_v:.4f}".rstrip('0').rstrip('.') or '0')
            it_n.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            it_n.setFlags(flag)
            self.tbl_acu.setItem(row, 5, it_n)

        self._stack_detalle.setCurrentIndex(1)

    # ── CRUD ────────────────────────────────────────────────────────────────
    def _nuevo(self):
        dlg = CUFormDialog(self)
        if dlg.exec() == QDialog.Accepted:
            self.cargar()

    def _editar_id(self, cu_id: int):
        conn = get_db()
        r = conn.execute(
            "SELECT id, descripcion, unidad, rendimiento, costo_unitario, "
            "       grupo, especificaciones FROM biblioteca_cu WHERE id=?",
            (cu_id,)
        ).fetchone()
        conn.close()
        if not r:
            return
        dlg = CUFormDialog(self, cu=dict(r))
        if dlg.exec() == QDialog.Accepted:
            self.cargar()

    def _duplicar_id(self, cu_id: int):
        conn = get_db()
        r = conn.execute(
            "SELECT descripcion, unidad, rendimiento, costo_unitario, grupo, "
            "       especificaciones FROM biblioteca_cu WHERE id=?", (cu_id,)
        ).fetchone()
        if not r:
            conn.close()
            return
        cur = conn.execute(
            "INSERT INTO biblioteca_cu "
            "(descripcion, unidad, rendimiento, costo_unitario, grupo, especificaciones, usos) "
            "VALUES (?,?,?,?,?,?,0)",
            (r['descripcion'] + " (copia)", r['unidad'], r['rendimiento'],
             r['costo_unitario'], r['grupo'], r['especificaciones'])
        )
        new_id = cur.lastrowid
        # Duplicar también los items ACU si los tiene
        items = conn.execute(
            "SELECT recurso_id, cuadrilla, cantidad FROM biblioteca_acu_items "
            "WHERE cu_id=?", (cu_id,)
        ).fetchall()
        for it in items:
            conn.execute(
                "INSERT INTO biblioteca_acu_items (cu_id, recurso_id, cuadrilla, cantidad) "
                "VALUES (?,?,?,?)",
                (new_id, it['recurso_id'], it['cuadrilla'], it['cantidad'])
            )
        conn.commit()
        conn.close()
        self.cargar()

    def _eliminar_id(self, cu_id: int):
        self._eliminar_ids([cu_id])

    def _eliminar_seleccion(self):
        rows = sorted({i.row() for i in self.tbl.selectedIndexes()})
        ids = [self._rid_at(r) for r in rows]
        ids = [i for i in ids if i is not None]
        if ids:
            self._eliminar_ids(ids)

    def _eliminar_ids(self, ids: list[int]):
        if not ids:
            return
        n = len(ids)
        msg = (f"¿Eliminar {n} CU de la biblioteca?" if n > 1
               else "¿Eliminar este CU de la biblioteca?")
        res = QMessageBox.question(
            self, "Confirmar eliminación",
            msg + "\nEsta acción no se puede deshacer.",
            QMessageBox.Yes | QMessageBox.No
        )
        if res != QMessageBox.Yes:
            return
        conn = get_db()
        try:
            placeholders = ','.join('?' * len(ids))
            # ON DELETE CASCADE en biblioteca_acu_items.cu_id
            conn.execute(f"DELETE FROM biblioteca_cu WHERE id IN ({placeholders})", ids)
            conn.commit()
        finally:
            conn.close()
        self.cargar()

    def _on_double_click(self, row: int, _col: int):
        cu_id = self._rid_at(row)
        if cu_id is not None:
            self._editar_id(cu_id)

    # ── menú contextual ────────────────────────────────────────────────────
    def _menu_contextual(self, pos):
        idx = self.tbl.indexAt(pos)
        if not idx.isValid():
            return
        cu_id = self._rid_at(idx.row())
        if cu_id is None:
            return
        seleccion = sorted({i.row() for i in self.tbl.selectedIndexes()})
        ids_sel = [self._rid_at(r) for r in seleccion]
        ids_sel = [i for i in ids_sel if i is not None]

        m = QMenu(self)
        a_edit = QAction(icon("editar"), "Editar", self)
        a_edit.triggered.connect(lambda: self._editar_id(cu_id))
        m.addAction(a_edit)
        a_dup = QAction(icon("duplicar"), "Duplicar", self)
        a_dup.triggered.connect(lambda: self._duplicar_id(cu_id))
        m.addAction(a_dup)
        m.addSeparator()
        if len(ids_sel) > 1:
            a_del = QAction(icon("eliminar"),
                            f"Eliminar {len(ids_sel)} seleccionados", self)
            a_del.triggered.connect(lambda: self._eliminar_ids(ids_sel))
        else:
            a_del = QAction(icon("eliminar"), "Eliminar", self)
            a_del.triggered.connect(lambda: self._eliminar_id(cu_id))
        m.addAction(a_del)
        m.exec(self.tbl.viewport().mapToGlobal(pos))

    # ── filtros ────────────────────────────────────────────────────────────
    def _limpiar_filtros(self):
        self.inp_q.blockSignals(True)
        self.inp_q.clear()
        self.inp_q.blockSignals(False)
        self.cmb_grupo.setCurrentIndex(0)
        self.cmb_acu.setCurrentIndex(0)
        self.cargar()

    # ── Import / Export JSON ───────────────────────────────────────────────
    def _exportar_json(self):
        from datetime import datetime as _dt
        from core.catalogos_json import exportar_biblioteca_json
        from PySide6.QtWidgets import QFileDialog
        fecha = _dt.now().strftime("%Y%m%d_%H%M")
        sugerido = f"biblioteca_cu_{fecha}.json"
        path, _ = QFileDialog.getSaveFileName(
            self, "Exportar Biblioteca CU a JSON", sugerido, "JSON (*.json)"
        )
        if not path:
            return
        if not path.lower().endswith(".json"):
            path += ".json"
        try:
            n = exportar_biblioteca_json(path)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo exportar:\n{e}")
            return
        QMessageBox.information(
            self, "Exportado",
            f"{n} costos unitarios exportados a:\n{path}\n\n"
            f"El archivo incluye los ACU items con su recurso "
            f"identificado por código (no por id local), por lo que se "
            f"puede importar en otra instalación."
        )

    def _importar_json(self):
        from core.catalogos_json import importar_biblioteca_json
        from PySide6.QtWidgets import QFileDialog, QMessageBox as _QMB
        path, _ = QFileDialog.getOpenFileName(
            self, "Importar Biblioteca CU desde JSON", "", "JSON (*.json)"
        )
        if not path:
            return

        # Preguntar modo
        msg = (
            "¿Cómo manejar los CU que ya existen en tu biblioteca?\n\n"
            "Un CU se considera existente si coincide en\n"
            "(descripción · unidad · grupo).\n\n"
            "• Sí (Merge): reemplaza el CU + sus ACU items con los del JSON\n"
            "• No (Solo nuevos): ignora los existentes, solo agrega los nuevos"
        )
        res = _QMB.question(
            self, "Modo de importación", msg,
            _QMB.Yes | _QMB.No | _QMB.Cancel
        )
        if res == _QMB.Cancel:
            return
        modo = 'merge' if res == _QMB.Yes else 'solo_nuevos'

        try:
            r = importar_biblioteca_json(path, modo=modo)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo importar:\n{e}")
            return
        if not r['ok']:
            QMessageBox.warning(self, "Importar", r.get('msg'))
            return
        self.cargar()
        QMessageBox.information(
            self, "Importación completa",
            f"{r['msg']}\nTotal CU en archivo: {r['n_total']}"
        )

    def _importar_delphin_sqlite(self):
        from PySide6.QtWidgets import QFileDialog, QMessageBox as _QMB
        path, _ = QFileDialog.getOpenFileName(
            self, "Importar Biblioteca CU desde Delphin Express",
            "", "Bases de datos Delphin (*.sqlite *.db)"
        )
        if not path:
            return

        # Preguntar modo (igual que JSON)
        msg = (
            "¿Cómo manejar los CU que ya existen en tu biblioteca?\n\n"
            "Un CU se considera existente si coincide en\n"
            "(descripción · unidad · grupo).\n\n"
            "• Sí (Merge): reemplaza el CU + sus ACU items con los de Delphin.\n"
            "• No (Solo nuevos): ignora los existentes, solo agrega los nuevos.\n\n"
            "La biblioteca de Delphin contiene los ACU plantilla del programa, "
            "no los del proyecto activo (esos se importan en 'Importar' → "
            "'Delphin Base de datos')."
        )
        res = _QMB.question(
            self, "Modo de importación", msg,
            _QMB.Yes | _QMB.No | _QMB.Cancel
        )
        if res == _QMB.Cancel:
            return
        modo = 'merge' if res == _QMB.Yes else 'solo_nuevos'

        try:
            from core.delphin_sqlite_importer import import_biblioteca_delphin_sqlite
            r = import_biblioteca_delphin_sqlite(path, modo=modo)
        except Exception as e:
            QMessageBox.critical(
                self, "Error",
                f"No se pudo importar la biblioteca:\n\n{e}"
            )
            return
        if not r['ok']:
            QMessageBox.warning(self, "Importar", r.get('msg'))
            return
        self.cargar()
        QMessageBox.information(
            self, "Importación completa",
            f"Biblioteca importada desde Delphin.\n\n"
            f"  ACU origen:        {r['n_acs_origen']}\n"
            f"  Creados:           {r['n_creados']}\n"
            f"  Actualizados:      {r['n_actualizados']}\n"
            f"  Ignorados:         {r['n_ignorados']}\n\n"
            f"  Items ACU insertados:  {r['n_items']}\n"
            f"  Recursos nuevos:       {r['n_recursos_creados']}"
        )
