# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""indices_inei_view — Histórico de Índices Unificados de Precios INEI.

Layout:
    - Topbar:        ← Inicio · Índices INEI · selector de área · botones
    - Split H:
        · Izquierda (sidebar): lista de 80 índices con búsqueda + KPIs
        · Derecha (centro):    tabla pivot año × meses del índice seleccionado
    - Acciones:      Importar Excel INEI · Exportar JSON · Importar JSON

Equivalente conceptual al módulo "Importación de Índices de Precios INEI 2026"
de Delphin Express.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QSize, QTimer, Signal
from PySide6.QtGui import QFont, QColor, QShortcut, QKeySequence
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QLineEdit, QComboBox,
    QPushButton, QListWidget, QListWidgetItem, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QSplitter, QFileDialog, QMessageBox,
    QSizePolicy, QApplication,
)

from core.indices_inei import (
    asegurar_seed, listar_indices, listar_areas,
    obtener_matriz, guardar_valor, guardar_valores, eliminar_valor,
    importar_excel_inei, exportar_json, importar_json,
    descargar_desde_url, importar_desde_texto,
    buscar_ultimo_excel_inei, descargar_ultimo_inei,
)
from utils.icons import icon
from utils.formatting import parse_num


# ── Paleta ────────────────────────────────────────────────────────────────────
ORANGE       = "#F37329"
ORANGE_DARK  = "#C0621A"
ORANGE_SOFT  = "#FEF5EB"
SLATE_700    = "#273445"
SLATE_500    = "#485A6C"
SLATE_300    = "#667885"
SILVER_50    = "#FBFBFC"
SILVER_100   = "#F8F9FA"
SILVER_200   = "#F0F1F2"
SILVER_300   = "#D4D4D4"
WHITE        = "#FFFFFF"
BLUE_700     = "#0D52BF"
GREEN_700    = "#16A34A"
GREEN_SOFT   = "#D1FAE5"

MESES_LARGOS = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun',
                'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']


class IndicesINEIView(QWidget):
    """Histórico de Índices Unificados de Precios INEI."""

    volver = Signal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setProperty("vista_nombre", "indices_inei")
        asegurar_seed()
        self._codigo_actual: str | None = None
        self._area_actual: str = '01'
        self._build()
        self._cargar_todo()

    # ── construcción UI ─────────────────────────────────────────────────────
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(12)

        # ── Topbar ──
        top = QHBoxLayout()
        top.setSpacing(10)

        ico_t = QLabel()
        ico_t.setPixmap(icon("rep-resumen").pixmap(28, 28))
        top.addWidget(ico_t)

        title = QLabel("Índices Unificados de Precios INEI")
        f = QFont(); f.setPointSize(15); f.setWeight(QFont.DemiBold)
        title.setFont(f)
        title.setStyleSheet(f"color:{SLATE_700};")
        top.addWidget(title)

        self.lbl_subt = QLabel("")
        self.lbl_subt.setStyleSheet(f"color:{SLATE_300}; padding-left:6px;")
        top.addWidget(self.lbl_subt)
        top.addStretch(1)

        # Selector de área
        lbl_a = QLabel("Área:")
        lbl_a.setStyleSheet(f"color:{SLATE_500}; font-weight:600;")
        top.addWidget(lbl_a)
        self.cmb_area = QComboBox()
        self.cmb_area.setMinimumWidth(280)
        self.cmb_area.currentIndexChanged.connect(self._on_area_change)
        top.addWidget(self.cmb_area)

        # Botones — ordenados de más automático a más manual
        self.btn_auto = self._mk_btn("Sincronizar con INEI", icon_name="importar",
                                      primary=True)
        self.btn_auto.setToolTip(
            "Detecta y descarga el último archivo oficial del INEI"
            " automáticamente"
        )
        self.btn_auto.clicked.connect(self._sincronizar_inei)
        top.addWidget(self.btn_auto)

        self.btn_url = self._mk_btn("URL", icon_name="importar")
        self.btn_url.setToolTip("Descargar desde URL específica")
        self.btn_url.clicked.connect(self._descargar_url)
        top.addWidget(self.btn_url)

        self.btn_pegar = self._mk_btn("Pegar datos", icon_name="copiar")
        self.btn_pegar.setToolTip("Pegar tabla desde portapapeles")
        self.btn_pegar.clicked.connect(self._pegar_datos)
        top.addWidget(self.btn_pegar)

        self.btn_imp_excel = self._mk_btn("Excel local", icon_name="folder")
        self.btn_imp_excel.clicked.connect(self._importar_excel)
        top.addWidget(self.btn_imp_excel)

        self.btn_imp_delphin = self._mk_btn("Delphin SQLite", icon_name="sqlite")
        self.btn_imp_delphin.setToolTip(
            "Importar histórico INEI desde una base de datos de Delphin Express"
        )
        self.btn_imp_delphin.clicked.connect(self._importar_delphin_sqlite)
        top.addWidget(self.btn_imp_delphin)

        self.btn_imp_json = self._mk_btn("JSON", icon_name="importar")
        self.btn_imp_json.setToolTip("Importar JSON")
        self.btn_imp_json.clicked.connect(self._importar_json)
        top.addWidget(self.btn_imp_json)

        self.btn_exp_json = self._mk_btn("Exportar", icon_name="exportar")
        self.btn_exp_json.setToolTip("Exportar a JSON")
        self.btn_exp_json.clicked.connect(self._exportar_json)
        top.addWidget(self.btn_exp_json)

        root.addLayout(top)

        # ── KPIs ──
        kpis = QHBoxLayout()
        kpis.setSpacing(10)
        self.kpi_indices = self._mk_kpi("Índices catálogo", "0", SLATE_500)
        self.kpi_con_datos = self._mk_kpi("Con valores cargados", "0", GREEN_700)
        self.kpi_valores = self._mk_kpi("Valores totales", "0", BLUE_700)
        from utils.theme import accent_color as _acc
        self.kpi_ultimo = self._mk_kpi("Último período cargado", "—", _acc())
        for k in (self.kpi_indices, self.kpi_con_datos,
                  self.kpi_valores, self.kpi_ultimo):
            kpis.addWidget(k, 1)
        root.addLayout(kpis)

        # ── Cuerpo: splitter izq (lista) + der (matriz año×mes) ──
        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        split.setStyleSheet(
            "QSplitter::handle { background: #D4D4D4; }"
            "QSplitter::handle:horizontal { width: 1px; }"
            "QSplitter::handle:hover { background: #F37329; }"
        )

        split.addWidget(self._build_panel_izq())
        split.addWidget(self._build_panel_der())
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 5)
        split.setSizes([280, 700])

        root.addWidget(split, 1)

    def _build_panel_izq(self) -> QWidget:
        fr = QFrame()
        fr.setStyleSheet(
            f"QFrame {{ background:{WHITE}; border:1px solid {SILVER_300};"
            f"  border-radius:6px; }}"
        )
        v = QVBoxLayout(fr)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # Header del panel
        hd = QFrame()
        hd.setStyleSheet(f"QFrame {{ background:{SLATE_500};"
                          f"  border-radius:6px 6px 0 0; }}")
        hl = QHBoxLayout(hd); hl.setContentsMargins(10, 7, 10, 7); hl.setSpacing(6)
        i_h = QLabel(); i_h.setPixmap(icon("rep-presupuesto").pixmap(14, 14))
        i_h.setStyleSheet("background:transparent; border:none;")
        hl.addWidget(i_h)
        l_h = QLabel("Índices")
        l_h.setStyleSheet(
            "color:white; font-weight:600; font-size:12px;"
            " background:transparent; border:none;"
        )
        hl.addWidget(l_h)
        hl.addStretch(1)
        v.addWidget(hd)

        # Búsqueda
        srh = QHBoxLayout()
        srh.setContentsMargins(8, 8, 8, 6)
        srh.setSpacing(6)
        ico_s = QLabel(); ico_s.setPixmap(icon("buscar").pixmap(14, 14))
        ico_s.setStyleSheet("background:transparent; border:none;")
        srh.addWidget(ico_s)
        self.inp_q = QLineEdit()
        self.inp_q.setPlaceholderText("Buscar por código o nombre…")
        self.inp_q.setClearButtonEnabled(True)
        self._timer_q = QTimer(self)
        self._timer_q.setSingleShot(True)
        self._timer_q.timeout.connect(self._refrescar_lista)
        self.inp_q.textChanged.connect(lambda _: self._timer_q.start(220))
        srh.addWidget(self.inp_q, 1)
        v.addLayout(srh)

        # Lista
        self.lst = QListWidget()
        self.lst.setStyleSheet(
            "QListWidget { border:none; background:white; }"
            "QListWidget::item { padding:6px 10px;"
            " border-bottom:1px solid #F0F1F2; }"
            "QListWidget::item:hover { background:#FEF5EB; }"
            "QListWidget::item:selected { background:#FFE4CC; color:#7A3800; }"
        )
        self.lst.itemSelectionChanged.connect(self._on_lst_change)
        v.addWidget(self.lst, 1)

        return fr

    def _build_panel_der(self) -> QWidget:
        fr = QFrame()
        fr.setStyleSheet(
            f"QFrame {{ background:{WHITE}; border:1px solid {SILVER_300};"
            f"  border-radius:6px; }}"
        )
        v = QVBoxLayout(fr)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # Header con título dinámico
        hd = QFrame()
        hd.setStyleSheet(f"QFrame {{ background:{SLATE_500};"
                          f"  border-radius:6px 6px 0 0; }}")
        hl = QHBoxLayout(hd); hl.setContentsMargins(10, 7, 10, 7); hl.setSpacing(8)
        i_h = QLabel(); i_h.setPixmap(icon("rep-curva-s").pixmap(14, 14))
        i_h.setStyleSheet("background:transparent; border:none;")
        hl.addWidget(i_h)
        self.lbl_titulo_matriz = QLabel("Selecciona un índice")
        self.lbl_titulo_matriz.setStyleSheet(
            "color:white; font-weight:600; font-size:12px;"
            " background:transparent; border:none;"
        )
        hl.addWidget(self.lbl_titulo_matriz)
        hl.addStretch(1)

        # Botones para agregar/quitar año
        btn_add_anio = QPushButton("Agregar año")
        btn_add_anio.setIcon(icon("add"))
        btn_add_anio.setIconSize(QSize(13, 13))
        btn_add_anio.setCursor(Qt.PointingHandCursor)
        btn_add_anio.setStyleSheet(
            "QPushButton { background:rgba(255,255,255,0.15); color:white;"
            " border:1px solid rgba(255,255,255,0.25); border-radius:4px;"
            " padding:4px 10px; font-size:11px; }"
            "QPushButton:hover { background:rgba(255,255,255,0.25); }"
        )
        btn_add_anio.clicked.connect(self._agregar_anio)
        hl.addWidget(btn_add_anio)
        v.addWidget(hd)

        # Tabla pivot: filas = años, cols = Ene..Dic + Anual (promedio)
        self.tbl = QTableWidget(0, 13)
        self.tbl.setHorizontalHeaderLabels(MESES_LARGOS + ["Promedio"])
        self.tbl.verticalHeader().setVisible(True)
        self.tbl.verticalHeader().setDefaultSectionSize(28)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.tbl.setEditTriggers(
            QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
            | QAbstractItemView.AnyKeyPressed
        )
        self.tbl.setAlternatingRowColors(True)
        self.tbl.setShowGrid(True)
        self.tbl.setStyleSheet(
            "QTableWidget { background:white; border:none;"
            " gridline-color: #ECECEC; font-size:12px; }"
            "QTableWidget::item { padding:4px 6px; }"
            "QTableWidget::item:selected { background:#FFE4CC; color:#7A3800; }"
            f"QHeaderView::section {{ background:{SILVER_100};"
            f"  color:{SLATE_500}; padding:6px 8px; border:none;"
            f"  border-right:1px solid {SILVER_300};"
            f"  border-bottom:1px solid {SILVER_300};"
            f"  font-size:11px; font-weight:700; }}"
        )
        h = self.tbl.horizontalHeader()
        for c in range(12):
            h.setSectionResizeMode(c, QHeaderView.Stretch)
        h.setSectionResizeMode(12, QHeaderView.Fixed)
        h.resizeSection(12, 90)
        self.tbl.itemChanged.connect(self._on_celda_cambiada)

        # Atajos
        QShortcut(QKeySequence("Delete"), self.tbl,
                  activated=self._eliminar_valor_seleccionado)
        v.addWidget(self.tbl, 1)

        return fr

    def _mk_btn(self, text: str, icon_name: str | None = None,
                primary: bool = False) -> QPushButton:
        b = QPushButton(text)
        b.setCursor(Qt.PointingHandCursor)
        b.setMinimumHeight(32)
        if icon_name:
            b.setIcon(icon(icon_name))
            b.setIconSize(QSize(16, 16))
        if primary:
            from utils.theme import BTN_PRIMARY_SS
            b.setStyleSheet(BTN_PRIMARY_SS)
        else:
            b.setStyleSheet(
                f"QPushButton {{ background:{WHITE}; color:{SLATE_700};"
                f"  border:1px solid {SILVER_300}; border-radius:6px;"
                f"  padding:6px 12px; font-size:12px; }}"
                f"QPushButton:hover {{ background:{ORANGE_SOFT};"
                f"  border-color:{ORANGE}; color:{ORANGE_DARK}; }}"
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
        v.setContentsMargins(14, 8, 14, 8)
        v.setSpacing(0)
        l_e = QLabel(etiqueta)
        l_e.setStyleSheet(
            f"color:{SLATE_300}; font-size:11px; letter-spacing:0.4px; "
            f"background:transparent; border:none;"
        )
        l_v = QLabel(valor)
        f = QFont(); f.setPointSize(14); f.setWeight(QFont.DemiBold)
        l_v.setFont(f)
        l_v.setStyleSheet(f"color:{color}; background:transparent; border:none;")
        v.addWidget(l_e)
        v.addWidget(l_v)
        card.lbl_valor = l_v
        return card

    # ── Carga inicial ───────────────────────────────────────────────────────
    def _cargar_todo(self):
        # Áreas
        self.cmb_area.blockSignals(True)
        self.cmb_area.clear()
        for a in listar_areas():
            self.cmb_area.addItem(f"{a['codigo']} — {a['nombre']}", a['codigo'])
        self.cmb_area.blockSignals(False)
        self._area_actual = self.cmb_area.itemData(0) or '01'

        self._refrescar_lista()
        self._actualizar_kpis()

    def _refrescar_lista(self):
        q = self.inp_q.text().strip().lower() if hasattr(self, 'inp_q') else ''
        indices = listar_indices()
        anterior = self._codigo_actual

        self.lst.blockSignals(True)
        self.lst.clear()
        cnt = 0
        for ind in indices:
            txt = f"{ind['codigo']}  ·  {ind['nombre']}"
            if q and q not in ind['codigo'].lower() and q not in ind['nombre'].lower():
                continue
            cnt += 1
            it = QListWidgetItem(txt)
            it.setData(Qt.UserRole, ind['codigo'])
            # Badge con último período si existe
            if ind['ultimo_periodo']:
                it.setToolTip(
                    f"{ind['nombre']}\n"
                    f"{ind['n_valores']} valores · último: "
                    f"{ind['ultimo_periodo']} = {ind['ultimo_valor']:.2f}"
                )
            self.lst.addItem(it)
        self.lst.blockSignals(False)

        if anterior:
            # Re-seleccionar el código actual si existe
            for i in range(self.lst.count()):
                if self.lst.item(i).data(Qt.UserRole) == anterior:
                    self.lst.setCurrentRow(i)
                    break
        if self.lst.count() and self.lst.currentRow() < 0:
            self.lst.setCurrentRow(0)
        self.lbl_subt.setText(f"  ·  {cnt} índices")

    def _actualizar_kpis(self):
        from core.database import get_db
        conn = get_db()
        n_indices = conn.execute("SELECT COUNT(*) FROM indices_inei").fetchone()[0]
        n_con_datos = conn.execute(
            "SELECT COUNT(DISTINCT codigo) FROM indices_inei_valores "
            "WHERE area=?", (self._area_actual,)
        ).fetchone()[0]
        n_valores = conn.execute(
            "SELECT COUNT(*) FROM indices_inei_valores WHERE area=?",
            (self._area_actual,)
        ).fetchone()[0]
        ult = conn.execute(
            "SELECT anio, mes FROM indices_inei_valores WHERE area=? "
            "ORDER BY anio DESC, mes DESC LIMIT 1",
            (self._area_actual,)
        ).fetchone()
        conn.close()
        self.kpi_indices.lbl_valor.setText(str(n_indices))
        self.kpi_con_datos.lbl_valor.setText(str(n_con_datos))
        self.kpi_valores.lbl_valor.setText(str(n_valores))
        self.kpi_ultimo.lbl_valor.setText(
            f"{ult['anio']}-{ult['mes']:02d}" if ult else "—"
        )

    # ── Eventos ─────────────────────────────────────────────────────────────
    def _on_area_change(self):
        self._area_actual = self.cmb_area.currentData() or '01'
        self._actualizar_kpis()
        if self._codigo_actual:
            self._cargar_matriz(self._codigo_actual)

    def _on_lst_change(self):
        items = self.lst.selectedItems()
        if not items:
            self._codigo_actual = None
            self._limpiar_matriz()
            return
        cod = items[0].data(Qt.UserRole)
        self._codigo_actual = cod
        self._cargar_matriz(cod)

    def _limpiar_matriz(self):
        self.tbl.blockSignals(True)
        self.tbl.setRowCount(0)
        self.tbl.blockSignals(False)
        self.lbl_titulo_matriz.setText("Selecciona un índice")

    def _cargar_matriz(self, codigo: str):
        # Recuperar nombre del índice
        ind = next((x for x in listar_indices() if x['codigo'] == codigo), None)
        nombre = ind['nombre'] if ind else codigo
        self.lbl_titulo_matriz.setText(f"{codigo}  ·  {nombre}")

        m = obtener_matriz(codigo, self._area_actual)
        # Años a mostrar: rango completo desde el mín hasta el actual, o solo el actual
        hoy = datetime.now().year
        if m:
            anio_min = min(m.keys())
            anio_max = max(max(m.keys()), hoy)
        else:
            anio_min = hoy
            anio_max = hoy

        self.tbl.blockSignals(True)
        self.tbl.setRowCount(0)
        for anio in range(anio_min, anio_max + 1):
            row = self.tbl.rowCount()
            self.tbl.insertRow(row)
            self.tbl.setVerticalHeaderItem(row, QTableWidgetItem(str(anio)))
            data_anio = m.get(anio, {})
            for mes in range(1, 13):
                v = data_anio.get(mes)
                txt = f"{v:.4f}".rstrip('0').rstrip('.') if v is not None else ""
                it = QTableWidgetItem(txt)
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                it.setData(Qt.UserRole, anio)
                it.setData(Qt.UserRole + 1, mes)
                if v is not None:
                    f = QFont(); f.setWeight(QFont.DemiBold)
                    it.setFont(f)
                    it.setForeground(QColor(SLATE_700))
                else:
                    it.setForeground(QColor(SLATE_300))
                self.tbl.setItem(row, mes - 1, it)
            # Promedio (solo lectura)
            valores = [v for v in data_anio.values() if v is not None]
            avg = sum(valores) / len(valores) if valores else 0
            it_avg = QTableWidgetItem(f"{avg:.4f}".rstrip('0').rstrip('.')
                                      if valores else "—")
            it_avg.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            it_avg.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            it_avg.setForeground(QColor(ORANGE_DARK) if valores else QColor(SLATE_300))
            f = QFont(); f.setBold(True)
            it_avg.setFont(f)
            self.tbl.setItem(row, 12, it_avg)
        self.tbl.blockSignals(False)

    def _agregar_anio(self):
        if not self._codigo_actual:
            return
        # Agregar fila al año siguiente del más alto actualmente mostrado
        if self.tbl.rowCount() == 0:
            anio = datetime.now().year
        else:
            ultimo = int(self.tbl.verticalHeaderItem(
                self.tbl.rowCount() - 1
            ).text())
            anio = ultimo + 1
        self.tbl.blockSignals(True)
        row = self.tbl.rowCount()
        self.tbl.insertRow(row)
        self.tbl.setVerticalHeaderItem(row, QTableWidgetItem(str(anio)))
        for mes in range(1, 13):
            it = QTableWidgetItem("")
            it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            it.setData(Qt.UserRole, anio)
            it.setData(Qt.UserRole + 1, mes)
            it.setForeground(QColor(SLATE_300))
            self.tbl.setItem(row, mes - 1, it)
        it_avg = QTableWidgetItem("—")
        it_avg.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        it_avg.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        it_avg.setForeground(QColor(SLATE_300))
        self.tbl.setItem(row, 12, it_avg)
        self.tbl.blockSignals(False)
        self.tbl.scrollToBottom()
        # Foco en enero del nuevo año
        self.tbl.setCurrentCell(row, 0)
        self.tbl.editItem(self.tbl.item(row, 0))

    def _on_celda_cambiada(self, item: QTableWidgetItem):
        if not self._codigo_actual or item.column() >= 12:
            return
        anio = item.data(Qt.UserRole)
        mes = item.data(Qt.UserRole + 1)
        if anio is None or mes is None:
            return
        txt = item.text().strip()
        if not txt:
            eliminar_valor(self._codigo_actual, anio, mes, self._area_actual)
            self.tbl.blockSignals(True)
            item.setForeground(QColor(SLATE_300))
            self.tbl.blockSignals(False)
        else:
            valor = parse_num(txt)
            if valor <= 0:
                return
            guardar_valor(self._codigo_actual, anio, mes, valor, self._area_actual)
            self.tbl.blockSignals(True)
            item.setText(f"{valor:.4f}".rstrip('0').rstrip('.'))
            f = QFont(); f.setWeight(QFont.DemiBold)
            item.setFont(f)
            item.setForeground(QColor(SLATE_700))
            self.tbl.blockSignals(False)
        # Recalcular promedio + KPIs + tooltip de la lista
        self._recalcular_promedio_fila(item.row())
        self._actualizar_kpis()
        self._refrescar_lista()

    def _recalcular_promedio_fila(self, row: int):
        valores: list[float] = []
        for c in range(12):
            it = self.tbl.item(row, c)
            if it and it.text().strip():
                try:
                    valores.append(float(it.text().strip()))
                except Exception:
                    pass
        it_avg = self.tbl.item(row, 12)
        if not it_avg:
            return
        self.tbl.blockSignals(True)
        if valores:
            avg = sum(valores) / len(valores)
            it_avg.setText(f"{avg:.4f}".rstrip('0').rstrip('.'))
            it_avg.setForeground(QColor(ORANGE_DARK))
        else:
            it_avg.setText("—")
            it_avg.setForeground(QColor(SLATE_300))
        self.tbl.blockSignals(False)

    def _eliminar_valor_seleccionado(self):
        sel = self.tbl.selectedItems()
        if not sel or not self._codigo_actual:
            return
        for it in sel:
            if it.column() >= 12:
                continue
            self.tbl.blockSignals(True)
            it.setText("")
            self.tbl.blockSignals(False)
            self._on_celda_cambiada(it)

    # ── Sincronizar automáticamente con INEI ────────────────────────────────
    def _sincronizar_inei(self):
        """Busca + descarga + importa el último Excel oficial del INEI."""
        # Bloquear UI durante la descarga
        self.btn_auto.setEnabled(False)
        self.btn_auto.setText("Buscando último archivo INEI…")
        QApplication.processEvents()

        try:
            busq = buscar_ultimo_excel_inei()
            if not busq['ok']:
                QMessageBox.warning(
                    self, "Sincronizar con INEI",
                    busq.get('msg') or "No se encontró archivo."
                )
                return

            self.btn_auto.setText(
                f"Descargando {busq['mes_detectado'].title()} "
                f"{busq['anio_detectado']}…"
            )
            QApplication.processEvents()

            res = descargar_desde_url(
                busq['url'],
                area=self._area_actual,
                anio_override=busq['anio_detectado']
            )
            res['mes_detectado'] = busq['mes_detectado']
            res['anio_detectado_url'] = busq['anio_detectado']

            if not res.get('ok'):
                QMessageBox.critical(
                    self, "Sincronizar con INEI",
                    f"Encontré el archivo pero falló la descarga:\n"
                    f"{busq['url']}\n\n{res.get('msg')}"
                )
                return

            fuente = (f"INEI oficial — {busq['mes_detectado'].title()} "
                      f"{busq['anio_detectado']}  ({res.get('tamano_kb', 0)} KB)")
            self._procesar_resultado_import(res, fuente=fuente)
        finally:
            self.btn_auto.setEnabled(True)
            self.btn_auto.setText("Sincronizar con INEI")

    # ── Descargar desde URL ─────────────────────────────────────────────────
    def _descargar_url(self):
        from PySide6.QtWidgets import (
            QDialog, QDialogButtonBox, QLineEdit, QFormLayout, QSpinBox,
            QLabel as _QLabel, QVBoxLayout as _QV
        )

        # Diálogo personalizado: URL + año override opcional
        dlg = QDialog(self)
        dlg.setWindowTitle("Descargar Excel desde URL")
        dlg.setMinimumWidth(520)
        v = _QV(dlg)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(10)

        intro = _QLabel(
            "Pega aquí el enlace directo al archivo <b>.xlsx</b> publicado por "
            "el INEI (o cualquier fuente).<br><br>"
            "<b>Tip:</b> usa el botón <i>«Sincronizar con INEI»</i> para "
            "descargar automáticamente el último archivo. Esta opción es "
            "para descargar un mes específico o desde otra fuente.<br><br>"
            "<b>Cómo conseguirlo manualmente:</b><br>"
            "1. Abre:<br>"
            "&nbsp;&nbsp;<a href='https://www.inei.gob.pe/estadisticas/indice-tematico/price-indexes/'>"
            "inei.gob.pe — Índices de Precios</a><br>"
            "2. <b>Clic derecho</b> sobre el enlace del Excel del mes deseado.<br>"
            "3. <b>«Copiar dirección del enlace»</b>.<br>"
            "4. Pega aquí abajo y pulsa <b>Descargar</b>."
        )
        intro.setOpenExternalLinks(True)
        intro.setWordWrap(True)
        intro.setTextFormat(Qt.RichText)
        intro.setStyleSheet(f"color:{SLATE_500}; font-size:12px;")
        v.addWidget(intro)

        form = QFormLayout()
        form.setSpacing(8)
        inp_url = QLineEdit()
        inp_url.setPlaceholderText("https://m.inei.gob.pe/.../iu-XXXxxxx.xlsx")
        # Auto-pegar desde clipboard si tiene un URL
        from PySide6.QtWidgets import QApplication as _QApp
        cb = _QApp.clipboard().text().strip()
        if cb.startswith("http://") or cb.startswith("https://"):
            inp_url.setText(cb)
        form.addRow("URL:", inp_url)

        inp_anio = QSpinBox()
        inp_anio.setRange(0, 2100)
        inp_anio.setSpecialValueText("(detectar automáticamente)")
        inp_anio.setValue(0)
        form.addRow("Año (opcional):", inp_anio)

        info_area = _QLabel(
            f"Los datos se cargarán para el área actual: "
            f"<b>{self.cmb_area.currentText()[:50]}</b>"
        )
        info_area.setStyleSheet(f"color:{SLATE_300}; font-size:11px;")
        info_area.setTextFormat(Qt.RichText)
        info_area.setWordWrap(True)
        v.addLayout(form)
        v.addWidget(info_area)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Ok).setText("Descargar e importar")
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        v.addWidget(btns)

        if dlg.exec() != QDialog.Accepted:
            return
        url = inp_url.text().strip()
        if not url:
            return
        anio_ovr = inp_anio.value() if inp_anio.value() > 1990 else None

        # Indicador visual de progreso (cambiar texto del botón)
        self.btn_url.setEnabled(False)
        self.btn_url.setText("Descargando…")
        QApplication.processEvents()
        try:
            res = descargar_desde_url(url, area=self._area_actual,
                                       anio_override=anio_ovr)
        finally:
            self.btn_url.setEnabled(True)
            self.btn_url.setText("Descargar desde URL")

        self._procesar_resultado_import(res, fuente=f"URL ({url[:60]}…)")

    # ── Pegar desde portapapeles ────────────────────────────────────────────
    def _pegar_datos(self):
        from PySide6.QtWidgets import (
            QDialog, QDialogButtonBox, QTextEdit as _QText, QSpinBox,
            QLabel as _QLabel, QVBoxLayout as _QV
        )
        from PySide6.QtWidgets import QApplication as _QApp

        dlg = QDialog(self)
        dlg.setWindowTitle("Pegar datos INEI desde portapapeles")
        dlg.setMinimumSize(720, 480)
        v = _QV(dlg)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(8)

        intro = _QLabel(
            "Pega aquí una tabla de cualquier fuente (Excel, página web, PDF, "
            "etc.).<br>"
            "<b>Formato esperado:</b> primera columna = código INEI, "
            "siguientes columnas = meses (Ene–Dic o 1–12).<br>"
            "El parser detecta automáticamente el separador (tab, coma, "
            "punto y coma)."
        )
        intro.setTextFormat(Qt.RichText)
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color:{SLATE_500}; font-size:12px;")
        v.addWidget(intro)

        txt = _QText()
        txt.setPlaceholderText(
            "Ejemplo:\n"
            "Código\tEne\tFeb\tMar\tAbr\tMay\tJun\tJul\tAgo\tSep\tOct\tNov\tDic\n"
            "47\t1245.32\t1267.81\t1290.55\t1310.20\t1325.40\t...\n"
            "39\t1124.10\t1135.50\t1145.20\t..."
        )
        f_mono = QFont("monospace"); f_mono.setPointSize(10)
        txt.setFont(f_mono)
        # Auto-poblar con el clipboard si tiene texto
        clip = _QApp.clipboard().text()
        if clip.strip() and (',' in clip or '\t' in clip or ';' in clip):
            txt.setPlainText(clip)
        v.addWidget(txt, 1)

        # Fila inferior: año override
        from PySide6.QtWidgets import QHBoxLayout as _QH
        bottom = _QH()
        bottom.addWidget(_QLabel("Año:"))
        inp_anio = QSpinBox()
        inp_anio.setRange(0, 2100)
        inp_anio.setSpecialValueText("(detectar automáticamente)")
        inp_anio.setValue(0)
        bottom.addWidget(inp_anio)
        bottom.addStretch(1)

        info_area = _QLabel(
            f"Área destino: <b>{self.cmb_area.currentText()[:50]}</b>"
        )
        info_area.setStyleSheet(f"color:{SLATE_300}; font-size:11px;")
        info_area.setTextFormat(Qt.RichText)
        bottom.addWidget(info_area)
        v.addLayout(bottom)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Ok).setText("Procesar datos")
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        v.addWidget(btns)

        if dlg.exec() != QDialog.Accepted:
            return
        texto = txt.toPlainText()
        if not texto.strip():
            return
        anio_ovr = inp_anio.value() if inp_anio.value() > 1990 else None

        res = importar_desde_texto(texto, area=self._area_actual,
                                    anio_override=anio_ovr)
        self._procesar_resultado_import(res, fuente="Portapapeles")

    def _procesar_resultado_import(self, res: dict, fuente: str = ""):
        """Aplica el resultado de un importador: confirma y persiste."""
        if not res.get('ok'):
            QMessageBox.warning(
                self, "Importar",
                res.get('msg') or "No se pudo procesar."
            )
            return

        if not res['rows']:
            QMessageBox.information(
                self, "Importar",
                "No se detectaron valores nuevos."
            )
            return

        anio = res.get('anio_detectado')
        codigos = sorted(res.get('codigos_encontrados') or set())
        cod_preview = ", ".join(codigos[:8])
        if len(codigos) > 8:
            cod_preview += f"… (+{len(codigos) - 8} más)"

        msg = (f"<b>Fuente:</b> {fuente}<br>"
               f"<b>Año detectado:</b> {anio or '(no detectado)'}<br>"
               f"<b>Área destino:</b> {self._area_actual}<br>"
               f"<b>Índices encontrados:</b> {len(codigos)} ({cod_preview})<br>"
               f"<b>Valores a importar:</b> {len(res['rows'])}<br>"
               f"<b>Ignorados:</b> {res.get('ignorados', 0)}<br><br>"
               f"¿Importar? (los valores existentes se reemplazarán.)")

        ok = QMessageBox.question(
            self, "Confirmar importación", msg,
            QMessageBox.Yes | QMessageBox.No
        )
        if ok != QMessageBox.Yes:
            return

        ok_n, err_n = guardar_valores(res['rows'])
        self._actualizar_kpis()
        self._refrescar_lista()
        if self._codigo_actual:
            self._cargar_matriz(self._codigo_actual)
        QMessageBox.information(
            self, "Importación completa",
            f"{ok_n} valores importados, {err_n} ignorados."
        )

    # ── Importar Excel INEI ─────────────────────────────────────────────────
    def _importar_excel(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Importar Excel INEI", "", "Excel (*.xlsx *.xls)"
        )
        if not path:
            return
        res = importar_excel_inei(path, area=self._area_actual)
        self._procesar_resultado_import(res, fuente=Path(path).name)

    def _importar_delphin_sqlite(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Importar histórico INEI desde Delphin Express",
            "", "Bases de datos Delphin (*.sqlite *.db)"
        )
        if not path:
            return

        # Pre-confirmación
        msg = (
            "Se va a importar el histórico completo de índices INEI desde la "
            "base de datos de Delphin Express.\n\n"
            "Mapeo de regiones Delphin → áreas INEI ingePresupuestos:\n"
            "  • Región 1 (Costa Norte)   → 02 Norte\n"
            "  • Región 2 (Lima/Centro)   → 01 Lima Metropolitana\n"
            "  • Región 3 (Sierra Centro) → 03 Centro\n"
            "  • Región 4 (Sur Costa)     → 05 Sur\n"
            "  • Región 5 (Loreto/Selva)  → 04 Sur Medio y Selva\n"
            "  • Región 6 (Sierra Sur)    → 06 Nacional\n\n"
            "Los valores existentes con la misma combinación "
            "(código, año, mes, área) serán reemplazados.\n\n"
            "¿Continuar?"
        )
        r = QMessageBox.question(
            self, "Importar histórico INEI desde Delphin", msg,
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
        )
        if r != QMessageBox.Yes:
            return

        try:
            from core.delphin_sqlite_importer import import_inei_delphin_sqlite
            res = import_inei_delphin_sqlite(path)
        except Exception as e:
            QMessageBox.critical(
                self, "Importar histórico INEI desde Delphin",
                f"No se pudo leer la base de datos:\n\n{e}"
            )
            return

        anios = res['anios']
        rango_anios = (f"{anios[0]} – {anios[-1]} ({len(anios)} años)"
                       if anios else "—")
        resumen = (
            f"Importación completada.\n\n"
            f"  Filas leídas:      {res['n_filas_origen']:,}\n"
            f"  Valores guardados: {res['n_insertadas']:,}\n"
            f"  Filas ignoradas:   {res['n_ignoradas']:,}\n\n"
            f"  Años:              {rango_anios}\n"
            f"  Códigos INEI:      {len(res['codigos'])}\n"
            f"  Regiones Delphin:  {len(res['regiones_origen'])}\n"
            f"  Áreas pobladas:    {', '.join(res['areas_destino'])}"
        )
        self._actualizar_kpis()
        self._refrescar_lista()
        if self._codigo_actual:
            self._cargar_matriz(self._codigo_actual)
        QMessageBox.information(
            self, "Importar histórico INEI desde Delphin", resumen
        )

    def _importar_json(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Importar JSON de índices INEI", "", "JSON (*.json)"
        )
        if not path:
            return
        res = importar_json(path)
        if not res['ok']:
            QMessageBox.warning(self, "Importar JSON", res.get('msg'))
            return
        self._actualizar_kpis()
        self._refrescar_lista()
        if self._codigo_actual:
            self._cargar_matriz(self._codigo_actual)
        QMessageBox.information(self, "Importar JSON", res['msg'])

    def _exportar_json(self):
        from datetime import datetime as _dt
        fecha = _dt.now().strftime("%Y%m%d_%H%M")
        sugerido = f"indices_inei_{self._area_actual}_{fecha}.json"
        path, _ = QFileDialog.getSaveFileName(
            self, "Exportar JSON de índices INEI", sugerido, "JSON (*.json)"
        )
        if not path:
            return
        if not path.lower().endswith(".json"):
            path += ".json"
        try:
            n = exportar_json(path, area=self._area_actual)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo exportar:\n{e}")
            return
        QMessageBox.information(
            self, "Exportado",
            f"{n} valores exportados a:\n{path}"
        )


