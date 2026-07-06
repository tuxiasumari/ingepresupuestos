# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""Diálogo para agregar partidas al presupuesto.

2 tabs:
  1. Desde Biblioteca  — búsqueda + selección múltiple con checkboxes
  2. Ingreso Manual    — formulario con autocompletado desde biblioteca

Tema: Elementary OS (Blueberry, Slate, tipografía Ubuntu Sans).
"""
import sqlite3
import re as _re
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QFrame, QScrollArea, QWidget, QCheckBox,
    QComboBox, QFormLayout, QSizePolicy, QDoubleSpinBox,
    QCompleter, QMessageBox, QApplication, QSplitter
)
from PySide6.QtCore import Qt, Signal, QTimer, QStringListModel, QSortFilterProxyModel
from PySide6.QtGui import QFont, QColor, QCursor

from core.database import get_db, _recalcular_pu
from utils.formatting import fmt

# ── Paleta ────────────────────────────────────────────────────────────────────
BLUE_500  = "#F37329"
BLUE_700  = "#C0621A"
SLATE_700 = "#273445"
SLATE_500 = "#485A6C"
SLATE_300 = "#667885"
SLATE_100 = "#95A3AB"
SILVER_100 = "#F8F9FA"
SILVER_300 = "#D4D4D4"
GREEN_500 = "#68B723"
RED_500   = "#C6262E"


# ── Tab bar personalizado ─────────────────────────────────────────────────────

class _TabBar(QFrame):
    changed = Signal(int)

    def __init__(self, labels: list[str], parent=None):
        super().__init__(parent)
        self.setFixedHeight(42)
        self.setStyleSheet(f"background:white; border-bottom:1px solid {SILVER_300};")
        self._btns: list[QPushButton] = []
        hl = QHBoxLayout(self)
        hl.setContentsMargins(16, 0, 16, 0)
        hl.setSpacing(0)
        for i, lbl in enumerate(labels):
            btn = QPushButton(lbl)
            btn.setCheckable(True)
            btn.setFixedHeight(42)
            btn.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            btn.setStyleSheet(self._style(False))
            btn.clicked.connect(lambda _, idx=i: self._select(idx))
            hl.addWidget(btn)
            self._btns.append(btn)
        hl.addStretch()
        self._select(0)

    def _style(self, active: bool) -> str:
        if active:
            return (
                f"QPushButton {{ color:{BLUE_500}; font-size:12px; font-weight:700;"
                f" border:none; border-bottom:2px solid {BLUE_500}; background:white;"
                f" padding:0 18px; }}"
            )
        return (
            "QPushButton { color:#667885; font-size:12px; font-weight:600;"
            " border:none; border-bottom:2px solid transparent; background:white;"
            " padding:0 18px; }"
            "QPushButton:hover { color:#273445; }"
        )

    def _select(self, idx: int):
        for i, btn in enumerate(self._btns):
            btn.setChecked(i == idx)
            btn.setStyleSheet(self._style(i == idx))
        self.changed.emit(idx)

    def select(self, idx: int):
        self._select(idx)


# ── Fila de ítem de biblioteca ────────────────────────────────────────────────

class _BibliotecaRow(QFrame):
    toggled = Signal(int, bool)   # (cu_id, checked) → marcar para agregar
    clicked = Signal(int)         # (cu_id)          → previsualizar ACU

    def __init__(self, cu: dict, parent=None):
        super().__init__(parent)
        self.cu_id = cu['id']
        self._focused = False
        self._restyle()
        self.setFixedHeight(52)
        self.setCursor(QCursor(Qt.PointingHandCursor))

        hl = QHBoxLayout(self)
        hl.setContentsMargins(12, 4, 12, 4)
        hl.setSpacing(10)

        self.chk = QCheckBox()
        self.chk.setFixedSize(18, 18)
        # Usar toggled(bool) en lugar de stateChanged(int) — más fiable en PySide6
        self.chk.toggled.connect(
            lambda checked: self.toggled.emit(self.cu_id, checked)
        )
        hl.addWidget(self.chk)

        vl = QVBoxLayout()
        vl.setSpacing(2)
        lbl_desc = QLabel(cu['descripcion'] or "—")
        lbl_desc.setStyleSheet(f"color:{SLATE_700}; font-size:12px; font-weight:600; border:none;")
        lbl_desc.setWordWrap(False)

        grupo  = cu.get('grupo') or ""
        unidad = cu.get('unidad') or ""
        precio = cu.get('costo_unitario') or 0
        lbl_meta = QLabel(
            f"{grupo}  ·  {fmt(precio, 'Soles')} / {unidad}" if grupo
            else f"{fmt(precio, 'Soles')} / {unidad}"
        )
        lbl_meta.setStyleSheet(f"color:{SLATE_100}; font-size:10px; border:none;")

        vl.addWidget(lbl_desc)
        vl.addWidget(lbl_meta)
        hl.addLayout(vl, stretch=1)

    def _restyle(self):
        bg = '#FEF0E6' if self._focused else 'white'
        borde = (f"border-left:3px solid {BLUE_500};" if self._focused
                 else "border-left:3px solid transparent;")
        self.setStyleSheet(
            f"QFrame {{ border:none; border-bottom:1px solid {SILVER_100};"
            f" {borde} background:{bg}; }}"
            f"QFrame:hover {{ background:#F5F8FF; }}"
        )

    def set_focused(self, v: bool):
        if v != self._focused:
            self._focused = v
            self._restyle()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            # Clic en el cuerpo (no en la casilla) → previsualizar el ACU.
            # La casilla queda solo para marcar la partida a agregar.
            child = self.childAt(event.position().toPoint())
            if child is not self.chk:
                self.clicked.emit(self.cu_id)

    def is_checked(self) -> bool:
        return self.chk.isChecked()

    def set_checked(self, v: bool):
        self.chk.setChecked(v)


# ═══════════════════════════════════════════════════════════════════════════════
class AgregarPartidaDialog(QDialog):
# ═══════════════════════════════════════════════════════════════════════════════

    partidas_agregadas = Signal()   # emitida tras agregar ítems

    # tab_inicial: 0=Biblioteca, 1=Manual
    # contexto_item: ítem seleccionado en el árbol (ej. "01.02") o None
    def __init__(self, proyecto_id: int, usuario,
                 tab_inicial: int = 0,
                 contexto_item: str | None = None,
                 contexto_es_titulo: bool = False,
                 sub_presupuesto_id: int | None = None,
                 parent=None):
        super().__init__(parent)
        self.pid                  = proyecto_id
        self.usuario              = usuario
        self._contexto_item       = contexto_item        # código del ítem seleccionado
        self._contexto_es_titulo  = contexto_es_titulo   # True si es título/sección
        self._sub_ppto_id         = sub_presupuesto_id
        self._cu_rows: list[_BibliotecaRow] = []
        self._seleccionados: set[int] = set()   # cu_ids seleccionados
        self._grupo_proyecto      = self._leer_grupo_proyecto()

        from utils.i18n import tr
        self._tr = tr
        self.setWindowTitle(tr("Agregar partida"))
        self.setMinimumSize(900, 540)
        self.resize(1060, 620)
        self.setModal(True)
        self.setStyleSheet("QDialog { background: white; }")

        self._build_ui()
        self._cargar_grupos()
        self._tabs.select(tab_inicial)

    def _leer_grupo_proyecto(self) -> str:
        try:
            conn = get_db()
            row  = conn.execute(
                "SELECT grupo_analisis FROM proyectos WHERE id=?", (self.pid,)
            ).fetchone()
            conn.close()
            return (row['grupo_analisis'] or '').strip() if row else ''
        except Exception:
            return ''

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._make_header())
        self._tabs = _TabBar([f"☰  {self._tr('Biblioteca')}", f"✎  {self._tr('Manual')}"])
        self._tabs.changed.connect(self._on_tab)
        root.addWidget(self._tabs)

        # Área de contenido (stack)
        from PySide6.QtWidgets import QStackedWidget
        self._stack = QStackedWidget()
        self._stack.addWidget(self._tab_biblioteca())
        self._stack.addWidget(self._tab_manual())
        root.addWidget(self._stack, stretch=1)

        root.addWidget(self._make_footer())

    def _make_header(self) -> QFrame:
        hdr = QFrame()
        hdr.setFixedHeight(44)
        hdr.setStyleSheet(f"background:{SLATE_700};")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(16, 0, 12, 0)
        lbl = QLabel(self._tr("Agregar partida"))
        lbl.setStyleSheet("color:white; font-size:13px; font-weight:700; border:none;")
        hl.addWidget(lbl)
        hl.addStretch()
        btn_x = QPushButton("✕")
        btn_x.setFixedSize(28, 28)
        btn_x.setStyleSheet(
            "QPushButton { background:transparent; color:#95A3AB; border:none; font-size:14px; }"
            "QPushButton:hover { color:white; }"
        )
        btn_x.clicked.connect(self.reject)
        hl.addWidget(btn_x)
        return hdr

    # ── Tab 1: Desde Biblioteca ───────────────────────────────────────────────

    def _tab_biblioteca(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background:white;")
        vl = QVBoxLayout(w)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)

        # ── Zona de búsqueda (fondo gris suave, bien visible) ─────────────────
        zona_busq = QFrame()
        zona_busq.setStyleSheet(
            f"background:{SILVER_100}; border-bottom:1px solid {SILVER_300};"
        )
        vb = QVBoxLayout(zona_busq)
        vb.setContentsMargins(14, 10, 14, 10)
        vb.setSpacing(8)

        # Fila 1: campo búsqueda grande
        self.inp_bib = QLineEdit()
        self.inp_bib.setPlaceholderText(self._tr("Buscar") + "…")
        self.inp_bib.setFixedHeight(38)
        self.inp_bib.setStyleSheet(
            f"QLineEdit {{"
            f"  border:1.5px solid {BLUE_500}; border-radius:8px;"
            f"  padding:0 14px; font-size:13px; color:{SLATE_700};"
            f"  background:white;"
            f"}}"
            f"QLineEdit:focus {{ border-color:{BLUE_700}; }}"
        )
        self.inp_bib.textChanged.connect(self._debounce_buscar)
        vb.addWidget(self.inp_bib)

        # Fila 2: grupo dropdown + contador
        hl2 = QHBoxLayout()
        hl2.setSpacing(8)
        lbl_g = QLabel(self._tr("Grupo") + ":")
        lbl_g.setStyleSheet(f"color:{SLATE_300}; font-size:11px; border:none;")
        hl2.addWidget(lbl_g)

        self.cmb_grupo = QComboBox()
        self.cmb_grupo.setFixedHeight(26)
        self.cmb_grupo.setStyleSheet(
            f"border:1px solid {SILVER_300}; border-radius:6px;"
            f" padding:0 8px; font-size:11px; background:white;"
        )
        self.cmb_grupo.currentIndexChanged.connect(self._buscar_biblioteca)
        hl2.addWidget(self.cmb_grupo, stretch=1)

        self.lbl_sel = QLabel("")
        self.lbl_sel.setStyleSheet(
            f"color:{BLUE_500}; font-size:11px; font-weight:700; border:none;"
        )
        hl2.addWidget(self.lbl_sel)
        vb.addLayout(hl2)

        vl.addWidget(zona_busq)

        # ── Lista de resultados ───────────────────────────────────────────────
        self._scroll_bib = QScrollArea()
        self._scroll_bib.setWidgetResizable(True)
        self._scroll_bib.setFrameShape(QFrame.NoFrame)
        self._scroll_bib.setStyleSheet(
            "QScrollArea { background:white; border:none; }"
            "QScrollBar:vertical { width:6px; background:transparent; }"
            "QScrollBar::handle:vertical { background:#ABACAE; border-radius:4px; }"
        )

        self._lista_bib = QWidget()
        self._lista_bib.setStyleSheet("background:white;")
        self._lista_layout = QVBoxLayout(self._lista_bib)
        self._lista_layout.setContentsMargins(0, 0, 0, 0)
        self._lista_layout.setSpacing(0)
        self._lista_layout.addStretch()
        self._scroll_bib.setWidget(self._lista_bib)

        # ── Panel lateral de previsualización del ACU ─────────────────────────
        self._preview_panel = self._build_preview_panel()

        split = QSplitter(Qt.Horizontal)
        split.setHandleWidth(1)
        split.setStyleSheet(f"QSplitter::handle {{ background:{SILVER_300}; }}")
        split.addWidget(self._scroll_bib)
        split.addWidget(self._preview_panel)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        split.setSizes([560, 420])
        vl.addWidget(split, stretch=1)

        # Placeholder (se muestra hasta que haya resultados)
        self._lbl_placeholder = QLabel("Cargando…")
        self._lbl_placeholder.setAlignment(Qt.AlignCenter)
        self._lbl_placeholder.setStyleSheet(
            f"color:{SLATE_100}; font-size:13px; padding:40px; border:none;"
        )
        self._lista_layout.insertWidget(0, self._lbl_placeholder)

        # Debounce timer
        self._bib_timer = QTimer(self)
        self._bib_timer.setSingleShot(True)
        self._bib_timer.setInterval(280)
        self._bib_timer.timeout.connect(self._buscar_biblioteca)

        # Cargar los primeros 80 registros al abrir
        QTimer.singleShot(50, self._buscar_biblioteca)

        return w

    # ── Tab 2: Ingreso Manual ─────────────────────────────────────────────────

    # Unidades más frecuentes en presupuestos de obra pública
    UNIDADES = [
        "m²", "m³", "m", "ml", "km",
        "und", "pza", "pzas", "jgo", "glb", "gbl",
        "kg", "tn", "ton",
        "pto", "cjt", "est",
        "día", "h", "hr", "mes",
        "l", "gal", "lt",
        "ha", "pie²", "pie³",
        "vj", "rll",
    ]

    def _tab_manual(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background:white;")
        vl = QVBoxLayout(w)
        vl.setContentsMargins(28, 20, 28, 12)
        vl.setSpacing(12)

        # Popup styling cubierto por `install_global_popup_styles(app)`.
        CMB_STYLE = (
            f"QComboBox {{ border:1px solid {SILVER_300}; border-radius:8px;"
            f" padding:0 12px; font-size:13px; color:{SLATE_700}; background:white; }}"
            f"QComboBox:focus {{ border-color:{BLUE_500}; }}"
            f"QComboBox::drop-down {{ border:none; width:28px; }}"
        )

        # ── Descripción ───────────────────────────────────────────────────────
        vl.addWidget(self._lbl_campo("Descripción de la partida  *"))
        self.inp_m_desc = QLineEdit()
        self.inp_m_desc.setPlaceholderText(
            self._tr("Descripción")
        )
        self.inp_m_desc.setMinimumHeight(42)
        self.inp_m_desc.setStyleSheet(
            f"QLineEdit {{ border:1.5px solid {BLUE_500}; border-radius:8px;"
            f" padding:0 14px; font-size:13px; color:{SLATE_700}; background:white; }}"
            f"QLineEdit:focus {{ border-color:{BLUE_700}; }}"
        )
        # Manual = entrada nueva sin sugerencias (la búsqueda en biblioteca es
        # el otro tab). Sin autocompletado redundante.
        self._cu_match_id = None
        vl.addWidget(self.inp_m_desc)

        # ── Fila: Unidad + Grupo ──────────────────────────────────────────────
        fila = QHBoxLayout()
        fila.setSpacing(16)

        # Unidad — combobox con filtro mientras se escribe
        col_u = QVBoxLayout(); col_u.setSpacing(4)
        col_u.addWidget(self._lbl_campo("Unidad de medida"))
        self.cmb_m_unidad = QComboBox()
        self.cmb_m_unidad.setEditable(True)
        self.cmb_m_unidad.setInsertPolicy(QComboBox.NoInsert)
        self.cmb_m_unidad.setMinimumHeight(38)
        self.cmb_m_unidad.setMinimumWidth(120)
        self.cmb_m_unidad.setStyleSheet(CMB_STYLE)
        for u in self.UNIDADES:
            self.cmb_m_unidad.addItem(u)
        # Completador que filtra mientras se escribe (MatchContains)
        comp_u = QCompleter(self.UNIDADES)
        comp_u.setCaseSensitivity(Qt.CaseInsensitive)
        comp_u.setFilterMode(Qt.MatchContains)
        comp_u.setCompletionMode(QCompleter.PopupCompletion)
        comp_u.popup().setStyleSheet(
            f"QListView {{ border:1px solid {SILVER_300}; border-radius:6px;"
            f" font-size:13px; padding:4px; background:white; }}"
            f"QListView::item:selected {{ background:#FEF5EB; color:{BLUE_700}; }}"
        )
        self.cmb_m_unidad.setCompleter(comp_u)

        # Auto-convertir "m2"→"m²", "m3"→"m³"
        _SUP = {'2': '²', '3': '³'}
        def _auto_sup_u(text):
            m = _re.match(r'^([a-zA-Z/]+)([23])$', text)
            if m:
                nuevo = m.group(1) + _SUP[m.group(2)]
                QTimer.singleShot(0, lambda: self.cmb_m_unidad.setEditText(nuevo))
        self.cmb_m_unidad.lineEdit().textEdited.connect(_auto_sup_u)

        col_u.addWidget(self.cmb_m_unidad)
        fila.addLayout(col_u, stretch=1)

        # Grupo — combobox editable con grupos del proyecto y biblioteca
        col_g = QVBoxLayout(); col_g.setSpacing(4)
        col_g.addWidget(self._lbl_campo("Grupo  (opcional)"))
        self.cmb_m_grupo = QComboBox()
        self.cmb_m_grupo.setEditable(True)
        self.cmb_m_grupo.setInsertPolicy(QComboBox.NoInsert)
        self.cmb_m_grupo.setMinimumHeight(38)
        self.cmb_m_grupo.setStyleSheet(CMB_STYLE)
        self.cmb_m_grupo.addItem("")   # opción vacía
        self._cargar_grupos_manual()
        comp_g = QCompleter(self._grupos_manual_lista)
        comp_g.setCaseSensitivity(Qt.CaseInsensitive)
        comp_g.setFilterMode(Qt.MatchContains)
        comp_g.setCompletionMode(QCompleter.PopupCompletion)
        comp_g.popup().setStyleSheet(
            f"QListView {{ border:1px solid {SILVER_300}; border-radius:6px;"
            f" font-size:13px; padding:4px; background:white; color:{SLATE_700}; }}"
            f"QListView::item:selected {{ background:#FEF5EB; color:{BLUE_700}; }}"
        )
        self.cmb_m_grupo.setCompleter(comp_g)
        col_g.addWidget(self.cmb_m_grupo)
        fila.addLayout(col_g, stretch=2)

        vl.addLayout(fila)
        vl.addStretch()

        # ── Botón agregar ─────────────────────────────────────────────────────
        btn_ag = QPushButton("  " + self._tr("Agregar partida"))
        btn_ag.setFixedHeight(40)
        btn_ag.setMaximumWidth(200)
        btn_ag.setStyleSheet(
            f"QPushButton {{ background:{BLUE_500}; color:white; border:none;"
            f" border-radius:8px; font-size:13px; font-weight:700; padding:0 20px; }}"
            f"QPushButton:hover {{ background:{BLUE_700}; }}"
        )
        btn_ag.clicked.connect(self._agregar_manual)
        vl.addWidget(btn_ag, alignment=Qt.AlignLeft)

        self.lbl_m_error = QLabel("")
        self.lbl_m_error.setStyleSheet(f"color:{RED_500}; font-size:11px; border:none;")
        vl.addWidget(self.lbl_m_error)

        return w

    def _lbl_campo(self, texto: str) -> QLabel:
        lbl = QLabel(texto)
        lbl.setStyleSheet(
            f"color:{SLATE_500}; font-size:12px; font-weight:600; border:none;"
        )
        return lbl

    def _cargar_grupos_manual(self):
        """Carga grupos: grupo_analisis del proyecto primero, luego partidas + biblioteca."""
        grupos = set()
        try:
            conn = get_db()
            for r in conn.execute(
                "SELECT DISTINCT grupo FROM partidas WHERE proyecto_id=? AND grupo IS NOT NULL AND grupo!=''",
                (self.pid,)
            ).fetchall():
                grupos.add(r[0])
            for r in conn.execute(
                "SELECT DISTINCT grupo FROM biblioteca_cu WHERE grupo IS NOT NULL AND grupo!='' ORDER BY grupo LIMIT 100"
            ).fetchall():
                grupos.add(r[0])
            conn.close()
        except Exception:
            pass

        # grupo_analisis del proyecto va primero y excluido del resto para no duplicar
        gp = self._grupo_proyecto
        if gp:
            grupos.discard(gp)
        self._grupos_manual_lista = ([gp] if gp else []) + sorted(grupos)

        for g in self._grupos_manual_lista:
            self.cmb_m_grupo.addItem(g)

        # Preseleccionar el grupo del proyecto
        if gp:
            self.cmb_m_grupo.setCurrentText(gp)


    # ── Footer ────────────────────────────────────────────────────────────────

    def _make_footer(self) -> QFrame:
        footer = QFrame()
        footer.setFixedHeight(52)
        footer.setStyleSheet(
            f"background:{SILVER_100}; border-top:1px solid {SILVER_300};"
        )
        hl = QHBoxLayout(footer)
        hl.setContentsMargins(16, 0, 16, 0)
        hl.setSpacing(8)
        hl.addStretch()

        self.btn_agregar_bib = QPushButton(self._tr("Agregar"))
        self.btn_agregar_bib.setFixedHeight(34)
        self.btn_agregar_bib.setStyleSheet(
            f"QPushButton {{ background:{BLUE_500}; color:white; border:none;"
            f" border-radius:8px; font-size:12px; font-weight:700; padding:0 18px; }}"
            f"QPushButton:hover {{ background:{BLUE_700}; }}"
            f"QPushButton:disabled {{ background:{SILVER_300}; color:{SLATE_100}; }}"
        )
        self.btn_agregar_bib.clicked.connect(self._agregar_desde_biblioteca)
        hl.addWidget(self.btn_agregar_bib)

        btn_cancel = QPushButton(self._tr("Cancelar"))
        btn_cancel.setFixedHeight(34)
        btn_cancel.setStyleSheet(
            f"QPushButton {{ background:white; color:{SLATE_500}; border:1px solid {SILVER_300};"
            f" border-radius:8px; font-size:12px; font-weight:600; padding:0 16px; }}"
            f"QPushButton:hover {{ border-color:{BLUE_500}; color:{BLUE_700}; }}"
        )
        btn_cancel.clicked.connect(self.reject)
        hl.addWidget(btn_cancel)
        return footer

    # ── Lógica de tabs ────────────────────────────────────────────────────────

    def _on_tab(self, idx: int):
        self._stack.setCurrentIndex(idx)
        # El botón del footer solo es relevante en tab Biblioteca
        self.btn_agregar_bib.setVisible(idx == 0)
        self.btn_agregar_bib.setEnabled(len(self._seleccionados) > 0)
        # Foco directo al buscador al entrar a Biblioteca (menos clics)
        if idx == 0:
            QTimer.singleShot(0, self.inp_bib.setFocus)

    def showEvent(self, event):
        super().showEvent(event)
        # Al abrir en la pestaña Biblioteca, dejar el cursor listo en "Buscar"
        if not getattr(self, '_foco_inicial', False) and self._stack.currentIndex() == 0:
            self._foco_inicial = True
            QTimer.singleShot(0, self.inp_bib.setFocus)

    # ── Biblioteca — búsqueda ─────────────────────────────────────────────────

    def _cargar_grupos(self):
        try:
            conn = get_db()
            grupos = [r[0] for r in conn.execute(
                "SELECT DISTINCT grupo FROM biblioteca_cu WHERE grupo IS NOT NULL AND grupo!='' ORDER BY grupo"
            ).fetchall()]
            conn.close()
        except Exception:
            grupos = []
        self.cmb_grupo.blockSignals(True)
        self.cmb_grupo.addItem("Todos los grupos", "")
        for g in grupos:
            self.cmb_grupo.addItem(g, g)
        self.cmb_grupo.blockSignals(False)

    def _debounce_buscar(self):
        self._bib_timer.start()

    def _buscar_biblioteca(self):
        from utils.formatting import norm_busqueda
        texto = self.inp_bib.text().strip()
        grupo = self.cmb_grupo.currentData() if hasattr(self, 'cmb_grupo') else ""

        query  = "SELECT * FROM biblioteca_cu WHERE 1=1"
        params: list = []
        if texto:
            query += " AND _norm(descripcion) LIKE ?"
            params.append(f"%{norm_busqueda(texto)}%")
        if grupo:
            query += " AND grupo=?"
            params.append(grupo)
        query += " ORDER BY descripcion LIMIT 120"

        try:
            conn = get_db()
            conn.create_function("_norm", 1, norm_busqueda)
            rows = conn.execute(query, params).fetchall()
            conn.close()
        except Exception:
            rows = []

        self._limpiar_lista(keep_placeholder=False)
        if hasattr(self, '_prev_layout'):
            self._preview_placeholder()   # la lista cambió → limpiar preview

        if not rows:
            msg = f"Sin resultados para «{texto}»" if texto else "Sin registros en la biblioteca"
            self._lbl_placeholder.setText(msg)
            self._lbl_placeholder.show()
            return

        self._lbl_placeholder.hide()
        self._focused_row = None
        for row in rows:
            cu = dict(row)
            fila = _BibliotecaRow(cu)
            if cu['id'] in self._seleccionados:
                fila.set_checked(True)
            fila.toggled.connect(self._on_cu_toggle)
            fila.clicked.connect(self._on_cu_preview)
            self._lista_layout.insertWidget(
                self._lista_layout.count() - 1, fila
            )
            self._cu_rows.append(fila)

        # Actualizar subtítulo con cuántos resultados hay
        n = len(rows)
        sufijo = "+" if n == 120 else ""
        if not texto and not grupo:
            self._lbl_placeholder.hide()   # ya ocultado arriba, asegurar

    # ── Panel de previsualización del ACU ─────────────────────────────────────

    def _build_preview_panel(self) -> QWidget:
        panel = QScrollArea()
        panel.setWidgetResizable(True)
        panel.setFrameShape(QFrame.NoFrame)
        panel.setStyleSheet(
            f"QScrollArea {{ background:{SILVER_100}; border-left:1px solid {SILVER_300}; }}"
            "QScrollBar:vertical { width:6px; background:transparent; }"
            "QScrollBar::handle:vertical { background:#ABACAE; border-radius:4px; }"
        )
        cont = QWidget()
        cont.setStyleSheet(f"background:{SILVER_100};")
        self._prev_layout = QVBoxLayout(cont)
        self._prev_layout.setContentsMargins(14, 14, 14, 14)
        self._prev_layout.setSpacing(0)
        self._prev_layout.addStretch()
        panel.setWidget(cont)
        self._preview_placeholder()
        return panel

    def _clear_preview(self):
        while self._prev_layout.count():
            it = self._prev_layout.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()

    def _preview_placeholder(self):
        self._clear_preview()
        lbl = QLabel(self._tr("Haz clic en una partida\npara ver su análisis (ACU)"))
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet(f"color:{SLATE_100}; font-size:12px; border:none;"
                          f" background:transparent; padding:40px 10px;")
        self._prev_layout.addWidget(lbl)
        self._prev_layout.addStretch()

    def _on_cu_preview(self, cu_id: int):
        # Resaltar la fila enfocada y desmarcar las demás
        for fila in self._cu_rows:
            fila.set_focused(fila.cu_id == cu_id)
            if fila.cu_id == cu_id:
                self._focused_row = fila
        self._preview_acu(cu_id)

    _TIPO_NOM = {'MO': 'Mano de obra', 'MAT': 'Materiales',
                 'EQ': 'Equipos', 'SC': 'Subcontratos'}
    _TIPO_COLOR = {'MO': '#F39C12', 'MAT': '#27AE60', 'EQ': '#607D8B', 'SC': '#7A36B1'}

    def _preview_acu(self, cu_id: int):
        from core.database import _rn
        conn = get_db()
        cu = conn.execute("SELECT * FROM biblioteca_cu WHERE id=?", (cu_id,)).fetchone()
        items = conn.execute(
            """SELECT r.tipo, r.descripcion, r.unidad, bi.cuadrilla, bi.cantidad,
                      COALESCE(bi.precio, r.precio, 0) AS precio
               FROM biblioteca_acu_items bi JOIN recursos r ON r.id=bi.recurso_id
               WHERE bi.cu_id=?""", (cu_id,)).fetchall()
        conn.close()
        if not cu:
            return
        cu = dict(cu)

        self._clear_preview()

        # Cabecera: descripción + meta (unidad · rendimiento · CU)
        h = QLabel(cu['descripcion'] or "—")
        h.setWordWrap(True)
        h.setStyleSheet(f"color:{SLATE_700}; font-size:13px; font-weight:700;"
                        f" border:none; background:transparent;")
        self._prev_layout.addWidget(h)
        rend = cu.get('rendimiento') or 0
        meta = QLabel(f"{(cu.get('unidad') or '—')}   ·   "
                      f"{self._tr('Rend')} {rend:g}/{self._tr('día')}   ·   "
                      f"CU {fmt(cu.get('costo_unitario') or 0, 'Soles')}")
        meta.setStyleSheet(f"color:{SLATE_300}; font-size:11px; border:none;"
                           f" background:transparent; padding:2px 0 8px 0;")
        self._prev_layout.addWidget(meta)

        if not items:
            v = QLabel(self._tr("Esta partida no tiene análisis en la biblioteca."))
            v.setWordWrap(True)
            v.setStyleSheet(f"color:{SLATE_100}; font-size:11px; border:none;"
                            f" background:transparent; padding:8px 0;")
            self._prev_layout.addWidget(v)
            self._prev_layout.addStretch()
            return

        # Subtotales por tipo (parcial real, igual criterio que _pu_desde_items)
        tot = {'MO': 0.0, 'MAT': 0.0, 'EQ': 0.0}
        pct = []
        normales = []
        for it in items:
            d = dict(it)
            if (d['unidad'] or '').startswith('%'):
                pct.append(d)
            else:
                d['parcial'] = _rn((d['cantidad'] or 0) * (d['precio'] or 0), 2)
                t = d['tipo'] if d['tipo'] in tot else 'MAT'
                tot[t] += d['parcial']
                normales.append(d)
        for d in pct:
            u = (d['unidad'] or '').lower()
            base = tot.get('MO' if '%mo' in u else 'MAT' if '%mat' in u else 'MO', 0)
            d['parcial'] = _rn((d['cantidad'] or 0) / 100 * base, 2)

        # Render agrupado por tipo
        orden = {'MO': 0, 'MAT': 1, 'EQ': 2, 'SC': 3}
        grupos = {}
        for d in normales + pct:
            grupos.setdefault(d['tipo'] if d['tipo'] in orden else 'MAT', []).append(d)
        for tipo in sorted(grupos, key=lambda t: orden.get(t, 9)):
            col = self._TIPO_COLOR.get(tipo, SLATE_300)
            cab = QLabel(self._TIPO_NOM.get(tipo, tipo))
            cab.setStyleSheet(f"color:{col}; font-size:10px; font-weight:700;"
                              f" border:none; background:transparent; padding:8px 0 2px 0;")
            self._prev_layout.addWidget(cab)
            for d in grupos[tipo]:
                self._prev_layout.addWidget(self._preview_item_row(d))

        # Total
        sep = QFrame(); sep.setFixedHeight(1)
        sep.setStyleSheet(f"background:{SILVER_300}; border:none;")
        self._prev_layout.addSpacing(6); self._prev_layout.addWidget(sep)
        tot_row = QHBoxLayout()
        lt = QLabel(self._tr("Costo unitario")); lt.setStyleSheet(
            f"color:{SLATE_700}; font-size:12px; font-weight:700; border:none; background:transparent;")
        lv = QLabel(fmt(cu.get('costo_unitario') or 0, 'Soles')); lv.setStyleSheet(
            f"color:{SLATE_700}; font-size:12px; font-weight:700; border:none; background:transparent;")
        lv.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        wrap = QWidget(); wrap.setStyleSheet("background:transparent;")
        tot_row = QHBoxLayout(wrap); tot_row.setContentsMargins(0, 4, 0, 0)
        tot_row.addWidget(lt); tot_row.addStretch(); tot_row.addWidget(lv)
        self._prev_layout.addWidget(wrap)
        self._prev_layout.addStretch()

    def _preview_item_row(self, d: dict) -> QWidget:
        w = QWidget(); w.setStyleSheet("background:transparent;")
        hl = QHBoxLayout(w); hl.setContentsMargins(6, 1, 0, 1); hl.setSpacing(6)
        desc = QLabel(d['descripcion'] or "—")
        desc.setStyleSheet(f"color:{SLATE_700}; font-size:11px; border:none; background:transparent;")
        desc.setWordWrap(True)
        parc = QLabel(fmt(d.get('parcial') or 0, 'Soles'))
        parc.setStyleSheet(f"color:{SLATE_300}; font-size:11px; font-weight:600;"
                           f" border:none; background:transparent;")
        parc.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        parc.setFixedWidth(82)
        hl.addWidget(desc, stretch=1)
        hl.addWidget(parc)
        return w

    def _limpiar_lista(self, keep_placeholder=True):
        for row in self._cu_rows:
            self._lista_layout.removeWidget(row)
            row.deleteLater()
        self._cu_rows.clear()
        if keep_placeholder:
            self._lbl_placeholder.show()

    def _on_cu_toggle(self, cu_id: int, checked: bool):
        if checked:
            self._seleccionados.add(cu_id)
        else:
            self._seleccionados.discard(cu_id)
        n = len(self._seleccionados)
        if n == 0:
            self.lbl_sel.setText("Ninguna partida seleccionada")
        else:
            self.lbl_sel.setText(f"{n} partida{'s' if n>1 else ''} seleccionada{'s' if n>1 else ''}")
        self.btn_agregar_bib.setEnabled(n > 0)

    # ── Agregar desde biblioteca ──────────────────────────────────────────────

    def _agregar_desde_biblioteca(self):
        if not self._seleccionados:
            return
        try:
            conn = get_db()
            agregados = 0
            for cu_id in sorted(self._seleccionados):
                cu = conn.execute(
                    "SELECT * FROM biblioteca_cu WHERE id=?", (cu_id,)
                ).fetchone()
                if not cu:
                    continue

                nuevo_item = self._siguiente_item(conn)
                nivel      = len(nuevo_item.split('.'))

                conn.execute(
                    """INSERT INTO partidas
                       (proyecto_id, item, descripcion, unidad,
                        metrado, precio_unitario, nivel, es_titulo, rendimiento,
                        sub_presupuesto_id)
                       VALUES (?,?,?,?,0,?,?,0,?,?)""",
                    (self.pid, nuevo_item,
                     cu['descripcion'],
                     cu['unidad'] or '',
                     cu['costo_unitario'] or 0,
                     nivel,
                     cu['rendimiento'] or 1,
                     self._sub_ppto_id)
                )
                new_part_id = conn.execute(
                    "SELECT last_insert_rowid()"
                ).fetchone()[0]

                # Copiar ACU items de biblioteca (si la tabla tiene datos)
                try:
                    bib_acus = conn.execute(
                        "SELECT * FROM biblioteca_acu_items WHERE cu_id=?",
                        (cu_id,)
                    ).fetchall()
                    for bai in bib_acus:
                        bai_dict = dict(bai)
                        # precio NULL → COALESCE(ai.precio, r.precio) cae al de catálogo
                        precio = bai_dict.get('precio')
                        conn.execute(
                            "INSERT INTO acu_items"
                            " (partida_id, recurso_id, cuadrilla, cantidad, precio)"
                            " VALUES (?,?,?,?,?)",
                            (new_part_id,
                             bai_dict.get('recurso_id'),
                             bai_dict.get('cuadrilla', 0),
                             bai_dict.get('cantidad', 0),
                             precio if precio else None)
                        )
                    if bib_acus:
                        _recalcular_pu(conn, new_part_id)
                except Exception:
                    pass   # Sin ACU items en biblioteca — no es error

                agregados += 1

            conn.commit()
            conn.close()
        except Exception as e:
            QMessageBox.critical(self, "Error al agregar",
                                 f"No se pudo insertar la partida:\n{e}")
            return

        self._seleccionados.clear()
        self.partidas_agregadas.emit()
        self.accept()

    # ── Agregar manual ────────────────────────────────────────────────────────

    def _agregar_manual(self):
        desc = self.inp_m_desc.text().strip()
        if not desc:
            self.lbl_m_error.setText("La descripción es obligatoria")
            return

        unidad = self.cmb_m_unidad.currentText().strip()
        grupo  = self.cmb_m_grupo.currentText().strip()

        try:
            conn    = get_db()
            codigo  = self._siguiente_item(conn)
            nivel   = len(codigo.split('.'))
            conn.execute(
                """INSERT INTO partidas
                   (proyecto_id, item, descripcion, unidad,
                    metrado, precio_unitario, nivel, es_titulo, rendimiento, grupo,
                    sub_presupuesto_id)
                   VALUES (?,?,?,?,0,0,?,0,1,?,?)""",
                (self.pid, codigo, desc, unidad, nivel, grupo,
                 self._sub_ppto_id)
            )
            conn.commit()
            conn.close()
        except Exception as e:
            self.lbl_m_error.setText(f"Error: {e}")
            return

        self.lbl_m_error.clear()
        self.partidas_agregadas.emit()
        self.accept()

    # ── Agregar sección/título ────────────────────────────────────────────────

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _siguiente_item(self, conn) -> str:
        """Devuelve el siguiente código de ítem disponible según el contexto.

        Reglas:
        - Título seleccionado "01"   → hijo: "01.01", "01.02"… (dentro del título)
        - Partida seleccionada "01.02" → hermano siguiente: "01.03"
        - Nada seleccionado          → raíz: "01", "02"…
        """
        existing = {r[0] for r in conn.execute(
            "SELECT item FROM partidas WHERE proyecto_id=?", (self.pid,)
        ).fetchall()}

        ctx         = self._contexto_item
        es_titulo   = self._contexto_es_titulo

        # Sin selección → colgar del ÚLTIMO título (si existe alguno)
        if not ctx:
            ctx = self._ultimo_titulo(conn)
            es_titulo = bool(ctx)

        if ctx and es_titulo:
            # Insertar DENTRO del título → como hijo
            prefijo = ctx
            for n in range(1, 1000):
                candidate = f"{prefijo}.{n:02d}"
                if candidate not in existing:
                    existing.add(candidate)
                    return candidate

        elif ctx and not es_titulo:
            # Insertar DESPUÉS de la partida → hermano al mismo nivel
            partes = ctx.split('.')
            for n in range(1, 1000):
                partes[-1] = f"{n:02d}"
                candidate  = '.'.join(partes)
                if candidate not in existing:
                    existing.add(candidate)
                    return candidate

        else:
            # No hay títulos → siguiente en raíz
            for n in range(1, 1000):
                candidate = f"{n:02d}"
                if candidate not in existing:
                    existing.add(candidate)
                    return candidate

        return "99"

    def _ultimo_titulo(self, conn) -> str | None:
        """Código del último título del subpresupuesto activo (orden natural).

        Permite que, sin selección, las partidas se agreguen bajo el título más
        reciente en vez de en la raíz.
        """
        if self._sub_ppto_id is None:
            rows = conn.execute(
                "SELECT item FROM partidas "
                "WHERE proyecto_id=? AND es_titulo=1 AND sub_presupuesto_id IS NULL",
                (self.pid,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT item FROM partidas "
                "WHERE proyecto_id=? AND es_titulo=1 AND sub_presupuesto_id=?",
                (self.pid, self._sub_ppto_id)
            ).fetchall()
        items = [r[0] for r in rows if r[0]]
        if not items:
            return None

        def _clave(code: str):
            try:
                return tuple(int(p) for p in code.split('.'))
            except ValueError:
                return (float('inf'),)

        return max(items, key=_clave)

