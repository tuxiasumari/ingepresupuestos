# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""Diálogo para buscar/crear recursos y agregarlos al ACU de una partida."""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
    QLineEdit, QPushButton, QTableWidget, QTableWidgetItem,
    QComboBox, QHeaderView, QAbstractItemView, QTabWidget,
    QWidget, QMessageBox, QFrame, QCompleter
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont

from core.config import DB_PATH, TIPOS_RECURSO
from core.database import (get_db, _rn, _recalcular_pu, _siguiente_codigo_inei,
                           precio_recurso_en_proyecto, get_decimales_cant_acu)
from utils.formatting import parse_num

_TIPO_BG  = {'MO': '#FFF3CD', 'MAT': '#D1E7DD', 'EQ':  '#CCE5FF',
             'SC': '#E5D6F8'}
_TIPO_FG  = {'MO': '#856404', 'MAT': '#0F5132', 'EQ':  '#084298',
             'SC': '#6A36B1'}


def _es_por_hora(tipo: str, unidad: str | None) -> bool:
    """True si la cantidad se deriva de la cuadrilla: MO y equipo por hora (hh/hm).
    Fórmula canónica: cant = cuadrilla / rendimiento × jornada."""
    u = (unidad or '').strip().lower()
    return (tipo == 'MO'
            or u in ('hh', 'hm', 'h-h', 'h-m', 'jph', 'jh')
            or 'hora' in u)


def _es_por_dia(tipo: str, unidad: str | None) -> bool:
    """True si la cantidad se deriva de la cuadrilla SIN jornada: MO/EQ con
    unidad día/jor (el rendimiento ya es por día): cant = cuadrilla / rend."""
    u = (unidad or '').strip().rstrip('.').lower()
    return (tipo in ('MO', 'EQ')
            and u in ('día', 'dia', 'días', 'dias', 'jor', 'jornada'))


def _es_partida_global(unidad: str | None) -> bool:
    """True si la PARTIDA es global (glb/est/serv): el ACU no usa
    cuadrilla/rendimiento; la cantidad se llena directa (PowerCost)."""
    u = (unidad or '').strip().rstrip('.').lower()
    return u in ('glb', 'gbl', 'est', 'serv')


class RecursoSelectorDialog(QDialog):
    """Buscar recursos del catálogo (checkboxes) o crear uno nuevo y agregarlos al ACU."""

    def __init__(self, part_id: int, proyecto: dict, parent=None):
        super().__init__(parent)
        self.part_id  = part_id
        self.proyecto = proyecto
        self.setWindowTitle("Agregar recursos al ACU")
        self.resize(680, 520)
        self.setModal(True)
        self._recurso_ids: list[int] = []
        self._checked_ids: set[int] = set()
        self._usado_ids: set[int] = set()
        # Proyecto de la partida — para priorizar recursos ya usados (evita duplicados).
        conn = get_db()
        prow = conn.execute(
            "SELECT proyecto_id FROM partidas WHERE id=?", (part_id,)
        ).fetchone()
        conn.close()
        self._proyecto_id = prow['proyecto_id'] if prow else None
        self._build_ui()
        self._buscar()

    def showEvent(self, event):
        super().showEvent(event)
        # Cursor listo en "Buscar en catálogo" al abrir (menos clics)
        if not getattr(self, '_foco_inicial', False) and self.tabs.currentIndex() == 0:
            self._foco_inicial = True
            QTimer.singleShot(0, self.inp_buscar.setFocus)

    # ── UI ─────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        vl = QVBoxLayout(self)
        vl.setContentsMargins(14, 14, 14, 14)
        vl.setSpacing(10)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._tab_buscar(), "Buscar en catálogo")
        self.tabs.addTab(self._tab_nuevo(),  "Crear nuevo recurso")
        vl.addWidget(self.tabs)

        # Barra inferior: contador + botones
        btns = QHBoxLayout()

        self.lbl_sel = QLabel("Sin selección")
        self.lbl_sel.setStyleSheet(
            "color:#485a6c; font-size:11px; font-weight:600;"
            " background:#E9ECEF; border-radius:4px; padding:2px 10px;"
        )
        btns.addWidget(self.lbl_sel)
        btns.addStretch()

        btn_can = QPushButton("Cancelar")
        btn_can.setFixedHeight(32)
        btn_can.clicked.connect(self.reject)
        btns.addWidget(btn_can)

        self.btn_agregar = QPushButton("✚  Agregar al ACU")
        self.btn_agregar.setFixedHeight(32)
        self.btn_agregar.setStyleSheet(
            "background:#485a6c; color:white; border:none;"
            " border-radius:6px; padding:0 20px; font-size:12px; font-weight:600;"
        )
        self.btn_agregar.clicked.connect(self._agregar)
        btns.addWidget(self.btn_agregar)
        vl.addLayout(btns)

    def _tab_buscar(self) -> QWidget:
        w = QWidget()
        vl = QVBoxLayout(w)
        vl.setContentsMargins(8, 8, 8, 8)
        vl.setSpacing(6)

        # Barra de búsqueda
        hl = QHBoxLayout()
        self.inp_buscar = QLineEdit()
        self.inp_buscar.setPlaceholderText("Buscar por descripción, código…")
        self.inp_buscar.setMinimumHeight(32)
        self.inp_buscar.textChanged.connect(self._buscar)
        hl.addWidget(self.inp_buscar)

        self.cmb_tipo = QComboBox()
        self.cmb_tipo.setMinimumHeight(32)
        self.cmb_tipo.setFixedWidth(90)
        self.cmb_tipo.addItem("Todos", "")
        for t in TIPOS_RECURSO:
            self.cmb_tipo.addItem(t, t)
        self.cmb_tipo.currentIndexChanged.connect(self._buscar)
        hl.addWidget(self.cmb_tipo)

        btn_all = QPushButton("☑ Todos")
        btn_all.setFixedSize(70, 32)
        btn_all.setStyleSheet("font-size:11px;")
        btn_all.clicked.connect(self._marcar_todos)
        hl.addWidget(btn_all)

        btn_none = QPushButton("☐ Ninguno")
        btn_none.setFixedSize(80, 32)
        btn_none.setStyleSheet("font-size:11px;")
        btn_none.clicked.connect(self._desmarcar_todos)
        hl.addWidget(btn_none)
        vl.addLayout(hl)

        hint = QLabel(
            "Los recursos ya usados en este proyecto aparecen primero y resaltados "
            "en verde — reutilízalos para no duplicar insumos."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(
            "color:#0F5132; font-size:10px; background:transparent; border:none;"
        )
        vl.addWidget(hint)

        # Tabla con checkbox en col 0
        cols = ["", "Código", "Descripción", "Tipo", "Unidad", "Precio ref."]
        self.tbl = QTableWidget(0, len(cols))
        self.tbl.setHorizontalHeaderLabels(cols)
        self.tbl.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.tbl.setColumnWidth(0, 28)   # checkbox
        self.tbl.setColumnWidth(1, 72)   # código
        self.tbl.setColumnWidth(3, 46)   # tipo
        self.tbl.setColumnWidth(4, 46)   # unidad
        self.tbl.setColumnWidth(5, 100)  # precio
        self.tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl.setSelectionMode(QAbstractItemView.NoSelection)
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setShowGrid(True)
        self.tbl.setAlternatingRowColors(False)
        self.tbl.itemClicked.connect(self._toggle_check)
        self.tbl.setStyleSheet("""
            QTableWidget { font-size:11px; border:1px solid #DEE2E6; }
            QTableWidget::item { padding:2px 4px; }
            QTableWidget::item:hover { background:#F0F4FF; }
            QHeaderView::section {
                background:#485a6c; color:white; font-size:10px;
                font-weight:bold; padding:4px; border:none;
                border-right:1px solid #5a6c7e;
            }
        """)
        vl.addWidget(self.tbl)

        # Cuadrilla / Cantidad
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color:#DEE2E6;")
        vl.addWidget(sep)

        form = QHBoxLayout()
        form.setSpacing(16)

        lbl_mo = QLabel("MO — Cuadrilla:")
        lbl_mo.setStyleSheet("color:#856404; font-size:11px; font-weight:600;")
        self.inp_cuad_b = QLineEdit("1.000")
        self.inp_cuad_b.setFixedWidth(72)
        form.addWidget(lbl_mo)
        form.addWidget(self.inp_cuad_b)

        lbl_mat = QLabel("MAT/EQ — Cantidad:")
        lbl_mat.setStyleSheet("color:#0F5132; font-size:11px; font-weight:600;")
        self.inp_cant_b = QLineEdit("0.0000")
        self.inp_cant_b.setFixedWidth(72)
        form.addWidget(lbl_mat)
        form.addWidget(self.inp_cant_b)
        form.addStretch()
        vl.addLayout(form)

        return w

    def _tab_nuevo(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(12, 12, 12, 12)
        form.setSpacing(10)

        self.inp_n_desc = QLineEdit()
        self.inp_n_desc.setPlaceholderText("Descripción del recurso")
        form.addRow("Descripción *:", self.inp_n_desc)

        self.cmb_n_tipo = QComboBox()
        for t in TIPOS_RECURSO:
            self.cmb_n_tipo.addItem(t, t)
        self.cmb_n_tipo.currentIndexChanged.connect(self._on_tipo_nuevo)
        form.addRow("Tipo *:", self.cmb_n_tipo)

        # ── Índice INEI — obligatorio ──────────────��─────────────────
        _INEI_OPTS = [
            ("",    "— Seleccione índice INEI —"),
            ("01",  "01 — Aceite"),
            ("02",  "02 — Acero de construcción liso"),
            ("03",  "03 — Acero de construcción corrugado"),
            ("04",  "04 — Agregado fino"),
            ("05",  "05 — Agregado grueso"),
            ("06",  "06 — Alambre y cable de cobre desnudo"),
            ("07",  "07 — Alambre y cable tipo TW y THW"),
            ("08",  "08 — Alambre y cable tipo WP"),
            ("09",  "09 — Alcantarilla metálica"),
            ("10",  "10 — Aparato sanitario con grifería"),
            ("11",  "11 — Artefacto de alumbrado exterior"),
            ("12",  "12 — Artefacto de alumbrado interior"),
            ("13",  "13 — Asfalto"),
            ("14",  "14 — Baldosa acústica"),
            ("15",  "15 — Baldosa asfáltica"),
            ("16",  "16 — Baldosa vinílica"),
            ("17",  "17 — Bloque y ladrillo"),
            ("18",  "18 — Cable telefónico"),
            ("19",  "19 — Cable NYY-N2XY"),
            ("20",  "20 — Cemento asfáltico"),
            ("21",  "21 — Cemento Portland tipo I"),
            ("22",  "22 — Cemento Portland tipo II"),
            ("23",  "23 — Cemento Portland tipo V"),
            ("24",  "24 — Cerámica esmaltada y sin esmaltar"),
            ("26",  "26 — Cerrajería nacional"),
            ("27",  "27 — Detonante"),
            ("28",  "28 — Dinamita"),
            ("29",  "29 — Dólar"),
            ("30",  "30 — Dólar más inflación USA / General ponderado"),
            ("31",  "31 — Ducto de concreto"),
            ("32",  "32 — Flete terrestre"),
            ("33",  "33 — Flete aéreo"),
            ("34",  "34 — Gasolina"),
            ("37",  "37 — Herramienta manual"),
            ("38",  "38 — Hormigón"),
            ("39",  "39 — Índice general de precios al consumidor (IPC)"),
            ("40",  "40 — Loseta"),
            ("41",  "41 — Madera en tiras para piso"),
            ("42",  "42 — Madera importada para encofrado y carpintería"),
            ("43",  "43 — Madera nacional para encofrado y carpintería"),
            ("44",  "44 — Madera terciada para encofrado y carpintería"),
            ("45",  "45 — Madera terciada para encofrado"),
            ("46",  "46 — Malla de acero"),
            ("47",  "47 — Mano de obra (incluido leyes sociales)"),
            ("48",  "48 — Maquinaria y equipo nacional"),
            ("49",  "49 — Maquinaria y equipo importado"),
            ("50",  "50 — Marco y tapa de hierro fundido"),
            ("51",  "51 — Perfil de acero liviano"),
            ("52",  "52 — Perfil de aluminio"),
            ("53",  "53 — Petróleo diesel"),
            ("54",  "54 — Pintura látex"),
            ("55",  "55 — Pintura temple"),
            ("56",  "56 — Plancha de Aero LAC"),
            ("57",  "57 — Plancha de Aero LAF"),
            ("59",  "59 — Plancha de fibro-cemento"),
            ("60",  "60 — Plancha de poliuretano"),
            ("61",  "61 — Plancha galvanizada"),
            ("62",  "62 — Poste de concreto"),
            ("64",  "64 — Terrazo"),
            ("65",  "65 — Tubería de acero negro y/o galvanizado"),
            ("66",  "66 — Tubería de PVC para agua potable y alcantarillado"),
            ("68",  "68 — Tubería de cobre"),
            ("69",  "69 — Tubería de concreto simple"),
            ("70",  "70 — Tubería de concreto reforzado"),
            ("71",  "71 — Tubería de fierro fundido"),
            ("72",  "72 — Tubería de PVC para agua"),
            ("73",  "73 — Ducto telefónico de PVC"),
            ("74",  "74 — Tubería de PVC para electricidad (SAP)"),
            ("77",  "77 — Válvula de bronce nacional"),
            ("78",  "78 — Válvula de fierro fundido nacional"),
            ("79",  "79 — Vidrio incoloro nacional"),
            ("80",  "80 — Concreto premezclado"),
            ("OTRO", "Otro (ingresar manualmente)"),
        ]
        self.cmb_n_inei = QComboBox()
        for val, lbl in _INEI_OPTS:
            self.cmb_n_inei.addItem(lbl, val)
        self.cmb_n_inei.currentIndexChanged.connect(self._on_inei_nuevo)

        lbl_inei = QLabel("Índice INEI *:")
        lbl_inei.setStyleSheet("font-weight:600;")
        form.addRow(lbl_inei, self.cmb_n_inei)

        # Campo libre para índice manual (visible solo con "Otro")
        self.inp_n_inei = QLineEdit()
        self.inp_n_inei.setPlaceholderText("Código 2 dígitos, ej: 15")
        self.inp_n_inei.setMaxLength(2)
        self.inp_n_inei.setVisible(False)
        self.inp_n_inei.textChanged.connect(self._auto_codigo_nuevo)
        form.addRow("", self.inp_n_inei)

        # Código generado automáticamente (solo lectura)
        self.inp_n_codigo = QLineEdit()
        self.inp_n_codigo.setPlaceholderText("Se genera al seleccionar INEI")
        self.inp_n_codigo.setMaxLength(7)
        self.inp_n_codigo.setReadOnly(True)
        self.inp_n_codigo.setStyleSheet(
            "QLineEdit { background:#F5F5F5; color:#667885; border-radius:4px; padding:2px 6px; }"
        )
        form.addRow("Código INEI:", self.inp_n_codigo)

        self.inp_n_unidad = QLineEdit()
        self.inp_n_unidad.setPlaceholderText("hh, m³, kg, glb, …")
        _UNIDADES = sorted({
            "m","m²","m³","ml","km","cm","mm",
            "kg","tn","ton","lb",
            "und","glb","pza","pzas","jgo","cjt","vj","est",
            "hh","hm","h","hr","día","mes","sem",
            "lt","l","gal","bls","bol",
            "pie²","pie³","p2","p3","ha","pto","rll",
        })
        comp_u = QCompleter(_UNIDADES, self.inp_n_unidad)
        comp_u.setCaseSensitivity(Qt.CaseInsensitive)
        comp_u.setFilterMode(Qt.MatchContains)
        comp_u.setCompletionMode(QCompleter.PopupCompletion)
        comp_u.popup().setStyleSheet(
            "QListView { background:white; border:1px solid #D4D4D4;"
            " border-radius:6px; font-size:12px; padding:4px; color:#273445; }"
            "QListView::item { padding:4px 10px; }"
            "QListView::item:selected { background:#FEF5EB; color:#C0621A; }"
        )
        self.inp_n_unidad.setCompleter(comp_u)
        form.addRow("Unidad:", self.inp_n_unidad)

        self.inp_n_precio = QLineEdit("0.00")
        form.addRow("Precio:", self.inp_n_precio)

        self.inp_n_cuad = QLineEdit("1.000")
        self.inp_n_cuad.setMaximumWidth(80)
        form.addRow("Cuadrilla:", self.inp_n_cuad)

        self.inp_n_cant = QLineEdit("0.0000")
        self.inp_n_cant.setMaximumWidth(80)
        form.addRow("Cantidad:", self.inp_n_cant)

        self.lbl_n_error = QLabel("")
        self.lbl_n_error.setStyleSheet("color:#dc3545; font-size:11px;")
        form.addRow("", self.lbl_n_error)

        # Inicializar código con tipo por defecto
        self._on_tipo_nuevo()
        return w

    # ── Lógica de búsqueda y checkboxes ────────────────────────────────────────

    def _buscar(self):
        from utils.formatting import norm_busqueda
        texto = self.inp_buscar.text().strip() if hasattr(self, 'inp_buscar') else ""
        tipo  = self.cmb_tipo.currentData() if hasattr(self, 'cmb_tipo') else ""

        query  = ("SELECT r.*, EXISTS("
                  "  SELECT 1 FROM acu_items ai JOIN partidas p ON p.id = ai.partida_id"
                  "  WHERE ai.recurso_id = r.id AND p.proyecto_id = ?) AS usado"
                  " FROM recursos r WHERE 1=1")
        params = [self._proyecto_id]
        if tipo:
            query += " AND r.tipo=?"
            params.append(tipo)
        if texto:
            query += " AND (_norm(r.descripcion) LIKE ? OR _norm(r.codigo) LIKE ?)"
            like = f"%{norm_busqueda(texto)}%"
            params += [like, like]
        # Recursos ya usados en este proyecto primero (evita duplicar insumos).
        query += " ORDER BY usado DESC, r.tipo, r.descripcion LIMIT 300"

        conn = get_db()
        conn.create_function("_norm", 1, norm_busqueda)
        rows = conn.execute(query, params).fetchall()
        conn.close()

        self.tbl.blockSignals(True)
        self.tbl.setRowCount(0)
        self._recurso_ids = []
        self._usado_ids = set()

        for row in rows:
            r = self.tbl.rowCount()
            self.tbl.insertRow(r)
            self.tbl.setRowHeight(r, 22)
            self._recurso_ids.append(row['id'])
            tipo_r = row['tipo'] or ''
            bg  = QColor(_TIPO_BG.get(tipo_r, '#FFFFFF'))
            es_usado = bool(row['usado'])
            if es_usado:
                self._usado_ids.add(row['id'])
            bg_light = QColor('#C8EFD4') if es_usado else QColor('#FFFFFF')

            # Col 0: checkbox — restaurar si estaba marcado antes de la búsqueda
            marcado = row['id'] in self._checked_ids
            chk = QTableWidgetItem()
            chk.setCheckState(Qt.Checked if marcado else Qt.Unchecked)
            chk.setTextAlignment(Qt.AlignCenter)
            chk.setBackground(bg_light)
            self.tbl.setItem(r, 0, chk)

            # Col 1: código
            it_cod = QTableWidgetItem(row['codigo'] or '')
            it_cod.setBackground(bg_light)
            it_cod.setForeground(QColor('#495057'))
            it_cod.setFont(QFont('', 9))
            self.tbl.setItem(r, 1, it_cod)

            # Col 2: descripción
            it_desc = QTableWidgetItem(
                ("✓  " if es_usado else "") + (row['descripcion'] or '')
            )
            it_desc.setBackground(bg_light)
            if es_usado:
                it_desc.setForeground(QColor('#0F5132'))
                it_desc.setFont(QFont('', 10, QFont.Bold))
                it_desc.setToolTip("Ya usado en este proyecto — reutilízalo para no duplicar")
            self.tbl.setItem(r, 2, it_desc)

            # Col 3: tipo badge con color
            it_tipo = QTableWidgetItem(tipo_r)
            it_tipo.setBackground(bg)
            it_tipo.setForeground(QColor(_TIPO_FG.get(tipo_r, '#333')))
            it_tipo.setTextAlignment(Qt.AlignCenter)
            it_tipo.setFont(QFont('', 9, QFont.Bold))
            self.tbl.setItem(r, 3, it_tipo)

            # Col 4: unidad
            it_und = QTableWidgetItem(row['unidad'] or '')
            it_und.setBackground(bg_light)
            it_und.setTextAlignment(Qt.AlignCenter)
            self.tbl.setItem(r, 4, it_und)

            # Col 5: precio
            it_pre = QTableWidgetItem(f"{row['precio'] or 0:.4f}")
            it_pre.setBackground(bg_light)
            it_pre.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.tbl.setItem(r, 5, it_pre)

            if marcado:
                self._pintar_fila(r, True)

        self.tbl.blockSignals(False)
        self._actualizar_contador()

    def _toggle_check(self, item: QTableWidgetItem):
        row = item.row()
        chk = self.tbl.item(row, 0)
        if chk is None or row >= len(self._recurso_ids):
            return
        nuevo = Qt.Unchecked if chk.checkState() == Qt.Checked else Qt.Checked
        chk.setCheckState(nuevo)
        rid = self._recurso_ids[row]
        if nuevo == Qt.Checked:
            self._checked_ids.add(rid)
        else:
            self._checked_ids.discard(rid)
        self._pintar_fila(row, nuevo == Qt.Checked)
        self._actualizar_contador()

    def _pintar_fila(self, row: int, marcada: bool):
        bg_check = QColor('#EBF5FF')
        rid = self._recurso_ids[row] if row < len(self._recurso_ids) else None
        bg_normal = QColor('#C8EFD4') if rid in self._usado_ids else QColor('#FFFFFF')
        for c in range(1, self.tbl.columnCount()):
            it = self.tbl.item(row, c)
            if it:
                # col 3 (tipo badge) mantiene su color propio
                if c == 3:
                    tipo_r = it.text()
                    it.setBackground(QColor(_TIPO_BG.get(tipo_r, '#FFFFFF'))
                                     if not marcada else QColor('#BEE3F8'))
                else:
                    it.setBackground(bg_check if marcada else bg_normal)

    def _marcar_todos(self):
        self.tbl.blockSignals(True)
        for r in range(self.tbl.rowCount()):
            chk = self.tbl.item(r, 0)
            if chk:
                chk.setCheckState(Qt.Checked)
                self._pintar_fila(r, True)
                if r < len(self._recurso_ids):
                    self._checked_ids.add(self._recurso_ids[r])
        self.tbl.blockSignals(False)
        self._actualizar_contador()

    def _desmarcar_todos(self):
        self.tbl.blockSignals(True)
        for r in range(self.tbl.rowCount()):
            chk = self.tbl.item(r, 0)
            if chk:
                chk.setCheckState(Qt.Unchecked)
                self._pintar_fila(r, False)
                if r < len(self._recurso_ids):
                    self._checked_ids.discard(self._recurso_ids[r])
        self.tbl.blockSignals(False)
        self._actualizar_contador()

    def _filas_marcadas(self) -> list[int]:
        return [
            r for r in range(self.tbl.rowCount())
            if self.tbl.item(r, 0) and
               self.tbl.item(r, 0).checkState() == Qt.Checked
        ]

    def _actualizar_contador(self):
        if not hasattr(self, 'lbl_sel'):
            return
        n = len(self._checked_ids)
        if n == 0:
            self.lbl_sel.setText("Sin selección")
            self.lbl_sel.setStyleSheet(
                "color:#6c757d; font-size:11px; font-weight:600;"
                " background:#E9ECEF; border-radius:4px; padding:2px 10px;"
            )
        else:
            self.lbl_sel.setText(f"✔  {n} recurso{'s' if n > 1 else ''} seleccionado{'s' if n > 1 else ''}")
            self.lbl_sel.setStyleSheet(
                "color:#0F5132; font-size:11px; font-weight:600;"
                " background:#D1E7DD; border-radius:4px; padding:2px 10px;"
            )

    # ── Agregar ────────────────────────────────────────────────────────────────

    def _agregar(self):
        if self.tabs.currentIndex() == 0:
            self._agregar_existentes()
        else:
            self._agregar_nuevo()

    def _agregar_existentes(self):
        if not self._checked_ids:
            QMessageBox.warning(self, "Selección",
                                "Marque al menos un recurso con el checkbox.")
            return

        try:
            cuad = parse_num(self.inp_cuad_b.text())
            cant = parse_num(self.inp_cant_b.text())
        except Exception:
            cuad = cant = 0.0

        conn = get_db()
        partida = conn.execute(
            "SELECT rendimiento, proyecto_id, unidad FROM partidas WHERE id=?",
            (self.part_id,)
        ).fetchone()
        if not partida:
            conn.close()
            return

        proy = conn.execute(
            "SELECT jornada_laboral FROM proyectos WHERE id=?",
            (partida['proyecto_id'],)
        ).fetchone()
        jornada = (proy['jornada_laboral'] if proy else None) or 8
        rend    = partida['rendimiento'] or 1
        es_global = _es_partida_global(partida['unidad'])

        for recurso_id in self._checked_ids:
            rec = conn.execute(
                "SELECT tipo, unidad, precio FROM recursos WHERE id=?", (recurso_id,)
            ).fetchone()
            if not rec:
                continue

            if not es_global and _es_por_dia(rec['tipo'], rec['unidad']):
                cuadrilla_real = cuad
                cantidad_real  = _rn(cuad / rend, get_decimales_cant_acu()) if cuad > 0 else cant
            elif not es_global and _es_por_hora(rec['tipo'], rec['unidad']):
                cuadrilla_real = cuad
                cantidad_real  = (_rn(cuad / rend * jornada, get_decimales_cant_acu())
                                  if cuad > 0 else cant)
            else:
                cuadrilla_real = 0.0
                cantidad_real  = cant

            # Un insumo = un precio por proyecto: si el recurso ya se usa
            # en este proyecto, entra con ese precio (no el del catálogo).
            precio_ins = precio_recurso_en_proyecto(
                conn, partida['proyecto_id'], recurso_id)
            if precio_ins is None:
                precio_ins = rec['precio'] or 0

            conn.execute(
                "INSERT INTO acu_items "
                "(partida_id, recurso_id, cuadrilla, cantidad, precio) "
                "VALUES (?,?,?,?,?)",
                (self.part_id, recurso_id,
                 cuadrilla_real, cantidad_real, precio_ins)
            )

        _recalcular_pu(conn, self.part_id)
        conn.commit()
        conn.close()
        self.accept()

    def _agregar_nuevo(self):
        desc = self.inp_n_desc.text().strip()
        if not desc:
            self.lbl_n_error.setText("La descripción es obligatoria.")
            return

        inei = self._inei_actual()
        if not inei or len(inei) != 2:
            self.lbl_n_error.setText("El Índice INEI es obligatorio (2 dígitos).")
            if hasattr(self, 'cmb_n_inei'):
                self.cmb_n_inei.setFocus()
            return

        tipo   = self.cmb_n_tipo.currentData()
        unidad = self.inp_n_unidad.text().strip()
        precio = parse_num(self.inp_n_precio.text())
        codigo = self.inp_n_codigo.text().strip()

        conn = get_db()
        if not codigo:
            codigo = _siguiente_codigo_inei(conn, inei)

        cur = conn.execute(
            "INSERT INTO recursos "
            "(codigo, descripcion, tipo, unidad, precio, indice_inei) "
            "VALUES (?,?,?,?,?,?)",
            (codigo, desc, tipo, unidad, precio, inei)
        )
        recurso_id = cur.lastrowid
        conn.commit()

        try:
            cuad = parse_num(self.inp_n_cuad.text())
            cant = parse_num(self.inp_n_cant.text())
        except Exception:
            cuad = cant = 0.0

        partida = conn.execute(
            "SELECT rendimiento, proyecto_id, unidad FROM partidas WHERE id=?",
            (self.part_id,)
        ).fetchone()
        if (partida and not _es_partida_global(partida['unidad'])
                and (_es_por_dia(tipo, unidad) or _es_por_hora(tipo, unidad))
                and cuad > 0 and cant == 0):
            proy = conn.execute(
                "SELECT jornada_laboral FROM proyectos WHERE id=?",
                (partida['proyecto_id'],)
            ).fetchone()
            jornada = (proy['jornada_laboral'] if proy else None) or 8
            factor = 1 if _es_por_dia(tipo, unidad) else jornada
            cant = _rn(cuad / (partida['rendimiento'] or 1) * factor,
                       get_decimales_cant_acu())

        conn.execute(
            "INSERT INTO acu_items "
            "(partida_id, recurso_id, cuadrilla, cantidad, precio) "
            "VALUES (?,?,?,?,?)",
            (self.part_id, recurso_id, cuad, cant, precio)
        )
        _recalcular_pu(conn, self.part_id)
        conn.commit()
        conn.close()
        self.accept()

    def _inei_actual(self) -> str:
        """Devuelve el índice INEI seleccionado (del combo o del campo libre)."""
        if not hasattr(self, 'cmb_n_inei'):
            return ''
        val = self.cmb_n_inei.currentData()
        if val == 'OTRO':
            return self.inp_n_inei.text().strip() if hasattr(self, 'inp_n_inei') else ''
        return val or ''

    def _on_tipo_nuevo(self):
        """Al cambiar tipo, preselecciona el índice INEI por defecto del tipo."""
        if not hasattr(self, 'cmb_n_tipo') or not hasattr(self, 'cmb_n_inei'):
            return
        from core.config import INEI_DEFAULT
        tipo     = self.cmb_n_tipo.currentData()
        inei_def = INEI_DEFAULT.get(tipo, '39')
        # Buscar en el combo
        for i in range(self.cmb_n_inei.count()):
            if self.cmb_n_inei.itemData(i) == inei_def:
                self.cmb_n_inei.setCurrentIndex(i)
                return
        # Si no está, seleccionar "Otro" y poner en campo libre
        for i in range(self.cmb_n_inei.count()):
            if self.cmb_n_inei.itemData(i) == 'OTRO':
                self.cmb_n_inei.setCurrentIndex(i)
                if hasattr(self, 'inp_n_inei'):
                    self.inp_n_inei.setText(inei_def)
                return

    def _on_inei_nuevo(self):
        """Al cambiar el combo INEI, muestra/oculta campo libre y auto-genera código."""
        if not hasattr(self, 'cmb_n_inei'):
            return
        es_otro = self.cmb_n_inei.currentData() == 'OTRO'
        if hasattr(self, 'inp_n_inei'):
            self.inp_n_inei.setVisible(es_otro)
            if es_otro:
                self.inp_n_inei.setFocus()
                return  # código se genera cuando el usuario escribe
        self._auto_codigo_nuevo()

    def _auto_codigo_nuevo(self):
        inei = self._inei_actual() if hasattr(self, 'cmb_n_inei') else ''
        if len(inei) == 2:
            conn = get_db()
            self.inp_n_codigo.setText(_siguiente_codigo_inei(conn, inei))
            conn.close()
