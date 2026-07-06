# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""metrados_view — Hoja de Metrados (≈ metrados.html de Flask).

Vista standalone anclada al ``_root_stack`` de ProyectoView. Muestra
TODAS las partidas del proyecto con su detalle de metrados en un solo
scroll. Es una vista de revisión/impresión: la edición fina sigue en la
pestaña "Metrados" del proyecto.

Layout:
    - Topbar:        ← Presupuesto · 📐 Hoja de Metrados · nombre proyecto
    - Toolbar:       Imprimir · Exportar Excel · KPIs
    - Card cabecera: proyecto · cliente · ubicación · sub-pres · fecha · modalidad
    - Tabla:         filas título + cabeceras de partida + dimensiones + total
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QSize, QTimer, Signal
from PySide6.QtGui import QFont, QColor, QBrush
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QFileDialog, QMessageBox, QSizePolicy, QMenu, QStackedWidget,
)
from PySide6.QtPrintSupport import QPrinter, QPrintPreviewDialog

from core.database import (get_db, get_decimales_ppto, get_decimales_metrado,
                           _rn, parcial_wysiwyg, partida_usa_acero)
from utils.formatting import fmt
from utils.icons import icon


# ── Paleta ────────────────────────────────────────────────────────────────────
ORANGE       = "#F37329"
ORANGE_DARK  = "#C0621A"
ORANGE_SOFT  = "#FEF5EB"
ORANGE_BG_T1 = "#FFE8CC"   # fondo título nivel 1
ORANGE_BG_T  = "#FFF3E8"   # fondo título nivel 2+
ORANGE_BORDER = "#F5C490"
# Colores de título por nivel — espejo de NIVEL_ESTILO del Presupuesto.
NIVEL_COL = {1: "#B71C1C", 2: "#0D52BF", 3: "#6A1B9A", 4: "#AD1457"}
NIVEL_BG  = {1: "#FFF5F5", 2: "#F5F8FF", 3: "#F9F5FF", 4: "#FFF5FA"}
SLATE_700    = "#273445"
SLATE_500    = "#485A6C"
SLATE_300    = "#667885"
SILVER_50    = "#FBFBFC"
SILVER_100   = "#F8F9FA"
SILVER_200   = "#F0F1F2"
SILVER_300   = "#D4D4D4"
WHITE        = "#FFFFFF"
PAGE_BG      = "#EEF2F7"   # fondo de la vista (canvas detrás de la tabla)
BLUE_HEAD    = "#F0F4FA"   # fondo cabecera de partida-hoja
BLUE_BORDER  = "#C8D2E0"


COLS = ["Ítem", "Descripción", "Und.", "N°Est.", "N°Elem.",
        "Área", "Largo", "Ancho", "Alto", "Parcial", "Total"]

# Planilla de acero (solo lectura) — mismas columnas que la tabla de acero del
# proyecto (COLS_ACERO en proyecto_view), con «Ítem» al frente por ser una hoja
# multi-partida. Parc.(m) = N°Estr × N°Elem × N°Var × Longitud (calculado);
# la BD guarda `parcial` = Parc.(kg).
ACERO_COLS = ["Ítem", "Descripción", "Diámetro", "N°Estr.", "N°Elem.",
              "N°Var.", "Longitud", "Parc.(m)", "kg/ml", "Parc.(kg)"]


class MetradosView(QWidget):
    """Hoja de metrados completa del proyecto (todas las partidas)."""

    def __init__(self, proyecto_id: int, proyecto_nombre: str = "",
                 on_back=None, parent=None, editable: bool = True):
        super().__init__(parent)
        self.pid = proyecto_id
        self.proyecto_nombre = proyecto_nombre
        self._on_back = on_back
        self._editable = editable   # False → solo lectura (estado aprobado/ejecutado)
        self._proy: dict = {}
        self._row_color: list[QColor] = []   # color de fondo cacheado por fila
        # Tracking para edición: kind ∈ {'title','header','dim'} y partida_id por fila
        self._row_kind: list[str] = []
        self._row_partida: list[int] = []
        self._loading: bool = False
        self._build()

    # ── construcción UI ─────────────────────────────────────────────────────
    def _build(self):
        # Fondo de página tipo "canvas" para que la tabla blanca contraste,
        # mismo patrón que Cronograma / Dashboard.
        self.setObjectName("metRoot")
        self.setStyleSheet(
            f"QWidget#metRoot {{ background:{PAGE_BG}; }}"
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Barra única compacta (mismo patrón que Cronograma) ──────────────
        # Sin título grande ni nombre de proyecto repetido: el proyecto ya se ve
        # en las pestañas de arriba (vista de proyecto). Ahorra alto vertical.
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

        lbl_title = QLabel("Hoja de Metrados")
        lbl_title.setStyleSheet(
            "color:white; font-size:12px; font-weight:700;"
            " background:transparent; border:none;")
        hl.addWidget(lbl_title)
        hl.addSpacing(14)

        # Pestañas Metrados | Acero (la de Acero solo aparece si hay datos).
        def _tab_style(sel: bool) -> str:
            bg = ORANGE if sel else "transparent"
            hov = "" if sel else ("QPushButton:hover { background:rgba(255,255,255,0.15);"
                                  " color:white; }")
            return (f"QPushButton {{ background:{bg}; color:white; border:none;"
                    f" border-radius:6px; font-size:11px; font-weight:700;"
                    f" padding:3px 14px; }}" + hov)
        self._tab_style = _tab_style
        self.btn_tab_met = QPushButton("Metrados")
        self.btn_tab_met.setCursor(Qt.PointingHandCursor)
        self.btn_tab_met.setStyleSheet(_tab_style(True))
        self.btn_tab_met.clicked.connect(lambda: self._select_tab(0))
        hl.addWidget(self.btn_tab_met)
        self.btn_tab_acero = QPushButton("Acero")
        self.btn_tab_acero.setCursor(Qt.PointingHandCursor)
        self.btn_tab_acero.setStyleSheet(_tab_style(False))
        self.btn_tab_acero.clicked.connect(lambda: self._select_tab(1))
        self.btn_tab_acero.setVisible(False)   # se muestra si el proyecto tiene acero
        hl.addWidget(self.btn_tab_acero)

        hl.addStretch(1)

        action_style = (
            "QPushButton { background:rgba(255,255,255,0.18); color:white;"
            " border:1px solid rgba(255,255,255,0.35); border-radius:4px;"
            " font-size:11px; padding:3px 12px; min-height:0; }"
            "QPushButton:hover { background:rgba(255,255,255,0.30); }"
        )
        self.btn_imprimir = QPushButton("Imprimir…")
        self.btn_imprimir.setIcon(icon("imprimir"))
        self.btn_imprimir.setIconSize(QSize(14, 14))
        self.btn_imprimir.setCursor(Qt.PointingHandCursor)
        self.btn_imprimir.setStyleSheet(action_style)
        self.btn_imprimir.clicked.connect(self._imprimir)
        hl.addWidget(self.btn_imprimir)

        self.btn_excel = QPushButton("Exportar Excel")
        self.btn_excel.setIcon(icon("xlsx"))
        self.btn_excel.setIconSize(QSize(14, 14))
        self.btn_excel.setCursor(Qt.PointingHandCursor)
        self.btn_excel.setStyleSheet(
            f"QPushButton {{ background:{ORANGE}; color:white; border:none;"
            f" border-radius:4px; font-size:11px; font-weight:600;"
            f" padding:4px 14px; min-height:0; }}"
            f"QPushButton:hover {{ background:{ORANGE_DARK}; }}"
        )
        self.btn_excel.clicked.connect(self._exportar_excel)
        hl.addWidget(self.btn_excel)

        root.addWidget(hdr)

        # ── Área de contenido (con margen y canvas slate-100) ───────────────
        content = QWidget()
        content_vl = QVBoxLayout(content)
        content_vl.setContentsMargins(20, 14, 20, 14)
        content_vl.setSpacing(0)

        # Banda con pistas de uso (encima de la tabla)
        if self._editable:
            tips = QLabel(
                "💡  <b>Doble clic en una partida</b> agrega una fila de detalle  ·  "
                "<b>Doble clic en una celda</b> la edita  ·  "
                "Flechas / Tab / Enter para navegar  ·  "
                "<b>Clic derecho</b> para más acciones  ·  "
                "<b>Supr</b> borra contenido"
            )
            tips.setStyleSheet(
                f"color:{SLATE_500}; font-size:11px; background:{SILVER_100};"
                f" border:1px solid {SILVER_300}; border-bottom:none;"
                f" border-top-left-radius:6px; border-top-right-radius:6px;"
                f" padding:6px 12px;"
            )
        else:
            tips = QLabel(
                "🔒  <b>Solo lectura</b> — el proyecto está aprobado o en ejecución. "
                "Cambia el estado a «En elaboración» (chip de estado del proyecto) "
                "para editar los metrados."
            )
            tips.setStyleSheet(
                "color:#273445; font-size:11px; background:#FFF8E1;"
                " border:1px solid #FFD27D; border-bottom:none;"
                " border-top-left-radius:6px; border-top-right-radius:6px;"
                " padding:6px 12px;"
            )
        tips.setTextFormat(Qt.RichText)
        content_vl.addWidget(tips)

        # Tabla — mismo estilo que Cronograma Valorizado / Gantt:
        # border silver, gridlines slate-200 sutiles, header slate-500 blanco.
        self.tbl = QTableWidget(0, len(COLS))
        self.tbl.setHorizontalHeaderLabels(COLS)
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.tbl.setEditTriggers(
            (QAbstractItemView.DoubleClicked   |
             QAbstractItemView.SelectedClicked |
             QAbstractItemView.EditKeyPressed  |
             QAbstractItemView.AnyKeyPressed)
            if self._editable else QAbstractItemView.NoEditTriggers
        )
        self.tbl.setShowGrid(True)
        self.tbl.setAlternatingRowColors(False)
        self.tbl.itemChanged.connect(self._on_item_changed)
        self.tbl.cellDoubleClicked.connect(self._on_cell_double_clicked)
        self.tbl.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tbl.customContextMenuRequested.connect(self._on_context_menu)
        self.tbl.installEventFilter(self)
        self.tbl.setStyleSheet(f"""
            QTableWidget {{ background:white; border:1px solid {SILVER_300};
                            border-radius:6px; font-size:11px;
                            gridline-color:#E0E5EC; }}
            QTableWidget::item {{ padding:3px 8px; }}
            QTableWidget::item:selected {{ background:#FEF0E0; color:{SLATE_700}; }}
            QHeaderView::section {{ background:{SLATE_500}; color:white;
                font-size:10px; font-weight:700;
                padding:4px 6px; border:none;
                letter-spacing:0.3px; }}
            QTableWidget QLineEdit {{ background:white; color:{SLATE_700};
                border:1px solid {ORANGE}; border-radius:0; padding:0 2px; margin:0;
                selection-background-color:{ORANGE}; selection-color:white; }}
        """)
        h = self.tbl.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.Fixed); h.resizeSection(0, 80)   # ítem
        h.setSectionResizeMode(1, QHeaderView.Stretch)                          # descripción
        h.setSectionResizeMode(2, QHeaderView.Fixed); h.resizeSection(2, 56)   # und
        h.setSectionResizeMode(3, QHeaderView.Fixed); h.resizeSection(3, 65)   # n°est
        h.setSectionResizeMode(4, QHeaderView.Fixed); h.resizeSection(4, 65)   # n°elem
        h.setSectionResizeMode(5, QHeaderView.Fixed); h.resizeSection(5, 75)   # área
        h.setSectionResizeMode(6, QHeaderView.Fixed); h.resizeSection(6, 75)   # largo
        h.setSectionResizeMode(7, QHeaderView.Fixed); h.resizeSection(7, 75)   # ancho
        h.setSectionResizeMode(8, QHeaderView.Fixed); h.resizeSection(8, 75)   # alto
        h.setSectionResizeMode(9, QHeaderView.Fixed); h.resizeSection(9, 90)   # parcial
        h.setSectionResizeMode(10, QHeaderView.Fixed); h.resizeSection(10, 100) # total
        content_vl.addWidget(self.tbl, 1)

        # Stack: página 0 = metrados (content), página 1 = acero (solo lectura)
        self._content_stack = QStackedWidget()
        self._content_stack.addWidget(content)
        self._content_stack.addWidget(self._build_acero_page())
        root.addWidget(self._content_stack, 1)
        self._tab_idx = 0

    # ── Carga ──────────────────────────────────────────────────────────────
    def cargar(self):
        """Carga el proyecto, las partidas y todos sus metrados."""
        conn = get_db()
        proy = conn.execute(
            "SELECT * FROM proyectos WHERE id=?", (self.pid,)
        ).fetchone()
        if not proy:
            conn.close()
            return
        self._proy = dict(proy)

        todas = conn.execute(
            "SELECT * FROM partidas WHERE proyecto_id=? ORDER BY item",
            (self.pid,)
        ).fetchall()

        # Partidas de acero = con planilla de acero  O  (vacías y claramente de
        # acero: unidad kg + descripción ACERO/FIERRO/…). Van a la pestaña Acero
        # y se excluyen del metrado normal.
        acero_ids = self._acero_partida_set(conn, todas)
        self._acero_partida_ids = acero_ids

        # Solo conservar títulos cuyos hijos hoja sean del tipo metrado normal
        hojas_normales = {p['item'] for p in todas
                          if not p['es_titulo'] and p['id'] not in acero_ids}

        def tiene_hijos_normales(titulo_item: str) -> bool:
            prefix = titulo_item + '.'
            return any(hi.startswith(prefix) for hi in hojas_normales)

        partidas = [
            p for p in todas
            if (p['es_titulo'] and tiene_hijos_normales(p['item']))
            or (not p['es_titulo'] and p['id'] not in acero_ids)
        ]

        # Cargar metrados_detalle por partida
        planilla: dict[int, list[dict]] = {}
        for p in partidas:
            if p['es_titulo']:
                continue
            filas = conn.execute(
                "SELECT * FROM metrados_detalle WHERE partida_id=? "
                "ORDER BY orden, id",
                (p['id'],)
            ).fetchall()
            planilla[p['id']] = [dict(f) for f in filas]
        conn.close()

        self._render_tabla(partidas, planilla)

        # Pestaña «Acero»: visible solo si el proyecto tiene planillas de acero.
        self._acero_loaded = False
        self.btn_tab_acero.setVisible(bool(acero_ids))
        if not acero_ids and getattr(self, '_tab_idx', 0) == 1:
            self._select_tab(0)
        elif getattr(self, '_tab_idx', 0) == 1:
            self._cargar_acero()

    def _acero_partida_set(self, conn, todas) -> set:
        """IDs de partidas de acero: las que tienen planilla de acero + las
        vacías que la heurística reconoce como acero (kg + descripción). Una
        partida con metrados normales NO se reclasifica."""
        con_acero = {r['partida_id'] for r in conn.execute(
            "SELECT DISTINCT partida_id FROM acero_detalle "
            "WHERE partida_id IN (SELECT id FROM partidas WHERE proyecto_id=?)",
            (self.pid,)).fetchall()}
        con_met = {r['partida_id'] for r in conn.execute(
            "SELECT DISTINCT partida_id FROM metrados_detalle "
            "WHERE partida_id IN (SELECT id FROM partidas WHERE proyecto_id=?)",
            (self.pid,)).fetchall()}
        ids = set(con_acero)
        for p in todas:
            if p['es_titulo'] or p['id'] in con_acero:
                continue
            tm = p['id'] in con_met
            if partida_usa_acero(False, tm, p['metrado_tipo'],
                                 p['descripcion'], p['unidad']):
                ids.add(p['id'])
        return ids

    # ── Pestaña Acero (solo lectura) ─────────────────────────────────────────
    def _build_acero_page(self) -> QWidget:
        page = QWidget()
        vl = QVBoxLayout(page)
        vl.setContentsMargins(20, 14, 20, 14)
        vl.setSpacing(0)
        if self._editable:
            info = QLabel(
                "🔩  <b>Acero de refuerzo</b>  ·  <b>Doble clic en una partida</b> "
                "agrega una fila  ·  escribe el <b>Ø</b> (1/2\", 3/8\"…) y el kg/m se "
                "completa solo  ·  <b>Supr</b> borra  ·  Parc.(m) y Parc.(kg) se "
                "calculan. Se guarda y actualiza el metrado del presupuesto."
            )
        else:
            info = QLabel(
                "🔩  <b>Acero de refuerzo</b> — solo lectura (proyecto aprobado/"
                "en ejecución). Cambia el estado a «En elaboración» para editar."
            )
        info.setTextFormat(Qt.RichText)
        info.setStyleSheet(
            f"color:{SLATE_500}; font-size:11px; background:{SILVER_100};"
            f" border:1px solid {SILVER_300}; border-bottom:none;"
            f" border-top-left-radius:6px; border-top-right-radius:6px;"
            f" padding:6px 12px;")
        vl.addWidget(info)

        self.tbl_acero = QTableWidget(0, len(ACERO_COLS))
        self.tbl_acero.setHorizontalHeaderLabels(ACERO_COLS)
        self.tbl_acero.verticalHeader().setVisible(False)
        self.tbl_acero.setEditTriggers(
            (QAbstractItemView.DoubleClicked   |
             QAbstractItemView.SelectedClicked |
             QAbstractItemView.EditKeyPressed  |
             QAbstractItemView.AnyKeyPressed)
            if self._editable else QAbstractItemView.NoEditTriggers
        )
        self.tbl_acero.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.tbl_acero.setShowGrid(True)
        self.tbl_acero.setAlternatingRowColors(False)
        # Tracking de filas para edición (paralelo a self.tbl)
        self._ac_kind: list[str] = []      # 'title' | 'header' | 'detail'
        self._ac_partida: list[int] = []
        self._ac_pu: dict[int, float] = {}
        self._ac_loading = False
        self.tbl_acero.itemChanged.connect(self._ac_on_item_changed)
        self.tbl_acero.cellDoubleClicked.connect(self._ac_on_double_click)
        self.tbl_acero.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tbl_acero.customContextMenuRequested.connect(self._ac_on_context_menu)
        self.tbl_acero.installEventFilter(self)
        self.tbl_acero.setStyleSheet(f"""
            QTableWidget {{ background:white; border:1px solid {SILVER_300};
                            border-radius:6px; font-size:11px;
                            gridline-color:#E0E5EC; }}
            QTableWidget::item {{ padding:3px 8px; }}
            QTableWidget::item:selected {{ background:#FEF0E0; color:{SLATE_700}; }}
            QHeaderView::section {{ background:{SLATE_500}; color:white;
                font-size:10px; font-weight:700; padding:4px 6px; border:none;
                letter-spacing:0.3px; }}
            /* Editor de celda compacto: el QSS global pone padding grande +
               selección naranja-sobre-naranja → el número no se ve al tipear. */
            QTableWidget QLineEdit {{ background:white; color:{SLATE_700};
                border:1px solid {ORANGE}; border-radius:0; padding:0 2px; margin:0;
                selection-background-color:{ORANGE}; selection-color:white; }}
        """)
        h = self.tbl_acero.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.Fixed); h.resizeSection(0, 80)
        h.setSectionResizeMode(1, QHeaderView.Stretch)
        # 2:Diám 3:N°Estr 4:N°Elem 5:N°Var 6:Longitud 7:Parc(m) 8:kg/ml 9:Parc(kg)
        for c, w in [(2, 80), (3, 60), (4, 60), (5, 60), (6, 80),
                     (7, 78), (8, 70), (9, 95)]:
            h.setSectionResizeMode(c, QHeaderView.Fixed); h.resizeSection(c, w)
        vl.addWidget(self.tbl_acero, 1)
        return page

    def _select_tab(self, idx: int):
        self._tab_idx = idx
        self._content_stack.setCurrentIndex(idx)
        self.btn_tab_met.setStyleSheet(self._tab_style(idx == 0))
        self.btn_tab_acero.setStyleSheet(self._tab_style(idx == 1))
        if idx == 1:
            self._cargar_acero()

    @staticmethod
    def _nf(v, dec: int) -> str:
        if v is None or v == '':
            return ''
        try:
            return f"{float(v):,.{dec}f}"
        except (ValueError, TypeError):
            return str(v)

    @staticmethod
    def _ng(v) -> str:
        """Número 'general': entero si es entero, si no sin ceros sobrantes
        (igual que la tabla de acero del proyecto, que muestra el valor crudo)."""
        if v is None or v == '':
            return ''
        try:
            fv = float(v)
        except (ValueError, TypeError):
            return str(v)
        if fv == int(fv):
            return str(int(fv))
        return f"{fv:.6f}".rstrip('0').rstrip('.')

    def _cargar_acero(self):
        if getattr(self, '_acero_loaded', False):
            return
        conn = get_db()
        todas = conn.execute(
            "SELECT * FROM partidas WHERE proyecto_id=? ORDER BY item", (self.pid,)
        ).fetchall()
        # Set de partidas de acero (dato + heurística), consistente con cargar().
        acero_ids = getattr(self, '_acero_partida_ids', None)
        if acero_ids is None:
            acero_ids = self._acero_partida_set(conn, todas)
        acero_rows: dict[int, list[dict]] = {}
        for pid in acero_ids:
            filas = conn.execute(
                "SELECT * FROM acero_detalle WHERE partida_id=? ORDER BY orden, id",
                (pid,)
            ).fetchall()
            acero_rows[pid] = [dict(f) for f in filas]   # puede quedar vacío
        conn.close()
        items_acero = {p['item'] for p in todas
                       if not p['es_titulo'] and p['id'] in acero_ids}

        def tiene_hijos_acero(titulo_item: str) -> bool:
            prefix = titulo_item + '.'
            return any(it.startswith(prefix) for it in items_acero)

        partidas = [
            p for p in todas
            if (p['es_titulo'] and tiene_hijos_acero(p['item']))
            or (not p['es_titulo'] and p['id'] in acero_ids)
        ]
        # PU por partida (para recalcular el parcial del presupuesto al editar)
        self._ac_pu = {p['id']: (p['precio_unitario'] or 0)
                       for p in partidas if not p['es_titulo']}
        self._render_acero(partidas, acero_rows)
        self._acero_loaded = True

    @staticmethod
    def _parc_m(f: dict) -> float:
        """Parc.(m) = N°Estr × N°Elem × N°Var × Longitud (factores presentes)."""
        dims = []
        for k in ('n_estructuras', 'n_elementos', 'n_veces', 'longitud'):
            v = f.get(k)
            if v not in (None, ''):
                try:
                    dims.append(float(v))
                except (ValueError, TypeError):
                    pass
        p = 1.0
        for d in dims:
            p *= d
        return p if dims else 0.0

    # Columnas editables de una fila de detalle de acero.
    _AC_EDIT_COLS = {1, 2, 3, 4, 5, 6, 8}

    @staticmethod
    def _ac_kg(v) -> str:
        try:
            return f"{float(v):.3f}" if v not in (None, '') else ''
        except (ValueError, TypeError):
            return ''

    def _render_acero(self, partidas: list, acero_rows: dict[int, list[dict]]):
        t = self.tbl_acero
        self._ac_loading = True
        t.setUpdatesEnabled(False)
        t.clearContents()
        t.setRowCount(0)
        self._ac_kind.clear()
        self._ac_partida.clear()
        right = {c: Qt.AlignRight for c in (3, 4, 5, 6, 7, 8, 9)}
        right[2] = Qt.AlignCenter
        dec = get_decimales_metrado()

        def add_row(cells, *, kind, partida_id, bold=False, bg=None, fg=None,
                    align=None, editable_cols=frozenset()):
            r = t.rowCount(); t.insertRow(r); t.setRowHeight(r, 24)
            self._ac_kind.append(kind)
            self._ac_partida.append(partida_id)
            for c, txt in enumerate(cells):
                it = QTableWidgetItem(txt)
                if self._editable and c in editable_cols:
                    it.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled
                                | Qt.ItemIsEditable)
                else:
                    it.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                al = (align or {}).get(c)
                it.setTextAlignment((al or Qt.AlignLeft) | Qt.AlignVCenter)
                if bold:
                    f = QFont(); f.setBold(True); it.setFont(f)
                if bg:
                    it.setBackground(QBrush(QColor(bg)))
                if fg:
                    it.setForeground(QBrush(QColor(fg)))
                t.setItem(r, c, it)
            return r

        grand = 0.0
        for p in partidas:
            nivel = p['nivel'] or 1
            indent = "    " * max(0, nivel - 1)
            if p['es_titulo']:
                col = NIVEL_COL.get(nivel, SLATE_700)
                bg = NIVEL_BG.get(nivel, "#FFF5F5")
                add_row([p['item'] or '', indent + (p['descripcion'] or ''),
                         '', '', '', '', '', '', '', ''],
                        kind='title', partida_id=-1, bold=True, bg=bg, fg=col)
            else:
                filas = acero_rows.get(p['id'], [])
                tot = sum((f.get('parcial') or 0) for f in filas)
                grand += tot
                add_row([p['item'] or '', indent + (p['descripcion'] or ''),
                         '', '', '', '', '', '', '', self._nf(tot, dec)],
                        kind='header', partida_id=p['id'], bold=True,
                        bg=BLUE_HEAD, align={9: Qt.AlignRight})
                for f in filas:
                    self._ac_add_detail(p['id'], f)
        if t.rowCount():
            add_row(['', 'TOTAL ACERO (kg)', '', '', '', '', '', '', '',
                     self._nf(grand, dec)], kind='total', partida_id=-1,
                    bold=True, bg="#FFF3E8", fg=ORANGE_DARK,
                    align={9: Qt.AlignRight})
        t.setUpdatesEnabled(True)
        self._ac_loading = False

    def _ac_add_detail(self, partida_id: int, f: dict, at_row: int | None = None):
        """Inserta una fila de detalle de acero (editable) en tbl_acero."""
        t = self.tbl_acero
        dec = get_decimales_metrado()
        right = {c: Qt.AlignRight for c in (3, 4, 5, 6, 7, 8, 9)}
        right[2] = Qt.AlignCenter
        r = at_row if at_row is not None else t.rowCount()
        prev = self._ac_loading
        self._ac_loading = True
        t.insertRow(r)
        t.setRowHeight(r, 24)
        self._ac_kind.insert(r, 'detail')
        self._ac_partida.insert(r, partida_id)
        cells = [
            '', '    ' + (f.get('descripcion') or ''),
            f.get('diametro') or '',
            self._ng(f.get('n_estructuras')),
            self._ng(f.get('n_elementos')),
            self._ng(f.get('n_veces')),
            self._ng(f.get('longitud')),
            self._nf(self._parc_m(f), dec),
            self._ac_kg(f.get('kg_ml')),
            self._nf(f.get('parcial'), dec) if f.get('parcial') not in (None, '')
            else '',
        ]
        for c, txt in enumerate(cells):
            it = QTableWidgetItem(txt)
            if self._editable and c in self._AC_EDIT_COLS:
                it.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
            else:
                it.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            it.setTextAlignment(right.get(c, Qt.AlignLeft) | Qt.AlignVCenter)
            if c in (7, 9):
                it.setBackground(QColor(SILVER_100))
            t.setItem(r, c, it)
        self._ac_loading = prev
        return r

    # ── Edición de acero ─────────────────────────────────────────────────────
    @staticmethod
    def _ac_parse(text) -> float | None:
        text = (text or '').strip()
        if not text:
            return None
        try:
            return float(text.replace(',', '.'))
        except (ValueError, TypeError):
            return None

    def _ac_detail_rows_of(self, partida_id: int) -> list[int]:
        return [r for r, (k, pid) in enumerate(zip(self._ac_kind, self._ac_partida))
                if k == 'detail' and pid == partida_id]

    def _ac_find_header(self, partida_id: int) -> int | None:
        for r, (k, pid) in enumerate(zip(self._ac_kind, self._ac_partida)):
            if k == 'header' and pid == partida_id:
                return r
        return None

    def _ac_on_item_changed(self, item):
        if self._ac_loading or not self._editable:
            return
        row = item.row()
        if row >= len(self._ac_kind) or self._ac_kind[row] != 'detail':
            return
        if item.column() == 2:        # diámetro → normalizar + kg/ml automático
            self._ac_apply_diametro(row)
        elif item.column() in (3, 4, 5, 6, 8):
            # Completar «0» a la izquierda en decimales: «.1» → «0.1».
            t = (item.text() or '').strip()
            nt = ('0' + t if t[:1] in ('.', ',')
                  else '-0' + t[1:] if t[:2] in ('-.', '-,') else t)
            if nt != item.text():
                self._ac_loading = True
                item.setText(nt)
                self._ac_loading = False
        self._ac_recompute_row(row)
        try:
            self._ac_guardar_partida(self._ac_partida[row])
        except Exception:
            import traceback; traceback.print_exc()

    def _ac_apply_diametro(self, row: int):
        t = self.tbl_acero
        it = t.item(row, 2)
        raw = (it.text() if it else '').strip()
        if not raw:
            return
        try:
            from views.proyecto_view import (_normalizar_diametro_acero as _norm,
                                             _ACERO_KG_ML as _KG)
        except Exception:
            return
        norm = _norm(raw)
        self._ac_loading = True
        if it:
            it.setText(norm)
        kg = _KG.get(norm)
        if kg is not None and t.item(row, 8):
            t.item(row, 8).setText(f"{kg:.3f}")
        self._ac_loading = False

    def _ac_recompute_row(self, row: int) -> float:
        t = self.tbl_acero
        dec = get_decimales_metrado()

        def val(c):
            it = t.item(row, c)
            return self._ac_parse(it.text() if it else '')

        dims = [v for v in (val(3), val(4), val(5), val(6)) if v is not None]
        kgml = val(8)
        parc_m = 1.0
        for d in dims:
            parc_m *= d
        parc_m = round(parc_m, 4) if dims else 0.0
        parc_kg = round(parc_m * kgml, 4) if (dims and kgml) else 0.0
        self._ac_loading = True
        if t.item(row, 7):
            t.item(row, 7).setText(self._nf(parc_m, dec) if dims else '')
        if t.item(row, 9):
            t.item(row, 9).setText(self._nf(parc_kg, dec) if (dims and kgml) else '')
        self._ac_loading = False
        return parc_kg

    def _ac_guardar_partida(self, partida_id: int):
        if not self._editable or partida_id < 0:
            return
        t = self.tbl_acero
        dec = get_decimales_metrado()
        registros = []
        total_kg = 0.0
        for r in self._ac_detail_rows_of(partida_id):
            def cell(c):
                it = t.item(r, c)
                return (it.text().strip() if it else '')
            desc = cell(1).strip()
            diam = cell(2).strip()
            n_est = self._ac_parse(cell(3)); n_el = self._ac_parse(cell(4))
            n_var = self._ac_parse(cell(5)); llong = self._ac_parse(cell(6))
            kgml = self._ac_parse(cell(8))
            if not desc and not diam and all(v is None for v in (n_est, n_el, n_var, llong)):
                continue
            dims = [v for v in (n_est, n_el, n_var, llong) if v is not None]
            parc_m = 1.0
            for d in dims:
                parc_m *= d
            parc_m = round(parc_m, 4) if dims else 0.0
            parc_kg = round(parc_m * kgml, 4) if kgml else 0.0
            total_kg += parc_kg
            registros.append((desc, diam, n_est, n_el, n_var, llong, kgml, parc_kg))
        total_kg = round(total_kg, dec)

        conn = get_db()
        try:
            conn.execute("DELETE FROM acero_detalle WHERE partida_id=?", (partida_id,))
            for orden, reg in enumerate(registros, 1):
                conn.execute(
                    """INSERT INTO acero_detalle
                       (partida_id, orden, descripcion, diametro, n_estructuras,
                        n_elementos, n_veces, longitud, kg_ml, parcial)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (partida_id, orden, *reg))
            conn.execute("UPDATE partidas SET metrado=? WHERE id=?",
                         (total_kg, partida_id))
            conn.commit()
        finally:
            conn.close()

        # Actualizar total de la partida (header) + total general en la UI.
        self._ac_loading = True
        hdr = self._ac_find_header(partida_id)
        if hdr is not None and t.item(hdr, 9):
            t.item(hdr, 9).setText(self._nf(total_kg, dec))
        self._ac_update_grand()
        self._ac_loading = False

    def _ac_update_grand(self):
        t = self.tbl_acero
        dec = get_decimales_metrado()
        grand = 0.0
        total_row = None
        for r, k in enumerate(self._ac_kind):
            if k == 'header':
                it = t.item(r, 9)
                if it and it.text().strip():
                    try:
                        grand += float(it.text().replace(',', ''))
                    except ValueError:
                        pass
            elif k == 'total':
                total_row = r
        if total_row is not None and t.item(total_row, 9):
            t.item(total_row, 9).setText(self._nf(grand, dec))

    def _ac_on_double_click(self, row: int, col: int):
        if not self._editable or row >= len(self._ac_kind):
            return
        if self._ac_kind[row] == 'header':
            pid = self._ac_partida[row]
            rows = self._ac_detail_rows_of(pid)
            at = (max(rows) + 1) if rows else row + 1
            r = self._ac_add_detail(pid, {}, at_row=at)
            self.tbl_acero.setCurrentCell(r, 1)
            self.tbl_acero.editItem(self.tbl_acero.item(r, 1))

    def _ac_on_context_menu(self, pos):
        if not self._editable:
            return
        row = self.tbl_acero.rowAt(pos.y())
        if row < 0 or row >= len(self._ac_kind):
            return
        menu = QMenu(self)
        kind = self._ac_kind[row]
        pid = self._ac_partida[row]
        if kind == 'header':
            menu.addAction("Agregar fila de acero",
                           lambda: self._ac_on_double_click(row, 0))
        elif kind == 'detail':
            menu.addAction("Agregar fila de acero",
                           lambda: self._ac_on_double_click(self._ac_find_header(pid) or row, 0))
            menu.addAction("Eliminar fila", lambda: self._ac_eliminar_fila(row, pid))
        if kind in ('header', 'detail'):
            menu.addSeparator()
            menu.addAction("📐  Cambiar a planilla de metrados normal",
                           lambda p=pid: self._cambiar_planilla(p, 'met'))
        if not menu.isEmpty():
            menu.exec(self.tbl_acero.viewport().mapToGlobal(pos))

    def _ac_eliminar_fila(self, row: int, partida_id: int):
        if not self._editable or row >= len(self._ac_kind):
            return
        self._ac_loading = True
        self.tbl_acero.removeRow(row)
        del self._ac_kind[row]
        del self._ac_partida[row]
        self._ac_loading = False
        self._ac_guardar_partida(partida_id)

    def _cambiar_planilla(self, partida_id: int, modo: str):
        """Cambia la partida entre planilla de acero ('acero') y metrados normal
        ('met'). Si tiene datos de la otra planilla, pide confirmación y los
        borra. Marca partidas.metrado_tipo y recarga la Hoja."""
        if not self._editable or partida_id < 0:
            return
        otro_tbl = 'metrados_detalle' if modo == 'acero' else 'acero_detalle'
        otro_nom = 'metrado normal' if modo == 'acero' else 'acero'
        conn = get_db()
        tiene_otro = conn.execute(
            f"SELECT 1 FROM {otro_tbl} WHERE partida_id=? LIMIT 1", (partida_id,)
        ).fetchone() is not None
        conn.close()
        if tiene_otro:
            resp = QMessageBox.question(
                self, "Cambiar planilla",
                f"Esta partida tiene datos de {otro_nom}.\n"
                "Al cambiar de planilla esos datos se borrarán.\n\n¿Continuar?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if resp != QMessageBox.Yes:
                return
        conn = get_db()
        try:
            if tiene_otro:
                conn.execute(f"DELETE FROM {otro_tbl} WHERE partida_id=?", (partida_id,))
                conn.execute("UPDATE partidas SET metrado=0 WHERE id=?", (partida_id,))
            conn.execute("UPDATE partidas SET metrado_tipo=? WHERE id=?",
                         (modo, partida_id))
            conn.commit()
        finally:
            conn.close()
        # Recargar la Hoja completa y mostrar la pestaña destino.
        self._acero_loaded = False
        self.cargar()
        self._select_tab(1 if modo == 'acero' else 0)

    def _render_tabla(self, partidas: list, planilla: dict[int, list[dict]]):
        tbl = self.tbl
        self._loading = True
        tbl.setUpdatesEnabled(False)
        tbl.setSortingEnabled(False)
        tbl.clearContents()
        tbl.setRowCount(0)
        self._row_color.clear()
        self._row_kind.clear()
        self._row_partida.clear()

        for p in partidas:
            es_tit = bool(p['es_titulo'])
            indent = "    " * max(0, (p['nivel'] or 1) - 1)
            if es_tit:
                self._add_titulo_row(p, indent, p['nivel'] or 1)
            else:
                self._add_partida_header_row(p, indent)
                filas = planilla.get(p['id'], [])
                if filas:
                    for i, f in enumerate(filas, 1):
                        self._add_dim_row(i, f, p['id'])
                self._add_total_row(p)

        tbl.setUpdatesEnabled(True)
        self._loading = False

    # ── Helpers de creación de filas ───────────────────────────────────────
    def _add_titulo_row(self, p, indent: str, nivel: int):
        tbl = self.tbl
        row = tbl.rowCount()
        tbl.insertRow(row)
        # Formato espejo del Presupuesto: color por nivel; N1 rojo subrayado.
        bg = QColor(NIVEL_BG.get(nivel, "#F8F9FA"))
        fg = QColor(NIVEL_COL.get(nivel, SLATE_700))
        f = QFont(); f.setBold(True)
        if nivel == 1:
            f.setPointSize(10)
            f.setUnderline(True)

        for c in range(len(COLS)):
            txt = ""
            if c == 0:
                txt = p['item'] or ''
            elif c == 1:
                txt = indent + (p['descripcion'] or '')
            it = QTableWidgetItem(txt)
            it.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            it.setBackground(QBrush(bg))
            it.setForeground(QBrush(fg))   # item y descripción mismo color
            it.setFont(f)
            tbl.setItem(row, c, it)
        self._row_kind.append('title')
        self._row_partida.append(-1)

    def _add_partida_header_row(self, p, indent: str):
        tbl = self.tbl
        row = tbl.rowCount()
        tbl.insertRow(row)
        bg = QColor(BLUE_HEAD)
        fg = QColor(SLATE_700)
        f_b = QFont(); f_b.setBold(True)

        # Item — mismo color que la descripción
        it_item = QTableWidgetItem(p['item'] or '')
        it_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        it_item.setBackground(QBrush(bg))
        it_item.setForeground(QBrush(fg))
        f2 = QFont(); f2.setBold(True); f2.setPointSize(10)
        it_item.setFont(f2)
        tbl.setItem(row, 0, it_item)

        # Descripción
        it_desc = QTableWidgetItem(indent + (p['descripcion'] or ''))
        it_desc.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        it_desc.setBackground(QBrush(bg))
        it_desc.setForeground(QBrush(fg))
        it_desc.setFont(f_b)
        tbl.setItem(row, 1, it_desc)

        # Unidad
        it_und = QTableWidgetItem(p['unidad'] or '—')
        it_und.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        it_und.setBackground(QBrush(bg))
        it_und.setForeground(QBrush(QColor(SLATE_300)))
        it_und.setTextAlignment(Qt.AlignCenter)
        tbl.setItem(row, 2, it_und)

        # cols 3-9 vacías con fondo
        for c in range(3, 10):
            it = QTableWidgetItem("")
            it.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            it.setBackground(QBrush(bg))
            tbl.setItem(row, c, it)

        # col 10 — total de la partida
        total = float(p['metrado'] or 0)
        it_tot = QTableWidgetItem(self._fmt_total(total))
        it_tot.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        it_tot.setBackground(QBrush(bg))
        it_tot.setForeground(QBrush(QColor("#000000")))   # negro
        f3 = QFont(); f3.setBold(True)
        it_tot.setFont(f3)
        it_tot.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        tbl.setItem(row, 10, it_tot)
        self._row_kind.append('header')
        self._row_partida.append(p['id'])

    @staticmethod
    def _fmt_total(total: float) -> str:
        """Formato para la columna Total: vacío si 0, decimales de metrado."""
        if not total:
            return ""
        return f"{total:,.{get_decimales_metrado()}f}"

    @staticmethod
    def _fmt2(v) -> str:
        """Valor del metrado: vacío si None/0, decimales de metrado."""
        if v is None or v == 0:
            return ""
        return f"{float(v):,.{get_decimales_metrado()}f}"

    def _add_dim_row(self, n: int, f: dict, partida_id: int):
        tbl = self.tbl
        row = tbl.rowCount()
        tbl.insertRow(row)
        # Flags: read-only por defecto; columnas editables solo si el estado
        # del proyecto lo permite (en aprobado/ejecutado todo queda bloqueado).
        ro_flag  = Qt.ItemIsSelectable | Qt.ItemIsEnabled
        ed_flag  = (ro_flag | Qt.ItemIsEditable) if self._editable else ro_flag

        # # de fila en col 0 (read-only). Guarda metrado_id + partida_id en UserRole.
        it_n = QTableWidgetItem(str(n))
        it_n.setFlags(ro_flag)
        it_n.setForeground(QBrush(QColor(SLATE_300)))
        it_n.setTextAlignment(Qt.AlignCenter)
        it_n.setData(Qt.UserRole, {
            'metrado_id': f.get('id'),
            'partida_id': partida_id,
        })
        tbl.setItem(row, 0, it_n)

        # Descripción (editable)
        it_d = QTableWidgetItem(f.get('descripcion') or '')
        it_d.setFlags(ed_flag)
        tbl.setItem(row, 1, it_d)

        # Und. (vacío, read-only)
        it_u = QTableWidgetItem("")
        it_u.setFlags(ro_flag)
        tbl.setItem(row, 2, it_u)

        # N°Est, N°Elem, Área, Largo, Ancho, Alto (editables) — siempre 2 dec.
        for c, key in [
            (3, 'n_estructuras'), (4, 'n_elementos'), (5, 'area'),
            (6, 'largo'), (7, 'ancho'), (8, 'alto'),
        ]:
            it = QTableWidgetItem(self._fmt2(f.get(key)))
            it.setFlags(ed_flag)
            it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            tbl.setItem(row, c, it)

        # Parcial (calculado, read-only)
        parcial = float(f.get('parcial') or 0)
        it_p = QTableWidgetItem(self._fmt2(parcial))
        it_p.setFlags(ro_flag)
        it_p.setBackground(QBrush(QColor(SILVER_100)))
        it_p.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        f_b = QFont(); f_b.setWeight(QFont.DemiBold)
        it_p.setFont(f_b)
        it_p.setForeground(QBrush(QColor(SLATE_700)))
        tbl.setItem(row, 9, it_p)

        # Total — vacío en filas de detalle (read-only)
        it_t = QTableWidgetItem("")
        it_t.setFlags(ro_flag)
        tbl.setItem(row, 10, it_t)

        self._row_kind.append('dim')
        self._row_partida.append(partida_id)

    def _add_total_row(self, p):
        """Fila de total de partida (solo si tiene filas de detalle)."""
        # Skip si la cabecera ya muestra el total y no hay un patrón de
        # subrayado distinto en HTML/Flask. Mantenemos solo cabecera para
        # un look más compacto.
        return

    # ── Edición estilo Excel ───────────────────────────────────────────────
    def _parse_num(self, txt: str):
        """Devuelve float o None. Acepta coma como separador decimal."""
        if not txt or not txt.strip():
            return None
        try:
            return float(txt.replace(',', '.'))
        except ValueError:
            return None

    def _find_header_row(self, partida_id: int) -> int | None:
        for r, (kind, pid) in enumerate(zip(self._row_kind, self._row_partida)):
            if kind == 'header' and pid == partida_id:
                return r
        return None

    def _dim_rows_of(self, partida_id: int) -> list[int]:
        return [r for r, (k, pid) in enumerate(zip(self._row_kind, self._row_partida))
                if k == 'dim' and pid == partida_id]

    def _on_item_changed(self, item):
        """Recalcula parcial + total + persiste a DB cuando el usuario edita una celda."""
        if self._loading:
            return
        row = item.row()
        if row >= len(self._row_kind) or self._row_kind[row] != 'dim':
            return
        partida_id = self._row_partida[row]
        try:
            self._guardar_fila(row, partida_id)
        except Exception:
            import traceback; traceback.print_exc()

    def _guardar_fila(self, row: int, partida_id: int):
        if not self._editable:
            return
        tbl = self.tbl
        dec = get_decimales_metrado()
        # Leer datos de la fila
        desc  = (tbl.item(row, 1).text() if tbl.item(row, 1) else '').strip()
        n_est = self._parse_num(tbl.item(row, 3).text() if tbl.item(row, 3) else '')
        n_el  = self._parse_num(tbl.item(row, 4).text() if tbl.item(row, 4) else '')
        area  = self._parse_num(tbl.item(row, 5).text() if tbl.item(row, 5) else '')
        largo = self._parse_num(tbl.item(row, 6).text() if tbl.item(row, 6) else '')
        ancho = self._parse_num(tbl.item(row, 7).text() if tbl.item(row, 7) else '')
        alto  = self._parse_num(tbl.item(row, 8).text() if tbl.item(row, 8) else '')

        dims = [x for x in [n_est, n_el, area, largo, ancho, alto] if x is not None]
        parcial = 1.0
        for d in dims:
            parcial *= d
        parcial = _rn(parcial, dec) if dims else 0.0

        # Actualizar parcial + reformatear dimensiones a 2 decimales (sin
        # re-disparar itemChanged).
        self._loading = True
        it_p = tbl.item(row, 9)
        if it_p:
            it_p.setText(self._fmt2(parcial) if dims else "")
        for c, val in [(3, n_est), (4, n_el), (5, area),
                       (6, largo), (7, ancho), (8, alto)]:
            cell = tbl.item(row, c)
            if cell is not None:
                cell.setText(self._fmt2(val))
        self._loading = False

        # Persistir fila ↔ DB
        meta = tbl.item(row, 0).data(Qt.UserRole) or {}
        metrado_id = meta.get('metrado_id')
        is_empty = (not desc) and (not dims)

        conn = get_db()
        try:
            if is_empty:
                if metrado_id is not None:
                    conn.execute("DELETE FROM metrados_detalle WHERE id=?", (metrado_id,))
                    meta['metrado_id'] = None
                    self._loading = True
                    tbl.item(row, 0).setData(Qt.UserRole, meta)
                    self._loading = False
            elif metrado_id is None:
                cur = conn.execute(
                    """INSERT INTO metrados_detalle
                       (partida_id, orden, descripcion, n_estructuras, n_elementos,
                        area, largo, ancho, alto, parcial)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (partida_id, row, desc, n_est, n_el, area, largo, ancho, alto, parcial)
                )
                meta['metrado_id'] = cur.lastrowid
                self._loading = True
                tbl.item(row, 0).setData(Qt.UserRole, meta)
                self._loading = False
            else:
                conn.execute(
                    """UPDATE metrados_detalle SET
                          descripcion=?, n_estructuras=?, n_elementos=?,
                          area=?, largo=?, ancho=?, alto=?, parcial=?
                       WHERE id=?""",
                    (desc, n_est, n_el, area, largo, ancho, alto, parcial, metrado_id)
                )

            # Recalcular total de la partida sumando parciales de sus dim rows
            total = 0.0
            for r2 in self._dim_rows_of(partida_id):
                it = tbl.item(r2, 9)
                if it and it.text().strip():
                    try:
                        total += float(it.text().replace(',', ''))
                    except ValueError:
                        pass
            total = _rn(total, dec)
            conn.execute("UPDATE partidas SET metrado=? WHERE id=?",
                         (total, partida_id))
            conn.commit()
        finally:
            conn.close()

        # Actualizar header row col 10 (Total de la partida) en la UI
        hdr = self._find_header_row(partida_id)
        if hdr is not None:
            it_tot = tbl.item(hdr, 10)
            if it_tot:
                self._loading = True
                it_tot.setText(self._fmt_total(total))
                self._loading = False

    def _on_cell_double_clicked(self, row: int, col: int):
        """Doble clic en una fila de partida (header) inserta nueva dim row.
        En filas dim, Qt ya abre el editor por el editTrigger DoubleClicked
        (no hacemos nada extra). Las filas título se ignoran."""
        if row >= len(self._row_kind):
            return
        kind = self._row_kind[row]
        if kind == 'header':
            self._insertar_fila_bajo(self._row_partida[row])

    # ── Insertar / eliminar filas ──────────────────────────────────────────
    def _on_context_menu(self, pos):
        if not self._editable:
            return   # solo lectura: sin acciones de agregar/eliminar
        idx = self.tbl.indexAt(pos)
        if not idx.isValid():
            return
        row = idx.row()
        if row >= len(self._row_kind):
            return
        kind = self._row_kind[row]
        if kind == 'title':
            return  # filas de título no admiten acciones
        partida_id = self._row_partida[row]

        menu = QMenu(self)
        act_add = menu.addAction("➕  Agregar fila bajo esta partida")
        act_del = None
        sel_rows = sorted({i.row() for i in self.tbl.selectedIndexes()
                           if i.row() < len(self._row_kind)
                           and self._row_kind[i.row()] == 'dim'})
        if sel_rows:
            n = len(sel_rows)
            act_del = menu.addAction(f"🗑  Eliminar {n} fila{'s' if n>1 else ''}  (Supr)")
        menu.addSeparator()
        act_acero = menu.addAction("🔩  Cambiar a planilla de acero")

        chosen = menu.exec(self.tbl.viewport().mapToGlobal(pos))
        if chosen is act_add:
            self._insertar_fila_bajo(partida_id)
        elif chosen is act_del and act_del is not None:
            self._eliminar_filas(sel_rows)
        elif chosen is act_acero:
            self._cambiar_planilla(partida_id, 'acero')

    def _insertar_fila_bajo(self, partida_id: int):
        """Inserta una fila de dimensión vacía después de la última dim row de la partida
        (o justo después del header si no tiene dims). Pone el foco en la columna
        Descripción de la nueva fila."""
        if not self._editable:
            return
        dim_rows = self._dim_rows_of(partida_id)
        if dim_rows:
            insert_at = max(dim_rows) + 1
        else:
            hdr = self._find_header_row(partida_id)
            if hdr is None:
                return
            insert_at = hdr + 1

        # Renumerar: contar dims previas para asignar el # de la nueva
        n_new = len(dim_rows) + 1

        tbl = self.tbl
        self._loading = True
        tbl.insertRow(insert_at)

        ro_flag = Qt.ItemIsSelectable | Qt.ItemIsEnabled
        ed_flag = ro_flag | Qt.ItemIsEditable

        it_n = QTableWidgetItem(str(n_new))
        it_n.setFlags(ro_flag)
        it_n.setForeground(QBrush(QColor(SLATE_300)))
        it_n.setTextAlignment(Qt.AlignCenter)
        it_n.setData(Qt.UserRole, {'metrado_id': None, 'partida_id': partida_id})
        tbl.setItem(insert_at, 0, it_n)

        it_d = QTableWidgetItem(""); it_d.setFlags(ed_flag)
        tbl.setItem(insert_at, 1, it_d)
        it_u = QTableWidgetItem(""); it_u.setFlags(ro_flag)
        tbl.setItem(insert_at, 2, it_u)
        for c in range(3, 9):
            it = QTableWidgetItem(""); it.setFlags(ed_flag)
            it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            tbl.setItem(insert_at, c, it)
        it_p = QTableWidgetItem(""); it_p.setFlags(ro_flag)
        it_p.setBackground(QBrush(QColor(SILVER_100)))
        it_p.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        tbl.setItem(insert_at, 9, it_p)
        it_t = QTableWidgetItem(""); it_t.setFlags(ro_flag)
        tbl.setItem(insert_at, 10, it_t)

        # Actualizar tracking
        self._row_kind.insert(insert_at, 'dim')
        self._row_partida.insert(insert_at, partida_id)
        self._loading = False

        # Renumerar las filas de dim subsecuentes (si insertamos en medio)
        self._renumerar_dims(partida_id)

        # Foco en la descripción de la nueva fila + abrir editor
        tbl.setCurrentCell(insert_at, 1)
        QTimer.singleShot(0, lambda: tbl.edit(tbl.currentIndex()))

    def _renumerar_dims(self, partida_id: int):
        """Reasigna el # de fila (col 0) según orden secuencial de las dim rows de la partida."""
        self._loading = True
        for i, r in enumerate(self._dim_rows_of(partida_id), 1):
            it = self.tbl.item(r, 0)
            if it:
                it.setText(str(i))
        self._loading = False

    def _eliminar_filas(self, rows: list[int]):
        """Elimina filas de dimensión (de la DB y la UI). Acepta una lista en cualquier orden."""
        if not self._editable or not rows:
            return
        # Validar que todas son dim rows
        rows = sorted([r for r in rows if 0 <= r < len(self._row_kind)
                       and self._row_kind[r] == 'dim'], reverse=True)
        if not rows:
            return

        # Set de partidas afectadas (para recalc totales después)
        partidas_afectadas = {self._row_partida[r] for r in rows}

        # Borrar de DB primero (los metrado_id que existan)
        ids_db = []
        for r in rows:
            meta = self.tbl.item(r, 0).data(Qt.UserRole) or {}
            mid = meta.get('metrado_id')
            if mid is not None:
                ids_db.append(mid)
        if ids_db:
            conn = get_db()
            try:
                conn.executemany("DELETE FROM metrados_detalle WHERE id=?",
                                 [(i,) for i in ids_db])
                conn.commit()
            finally:
                conn.close()

        # Borrar de la UI + tracking (en orden inverso para no des-indexar)
        self._loading = True
        for r in rows:
            self.tbl.removeRow(r)
            del self._row_kind[r]
            del self._row_partida[r]
        self._loading = False

        # Recalcular totales y renumerar dims de cada partida afectada
        dec = get_decimales_metrado()
        conn = get_db()
        try:
            for pid in partidas_afectadas:
                total = 0.0
                for r2 in self._dim_rows_of(pid):
                    it = self.tbl.item(r2, 9)
                    if it and it.text().strip():
                        try:
                            total += float(it.text().replace(',', ''))
                        except ValueError:
                            pass
                total = _rn(total, dec)
                conn.execute("UPDATE partidas SET metrado=? WHERE id=?",
                             (total, pid))
                # Actualizar header row col 10
                hdr = self._find_header_row(pid)
                if hdr is not None:
                    it_tot = self.tbl.item(hdr, 10)
                    if it_tot:
                        self._loading = True
                        it_tot.setText(self._fmt_total(total))
                        self._loading = False
                self._renumerar_dims(pid)
            conn.commit()
        finally:
            conn.close()

    def eventFilter(self, obj, event):
        """Supr en celdas editables (sin editar) → borra contenido (Excel-like).
        Funciona sobre la selección, y si la selección está vacía, sobre la
        celda actual (la que tiene el foco con flechas)."""
        from PySide6.QtCore import QEvent
        # Supr en la tabla de acero → borra celdas editables y re-guarda.
        if (obj is getattr(self, 'tbl_acero', None) and self._editable
                and event.type() == QEvent.KeyPress
                and event.key() == Qt.Key_Delete
                and event.modifiers() == Qt.NoModifier
                and self.tbl_acero.state() != QAbstractItemView.EditingState):
            indices = list(self.tbl_acero.selectedIndexes())
            if not indices:
                cur = self.tbl_acero.currentIndex()
                if cur.isValid():
                    indices = [cur]
            sel = [i for i in indices
                   if 0 <= i.row() < len(self._ac_kind)
                   and self._ac_kind[i.row()] == 'detail'
                   and i.column() in self._AC_EDIT_COLS]
            if sel:
                self._ac_loading = True
                pids = {}
                for idx in sel:
                    if self.tbl_acero.item(idx.row(), idx.column()):
                        self.tbl_acero.item(idx.row(), idx.column()).setText("")
                    pids[idx.row()] = self._ac_partida[idx.row()]
                self._ac_loading = False
                for r in {i.row() for i in sel}:
                    self._ac_recompute_row(r)
                for pid in set(pids.values()):
                    self._ac_guardar_partida(pid)
            return True
        if obj is self.tbl and event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Delete and event.modifiers() == Qt.NoModifier:
                if self.tbl.state() != QAbstractItemView.EditingState:
                    # Selección primero; si vacía, fallback a celda actual
                    indices = list(self.tbl.selectedIndexes())
                    if not indices:
                        cur = self.tbl.currentIndex()
                        if cur.isValid():
                            indices = [cur]
                    sel_items = [i for i in indices
                                 if 0 <= i.row() < len(self._row_kind)
                                 and self._row_kind[i.row()] == 'dim'
                                 and self.tbl.item(i.row(), i.column()) is not None
                                 and (self.tbl.item(i.row(), i.column()).flags()
                                      & Qt.ItemIsEditable)]
                    if sel_items:
                        rows_afectadas = {}  # row → partida_id
                        self._loading = True
                        for idx in sel_items:
                            self.tbl.item(idx.row(), idx.column()).setText("")
                            rows_afectadas[idx.row()] = self._row_partida[idx.row()]
                        self._loading = False
                        for r, pid in rows_afectadas.items():
                            self._guardar_fila(r, pid)
                    # Consumir SIEMPRE Supr para evitar que AnyKeyPressed abra el editor
                    return True
        return super().eventFilter(obj, event)

    # ── Acciones ────────────────────────────────────────────────────────────
    def _exportar_excel(self):
        from datetime import datetime
        import re
        nombre = self._proy.get('nombre') or 'proyecto'
        slug = re.sub(r'[^\w\s-]', '', nombre)[:40].strip()
        slug = re.sub(r'\s+', '_', slug) or "proyecto"
        fecha = datetime.now().strftime("%Y%m%d_%H%M")
        sugerido = f"{slug}_metrados_{fecha}.xlsx"

        path, _ = QFileDialog.getSaveFileName(
            self, "Exportar Hoja de Metrados", sugerido, "Excel (*.xlsx)"
        )
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        try:
            from core.exporter import exportar_metrados
            buf = exportar_metrados(self.pid)
            with open(path, "wb") as f:
                f.write(buf.getvalue())
        except Exception as e:
            import traceback; traceback.print_exc()
            QMessageBox.critical(self, "Error",
                                 f"No se pudo exportar:\n{e}")
            return
        QMessageBox.information(self, "Exportado",
                                f"Archivo guardado:\n{path}")

    def _imprimir(self):
        """Muestra una vista previa de impresión del PDF de metrados."""
        try:
            import tempfile, os
            from core.pdf_reports import generar_pdf_archivo
            tmp_pdf = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
            tmp_pdf.close()
            generar_pdf_archivo("metrados", self.pid, tmp_pdf.name)

            printer = QPrinter(QPrinter.HighResolution)
            dlg = QPrintPreviewDialog(printer, self)
            dlg.setWindowTitle("Vista previa — Hoja de Metrados")
            dlg.resize(900, 700)
            dlg.paintRequested.connect(
                lambda p: self._paint_pdf_a_printer(p, tmp_pdf.name)
            )
            dlg.exec()
            try:
                os.unlink(tmp_pdf.name)
            except Exception:
                pass
        except Exception as e:
            import traceback; traceback.print_exc()
            QMessageBox.critical(self, "Error",
                                 f"No se pudo preparar la impresión:\n{e}")

    def _paint_pdf_a_printer(self, printer, pdf_path: str):
        """Renderiza el PDF temporal página por página al QPrinter."""
        try:
            from PySide6.QtPdf import QPdfDocument
            doc = QPdfDocument(self)
            doc.load(pdf_path)
            from PySide6.QtGui import QPainter
            painter = QPainter(printer)
            for i in range(doc.pageCount()):
                if i > 0:
                    printer.newPage()
                size = doc.pagePointSize(i)
                page_image = doc.render(
                    i,
                    (int(size.width() * 2), int(size.height() * 2))
                )
                target = printer.pageRect(QPrinter.DevicePixel)
                painter.drawImage(target, page_image)
            painter.end()
        except Exception as e:
            import traceback; traceback.print_exc()
            QMessageBox.warning(self, "Error de impresión", str(e))
