# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""Control de Obra — vista nivel-proyecto (Fase 1: Valorizaciones).

Se ancla al `_root_stack` del proyecto (igual que Cronograma/Reportes) y se abre
con el botón «Control de Obra» del topbar. Pestañas (orden del flujo de obra):
Requerimientos · Almacén · Cuaderno · Valorizaciones · Curva S real (todas
funcionales). «Liquidación» queda oculta para una actualización mayor.

El residente solo edita la columna «Metr. actual»; todo lo demás se deriva en
`core/valorizacion.py`. SOLO LEE del presupuesto, nunca lo modifica.
Ver `[[project_modulo_ejecucion_obra]]`.
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QPushButton, QLabel,
    QStackedWidget, QTableWidget, QTableWidgetItem, QHeaderView,
    QComboBox, QMessageBox, QDialog, QDateEdit, QAbstractItemView,
    QStyledItemDelegate, QLineEdit, QPlainTextEdit, QSplitter, QTabWidget,
    QTextBrowser,
    QApplication, QMenu, QTableView, QScrollArea, QTreeWidget, QTreeWidgetItem,
    QTabBar, QCheckBox, QFormLayout, QColorDialog,
)
from PySide6.QtCore import (Qt, QDate, QRect, QRectF, QSize, QPointF, QTimer,
                            QEvent, QThread, Signal, QSettings)
from PySide6.QtGui import (QColor, QFont, QPainter, QBrush, QKeySequence,
                           QPixmap, QPen, QIcon, QSyntaxHighlighter,
                           QTextCharFormat, QPolygonF)

from core.database import get_db, get_decimales_metrado, get_config, set_config
from utils.formatting import fmt_num, parse_num
import core.valorizacion as V
import core.parte_diario as PD
import core.requerimientos as REQ
import core.almacen as ALM
import core.curva_s as CS
import core.clasificador as clasificador
import core.ai_requerimientos as AR


def _dir_reportes() -> str:
    """Carpeta por defecto para guardar reportes: la última usada, luego
    Descargas/Downloads, luego HOME (compartida con el Centro de Reportes)."""
    import os
    s = QSettings("ingePresupuestos", "reportes")
    guardado = s.value("last_export_dir", "")
    if guardado and os.path.isdir(guardado):
        return guardado
    candidatos = [os.path.expanduser("~/Descargas"),
                  os.path.expanduser("~/Downloads"),
                  os.path.expanduser("~")]
    return next((c for c in candidatos if os.path.isdir(c)), os.path.expanduser("~"))


def _guardar_dir_reportes(path: str):
    """Persiste la carpeta del reporte recién guardado."""
    import os
    d = os.path.dirname(path)
    if d and os.path.isdir(d):
        QSettings("ingePresupuestos", "reportes").setValue("last_export_dir", d)


SLATE_700 = "#273445"
SLATE_500 = "#485A6C"
SLATE_300 = "#667885"
SILVER_100 = "#F8F9FA"
SILVER_200 = "#F0F1F2"
SILVER_300 = "#D4D4D4"
ORANGE = "#F37329"
GREEN_700 = "#16A34A"
RED_700 = "#B71C1C"
RED_BG = "#FDECEC"   # tinte de alerta: acumulado que excede la base contractual
BLUE = "#3689E6"     # curva S programada (planificado)
PURPLE = "#8E44AD"   # curva S reprogramada (meta del residente)
# Paleta elementary «Banana» — resalta el grupo «Actual» (período en curso).
BANANA_100 = "#FFF394"   # celda editable (Metr. actual) — más fuerte
BANANA_SOFT = "#FFF9CC"  # resto del grupo Actual — tinte suave
# Azul claro: el metrado del mes lo alimenta el parte diario (celda de solo
# lectura). Distingue «escribe aquí» (banana) de «viene del cuaderno» (azul).
DIARIO_BG = "#E3F2FD"
# Resaltado de selección sutil (crema), consistente con el resto de la app —
# evita el naranja intenso de la paleta por defecto.
SELECT_BG = "#FEF5EB"

# Estilo de títulos por nivel — MISMO que el presupuesto (`proyecto_view.NIVEL_ESTILO`)
# para mantener consistencia: (color de fuente, fondo tinte). Nivel 1 va subrayado.
NIVEL_ESTILO = {
    1: ("#B71C1C", "#E2E8F0"),   # rojo oscuro — capítulos
    2: ("#0D52BF", "#F5F8FF"),   # arándano    — sub-capítulos
    3: ("#6A1B9A", "#F9F5FF"),   # morado      — secciones
    4: ("#AD1457", "#FFF5FA"),   # rosa oscuro — sub-secciones
}

# Columnas de la grilla de valorización — agrupadas como una valorización real:
# Presupuesto base · Anterior · Actual · Acumulado · Saldo (cada grupo con
# Metrado / Valorizado / %). Cabecera de dos niveles (`_GroupedHeader`).
(COL_ITEM, COL_DESC, COL_UND,
 COL_B_METR, COL_B_PU, COL_B_PARC,
 COL_A_METR, COL_A_VAL, COL_A_PCT,
 COL_C_METR, COL_C_VAL, COL_C_PCT,
 COL_K_METR, COL_K_VAL, COL_K_PCT,
 COL_S_METR, COL_S_VAL, COL_S_PCT) = range(18)
NCOLS = 18
COL_ACT = COL_C_METR   # única columna editable (metrado del período actual)

# Sub-cabecera (fila inferior) por columna y grupos (fila superior, con span).
_SUBS = ["Ítem", "Descripción", "Und",
         "Metrado", "P.U.", "Parcial",
         "Metrado", "Valorizado", "%",
         "Metrado", "Valorizado", "%",
         "Metrado", "Valorizado", "%",
         "Metrado", "Valor", "%"]
_GROUPS = [("Presupuesto base", COL_B_METR, 3), ("Anterior", COL_A_METR, 3),
           ("Actual", COL_C_METR, 3), ("Acumulado", COL_K_METR, 3),
           ("Saldo", COL_S_METR, 3)]


class _GroupedHeader(QHeaderView):
    """Cabecera horizontal de DOS niveles: fila superior con los grupos
    (Presupuesto base / Anterior / Actual / Acumulado / Saldo) abarcando sus
    columnas, fila inferior con las sub-columnas (Metrado / Valorizado / %).
    Las columnas sin grupo (Ítem/Descripción/Und) ocupan el alto completo."""

    def __init__(self, subs, groups, accent_cols=None, parent=None):
        super().__init__(Qt.Horizontal, parent)
        self._subs = subs
        self._groups = groups
        self._accent = set(accent_cols or [])
        self.setSectionsClickable(False)
        self.setHighlightSections(False)

    def sizeHint(self):
        s = super().sizeHint()
        return QSize(s.width(), 40)

    def _cell(self, painter, rect, text, bold=False, bg=SILVER_200):
        painter.fillRect(rect, QColor(bg))
        painter.setPen(QColor(SILVER_300))
        painter.drawRect(rect.adjusted(0, 0, -1, -1))
        f = painter.font(); f.setBold(bold); f.setPointSize(8)
        painter.setFont(f)
        painter.setPen(QColor(SLATE_700))
        painter.drawText(rect.adjusted(2, 0, -2, 0),
                         Qt.AlignCenter | Qt.TextWordWrap, str(text or ''))

    def paintEvent(self, event):
        painter = QPainter(self.viewport())
        H = self.height(); half = H // 2
        grouped = set()
        for _label, start, span in self._groups:
            for k in range(span):
                grouped.add(start + k)
        # Fila inferior: sub-columnas de los grupos.
        for i in range(self.count()):
            if i not in grouped:
                continue
            x = self.sectionViewportPosition(i); w = self.sectionSize(i)
            bg = BANANA_SOFT if i in self._accent else SILVER_200
            self._cell(painter, QRect(x, half, w, H - half),
                       self._subs[i] if i < len(self._subs) else '', bg=bg)
        # Fila superior: etiqueta de grupo abarcando sus columnas.
        for label, start, span in self._groups:
            x = self.sectionViewportPosition(start)
            w = sum(self.sectionSize(start + k) for k in range(span))
            bg = BANANA_100 if start in self._accent else SILVER_200
            self._cell(painter, QRect(x, 0, w, half), label, bold=True, bg=bg)
        # Columnas sin grupo: alto completo.
        for i in range(self.count()):
            if i in grouped:
                continue
            x = self.sectionViewportPosition(i); w = self.sectionSize(i)
            self._cell(painter, QRect(x, 0, w, H),
                       self._subs[i] if i < len(self._subs) else '')


def _gate_reporte_editable(fmt, parent) -> bool:
    """Los reportes EDITABLES (Word/Excel/ODS) de Control de Obra son premium
    (libres durante el trial; el PDF es SIEMPRE gratis). Devuelve True si se
    puede generar; si es editable y no hay premium, muestra el diálogo y False."""
    if fmt == 'pdf':
        return True
    from core.licencia import require_premium
    return require_premium('export_editable', parent)


def _co_editable(proy) -> bool:
    """Control de Obra SOLO se registra cuando la obra está «En ejecución»
    (estado interno 'ejecutado'). En cualquier otro estado (elaboración, revisión,
    aprobado) los paneles quedan de SOLO LECTURA."""
    return ((proy or {}).get('estado') or '') == 'ejecutado'


class ControlObraView(QWidget):
    """Vista completa de Control de Obra — page del root_stack del proyecto."""

    def __init__(self, pid: int, proyecto: dict, on_back, parent=None,
                 on_editar=None):
        super().__init__(parent)
        self.pid = pid
        self._proy = proyecto
        self._on_back = on_back
        self._on_editar = on_editar
        self._build_ui()

    def _build_ui(self):
        vl = QVBoxLayout(self)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)

        bar = QFrame()
        bar.setFixedHeight(36)
        bar.setStyleSheet(f"background:{SLATE_500}; border:none;")
        hl = QHBoxLayout(bar)
        hl.setContentsMargins(8, 4, 10, 4)
        hl.setSpacing(6)

        btn_back = QPushButton("← Presupuesto")
        btn_back.setCursor(Qt.PointingHandCursor)
        btn_back.setStyleSheet(
            "QPushButton { background:rgba(255,255,255,0.12); color:white;"
            " border:1px solid rgba(255,255,255,0.25); border-radius:6px;"
            " font-size:11px; padding:3px 10px; }"
            "QPushButton:hover { background:rgba(255,255,255,0.22); }")
        btn_back.clicked.connect(self._on_back)
        hl.addWidget(btn_back)
        hl.addSpacing(8)

        self._stack = QStackedWidget()
        self._stack.setStyleSheet(f"background:{SILVER_100};")

        # Orden del flujo de obra: requerir → registrar (cuaderno) → valorizar →
        # derivados (avance/curva S) → cerrar (liquidación).
        # «Liquidación» queda para una actualización mayor (oculta en esta versión).
        self._tabs = ["Requerimientos", "Almacén", "Cuaderno", "Valorizaciones",
                      "Curva S real"]
        self._tab_btns: list[QPushButton] = []

        # Índices funcionales (independientes del orden de las pestañas).
        self._idx_req = self._tabs.index("Requerimientos")
        self._idx_cuaderno = self._tabs.index("Cuaderno")
        self._idx_almacen = self._tabs.index("Almacén")
        self._idx_valo = self._tabs.index("Valorizaciones")
        self._idx_curva = self._tabs.index("Curva S real")

        for i, lbl in enumerate(self._tabs):
            btn = QPushButton(lbl)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(self._tab_style(i == 0))
            btn.clicked.connect(lambda _, ix=i: self._select_tab(ix))
            hl.addWidget(btn)
            self._tab_btns.append(btn)
        hl.addStretch()
        vl.addWidget(bar)

        # Banner de SOLO LECTURA (visible si el estado no es «En ejecución»).
        self._ro_banner = QLabel()
        self._ro_banner.setWordWrap(True)
        self._ro_banner.setStyleSheet(
            f"QLabel {{ color:{SLATE_700}; background:#FEF5EB; padding:6px 12px;"
            f" border-bottom:1px solid #F9A65C; font-size:11px; font-weight:600; }}")
        self._ro_banner.hide()
        vl.addWidget(self._ro_banner)

        # Paneles + stack (en el orden de las pestañas).
        self._valo_panel = _ValorizacionesPanel(self.pid, self._proy, self)
        self._cuaderno_panel = _CuadernoPanel(self.pid, self._proy, self)
        self._req_panel = _RequerimientosPanel(self.pid, self._proy, self)
        self._almacen_panel = _AlmacenPanel(self.pid, self._proy, self)
        self._curva_panel = _CurvaSRealPanel(self.pid, self._proy, self)
        for i, nombre in enumerate(self._tabs):
            if i == self._idx_valo:
                self._stack.addWidget(self._valo_panel)
            elif i == self._idx_cuaderno:
                self._stack.addWidget(self._cuaderno_panel)
            elif i == self._idx_req:
                self._stack.addWidget(self._req_panel)
            elif i == self._idx_almacen:
                self._stack.addWidget(self._almacen_panel)
            elif i == self._idx_curva:
                self._stack.addWidget(self._curva_panel)
            else:
                self._stack.addWidget(self._placeholder(nombre))
        vl.addWidget(self._stack, stretch=1)

    def _tab_style(self, sel: bool) -> str:
        bg = ORANGE if sel else "transparent"
        hov = ("" if sel else
               "QPushButton:hover { background:rgba(255,255,255,0.15); color:white; }")
        return (f"QPushButton {{ background:{bg}; color:white; border:none;"
                f" border-radius:6px; font-size:11px; font-weight:700;"
                f" padding:4px 14px; }}" + hov)

    def _select_tab(self, idx: int):
        self._stack.setCurrentIndex(idx)
        for i, b in enumerate(self._tab_btns):
            b.setStyleSheet(self._tab_style(i == idx))
        # Refrescar el panel al entrar: la valorización refleja los cambios del
        # cuaderno (y viceversa) recién al recargar.
        if idx == self._idx_valo:
            self._valo_panel.cargar()
        elif idx == self._idx_cuaderno:
            self._cuaderno_panel.cargar()
        elif idx == self._idx_req:
            self._req_panel.cargar()
        elif idx == self._idx_almacen:
            self._almacen_panel.cargar()
        elif idx == self._idx_curva:
            self._curva_panel.cargar()

    def _placeholder(self, nombre: str) -> QWidget:
        w = QWidget()
        w.setStyleSheet(f"background:{SILVER_100};")
        v = QVBoxLayout(w)
        v.addStretch()
        lbl = QLabel(f"« {nombre} »\n\nPróximamente — fase siguiente del módulo.")
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet(
            f"color:{SLATE_300}; font-size:14px; background:transparent;"
            " border:none;")
        v.addWidget(lbl)
        v.addStretch()
        return w

    def mostrar_tab(self, idx: int):
        if 0 <= idx < len(self._tab_btns):
            self._tab_btns[idx].click()

    def cargar(self):
        # Propagar el proyecto (con su estado) a TODOS los paneles antes de
        # cargar — cada uno decide su editabilidad según el estado.
        for pnl in (self._valo_panel, self._cuaderno_panel, self._req_panel,
                    self._almacen_panel, self._curva_panel):
            pnl._proy = self._proy
        # Banner de solo lectura fuera de «En ejecución».
        if _co_editable(self._proy):
            self._ro_banner.hide()
        else:
            from core.config import ESTADOS_PROYECTO_NOMBRE
            est = ESTADOS_PROYECTO_NOMBRE.get(
                (self._proy or {}).get('estado'), 'En elaboración')
            self._ro_banner.setText(
                f"🔒  Solo lectura — el proyecto está en «{est}». El Control de "
                "Obra se registra cuando la obra pasa a «En ejecución». "
                "Cambia el estado para editar.")
            self._ro_banner.show()
        # Cargar la pestaña visible (la primera = Requerimientos).
        self._select_tab(self._stack.currentIndex())


class _ValorizacionesPanel(QWidget):
    """Pestaña Valorizaciones: lista de períodos + grilla de avance por partida.
    Solo se edita la columna «Metr. actual»; el resto se deriva."""

    def __init__(self, pid: int, proy: dict, parent=None):
        super().__init__(parent)
        self.pid = pid
        self._proy = proy
        self._val_id = None
        self._build_ui()

    def _build_ui(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 8, 10, 8)
        v.setSpacing(8)

        # Aviso de estado — se actualiza en cargar() leyendo el estado FRESCO
        # de la BD (no una copia cacheada del proyecto, que quedaba obsoleta).
        self.aviso = QLabel("")
        self.aviso.setWordWrap(True)
        self.aviso.setStyleSheet(
            f"color:{SLATE_700}; background:#FEF5EB; border:1px solid #F9A65C;"
            " border-radius:6px; padding:6px 10px; font-size:11px;")
        self.aviso.hide()
        v.addWidget(self.aviso)

        # Toolbar: selector de valorización + acciones
        tb = QHBoxLayout(); tb.setSpacing(6)
        lbl = QLabel("Valorización:")
        lbl.setStyleSheet(f"color:{SLATE_700}; font-size:12px; font-weight:600;"
                          " background:transparent; border:none;")
        tb.addWidget(lbl)
        self.cmb = QComboBox()
        self.cmb.setMinimumWidth(150)
        self.cmb.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.cmb.setStyleSheet(
            f"QComboBox {{ border:1px solid {SILVER_300}; border-radius:6px;"
            f" padding:3px 10px; font-size:12px; background:white; min-height:28px; }}")
        self.cmb.currentIndexChanged.connect(self._on_val_changed)
        tb.addWidget(self.cmb)

        # Período como enlace clickable (edita la fecha sin botón aparte).
        self.lbl_periodo = QLabel()
        self.lbl_periodo.setStyleSheet("background:transparent; border:none;"
                                       " font-size:11px;")
        self.lbl_periodo.setToolTip("Clic para editar el período (fechas) de esta "
                                    "valorización.")
        self.lbl_periodo.linkActivated.connect(lambda _: self._editar_fecha())
        tb.addWidget(self.lbl_periodo)

        def _btn(txt, fn, primary=False):
            b = QPushButton(txt)
            b.setCursor(Qt.PointingHandCursor)
            if primary:
                b.setStyleSheet(
                    f"QPushButton {{ background:{ORANGE}; color:white; border:none;"
                    f" border-radius:6px; font-size:11px; font-weight:600;"
                    f" padding:5px 12px; }}"
                    f"QPushButton:hover {{ background:#C0621A; }}")
            else:
                b.setStyleSheet(
                    f"QPushButton {{ background:white; color:{SLATE_700};"
                    f" border:1px solid {SILVER_300}; border-radius:6px;"
                    f" font-size:11px; padding:5px 10px; }}"
                    f"QPushButton:hover {{ background:{SILVER_200}; }}")
            b.clicked.connect(fn)
            return b

        self.btn_nueva = _btn("+ Nueva valorización", self._nueva, primary=True)
        tb.addWidget(self.btn_nueva)
        self.btn_cerrar = _btn("Cerrar", self._cerrar_reabrir)
        tb.addWidget(self.btn_cerrar)
        self.btn_elim = _btn("Eliminar", self._eliminar)
        tb.addWidget(self.btn_elim)
        self.btn_reporte = _btn("📄 Reporte", lambda: None)
        _rm = QMenu(self.btn_reporte)
        _rm.addAction("PDF", lambda: self._reporte('pdf'))
        _rm.addAction("Excel (.xlsx)", lambda: self._reporte('xlsx'))
        _rm.addAction("LibreOffice (.ods)", lambda: self._reporte('ods'))
        self.btn_reporte.setMenu(_rm)
        tb.addWidget(self.btn_reporte)
        tb.addStretch()
        self.lbl_estado = QLabel("")
        self.lbl_estado.setStyleSheet("background:transparent; border:none;"
                                      " font-size:11px; font-weight:700;")
        tb.addWidget(self.lbl_estado)
        v.addLayout(tb)

        # Tabla con cabecera agrupada de dos niveles.
        self.tbl = QTableWidget()
        self.tbl.setColumnCount(NCOLS)
        self.tbl.setHorizontalHeader(_GroupedHeader(
            _SUBS, _GROUPS, accent_cols={COL_C_METR, COL_C_VAL, COL_C_PCT},
            parent=self.tbl))
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setEditTriggers(QAbstractItemView.DoubleClicked
                                 | QAbstractItemView.SelectedClicked
                                 | QAbstractItemView.AnyKeyPressed)
        self.tbl.setAlternatingRowColors(True)
        self.tbl.setWordWrap(True)   # la descripción larga ajusta a varias líneas
        self.tbl.setStyleSheet(
            f"QTableWidget {{ background:white; gridline-color:{SILVER_200};"
            f" font-size:11px; }}")
        hdr = self.tbl.horizontalHeader()
        # Todas Interactive (no Stretch/ResizeToContents): así la Descripción es
        # redimensionable por el usuario y NO recalcula anchos en cada edición.
        # Las columnas se dimensionan una vez por carga completa; la Descripción
        # llena el espacio restante (ver _refrescar_tabla).
        hdr.setStretchLastSection(False)
        for c in range(NCOLS):
            hdr.setSectionResizeMode(c, QHeaderView.Interactive)
        self._dimensionando = False   # evita reflow de filas durante el dimensionado masivo
        self.tbl.setItemDelegateForColumn(COL_ACT, _MetradoDelegate(self.tbl))
        self.tbl.verticalHeader().setDefaultSectionSize(24)
        self.tbl.itemChanged.connect(self._on_item_changed)
        v.addWidget(self.tbl, stretch=1)

        # Fila TOTAL CONGELADA (siempre visible) — tabla de 1 fila sincronizada
        # en ancho de columnas y scroll horizontal con la tabla principal.
        self.tbl_total = QTableWidget(1, NCOLS)
        self.tbl_total.horizontalHeader().setVisible(False)
        self.tbl_total.verticalHeader().setVisible(False)
        self.tbl_total.setFixedHeight(30)
        self.tbl_total.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl_total.setSelectionMode(QAbstractItemView.NoSelection)
        self.tbl_total.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tbl_total.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tbl_total.setStyleSheet(
            f"QTableWidget {{ background:#D5DBE2; border:none;"
            f" border-top:2px solid {SLATE_500}; gridline-color:{SILVER_300};"
            f" font-size:11px; }}")
        self.tbl_total.setVisible(False)
        v.addWidget(self.tbl_total)
        # Sincronizar anchos y scroll horizontal con la tabla principal.
        self.tbl.horizontalHeader().sectionResized.connect(self._on_col_resized)
        self.tbl.horizontalScrollBar().valueChanged.connect(
            self.tbl_total.horizontalScrollBar().setValue)

        # Estado vacío (sin presupuesto)
        self.lbl_vacio = QLabel(
            "Para valorizar necesitas el presupuesto del proyecto.\n"
            "Impórtalo o créalo desde la pestaña «Presupuesto».")
        self.lbl_vacio.setAlignment(Qt.AlignCenter)
        self.lbl_vacio.setStyleSheet(
            f"color:{SLATE_300}; font-size:13px; background:transparent;"
            " border:none;")
        self.lbl_vacio.hide()
        v.addWidget(self.lbl_vacio)

        # Footer: % avance físico global
        ft = QHBoxLayout()
        ft.addStretch()
        self.lbl_resumen = QLabel("")
        self.lbl_resumen.setStyleSheet(
            f"color:{SLATE_700}; font-size:12px; font-weight:700;"
            " background:transparent; border:none;")
        ft.addWidget(self.lbl_resumen)
        v.addLayout(ft)

    # ── Carga ────────────────────────────────────────────────────────────────

    def cargar(self):
        # Estado FRESCO + ¿hay presupuesto?  (todo desde la BD, no cacheado).
        conn = get_db()
        prow = conn.execute("SELECT estado FROM proyectos WHERE id=?",
                            (self.pid,)).fetchone()
        estado = ((prow['estado'] if prow else '') or '').lower()
        n = conn.execute("SELECT COUNT(*) c FROM partidas WHERE proyecto_id=? "
                         "AND es_titulo=0", (self.pid,)).fetchone()['c']
        conn.close()
        # El aviso de estado lo da el banner global de ControlObraView.
        self.aviso.hide()
        co = _co_editable(self._proy)
        sin_ppto = (n == 0)
        self.tbl.setVisible(not sin_ppto)
        self.tbl_total.setVisible(not sin_ppto)
        self.lbl_vacio.setVisible(sin_ppto)
        # El combo (seleccionar/ver) queda habilitado siempre; crear/cerrar/eliminar
        # solo en «En ejecución».
        self.cmb.setEnabled(not sin_ppto)
        for b in (self.btn_nueva, self.btn_cerrar, self.btn_elim):
            b.setEnabled(not sin_ppto and co)
        if sin_ppto:
            self.lbl_resumen.setText("")
            return
        self._recargar_lista()

    def _recargar_lista(self):
        prev = self._val_id
        self.cmb.blockSignals(True)
        self.cmb.clear()
        vals = V.listar_valorizaciones(self.pid)
        for vrow in vals:
            # El período va aparte (enlace editable); aquí solo el número + estado.
            cerr = "  🔒" if vrow['estado'] == 'cerrada' else ""
            self.cmb.addItem(f"Valorización N°{vrow['numero']}{cerr}", vrow['id'])
        self.cmb.blockSignals(False)
        if not vals:
            self._val_id = None
            self.tbl.setRowCount(0)
            self.tbl_total.setVisible(False)
            self.lbl_resumen.setText("Sin valorizaciones. Crea la primera con "
                                     "«+ Nueva valorización».")
            self._sync_botones(None)
            self.lbl_periodo.setText("")
            return
        # Seleccionar la previa o la última.
        idx = next((i for i in range(self.cmb.count())
                    if self.cmb.itemData(i) == prev), self.cmb.count() - 1)
        self.cmb.setCurrentIndex(idx)
        self._on_val_changed()

    def _on_val_changed(self):
        self._val_id = self.cmb.currentData()
        self._refrescar_tabla()
        self._actualizar_periodo_link()

    def _actualizar_periodo_link(self):
        if not self._val_id:
            self.lbl_periodo.setText("")
            return
        v = V.get_valorizacion(self._val_id)
        cerrada = v.get('estado') == 'cerrada' or not _co_editable(self._proy)
        rango = (f"{_fmt_fecha(v.get('periodo_desde'))} – "
                 f"{_fmt_fecha(v.get('periodo_hasta'))}"
                 if (v.get('periodo_desde') or v.get('periodo_hasta'))
                 else "sin período")
        if cerrada:   # cerrada / solo lectura: solo texto, no editable
            self.lbl_periodo.setText(
                f'<span style="color:{SLATE_500}">📅 {rango}</span>')
        else:
            self.lbl_periodo.setText(
                f'📅 <a href="#" style="color:{ORANGE}; text-decoration:none">'
                f'{rango} ✏</a>')

    # ── Tabla ────────────────────────────────────────────────────────────────

    def _refrescar_tabla(self):
        if not self._val_id:
            return
        filas, resumen = V.get_valorizacion_detalle(self._val_id)
        # Editable solo si la valorización está abierta Y la obra «En ejecución».
        abierta = (resumen.get('estado') == 'abierta') and _co_editable(self._proy)
        dm = get_decimales_metrado()
        moneda = self._proy.get('moneda', 'Soles')

        # Profundidad jerárquica = puntos del ítem relativos al más superficial
        # (igual que el presupuesto) → sangría de la descripción.
        dots = [(f['item'] or '').count('.') for f in filas]
        min_dots = min(dots) if dots else 0

        self.tbl.blockSignals(True)
        self.tbl.setRowCount(len(filas))
        for r, f in enumerate(filas):
            self._fila_valor(r, f, min_dots, dm, moneda, abierta)
        self.tbl.blockSignals(False)
        # Dimensionar columnas UNA vez por carga completa (no en cada edición).
        self._dimensionando = True
        for c in range(NCOLS):
            if c != COL_DESC:
                self.tbl.resizeColumnToContents(c)
        # Ancho mínimo para que las sub-cabeceras (ej. «Valorizado») no se corten
        # (el header pintado a mano no lo considera en resizeColumnToContents).
        for c in range(COL_B_METR, NCOLS):
            if self.tbl.columnWidth(c) < 62:
                self.tbl.setColumnWidth(c, 62)
        # La Descripción ocupa el espacio restante del viewport (y el usuario la
        # puede redimensionar a mano desde ahí).
        usado = sum(self.tbl.columnWidth(c) for c in range(NCOLS) if c != COL_DESC)
        avail = self.tbl.viewport().width() - usado
        self.tbl.setColumnWidth(COL_DESC, max(240, avail))
        self._dimensionando = False
        # Ajustar alto de filas al texto envuelto de la Descripción.
        self.tbl.resizeRowsToContents()
        self.tbl_total.setVisible(True)
        self._pintar_total(resumen, moneda)
        self._pintar_resumen(resumen)

    def _fila_valor(self, r, f, min_dots, dm, moneda, abierta):
        es_tit = f['es_titulo']
        niv = f.get('nivel', 1) or 1
        depth = max(0, (f['item'] or '').count('.') - min_dots)
        base = f['base_val'] or 0
        # Exceso del acumulado sobre la base → celdas en rojo.
        over_val = _excede(f['acu_val'], f['base_val'])
        over_metr = (not es_tit) and _excede(f['acu_metr'], f['base_metr'])
        def money(v):
            return fmt_num(v, moneda)
        self._set(r, COL_ITEM, f['item'], pid_part=f['id'], es_tit=es_tit,
                  nivel=niv, left=True)
        self._set(r, COL_DESC, f['descripcion'], es_tit=es_tit, nivel=niv,
                  left=True, depth=depth)
        if es_tit:
            # Título: metrados en blanco, valores agregados + % por grupo.
            for c in (COL_UND, COL_B_METR, COL_B_PU, COL_A_METR,
                      COL_C_METR, COL_K_METR, COL_S_METR):
                self._set(r, c, "", es_tit=True, nivel=niv)
            self._set(r, COL_B_PARC, money(f['base_val']), es_tit=True, nivel=niv, num=True)
            self._set(r, COL_A_VAL, money(f['ant_val']), es_tit=True, nivel=niv, num=True)
            self._set(r, COL_A_PCT, _pp(f['ant_val'], base), es_tit=True, nivel=niv, num=True)
            self._set(r, COL_C_VAL, money(f['act_val']), es_tit=True, nivel=niv, num=True)
            self._set(r, COL_C_PCT, _pp(f['act_val'], base), es_tit=True, nivel=niv, num=True)
            self._set(r, COL_K_VAL, money(f['acu_val']), es_tit=True, nivel=niv, num=True, danger=over_val)
            self._set(r, COL_K_PCT, _pp(f['acu_val'], base), es_tit=True, nivel=niv, num=True, danger=over_val)
            self._set(r, COL_S_VAL, money(f['sal_val']), es_tit=True, nivel=niv, num=True)
            self._set(r, COL_S_PCT, _pp(f['sal_val'], base), es_tit=True, nivel=niv, num=True)
            return
        self._set(r, COL_UND, f['unidad'] or "", num=True)
        self._set(r, COL_B_METR, _m(f['base_metr'], dm), num=True)
        self._set(r, COL_B_PU, money(f['precio_unitario']), num=True)
        self._set(r, COL_B_PARC, money(f['base_val']), num=True)
        self._set(r, COL_A_METR, _m(f['ant_metr'], dm), num=True)
        self._set(r, COL_A_VAL, money(f['ant_val']), num=True)
        self._set(r, COL_A_PCT, _pp(f['ant_val'], base), num=True)
        # Grupo «Actual» resaltado en banana; el metrado (editable) más fuerte.
        # Si lo alimenta el parte diario, queda de solo lectura y en azul.
        es_diario = (f.get('origen') == 'diario')
        self._set(r, COL_C_METR, _m(f['act_metr'], dm), num=True,
                  editable=(abierta and not es_diario),
                  bg=(DIARIO_BG if es_diario else BANANA_100),
                  tip=("Metrado calculado desde el parte diario (cuaderno de "
                       "obra). Para cambiarlo, edita los partes del período."
                       if es_diario else None))
        self._set(r, COL_C_VAL, money(f['act_val']), num=True, bg=BANANA_SOFT)
        self._set(r, COL_C_PCT, _pp(f['act_val'], base), num=True, bg=BANANA_SOFT)
        self._set(r, COL_K_METR, _m(f['acu_metr'], dm), num=True, danger=over_metr)
        self._set(r, COL_K_VAL, money(f['acu_val']), num=True, danger=over_val)
        self._set(r, COL_K_PCT, _pp(f['acu_val'], base), num=True, danger=over_val)
        self._set(r, COL_S_METR, _m(f['sal_metr'], dm), num=True)
        self._set(r, COL_S_VAL, money(f['sal_val']), num=True)
        self._set(r, COL_S_PCT, _pp(f['sal_val'], base), num=True)

    def _pintar_total(self, resumen, moneda):
        """Rellena la fila TOTAL congelada (tabla aparte, siempre visible)."""
        base = resumen.get('base_val', 0) or 0
        def money(v):
            return fmt_num(v, moneda)
        vals = {
            COL_DESC: ("TOTAL", Qt.AlignLeft | Qt.AlignVCenter),
            COL_B_PARC: (money(base), None),
            COL_A_VAL: (money(resumen.get('ant_val', 0)), None),
            COL_A_PCT: (_pp(resumen.get('ant_val', 0), base), None),
            COL_C_VAL: (money(resumen.get('act_val', 0)), None),
            COL_C_PCT: (_pp(resumen.get('act_val', 0), base), None),
            COL_K_VAL: (money(resumen.get('acu_val', 0)), None),
            COL_K_PCT: (_pp(resumen.get('acu_val', 0), base), None),
            COL_S_VAL: (money(resumen.get('sal_val', 0)), None),
            COL_S_PCT: (_pp(resumen.get('sal_val', 0), base), None),
        }
        over_tot = _excede(resumen.get('acu_val', 0), base)
        self.tbl_total.blockSignals(True)
        for c in range(NCOLS):
            text, align = vals.get(c, ("", None))
            it = QTableWidgetItem(str(text))
            fnt = it.font(); fnt.setBold(True); it.setFont(fnt)
            actual = c in (COL_C_METR, COL_C_VAL, COL_C_PCT)
            if over_tot and c in (COL_K_VAL, COL_K_PCT):
                it.setForeground(QColor(RED_700))
                it.setBackground(QColor(RED_BG))
            else:
                it.setForeground(QColor("#1A2535"))
                it.setBackground(QColor(BANANA_SOFT if actual else "#D5DBE2"))
            if align is not None:
                it.setTextAlignment(align)
            elif c >= COL_B_METR:
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            else:
                it.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
            it.setFlags(Qt.ItemIsEnabled)
            self.tbl_total.setItem(0, c, it)
        self.tbl_total.blockSignals(False)
        self._sync_total_widths()

    def _on_col_resized(self, idx, _old, new):
        self.tbl_total.setColumnWidth(idx, new)
        # Al redimensionar la Descripción, reajustar el alto de las filas para que
        # el texto envuelto se vea completo (diferido para no reflowar en ráfaga
        # durante el dimensionado masivo de carga).
        if idx == COL_DESC and not self._dimensionando:
            QTimer.singleShot(0, self.tbl.resizeRowsToContents)

    def _sync_total_widths(self):
        for c in range(NCOLS):
            self.tbl_total.setColumnWidth(c, self.tbl.columnWidth(c))

    def _pintar_resumen(self, resumen):
        moneda = self._proy.get('moneda', 'Soles')
        pct = resumen.get('pct_fisico', 0) or 0
        self.lbl_resumen.setText(
            f"Avance físico: {pct:.2f}%    ·    "
            f"Acumulado: {fmt_num(resumen.get('acu_val', 0), moneda)}    ·    "
            f"Saldo: {fmt_num(resumen.get('sal_val', 0), moneda)}")
        self._sync_botones(resumen.get('estado'))

    def _set(self, row, col, text, *, pid_part=None, es_tit=False, nivel=1,
             left=False, num=False, editable=False, depth=0, total=False, bg=None,
             danger=False, tip=None):
        txt = str(text)
        it = QTableWidgetItem()
        if col == COL_DESC:
            if depth > 0:
                txt = ("    " * depth) + txt      # sangría jerárquica (tab)
            it.setToolTip(str(text))             # texto completo al pasar el ratón
        if tip:
            it.setToolTip(tip)
        it.setText(txt)
        if pid_part is not None:
            it.setData(Qt.UserRole, pid_part)
        if num and not left:
            it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        elif not left:
            it.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
        flags = Qt.ItemIsSelectable | Qt.ItemIsEnabled
        if editable:
            flags |= Qt.ItemIsEditable
        it.setFlags(flags)
        if total:
            fnt = it.font(); fnt.setBold(True); it.setFont(fnt)
            it.setForeground(QColor("#1A2535"))
            it.setBackground(QColor("#D5DBE2"))
        elif es_tit:
            color, tbg = NIVEL_ESTILO.get(min(max(nivel, 1), 4),
                                          (SLATE_700, SILVER_200))
            fnt = it.font(); fnt.setBold(True)
            # El color de nivel (N1 rojo, etc.) SOLO en el ítem/descripción; los
            # valores van en negrita oscura para no confundirse con el rojo del
            # acumulado excedente. Tinte de fondo en toda la fila.
            if nivel == 1 and left:
                fnt.setUnderline(True)
            it.setFont(fnt)
            it.setForeground(QColor(color if left else "#1A2535"))
            it.setBackground(QColor(tbg))
        elif editable:
            it.setBackground(QColor(BANANA_100))   # input del período actual
        elif bg:
            it.setBackground(QColor(bg))
        # Alerta de exceso: el acumulado supera la base contractual. Tiene
        # precedencia sobre el estilo de título/banana (texto rojo + tinte).
        if danger:
            fnt = it.font(); fnt.setBold(True); it.setFont(fnt)
            it.setForeground(QColor(RED_700))
            it.setBackground(QColor(RED_BG))
        self.tbl.setItem(row, col, it)

    def _on_item_changed(self, item):
        if item.column() != COL_ACT or not self._val_id:
            return
        item0 = self.tbl.item(item.row(), COL_ITEM)
        if item0 is None:
            return
        pid_part = item0.data(Qt.UserRole)
        if pid_part is None:
            return
        val = parse_num(item.text())
        if val < 0:
            val = 0
        if V.set_metrado_ejecutado(self._val_id, pid_part, val):
            # Reformatear la celda editada a los decimales de metrado (1 → 1.00).
            self.tbl.blockSignals(True)
            item.setText(_m(val, get_decimales_metrado()))
            self.tbl.blockSignals(False)
            # Actualización EN SU LUGAR (no reconstruye la tabla) → rápido y
            # conserva el foco para seguir bajando por la columna.
            self._actualizar_valores()

    def _actualizar_valores(self):
        """Refresca solo las columnas derivadas (acumulado/%/valores/saldo) y
        los subtotales de título + el resumen, sin recrear filas ni recalcular
        anchos. Es lo que se llama tras editar un metrado."""
        if not self._val_id:
            return
        filas, resumen = V.get_valorizacion_detalle(self._val_id)
        dm = get_decimales_metrado()
        moneda = self._proy.get('moneda', 'Soles')
        def money(v):
            return fmt_num(v, moneda)
        self.tbl.blockSignals(True)
        # Solo cambian Actual, Acumulado y Saldo (Anterior/Base son fijos).
        for r, f in enumerate(filas):
            base = f['base_val'] or 0
            es_tit = f['es_titulo']
            niv = f.get('nivel', 1) or 1
            over_val = _excede(f['acu_val'], f['base_val'])
            over_metr = (not es_tit) and _excede(f['acu_metr'], f['base_metr'])
            self._upd(r, COL_C_VAL, money(f['act_val']))
            self._upd(r, COL_C_PCT, _pp(f['act_val'], base))
            self._upd(r, COL_K_VAL, money(f['acu_val']),
                      danger=over_val, es_tit=es_tit, nivel=niv)
            self._upd(r, COL_K_PCT, _pp(f['acu_val'], base),
                      danger=over_val, es_tit=es_tit, nivel=niv)
            self._upd(r, COL_S_VAL, money(f['sal_val']))
            self._upd(r, COL_S_PCT, _pp(f['sal_val'], base))
            if not es_tit:
                self._upd(r, COL_K_METR, _m(f['acu_metr'], dm), danger=over_metr)
                self._upd(r, COL_S_METR, _m(f['sal_metr'], dm))
        self.tbl.blockSignals(False)
        self._pintar_total(resumen, moneda)
        self._pintar_resumen(resumen)

    def _upd(self, r, c, text, danger=None, es_tit=False, nivel=1):
        it = self.tbl.item(r, c)
        if it is None:
            return
        it.setText(str(text))
        if danger is None:
            return   # solo texto; conserva el fondo (ej. banana del «Actual»)
        fnt = it.font()
        if danger:
            fnt.setBold(True); it.setFont(fnt)
            it.setForeground(QColor(RED_700))
            it.setBackground(QColor(RED_BG))
        elif es_tit:
            _color, tbg = NIVEL_ESTILO.get(min(max(nivel, 1), 4),
                                           (SLATE_700, SILVER_200))
            fnt.setBold(True); it.setFont(fnt)
            # _upd solo toca columnas de VALOR → negrita oscura (no color de
            # nivel), igual que en _set; conserva el tinte de fondo del título.
            it.setForeground(QColor("#1A2535"))
            it.setBackground(QColor(tbg))
        else:
            fnt.setBold(False); it.setFont(fnt)
            it.setForeground(QBrush())   # restaura texto/fondo por defecto
            it.setBackground(QBrush())

    # ── Acciones ─────────────────────────────────────────────────────────────

    def _sync_botones(self, estado):
        cerrada = (estado == 'cerrada')
        co = _co_editable(self._proy)
        self.btn_cerrar.setText("Reabrir" if cerrada else "Cerrar")
        self.btn_cerrar.setEnabled(estado is not None and co)
        self.btn_elim.setEnabled(estado == 'abierta' and co)
        if estado is None:
            self.lbl_estado.setText("")
        elif cerrada:
            self.lbl_estado.setText("🔒 CERRADA")
            self.lbl_estado.setStyleSheet("background:transparent; border:none;"
                f" font-size:11px; font-weight:700; color:{RED_700};")
        else:
            self.lbl_estado.setText("● ABIERTA")
            self.lbl_estado.setStyleSheet("background:transparent; border:none;"
                f" font-size:11px; font-weight:700; color:{GREEN_700};")

    def _nueva(self):
        dlg = _PeriodoDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        desde, hasta = dlg.valores()
        V.crear_valorizacion(self.pid, desde, hasta)
        self._recargar_lista()
        self.cmb.setCurrentIndex(self.cmb.count() - 1)

    def _editar_fecha(self):
        if not self._val_id:
            return
        v = V.get_valorizacion(self._val_id)
        if v.get('estado') == 'cerrada':
            QMessageBox.information(self, "Editar fecha",
                "La valorización está cerrada. Reábrela para cambiar su período.")
            return
        dlg = _PeriodoDialog(self, desde=v.get('periodo_desde') or '',
                             hasta=v.get('periodo_hasta') or '',
                             titulo=f"Editar período — Valorización N°{v['numero']}",
                             boton="Guardar")
        if dlg.exec() != QDialog.Accepted:
            return
        desde, hasta = dlg.valores()
        if not V.set_periodo(self._val_id, desde, hasta):
            QMessageBox.warning(self, "Editar fecha",
                                "No se pudo cambiar el período.")
            return
        self._recargar_lista()
        idx = self.cmb.findData(self._val_id)
        if idx >= 0:
            self.cmb.setCurrentIndex(idx)

    def _cerrar_reabrir(self):
        if not self._val_id:
            return
        v = V.get_valorizacion(self._val_id)
        if v['estado'] == 'cerrada':
            V.reabrir_valorizacion(self._val_id)
        else:
            if QMessageBox.question(
                self, "Cerrar valorización",
                "Al cerrar, la valorización queda congelada (no se podrá editar "
                "su metrado). ¿Continuar?") != QMessageBox.Yes:
                return
            V.cerrar_valorizacion(self._val_id)
        self._recargar_lista()

    def _reporte(self, fmt='pdf'):
        if not self._val_id:
            return
        if not _gate_reporte_editable(fmt, self):
            return
        import os
        from PySide6.QtWidgets import QFileDialog
        v = V.get_valorizacion(self._val_id)
        ext = {'pdf': 'pdf', 'xlsx': 'xlsx', 'ods': 'ods'}[fmt]
        filtro = {'pdf': 'PDF (*.pdf)', 'xlsx': 'Excel (*.xlsx)',
                  'ods': 'LibreOffice (*.ods)'}[fmt]
        default = os.path.join(_dir_reportes(),
                               f"valorizacion_{v['numero']:02d}.{ext}")
        path, _ = QFileDialog.getSaveFileName(
            self, "Guardar valorización", default, filtro)
        if not path:
            return
        try:
            if fmt == 'pdf':
                from core import pdf_reports
                pdf_reports.generar_valorizacion_pdf(self._val_id, path)
            elif fmt == 'xlsx':
                from core import exporter
                with open(path, 'wb') as f:
                    f.write(exporter.exportar_valorizacion(self._val_id).getvalue())
            else:
                from core import ods_reports
                ods_reports.generar_ods_valorizacion(self._val_id, path)
            _guardar_dir_reportes(path)
            QMessageBox.information(self, "Reporte", f"Guardado en:\n{path}")
        except Exception as e:
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "Reporte",
                                 f"No se pudo generar el reporte:\n{e}")

    def _eliminar(self):
        if not self._val_id:
            return
        v = V.get_valorizacion(self._val_id)
        if QMessageBox.question(
            self, "Eliminar valorización",
            f"¿Eliminar la Valorización N°{v['numero']}? "
            "Solo se puede borrar la última y abierta.") != QMessageBox.Yes:
            return
        if not V.eliminar_valorizacion(self._val_id):
            QMessageBox.warning(self, "Eliminar",
                "Solo se puede eliminar la ÚLTIMA valorización y si está abierta.")
            return
        self._val_id = None
        self._recargar_lista()


# ── Cuaderno de obra / parte diario ──────────────────────────────────────────

# Columnas FIJAS de la grilla del cuaderno (Ítem · Descripción · Und · Metrado
# contractual · Metrado acumulado ejecutado). Los días van como columnas extra a
# la derecha (una por parte/fecha). El «Acumulado» va junto al contractual para
# verlos juntos sin desplazarse a los días lejanos.
(CUA_ITEM, CUA_DESC, CUA_UND, CUA_BASE, CUA_ACUM) = range(5)
CUA_NFIJAS = 5
_CUA_FIJAS = ["Ítem", "Descripción", "Und", "Metrado\ncontractual",
              "Ejecutado\nacumulado"]
DAY_CLOSED_BG = "#F0F1F2"     # columna de un día cerrado (solo lectura)
ACTIVE_DAY_BG = BANANA_SOFT   # columna del día seleccionado
ACUM_BG = "#EEF1F4"           # columna de acumulado

# Planilla de metrados (referencia del proyecto + del día) — mismas columnas
# que la hoja de metrados del presupuesto. Parcial = producto de dims llenas.
_MET_COLS = ["Descripción", "N°Est.", "N°Elem.", "Área", "Largo", "Ancho",
             "Alto", "Parcial"]
_MET_DIMS = ('n_estructuras', 'n_elementos', 'area', 'largo', 'ancho', 'alto')

# Recursos del día (Fase B): mano de obra (personas) e insumos (consumo).
(RES_DESC, RES_UND, RES_CANT) = range(3)
_RES_COLS = ["Recurso", "Und", "Cantidad"]


_MESES = ['ENERO', 'FEBRERO', 'MARZO', 'ABRIL', 'MAYO', 'JUNIO', 'JULIO',
          'AGOSTO', 'SEPTIEMBRE', 'OCTUBRE', 'NOVIEMBRE', 'DICIEMBRE']
_DIAS_SEM = ['lun', 'mar', 'mié', 'jue', 'vie', 'sáb', 'dom']  # 0=lunes


def _fecha_larga(iso):
    """«yyyy-MM-dd» → «12 DE JUNIO DE 2099» (día número, mes en letras, año número)."""
    p = str(iso).split('-')
    if len(p) == 3 and len(p[0]) == 4:
        try:
            m = int(p[1])
            if 1 <= m <= 12:
                return f"{int(p[2])} DE {_MESES[m - 1]} DE {p[0]}"
        except ValueError:
            pass
    return _fmt_fecha(iso)


def _cant_entera(c):
    """Cantidad de mano de obra para el asiento: entero con cero a la izquierda
    (01, 11) como en el cuaderno; si trae decimales, se muestra tal cual."""
    try:
        f = float(c)
        return f"{int(f):02d}" if f == int(f) else f"{f:g}"
    except (TypeError, ValueError):
        return str(c)


def _zebra(r):
    """Color de fila (zebra) OPACO por índice — para que ninguna celda quede
    transparente (las vistas congeladas no repintan limpio las transparentes)."""
    return "#FFFFFF" if (r % 2 == 0) else SILVER_100


def _numtxt(v):
    """Número para celda de planilla: vacío si None o 0, sin ceros sobrantes.
    (Las dimensiones vacías del proyecto se guardan como 0; mostrarlas como «0»
    haría que el parcial se calcule en 0 al copiarlas.)"""
    if v is None or v == "":
        return ""
    try:
        f = float(v)
        return "" if f == 0 else f"{f:g}"
    except (TypeError, ValueError):
        return str(v)


class _MetTable(QTableWidget):
    """Tabla de la planilla de metrados con teclas estilo Excel manejadas en
    keyPressEvent (más fiable que QShortcut/eventFilter: se invoca siempre en la
    tabla enfocada y, al editar una celda, el foco lo tiene el editor → no
    interfiere). Los callbacks `on_*` los asigna el panel."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.on_copy = self.on_paste = self.on_cut = self.on_delete = None

    def _es_tecla_propia(self, e):
        return (e.matches(QKeySequence.Copy) or e.matches(QKeySequence.Paste)
                or e.matches(QKeySequence.Cut)
                or e.key() in (Qt.Key_Delete, Qt.Key_Backspace))

    def event(self, e):
        # Reclamar estas teclas frente a atajos globales (p. ej. «eliminar
        # partida»): aceptar el ShortcutOverride hace que Qt las entregue como
        # pulsación normal a esta tabla (la enfocada) en vez de disparar el atajo.
        if e.type() == QEvent.ShortcutOverride and self._es_tecla_propia(e):
            e.accept()
            return True
        return super().event(e)

    def keyPressEvent(self, e):
        if e.matches(QKeySequence.Copy) and self.on_copy:
            self.on_copy(); return
        if e.matches(QKeySequence.Paste) and self.on_paste:
            self.on_paste(); return
        if e.matches(QKeySequence.Cut) and self.on_cut:
            self.on_cut(); return
        if e.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self.on_delete:
            self.on_delete(); return
        super().keyPressEvent(e)


class _FrozenGrid(QTableWidget):
    """QTableWidget con columnas «congeladas» a la izquierda Y/O a la derecha
    (siempre visibles al desplazarse horizontalmente), estilo «inmovilizar
    paneles» de Excel. Se logra con vistas superpuestas que comparten el modelo y
    la selección, y sincronizan scroll vertical, anchos y alto de filas.

    `frozen` = nº de columnas fijas a la izquierda · `frozen_right` = nº de
    columnas fijas a la derecha (las últimas, p. ej. «Acumulado»)."""

    def __init__(self, frozen=0, frozen_right=0, parent=None):
        super().__init__(parent)
        self._frozen = max(0, frozen)
        self._frozen_r = max(0, frozen_right)
        self._fz = QTableView(self)    # panel izquierdo
        self._fzr = QTableView(self)   # panel derecho
        self._init_fz(self._fz)
        self._init_fz(self._fzr)
        self.horizontalHeader().sectionResized.connect(self._on_col_resized)
        self.verticalHeader().sectionResized.connect(self._on_row_resized)
        for fzv in (self._fz, self._fzr):
            fzv.verticalScrollBar().valueChanged.connect(
                self.verticalScrollBar().setValue)
            self.verticalScrollBar().valueChanged.connect(
                fzv.verticalScrollBar().setValue)
            fzv.hide()
        # Reposicionar el panel derecho al desplazarse horizontalmente.
        self.horizontalScrollBar().valueChanged.connect(self._update_fz_geometry)

    def frozenView(self):
        return self._fz

    def frozenRightView(self):
        return self._fzr

    def _init_fz(self, fz):
        fz.setModel(self.model())
        fz.setSelectionModel(self.selectionModel())
        fz.setFocusPolicy(Qt.NoFocus)
        fz.verticalHeader().hide()
        fz.setFrameShape(QFrame.NoFrame)
        fz.setEditTriggers(QAbstractItemView.NoEditTriggers)
        fz.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        fz.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        fz.setAlternatingRowColors(True)
        fz.horizontalHeader().setSectionResizeMode(QHeaderView.Fixed)
        fz.setWordWrap(False)
        self.viewport().stackUnder(fz)

    def _right_cols(self):
        n = self.columnCount()
        return list(range(n - self._frozen_r, n)) if (self._frozen_r and n) else []

    def _on_col_resized(self, idx, _old, new):
        if idx < self._frozen:
            self._fz.setColumnWidth(idx, new)
        if idx in self._right_cols():
            self._fzr.setColumnWidth(idx, new)
        self._update_fz_geometry()

    def _on_row_resized(self, idx, _old, new):
        self._fz.setRowHeight(idx, new)
        self._fzr.setRowHeight(idx, new)

    def sync_frozen(self):
        """Re-sincroniza las vistas congeladas tras reconstruir la tabla."""
        n = self.columnCount()
        self._sync_one(self._fz, range(self._frozen) if (self._frozen and n) else [])
        self._sync_one(self._fzr, self._right_cols())
        self._update_fz_geometry()

    def _sync_one(self, fz, cols):
        cols = list(cols)
        if not cols:
            fz.hide(); return
        for c in range(self.columnCount()):
            fz.setColumnHidden(c, c not in cols)
            if c in cols:
                fz.setColumnWidth(c, self.columnWidth(c))
        for r in range(self.rowCount()):
            fz.setRowHeight(r, self.rowHeight(r))
        fz.show()

    def _update_fz_geometry(self):
        h = self.viewport().height() + self.horizontalHeader().height()
        if self._frozen > 0 and self.columnCount():
            w = sum(self.columnWidth(c) for c in range(self._frozen))
            self._fz.setGeometry(self.frameWidth(), self.frameWidth(), w, h)
        rc = self._right_cols()
        if rc:
            w = sum(self.columnWidth(c) for c in rc)
            # Posición REAL de la columna; fijada al borde derecho solo cuando se
            # saldría de la vista (contenido más ancho que el viewport). Así no
            # hay desfase cuando las columnas caben sin scroll.
            natural = self.columnViewportPosition(rc[0])
            x = self.frameWidth() + min(natural, self.viewport().width() - w)
            self._fzr.setGeometry(x, self.frameWidth(), w, h)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._update_fz_geometry()

    def scrollTo(self, index, hint=QAbstractItemView.EnsureVisible):
        # No dejar que una celda quede oculta bajo los paneles congelados.
        c = index.column()
        if self._frozen <= c < self.columnCount() - self._frozen_r:
            rect = self.visualRect(index)
            izq = sum(self.columnWidth(x) for x in range(self._frozen))
            der = sum(self.columnWidth(x) for x in self._right_cols())
            if rect.left() < izq:
                self.horizontalScrollBar().setValue(
                    self.horizontalScrollBar().value() + rect.left() - izq)
            elif rect.right() > self.viewport().width() - der:
                self.horizontalScrollBar().setValue(
                    self.horizontalScrollBar().value() + rect.right()
                    - (self.viewport().width() - der))
        super().scrollTo(index, hint)


class _MesHeader(QHeaderView):
    """Cabecera de la grilla de días (2 niveles): arriba el MES + año agrupando
    los días consecutivos del mismo mes; abajo el día del mes (+ 🔒 si cerrado)."""

    def __init__(self, parent=None):
        super().__init__(Qt.Horizontal, parent)
        self._cols = []   # [{'mes': 'JUNIO 2026', 'dia': '24', 'cerr': bool}]
        self._active_col = None   # columna del día que se está llenando
        self.setSectionsClickable(True)
        self.setHighlightSections(False)

    def set_cols(self, cols):
        self._cols = cols
        self.viewport().update()

    def set_active_col(self, col):
        if col != self._active_col:
            self._active_col = col
            self.viewport().update()

    def sizeHint(self):
        s = super().sizeHint()
        return QSize(s.width(), 40)

    def _cell(self, p, rect, text, *, bold=False, bg=SILVER_200):
        p.fillRect(rect, QColor(bg))
        # Solo borde derecho + inferior (evita la doble línea entre celdas
        # adyacentes; igual que el header de la tabla fija).
        p.setPen(QColor(SILVER_300))
        p.drawLine(rect.right(), rect.top(), rect.right(), rect.bottom())
        p.drawLine(rect.left(), rect.bottom(), rect.right(), rect.bottom())
        f = p.font(); f.setBold(bold); f.setPointSize(8); p.setFont(f)
        p.setPen(QColor(SLATE_700))
        p.drawText(rect.adjusted(2, 0, -2, 0), Qt.AlignCenter, str(text or ''))

    def paintEvent(self, e):
        p = QPainter(self.viewport())
        H = self.height(); half = H // 2
        n = min(self.count(), len(self._cols))
        act = self._active_col
        # Fila inferior: día por columna (activo = banana + negrita).
        for i in range(n):
            x = self.sectionViewportPosition(i); w = self.sectionSize(i)
            c = self._cols[i]
            txt = c['dia'] + (' 🔒' if c.get('cerr') else '')
            es_act = (i == act)
            self._cell(p, QRect(x, half, w, H - half), txt, bold=es_act,
                       bg=ACTIVE_DAY_BG if es_act else SILVER_200)
        # Fila superior: mes agrupado (columnas consecutivas del mismo mes).
        i = 0
        while i < n:
            mes = self._cols[i]['mes']
            j = i
            while j + 1 < n and self._cols[j + 1]['mes'] == mes:
                j += 1
            x = self.sectionViewportPosition(i)
            w = sum(self.sectionSize(k) for k in range(i, j + 1))
            self._cell(p, QRect(x, 0, w, half), mes, bold=True, bg=SILVER_200)
            i = j + 1
        # Marco de acento (naranja) alrededor de la columna del día activo, para
        # que se vea claramente qué día se está llenando abajo.
        if act is not None and 0 <= act < n:
            x = self.sectionViewportPosition(act); w = self.sectionSize(act)
            pen = QPen(QColor(ORANGE)); pen.setWidth(2)
            p.setPen(pen)
            p.drawRect(QRect(x + 1, 1, w - 2, H - 3))


class _CuadernoPanel(QWidget):
    """Parte diario en formato planilla: partidas en filas, un DÍA por columna a
    la derecha. Al seleccionar la columna de un día se editan, abajo, sus
    incidencias/observaciones. Cada «Metr. del día» se acumula hacia la
    valorización cuyo período contiene la fecha (modelo mixto). Solo se edita el
    metrado del día (y las observaciones del día seleccionado)."""

    def __init__(self, pid: int, proy: dict, parent=None):
        super().__init__(parent)
        self.pid = pid
        self._proy = proy
        self._partidas = []
        self._partes = []
        self._col2parte = {}        # col (en tbl_dias) -> parte_id
        self._estado_col = {}       # col -> 'abierto'|'cerrado'
        self._col_fecha = {}        # col -> fecha ISO (para saltar desde Almacén)
        self._es_titulo_row = []
        self._row_partida = []      # fila -> partida_id
        self._dia_col = None        # columna del día activo
        self._dia_parte = None      # parte_id del día activo
        self._partida_sel = None    # partida seleccionada (para sus metrados)
        self._part_by_id = {}
        self._con_detalle = set()   # (parte_id, partida_id) con planilla del día
        self._dia_abierto = False   # ¿el día activo admite edición?
        self._obs_pendiente = False
        self._rendering = False
        self._met_loading = False
        self._res_tbl = {}            # clase -> tabla de recursos del día
        self._res_btn_estimar = []
        self._estimar_enteros = True   # redondear MAT/EQ/SC a unidades enteras (def)
        self._chk_enteros = []        # checkboxes «Enteros» (una por pestaña)
        self._dia_delegate = _MetradoDelegate(self)
        self._build_ui()

    def _build_ui(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 8, 10, 8)
        v.setSpacing(8)

        # Botón «+ Días» (se ubica en la cabecera del día, abajo; ver _build_ui
        # del panel). Cada columna del grid es un día; se selecciona haciendo clic
        # en su columna y se registran sus datos en el panel de abajo.
        self.btn_nuevo = QPushButton("+ Días")
        self.btn_nuevo.setToolTip("Generar uno o varios días (rango) para el "
            "cuaderno. Cada columna del grid es un día.")
        self.btn_nuevo.setCursor(Qt.PointingHandCursor)
        self.btn_nuevo.setStyleSheet(
            f"QPushButton {{ background:{ORANGE}; color:white; border:none;"
            f" border-radius:6px; font-size:11px; font-weight:600;"
            f" padding:4px 12px; }}"
            f"QPushButton:hover {{ background:#C0621A; }}")
        self.btn_nuevo.clicked.connect(self._nuevo)

        # DOS tablas reales lado a lado (columnas «congeladas» robustas, sin
        # overlays): IZQUIERDA fija (Ítem·Descripción·Und·Metrado contractual·
        # Metrado acumulado) sin scroll horizontal; DERECHA con los días, que se
        # desplaza. El scroll vertical va sincronizado por fila.
        _grid_qss = (
            f"background:white; alternate-background-color:{SILVER_100};"
            f" gridline-color:{SILVER_200}; font-size:11px;")
        _hdr_qss = (
            f"QHeaderView::section {{ background:{SILVER_200}; color:{SLATE_700};"
            f" border:none; border-right:1px solid {SILVER_300};"
            f" border-bottom:1px solid {SILVER_300}; padding:3px; font-weight:600; }}")
        _sel = (f" QTableWidget::item:selected {{ background:{SELECT_BG};"
                f" color:{SLATE_700}; }}")

        self.tbl_fix = QTableWidget()
        self.tbl_fix.setColumnCount(CUA_NFIJAS)
        self.tbl_fix.setHorizontalHeaderLabels(_CUA_FIJAS)
        self.tbl_fix.verticalHeader().setVisible(False)
        self.tbl_fix.setAlternatingRowColors(True)
        self.tbl_fix.setWordWrap(True)
        self.tbl_fix.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tbl_fix.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tbl_fix.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl_fix.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl_fix.setStyleSheet(
            f"QTableWidget {{ {_grid_qss} border:none;"
            f" border-right:2px solid {SLATE_300}; }}" + _hdr_qss + _sel)
        self.tbl_fix.verticalHeader().setDefaultSectionSize(24)
        self.tbl_fix.cellClicked.connect(self._on_fix_clicked)

        self.tbl_dias = QTableWidget()
        self._mes_header = _MesHeader(self.tbl_dias)
        self.tbl_dias.setHorizontalHeader(self._mes_header)
        self.tbl_dias.verticalHeader().setVisible(False)
        self.tbl_dias.setAlternatingRowColors(True)
        self.tbl_dias.setWordWrap(False)
        self.tbl_dias.setEditTriggers(QAbstractItemView.DoubleClicked
                                      | QAbstractItemView.SelectedClicked
                                      | QAbstractItemView.AnyKeyPressed)
        self.tbl_dias.setStyleSheet(
            f"QTableWidget {{ {_grid_qss} }}" + _hdr_qss + _sel)
        self.tbl_dias.verticalHeader().setDefaultSectionSize(24)
        self.tbl_dias.itemChanged.connect(self._on_item_changed)
        self.tbl_dias.cellClicked.connect(self._on_cell_clicked)
        self._mes_header.sectionClicked.connect(self._activar_dia)
        # Alinear la altura de cabecera de la tabla fija (izquierda) con la de
        # 2 niveles de los días para que las filas queden a la par.
        self.tbl_fix.horizontalHeader().setFixedHeight(40)

        # Estado vacío: cuando no hay ningún día creado, la tabla de la derecha
        # queda en blanco y no es obvio qué hacer. Overlay clickable que invita
        # a crear el primer día (equivale al botón «+ Días»).
        self._lbl_dias_vacio = QLabel(
            "Sin días registrados.\n\nHaz clic aquí o en «+ Días»\npara crear el primero.",
            self.tbl_dias.viewport())
        self._lbl_dias_vacio.setAlignment(Qt.AlignCenter)
        self._lbl_dias_vacio.setCursor(Qt.PointingHandCursor)
        self._lbl_dias_vacio.setStyleSheet(
            f"QLabel {{ background:white; color:{SLATE_300};"
            f" font-size:13px; font-weight:600; border:none; }}")
        self._lbl_dias_vacio.hide()
        self._lbl_dias_vacio.installEventFilter(self)
        self.tbl_dias.viewport().installEventFilter(self)

        # Scroll vertical sincronizado (por fila).
        self.tbl_dias.verticalScrollBar().valueChanged.connect(
            self.tbl_fix.verticalScrollBar().setValue)
        self.tbl_fix.verticalScrollBar().valueChanged.connect(
            self.tbl_dias.verticalScrollBar().setValue)

        # Split horizontal ARRIBA: tabla fija | tabla de días (arrastrable, y su
        # posición se sincroniza con el split del panel de abajo).
        self._sp_top = QSplitter(Qt.Horizontal)
        self._sp_top.setChildrenCollapsible(False)
        self._sp_top.setHandleWidth(2)
        self._sp_top.addWidget(self.tbl_fix)
        self._sp_top.addWidget(self.tbl_dias)
        # La Descripción ocupa el ancho que sobre en la tabla fija (que define el
        # split), así no queda espacio vacío ni scroll horizontal.
        self.tbl_fix.horizontalHeader().setSectionResizeMode(
            CUA_DESC, QHeaderView.Stretch)
        self._sp_inited = False
        self._sync_guard = False
        self._h_timer = QTimer(self); self._h_timer.setSingleShot(True)
        self._h_timer.setInterval(60)
        self._h_timer.timeout.connect(self._resync_heights)
        self._sp_top.splitterMoved.connect(lambda *a: self._on_split_moved(True))

        # Split vertical: planilla de días arriba, panel del día abajo.
        self._split = QSplitter(Qt.Vertical)
        self._split.setChildrenCollapsible(False)
        self._split.addWidget(self._sp_top)
        v.addWidget(self._split, stretch=1)

        # Panel inferior: día seleccionado + incidencias + planillas de metrados.
        self._panel = QFrame()
        self._panel.setStyleSheet(
            f"QFrame {{ background:{SILVER_100}; border:none; }}")
        pv = QVBoxLayout(self._panel)
        pv.setContentsMargins(10, 8, 10, 8)
        pv.setSpacing(6)
        def _sbtn(txt, fn):
            b = QPushButton(txt)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(
                f"QPushButton {{ background:white; color:{SLATE_700};"
                f" border:1px solid {SILVER_300}; border-radius:6px;"
                f" font-size:11px; padding:4px 10px; }}"
                f"QPushButton:hover {{ background:{SILVER_200}; }}"
                f"QPushButton:disabled {{ color:{SLATE_300}; }}")
            b.clicked.connect(fn)
            return b

        cab = QHBoxLayout(); cab.setSpacing(6)
        self.lbl_dia = QLabel("—")
        self.lbl_dia.setStyleSheet(f"color:{SLATE_700}; font-size:12px;"
                                   " font-weight:700; background:transparent; border:none;")
        cab.addWidget(self.lbl_dia)
        cab.addWidget(self.btn_nuevo)   # «+ Días» junto a la fecha
        # «Vista para cuaderno» al costado de la fecha del día.
        self.btn_cuaderno = _sbtn("📋 Vista para cuaderno", self._vista_cuaderno)
        self.btn_cuaderno.setToolTip("Arma el asiento del día (mano de obra, "
            "materiales, actividades y observaciones) listo para transcribir.")
        cab.addWidget(self.btn_cuaderno)
        self.btn_reporte = _sbtn("📄 Reporte", lambda: None)
        self.btn_reporte.setToolTip("Genera un reporte del cuaderno con los días "
                                    "que elijas (PDF, Word u ODT).")
        _rm = QMenu(self.btn_reporte)
        _rm.addAction("PDF", lambda: self._reporte('pdf'))
        _rm.addAction("Word (.docx)", lambda: self._reporte('docx'))
        _rm.addAction("LibreOffice (.odt)", lambda: self._reporte('odt'))
        self.btn_reporte.setMenu(_rm)
        cab.addWidget(self.btn_reporte)
        cab.addStretch()
        self.lbl_estado = QLabel("")
        self.lbl_estado.setStyleSheet("background:transparent; border:none;"
                                      " font-size:11px; font-weight:700;")
        cab.addWidget(self.lbl_estado)
        self.btn_cerrar = _sbtn("Cerrar", self._cerrar_reabrir)
        self.btn_elim = _sbtn("Eliminar", self._eliminar)
        cab.addWidget(self.btn_cerrar)
        cab.addWidget(self.btn_elim)
        pv.addLayout(cab)

        # Mitad inferior: izquierda incidencias, derecha metrados (en pestañas).
        cuerpo = QSplitter(Qt.Horizontal)
        cuerpo.setChildrenCollapsible(False)
        cuerpo.setHandleWidth(2)
        self._sp_bot = cuerpo
        cuerpo.splitterMoved.connect(lambda *a: self._on_split_moved(False))

        _tabs_qss = (
            f"QTabWidget::pane {{ border:1px solid {SILVER_300}; border-radius:6px;"
            f" top:-1px; background:white; }}"
            f"QTabBar::tab {{ background:{SILVER_200}; color:{SLATE_700};"
            f" padding:3px 12px; font-size:10px; font-weight:600;"
            f" border:1px solid {SILVER_300}; border-bottom:none;"
            f" border-top-left-radius:5px; border-top-right-radius:5px; }}"
            f"QTabBar::tab:selected {{ background:white; color:{ORANGE}; }}")

        # Izquierda — TODO lo del día: incidencias · mano de obra · insumos.
        self.tabs_dia = QTabWidget()
        self.tabs_dia.setStyleSheet(_tabs_qss)
        # Incidencias.
        winc = QWidget(); winc.setStyleSheet("background:white;")
        il = QVBoxLayout(winc); il.setContentsMargins(4, 4, 4, 4); il.setSpacing(2)
        self.txt_obs = QPlainTextEdit()
        self.txt_obs.setMinimumHeight(84)
        self.txt_obs.setPlaceholderText(
            "Ocurrencias, instrucciones del supervisor, observaciones del residente…")
        self.txt_obs.setStyleSheet(
            f"QPlainTextEdit {{ border:none; padding:2px; font-size:11px;"
            f" background:white; }}")
        self.txt_obs.textChanged.connect(self._obs_dirty)
        il.addWidget(self.txt_obs, stretch=1)
        # Orden de pestañas: Mano de obra · Insumos · Incidencias.
        self._res_tbl = {}
        self.tabs_dia.addTab(self._mk_tab_recursos('mo', _sbtn), "Mano de obra")
        self.tabs_dia.addTab(self._mk_tab_insumos(_sbtn), "Insumos")
        self.tabs_dia.addTab(winc, "Incidencias")
        cuerpo.addWidget(self.tabs_dia)

        # Derecha — metrados de la partida seleccionada, en pestañas.
        der = QWidget(); der.setStyleSheet("background:transparent;")
        rv = QVBoxLayout(der); rv.setContentsMargins(0, 0, 0, 0); rv.setSpacing(2)
        self.lbl_part = QLabel("Selecciona una partida para ver y registrar sus "
                               "metrados del día.")
        self.lbl_part.setWordWrap(True)
        self.lbl_part.setStyleSheet(f"color:{SLATE_700}; font-size:11px;"
            " font-weight:700; background:transparent; border:none;")
        rv.addWidget(self.lbl_part)
        self.tabs_met = QTabWidget()
        self.tabs_met.setStyleSheet(
            f"QTabWidget::pane {{ border:1px solid {SILVER_300}; border-radius:6px;"
            f" top:-1px; background:white; }}"
            f"QTabBar::tab {{ background:{SILVER_200}; color:{SLATE_700};"
            f" padding:3px 12px; font-size:10px; font-weight:600;"
            f" border:1px solid {SILVER_300}; border-bottom:none;"
            f" border-top-left-radius:5px; border-top-right-radius:5px; }}"
            f"QTabBar::tab:selected {{ background:white; color:{ORANGE}; }}")
        # Pestaña «Del proyecto» (referencia, solo lectura).
        wref = QWidget(); wref.setStyleSheet("background:white;")
        wrl = QVBoxLayout(wref); wrl.setContentsMargins(4, 4, 4, 4); wrl.setSpacing(2)
        self.tbl_ref = self._mk_met_table(editable=False)
        wrl.addWidget(self.tbl_ref, stretch=1)
        self.lbl_ref_total = QLabel("")
        self.lbl_ref_total.setAlignment(Qt.AlignRight)
        self.lbl_ref_total.setStyleSheet(f"color:{SLATE_700}; font-size:10px;"
            " font-weight:700; background:transparent; border:none;")
        wrl.addWidget(self.lbl_ref_total)
        self.tabs_met.addTab(wref, "Del proyecto (referencia)")
        # Pestaña «Del día» (editable).
        wdia = QWidget(); wdia.setStyleSheet("background:white;")
        wdl = QVBoxLayout(wdia); wdl.setContentsMargins(4, 4, 4, 4); wdl.setSpacing(2)
        hint_cp = QLabel("Copia filas de «Del proyecto» (Ctrl+C / clic derecho) y "
                         "pégalas aquí (Ctrl+V).")
        hint_cp.setStyleSheet(f"color:{SLATE_300}; font-size:9px; font-style:italic;"
            " background:transparent; border:none;")
        wdl.addWidget(hint_cp)
        self.tbl_dia = self._mk_met_table(editable=True)
        self.tbl_dia.itemChanged.connect(self._on_met_dia_changed)
        wdl.addWidget(self.tbl_dia, stretch=1)
        self.lbl_dia_total = QLabel("")
        self.lbl_dia_total.setAlignment(Qt.AlignRight)
        self.lbl_dia_total.setStyleSheet(f"color:{SLATE_700}; font-size:10px;"
            " font-weight:700; background:transparent; border:none;")
        wdl.addWidget(self.lbl_dia_total)
        self.tabs_met.addTab(wdia, "Del día (editable)")
        self.tabs_met.setCurrentIndex(1)   # arranca en «Del día»
        rv.addWidget(self.tabs_met, stretch=1)
        cuerpo.addWidget(der)

        cuerpo.setSizes([400, 400])
        pv.addWidget(cuerpo, stretch=1)

        # Menús contextuales (clic derecho) de las planillas de metrados.
        self.tbl_ref.customContextMenuRequested.connect(
            lambda pos: self._menu_metrados(self.tbl_ref, pos, editable=False))
        self.tbl_dia.customContextMenuRequested.connect(
            lambda pos: self._menu_metrados(self.tbl_dia, pos, editable=True))

        self._split.addWidget(self._panel)
        self._split.setStretchFactor(0, 3)
        self._split.setStretchFactor(1, 2)
        self._split.setSizes([340, 320])

        # Estado vacío (sin presupuesto).
        self.lbl_vacio = QLabel(
            "Para registrar avance necesitas el presupuesto del proyecto.\n"
            "Impórtalo o créalo desde la pestaña «Presupuesto».")
        self.lbl_vacio.setAlignment(Qt.AlignCenter)
        self.lbl_vacio.setStyleSheet(
            f"color:{SLATE_300}; font-size:13px; background:transparent;"
            " border:none;")
        self.lbl_vacio.hide()
        v.addWidget(self.lbl_vacio)

    # ── Carga / render ───────────────────────────────────────────────────────

    def cargar(self):
        self._partidas = PD.partidas_proyecto(self.pid)
        no_titulos = [p for p in self._partidas if not p['es_titulo']]
        sin_ppto = (len(no_titulos) == 0)
        self._split.setVisible(not sin_ppto)
        self.lbl_vacio.setVisible(sin_ppto)
        self.btn_nuevo.setEnabled(not sin_ppto and _co_editable(self._proy))
        if sin_ppto:
            return
        self._render()

    def eventFilter(self, obj, ev):
        # Mantener el overlay de estado vacío cubriendo el viewport de los días.
        if obj is self.tbl_dias.viewport() and ev.type() == QEvent.Resize:
            self._lbl_dias_vacio.setGeometry(self.tbl_dias.viewport().rect())
        elif obj is self._lbl_dias_vacio and ev.type() == QEvent.MouseButtonRelease:
            self._nuevo()
            return True
        return super().eventFilter(obj, ev)

    def _render(self):
        prev = self._dia_parte
        self._partes = PD.listar_partes(self.pid)
        partes = self._partes
        # Estado vacío en la tabla de días (no hay ningún parte creado).
        if hasattr(self, '_lbl_dias_vacio'):
            if partes:
                self._lbl_dias_vacio.hide()
            else:
                self._lbl_dias_vacio.setGeometry(self.tbl_dias.viewport().rect())
                self._lbl_dias_vacio.show()
                self._lbl_dias_vacio.raise_()
        self._part_by_id = {p['id']: p for p in self._partidas}
        self._con_detalle = PD.claves_con_detalle(self.pid)
        dm = get_decimales_metrado()
        metr_por_parte = {pr['id']: PD.get_metrados_dia(pr['id']) for pr in partes}

        # Días → columnas de la tabla DERECHA (índice 0-based en tbl_dias).
        self._col2parte = {}
        self._estado_col = {}
        self._col_fecha = {}
        day_cols = []
        for j, pr in enumerate(partes):
            self._col2parte[j] = pr['id']
            self._estado_col[j] = pr['estado']
            self._col_fecha[j] = str(pr['fecha'])
            p = str(pr['fecha']).split('-')
            if len(p) == 3:
                mes = f"{_MESES[int(p[1]) - 1]} {p[0]}"
                try:
                    from datetime import date as _date
                    wd = _date(int(p[0]), int(p[1]), int(p[2])).weekday()
                    dia = f"{_DIAS_SEM[wd]} {int(p[2])}"
                except ValueError:
                    dia = str(int(p[2]))
            else:
                mes, dia = '', str(pr['fecha'])
            day_cols.append({'mes': mes, 'dia': dia,
                             'cerr': pr['estado'] == 'cerrado'})

        dots = [(p['item'] or '').count('.') for p in self._partidas]
        min_dots = min(dots) if dots else 0
        nrows = len(self._partidas)
        self._row_partida = [p['id'] for p in self._partidas]

        self._rendering = True
        self.tbl_fix.blockSignals(True)
        self.tbl_dias.blockSignals(True)
        self.tbl_fix.setRowCount(nrows)
        self.tbl_dias.setColumnCount(len(partes))
        self._mes_header.set_cols(day_cols)
        self.tbl_dias.setRowCount(nrows)
        self._es_titulo_row = []
        for r, p in enumerate(self._partidas):
            es_tit = p['es_titulo']
            self._es_titulo_row.append(es_tit)
            niv = p.get('nivel', 1) or 1
            depth = max(0, (p['item'] or '').count('.') - min_dots)
            # IZQUIERDA (fija)
            self._celda(self.tbl_fix, r, CUA_ITEM, p['item'], left=True,
                        es_tit=es_tit, niv=niv)
            self._celda(self.tbl_fix, r, CUA_DESC, p['descripcion'], left=True,
                        es_tit=es_tit, niv=niv, depth=depth)
            self.tbl_fix.item(r, CUA_ITEM).setData(Qt.UserRole, p['id'])
            if es_tit:
                for c in range(CUA_UND, CUA_NFIJAS):
                    self._celda(self.tbl_fix, r, c, "")
                for j in range(len(partes)):
                    self._celda(self.tbl_dias, r, j, "")
                continue
            self._celda(self.tbl_fix, r, CUA_UND, p['unidad'] or "")
            self._celda(self.tbl_fix, r, CUA_BASE, _m(p['metrado'] or 0, dm), num=True)
            total = 0.0
            for j, pr in enumerate(partes):
                val = metr_por_parte[pr['id']].get(p['id'], 0)
                total += val
                cerr = (pr['estado'] == 'cerrado')
                det = (pr['id'], p['id']) in self._con_detalle
                self._celda(self.tbl_dias, r, j, (_m(val, dm) if val else ""),
                            num=True,
                            editable=(not cerr and not det and _co_editable(self._proy)),
                            daybg=(DAY_CLOSED_BG if cerr else None),
                            rotip=("Metrado calculado desde la planilla del día."
                                   if det else None))
            self._celda(self.tbl_fix, r, CUA_ACUM, (_m(total, dm) if total else ""),
                        num=True, acum=True, over=_excede(total, p['metrado'] or 0))
        self.tbl_fix.blockSignals(False)
        self.tbl_dias.blockSignals(False)
        self._rendering = False

        # Delegate de metrado en cada columna de día.
        for j in range(len(partes)):
            self.tbl_dias.setItemDelegateForColumn(j, self._dia_delegate)

        # Anchos tabla fija: las fijas a contenido; la Descripción es Stretch
        # (absorbe el ancho que da el split). No se usa ancho fijo.
        for c in (CUA_ITEM, CUA_UND, CUA_BASE, CUA_ACUM):
            self.tbl_fix.resizeColumnToContents(c)
        if self.tbl_fix.columnWidth(CUA_BASE) < 70:
            self.tbl_fix.setColumnWidth(CUA_BASE, 70)
        if self.tbl_fix.columnWidth(CUA_ACUM) < 80:
            self.tbl_fix.setColumnWidth(CUA_ACUM, 80)
        nondesc = sum(self.tbl_fix.columnWidth(c)
                      for c in (CUA_ITEM, CUA_UND, CUA_BASE, CUA_ACUM))
        self.tbl_fix.setMinimumWidth(nondesc + 60)   # no colapsar bajo las fijas

        # Anchos tabla días: compactos.
        for j in range(len(partes)):
            if self.tbl_dias.columnWidth(j) < 64:
                self.tbl_dias.setColumnWidth(j, 64)

        # Posición inicial de los splits (sincronizados arriba/abajo): la tabla
        # fija arranca con un ancho cómodo para la Descripción.
        if not self._sp_inited:
            wfix = nondesc + 250
            tot = self._sp_top.width() or 1000
            sizes = [wfix, max(tot - wfix, 320)]
            self._sp_top.setSizes(sizes)
            self._sp_bot.setSizes(sizes)
            self._sp_inited = True

        self._resync_heights()
        QTimer.singleShot(0, self._resync_heights)   # tras el layout

        # Día activo: conservar el previo si sigue, si no el último.
        if not partes:
            self._dia_col = None
            self._dia_parte = None
            self._mes_header.set_active_col(None)
            self._panel_vacio()
            self._cargar_metrados()   # limpia las planillas (dia_parte=None → hint)
            self._cargar_recursos_dia()
            return
        target = prev if any(pr['id'] == prev for pr in partes) else partes[-1]['id']
        col = next(c for c, pid_ in self._col2parte.items() if pid_ == target)
        self._dia_col = None
        self._activar_dia(col, force=True)

    def _on_split_moved(self, from_top):
        """Sincroniza la posición del split de arriba con el de abajo (y viceversa)
        para que el borde de las columnas fijas coincida con el del panel del día."""
        if self._sync_guard:
            return
        self._sync_guard = True
        src, dst = ((self._sp_top, self._sp_bot) if from_top
                    else (self._sp_bot, self._sp_top))
        dst.setSizes(src.sizes())
        self._sync_guard = False
        self._h_timer.start()   # el ancho de la Descripción cambió → re-altura

    def _resync_heights(self):
        """Recalcula el alto de filas de la tabla fija (Descripción envuelta) y lo
        copia a la tabla de días, para que queden alineadas."""
        if self.tbl_fix.rowCount() == 0:
            return
        self.tbl_fix.resizeRowsToContents()
        for r in range(self.tbl_dias.rowCount()):
            self.tbl_dias.setRowHeight(r, self.tbl_fix.rowHeight(r))

    def _celda(self, tbl, r, col, text, *, left=False, es_tit=False, niv=1,
               depth=0, num=False, editable=False, daybg=None, acum=False,
               rotip=None, over=False):
        txt = str(text)
        es_desc = (tbl is self.tbl_fix and col == CUA_DESC)
        if es_desc and depth > 0:
            txt = ("    " * depth) + txt
        it = QTableWidgetItem(txt)
        if es_desc:
            it.setToolTip(str(text))
        if rotip:
            it.setToolTip(rotip)
        if num and not left:
            it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        elif not left:
            it.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
        flags = Qt.ItemIsSelectable | Qt.ItemIsEnabled
        if editable:
            flags |= Qt.ItemIsEditable
        it.setFlags(flags)
        if es_tit:
            color, tbg = NIVEL_ESTILO.get(min(max(niv, 1), 4),
                                          (SLATE_700, SILVER_200))
            fnt = it.font(); fnt.setBold(True)
            if niv == 1 and left:
                fnt.setUnderline(True)
            it.setFont(fnt)
            it.setForeground(QColor(color if left else "#1A2535"))
            it.setBackground(QColor(tbg))
        elif daybg:
            it.setBackground(QColor(daybg))
        elif acum:
            fnt = it.font(); fnt.setBold(True); it.setFont(fnt)
            # Rojo si el ejecutado acumulado supera el contractual.
            if over:
                it.setForeground(QColor(RED_700))
                it.setBackground(QColor(RED_BG))
            else:
                it.setForeground(QColor("#1A2535"))
        tbl.setItem(r, col, it)

    # ── Día activo + incidencias ──────────────────────────────────────────────

    def _activar_dia(self, col, force=False):
        if col not in self._col2parte:
            return   # columna fija o de acumulado: no es un día
        if not force and col == self._dia_col:
            return
        self._guardar_obs()
        self._tint_col(self._dia_col, active=False)
        self._dia_col = col
        self._dia_parte = self._col2parte[col]
        self._tint_col(col, active=True)
        self._mes_header.set_active_col(col)   # resalta el día activo arriba
        self._cargar_panel_dia()
        self._cargar_metrados()   # recarga la planilla del día para la partida sel.
        self._cargar_recursos_dia()   # MO e insumos del día

    def seleccionar_dia(self, fecha, recurso_id=None):
        """Activa el día con esa fecha ISO (usado al saltar desde el Almacén).
        Recarga si hace falta, desplaza a esa columna y —si se da `recurso_id`—
        abre la pestaña «Insumos» y deja el cursor en la celda «Cantidad» de ese
        insumo, listo para editar."""
        if not getattr(self, '_col_fecha', None):
            self.cargar()
        col = next((c for c, f in (self._col_fecha or {}).items()
                    if f == str(fecha)), None)
        if col is None:
            return
        self._activar_dia(col, force=True)
        try:
            idx = self.tbl_dias.model().index(0, col)
            self.tbl_dias.scrollTo(idx, QAbstractItemView.PositionAtCenter)
        except Exception:   # noqa: BLE001
            pass
        if recurso_id is not None:
            # Diferir un ciclo: asegura que la pestaña ya esté visible/dibujada
            # para que el editor de la celda «Cantidad» abra correctamente.
            QTimer.singleShot(0, lambda: self._enfocar_insumo_dia(recurso_id))

    def _enfocar_insumo_dia(self, recurso_id):
        """Abre la pestaña «Insumos» del día y pone el foco/editor en la celda
        «Cantidad» del insumo con ese recurso_id (materiales)."""
        # Ir a la pestaña «Insumos» del panel del día.
        for i in range(self.tabs_dia.count()):
            if self.tabs_dia.tabText(i) == "Insumos":
                self.tabs_dia.setCurrentIndex(i)
                break
        tbl = (self._res_tbl or {}).get('mat')
        if tbl is None:
            return
        for r in range(tbl.rowCount()):
            it0 = tbl.item(r, RES_DESC)
            if it0 and it0.data(Qt.UserRole) == recurso_id:
                it_cant = tbl.item(r, RES_CANT)
                if it_cant is None:
                    return
                tbl.setCurrentItem(it_cant)
                # Asegurar que la fila quede visible en el scroll externo.
                sc = getattr(self, '_ins_scroll', None)
                if sc is not None:
                    try:
                        rect = tbl.visualItemRect(it_cant)
                        pt = tbl.mapTo(sc.widget(), rect.topLeft())
                        sc.ensureVisible(pt.x(), pt.y(), 0, rect.height() + 24)
                    except Exception:   # noqa: BLE001
                        pass
                # Abrir el editor si el día está abierto (celda editable).
                if it_cant.flags() & Qt.ItemIsEditable:
                    tbl.editItem(it_cant)
                return

    def _on_cell_clicked(self, r, c):
        # Clic en una celda de día (tabla derecha): activa el día + selecciona
        # la partida de la fila (resalta también en la tabla izquierda).
        self._activar_dia(c)
        self._seleccionar_partida(r)

    def _on_fix_clicked(self, r, c):
        # Clic en la tabla izquierda: selecciona la partida (sin cambiar de día).
        self._seleccionar_partida(r)

    def _seleccionar_partida(self, r):
        if r >= len(self._es_titulo_row) or self._es_titulo_row[r]:
            return
        # Resaltar la fila en ambas tablas.
        self.tbl_fix.selectRow(r)
        self.tbl_dias.selectRow(r)
        pid_part = self._row_partida[r] if r < len(self._row_partida) else None
        if pid_part is not None and pid_part != self._partida_sel:
            self._partida_sel = pid_part
            self._cargar_metrados()

    def _tint_col(self, col, active):
        if col is None or col not in self._col2parte:
            return
        cerr = (self._estado_col.get(col) == 'cerrado')
        self.tbl_dias.blockSignals(True)
        for r in range(self.tbl_dias.rowCount()):
            if r < len(self._es_titulo_row) and self._es_titulo_row[r]:
                continue
            it = self.tbl_dias.item(r, col)
            if it is None:
                continue
            # Activo = banana; al revertir, día cerrado gris o sin fondo (zebra).
            if active:
                it.setBackground(QColor(ACTIVE_DAY_BG))
            elif cerr:
                it.setBackground(QColor(DAY_CLOSED_BG))
            else:
                it.setData(Qt.BackgroundRole, None)   # vuelve a la zebra del view
        self.tbl_dias.blockSignals(False)

    def _cargar_panel_dia(self):
        parte = PD.get_parte(self._dia_parte)
        if not parte:
            self._panel_vacio()
            return
        # Editable solo si el día está abierto Y la obra está «En ejecución».
        abierto = (parte['estado'] == 'abierto') and _co_editable(self._proy)
        self._dia_abierto = abierto   # estado del DÍA (no depende de la partida sel.)
        self.lbl_dia.setText(f"Día {_fmt_fecha(parte['fecha'])}")
        self.btn_cerrar.setText("Reabrir" if not abierto else "Cerrar")
        self.btn_cerrar.setEnabled(_co_editable(self._proy))
        self.btn_elim.setEnabled(abierto)
        self.btn_cuaderno.setEnabled(True)
        if abierto:
            self.lbl_estado.setText("● ABIERTO")
            self.lbl_estado.setStyleSheet("background:transparent; border:none;"
                f" font-size:11px; font-weight:700; color:{GREEN_700};")
        else:
            self.lbl_estado.setText("🔒 CERRADO")
            self.lbl_estado.setStyleSheet("background:transparent; border:none;"
                f" font-size:11px; font-weight:700; color:{RED_700};")
        self.txt_obs.blockSignals(True)
        self.txt_obs.setPlainText(parte.get('observaciones') or "")
        self.txt_obs.blockSignals(False)
        self.txt_obs.setReadOnly(not abierto)
        self._obs_pendiente = False

    def _panel_vacio(self):
        self._dia_abierto = False
        self.lbl_dia.setText("—")
        self.lbl_estado.setText("")
        self.btn_cerrar.setEnabled(False)
        self.btn_elim.setEnabled(False)
        self.btn_cuaderno.setEnabled(False)
        self.txt_obs.blockSignals(True)
        self.txt_obs.setPlainText("")
        self.txt_obs.blockSignals(False)
        self.txt_obs.setReadOnly(True)
        self._obs_pendiente = False

    # ── Planillas de metrados (referencia + del día) ──────────────────────────

    def _mk_met_table(self, editable):
        t = _MetTable(0, len(_MET_COLS))
        t.setHorizontalHeaderLabels(_MET_COLS)
        t.verticalHeader().setVisible(False)
        t.setMinimumHeight(96)
        t.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for c in range(1, len(_MET_COLS)):
            t.setColumnWidth(c, 52)
        t.verticalHeader().setDefaultSectionSize(22)
        if editable:
            t.setEditTriggers(QAbstractItemView.DoubleClicked
                              | QAbstractItemView.SelectedClicked
                              | QAbstractItemView.AnyKeyPressed)
            deleg = _MetCellDelegate(t)
            for c in range(7):   # Descripción + 6 dimensiones (parcial no se edita)
                t.setItemDelegateForColumn(c, deleg)
        else:
            t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        # Selección de filas + Ctrl+C/V/X + Supr + menú contextual (estilo Excel).
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.setSelectionMode(QAbstractItemView.ExtendedSelection)
        t.setContextMenuPolicy(Qt.CustomContextMenu)
        # Teclas manejadas en _MetTable.keyPressEvent (ver callbacks).
        t.on_copy = lambda: self._copiar_tabla(t)
        if editable:
            t.on_paste = self._pegar_en_dia
            t.on_cut = lambda: (self._copiar_tabla(t), self._eliminar_filas_dia())
            t.on_delete = self._eliminar_filas_dia
        t.setStyleSheet(
            f"QTableWidget {{ background:white; gridline-color:{SILVER_200};"
            f" font-size:10px; }}"
            f"QHeaderView::section {{ background:{SLATE_500}; color:white;"
            f" border:none; padding:2px; font-size:9px; font-weight:700; }}"
            f"QTableWidget::item:selected {{ background:{SELECT_BG};"
            f" color:{SLATE_700}; }}")
        return t

    def _cargar_metrados(self):
        """Carga, para la partida seleccionada, la planilla del proyecto
        (referencia) y la del día activo (editable)."""
        dm = get_decimales_metrado()
        pid_part = self._partida_sel
        if pid_part is None or self._dia_parte is None:
            self.lbl_part.setText("Selecciona una partida para ver y registrar "
                                  "sus metrados del día.")
            self._met_loading = True
            self.tbl_ref.setRowCount(0)
            self.tbl_dia.setRowCount(0)
            self._met_loading = False
            self.lbl_ref_total.setText("")
            self.lbl_dia_total.setText("")
            self.tbl_dia.setEnabled(False)
            return   # NO tocar _dia_abierto: es estado del DÍA, no de la partida
        p = self._part_by_id.get(pid_part, {})
        self.lbl_part.setText(
            f"Metrados — {p.get('item','')}  {p.get('descripcion','')}".strip())
        ref, reftot = PD.get_metrado_detalle_proyecto(pid_part)
        self._llenar_met(self.tbl_ref, ref, dm, editable=False)
        self.lbl_ref_total.setText(f"Total proyecto: {_m(reftot, dm)}")
        parte = PD.get_parte(self._dia_parte)
        abierto = bool(parte and parte['estado'] == 'abierto')
        dia, diatot = PD.get_metrado_detalle_dia(self._dia_parte, pid_part)
        self._llenar_met(self.tbl_dia, dia, dm, editable=abierto, add_empty=abierto)
        self.lbl_dia_total.setText(f"Total del día: {_m(diatot, dm)}")
        self.tbl_dia.setEnabled(True)

    # ── Copiar / pegar / eliminar (Ctrl+C / Ctrl+V / Supr / clic derecho) ─────

    def _menu_metrados(self, tbl, pos, editable):
        m = QMenu(self)
        act_cop = m.addAction("Copiar")
        act_peg = act_eli = None
        if editable and self._dia_abierto:
            act_peg = m.addAction("Pegar")
            m.addSeparator()
            act_eli = m.addAction("Eliminar fila(s)")
        chosen = m.exec(tbl.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        if chosen == act_cop:
            self._copiar_tabla(tbl)
        elif chosen == act_peg:
            self._pegar_en_dia()
        elif chosen == act_eli:
            self._eliminar_filas_dia()

    def _copiar_tabla(self, tbl):
        """Copia las filas seleccionadas al portapapeles como texto tabulado."""
        rows = sorted({i.row() for i in tbl.selectedItems()})
        if not rows and tbl.currentRow() >= 0:
            rows = [tbl.currentRow()]
        lineas = []
        for r in rows:
            cells = [(tbl.item(r, c).text() if tbl.item(r, c) else "")
                     for c in range(tbl.columnCount())]
            if any(c.strip() for c in cells):
                lineas.append("\t".join(cells))
        if lineas:
            QApplication.clipboard().setText("\n".join(lineas))

    def _pegar_en_dia(self):
        """Pega filas tabuladas del portapapeles en la planilla del día,
        empezando en la fila actual (se toman las cols Descripción..Alto)."""
        if not self._dia_abierto or self._partida_sel is None:
            return
        texto = QApplication.clipboard().text()
        lineas = [ln for ln in texto.replace("\r", "").split("\n")]
        while lineas and not lineas[-1].strip():
            lineas.pop()
        if not lineas:
            return
        dm = get_decimales_metrado()
        start = self.tbl_dia.currentRow()
        if start < 0:
            start = self.tbl_dia.rowCount() - 1   # la fila vacía del final
            if start < 0:
                start = 0
        self._met_loading = True
        self.tbl_dia.blockSignals(True)
        for i, ln in enumerate(lineas):
            campos = ln.split("\t")
            r = start + i
            while self.tbl_dia.rowCount() <= r:
                self._met_fila(self.tbl_dia, {}, dm, True)
            for c in range(7):   # Descripción + 6 dimensiones (parcial se deriva)
                val = campos[c].strip() if c < len(campos) else ""
                it = self.tbl_dia.item(r, c)
                if it is not None:
                    it.setText(val)
        self.tbl_dia.blockSignals(False)
        self._met_loading = False
        self._recompute_parciales()
        self._guardar_dia()

    def _eliminar_filas_dia(self):
        if not self._dia_abierto or self._partida_sel is None:
            return
        rows = sorted({i.row() for i in self.tbl_dia.selectedItems()}, reverse=True)
        if not rows and self.tbl_dia.currentRow() >= 0:
            rows = [self.tbl_dia.currentRow()]
        if not rows:
            return
        self._met_loading = True
        self.tbl_dia.blockSignals(True)
        for r in rows:
            self.tbl_dia.removeRow(r)
        self.tbl_dia.blockSignals(False)
        self._met_loading = False
        self._recompute_parciales()
        self._guardar_dia()

    def _recompute_parciales(self):
        """Recalcula la columna Parcial de todas las filas + garantiza una fila
        vacía al final (para seguir agregando)."""
        dm = get_decimales_metrado()
        self._met_loading = True
        self.tbl_dia.blockSignals(True)
        for r in range(self.tbl_dia.rowCount()):
            fila = self._leer_fila_met(self.tbl_dia, r)
            parc = PD._parcial_dims(fila)
            pit = self.tbl_dia.item(r, 7)
            if pit is not None:
                pit.setText(_m(parc, dm) if parc else "")
        # Fila vacía final si la última tiene datos.
        last = self.tbl_dia.rowCount() - 1
        if last < 0 or self._fila_met_no_vacia(self.tbl_dia, last):
            self._met_fila(self.tbl_dia, {}, dm, True)
        self.tbl_dia.blockSignals(False)
        self._met_loading = False

    def _guardar_dia(self):
        """Guarda la planilla del día → fija metrado_dia + push a la valorización."""
        if self._partida_sel is None or self._dia_parte is None:
            return
        dm = get_decimales_metrado()
        filas = [self._leer_fila_met(self.tbl_dia, r)
                 for r in range(self.tbl_dia.rowCount())]
        total = PD.save_metrado_detalle_dia(self._dia_parte, self._partida_sel, filas)
        if total is None:
            return
        self.lbl_dia_total.setText(f"Total del día: {_m(total, dm)}")
        self._reflejar_metrado_en_grilla(self._partida_sel, self._dia_parte, total)

    # ── Mano de obra / insumos del día (Fase B) ───────────────────────────────

    def _btn_estimar(self, sbtn, permitir_req=False):
        if not permitir_req:
            btn = sbtn("⤓ Estimar del metrado", self._estimar_recursos)
            btn.setToolTip("Calcula mano de obra, materiales, equipos y servicios "
                           "del día desde el ACU y el metrado registrado.")
            self._res_btn_estimar.append(btn)
            return btn
        btn = sbtn("⤓ Estimar", lambda: None)
        btn.setToolTip("Estima los insumos del día desde el ACU × metrado, o "
                       "tráelos de los requerimientos. Luego los ajustas.")
        menu = QMenu(btn)
        menu.aboutToShow.connect(lambda m=menu: self._build_estimar_menu(m))
        btn.setMenu(menu)
        self._res_btn_estimar.append(btn)
        return btn

    def _chk_estimar(self):
        chk = QCheckBox("Enteros")
        chk.setToolTip("Redondea materiales, equipos y servicios a unidades enteras "
            "de pedido (bolsas, varillas, galones, und…), como en los "
            "requerimientos. Las unidades continuas (kg, m³, ml) conservan "
            "decimales. Aplica al volver a estimar.")
        chk.setCursor(Qt.PointingHandCursor)
        chk.setChecked(self._estimar_enteros)
        chk.setStyleSheet(f"QCheckBox {{ color:{SLATE_700}; font-size:11px; }}")
        chk.toggled.connect(self._on_enteros_toggled)
        self._chk_enteros.append(chk)
        return chk

    def _on_enteros_toggled(self, on: bool):
        self._estimar_enteros = on
        for c in self._chk_enteros:
            if c.isChecked() != on:
                c.blockSignals(True); c.setChecked(on); c.blockSignals(False)

    def _build_estimar_menu(self, menu):
        """Menú del botón Estimar (Insumos): de los requerimientos (recomendado) o
        del metrado (guía teórica)."""
        menu.clear()
        a_req = menu.addAction("De los requerimientos…  (recomendado)")
        a_req.triggered.connect(self._estimar_desde_requerimientos)
        a_metr = menu.addAction("Del metrado (guía teórica ACU × metrado)")
        a_metr.triggered.connect(self._estimar_recursos)

    def _mk_tab_recursos(self, clase, sbtn):
        """Pestaña con una sola tabla de recursos del día (mano de obra)."""
        w = QWidget(); w.setStyleSheet("background:white;")
        lay = QVBoxLayout(w); lay.setContentsMargins(4, 4, 4, 4); lay.setSpacing(3)
        bar = QHBoxLayout(); bar.setSpacing(6)
        # La mano de obra NO se toma de requerimientos (no llevan MO): botón simple.
        bar.addWidget(self._btn_estimar(sbtn, permitir_req=False)); bar.addStretch()
        lay.addLayout(bar)
        t = self._mk_recurso_table(clase)
        self._res_tbl[clase] = t
        lay.addWidget(t, stretch=1)
        return w

    def _mk_tab_insumos(self, sbtn):
        """Pestaña «Insumos»: encabezado «Recurso·Und·Cantidad» FIJO arriba +
        Materiales·Equipos·Servicios bajo UN solo scroll (cada sub-tabla a su alto,
        sin encabezado ni scroll propio)."""
        w = QWidget(); w.setStyleSheet("background:white;")
        lay = QVBoxLayout(w); lay.setContentsMargins(4, 4, 4, 4); lay.setSpacing(3)
        bar = QHBoxLayout(); bar.setSpacing(6)
        bar.addWidget(self._btn_estimar(sbtn, permitir_req=True))
        bar.addWidget(self._chk_estimar()); bar.addStretch()
        lay.addLayout(bar)

        # Encabezado de columnas FIJO (una tabla de solo cabecera, 0 filas).
        hdrbar = QTableWidget(0, len(_RES_COLS))
        hdrbar.setHorizontalHeaderLabels(_RES_COLS)
        hdrbar.verticalHeader().setVisible(False)
        hdrbar.setFrameShape(QFrame.NoFrame)
        hdrbar.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        hdrbar.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        hdrbar.horizontalHeader().setSectionResizeMode(RES_DESC, QHeaderView.Stretch)
        hdrbar.setColumnWidth(RES_UND, 46); hdrbar.setColumnWidth(RES_CANT, 72)
        hdrbar.setStyleSheet(
            f"QTableWidget {{ background:white; border:none; }}"
            f"QHeaderView::section {{ background:{SLATE_500}; color:white;"
            f" border:none; padding:2px; font-size:9px; font-weight:700; }}")
        hdrbar.setFixedHeight(hdrbar.horizontalHeader().sizeHint().height() + 2)
        self._ins_hdrbar = hdrbar

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        scroll.setStyleSheet("QScrollArea { background:white; border:none; }")
        self._ins_scroll = scroll   # para desplazar a un insumo al saltar del Almacén
        # Reservar el ancho de la barra de scroll en el encabezado fijo, para que
        # sus columnas coincidan con las de las tablas (que pierden ese ancho).
        sbw = max(scroll.verticalScrollBar().sizeHint().width(), 12)
        top = QHBoxLayout(); top.setContentsMargins(0, 0, 0, 0); top.setSpacing(0)
        top.addWidget(hdrbar); top.addSpacing(sbw)
        lay.addLayout(top)

        inner = QWidget(); inner.setStyleSheet("background:white;")
        il = QVBoxLayout(inner)
        il.setContentsMargins(0, 0, 0, 0); il.setSpacing(2)
        for clase, titulo in (('mat', 'Materiales'), ('eq', 'Equipos'),
                              ('sc', 'Servicios')):
            lbl = QLabel(titulo)
            lbl.setStyleSheet(f"color:{SLATE_700}; font-size:11px; font-weight:700;"
                " background:transparent; border:none;")
            il.addWidget(lbl)
            t = self._mk_recurso_table(clase)
            t.setMinimumHeight(0)
            t.horizontalHeader().setVisible(False)   # el encabezado va fijo arriba
            t.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            t.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self._res_tbl[clase] = t
            il.addWidget(t)
        il.addStretch()
        scroll.setWidget(inner)
        lay.addWidget(scroll, stretch=1)
        return w

    def _mk_recurso_table(self, clase):
        t = _MetTable(0, len(_RES_COLS))
        t.setHorizontalHeaderLabels(_RES_COLS)
        t.verticalHeader().setVisible(False)
        t.setMinimumHeight(84)
        t.horizontalHeader().setSectionResizeMode(RES_DESC, QHeaderView.Stretch)
        t.setColumnWidth(RES_UND, 46)
        t.setColumnWidth(RES_CANT, 72)
        t.verticalHeader().setDefaultSectionSize(22)
        t.setEditTriggers(QAbstractItemView.DoubleClicked
                          | QAbstractItemView.SelectedClicked
                          | QAbstractItemView.AnyKeyPressed)
        deleg = _MetCellDelegate(t)
        for c in range(len(_RES_COLS)):
            t.setItemDelegateForColumn(c, deleg)
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.setSelectionMode(QAbstractItemView.ExtendedSelection)
        t.setContextMenuPolicy(Qt.CustomContextMenu)
        t.on_copy = lambda: self._copiar_tabla(t)
        t.on_delete = lambda c=clase: self._eliminar_recurso_filas(c)
        t.itemChanged.connect(lambda it, c=clase: self._on_recurso_changed(c, it))
        t.customContextMenuRequested.connect(
            lambda pos, tt=t, c=clase: self._menu_recursos(tt, c, pos))
        t.setStyleSheet(
            f"QTableWidget {{ background:white; gridline-color:{SILVER_200};"
            f" font-size:10px; }}"
            f"QHeaderView::section {{ background:{SLATE_500}; color:white;"
            f" border:none; padding:2px; font-size:9px; font-weight:700; }}"
            f"QTableWidget::item:selected {{ background:{SELECT_BG};"
            f" color:{SLATE_700}; }}")
        return t

    def _cargar_recursos_dia(self):
        abierto = bool(self._dia_parte) and self._dia_abierto
        for clase in ('mo', 'mat', 'eq', 'sc'):
            filas = (PD.get_recursos_dia(self._dia_parte, clase)
                     if self._dia_parte else [])
            self._llenar_recursos(self._res_tbl[clase], filas, abierto)
            self._ajustar_alto(clase)
        for b in self._res_btn_estimar:
            b.setEnabled(abierto)

    def _llenar_recursos(self, tbl, filas, abierto):
        self._met_loading = True
        tbl.blockSignals(True)
        tbl.setRowCount(0)
        for f in filas:
            self._recurso_fila(tbl, f, abierto)
        if abierto:
            self._recurso_fila(tbl, {}, abierto)
        tbl.blockSignals(False)
        self._met_loading = False

    def _recurso_fila(self, tbl, f, abierto):
        r = tbl.rowCount(); tbl.insertRow(r)
        it0 = QTableWidgetItem(f.get('descripcion') or '')
        if f.get('recurso_id') is not None:
            it0.setData(Qt.UserRole, f['recurso_id'])
        it1 = QTableWidgetItem(f.get('unidad') or '')
        it1.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
        cant = f.get('cantidad')
        it2 = QTableWidgetItem(_numtxt(cant) if cant else '')
        it2.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        for c, it in ((RES_DESC, it0), (RES_UND, it1), (RES_CANT, it2)):
            flags = Qt.ItemIsSelectable | Qt.ItemIsEnabled
            if abierto:
                flags |= Qt.ItemIsEditable
            it.setFlags(flags)
            tbl.setItem(r, c, it)

    def _leer_fila_recurso(self, tbl, r):
        def txt(c):
            it = tbl.item(r, c)
            return it.text().strip() if it else ''
        it0 = tbl.item(r, RES_DESC)
        rid = it0.data(Qt.UserRole) if it0 else None
        ct = txt(RES_CANT)
        cant = None
        if ct:
            try:
                cant = parse_num(ct)
            except (TypeError, ValueError):
                cant = None
        return {'recurso_id': rid, 'descripcion': txt(RES_DESC),
                'unidad': txt(RES_UND), 'cantidad': cant}

    def _recurso_fila_no_vacia(self, tbl, r):
        f = self._leer_fila_recurso(tbl, r)
        return bool((f['descripcion'] or '').strip() or f['cantidad'])

    def _on_recurso_changed(self, clase, item):
        if self._met_loading:
            return
        tbl = self._res_tbl[clase]
        last = tbl.rowCount() - 1
        if item.row() == last and self._recurso_fila_no_vacia(tbl, last):
            self._met_loading = True
            tbl.blockSignals(True)
            self._recurso_fila(tbl, {}, True)
            tbl.blockSignals(False)
            self._met_loading = False
            self._ajustar_alto(clase)
        self._guardar_recursos(clase)

    def _guardar_recursos(self, clase):
        if self._dia_parte is None:
            return
        tbl = self._res_tbl[clase]
        filas = [self._leer_fila_recurso(tbl, r) for r in range(tbl.rowCount())]
        PD.save_recursos_dia(self._dia_parte, clase, filas)

    def _agregar_fila_recurso(self, clase):
        """Agrega una fila extra al final (insumo no contemplado en el ACU) y la
        deja enfocada para escribir."""
        if not self._dia_abierto or self._dia_parte is None:
            return
        tbl = self._res_tbl[clase]
        last = tbl.rowCount() - 1
        if last < 0 or self._recurso_fila_no_vacia(tbl, last):
            self._met_loading = True
            tbl.blockSignals(True)
            self._recurso_fila(tbl, {}, True)
            tbl.blockSignals(False)
            self._met_loading = False
            last = tbl.rowCount() - 1
        self._ajustar_alto(clase)
        it = tbl.item(last, RES_DESC)
        if it is not None:
            tbl.scrollToItem(it)
            tbl.setCurrentItem(it)
            tbl.editItem(it)

    def _eliminar_recurso_filas(self, clase):
        if not self._dia_abierto or self._dia_parte is None:
            return
        tbl = self._res_tbl[clase]
        rows = sorted({i.row() for i in tbl.selectedItems()}, reverse=True)
        if not rows and tbl.currentRow() >= 0:
            rows = [tbl.currentRow()]
        if not rows:
            return
        self._met_loading = True
        tbl.blockSignals(True)
        for r in rows:
            tbl.removeRow(r)
        if tbl.rowCount() == 0 or self._recurso_fila_no_vacia(tbl, tbl.rowCount() - 1):
            self._recurso_fila(tbl, {}, True)
        tbl.blockSignals(False)
        self._met_loading = False
        self._guardar_recursos(clase)
        self._ajustar_alto(clase)

    def _ajustar_alto(self, clase):
        """Las sub-tablas de Insumos van a su alto (sin scroll propio) para que
        todo Insumos use un solo scroll."""
        if clase not in ('mat', 'eq', 'sc'):
            return
        t = self._res_tbl[clase]
        h = 0 if t.horizontalHeader().isHidden() else t.horizontalHeader().height()
        for r in range(t.rowCount()):
            h += t.rowHeight(r)
        h += 2 * t.frameWidth() + 2
        t.setFixedHeight(max(h, 28))

    def _menu_recursos(self, tbl, clase, pos):
        m = QMenu(self)
        ac = m.addAction("Copiar")
        aa = ae = None
        if self._dia_abierto:
            aa = m.addAction("Agregar fila")
            m.addSeparator()
            ae = m.addAction("Eliminar fila(s)")
        ch = m.exec(tbl.viewport().mapToGlobal(pos))
        if ch is None:
            return
        if ch == ac:
            self._copiar_tabla(tbl)
        elif ch == aa:
            self._agregar_fila_recurso(clase)
        elif ch == ae:
            self._eliminar_recurso_filas(clase)

    def _estimar_recursos(self):
        if self._dia_parte is None or not self._dia_abierto:
            return
        if not self._confirmar_estimar():
            return
        res = PD.estimar_consumo_dia(self._dia_parte, self._estimar_enteros)
        if not any(res.get(c) for c in ('mo', 'mat', 'eq', 'sc')):
            QMessageBox.information(self, "Estimar",
                "No hay metrado del día (o las partidas no tienen ACU) para "
                "estimar. Registra primero el metrado del día.")
            return
        self._aplicar_estimacion(res)

    def _estimar_desde_requerimientos(self):
        if self._dia_parte is None or not self._dia_abierto:
            return
        from core import requerimientos as RQ
        reqs = RQ.listar_requerimientos(self.pid)
        if not reqs:
            QMessageBox.information(self, "Requerimientos",
                "No hay requerimientos creados en este proyecto.")
            return
        sel = self._pedir_requerimientos(reqs)
        if sel is None:        # cancelado
            return
        if not sel:
            QMessageBox.information(self, "Requerimientos",
                "No marcaste ningún requerimiento.")
            return
        if not self._confirmar_estimar():
            return
        res = PD.estimar_consumo_requerimientos(
            self._dia_parte, sel, self._estimar_enteros)
        if not any(res.get(c) for c in ('mo', 'mat', 'eq', 'sc')):
            QMessageBox.information(self, "Estimar",
                "Los requerimientos seleccionados no tienen insumos y no hay "
                "metrado del día para la mano de obra.")
            return
        self._aplicar_estimacion(res)

    def _pedir_requerimientos(self, reqs):
        """Diálogo de selección múltiple de requerimientos (todos marcados por
        defecto). Devuelve la lista de ids marcados, o None si se cancela."""
        from core import requerimientos as RQ
        dlg = QDialog(self)
        dlg.setWindowTitle("Estimar de los requerimientos")
        v = QVBoxLayout(dlg)
        lbl = QLabel("Marca los requerimientos que limitan QUÉ insumos registrar "
                     "hoy.\nLa cantidad sale del metrado del día (no del total "
                     "pedido). Usa «Enteros» para redondear.")
        lbl.setStyleSheet("background:transparent; border:none;")
        v.addWidget(lbl)
        checks = []
        for r in reqs:
            cat = (r.get('categoria') or '').strip() or \
                RQ.tipo_de_requerimiento(r).upper()
            n = sum(len(RQ.get_detalle(r['id'], t)) for t in ('mat', 'eq', 'sc'))
            cb = QCheckBox(f"N°{r['numero']} — {cat}   ({n} insumo"
                           f"{'s' if n != 1 else ''})")
            cb.setChecked(True)
            cb._rid = r['id']
            checks.append(cb)
            v.addWidget(cb)
        bar = QHBoxLayout(); bar.addStretch()
        b_ok = QPushButton("Aplicar"); b_ca = QPushButton("Cancelar")
        b_ok.setCursor(Qt.PointingHandCursor); b_ca.setCursor(Qt.PointingHandCursor)
        b_ok.setStyleSheet(
            f"QPushButton {{ background:{ORANGE}; color:white; border:none;"
            f" border-radius:6px; font-weight:600; padding:5px 14px; }}"
            f"QPushButton:hover {{ background:#C0621A; }}")
        bar.addWidget(b_ca); bar.addWidget(b_ok)
        v.addLayout(bar)
        b_ok.clicked.connect(dlg.accept); b_ca.clicked.connect(dlg.reject)
        if dlg.exec() != QDialog.Accepted:
            return None
        return [c._rid for c in checks if c.isChecked()]

    def _confirmar_estimar(self) -> bool:
        hay = any(PD.get_recursos_dia(self._dia_parte, c)
                  for c in ('mo', 'mat', 'eq', 'sc'))
        return not hay or QMessageBox.question(
            self, "Estimar mano de obra e insumos",
            "Esto recalcula la mano de obra, materiales, equipos y servicios del "
            "día. Se CONSERVAN los que agregaste a mano (acelerante, aditivos, "
            "herramientas, personal extra, etc.). ¿Continuar?"
        ) == QMessageBox.Yes

    def _aplicar_estimacion(self, res: dict):
        for c in ('mo', 'mat', 'eq', 'sc'):
            # Conservar las filas MANUALES (sin recurso_id del ACU) que el
            # residente agregó; refrescar solo lo derivado del ACU/requerimiento.
            manuales = [f for f in PD.get_recursos_dia(self._dia_parte, c)
                        if not f.get('recurso_id')]
            PD.save_recursos_dia(self._dia_parte, c, res.get(c, []) + manuales)
        self._cargar_recursos_dia()

    def _llenar_met(self, tbl, filas, dm, editable, add_empty=False):
        self._met_loading = True
        tbl.blockSignals(True)
        tbl.setRowCount(0)
        for f in filas:
            self._met_fila(tbl, f, dm, editable)
        if add_empty:
            self._met_fila(tbl, {}, dm, editable)
        tbl.blockSignals(False)
        self._met_loading = False

    def _met_fila(self, tbl, f, dm, editable):
        r = tbl.rowCount()
        tbl.insertRow(r)
        parc = f.get('parcial')
        vals = [f.get('descripcion') or '',
                _numtxt(f.get('n_estructuras')), _numtxt(f.get('n_elementos')),
                _numtxt(f.get('area')), _numtxt(f.get('largo')),
                _numtxt(f.get('ancho')), _numtxt(f.get('alto')),
                (_m(parc, dm) if parc else '')]
        for c, txt in enumerate(vals):
            it = QTableWidgetItem(txt)
            if c >= 1:
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            flags = Qt.ItemIsSelectable | Qt.ItemIsEnabled
            if editable and c <= 6:
                flags |= Qt.ItemIsEditable
            it.setFlags(flags)
            if c == 7:
                fnt = it.font(); fnt.setBold(True); it.setFont(fnt)
                it.setForeground(QColor("#1A2535"))
                it.setBackground(QColor(ACUM_BG))
            tbl.setItem(r, c, it)

    def _leer_fila_met(self, tbl, r):
        def num(c):
            it = tbl.item(r, c)
            t = (it.text().strip() if it else "")
            if not t:
                return None
            try:
                val = parse_num(t)
            except (TypeError, ValueError):
                return None
            return None if val == 0 else val   # 0 = dimensión vacía
        dit = tbl.item(r, 0)
        return {'descripcion': (dit.text() if dit else ''),
                'n_estructuras': num(1), 'n_elementos': num(2), 'area': num(3),
                'largo': num(4), 'ancho': num(5), 'alto': num(6)}

    def _fila_met_no_vacia(self, tbl, r):
        f = self._leer_fila_met(tbl, r)
        return bool((f['descripcion'] or '').strip()
                    or any(f[c] is not None for c in _MET_DIMS))

    def _on_met_dia_changed(self, item):
        if self._met_loading or self._partida_sel is None or self._dia_parte is None:
            return
        if item.column() > 6:
            return
        dm = get_decimales_metrado()
        r = item.row()
        # Recalcular el parcial de la fila editada.
        fila = self._leer_fila_met(self.tbl_dia, r)
        parc = PD._parcial_dims(fila)
        self._met_loading = True
        pit = self.tbl_dia.item(r, 7)
        if pit:
            pit.setText(_m(parc, dm) if parc else "")
        # Agregar fila vacía si se llenó la última.
        last = self.tbl_dia.rowCount() - 1
        if r == last and self._fila_met_no_vacia(self.tbl_dia, r):
            self._met_fila(self.tbl_dia, {}, dm, True)
        self._met_loading = False
        self._guardar_dia()

    def _reflejar_metrado_en_grilla(self, partida_id, parte_id, total):
        """Tras editar la planilla del día, refleja el metrado en la celda de la
        tabla de días (solo lectura si hay detalle) + recalcula el acumulado."""
        col = next((c for c, pid_ in self._col2parte.items() if pid_ == parte_id),
                   None)
        if col is None:
            return
        row = (self._row_partida.index(partida_id)
               if partida_id in self._row_partida else None)
        if row is None:
            return
        dm = get_decimales_metrado()
        self.tbl_dias.blockSignals(True)
        it = self.tbl_dias.item(row, col)
        if it is not None:
            it.setText(_m(total, dm) if total else "")
            flags = Qt.ItemIsSelectable | Qt.ItemIsEnabled
            if total > 0:
                it.setToolTip("Metrado calculado desde la planilla del día.")
                self._con_detalle.add((parte_id, partida_id))
            else:
                it.setToolTip("")
                self._con_detalle.discard((parte_id, partida_id))
                if self._estado_col.get(col) == 'abierto':
                    flags |= Qt.ItemIsEditable
            it.setFlags(flags)
        self.tbl_dias.blockSignals(False)
        self._recalcular_acum(row, dm)

    # ── Edición de metrado del día ────────────────────────────────────────────

    def _on_item_changed(self, item):
        if self._rendering:
            return
        col = item.column()
        if col not in self._col2parte:
            return
        r = item.row()
        pid_part = self._row_partida[r] if r < len(self._row_partida) else None
        if pid_part is None:
            return
        val = parse_num(item.text())
        if val < 0:
            val = 0
        if PD.set_metrado_dia(self._col2parte[col], pid_part, val):
            dm = get_decimales_metrado()
            self.tbl_dias.blockSignals(True)
            item.setText(_m(val, dm) if val else "")
            self.tbl_dias.blockSignals(False)
            self._recalcular_acum(r, dm)

    def _recalcular_acum(self, row, dm):
        total = 0.0
        for col in self._col2parte:
            it = self.tbl_dias.item(row, col)
            if it and it.text():
                total += parse_num(it.text())
        ita = self.tbl_fix.item(row, CUA_ACUM)
        if ita is None:
            return
        base = (self._partidas[row]['metrado'] if row < len(self._partidas) else 0) or 0
        self.tbl_fix.blockSignals(True)
        ita.setText(_m(total, dm) if total else "")
        # Rojo si el ejecutado acumulado supera el contractual.
        if _excede(total, base):
            ita.setForeground(QColor(RED_700))
            ita.setBackground(QColor(RED_BG))
        else:
            ita.setForeground(QColor("#1A2535"))
            ita.setData(Qt.BackgroundRole, None)
        self.tbl_fix.blockSignals(False)

    # ── Observaciones ──────────────────────────────────────────────────────────

    def _obs_dirty(self):
        self._obs_pendiente = True

    def _guardar_obs(self):
        if self._obs_pendiente and self._dia_parte:
            PD.set_observaciones(self._dia_parte, self.txt_obs.toPlainText())
            self._obs_pendiente = False

    # ── Acciones ───────────────────────────────────────────────────────────────

    def _nuevo(self):
        dlg = _FechaDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        from datetime import date, timedelta
        desde, hasta = dlg.valores()
        d0, d1 = date.fromisoformat(desde), date.fromisoformat(hasta)
        if d1 < d0:
            d0, d1 = d1, d0
        if (d1 - d0).days > 90:
            QMessageBox.warning(self, "Rango muy grande",
                "El rango no puede superar 90 días por vez.")
            return
        self._guardar_obs()
        # Un parte por cada día del rango (crear_parte es idempotente por fecha).
        primero = None
        d = d0
        while d <= d1:
            pid = PD.crear_parte(self.pid, d.isoformat())
            if primero is None:
                primero = pid
            d += timedelta(days=1)
        self._dia_parte = primero   # selecciona el primer día generado
        self._render()

    def _cerrar_reabrir(self):
        if not self._dia_parte:
            return
        self._guardar_obs()
        parte = PD.get_parte(self._dia_parte)
        if parte['estado'] == 'cerrado':
            PD.reabrir_parte(self._dia_parte)
        else:
            if QMessageBox.question(
                self, "Cerrar parte",
                "Al cerrar, el parte del día queda congelado (no se podrá "
                "editar su metrado ni observaciones). ¿Continuar?"
            ) != QMessageBox.Yes:
                return
            PD.cerrar_parte(self._dia_parte)
        self._render()

    def _eliminar(self):
        if not self._dia_parte:
            return
        parte = PD.get_parte(self._dia_parte)
        if QMessageBox.question(
            self, "Eliminar parte",
            f"¿Eliminar el parte del {_fmt_fecha(parte['fecha'])}? "
            "Se descontará su avance de la valorización del período."
        ) != QMessageBox.Yes:
            return
        if not PD.eliminar_parte(self._dia_parte):
            QMessageBox.warning(self, "Eliminar",
                "Solo se puede eliminar un parte abierto.")
            return
        self._dia_parte = None
        self._render()

    # ── Vista para el cuaderno de obra (asiento del día) ──────────────────────

    def _texto_asiento(self, parte_id):
        """Compila el asiento del día en formato cuaderno (texto plano)."""
        parte = PD.get_parte(parte_id)
        if not parte:
            return ""
        dm = get_decimales_metrado()
        L = [f"ASIENTO DEL {_fecha_larga(parte['fecha'])}", ""]
        # 1) Mano de obra
        mo = PD.get_recursos_dia(parte_id, 'mo')
        if mo:
            L.append("MANO DE OBRA:")
            L.append(" · ".join(
                f"{_cant_entera(x['cantidad'])} {x['descripcion']}".strip()
                for x in mo))
            L.append("")
        # 2) Actividades realizadas
        acts = PD.get_actividades_dia(parte_id)
        if acts:
            L.append("ACTIVIDADES REALIZADAS:")
            for a in acts:
                L.append(f"- {a['item']} {a['descripcion']} — "
                         f"{_m(a['metrado_dia'], dm)} {a['unidad'] or ''}".rstrip())
            L.append("")
        # 3) Materiales · Equipos · Servicios
        for clase, tit in (('mat', 'MATERIALES'), ('eq', 'EQUIPOS'),
                           ('sc', 'SERVICIOS')):
            rs = PD.get_recursos_dia(parte_id, clase)
            if rs:
                L.append(f"{tit}:")
                L.append(" · ".join(
                    " ".join(s for s in (x['descripcion'], _numtxt(x['cantidad']),
                                         x['unidad']) if s).strip()
                    for x in rs))
                L.append("")
        # 4) Observaciones
        obs = (parte.get('observaciones') or '').strip()
        if obs:
            L.append("OBSERVACIONES / INCIDENCIAS:")
            L.append(obs)
        return "\n".join(L).strip()

    def _vista_cuaderno(self):
        if not self._dia_parte:
            return
        self._guardar_obs()   # incluir lo último escrito en observaciones
        txt = self._texto_asiento(self._dia_parte)
        dlg = QDialog(self)
        dlg.setWindowTitle("Vista para el cuaderno de obra")
        dlg.setWindowModality(Qt.WindowModal)
        dlg.resize(560, 540)
        v = QVBoxLayout(dlg); v.setContentsMargins(14, 12, 14, 12); v.setSpacing(8)
        hint = QLabel("Asiento del día listo para transcribir al cuaderno (o "
                      "copiar). Edita en las pestañas y vuelve a abrir para refrescar.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{SLATE_500}; font-size:11px;")
        v.addWidget(hint)
        te = QPlainTextEdit(); te.setReadOnly(True); te.setPlainText(txt)
        te.setStyleSheet(
            f"QPlainTextEdit {{ border:1px solid {SILVER_300}; border-radius:6px;"
            f" padding:6px 8px; font-size:12px; background:white; color:{SLATE_700}; }}")
        v.addWidget(te, stretch=1)
        bar = QHBoxLayout()
        lbl_ok = QLabel(""); lbl_ok.setStyleSheet(f"color:{GREEN_700}; font-size:11px;")
        bar.addWidget(lbl_ok); bar.addStretch()
        def _copiar():
            QApplication.clipboard().setText(txt)
            lbl_ok.setText("✓ Copiado al portapapeles")
        bcop = QPushButton("📋 Copiar")
        bcop.setCursor(Qt.PointingHandCursor)
        bcop.setStyleSheet(
            f"QPushButton {{ background:{ORANGE}; color:white; border:none;"
            f" border-radius:6px; padding:6px 14px; font-weight:600; }}"
            f"QPushButton:hover {{ background:#C0621A; }}")
        bcop.clicked.connect(_copiar)
        bcer = QPushButton("Cerrar"); bcer.clicked.connect(dlg.accept)
        bcer.setStyleSheet(
            f"QPushButton {{ background:white; color:{SLATE_700};"
            f" border:1px solid {SILVER_300}; border-radius:6px; padding:6px 14px; }}")
        bar.addWidget(bcop); bar.addWidget(bcer)
        v.addLayout(bar)
        dlg.exec()

    def _pedir_dias(self):
        """Diálogo de alcance del reporte: TODOS los días (por defecto), UN solo
        día (el que elijas) o ELEGIR meses/días en árbol (Año→Mes→Día, tri-estado).
        Devuelve la lista de parte_ids elegidos, o None si cancela."""
        from collections import OrderedDict
        from PySide6.QtWidgets import QRadioButton, QButtonGroup
        partes = PD.listar_partes(self.pid)
        if not partes:
            QMessageBox.information(self, "Reporte del cuaderno",
                                    "Aún no hay días registrados.")
            return None

        dlg = QDialog(self)
        dlg.setWindowTitle("Reporte del cuaderno")
        dlg.setWindowModality(Qt.WindowModal)
        dlg.resize(380, 500)
        v = QVBoxLayout(dlg); v.setContentsMargins(16, 14, 16, 14); v.setSpacing(6)

        grp = QButtonGroup(dlg)
        rb_todos = QRadioButton(f"Todos los días registrados  ({len(partes)})")
        rb_uno = QRadioButton("Un solo día:")
        rb_elegir = QRadioButton("Elegir meses/días…")
        for b in (rb_todos, rb_uno, rb_elegir):
            grp.addButton(b)
        rb_todos.setChecked(True)   # por defecto: TODOS
        v.addWidget(rb_todos)

        # ── Un solo día: combo con todos los días (default = el día activo) ──
        frow = QHBoxLayout(); frow.setContentsMargins(20, 0, 0, 0)
        frow.addWidget(rb_uno)
        cmb = QComboBox()
        for pr in partes:
            cerr = "  🔒" if pr['estado'] == 'cerrado' else ""
            cmb.addItem(_fmt_fecha(pr['fecha']) + cerr, pr['id'])
        idx_act = next((k for k, pr in enumerate(partes)
                        if pr['id'] == self._dia_parte), -1)
        if idx_act >= 0:
            cmb.setCurrentIndex(idx_act)
        cmb.setEnabled(False)
        frow.addWidget(cmb, stretch=1)
        v.addLayout(frow)

        v.addWidget(rb_elegir)
        # ── Árbol Año → Mes → Día (tri-estado) ──────────────────────────────
        arbol = OrderedDict()
        for pr in partes:
            p = str(pr['fecha']).split('-')
            y = p[0] if len(p) == 3 else '—'
            mo = int(p[1]) if len(p) == 3 else 0
            arbol.setdefault(y, OrderedDict()).setdefault(mo, []).append(pr)
        tree = QTreeWidget(); tree.setHeaderHidden(True)
        tree.setStyleSheet(
            f"QTreeWidget {{ border:1px solid {SILVER_300}; border-radius:6px;"
            f" font-size:12px; background:white; }}")
        leaves = []
        _ck = Qt.ItemIsUserCheckable
        _tri = Qt.ItemIsAutoTristate
        for y, meses in arbol.items():
            yit = QTreeWidgetItem(tree, [f"Año {y}"])
            yit.setFlags(yit.flags() | _ck | _tri)
            for mo, prs in meses.items():
                mlbl = f"{_MESES[mo - 1]} {y}" if mo else str(y)
                mit = QTreeWidgetItem(yit, [mlbl])
                mit.setFlags(mit.flags() | _ck | _tri)
                for pr in prs:
                    cerr = "  🔒" if pr['estado'] == 'cerrado' else ""
                    dit = QTreeWidgetItem(mit, [_fmt_fecha(pr['fecha']) + cerr])
                    dit.setFlags(dit.flags() | _ck)
                    dit.setData(0, Qt.UserRole, pr['id'])
                    dit.setCheckState(0, Qt.Checked)
                    leaves.append(dit)
            yit.setCheckState(0, Qt.Checked)
        if tree.topLevelItemCount():
            tree.topLevelItem(tree.topLevelItemCount() - 1).setExpanded(True)
        tree.setEnabled(False)
        v.addWidget(tree, stretch=1)

        rb_uno.toggled.connect(cmb.setEnabled)
        rb_elegir.toggled.connect(tree.setEnabled)

        bar = QHBoxLayout(); bar.addStretch()
        b_ca = QPushButton("Cancelar"); b_ca.clicked.connect(dlg.reject)
        b_ok = QPushButton("Generar"); b_ok.clicked.connect(dlg.accept)
        b_ok.setStyleSheet(
            f"QPushButton {{ background:{ORANGE}; color:white; border:none;"
            f" border-radius:6px; padding:6px 16px; font-weight:600; }}")
        bar.addWidget(b_ca); bar.addWidget(b_ok)
        v.addLayout(bar)
        if dlg.exec() != QDialog.Accepted:
            return None
        if rb_todos.isChecked():
            return [pr['id'] for pr in partes]
        if rb_uno.isChecked():
            d = cmb.currentData()
            return [d] if d is not None else []
        return [d.data(0, Qt.UserRole) for d in leaves
                if d.checkState(0) == Qt.Checked]

    def _reporte(self, fmt='pdf'):
        if not _gate_reporte_editable(fmt, self):
            return
        import os
        from PySide6.QtWidgets import QFileDialog
        ids = self._pedir_dias()
        if ids is None:
            return
        if not ids:
            QMessageBox.information(self, "Reporte", "No marcaste ningún día.")
            return
        ext = {'pdf': 'pdf', 'docx': 'docx', 'odt': 'odt'}[fmt]
        filtro = {'pdf': 'PDF (*.pdf)', 'docx': 'Word (*.docx)',
                  'odt': 'LibreOffice (*.odt)'}[fmt]
        destino = os.path.join(_dir_reportes(), f"cuaderno_obra.{ext}")
        path, _ = QFileDialog.getSaveFileName(
            self, "Guardar cuaderno de obra", destino, filtro)
        if not path:
            return
        try:
            if fmt == 'pdf':
                from core import pdf_reports
                pdf_reports.generar_cuaderno_pdf(self.pid, ids, path)
            elif fmt == 'docx':
                from core import word_reports
                word_reports.generar_word_cuaderno(self.pid, ids, path)
            else:
                from core import odt_reports
                odt_reports.generar_odt_cuaderno(self.pid, ids, path)
            _guardar_dir_reportes(path)
            QMessageBox.information(self, "Reporte", f"Guardado en:\n{path}")
        except Exception as e:
            import traceback; traceback.print_exc()
            QMessageBox.critical(self, "Reporte",
                                 f"No se pudo generar el reporte:\n{e}")

    def hideEvent(self, e):
        self._guardar_obs()
        super().hideEvent(e)


# ── Requerimientos ────────────────────────────────────────────────────────────

(REQ_ITEM, REQ_DESC, REQ_UND, REQ_PRES, REQ_REQ) = range(5)
_REQ_COLS = ["#", "Recurso", "Und", "Presup.", "Requerido"]


class _ReqTable(_MetTable):
    """Tabla del requerimiento que acepta insumos arrastrados desde el árbol de
    insumos del proyecto (panel izquierdo). `on_drop(list_de_insumos)`."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.on_drop = None
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DropOnly)

    def _es_arbol(self, e):
        return isinstance(e.source(), QTreeWidget)

    def dragEnterEvent(self, e):
        if self._es_arbol(e):
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if self._es_arbol(e):
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e):
        if self._es_arbol(e) and self.on_drop:
            datos = [it.data(0, Qt.UserRole) for it in e.source().selectedItems()]
            datos = [d for d in datos if d]
            if datos:
                self.on_drop(datos)
                e.acceptProposedAction()
                return
        super().dropEvent(e)


class _TDRWorker(QThread):
    """Genera el TDR/EE.TT. con IA en segundo plano (no congela la UI)."""
    done = Signal(int, str, str)   # req_id, texto, error

    def __init__(self, req_id, datos):
        super().__init__()
        self._req_id = req_id
        self._datos = datos

    def run(self):
        try:
            texto, error = AR.generar_tdr_ia(self._req_id, self._datos)
            self.done.emit(self._req_id, texto or '', error or '')
        except Exception as e:   # noqa: BLE001
            import traceback; traceback.print_exc()
            self.done.emit(self._req_id, '', f"Error inesperado: {e}")


class _TdrHighlighter(QSyntaxHighlighter):
    """Resalta en negrita los títulos (MAYÚSCULAS), subtítulos numerados
    («1.», «1.1», «A)») y etiquetas («CAMPO:») del TDR en el editor — mismo
    criterio que el render del PDF, pero el texto sigue siendo plano."""

    def __init__(self, doc):
        super().__init__(doc)
        import re
        self._num = re.compile(r'^(\d+(\.\d+)*|[IVXLA-Z])[\.\)]\s+\S')
        self._label = re.compile(r'^[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ0-9 /.\-]{1,38}:\s')

    def highlightBlock(self, text):
        s = text.strip()
        if not s:
            return
        letras = [c for c in s if c.isalpha()]
        es_may = bool(letras) and s == s.upper() and len(s) <= 80
        if es_may or self._num.match(s) or self._label.match(s):
            fmt = QTextCharFormat()
            fmt.setFontWeight(QFont.Bold)
            fmt.setForeground(QColor(SLATE_700))
            self.setFormat(0, len(text), fmt)


class _CheckArbolDelegate(QStyledItemDelegate):
    """Pinta un check verde AL FINAL del nombre del insumo cuando ya está
    incluido en algún requerimiento (data UserRole+1 == True)."""

    def __init__(self, panel):
        super().__init__(panel)
        self._panel = panel

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        if index.data(Qt.UserRole + 1):
            sz = 14
            r = option.rect
            x = r.right() - sz - 6
            y = r.top() + (r.height() - sz) // 2
            self._panel._check_icon().paint(painter, x, y, sz, sz)


_ALM_COLS = ["Insumo", "Und", "Pedido", "Ingresado", "Consumido", "Stock", "Por llegar"]
(ALM_DESC, ALM_UND, ALM_PED, ALM_ING, ALM_CONS, ALM_STOCK, ALM_LLEG) = range(7)
_TIPO_NOMBRE = {'MAT': 'MATERIALES', 'EQ': 'EQUIPOS', 'SC': 'SERVICIOS'}
_AMBAR = "#C0621A"


class _AlmacenPanel(QWidget):
    """Kárdex de obra. Por insumo: PEDIDO (Σ requerimientos), INGRESADO (entradas
    al almacén, por fecha), CONSUMIDO (salidas del cuaderno), STOCK = ingresado −
    consumido y POR LLEGAR = pedido − ingresado. El panel derecho muestra el
    kárdex por día (Entrada/Salida/Stock) y permite registrar ingresos."""

    def __init__(self, pid: int, proy: dict, parent=None):
        super().__init__(parent)
        self.pid = pid
        self._proy = proy
        self._obra = parent          # _ControlObraView (para saltar al Cuaderno)
        self._rid_sel = None
        self._k_ingreso_ids = {}     # fila k_tbl -> ingreso_id (solo entradas)
        self._k_salida_fecha = {}    # fila k_tbl -> fecha ISO (solo salidas)
        self._k_loading = False      # guard: no guardar durante la carga del kárdex
        self._build_ui()

    def _build_ui(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 8, 10, 8)
        v.setSpacing(6)

        cab = QHBoxLayout(); cab.setSpacing(8)
        ttl = QLabel("Control de materiales — Kárdex de obra")
        ttl.setStyleSheet(f"color:{SLATE_700}; font-size:13px; font-weight:700;"
                          " background:transparent; border:none;")
        cab.addWidget(ttl)
        cab.addStretch()
        self.lbl_aviso = QLabel("")
        self.lbl_aviso.setStyleSheet("background:transparent; border:none;"
                                     f" font-size:11px; font-weight:700; color:{RED_700};")
        cab.addWidget(self.lbl_aviso)
        self.btn_reporte = QPushButton("📄 Reporte")
        self.btn_reporte.setCursor(Qt.PointingHandCursor)
        self.btn_reporte.setStyleSheet(
            f"QPushButton {{ background:white; color:{SLATE_700};"
            f" border:1px solid {SILVER_300}; border-radius:6px; font-size:11px;"
            f" padding:3px 10px; }} QPushButton:hover {{ background:{SILVER_200}; }}")
        _rm = QMenu(self.btn_reporte)
        _rm.addAction("PDF", lambda: self._reporte('pdf'))
        _rm.addAction("Word (.docx)", lambda: self._reporte('docx'))
        _rm.addAction("LibreOffice (.odt)", lambda: self._reporte('odt'))
        self.btn_reporte.setMenu(_rm)
        cab.addWidget(self.btn_reporte)
        v.addLayout(cab)

        leyenda = QLabel("Pedido = Σ requerimientos · Ingresado = entradas al "
                         "almacén · Consumido = Σ cuaderno · Stock = Ingresado − "
                         "Consumido · Por llegar = Pedido − Ingresado. Selecciona un "
                         "insumo y registra sus ingresos a la derecha →")
        leyenda.setWordWrap(True)
        leyenda.setStyleSheet(f"color:{SLATE_300}; font-size:10px; background:transparent;"
                              " border:none;")
        v.addWidget(leyenda)

        self.tbl = QTableWidget(0, len(_ALM_COLS))
        self.tbl.setHorizontalHeaderLabels(_ALM_COLS)
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setAlternatingRowColors(True)
        self.tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl.setSelectionMode(QAbstractItemView.SingleSelection)
        _grid_ss = (
            f"QTableWidget {{ background:white; alternate-background-color:{SILVER_100};"
            f" gridline-color:{SILVER_200}; font-size:11px; border:1px solid {SILVER_300}; }}"
            f"QHeaderView::section {{ background:{SLATE_500}; color:white; border:none;"
            f" padding:4px; font-size:10px; font-weight:700; }}"
            f"QTableWidget::item:selected {{ background:{SELECT_BG}; color:{SLATE_700}; }}")
        self.tbl.setStyleSheet(_grid_ss)
        hdr = self.tbl.horizontalHeader()
        hdr.setSectionResizeMode(ALM_DESC, QHeaderView.Stretch)
        for c in (ALM_UND, ALM_PED, ALM_ING, ALM_CONS, ALM_STOCK, ALM_LLEG):
            hdr.setSectionResizeMode(c, QHeaderView.Fixed)
        self.tbl.setColumnWidth(ALM_UND, 48)
        for c in (ALM_PED, ALM_ING, ALM_CONS, ALM_STOCK, ALM_LLEG):
            self.tbl.setColumnWidth(c, 80)
        self.tbl.verticalHeader().setDefaultSectionSize(24)
        self.tbl.itemSelectionChanged.connect(self._on_sel)

        # Panel derecho: kárdex por día + registro de ingresos.
        self._kbox = QWidget()
        self._kbox.setStyleSheet(f"background:white; border:1px solid {SILVER_300};")
        kv = QVBoxLayout(self._kbox)
        kv.setContentsMargins(8, 8, 8, 8); kv.setSpacing(5)
        krow = QHBoxLayout(); krow.setSpacing(6)
        self.k_titulo = QLabel("Kárdex por día")
        self.k_titulo.setWordWrap(True)
        self.k_titulo.setStyleSheet(f"color:{SLATE_700}; font-size:12px;"
            " font-weight:700; background:transparent; border:none;")
        krow.addWidget(self.k_titulo, stretch=1)
        self.btn_ingreso = QPushButton("+ Ingreso")
        self.btn_ingreso.setCursor(Qt.PointingHandCursor)
        self.btn_ingreso.setToolTip("Registrar una entrada de este material al "
            "almacén (fecha + cantidad). El material puede llegar en varias entregas.")
        self.btn_ingreso.setStyleSheet(
            f"QPushButton {{ background:{ORANGE}; color:white; border:none;"
            f" border-radius:6px; font-size:11px; font-weight:600; padding:4px 12px; }}"
            f"QPushButton:hover {{ background:#C0621A; }}"
            f"QPushButton:disabled {{ background:{SILVER_300}; color:white; }}")
        self.btn_ingreso.clicked.connect(self._agregar_ingreso)
        self.btn_ingreso.setEnabled(False)
        krow.addWidget(self.btn_ingreso)
        kv.addLayout(krow)
        self.k_resumen = QLabel("Selecciona un insumo de la izquierda.")
        self.k_resumen.setWordWrap(True)
        self.k_resumen.setStyleSheet(f"color:{SLATE_500}; font-size:11px;"
            " background:transparent; border:none;")
        kv.addWidget(self.k_resumen)
        self.k_tbl = QTableWidget(0, 5)
        self.k_tbl.setHorizontalHeaderLabels(
            ["Fecha", "Entrada", "Salida", "Stock", "Observaciones"])
        self.k_tbl.verticalHeader().setVisible(False)
        self.k_tbl.setAlternatingRowColors(True)
        self.k_tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.k_tbl.setSelectionMode(QAbstractItemView.NoSelection)
        # Editor inline (QLineEdit) legible mientras se escribe: fondo blanco,
        # texto oscuro (sin esto hereda el QSS global y no se ve el texto).
        self.k_tbl.setStyleSheet(
            _grid_ss + f"QTableWidget QLineEdit {{ background:white;"
            f" color:{SLATE_700}; border:1px solid {ORANGE}; padding:0px;"
            f" selection-background-color:{ORANGE}; selection-color:white; }}")
        self.k_tbl.setContextMenuPolicy(Qt.CustomContextMenu)
        self.k_tbl.customContextMenuRequested.connect(self._menu_kardex)
        self.k_tbl.cellDoubleClicked.connect(self._dbl_kardex)
        self.k_tbl.itemChanged.connect(self._on_kardex_obs_changed)
        khdr = self.k_tbl.horizontalHeader()
        # TODAS las columnas redimensionables; la última (Observaciones) estira
        # para que la tabla ocupe TODO el ancho del panel (sin hueco a la derecha).
        for c in range(5):
            khdr.setSectionResizeMode(c, QHeaderView.Interactive)
        khdr.setStretchLastSection(True)
        self.k_tbl.setColumnWidth(0, 90)    # Fecha
        for c in (1, 2, 3):
            self.k_tbl.setColumnWidth(c, 64)
        self.k_tbl.verticalHeader().setDefaultSectionSize(22)
        kv.addWidget(self.k_tbl, stretch=1)
        k_hint = QLabel("Doble clic en Observaciones para anotar · doble clic en "
                        "Fecha/Entrada edita la entrada · clic derecho: registrar / "
                        "editar / eliminar.")
        k_hint.setStyleSheet(f"color:{SLATE_300}; font-size:9px; background:transparent;"
                             " border:none;")
        kv.addWidget(k_hint)

        self._split = QSplitter(Qt.Horizontal)
        self._split.setChildrenCollapsible(False)
        self._split.setHandleWidth(4)
        self._split.addWidget(self.tbl)
        self._split.addWidget(self._kbox)
        self._split.setStretchFactor(0, 3)
        self._split.setStretchFactor(1, 2)
        self._split.setSizes([580, 380])
        v.addWidget(self._split, stretch=1)

        self.lbl_vacio = QLabel("Aún no hay insumos requeridos, ingresados ni "
            "consumidos.\nCrea requerimientos y registra ingresos/consumo.")
        self.lbl_vacio.setAlignment(Qt.AlignCenter)
        self.lbl_vacio.setStyleSheet(f"color:{SLATE_300}; font-size:13px;"
            " font-weight:600; background:transparent; border:none;")
        self.lbl_vacio.hide()
        v.addWidget(self.lbl_vacio)

    def _reporte(self, fmt='pdf'):
        if not _gate_reporte_editable(fmt, self):
            return
        import os
        from PySide6.QtWidgets import QFileDialog
        ext = {'pdf': 'pdf', 'docx': 'docx', 'odt': 'odt'}[fmt]
        filtro = {'pdf': 'PDF (*.pdf)', 'docx': 'Word (*.docx)',
                  'odt': 'LibreOffice (*.odt)'}[fmt]
        destino = os.path.join(_dir_reportes(), f"control_materiales.{ext}")
        path, _ = QFileDialog.getSaveFileName(
            self, "Guardar control de materiales", destino, filtro)
        if not path:
            return
        try:
            if fmt == 'pdf':
                from core import pdf_reports
                pdf_reports.generar_almacen_pdf(self.pid, path)
            elif fmt == 'docx':
                from core import word_reports
                word_reports.generar_word_almacen(self.pid, path)
            else:
                from core import odt_reports
                odt_reports.generar_odt_almacen(self.pid, path)
            _guardar_dir_reportes(path)
            QMessageBox.information(self, "Reporte", f"Guardado en:\n{path}")
        except Exception as e:
            import traceback; traceback.print_exc()
            QMessageBox.critical(self, "Reporte",
                                 f"No se pudo generar el reporte:\n{e}")

    def cargar(self):
        dm = get_decimales_metrado()
        filas = REQ.control_almacen(self.pid)
        self._filas_por_rid = {f['recurso_id']: f for f in filas}
        self.tbl.blockSignals(True)
        self.tbl.setRowCount(0)
        if not filas:
            self.tbl.blockSignals(False)
            self._split.hide(); self.lbl_vacio.show()
            self.lbl_aviso.setText("")
            return
        self._split.show(); self.lbl_vacio.hide()
        neg_stock = 0
        primera_datos = None
        # Separar pedidos (en requerimientos) de los extras (sin requerimiento),
        # solo si existen ambos grupos.
        hay_req = any(f['pedido'] > 1e-6 for f in filas)
        hay_extra = any(f['pedido'] <= 1e-6 for f in filas)
        mostrar_grupos = hay_req and hay_extra
        grupo_actual = None
        for f in filas:
            es_pedido = f['pedido'] > 1e-6
            if mostrar_grupos and es_pedido != grupo_actual:
                grupo_actual = es_pedido
                self._fila_grupo("PEDIDOS EN REQUERIMIENTOS" if es_pedido
                                 else "OTROS — SIN REQUERIMIENTO")
            stock_neg = f['stock'] < -1e-6
            if stock_neg:
                neg_stock += 1
            r = self.tbl.rowCount()
            self.tbl.insertRow(r)
            if primera_datos is None:
                primera_datos = r
            vals = [f['descripcion'], f['unidad'],
                    _m(f['pedido'], dm), _m(f['ingresado'], dm),
                    _m(f['consumido'], dm), _m(f['stock'], dm), _m(f['por_llegar'], dm)]
            for c, txt in enumerate(vals):
                it = QTableWidgetItem(txt)
                if c == ALM_DESC:
                    it.setData(Qt.UserRole, f['recurso_id'])
                if c >= ALM_PED:
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if c == ALM_STOCK:
                    fnt = it.font(); fnt.setBold(True); it.setFont(fnt)
                    it.setForeground(QColor(RED_700 if stock_neg else GREEN_700))
                elif c == ALM_LLEG and f['por_llegar'] > 1e-6:
                    it.setForeground(QColor(_AMBAR))
                self.tbl.setItem(r, c, it)
        self.tbl.blockSignals(False)
        if neg_stock:
            self.lbl_aviso.setText(f"⚠ {neg_stock} insumo"
                f"{'s' if neg_stock != 1 else ''} con stock negativo "
                "(consumido > ingresado)")
        else:
            self.lbl_aviso.setText("")
        # Mantener el insumo seleccionado, o el primero, para no dejar el kárdex vacío.
        destino = self._fila_de_rid(self._rid_sel)
        if destino is None:
            destino = primera_datos
        if destino is not None:
            self.tbl.setCurrentCell(destino, ALM_DESC)

    def _fila_de_rid(self, rid):
        if rid is None:
            return None
        for r in range(self.tbl.rowCount()):
            it = self.tbl.item(r, ALM_DESC)
            if it and it.data(Qt.UserRole) == rid:
                return r
        return None

    def _seleccionar_rid(self, rid):
        r = self._fila_de_rid(rid)
        if r is not None:
            self.tbl.setCurrentCell(r, ALM_DESC)

    def _on_sel(self):
        items = self.tbl.selectedItems()
        if not items:
            return
        it = self.tbl.item(items[0].row(), ALM_DESC)
        rid = it.data(Qt.UserRole) if it else None
        if rid is None:
            return
        self._rid_sel = rid
        self.btn_ingreso.setEnabled(_co_editable(self._proy))
        self._mostrar_kardex(rid)

    def _mostrar_kardex(self, rid: int):
        dm = get_decimales_metrado()
        f = getattr(self, '_filas_por_rid', {}).get(rid)
        if not f:
            return
        und = f['unidad']
        self.k_titulo.setText(f"{f['descripcion']}  ({und})" if und else f['descripcion'])
        self.k_resumen.setText(
            f"Pedido {_m(f['pedido'], dm)} · Ingresado {_m(f['ingresado'], dm)} · "
            f"Consumido {_m(f['consumido'], dm)} · Stock {_m(f['stock'], dm)}")
        mov = ALM.movimientos(self.pid, rid)
        self._k_loading = True
        self.k_tbl.setRowCount(0)
        self._k_ingreso_ids = {}
        self._k_salida_fecha = {}
        stock = 0.0
        for m in mov:
            es_ent = (m['tipo'] == 'entrada')
            cant = m['cantidad'] or 0
            stock += cant if es_ent else -cant
            r = self.k_tbl.rowCount()
            self.k_tbl.insertRow(r)
            es_ingreso = es_ent and m.get('ingreso_id')
            if es_ingreso:
                self._k_ingreso_ids[r] = m['ingreso_id']
                tip = "Doble clic para editar la fecha o la cantidad de esta entrada."
            elif not es_ent:
                self._k_salida_fecha[r] = m['fecha']
                tip = ("Salida del cuaderno de obra (solo lectura). Doble clic para "
                       "ir a ese día en el Cuaderno y editar el consumo ahí.")
            else:
                tip = ""
            vals = [_fmt_fecha(m['fecha']),
                    _m(cant, dm) if es_ent else "",
                    _m(cant, dm) if not es_ent else "",
                    _m(round(stock, 2), dm),
                    m.get('observacion') or ""]
            for c, txt in enumerate(vals):
                it = QTableWidgetItem(txt)
                if tip:
                    it.setToolTip(tip)
                if c in (1, 2, 3):
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                # Entradas/salidas (c 1,2): sin color → texto oscuro por defecto,
                # como la columna Fecha (Marco los prefiere en negro, no verde/naranja).
                if c == 3:
                    it.setForeground(QColor(RED_700 if stock < -1e-6 else SLATE_700))
                # Observaciones (c 4): editable inline SOLO en filas de ingreso y
                # con la obra «En ejecución».
                if c == 4 and es_ingreso and _co_editable(self._proy):
                    it.setFlags(it.flags() | Qt.ItemIsEditable)
                    it.setToolTip("Doble clic para escribir una observación.")
                else:
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                self.k_tbl.setItem(r, c, it)
        if not mov:
            r = self.k_tbl.rowCount()
            self.k_tbl.insertRow(r)
            it = QTableWidgetItem("Sin movimientos. Usa «+ Ingreso» para registrar "
                                  "la llegada del material.")
            it.setForeground(QColor(SLATE_300))
            self.k_tbl.setItem(r, 0, it)
            self.k_tbl.setSpan(r, 0, 1, 5)
        self._k_loading = False

    def _agregar_ingreso(self):
        if not _co_editable(self._proy):
            return
        rid = self._rid_sel
        f = getattr(self, '_filas_por_rid', {}).get(rid)
        if not f:
            return
        datos = self._pedir_ingreso(f)
        if not datos:
            return
        fecha, cant, obs = datos
        ALM.agregar_ingreso(self.pid, rid, fecha, cant,
                            f['descripcion'], f['unidad'], obs)
        self.cargar()
        self._seleccionar_rid(rid)

    def _pedir_ingreso(self, f, inicial=None):
        """Diálogo de ingreso. `inicial=(fecha_iso, cantidad, observacion)` →
        modo edición."""
        editar = inicial is not None
        dlg = QDialog(self)
        dlg.setWindowTitle("Editar ingreso de material" if editar
                           else "Registrar ingreso de material")
        lay = QVBoxLayout(dlg)
        lbl = QLabel(f"{f['descripcion']}" + (f"  ({f['unidad']})" if f['unidad'] else ""))
        lbl.setStyleSheet(f"color:{SLATE_700}; font-weight:700;"
                          " background:transparent; border:none;")
        lay.addWidget(lbl)
        form = QFormLayout()
        de = QDateEdit(); de.setCalendarPopup(True)
        de.setDisplayFormat("dd/MM/yyyy")
        cant = QLineEdit(); cant.setPlaceholderText("Cantidad que llegó")
        obs = QLineEdit(); obs.setPlaceholderText("Opcional (guía, proveedor, N° vale…)")
        if editar:
            fi, ci, oi = (list(inicial) + [''])[:3]
            d = QDate.fromString(str(fi), "yyyy-MM-dd")
            de.setDate(d if d.isValid() else QDate.currentDate())
            cant.setText(_m(ci, get_decimales_metrado()))
            obs.setText(oi or '')
        else:
            de.setDate(QDate.currentDate())
        form.addRow("Fecha de llegada:", de)
        form.addRow("Cantidad:", cant)
        form.addRow("Observación:", obs)
        lay.addLayout(form)
        bar = QHBoxLayout(); bar.addStretch()
        b_ok = QPushButton("Guardar" if editar else "Registrar")
        b_ca = QPushButton("Cancelar")
        b_ok.setCursor(Qt.PointingHandCursor); b_ca.setCursor(Qt.PointingHandCursor)
        b_ok.setStyleSheet(
            f"QPushButton {{ background:{ORANGE}; color:white; border:none;"
            f" border-radius:6px; font-weight:600; padding:5px 14px; }}"
            f"QPushButton:hover {{ background:#C0621A; }}")
        bar.addWidget(b_ca); bar.addWidget(b_ok)
        lay.addLayout(bar)
        b_ok.clicked.connect(dlg.accept); b_ca.clicked.connect(dlg.reject)
        cant.setFocus()
        if dlg.exec() != QDialog.Accepted:
            return None
        try:
            q = parse_num(cant.text())
        except (TypeError, ValueError):
            q = 0
        if not q or q <= 0:
            return None
        return (de.date().toString("yyyy-MM-dd"), q, obs.text().strip())

    def _menu_kardex(self, pos):
        it = self.k_tbl.itemAt(pos)
        row = it.row() if it else -1
        ing_id = self._k_ingreso_ids.get(row)
        fecha_sal = self._k_salida_fecha.get(row)
        co = _co_editable(self._proy)
        m = QMenu(self)
        # Registrar una nueva entrada (cantidad + fecha) desde el clic derecho.
        a_new = m.addAction("＋ Registrar ingreso…")
        a_new.setEnabled(self._rid_sel is not None and co)
        a_ed = a_del = a_go = None
        if ing_id and co:
            m.addSeparator()
            a_ed = m.addAction("Editar este ingreso…")
            a_del = m.addAction("Eliminar este ingreso")
        elif fecha_sal:
            m.addSeparator()
            a_go = m.addAction("Ir a ese día en el Cuaderno de obra…")
        ch = m.exec(self.k_tbl.viewport().mapToGlobal(pos))
        if ch is None:
            return
        if ch == a_new:
            self._agregar_ingreso()
        elif ch is a_ed:
            self._editar_ingreso(ing_id)
        elif ch is a_del:
            ALM.eliminar_ingreso(ing_id)
            rid = self._rid_sel
            self.cargar()
            self._seleccionar_rid(rid)
        elif ch is a_go:
            self._ir_a_cuaderno(fecha_sal)

    def _dbl_kardex(self, row, col):
        """Doble clic:
        - en la columna Observaciones (col 4) de una entrada → edición INLINE.
        - en Fecha/Entrada/Salida/Stock → editar la entrada (diálogo) o saltar al
          día del Cuaderno (si es salida)."""
        if col == 4:
            if row in self._k_ingreso_ids:
                it = self.k_tbl.item(row, 4)
                if it is not None:
                    self.k_tbl.editItem(it)
            return
        ing_id = self._k_ingreso_ids.get(row)
        if ing_id:
            self._editar_ingreso(ing_id)
            return
        fecha = self._k_salida_fecha.get(row)
        if fecha:
            self._ir_a_cuaderno(fecha)

    def _on_kardex_obs_changed(self, item):
        """Guarda la observación editada inline en la celda del kárdex."""
        if self._k_loading or item is None or item.column() != 4:
            return
        ing_id = self._k_ingreso_ids.get(item.row())
        if ing_id:
            ALM.actualizar_observacion(ing_id, item.text().strip())

    def _editar_ingreso(self, ing_id):
        if not _co_editable(self._proy):
            return
        rid = self._rid_sel
        f = getattr(self, '_filas_por_rid', {}).get(rid)
        if not f:
            return
        ings = ALM.listar_ingresos(self.pid, rid)
        cur = next((x for x in ings if x['id'] == ing_id), None)
        if not cur:
            return
        datos = self._pedir_ingreso(
            f, inicial=(cur['fecha'], cur['cantidad'], cur.get('observacion') or ''))
        if not datos:
            return
        fecha, cant, obs = datos
        ALM.actualizar_ingreso(ing_id, fecha, cant, obs)
        self.cargar()
        self._seleccionar_rid(rid)

    def _ir_a_cuaderno(self, fecha):
        """Cambia a la pestaña Cuaderno, selecciona ese día y deja el cursor en la
        celda «Cantidad» del insumo seleccionado, listo para editar (el consumo se
        edita en el cuaderno, que es la fuente única del parte por día)."""
        obra = self._obra
        if obra is None:
            return
        try:
            obra.mostrar_tab(obra._idx_cuaderno)
            obra._cuaderno_panel.seleccionar_dia(fecha, recurso_id=self._rid_sel)
        except Exception:   # noqa: BLE001
            pass

    def _fila_grupo(self, titulo: str):
        # El stylesheet con alternate-background-color ignora setBackground por
        # fila, así que el divisor se hace con TEXTO oscuro en negrita (siempre
        # visible) en vez de una barra de color con texto blanco.
        r = self.tbl.rowCount()
        self.tbl.insertRow(r)
        it = QTableWidgetItem("›  " + titulo)
        fnt = it.font(); fnt.setBold(True); it.setFont(fnt)
        it.setForeground(QColor(SLATE_700))
        flags = it.flags() & ~Qt.ItemIsSelectable
        for c in range(len(_ALM_COLS)):
            cell = it if c == 0 else QTableWidgetItem("")
            cell.setFlags(flags)
            self.tbl.setItem(r, c, cell)
        self.tbl.setSpan(r, 0, 1, len(_ALM_COLS))


_CS_LINEAS = {'solida': Qt.SolidLine, 'guiones': Qt.DashLine, 'puntos': Qt.DotLine,
              'guion_punto': Qt.DashDotLine}
_CS_LINEA_OPC = [('Sólida', 'solida'), ('Guiones', 'guiones'),
                 ('Puntos', 'puntos'), ('Guion-punto', 'guion_punto')]
_CS_MARCA_OPC = [('Círculo', 'circulo'), ('Cuadrado', 'cuadrado'),
                 ('Triángulo', 'triangulo'), ('Rombo', 'rombo'),
                 ('Sin marca', 'ninguna')]
# clave · etiqueta · color por defecto · línea por defecto
_CS_SERIES = [('prog', 'Programado', BLUE, 'solida'),
              ('reprog', 'Reprogramado', PURPLE, 'guiones'),
              ('real', 'Real', ORANGE, 'solida')]


class _CurvaSChart(QWidget):
    """Curva S programada vs reprogramada vs real (QPainter). Eje X = períodos,
    eje Y = % acumulado. Colores/estilos de línea y marcadores configurables por
    clic derecho (persisten en QSettings)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(220)
        self._d = None
        self._show = {'prog': True, 'reprog': True, 'real': True}
        self._show_pct = True
        self._estilos = {}
        self._cargar_estilos()
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("background:white;")

    # ── Estilos (color · línea · marca) por serie, persistidos ───────────────
    def _cargar_estilos(self):
        st = QSettings("IngePresupuestos", "CurvaS")
        for key, _lbl, col, lin in _CS_SERIES:
            self._estilos[key] = {
                'color': st.value(f"{key}/color", col) or col,
                'linea': st.value(f"{key}/linea", lin) or lin,
                'marca': st.value(f"{key}/marca", 'circulo') or 'circulo',
            }

    def _guardar_estilo(self, key):
        st = QSettings("IngePresupuestos", "CurvaS")
        e = self._estilos[key]
        st.setValue(f"{key}/color", e['color'])
        st.setValue(f"{key}/linea", e['linea'])
        st.setValue(f"{key}/marca", e['marca'])

    def set_data(self, d):
        self._d = d
        self.update()

    def set_show_prog(self, on):
        self._show['prog'] = bool(on); self.update()

    def set_show_reprog(self, on):
        self._show['reprog'] = bool(on); self.update()

    def set_show_real(self, on):
        self._show['real'] = bool(on); self.update()

    def set_show_pct(self, on):
        self._show_pct = bool(on); self.update()

    @property
    def _show_prog(self):
        return self._show['prog']

    @property
    def _show_reprog(self):
        return self._show['reprog']

    @property
    def _show_real(self):
        return self._show['real']

    # ── Menú contextual: personalizar cada serie ─────────────────────────────
    def contextMenuEvent(self, ev):
        m = QMenu(self)
        for key, lbl, _c, _l in _CS_SERIES:
            sub = m.addMenu(lbl)
            sub.addAction("Color…", lambda k=key: self._elegir_color(k))
            ml = sub.addMenu("Línea")
            for txt, val in _CS_LINEA_OPC:
                a = ml.addAction(txt); a.setCheckable(True)
                a.setChecked(self._estilos[key]['linea'] == val)
                a.triggered.connect(
                    lambda _=False, k=key, vv=val: self._set_estilo(k, 'linea', vv))
            mk = sub.addMenu("Marca")
            for txt, val in _CS_MARCA_OPC:
                a = mk.addAction(txt); a.setCheckable(True)
                a.setChecked(self._estilos[key]['marca'] == val)
                a.triggered.connect(
                    lambda _=False, k=key, vv=val: self._set_estilo(k, 'marca', vv))
        m.addSeparator()
        m.addAction("Restablecer colores y estilos", self._reset_estilos)
        m.exec(ev.globalPos())

    def _elegir_color(self, key):
        c = QColorDialog.getColor(QColor(self._estilos[key]['color']), self,
                                  "Color de la serie")
        if c.isValid():
            self._set_estilo(key, 'color', c.name())

    def _set_estilo(self, key, campo, valor):
        self._estilos[key][campo] = valor
        self._guardar_estilo(key)
        self.update()

    def _reset_estilos(self):
        for key, _lbl, col, lin in _CS_SERIES:
            self._estilos[key] = {'color': col, 'linea': lin, 'marca': 'circulo'}
            self._guardar_estilo(key)
        self.update()

    def _marca(self, p, pt, forma, s, color):
        if forma == 'ninguna':
            return
        p.setBrush(QColor(color)); p.setPen(QColor(color))
        if forma == 'circulo':
            p.drawEllipse(pt, s, s)
        elif forma == 'cuadrado':
            p.drawRect(QRectF(pt.x() - s, pt.y() - s, 2 * s, 2 * s))
        elif forma == 'triangulo':
            p.drawPolygon(QPolygonF([QPointF(pt.x(), pt.y() - s - 1),
                                     QPointF(pt.x() - s - 1, pt.y() + s),
                                     QPointF(pt.x() + s + 1, pt.y() + s)]))
        elif forma == 'rombo':
            p.drawPolygon(QPolygonF([QPointF(pt.x(), pt.y() - s - 1),
                                     QPointF(pt.x() + s + 1, pt.y()),
                                     QPointF(pt.x(), pt.y() + s + 1),
                                     QPointF(pt.x() - s - 1, pt.y())]))

    def _dibujar_serie(self, p, key, pts_px, ancho, marca_s):
        e = self._estilos[key]
        col = e['color']
        p.setPen(QPen(QColor(col), ancho, _CS_LINEAS.get(e['linea'], Qt.SolidLine)))
        p.setBrush(Qt.NoBrush)
        p.drawPolyline(QPolygonF(pts_px))
        for pt in pts_px[1:]:
            self._marca(p, pt, e['marca'], marca_s, col)

    def _etiquetas(self, p, pares, color, dy):
        """Dibuja el % junto a cada punto en negro con recuadro (chip blanco con
        borde del color de la serie). pares = [(QPointF, pct)]."""
        if not self._show_pct:
            return
        f = QFont(); f.setPointSize(7); f.setBold(True); p.setFont(f)
        for pt, pct in pares:
            txt = f"{pct:.0f}%"
            w = 13 + 5 * len(txt)
            chip = QRectF(pt.x() - w / 2, pt.y() + dy, w, 14)
            p.setPen(QPen(QColor(color), 1))
            p.setBrush(QColor("white"))
            p.drawRoundedRect(chip, 3, 3)
            p.setPen(QColor("black"))
            p.drawText(chip, Qt.AlignCenter, txt)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        W, H = self.width(), self.height()
        p.fillRect(0, 0, W, H, QColor("white"))
        d = self._d
        ml, mr, mt, mb = 42, 14, 18, 30
        x0, y0 = ml, H - mb
        x1, y1 = W - mr, mt
        n = d['n_periods'] if d else 0
        # El eje Y es % (0–100), no depende del monto: basta con tener alguna
        # serie con datos (programado con presupuesto, o real/reprogramado).
        hay_serie = d and (d['total_general'] > 0
                           or len(d.get('real_pts', [])) > 1
                           or len(d.get('reprog_pts', [])) > 1)
        if not d or n <= 0 or not hay_serie:
            p.setPen(QColor(SLATE_300))
            p.drawText(self.rect(), Qt.AlignCenter,
                       "Genera el cronograma y registra valorizaciones\n"
                       "para ver la curva programada vs real.")
            p.end(); return

        def px(x):   # x en períodos [0..n] → píxel
            return x0 + (x / n) * (x1 - x0)

        def py(pct):  # % [0..100] → píxel
            return y0 - (pct / 100.0) * (y0 - y1)

        # Grilla horizontal 0/25/50/75/100 + ejes.
        p.setPen(QPen(QColor(SILVER_300), 1, Qt.DashLine))
        f = QFont(); f.setPointSize(7); p.setFont(f)
        for g in (0, 25, 50, 75, 100):
            yy = py(g)
            p.setPen(QPen(QColor(SILVER_300), 1, Qt.DashLine))
            p.drawLine(int(x0), int(yy), int(x1), int(yy))
            p.setPen(QColor(SLATE_500))
            p.drawText(QRectF(0, yy - 7, ml - 5, 14),
                       Qt.AlignRight | Qt.AlignVCenter, f"{g}%")
        p.setPen(QPen(QColor(SLATE_500), 1))
        p.drawLine(int(x0), int(y0), int(x1), int(y0))
        # Ticks X (1..n) con las etiquetas de período (Mes1 / Jun 26 / Sem1).
        labels = d.get('labels', [])
        for i in range(1, n + 1):
            xx = px(i)
            p.setPen(QColor(SLATE_300))
            p.drawLine(int(xx), int(y0), int(xx), int(y0) + 3)
            p.setPen(QColor(SLATE_500))
            lab = labels[i - 1] if i <= len(labels) else str(i)
            p.drawText(QRectF(xx - 26, y0 + 4, 52, 14), Qt.AlignCenter, lab)

        # Series: por clave (prog/reprog/real), con estilo configurable. dy = offset
        # de la etiqueta de %, ancho de línea y tamaño de marcador por serie.
        series = [('prog', d.get('prog_pts', []), 2.2, 2.6, -14),
                  ('reprog', d.get('reprog_pts', []), 2.2, 2.6, -14),
                  ('real', d.get('real_pts', []), 2.4, 3.0, 4)]
        presentes = {}   # key → True si se dibujó (tiene datos y está visible)
        for key, data, ancho, ms, dy in series:
            presentes[key] = len(data) > 1 and self._show[key]
            if not presentes[key]:
                continue
            pts = [QPointF(px(x), py(v)) for x, v in data]
            self._dibujar_serie(p, key, pts, ancho, ms)
            self._etiquetas(p, [(QPointF(px(x), py(v)), v) for x, v in data[1:]],
                            self._estilos[key]['color'], dy)

        self._dibujar_leyenda(p, x0, y1, presentes)
        p.end()

    def _dibujar_leyenda(self, p, x0, y1, presentes):
        entries = [(k, lbl) for k, lbl, _c, _l in _CS_SERIES if presentes.get(k)]
        if not entries:
            return
        f = QFont(); f.setPointSize(8); p.setFont(f)
        row_h, pad, sample = 16, 7, 22
        w = sample + 8 + max(p.fontMetrics().horizontalAdvance(lbl)
                             for _k, lbl in entries) + pad * 2
        h = pad * 2 + row_h * len(entries)
        bx, by = x0 + 10, y1 + 8
        p.setPen(QPen(QColor(SILVER_300), 1))
        p.setBrush(QColor(255, 255, 255, 235))
        p.drawRoundedRect(QRectF(bx, by, w, h), 6, 6)
        for i, (key, lbl) in enumerate(entries):
            cy = by + pad + i * row_h + row_h / 2
            e = self._estilos[key]
            p.setPen(QPen(QColor(e['color']), 2.2,
                          _CS_LINEAS.get(e['linea'], Qt.SolidLine)))
            p.drawLine(int(bx + pad), int(cy), int(bx + pad + sample), int(cy))
            self._marca(p, QPointF(bx + pad + sample / 2, cy), e['marca'], 3.0,
                        e['color'])
            p.setPen(QColor(SLATE_700))
            p.drawText(QRectF(bx + pad + sample + 6, cy - 8, w, 16),
                       Qt.AlignLeft | Qt.AlignVCenter, lbl)


_CURVA_SUBS = ["#", "Período",
               "Monto", "% Ejec", "% Acum",
               "Monto", "% Ejec", "% Acum",
               "Monto", "% Ejec", "% Acum", "Desv."]
(CC_NUM, CC_PER,
 CC_P_MON, CC_P_EJE, CC_P_ACU,
 CC_R_MON, CC_R_EJE, CC_R_ACU,
 CC_X_MON, CC_X_EJE, CC_X_ACU, CC_DESV) = range(12)
_CURVA_GROUPS = [("Programado", CC_P_MON, 3), ("Reprogramado", CC_R_MON, 3),
                 ("Real", CC_X_MON, 4)]   # Real incluye la Desviación


class _CurvaSRealPanel(QWidget):
    """Curva S real: avance acumulado programado (cronograma) vs real
    (valorizaciones), gráfico + tabla comparativa con la desviación."""

    def __init__(self, pid: int, proy: dict, parent=None):
        super().__init__(parent)
        self.pid = pid
        self._proy = proy
        self._base = 'mes_cal'   # default: corte a fin de mes calendario
        self._loading = False
        self._build_ui()

    def _build_ui(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 8, 10, 8); v.setSpacing(6)
        self.chart = _CurvaSChart()   # antes de la toolbar (los checks lo usan)

        cab = QHBoxLayout(); cab.setSpacing(8)
        ttl = QLabel("Curva S real — programado vs ejecutado")
        ttl.setStyleSheet(f"color:{SLATE_700}; font-size:13px; font-weight:700;"
                          " background:transparent; border:none;")
        cab.addWidget(ttl)
        lbl_p = QLabel("Período:")
        lbl_p.setStyleSheet(f"color:{SLATE_500}; font-size:11px; background:transparent;"
                            " border:none;")
        cab.addWidget(lbl_p)
        self.cmb = QComboBox()
        self._bases = ['semana', 'mes', 'mes_cal']
        self.cmb.addItems(["Semanal", "Mensual (rodante)", "Mensual (fin de mes)"])
        self.cmb.setCurrentIndex(2)   # default: fin de mes calendario
        self.cmb.setToolTip("Fin de mes = cortes a fin de mes calendario (la "
            "valorización mensual; primer mes parcial si arrancas a la quincena). "
            "Rodante = cada 30/7 días desde el inicio de la obra.")
        self.cmb.currentIndexChanged.connect(self._on_periodo)
        self.cmb.setStyleSheet("QComboBox { min-height:0; padding:2px 8px;"
            f" font-size:11px; border:1px solid {SILVER_300}; border-radius:4px; }}")
        cab.addWidget(self.cmb)
        _chk_ss = f"QCheckBox {{ color:{SLATE_500}; font-size:11px; padding:0 4px; }}"
        self.chk_prog = QCheckBox("Programado")
        self.chk_prog.setChecked(True)
        self.chk_prog.setToolTip("Mostrar u ocultar la curva y las columnas de "
                                 "Programado.")
        self.chk_prog.setStyleSheet(_chk_ss)
        self.chk_prog.toggled.connect(self._toggle_prog)
        cab.addWidget(self.chk_prog)
        self.chk_reprog = QCheckBox("Reprogramado")
        self.chk_reprog.setChecked(True)
        self.chk_reprog.setToolTip("Mostrar u ocultar la curva y las columnas de "
                                   "Reprogramado.")
        self.chk_reprog.setStyleSheet(_chk_ss)
        self.chk_reprog.toggled.connect(self._toggle_reprog)
        cab.addWidget(self.chk_reprog)
        self.chk_real = QCheckBox("Real")
        self.chk_real.setChecked(True)
        self.chk_real.setToolTip("Mostrar u ocultar la curva y las columnas de Real.")
        self.chk_real.setStyleSheet(_chk_ss)
        self.chk_real.toggled.connect(self._toggle_real)
        cab.addWidget(self.chk_real)
        self.chk_pct = QCheckBox("Mostrar %")
        self.chk_pct.setChecked(True)
        self.chk_pct.setStyleSheet(_chk_ss)
        self.chk_pct.toggled.connect(self.chart.set_show_pct)
        cab.addWidget(self.chk_pct)
        self.btn_limpiar = QPushButton("Restablecer")
        self.btn_limpiar.setCursor(Qt.PointingHandCursor)
        self.btn_limpiar.setToolTip("Borra los valores editados (etiqueta, "
            "programado y reprogramado) de esta base y vuelve a lo derivado del "
            "cronograma.")
        self.btn_limpiar.setStyleSheet(
            f"QPushButton {{ background:white; color:{SLATE_700};"
            f" border:1px solid {SILVER_300}; border-radius:6px; font-size:11px;"
            f" padding:3px 10px; }} QPushButton:hover {{ background:{SILVER_200}; }}")
        self.btn_limpiar.clicked.connect(self._limpiar_reprog)
        cab.addWidget(self.btn_limpiar)
        self.btn_reporte = QPushButton("📄 Reporte")
        self.btn_reporte.setCursor(Qt.PointingHandCursor)
        self.btn_reporte.setStyleSheet(
            f"QPushButton {{ background:white; color:{SLATE_700};"
            f" border:1px solid {SILVER_300}; border-radius:6px; font-size:11px;"
            f" padding:3px 10px; }} QPushButton:hover {{ background:{SILVER_200}; }}")
        _rm = QMenu(self.btn_reporte)
        _rm.addAction("PDF", lambda: self._reporte('pdf'))
        _rm.addAction("Word (.docx)", lambda: self._reporte('docx'))
        _rm.addAction("LibreOffice (.odt)", lambda: self._reporte('odt'))
        self.btn_reporte.setMenu(_rm)
        cab.addWidget(self.btn_reporte)
        cab.addStretch()
        self.lbl_resumen = QLabel("")
        self.lbl_resumen.setStyleSheet("background:transparent; border:none;"
            f" font-size:11px; font-weight:700; color:{SLATE_700};")
        cab.addWidget(self.lbl_resumen)
        v.addLayout(cab)

        self._split = QSplitter(Qt.Vertical)
        self._split.setChildrenCollapsible(False)
        self._split.setHandleWidth(4)
        self._split.addWidget(self.chart)

        self.tbl = QTableWidget(0, len(_CURVA_SUBS))
        self.tbl.setHorizontalHeader(_GroupedHeader(
            _CURVA_SUBS, _CURVA_GROUPS,
            accent_cols={CC_P_MON, CC_P_EJE, CC_R_MON, CC_R_EJE,
                         CC_X_MON, CC_X_EJE}))
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setAlternatingRowColors(True)
        self.tbl.setEditTriggers(QAbstractItemView.DoubleClicked
                                 | QAbstractItemView.SelectedClicked
                                 | QAbstractItemView.AnyKeyPressed)
        self.tbl.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tbl.setStyleSheet(
            f"QTableWidget {{ background:white; alternate-background-color:{SILVER_100};"
            f" gridline-color:{SILVER_200}; font-size:11px; border:1px solid {SILVER_300}; }}"
            f"QTableWidget::item:selected {{ background:{SELECT_BG}; color:{SLATE_700}; }}"
            f"QTableWidget QLineEdit {{ color:{SLATE_700}; background:white;"
            f" border:1px solid {ORANGE}; padding:0 2px; selection-background-color:{ORANGE};"
            f" selection-color:white; }}")
        hdr = self.tbl.horizontalHeader()
        for c in range(len(_CURVA_SUBS)):
            hdr.setSectionResizeMode(c, QHeaderView.Fixed)
        self.tbl.setColumnWidth(CC_NUM, 30)
        self.tbl.setColumnWidth(CC_PER, 104)
        for c in (CC_P_MON, CC_R_MON, CC_X_MON):
            self.tbl.setColumnWidth(c, 88)
        for c in (CC_P_EJE, CC_P_ACU, CC_R_EJE, CC_R_ACU, CC_X_EJE, CC_X_ACU):
            self.tbl.setColumnWidth(c, 56)
        self.tbl.setColumnWidth(CC_DESV, 70)
        self.tbl.verticalHeader().setDefaultSectionSize(24)
        self.tbl.itemChanged.connect(self._on_celda_editada)

        # Contenedor inferior: tabla + fila TOTAL CONGELADA (siempre visible).
        tbot = QWidget()
        tl = QVBoxLayout(tbot); tl.setContentsMargins(0, 0, 0, 0); tl.setSpacing(0)
        tl.addWidget(self.tbl, stretch=1)
        self.tbl_total = QTableWidget(1, len(_CURVA_SUBS))
        self.tbl_total.horizontalHeader().setVisible(False)
        self.tbl_total.verticalHeader().setVisible(False)
        self.tbl_total.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl_total.setSelectionMode(QAbstractItemView.NoSelection)
        self.tbl_total.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tbl_total.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tbl_total.setFixedHeight(26)
        self.tbl_total.setStyleSheet(
            f"QTableWidget {{ background:{SILVER_200}; gridline-color:{SILVER_300};"
            f" font-size:11px; border:1px solid {SILVER_300}; border-top:none; }}")
        for c in range(len(_CURVA_SUBS)):
            self.tbl_total.horizontalHeader().setSectionResizeMode(c, QHeaderView.Fixed)
        self.tbl_total.verticalHeader().setDefaultSectionSize(24)
        tl.addWidget(self.tbl_total)

        self._split.addWidget(tbot)
        self._split.setStretchFactor(0, 3)
        self._split.setStretchFactor(1, 2)
        v.addWidget(self._split, stretch=1)

        hint = QLabel("Celdas en amarillo editables: «Período» (etiqueta) y el "
                      "«Monto» o «% Ejec» del período en Programado, Reprogramado y "
                      "Real (el % Acum se deriva). Real toma las valorizaciones; deja "
                      "vacío para volver al valor automático. La última fila agrega "
                      "un período.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{SLATE_300}; font-size:10px; background:transparent;"
                           " border:none;")
        v.addWidget(hint)

        self.lbl_vacio = QLabel("Aún no hay cronograma ni valorizaciones.\n"
            "Genera el cronograma y registra valorizaciones para comparar avance.")
        self.lbl_vacio.setAlignment(Qt.AlignCenter)
        self.lbl_vacio.setStyleSheet(f"color:{SLATE_300}; font-size:13px;"
            " font-weight:600; background:transparent; border:none;")
        self.lbl_vacio.hide()
        v.addWidget(self.lbl_vacio)

    # Anchos proporcionales: la tabla llena todo el ancho disponible (responsivo).
    _COL_PESOS = {CC_PER: 2.2, CC_P_MON: 1.5, CC_P_EJE: 1.0, CC_P_ACU: 1.0,
                  CC_R_MON: 1.5, CC_R_EJE: 1.0, CC_R_ACU: 1.0,
                  CC_X_MON: 1.5, CC_X_EJE: 1.0, CC_X_ACU: 1.0, CC_DESV: 1.1}

    def _ajustar_columnas(self):
        vp = self.tbl.viewport().width()
        if vp <= 0:
            return
        avail = max(0, vp - 30)
        items = [(c, w) for c, w in self._COL_PESOS.items()
                 if not self.tbl.isColumnHidden(c)]
        tot = sum(w for _, w in items) or 1
        acc = 0
        anchos = {CC_NUM: 30}
        for j, (c, w) in enumerate(items):
            wpx = (avail - acc) if j == len(items) - 1 else int(avail * w / tot)
            acc += wpx if j < len(items) - 1 else 0
            anchos[c] = max(46, wpx)
        for c, w in anchos.items():
            self.tbl.setColumnWidth(c, w)
            self.tbl_total.setColumnWidth(c, w)

    def _ajustar_alto(self):
        """La tabla se muestra completa hasta ~10 períodos (+ fila «nuevo»); con
        más aparece scroll. El gráfico ocupa el resto. La fila TOTAL va aparte
        (congelada), siempre visible."""
        rows = self.tbl.rowCount()
        row_h = self.tbl.verticalHeader().defaultSectionSize()
        hh = self.tbl.horizontalHeader().height() or 40
        cap = 11                                   # ~10 períodos + fila «nuevo»
        self.tbl.setVerticalScrollBarPolicy(
            Qt.ScrollBarAsNeeded if rows > cap else Qt.ScrollBarAlwaysOff)
        th = hh + min(max(rows, 1), cap) * row_h + 4
        total_h = self._split.height()
        if total_h <= 0:
            return
        bottom = th + self.tbl_total.height() + 2
        chart_h = max(180, total_h - bottom)
        self._split.setSizes([chart_h, total_h - chart_h])

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._ajustar_columnas()
        self._ajustar_alto()

    def _ocultar_cols(self, cols, on):
        for c in cols:
            self.tbl.setColumnHidden(c, not on)
            self.tbl_total.setColumnHidden(c, not on)

    def _toggle_prog(self, on):
        self.chart.set_show_prog(on)
        if hasattr(self, 'tbl'):
            self._ocultar_cols((CC_P_MON, CC_P_EJE, CC_P_ACU), on)
            self._ajustar_columnas()

    def _toggle_reprog(self, on):
        self.chart.set_show_reprog(on)
        if hasattr(self, 'tbl'):
            self._ocultar_cols((CC_R_MON, CC_R_EJE, CC_R_ACU), on)
            self._ajustar_columnas()

    def _toggle_real(self, on):
        self.chart.set_show_real(on)
        if hasattr(self, 'tbl'):
            self._ocultar_cols((CC_X_MON, CC_X_EJE, CC_X_ACU, CC_DESV), on)
            self._ajustar_columnas()

    def _on_periodo(self, idx):
        self._base = self._bases[idx] if 0 <= idx < len(self._bases) else 'mes'
        self.cargar()

    def _reporte(self, fmt='pdf'):
        if not _gate_reporte_editable(fmt, self):
            return
        import os
        from PySide6.QtWidgets import QFileDialog
        ext = {'pdf': 'pdf', 'docx': 'docx', 'odt': 'odt'}[fmt]
        filtro = {'pdf': 'PDF (*.pdf)', 'docx': 'Word (*.docx)',
                  'odt': 'LibreOffice (*.odt)'}[fmt]
        destino = os.path.join(_dir_reportes(), f"curva_s.{ext}")
        path, _ = QFileDialog.getSaveFileName(
            self, "Guardar Curva S", destino, filtro)
        if not path:
            return
        vis = {'prog': self.chk_prog.isChecked(),
               'reprog': self.chk_reprog.isChecked(),
               'real': self.chk_real.isChecked(),
               'pct': self.chk_pct.isChecked()}
        try:
            if fmt == 'pdf':
                from core import pdf_reports
                pdf_reports.generar_curva_s_pdf(self.pid, path, base=self._base, vis=vis)
            elif fmt == 'docx':
                from core import word_reports
                word_reports.generar_word_curva_s(self.pid, path, base=self._base, vis=vis)
            else:
                from core import odt_reports
                odt_reports.generar_odt_curva_s(self.pid, path, base=self._base, vis=vis)
            _guardar_dir_reportes(path)
            QMessageBox.information(self, "Reporte", f"Guardado en:\n{path}")
        except Exception as e:
            import traceback; traceback.print_exc()
            QMessageBox.critical(self, "Reporte",
                                 f"No se pudo generar el reporte:\n{e}")

    def _limpiar_reprog(self):
        if CS.get_overrides(self.pid, self._base) and \
           QMessageBox.question(self, "Restablecer curva",
               "¿Borrar los valores editados (etiqueta, programado y "
               "reprogramado) de esta base y volver a lo derivado del cronograma?"
               ) != QMessageBox.Yes:
            return
        CS.limpiar_reprogramacion(self.pid, self._base)
        self.cargar()

    def cargar(self):
        self.btn_limpiar.setEnabled(_co_editable(self._proy))  # editar solo en ejecución
        d = CS.curva_s_comparada(self.pid, self._base)
        self.chart.set_data(d)
        filas = d.get('filas', [])
        self._total_general = d['total_general']
        hay = (d['total_general'] > 0 or d.get('reales')
               or any(f['r_acu'] is not None for f in filas))
        self._loading = True
        self.tbl.setRowCount(0)
        if not hay:
            self._loading = False
            self.tbl.hide(); self.tbl_total.hide(); self.lbl_vacio.show()
            self.lbl_resumen.setText("")
            return
        self.tbl.show(); self.tbl_total.show(); self.lbl_vacio.hide()
        for f in filas:
            self._fila_curva(f)
        self._fila_curva(None, idx=len(filas) + 1)    # «＋ nuevo período» al final
        self._fila_total(filas)                       # sumatoria CONGELADA abajo
        self._loading = False
        self._ajustar_columnas()
        self._ajustar_alto()
        # Resumen: última fila con dato real.
        con_real = [f for f in filas if f['pct_real'] is not None]
        if con_real:
            u = con_real[-1]
            obj = u['pct_reprog'] if u['pct_reprog'] is not None else u['pct_prog']
            if obj is not None:
                dv = u['pct_real'] - obj
                estado = ("atraso" if dv < -1e-6 else "adelanto" if dv > 1e-6
                          else "en línea")
                ref = "reprog" if u['pct_reprog'] is not None else "prog"
                self.lbl_resumen.setText(
                    f"Real {u['pct_real']:.1f}% vs {ref} {obj:.1f}%  "
                    f"({dv:+.1f}% · {estado})")
            else:
                self.lbl_resumen.setText("")
        else:
            self.lbl_resumen.setText("")

    def _pct(self, v):
        return f"{v:.1f}%" if v is not None else ""

    def _mon(self, v):
        return fmt_num(v, self._proy.get('moneda', 'Soles')) if v is not None else ""

    def _fila_curva(self, r, idx=None):
        row = self.tbl.rowCount()
        self.tbl.insertRow(row)
        nuevo = r is None
        idx = idx if nuevo else r['idx']
        if nuevo:
            cells = [(CC_NUM, str(idx)), (CC_PER, "＋ nuevo período")]
            cells += [(c, "") for c in range(CC_P_MON, CC_DESV + 1)]
            desv = None
        else:
            desv = r['desviacion']
            cells = [
                (CC_NUM, str(idx)), (CC_PER, r['label']),
                (CC_P_MON, self._mon(r['p_mon'])), (CC_P_EJE, self._pct(r['p_eje'])),
                (CC_P_ACU, self._pct(r['p_acu'])),
                (CC_R_MON, self._mon(r['r_mon'])), (CC_R_EJE, self._pct(r['r_eje'])),
                (CC_R_ACU, self._pct(r['r_acu'])),
                (CC_X_MON, self._mon(r['x_mon'])), (CC_X_EJE, self._pct(r['x_eje'])),
                (CC_X_ACU, self._pct(r['x_acu'])),
                (CC_DESV, (f"{desv:+.1f}%" + ("⚠" if desv < -1e-6 else ""))
                          if desv is not None else ""),
            ]
        # Editables: Monto y % Ejec de Programado, Reprogramado y Real (+ etiqueta).
        editables = {CC_PER, CC_P_MON, CC_P_EJE, CC_R_MON, CC_R_EJE,
                     CC_X_MON, CC_X_EJE}
        for c, txt in cells:
            it = QTableWidgetItem(txt)
            if c >= CC_P_MON:
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            base_flags = Qt.ItemIsSelectable | Qt.ItemIsEnabled
            if c in editables and _co_editable(self._proy):
                it.setFlags(base_flags | Qt.ItemIsEditable)
                it.setData(Qt.UserRole, idx)
                it.setBackground(QColor(BANANA_SOFT))
            else:
                it.setFlags(base_flags)
            if c == CC_DESV and desv is not None:
                fnt = it.font(); fnt.setBold(True); it.setFont(fnt)
                it.setForeground(QColor(RED_700 if desv < -1e-6 else GREEN_700))
            self.tbl.setItem(row, c, it)

    def _fila_total(self, rows):
        def _suma(campo):
            vals = [r.get(campo) for r in rows if r.get(campo) is not None]
            return sum(vals) if vals else None

        def _ult(campo):
            vals = [r.get(campo) for r in rows if r.get(campo) is not None]
            return vals[-1] if vals else None

        cells = {
            CC_PER: "TOTAL",
            CC_P_MON: self._mon(_suma('p_mon')), CC_P_ACU: self._pct(_ult('p_acu')),
            CC_R_MON: self._mon(_suma('r_mon')), CC_R_ACU: self._pct(_ult('r_acu')),
            CC_X_MON: self._mon(_suma('x_mon')), CC_X_ACU: self._pct(_ult('x_acu')),
        }
        for c in range(len(_CURVA_SUBS)):
            it = QTableWidgetItem(cells.get(c, ""))
            it.setFlags(Qt.ItemIsEnabled)
            if c >= CC_P_MON:
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            fnt = it.font(); fnt.setBold(True); it.setFont(fnt)
            it.setForeground(QColor(SLATE_700))
            self.tbl_total.setItem(0, c, it)

    def _on_celda_editada(self, item):
        col = item.column()
        editables = (CC_PER, CC_P_MON, CC_P_EJE, CC_R_MON, CC_R_EJE,
                     CC_X_MON, CC_X_EJE)
        if self._loading or col not in editables:
            return
        idx = item.data(Qt.UserRole)
        if idx is None:
            return
        txt = (item.text() or "").strip()
        if col == CC_PER:
            CS.set_override(self.pid, self._base, idx, 'label', txt or None)
            self.cargar()
            return
        # Bloque según la columna; Monto se convierte a % de ejecución.
        campo = ('prog' if col in (CC_P_MON, CC_P_EJE)
                 else 'reprog' if col in (CC_R_MON, CC_R_EJE) else 'real')
        es_monto = col in (CC_P_MON, CC_R_MON, CC_X_MON)
        raw = txt.replace('%', '').replace(',', '.')
        for s in ('S/', 'S/.', '$', ' '):
            raw = raw.replace(s, '')
        if not raw:                       # celda vaciada → borra el override
            CS.set_override(self.pid, self._base, idx, campo, None)
            self.cargar()
            return
        try:
            num = float(raw)
        except ValueError:
            self.cargar()                 # texto inválido → recarga, no toca la BD
            return
        total = getattr(self, '_total_general', 0) or 0
        if es_monto and total <= 0:       # sin presupuesto no se puede convertir
            self.cargar()
            return
        valor = (num / total * 100.0) if es_monto else num
        CS.set_override(self.pid, self._base, idx, campo, valor)
        self.cargar()


class _RequerimientosPanel(QWidget):
    """Requerimientos: documentos numerados, UNO POR CATEGORÍA (combustibles,
    materiales de construcción, agregados, pinturas…). «Precargar del presupuesto»
    trae solo los insumos de esa categoría con su saldo pendiente."""

    def __init__(self, pid: int, proy: dict, parent=None):
        super().__init__(parent)
        self.pid = pid
        self._proy = proy
        self._req_id = None
        self._tipo = 'mat'
        self._loading = False
        self._presup_map = {}
        self._tab_ids = []
        self._tab_loading = False
        self._leaf_by_rid = {}   # recurso_id → hoja del árbol (para marcar checks)
        self._chk_ic = None
        self._acero_desglose = []   # [{diametro, kg, kg_ml, varillas}] del proyecto
        self._tdr_loading = False
        self._tdr_worker = None
        self._tdr_preview = False
        self._tdr_req_id = None   # a qué requerimiento pertenece el texto del editor
        self._build_ui()
        self._tdr_save_timer = QTimer(self)
        self._tdr_save_timer.setSingleShot(True)
        self._tdr_save_timer.setInterval(800)
        self._tdr_save_timer.timeout.connect(self._guardar_tdr_now)

    def _check_icon(self):
        """Icono de check verde (se incluye en algún requerimiento)."""
        if self._chk_ic is None:
            pm = QPixmap(16, 16); pm.fill(Qt.transparent)
            p = QPainter(pm); p.setRenderHint(QPainter.Antialiasing)
            pen = QPen(QColor(GREEN_700)); pen.setWidth(2)
            pen.setCapStyle(Qt.RoundCap); pen.setJoinStyle(Qt.RoundJoin)
            p.setPen(pen)
            p.drawLine(3, 8, 7, 12); p.drawLine(7, 12, 13, 4)
            p.end()
            self._chk_ic = QIcon(pm)
        return self._chk_ic

    def _marcar_arbol(self):
        """Marca con check (al final del nombre) los insumos del árbol ya
        incluidos en algún requerimiento (para ver de un vistazo cuáles faltan)."""
        incluidos = REQ.recursos_en_requerimientos(self.pid)
        for rid, leaf in self._leaf_by_rid.items():
            leaf.setData(0, Qt.UserRole + 1, rid in incluidos)
        self.tree.viewport().update()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 8); outer.setSpacing(6)
        split = QSplitter(Qt.Horizontal); split.setChildrenCollapsible(False)

        # IZQUIERDA — insumos del proyecto (arrastrables al requerimiento).
        left = QWidget(); lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0); lv.setSpacing(4)
        selrow = QHBoxLayout(); selrow.setSpacing(6)
        ll = QLabel("Insumos del proyecto")
        ll.setStyleSheet(f"color:{SLATE_700}; font-size:12px; font-weight:700;"
            " background:transparent; border:none;")
        selrow.addWidget(ll)
        # Pista de la acción, en la misma fila (antes de «Agrupar»).
        hint_top = QLabel("⇢ arrástralo al requerimiento o doble clic")
        hint_top.setStyleSheet(
            f"color:{ORANGE}; font-size:10px; font-weight:600; padding:2px 7px;"
            f" background:{SELECT_BG}; border:1px solid {ORANGE}; border-radius:5px;")
        selrow.addSpacing(6); selrow.addWidget(hint_top)
        selrow.addStretch()
        ag = QLabel("Agrupar:")
        ag.setStyleSheet(f"color:{SLATE_500}; font-size:10px;"
            " background:transparent; border:none;")
        selrow.addWidget(ag)
        self.cmb_grupo = QComboBox()
        self.cmb_grupo.addItem("Por categoría", "categoria")
        self.cmb_grupo.addItem("Por índice", "indice")
        self.cmb_grupo.setStyleSheet(
            f"QComboBox {{ border:1px solid {SILVER_300}; border-radius:6px;"
            f" padding:2px 8px; font-size:11px; background:white; }}")
        self.cmb_grupo.currentIndexChanged.connect(self._llenar_arbol)
        selrow.addWidget(self.cmb_grupo)
        lv.addLayout(selrow)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Insumo", "Und", "Cant."])
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.Fixed)
        self.tree.header().setSectionResizeMode(2, QHeaderView.Fixed)
        self.tree.header().setStretchLastSection(False)
        self.tree.setColumnWidth(1, 44)
        self.tree.setColumnWidth(2, 70)
        self.tree.setDragEnabled(True)
        self.tree.setDragDropMode(QAbstractItemView.DragOnly)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setItemDelegateForColumn(0, _CheckArbolDelegate(self))
        self.tree.setStyleSheet(
            f"QTreeWidget {{ background:white; border:1px solid {SILVER_300};"
            f" border-radius:6px; font-size:11px; }}"
            f"QTreeWidget::item {{ border-bottom:1px solid {SILVER_200};"
            f" padding:1px 0; }}"
            f"QTreeWidget::item:selected {{ background:{SELECT_BG};"
            f" color:{SLATE_700}; }}"
            f"QHeaderView::section {{ background:{SILVER_200}; color:{SLATE_700};"
            f" border:none; border-right:1px solid {SILVER_300};"
            f" border-bottom:1px solid {SILVER_300}; padding:2px 4px;"
            f" font-size:9px; font-weight:600; }}")
        self.tree.setToolTip(
            "Arrastra uno o varios insumos a la tabla del requerimiento (derecha),\n"
            "o haz doble clic para agregarlo. El ✓ marca los que ya incluiste.")
        self.tree.itemDoubleClicked.connect(self._on_tree_dbl)
        lv.addWidget(self.tree, stretch=1)
        legend = QLabel("✓  ya incluido en algún requerimiento")
        legend.setStyleSheet(f"color:{SLATE_300}; font-size:10px;"
            " background:transparent; border:none;")
        lv.addWidget(legend)
        split.addWidget(left)

        # DERECHA — el requerimiento.
        right = QWidget(); v = QVBoxLayout(right)
        v.setContentsMargins(0, 0, 0, 0); v.setSpacing(8)

        # Pestañas de requerimientos (Req N°1 · N°2 … · «+» para crear).
        self.tabbar = QTabBar()
        self.tabbar.setExpanding(False)
        self.tabbar.setDrawBase(False)
        self.tabbar.setStyleSheet(
            f"QTabBar::tab {{ background:{SILVER_200}; color:{SLATE_700};"
            f" padding:4px 12px; font-size:11px; font-weight:600;"
            f" border:1px solid {SILVER_300}; border-bottom:none;"
            f" border-top-left-radius:6px; border-top-right-radius:6px; }}"
            f"QTabBar::tab:selected {{ background:{ORANGE}; color:white; }}")
        self.tabbar.tabBarClicked.connect(self._on_tab_clicked)
        self.tabbar.currentChanged.connect(self._on_tab_changed)
        self.tabbar.tabBarDoubleClicked.connect(self._on_tab_dbl)
        self.tabbar.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tabbar.customContextMenuRequested.connect(self._menu_tab)
        trow = QHBoxLayout(); trow.setSpacing(6)
        trow.addWidget(self.tabbar); trow.addStretch()
        self.lbl_estado = QLabel("")
        self.lbl_estado.setStyleSheet("background:transparent; border:none;"
                                      " font-size:11px; font-weight:700;")
        trow.addWidget(self.lbl_estado)
        v.addLayout(trow)

        def _btn(txt, fn):
            b = QPushButton(txt); b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(
                f"QPushButton {{ background:white; color:{SLATE_700};"
                f" border:1px solid {SILVER_300}; border-radius:6px;"
                f" font-size:11px; padding:5px 10px; }}"
                f"QPushButton:hover {{ background:{SILVER_200}; }}"
                f"QPushButton:disabled {{ color:{SLATE_300}; }}")
            if fn is not None:
                b.clicked.connect(fn)
            return b

        brow = QHBoxLayout(); brow.setSpacing(6)
        self.btn_cerrar = _btn("Cerrar", self._cerrar_reabrir)
        self.btn_elim = _btn("Eliminar", self._eliminar)
        brow.addWidget(self.btn_cerrar)
        brow.addWidget(self.btn_elim); brow.addStretch()
        self.lbl_cat = QLabel("")
        self.lbl_cat.setStyleSheet(f"color:{SLATE_700}; font-size:12px;"
            " font-weight:700; background:transparent; border:none;")
        brow.addWidget(self.lbl_cat)
        v.addLayout(brow)

        # Tabla única (la categoría ya agrupa). Encabezado sticky nativo. Acepta
        # insumos arrastrados desde el árbol de la izquierda.
        self.tbl = _ReqTable(0, len(_REQ_COLS))
        self.tbl.on_drop = self._add_recursos
        self.tbl.setHorizontalHeaderLabels(_REQ_COLS)
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.horizontalHeader().setSectionResizeMode(REQ_DESC, QHeaderView.Stretch)
        self.tbl.setColumnWidth(REQ_ITEM, 34)
        self.tbl.setColumnWidth(REQ_UND, 50)
        self.tbl.setColumnWidth(REQ_PRES, 84)
        self.tbl.setColumnWidth(REQ_REQ, 90)
        self.tbl.verticalHeader().setDefaultSectionSize(22)
        self.tbl.setEditTriggers(QAbstractItemView.DoubleClicked
                                 | QAbstractItemView.SelectedClicked
                                 | QAbstractItemView.AnyKeyPressed)
        deleg = _MetCellDelegate(self.tbl)
        for c in range(len(_REQ_COLS)):
            self.tbl.setItemDelegateForColumn(c, deleg)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tbl.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tbl.setAlternatingRowColors(True)
        self.tbl.on_copy = lambda: self._copiar()
        self.tbl.on_delete = lambda: self._eliminar_filas()
        self.tbl.itemChanged.connect(self._on_item)
        self.tbl.customContextMenuRequested.connect(self._menu)
        # Mismo estilo que las grillas de Valorizaciones/Cuaderno: encabezado
        # claro (gris) + filas alternas.
        self.tbl.setStyleSheet(
            f"QTableWidget {{ background:white; alternate-background-color:{SILVER_100};"
            f" gridline-color:{SILVER_200}; font-size:11px; }}"
            f"QHeaderView::section {{ background:{SILVER_200}; color:{SLATE_700};"
            f" border:none; border-right:1px solid {SILVER_300};"
            f" border-bottom:1px solid {SILVER_300}; padding:3px; font-weight:600; }}"
            f"QTableWidget::item:selected {{ background:{SELECT_BG};"
            f" color:{SLATE_700}; }}")

        # ── Editor de TDR / Especificaciones Técnicas (generado por IA) ──────
        tdr_box = QWidget(); tdr_box.setObjectName("tdrbox")
        tv = QVBoxLayout(tdr_box)
        tv.setContentsMargins(0, 0, 0, 0); tv.setSpacing(4)
        thdr = QHBoxLayout(); thdr.setSpacing(6)
        ltdr = QLabel("Términos de Referencia / Especificaciones Técnicas")
        ltdr.setStyleSheet(f"color:{SLATE_700}; font-size:12px; font-weight:700;"
            " background:transparent; border:none;")
        thdr.addWidget(ltdr); thdr.addStretch()
        self.lbl_tdr_estado = QLabel("")
        self.lbl_tdr_estado.setStyleSheet(f"color:{SLATE_500}; font-size:10px;"
            " background:transparent; border:none;")
        thdr.addWidget(self.lbl_tdr_estado)
        self.btn_tdr_prev = _btn("👁 Vista previa", self._toggle_tdr_prev)
        self.btn_tdr = _btn("✨ Generar con IA", self._generar_tdr)
        self.btn_tdr.setStyleSheet(
            f"QPushButton {{ background:{ORANGE}; color:white; border:none;"
            f" border-radius:6px; font-size:11px; padding:5px 12px; font-weight:600; }}"
            f"QPushButton:hover {{ background:#E0631F; }}"
            f"QPushButton:disabled {{ background:{SILVER_300}; color:white; }}")
        self.btn_tdr_pdf = _btn("📄 Reporte", None)
        _rm_tdr = QMenu(self.btn_tdr_pdf)
        _rm_tdr.addAction("PDF", lambda: self._exportar_tdr('pdf'))
        _rm_tdr.addAction("Word (.docx)", lambda: self._exportar_tdr('docx'))
        _rm_tdr.addAction("LibreOffice (.odt)", lambda: self._exportar_tdr('odt'))
        self.btn_tdr_pdf.setMenu(_rm_tdr)
        thdr.addWidget(self.btn_tdr_prev)
        thdr.addWidget(self.btn_tdr); thdr.addWidget(self.btn_tdr_pdf)
        tv.addLayout(thdr)
        self.txt_tdr = QPlainTextEdit()
        self.txt_tdr.setPlaceholderText(
            "Aún no hay TDR. Pulsa «✨ Generar con IA»: la IA redacta el "
            "requerimiento y los términos de referencia / especificaciones "
            "técnicas a partir de los insumos. Luego puedes editarlo aquí mismo.")
        self.txt_tdr.setStyleSheet(
            f"QPlainTextEdit {{ background:white; color:{SLATE_700};"
            f" border:1px solid {SILVER_300}; border-radius:6px; padding:6px;"
            f" font-family:'DejaVu Sans Mono','Consolas',monospace; font-size:11px; }}")
        self.txt_tdr.textChanged.connect(self._on_tdr_changed)
        self._tdr_hl = _TdrHighlighter(self.txt_tdr.document())
        tv.addWidget(self.txt_tdr, 1)
        # Vista previa (solo lectura) con el mismo render del PDF: cuadro de
        # tabla + negritas. Oculta hasta que el usuario pulse «Vista previa».
        self.txt_tdr_prev = QTextBrowser()
        self.txt_tdr_prev.setStyleSheet(
            f"QTextBrowser {{ background:white; color:{SLATE_700};"
            f" border:1px solid {SILVER_300}; border-radius:6px; padding:6px; }}")
        self.txt_tdr_prev.hide()
        tv.addWidget(self.txt_tdr_prev, 1)

        vsplit = QSplitter(Qt.Vertical); vsplit.setChildrenCollapsible(False)
        vsplit.addWidget(self.tbl)
        vsplit.addWidget(tdr_box)
        vsplit.setStretchFactor(0, 3); vsplit.setStretchFactor(1, 2)
        vsplit.setSizes([380, 240])
        self.vsplit = vsplit
        v.addWidget(vsplit, stretch=1)

        self.lbl_vacio = QLabel(
            "Sin requerimientos. Crea el primero con «+ Nuevo requerimiento» "
            "(eliges la categoría) y precarga los insumos del presupuesto.")
        self.lbl_vacio.setAlignment(Qt.AlignCenter); self.lbl_vacio.setWordWrap(True)
        self.lbl_vacio.setStyleSheet(f"color:{SLATE_300}; font-size:13px;"
            " background:transparent; border:none;")
        self.lbl_vacio.hide()
        # stretch=1: ocupa el espacio que dejaba el vsplit cuando no hay
        # requerimientos, de modo que las pestañas/botones queden fijos arriba
        # (antes se reacomodaban al medio al ocultar el vsplit).
        v.addWidget(self.lbl_vacio, stretch=1)

        split.addWidget(right)
        split.setSizes([300, 660])
        outer.addWidget(split)

    # ── Insumos del proyecto (panel izquierdo) ───────────────────────────────

    def _llenar_arbol(self):
        por = self.cmb_grupo.currentData() or 'categoria'
        self.tree.clear()
        self._leaf_by_rid = {}
        for grupo, insumos in REQ.insumos_arbol(self.pid, por):
            g = QTreeWidgetItem([f"{grupo}  ({len(insumos)})"])
            g.setFlags(Qt.ItemIsEnabled)
            fb = g.font(0); fb.setBold(True); g.setFont(0, fb)
            g.setForeground(0, QColor(SLATE_700))
            self.tree.addTopLevelItem(g)
            for x in insumos:
                leaf = QTreeWidgetItem([x['descripcion'], x['unidad'] or '',
                                        _numtxt(x['cantidad'])])
                leaf.setTextAlignment(1, Qt.AlignCenter)
                leaf.setTextAlignment(2, Qt.AlignRight | Qt.AlignVCenter)
                leaf.setData(0, Qt.UserRole, x)
                leaf.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable
                              | Qt.ItemIsDragEnabled)
                g.addChild(leaf)
                rid = x.get('recurso_id')
                if rid is not None:
                    self._leaf_by_rid[rid] = leaf
        self.tree.expandAll()   # desplegado por defecto (el usuario contrae si quiere)
        self._marcar_arbol()

    def _on_tree_dbl(self, item, _col):
        d = item.data(0, Qt.UserRole)
        if d:
            self._add_recursos([d])

    def _add_recursos(self, datos):
        """Agrega insumos (arrastrados o doble-clic) al requerimiento activo."""
        if not self._req_abierto():
            QMessageBox.information(self, "Requerimiento",
                "Crea o selecciona un requerimiento ABIERTO para agregar insumos.")
            return
        existentes = set()
        for r in range(self.tbl.rowCount()):
            it0 = self.tbl.item(r, REQ_DESC)
            rid = it0.data(Qt.UserRole) if it0 else None
            if rid is not None:
                existentes.add(rid)
        self._loading = True
        self.tbl.blockSignals(True)
        # Quitar la fila vacía del final para insertar antes de re-crearla.
        last = self.tbl.rowCount() - 1
        if last >= 0 and not self._fila_no_vacia(last):
            self.tbl.removeRow(last)
        nuevos = 0
        for x in datos:
            rid = x.get('recurso_id')
            if rid is not None and rid in existentes:
                continue
            existentes.add(rid)
            self._fila({'recurso_id': rid, 'descripcion': x.get('descripcion'),
                        'unidad': x.get('unidad'),
                        'cantidad': REQ.redondear_para_pedido(
                            x.get('cantidad'), x.get('unidad'))},
                       True)
            nuevos += 1
        self._fila({}, True)   # fila vacía al final
        self.tbl.blockSignals(False)
        self._loading = False
        self._renumerar()
        if nuevos:
            self._guardar()
            # Si se agregó acero, recargar para pintar sus sub-filas por diámetro.
            if self._acero_desglose and any(
                    AR._es_acero(x.get('descripcion')) for x in datos):
                self._refrescar()

    # ── Carga ──────────────────────────────────────────────────────────────────

    def cargar(self):
        self._presup_map = REQ.presupuesto_por_recurso(self.pid)
        self._acero_desglose = REQ.acero_varillas_por_diametro(self.pid)
        self._llenar_arbol()
        self._recargar_lista()

    def _recargar_lista(self):
        prev = self._req_id
        self._tab_loading = True
        self.tabbar.blockSignals(True)
        while self.tabbar.count():
            self.tabbar.removeTab(0)
        self._tab_ids = []
        reqs = REQ.listar_requerimientos(self.pid)
        for q in reqs:
            cat = (q.get('categoria') or '').strip()
            lock = " 🔒" if q['estado'] == 'cerrado' else ""
            self.tabbar.addTab(f"N°{q['numero']}  {cat}{lock}".rstrip())
            self._tab_ids.append(q['id'])
        self.tabbar.addTab("  +  ")   # nueva
        self.tabbar.setTabToolTip(self.tabbar.count() - 1, "Nuevo requerimiento")
        self.tabbar.blockSignals(False)
        self._tab_loading = False
        vac = (len(reqs) == 0)
        self.vsplit.setVisible(not vac)
        self.lbl_cat.setVisible(not vac)
        self.lbl_vacio.setVisible(vac)
        if vac:
            self._flush_tdr()
            self._req_id = None
            self._tdr_loading = True
            self.txt_tdr.setPlainText("")
            self._tdr_req_id = None
            self._tdr_loading = False
            self._sync_botones(None)
            self._marcar_arbol()
            return
        idx = self._tab_ids.index(prev) if prev in self._tab_ids \
            else len(self._tab_ids) - 1
        self.tabbar.blockSignals(True)
        self.tabbar.setCurrentIndex(idx)
        self.tabbar.blockSignals(False)
        self._req_id = self._tab_ids[idx]
        self._refrescar()

    def _on_tab_clicked(self, idx):
        if idx == self.tabbar.count() - 1:   # la pestaña «+»
            self._nuevo()

    def _on_tab_changed(self, idx):
        if self._tab_loading:
            return
        self._flush_tdr()   # guarda el TDR del requerimiento que dejamos
        if 0 <= idx < len(self._tab_ids):
            self._req_id = self._tab_ids[idx]
            self._refrescar()

    def _on_tab_dbl(self, idx):
        if 0 <= idx < len(self._tab_ids):
            self._renombrar(self._tab_ids[idx])

    def _menu_tab(self, pos):
        idx = self.tabbar.tabAt(pos)
        if not (0 <= idx < len(self._tab_ids)):
            return
        req_id = self._tab_ids[idx]
        m = QMenu(self)
        ar = m.addAction("Renombrar categoría…")
        m.addSeparator()
        ae = m.addAction("Eliminar requerimiento")
        ch = m.exec(self.tabbar.mapToGlobal(pos))
        if ch == ar:
            self._renombrar(req_id)
        elif ch == ae:
            self._req_id = req_id
            self._eliminar()

    def _renombrar(self, req_id):
        if not _co_editable(self._proy):
            return
        q = REQ.get_requerimiento(req_id)
        if not q:
            return
        if q['estado'] == 'cerrado':
            QMessageBox.information(self, "Renombrar",
                "El requerimiento está cerrado. Reábrelo para renombrarlo.")
            return
        dlg = _RenombrarReqDialog(clasificador.CATEGORIAS,
                                  q.get('categoria') or '', self)
        if dlg.exec() != QDialog.Accepted:
            return
        REQ.set_categoria(req_id, dlg.valor())
        self._req_id = req_id
        self._recargar_lista()

    def _refrescar(self):
        if not self._req_id:
            return
        q = REQ.get_requerimiento(self._req_id)
        # Editable solo si el requerimiento está abierto Y la obra «En ejecución».
        abierto = bool(q and q['estado'] == 'abierto') and _co_editable(self._proy)
        cat = (q.get('categoria') or '') if q else ''
        self._tipo = REQ.tipo_de_requerimiento(q) if q else 'mat'
        _tlbl = {'mat': 'materiales', 'eq': 'equipos', 'sc': 'servicios'}
        self.lbl_cat.setText(f"Categoría:  {cat or '(sin categoría)'}"
                             f"   ·   {_tlbl.get(self._tipo, '')}")
        filas = REQ.get_detalle(self._req_id, self._tipo)
        self._llenar(filas, abierto)
        self._sync_botones(q['estado'] if q else None)
        self._marcar_arbol()
        # Cargar el TDR guardado en el editor (sin disparar el autoguardado).
        self._tdr_loading = True
        self.txt_tdr.setPlainText((q.get('tdr') or '') if q else '')
        self._tdr_req_id = self._req_id
        self._tdr_loading = False
        self.txt_tdr.setReadOnly(not abierto)   # editor TDR solo en «En ejecución»
        self.tree.setDragEnabled(abierto)       # arrastrar insumos solo si editable
        tiene_tdr = bool((q.get('tdr') or '').strip() if q else False)
        self.btn_tdr_pdf.setEnabled(tiene_tdr)  # exportar TDR: siempre
        self.btn_tdr.setEnabled(self._tdr_worker is None and abierto)  # generar IA
        # Por defecto se muestra la vista previa (el render tipo PDF de los
        # términos de referencia / especificaciones técnicas). Si aún no hay TDR
        # se deja el editor para que se vea el placeholder y el botón «Generar».
        if tiene_tdr:
            self._mostrar_tdr_preview()
        else:
            self._mostrar_tdr_editor()

    # ── TDR / Especificaciones técnicas ─────────────────────────────────────

    def _on_tdr_changed(self):
        if self._tdr_loading:
            return
        self._tdr_save_timer.start()   # autoguardado con rebote

    def _toggle_tdr_prev(self):
        if self._tdr_preview:
            self._mostrar_tdr_editor()
        else:
            self._mostrar_tdr_preview()

    def _mostrar_tdr_preview(self):
        # Pasar a vista previa: guardar lo pendiente y renderizar como el PDF.
        self._flush_tdr()
        try:
            from core import pdf_reports
            body = pdf_reports._html_tdr(self.txt_tdr.toPlainText())
        except Exception:   # noqa: BLE001
            from html import escape as _esc
            body = "<pre>" + _esc(self.txt_tdr.toPlainText()) + "</pre>"
        # Misma tipografía proporcional que el PDF/Especificaciones (Inter) para
        # que la vista previa coincida con el reporte.
        self.txt_tdr_prev.setHtml(
            "<html><body style=\"font-family:'Inter','DejaVu Sans','Segoe UI',"
            f"Arial,sans-serif; color:{SLATE_700}; line-height:1.5;\">"
            f"{body}</body></html>")
        self.txt_tdr.hide(); self.txt_tdr_prev.show()
        self.btn_tdr_prev.setText("✏ Editar")
        self._tdr_preview = True

    def _mostrar_tdr_editor(self):
        self.txt_tdr_prev.hide(); self.txt_tdr.show()
        self.btn_tdr_prev.setText("👁 Vista previa")
        self._tdr_preview = False

    def _guardar_tdr_now(self):
        if self._tdr_req_id is not None:
            REQ.guardar_tdr(self._tdr_req_id, self.txt_tdr.toPlainText())
            self.btn_tdr_pdf.setEnabled(bool(self.txt_tdr.toPlainText().strip()))

    def _flush_tdr(self):
        """Guarda de inmediato si hay un autoguardado pendiente (antes de cambiar
        de requerimiento, para no escribir en el equivocado)."""
        if self._tdr_save_timer.isActive():
            self._tdr_save_timer.stop()
            self._guardar_tdr_now()

    def _generar_tdr(self):
        if self._req_id is None:
            return
        if self._tdr_worker is not None:
            return
        filas = REQ.get_detalle(self._req_id, self._tipo)
        if not any((f.get('descripcion') or '').strip() for f in filas):
            QMessageBox.information(self, "Generar TDR",
                "El requerimiento no tiene insumos. Agrega al menos uno antes de "
                "generar el TDR / especificaciones técnicas.")
            return
        if self.txt_tdr.toPlainText().strip():
            if QMessageBox.question(self, "Generar TDR",
                "Ya hay un TDR. ¿Reemplazarlo con uno nuevo generado por la IA?"
            ) != QMessageBox.Yes:
                return
        dlg = _DatosTDRDialog(self._req_id, self)
        if dlg.exec() != QDialog.Accepted:
            return
        datos = dlg.valores()
        self._flush_tdr()
        self.btn_tdr.setEnabled(False)
        self.lbl_tdr_estado.setText("Generando con IA…  ⏳")
        self._tdr_worker = _TDRWorker(self._req_id, datos)
        self._tdr_worker.done.connect(self._on_tdr_generado)
        self._tdr_worker.start()

    def _on_tdr_generado(self, req_id, texto, error):
        self._tdr_worker = None
        self.btn_tdr.setEnabled(True)
        self.lbl_tdr_estado.setText("")
        if error:
            QMessageBox.warning(self, "Generar TDR", error)
            return
        # Mostrar solo si seguimos en el mismo requerimiento.
        if req_id == self._req_id:
            self._tdr_loading = True
            self.txt_tdr.setPlainText(texto or '')
            self._tdr_req_id = req_id
            self._tdr_loading = False
            self.btn_tdr_pdf.setEnabled(bool((texto or '').strip()))
            # Recién generado: abrir directamente la vista previa (render PDF).
            if (texto or '').strip():
                self._mostrar_tdr_preview()
            else:
                self._mostrar_tdr_editor()
        self.lbl_tdr_estado.setText("✓ Generado")
        QTimer.singleShot(2500, lambda: self.lbl_tdr_estado.setText(""))

    def _exportar_tdr(self, fmt='pdf'):
        if self._req_id is None:
            return
        texto = self.txt_tdr.toPlainText().strip()
        if not texto:
            QMessageBox.information(self, "Exportar",
                "No hay TDR para exportar. Genéralo primero con la IA.")
            return
        if not _gate_reporte_editable(fmt, self):
            return
        self._flush_tdr()
        import os
        from PySide6.QtWidgets import QFileDialog
        q = REQ.get_requerimiento(self._req_id)
        ext = {'pdf': 'pdf', 'docx': 'docx', 'odt': 'odt'}[fmt]
        filtro = {'pdf': 'PDF (*.pdf)', 'docx': 'Word (*.docx)',
                  'odt': 'LibreOffice (*.odt)'}[fmt]
        sug = f"TDR_Req_N{q['numero']}.{ext}" if q else f"TDR.{ext}"
        destino = os.path.join(_dir_reportes(), sug)
        ruta, _ = QFileDialog.getSaveFileName(
            self, "Exportar Requerimiento / TDR", destino, filtro)
        if not ruta:
            return
        if not ruta.lower().endswith('.' + ext):
            ruta += '.' + ext
        try:
            if fmt == 'pdf':
                from core import pdf_reports
                pdf_reports.generar_tdr_pdf(ruta, self._req_id)
            elif fmt == 'docx':
                from core import word_reports
                word_reports.generar_word_tdr(self._req_id, ruta)
            else:
                from core import odt_reports
                odt_reports.generar_odt_tdr(self._req_id, ruta)
            _guardar_dir_reportes(ruta)
            QMessageBox.information(self, "Exportar", f"Guardado en:\n{ruta}")
        except Exception as e:  # noqa: BLE001
            import traceback; traceback.print_exc()
            QMessageBox.warning(self, "Exportar", f"No se pudo exportar:\n{e}")

    def _llenar(self, filas, abierto):
        self._loading = True
        self.tbl.blockSignals(True); self.tbl.setRowCount(0)
        for f in filas:
            self._fila(f, abierto)
            # Bajo la línea de acero corrugado: sub-filas por diámetro (varillas
            # de 9 m), solo lectura, calculadas de la planilla de acero.
            if self._acero_desglose and AR._es_acero(f.get('descripcion')):
                for x in self._acero_desglose:
                    self._fila_acero_sub(x['diametro'], x['varillas'])
        if abierto:
            self._fila({}, abierto)
        self.tbl.blockSignals(False)
        self._loading = False
        self._renumerar()

    def _fila_acero_sub(self, diametro, varillas):
        """Fila informativa (solo lectura) del acero por diámetro en varillas."""
        r = self.tbl.rowCount(); self.tbl.insertRow(r)
        gris = QColor(SLATE_500)
        iti = QTableWidgetItem("")
        iti.setData(Qt.UserRole, '_acero_sub')   # marca de sub-fila (se omite)
        iti.setFlags(Qt.ItemIsEnabled)
        self.tbl.setItem(r, REQ_ITEM, iti)
        it0 = QTableWidgetItem(f"      ↳ Ø {diametro}")
        it1 = QTableWidgetItem("VAR")
        it1.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
        it2 = QTableWidgetItem("")
        it3 = QTableWidgetItem(str(varillas))
        it3.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        for it in (it0, it1, it2, it3):
            it.setForeground(gris)
            f = it.font(); f.setItalic(True); it.setFont(f)
            it.setFlags(Qt.ItemIsEnabled)   # ni editable ni seleccionable
        self.tbl.setItem(r, REQ_DESC, it0)
        self.tbl.setItem(r, REQ_UND, it1)
        self.tbl.setItem(r, REQ_PRES, it2)
        self.tbl.setItem(r, REQ_REQ, it3)

    def _es_subfila(self, r):
        it = self.tbl.item(r, REQ_ITEM)
        return bool(it and it.data(Qt.UserRole) == '_acero_sub')

    def _renumerar(self):
        """Numera la columna «#» según los recursos (las filas con datos); la fila
        vacía del final queda sin número."""
        self._loading = True
        self.tbl.blockSignals(True)
        n = 0
        for r in range(self.tbl.rowCount()):
            if self._es_subfila(r):
                continue
            it = self.tbl.item(r, REQ_ITEM)
            if it is None:
                continue
            if self._fila_no_vacia(r):
                n += 1
                it.setText(str(n))
            else:
                it.setText("")
        self.tbl.blockSignals(False)
        self._loading = False

    def _fila(self, f, abierto):
        r = self.tbl.rowCount(); self.tbl.insertRow(r)
        rid = f.get('recurso_id')
        presup = self._presup_map.get(rid) if rid is not None else None
        iti = QTableWidgetItem("")
        iti.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
        iti.setForeground(QColor(SLATE_500))
        iti.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        self.tbl.setItem(r, REQ_ITEM, iti)
        it0 = QTableWidgetItem(f.get('descripcion') or '')
        if rid is not None:
            it0.setData(Qt.UserRole, rid)
        it1 = QTableWidgetItem(f.get('unidad') or '')
        it1.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
        it2 = QTableWidgetItem(_numtxt(presup) if presup else '')
        it2.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        it2.setForeground(QColor(SLATE_500))
        cant = f.get('cantidad')
        it3 = QTableWidgetItem(_numtxt(cant) if cant else '')
        it3.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        fb = it3.font(); fb.setBold(True); it3.setFont(fb)
        for c, it, ed in ((REQ_DESC, it0, True), (REQ_UND, it1, True),
                          (REQ_PRES, it2, False), (REQ_REQ, it3, True)):
            flags = Qt.ItemIsSelectable | Qt.ItemIsEnabled
            if abierto and ed:
                flags |= Qt.ItemIsEditable
            it.setFlags(flags)
            self.tbl.setItem(r, c, it)

    def _leer(self, r):
        def txt(c):
            it = self.tbl.item(r, c); return it.text().strip() if it else ''
        it0 = self.tbl.item(r, REQ_DESC)
        rid = it0.data(Qt.UserRole) if it0 else None
        ct = txt(REQ_REQ); cant = None
        if ct:
            try:
                cant = parse_num(ct)
            except (TypeError, ValueError):
                cant = None
        return {'recurso_id': rid, 'descripcion': txt(REQ_DESC),
                'unidad': txt(REQ_UND), 'cantidad': cant}

    def _fila_no_vacia(self, r):
        f = self._leer(r)
        return bool((f['descripcion'] or '').strip() or f['cantidad'])

    # ── Edición ────────────────────────────────────────────────────────────────

    def _on_item(self, item):
        if self._loading:
            return
        last = self.tbl.rowCount() - 1
        if item.row() == last and self._fila_no_vacia(last):
            self._loading = True; self.tbl.blockSignals(True)
            self._fila({}, True)
            self.tbl.blockSignals(False); self._loading = False
        self._renumerar()
        self._guardar()

    def _guardar(self):
        if self._req_id is None:
            return
        # Las sub-filas de acero (solo lectura) NO son detalle: se omiten.
        filas = [self._leer(r) for r in range(self.tbl.rowCount())
                 if not self._es_subfila(r)]
        REQ.save_detalle(self._req_id, self._tipo, filas)
        self._marcar_arbol()

    def _req_abierto(self):
        q = REQ.get_requerimiento(self._req_id) if self._req_id else None
        return bool(q and q['estado'] == 'abierto') and _co_editable(self._proy)

    def _agregar_fila(self):
        if not self._req_abierto():
            return
        last = self.tbl.rowCount() - 1
        if last < 0 or self._fila_no_vacia(last):
            self._loading = True; self.tbl.blockSignals(True)
            self._fila({}, True)
            self.tbl.blockSignals(False); self._loading = False
            last = self.tbl.rowCount() - 1
        it = self.tbl.item(last, REQ_DESC)
        if it is not None:
            self.tbl.scrollToItem(it); self.tbl.setCurrentItem(it)
            self.tbl.editItem(it)

    def _eliminar_filas(self):
        if not self._req_abierto():
            return
        rows = sorted({i.row() for i in self.tbl.selectedItems()
                       if not self._es_subfila(i.row())}, reverse=True)
        if not rows and self.tbl.currentRow() >= 0 \
                and not self._es_subfila(self.tbl.currentRow()):
            rows = [self.tbl.currentRow()]
        if not rows:
            return
        self._loading = True; self.tbl.blockSignals(True)
        for r in rows:
            self.tbl.removeRow(r)
        if self.tbl.rowCount() == 0 or self._fila_no_vacia(self.tbl.rowCount() - 1):
            self._fila({}, True)
        self.tbl.blockSignals(False); self._loading = False
        self._renumerar()
        self._guardar()

    def _copiar(self):
        rows = sorted({i.row() for i in self.tbl.selectedItems()})
        if not rows and self.tbl.currentRow() >= 0:
            rows = [self.tbl.currentRow()]
        lineas = []
        for r in rows:
            cells = [(self.tbl.item(r, c).text() if self.tbl.item(r, c) else "")
                     for c in range(self.tbl.columnCount())]
            if any(c.strip() for c in cells):
                lineas.append("\t".join(cells))
        if lineas:
            QApplication.clipboard().setText("\n".join(lineas))

    def _menu(self, pos):
        m = QMenu(self)
        ac = m.addAction("Copiar")
        aa = ae = None
        if self._req_abierto():
            aa = m.addAction("Agregar fila")
            m.addSeparator()
            ae = m.addAction("Eliminar fila(s)")
        ch = m.exec(self.tbl.viewport().mapToGlobal(pos))
        if ch is None:
            return
        if ch == ac:
            self._copiar()
        elif ch == aa:
            self._agregar_fila()
        elif ch == ae:
            self._eliminar_filas()

    # ── Acciones ───────────────────────────────────────────────────────────────

    def _sync_botones(self, estado):
        cerrado = (estado == 'cerrado')
        co = _co_editable(self._proy)
        self.btn_cerrar.setText("Reabrir" if cerrado else "Cerrar")
        self.btn_cerrar.setEnabled(estado is not None and co)
        self.btn_elim.setEnabled(estado == 'abierto' and co)
        if estado is None:
            self.lbl_estado.setText("")
        elif cerrado:
            self.lbl_estado.setText("🔒 CERRADO")
            self.lbl_estado.setStyleSheet("background:transparent; border:none;"
                f" font-size:11px; font-weight:700; color:{RED_700};")
        else:
            self.lbl_estado.setText("● ABIERTO")
            self.lbl_estado.setStyleSheet("background:transparent; border:none;"
                f" font-size:11px; font-weight:700; color:{GREEN_700};")

    def _nuevo(self):
        prev = self._req_id
        if not _co_editable(self._proy):
            # No se pueden crear requerimientos fuera de «En ejecución».
            if prev in self._tab_ids:
                self.tabbar.blockSignals(True)
                self.tabbar.setCurrentIndex(self._tab_ids.index(prev))
                self.tabbar.blockSignals(False)
            return
        dlg = _NuevoReqDialog(clasificador.CATEGORIAS, self)
        if dlg.exec() != QDialog.Accepted:
            # Volver de la pestaña «+» al requerimiento previo.
            if prev in self._tab_ids:
                self.tabbar.blockSignals(True)
                self.tabbar.setCurrentIndex(self._tab_ids.index(prev))
                self.tabbar.blockSignals(False)
            return
        fecha, cat, vacio = dlg.valores()
        self._req_id = REQ.crear_requerimiento(self.pid, fecha, cat)
        if not vacio:
            REQ.precargar_saldo(self._req_id)   # precarga la categoría elegida
        self._recargar_lista()                  # reconstruye pestañas + selecciona

    def _cerrar_reabrir(self):
        if not self._req_id:
            return
        q = REQ.get_requerimiento(self._req_id)
        if q['estado'] == 'cerrado':
            REQ.reabrir_requerimiento(self._req_id)
        else:
            if QMessageBox.question(self, "Cerrar requerimiento",
                "Al cerrar queda congelado (no editable). ¿Continuar?"
            ) != QMessageBox.Yes:
                return
            REQ.cerrar_requerimiento(self._req_id)
        self._refrescar()

    def _eliminar(self):
        if not self._req_id or not _co_editable(self._proy):
            return
        q = REQ.get_requerimiento(self._req_id)
        if QMessageBox.question(self, "Eliminar requerimiento",
            f"¿Eliminar el Requerimiento N°{q['numero']}?"
        ) != QMessageBox.Yes:
            return
        if not REQ.eliminar_requerimiento(self._req_id):
            QMessageBox.warning(self, "Eliminar",
                "No se pudo eliminar. Si está cerrado, reábrelo primero.")
            return
        self._req_id = None
        self._recargar_lista()


class _NuevoReqDialog(QDialog):
    """Nuevo requerimiento: categoría + fecha + opción «crear vacío».

    Por defecto precarga del presupuesto los insumos de la categoría con saldo
    pendiente. Marcando «Crear vacío» se crea sin nada — útil para armar a mano un
    requerimiento individual (un servicio o una maquinaria por documento)."""

    def __init__(self, categorias, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Nuevo requerimiento")
        self.setWindowModality(Qt.WindowModal)
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16); v.setSpacing(10)
        lc = QLabel("Categoría del requerimiento:")
        lc.setStyleSheet(f"color:{SLATE_700}; font-size:12px; font-weight:600;")
        v.addWidget(lc)
        self.cmb = QComboBox()
        for c in categorias:
            self.cmb.addItem(c, c)
        self.cmb.setMinimumWidth(280)
        self.cmb.setStyleSheet(
            f"QComboBox {{ border:1px solid {SILVER_300}; border-radius:6px;"
            f" padding:4px 10px; font-size:12px; background:white; }}")
        v.addWidget(self.cmb)
        lf = QLabel("Fecha:")
        lf.setStyleSheet(f"color:{SLATE_700}; font-size:12px; font-weight:600;")
        v.addWidget(lf)
        self.d = QDateEdit(QDate.currentDate())
        self.d.setCalendarPopup(True); self.d.setDisplayFormat("dd/MM/yyyy")
        v.addWidget(self.d)
        self.chk_vacio = QCheckBox("Crear vacío (lo lleno a mano, sin precargar)")
        self.chk_vacio.setStyleSheet(f"color:{SLATE_500}; font-size:11px;"
            " background:transparent; border:none;")
        self.chk_vacio.setToolTip(
            "Para requerimientos individuales (un servicio o una maquinaria por\n"
            "documento). Crea el requerimiento vacío y le agregas los insumos\n"
            "arrastrándolos del panel izquierdo o con el menú.")
        v.addWidget(self.chk_vacio)
        botones = QHBoxLayout(); botones.addStretch()
        cancelar = QPushButton("Cancelar"); cancelar.clicked.connect(self.reject)
        crear = QPushButton("Crear"); crear.clicked.connect(self.accept)
        crear.setStyleSheet(
            f"QPushButton {{ background:{ORANGE}; color:white; border:none;"
            f" border-radius:6px; padding:6px 16px; font-weight:600; }}")
        botones.addWidget(cancelar); botones.addWidget(crear)
        v.addLayout(botones)

    def valores(self):
        return (self.d.date().toString("yyyy-MM-dd"), self.cmb.currentData(),
                self.chk_vacio.isChecked())


class _RenombrarReqDialog(QDialog):
    """Renombra la categoría/etiqueta de un requerimiento. Combo EDITABLE: elige
    una categoría estándar o escribe una libre (p.ej. «REPUESTOS DE MAQUINARIA»,
    «SERVICIO DE ALQUILER»). No cambia el tipo del requerimiento."""

    def __init__(self, categorias, actual='', parent=None):
        super().__init__(parent)
        self.setWindowTitle("Renombrar categoría")
        self.setWindowModality(Qt.WindowModal)
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16); v.setSpacing(10)
        lc = QLabel("Categoría / nombre del requerimiento:")
        lc.setStyleSheet(f"color:{SLATE_700}; font-size:12px; font-weight:600;")
        v.addWidget(lc)
        hint = QLabel("Elige una de la lista o escribe la tuya.")
        hint.setStyleSheet(f"color:{SLATE_500}; font-size:10px;"
            " background:transparent; border:none;")
        v.addWidget(hint)
        self.cmb = QComboBox(); self.cmb.setEditable(True)
        for c in categorias:
            self.cmb.addItem(c, c)
        self.cmb.setCurrentText(actual or '')
        self.cmb.setMinimumWidth(300)
        self.cmb.setStyleSheet(
            f"QComboBox {{ border:1px solid {SILVER_300}; border-radius:6px;"
            f" padding:4px 10px; font-size:12px; background:white; }}")
        v.addWidget(self.cmb)
        botones = QHBoxLayout(); botones.addStretch()
        cancelar = QPushButton("Cancelar"); cancelar.clicked.connect(self.reject)
        ok = QPushButton("Guardar"); ok.clicked.connect(self.accept)
        ok.setStyleSheet(
            f"QPushButton {{ background:{ORANGE}; color:white; border:none;"
            f" border-radius:6px; padding:6px 16px; font-weight:600; }}")
        botones.addWidget(cancelar); botones.addWidget(ok)
        v.addLayout(botones)
        self.cmb.setFocus()

    def valor(self):
        return self.cmb.currentText().strip().upper()


class _DatosTDRDialog(QDialog):
    """Datos del documento para generar el TDR/EE.TT. con IA. Los campos estables
    (destinatario, entidad, solicitante, lugar…) se recuerdan en `configuracion`
    como predeterminados; el resto se ajusta por requerimiento. Si dejas vacíos
    los de entidad pública, la IA usa el formato privado (membrete simple)."""

    _CAMPOS = [   # (clave_config, etiqueta, placeholder)
        ('numero', "N° de requerimiento", "p.ej. 001-2026"),
        ('destinatario', "Destinatario (A)", "solo sector público — dejar vacío si privado"),
        ('cargo_destinatario', "Cargo del destinatario", "p.ej. Gerente Municipal"),
        ('atencion', "Atención", "p.ej. Oficina de Logística"),
        ('solicitante', "Solicitante (DE) / membrete", "tu nombre o empresa"),
        ('cargo_solicitante', "Cargo del solicitante", "p.ej. Residente de Obra"),
        ('entidad', "Entidad / institución", "p.ej. Municipalidad Distrital de…"),
        ('unidad_organica', "Unidad orgánica / área", "p.ej. Subgerencia de Infraestructura"),
        ('lugar', "Lugar (entrega/prestación)", "p.ej. distrito, provincia"),
        ('meta', "Meta presupuestal", "opcional"),
        ('objetivo', "Objetivo", "opcional — breve"),
    ]

    def __init__(self, req_id, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Datos para el TDR / Especificaciones técnicas")
        self.setWindowModality(Qt.WindowModal)
        self.setMinimumWidth(520)
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16); v.setSpacing(10)
        intro = QLabel(
            "Completa lo que aplique a tu caso. Lo que pongas se recuerda para la "
            "próxima vez. Si no eres entidad pública, deja vacíos «Destinatario», "
            "«Atención» y «Entidad» y se generará un documento privado.")
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color:{SLATE_500}; font-size:11px;"
            " background:transparent; border:none;")
        v.addWidget(intro)

        form = QFormLayout(); form.setSpacing(7)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        _ss = (f"QLineEdit, QComboBox {{ border:1px solid {SILVER_300};"
               f" border-radius:6px; padding:4px 8px; font-size:12px; background:white; }}")
        self._inp = {}
        q = REQ.get_requerimiento(req_id)
        empresa = get_config('empresa_nombre', '')
        for clave, etiqueta, ph in self._CAMPOS:
            le = QLineEdit(); le.setPlaceholderText(ph); le.setStyleSheet(_ss)
            prev = get_config(f'req_tdr_{clave}', '')
            if clave == 'numero':
                prev = prev or (str(q['numero']) if q else '')
            elif clave == 'solicitante':
                prev = prev or empresa
            le.setText(prev)
            self._inp[clave] = le
            form.addRow(etiqueta + ":", le)

        # Plazo (valor + unidad)
        prow = QHBoxLayout(); prow.setSpacing(6)
        self.inp_plazo = QLineEdit(get_config('req_tdr_plazo', ''))
        self.inp_plazo.setPlaceholderText("p.ej. 30"); self.inp_plazo.setStyleSheet(_ss)
        self.inp_plazo.setMaximumWidth(90)
        self.cmb_plazo_u = QComboBox(); self.cmb_plazo_u.setStyleSheet(_ss)
        self.cmb_plazo_u.addItem("días calendario", "dias")
        self.cmb_plazo_u.addItem("meses", "meses")
        _u = get_config('req_tdr_plazo_unidad', 'dias')
        self.cmb_plazo_u.setCurrentIndex(1 if _u == 'meses' else 0)
        prow.addWidget(self.inp_plazo); prow.addWidget(self.cmb_plazo_u); prow.addStretch()
        form.addRow("Plazo de ejecución:", prow)

        # Forma de pago
        self.cmb_pago = QComboBox(); self.cmb_pago.setStyleSheet(_ss)
        for t in ["Pago único previa conformidad", "Pago mensual",
                  "Pago por avance", "Según contrato"]:
            self.cmb_pago.addItem(t, t)
        _fp = get_config('req_tdr_forma_pago', '')
        if _fp:
            i = self.cmb_pago.findText(_fp)
            self.cmb_pago.setCurrentIndex(i if i >= 0 else 0)
        form.addRow("Forma de pago:", self.cmb_pago)

        # Fecha
        self.d = QDateEdit(QDate.currentDate())
        self.d.setCalendarPopup(True); self.d.setDisplayFormat("dd/MM/yyyy")
        self.d.setStyleSheet(_ss)
        form.addRow("Fecha:", self.d)
        v.addLayout(form)

        botones = QHBoxLayout(); botones.addStretch()
        cancelar = QPushButton("Cancelar"); cancelar.clicked.connect(self.reject)
        gen = QPushButton("Generar"); gen.clicked.connect(self.accept)
        gen.setStyleSheet(
            f"QPushButton {{ background:{ORANGE}; color:white; border:none;"
            f" border-radius:6px; padding:6px 16px; font-weight:600; }}")
        botones.addWidget(cancelar); botones.addWidget(gen)
        v.addLayout(botones)

    def valores(self):
        d = {k: le.text().strip() for k, le in self._inp.items()}
        d['plazo'] = self.inp_plazo.text().strip()
        d['plazo_unidad'] = self.cmb_plazo_u.currentData()
        d['forma_pago'] = self.cmb_pago.currentData()
        d['fecha'] = self.d.date().toString("dd/MM/yyyy")
        # Recordar para la próxima vez (todo salvo la fecha).
        for k in list(self._inp.keys()) + ['plazo', 'plazo_unidad', 'forma_pago']:
            set_config(f'req_tdr_{k}', d.get(k, ''))
        return d


class _FechaDialog(QDialog):
    """Pide la(s) fecha(s) de uno o varios partes diarios. «Del/Al»: se crea un
    parte por cada día del rango. Para un solo día, deja «Al» igual a «Del»."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Nuevo(s) parte(s) diario(s)")
        self.setWindowModality(Qt.WindowModal)
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(10)
        lbl = QLabel("Días a generar:")
        lbl.setStyleSheet(f"color:{SLATE_700}; font-size:12px; font-weight:600;")
        v.addWidget(lbl)
        fila = QHBoxLayout()
        self.d1 = QDateEdit(QDate.currentDate())
        self.d2 = QDateEdit(QDate.currentDate())
        for d in (self.d1, self.d2):
            d.setCalendarPopup(True)
            d.setDisplayFormat("dd/MM/yyyy")
        # Si «Al» queda antes que «Del», emparejarlos.
        self.d1.dateChanged.connect(
            lambda qd: self.d2.setDate(qd) if self.d2.date() < qd else None)
        fila.addWidget(QLabel("Del:")); fila.addWidget(self.d1)
        fila.addWidget(QLabel("Al:")); fila.addWidget(self.d2)
        v.addLayout(fila)
        hint = QLabel("Se crea un parte por cada día. Para un solo día, deja «Al» "
                      "igual a «Del».")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{SLATE_300}; font-size:10px; font-style:italic;")
        v.addWidget(hint)
        botones = QHBoxLayout(); botones.addStretch()
        cancelar = QPushButton("Cancelar"); cancelar.clicked.connect(self.reject)
        crear = QPushButton("Crear"); crear.clicked.connect(self.accept)
        crear.setStyleSheet(
            f"QPushButton {{ background:{ORANGE}; color:white; border:none;"
            f" border-radius:6px; padding:6px 16px; font-weight:600; }}")
        botones.addWidget(cancelar); botones.addWidget(crear)
        v.addLayout(botones)

    def valores(self):
        return (self.d1.date().toString("yyyy-MM-dd"),
                self.d2.date().toString("yyyy-MM-dd"))


class _PeriodoDialog(QDialog):
    """Pide el período (desde/hasta) de una valorización. Reutilizable para crear
    (defaults hoy) o editar (fechas iniciales + título/botón propios)."""

    def __init__(self, parent=None, *, desde='', hasta='',
                 titulo="Nueva valorización", boton="Crear"):
        super().__init__(parent)
        self.setWindowTitle(titulo)
        self.setWindowModality(Qt.WindowModal)
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(10)
        lbl = QLabel("Período de la valorización:")
        lbl.setStyleSheet(f"color:{SLATE_700}; font-size:12px; font-weight:600;")
        v.addWidget(lbl)
        fila = QHBoxLayout()
        qd1 = QDate.fromString(desde, "yyyy-MM-dd")
        qd2 = QDate.fromString(hasta, "yyyy-MM-dd")
        self.d1 = QDateEdit(qd1 if qd1.isValid() else QDate.currentDate())
        self.d2 = QDateEdit(qd2 if qd2.isValid() else QDate.currentDate())
        for d in (self.d1, self.d2):
            d.setCalendarPopup(True)
            d.setDisplayFormat("dd/MM/yyyy")
        fila.addWidget(QLabel("Del:")); fila.addWidget(self.d1)
        fila.addWidget(QLabel("Al:")); fila.addWidget(self.d2)
        v.addLayout(fila)
        botones = QHBoxLayout(); botones.addStretch()
        cancelar = QPushButton("Cancelar"); cancelar.clicked.connect(self.reject)
        crear = QPushButton(boton); crear.clicked.connect(self.accept)
        crear.setStyleSheet(
            f"QPushButton {{ background:{ORANGE}; color:white; border:none;"
            f" border-radius:6px; padding:6px 16px; font-weight:600; }}")
        botones.addWidget(cancelar); botones.addWidget(crear)
        v.addLayout(botones)

    def valores(self):
        return (self.d1.date().toString("yyyy-MM-dd"),
                self.d2.date().toString("yyyy-MM-dd"))


class _FechaUnicaDialog(QDialog):
    """Pide una sola fecha (p. ej. la de un requerimiento)."""

    def __init__(self, titulo="Fecha", parent=None):
        super().__init__(parent)
        self.setWindowTitle(titulo)
        self.setWindowModality(Qt.WindowModal)
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16); v.setSpacing(10)
        lbl = QLabel("Fecha:")
        lbl.setStyleSheet(f"color:{SLATE_700}; font-size:12px; font-weight:600;")
        v.addWidget(lbl)
        self.d = QDateEdit(QDate.currentDate())
        self.d.setCalendarPopup(True)
        self.d.setDisplayFormat("dd/MM/yyyy")
        v.addWidget(self.d)
        botones = QHBoxLayout(); botones.addStretch()
        cancelar = QPushButton("Cancelar"); cancelar.clicked.connect(self.reject)
        crear = QPushButton("Crear"); crear.clicked.connect(self.accept)
        crear.setStyleSheet(
            f"QPushButton {{ background:{ORANGE}; color:white; border:none;"
            f" border-radius:6px; padding:6px 16px; font-weight:600; }}")
        botones.addWidget(cancelar); botones.addWidget(crear)
        v.addLayout(botones)

    def valor(self):
        return self.d.date().toString("yyyy-MM-dd")


class _MetradoDelegate(QStyledItemDelegate):
    """Editor de la columna «Metr. actual»: QLineEdit alineado a la derecha y
    centrado verticalmente (el editor default aparecía pegado arriba)."""

    def createEditor(self, parent, option, index):
        ed = QLineEdit(parent)
        ed.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        ed.setStyleSheet(
            "QLineEdit { font-size:11px; padding:0 4px; margin:0;"
            f" border:1px solid {ORANGE}; background:white; color:#1A2535; }}")
        return ed


class _MetCellDelegate(QStyledItemDelegate):
    """Editor de las celdas de la planilla de metrados del día. Estiliza el
    QLineEdit (fondo blanco + texto oscuro) para que se VEA lo que se escribe —
    el editor por defecto heredaba un color que lo dejaba invisible al editar.
    Descripción (col 0) a la izquierda; dimensiones a la derecha."""

    def createEditor(self, parent, option, index):
        ed = QLineEdit(parent)
        if index.column() == 0:
            ed.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        else:
            ed.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        ed.setStyleSheet(
            "QLineEdit { font-size:10px; padding:0 4px; margin:0;"
            f" border:1px solid {ORANGE}; background:white; color:#1A2535; }}")
        return ed


def _fmt_fecha(iso):
    """Para mostrar: «yyyy-MM-dd» (como se guarda) → «dd/MM/yyyy». Si no
    coincide con el formato ISO, devuelve el texto tal cual."""
    if not iso:
        return ""
    p = str(iso).split('-')
    if len(p) == 3 and len(p[0]) == 4:
        return f"{p[2]}/{p[1]}/{p[0]}"
    return str(iso)


def _m(metrado, dec):
    if metrado is None:
        return ""
    return f"{metrado:,.{dec}f}"


def _pct(pct):
    if pct is None:
        return ""
    return f"{pct:.2f}%"


def _pp(val, base):
    """% del valor sobre la base contractual (0 si base=0)."""
    return f"{(val / base * 100) if base else 0:.2f}%"


def _excede(acu, base):
    """True si el acumulado supera la base contractual (con tolerancia, para no
    marcar diferencias por redondeo de float). Pinta la celda en rojo."""
    try:
        return (acu or 0) - (base or 0) > 1e-6
    except TypeError:
        return False
