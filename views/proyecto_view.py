# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""Vista principal de proyecto — fiel a las capturas Flask.

Layout:
┌─ Topbar: nombre proyecto | total ────────────────────────────┐
├─ Toolbar: ← Inicio · Editar · Exportar | Metrados · Cronograma · ... ─┤
│  QSplitter horizontal                                         │
│  ┌─ PRESUPUESTO (árbol) ──┬─ Tabs ──────────────────────────┐│
│  │  Ítem Descripción ...  │  ACU | Insumos | Metrados        ││
│  │                        │  Spec | Resumen                  ││
│  └────────────────────────┴──────────────────────────────────┘│
└───────────────────────────────────────────────────────────────┘
"""
import sqlite3
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QLabel,
    QPushButton, QFrame, QTreeWidget, QTreeWidgetItem, QTabWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QAbstractItemDelegate,
    QMenu, QMessageBox, QLineEdit, QSizePolicy, QTextEdit,
    QScrollArea, QGridLayout, QSpacerItem, QStyledItemDelegate, QStyle,
    QStyleOptionViewItem,
    QComboBox, QDialog, QFormLayout, QProgressBar, QCheckBox, QInputDialog,
    QListWidget, QListWidgetItem, QApplication
)
from PySide6.QtCore import Qt, Signal, QSettings, QTimer, QSize, QRect, QEvent, QObject, QThread
from PySide6.QtGui import (
    QFont, QColor, QBrush, QKeySequence, QShortcut, QIcon, QKeyEvent,
    QFontMetrics, QPainter, QTextCharFormat, QTextListFormat,
    QTextBlockFormat, QTextCursor, QImage, QCursor
)
from PySide6.QtWidgets import QFileDialog as _QFileDialog

from core.config import DB_PATH
from core.database import (
    get_db, _r2, _rn, _recalcular_pu, calcular_totales,
    get_acu_items, get_insumos_proyecto, get_insumos_para_partidas,
    _siguiente_codigo_inei,
    get_decimales_ppto, get_decimales_metrado, get_decimales_cant_acu,
    parcial_wysiwyg,
    precios_inconsistentes, unificar_precio_recurso, precio_recurso_en_proyecto,
    partidas_pu_inconsistente, partida_usa_acero
)
from models.usuario import Usuario
from utils.formatting import fmt, fmt_num, parse_num
from utils.icons import icon as load_icon, icon_colored
from utils import partidas_clipboard as _pclip

# ── Paleta — aliases de tokens centralizados (utils/theme.py) ────────────────
from utils.theme import C as _C

BLUE_500  = _C.brand            # naranja marca (legacy name)
BLUE_700  = _C.brand_hover
SLATE_700 = _C.text
SLATE_500 = _C.text_secondary
SLATE_300 = _C.text_muted
SLATE_100 = _C.text_faint
SILVER_100 = _C.bg
SILVER_300 = _C.border
RED_500   = _C.error
GREEN_500 = "#68B723"
ORANGE    = _C.warning          # variable ORANGE histórica era yellow/banana
_GG_CLIPBOARD: list = []   # filas copiadas entre rubros (sesión)
# Portapapeles de metrados/acero a nivel celda — globales de sesión para que el
# Ctrl+C/V funcione ENTRE proyectos abiertos (no solo dentro del mismo). Se
# mutan in-place (`[:] = ...`) para conservar la referencia compartida.
_MET_CLIPBOARD: list = []
_ACERO_CLIPBOARD: list = []


def _norm_lead_zero(t: str) -> str:
    """Completa el cero a la izquierda en decimales: «.1»→«0.1», «-.5»→«-0.5»
    (también con coma). Devuelve el texto igual si no aplica."""
    t = (t or '').strip()
    if t[:1] in ('.', ','):
        return '0' + t
    if t[:2] in ('-.', '-,'):
        return '-0' + t[1:]
    return t
# QMenu styling — el filter global `install_global_popup_styles(app)` aplica
# `_MENU_QSS` a TODOS los QMenu de la app. No se necesita setStyleSheet local.

# ── Colores jerárquicos del presupuesto ──────────────────────────────────────
# Cada nivel: (color_texto, color_fondo_tinte, tamaño_pt)
# Los títulos usan texto coloreado + tinte de fondo muy suave
NIVEL_ESTILO = {
    1: ("#B71C1C", "#FFF5F5", 9),   # Rojo oscuro       — capítulos principales
    2: (_C.info,   "#F5F8FF", 9),   # Arándano (Blueberry) — sub-capítulos
    3: ("#6A1B9A", "#F9F5FF", 9),   # Morado            — secciones
    4: ("#AD1457", "#FFF5FA", 9),   # Rosa oscuro       — sub-secciones
}
BG_PARTIDA = _C.surface

# ── Colores ACU por tipo ───────────────────────────────────────────────────────
# Esquema de colores ACU — consistente en badge, fondo de fila, cabecera y barras:
#   MO  = ámbar/naranja   MAT = verde   EQ = gris-acero   SC = morado
ACU_COLOR = {
    'MO':  QColor("#FFF9C4"),   # ámbar suave
    'MAT': QColor("#E8F5E9"),   # verde suave
    'EQ':  QColor("#ECEFF1"),   # gris-acero suave
    'SC':  QColor("#F3EAFA"),   # morado suave
}
ACU_BADGE = {
    'MO':  ("#F39C12", "#FFFFFF"),   # ámbar
    'MAT': ("#27AE60", "#FFFFFF"),   # verde
    'EQ':  ("#607D8B", "#FFFFFF"),   # gris-acero
    'SC':  ("#7A36B1", "#FFFFFF"),   # morado
}
ACU_SECTION = {
    'MO':  ('#FFF9C4', '#7a4900', 'MANO DE OBRA'),                       # ámbar bg, texto marrón
    'MAT': ('#E8F5E9', '#2d5a27', 'MATERIALES'),                          # verde bg, texto verde oscuro
    'EQ':  ('#ECEFF1', '#37474F', 'EQUIPO Y HERRAMIENTA'),                # gris-acero bg, texto oscuro
    'SC':  ('#F3EAFA', '#4A1B7A', 'SUB-CONTRATOS / SERVICIOS'),           # morado bg, texto morado oscuro
}
_NEUTRAL_BG = QColor('#F0F2F5')   # fondo neutro para celdas no editables

def _cols_acu():
    from utils.i18n import tr
    return ["Tip", tr("Descripción"), "Und.", tr("Cuadrilla"), tr("Cantidad"), tr("Precio"), tr("Parcial")]
COLS_ACU  = ["Tip", "Descripción", "Und.", "Cuadrilla", "Cantidad", "Precio", "Parcial"]


def _recurso_por_hora(tipo, unidad):
    """True si la cantidad se deriva de la cuadrilla: MO y equipo por hora (hh/hm).
    Fórmula canónica: cant = cuadrilla / rendimiento × jornada."""
    u = (unidad or '').strip().lower()
    return (tipo == 'MO'
            or u in ('hh', 'hm', 'h-h', 'h-m', 'jph', 'jh')
            or 'hora' in u)


def _recurso_por_dia(tipo, unidad):
    """True si la cantidad se deriva de la cuadrilla SIN jornada: MO/EQ con
    unidad día/jor. El rendimiento ya es producción por DÍA, entonces:
        cant = cuadrilla / rendimiento
    (validado contra bases PowerCost/Delphin: 23/33 items día cumplen exacto)."""
    u = (unidad or '').strip().rstrip('.').lower()
    return (tipo in ('MO', 'EQ')
            and u in ('día', 'dia', 'días', 'dias', 'jor', 'jornada'))


def _partida_global(unidad):
    """True si la PARTIDA es global (glb/est/serv): el ACU no usa
    cuadrilla/rendimiento y la cantidad se llena directa en todos los
    insumos, incluida la MO (comportamiento PowerCost)."""
    u = (unidad or '').strip().rstrip('.').lower()
    return u in ('glb', 'gbl', 'est', 'serv')


class _SubPptoTab(QPushButton):
    """Pestaña de sub-presupuesto: doble clic activa edición inline del nombre.

    Limita el ancho a `MAX_WIDTH` y trunca con elipsis el nombre visible;
    el nombre completo se preserva en `_full_name` y se muestra en tooltip
    para no romper el layout cuando el subpresupuesto tiene nombre largo.
    """

    MAX_WIDTH = 220
    renombrar = Signal(str)   # emite el nuevo nombre
    eliminar  = Signal()      # pide eliminar este sub-presupuesto
    copiar    = Signal()      # copiar este sub-presupuesto completo
    pegar_sub = Signal()      # pegar el sub-presupuesto del clipboard (nuevo)

    def __init__(self, nombre: str, editable: bool = True,
                 borrable: bool = False, parent=None):
        super().__init__(parent)
        self._editable = editable
        self._borrable = borrable
        self._editor: QLineEdit | None = None
        self._full_name = nombre or ''
        self.setMaximumWidth(self.MAX_WIDTH)
        self._apply_full_name(self._full_name)

    def contextMenuEvent(self, event):
        from utils.i18n import tr
        from utils import partidas_clipboard as _pc
        menu = QMenu(self)
        act_rename = menu.addAction(tr("Renombrar")) if self._editable else None
        act_delete = (menu.addAction(tr("Eliminar") + "…")
                      if self._borrable else None)
        menu.addSeparator()
        act_copy = menu.addAction(tr("Copiar sub-presupuesto"))
        act_paste = None
        if _pc.hay_subppto_clipboard():
            act_paste = menu.addAction(
                f"{tr('Pegar sub-presupuesto')} «{_pc.nombre_subppto_clipboard()}»")
        chosen = menu.exec(event.globalPos())
        if chosen is None:
            return
        if chosen is act_rename:
            self._iniciar_edicion()
        elif chosen is act_delete:
            self.eliminar.emit()
        elif chosen is act_copy:
            self.copiar.emit()
        elif chosen is act_paste:
            self.pegar_sub.emit()

    def _apply_full_name(self, nombre: str):
        """Trunca con elipsis al ancho disponible y propaga al tooltip."""
        self._full_name = nombre or ''
        fm = self.fontMetrics()
        # ~24 px reservados para padding interno del QPushButton
        avail = max(40, self.MAX_WIDTH - 24)
        elided = fm.elidedText(self._full_name, Qt.ElideRight, avail)
        super().setText(elided)
        self.setToolTip(self._full_name)

    def setText(self, txt: str):
        """Override: mantener `_full_name` sincronizado al setear texto."""
        self._apply_full_name(txt)

    def mouseDoubleClickEvent(self, event):
        if self._editable:
            self._iniciar_edicion()
        else:
            super().mouseDoubleClickEvent(event)

    def _iniciar_edicion(self):
        if self._editor:
            return
        from PySide6.QtCore import QObject, QEvent as _QE
        ed = QLineEdit(self._full_name, self.parent())
        ed.setGeometry(self.geometry())
        ed.setAlignment(Qt.AlignCenter)
        ed.setStyleSheet(
            "border:2px solid #F37329; border-radius:4px;"
            " background:white; color:#273445; font-size:11px; font-weight:700;"
            " min-height:0; padding:0;"
        )
        ed.selectAll()
        ed.show()
        ed.setFocus()
        self._editor = ed

        def _commit():
            if not self._editor:
                return
            nuevo = ed.text().strip()
            self._editor = None
            ed.deleteLater()
            if nuevo and nuevo != self._full_name:
                self.renombrar.emit(nuevo)

        def _cancel():
            if not self._editor:
                return
            self._editor = None
            ed.deleteLater()

        ed.returnPressed.connect(_commit)

        class _Filt(QObject):
            def eventFilter(self_, obj, event):
                if event.type() == _QE.Type.FocusOut:
                    _commit()
                    return False
                if event.type() == _QE.Type.KeyPress and event.key() == Qt.Key_Escape:
                    _cancel()
                    return True
                return False

        self._editor_filt = _Filt(ed)
        ed.installEventFilter(self._editor_filt)


class _SeleccionarRecursoDialog(QDialog):
    """Selector de recurso destino al reemplazar un insumo del proyecto.

    Muestra todos los recursos del catálogo, con badge 📦 para los que ya
    se usan en este proyecto (lo más útil al fusionar duplicados — el
    usuario típicamente elige uno de esos para consolidar).
    """

    def __init__(self, proyecto_id: int, recurso_id_excluir: int,
                 desc_origen: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Reemplazar por otro recurso")
        self.setMinimumSize(640, 460)
        self.setModal(True)
        self.selected_id: int | None = None
        self._proyecto_id = proyecto_id
        self._excluir = recurso_id_excluir

        vl = QVBoxLayout(self)
        vl.setContentsMargins(16, 14, 16, 14)
        vl.setSpacing(10)

        lbl = QLabel(
            f"Reemplazar todas las apariciones de:\n"
            f"  • <b>{desc_origen}</b>\n"
            f"por otro recurso <b>que ya está en este proyecto</b>."
        )
        lbl.setWordWrap(True)
        lbl.setStyleSheet("background:transparent; border:none;")
        vl.addWidget(lbl)

        from utils.i18n import tr
        self.inp = QLineEdit()
        self.inp.setPlaceholderText(tr("Buscar") + "…")
        self.inp.textChanged.connect(self._filtrar)
        vl.addWidget(self.inp)

        self.tbl = QTableWidget(0, 4, self)
        self.tbl.setHorizontalHeaderLabels(
            ['Código', 'Descripción', 'Unidad', 'Precio S/.']
        )
        self.tbl.setSelectionBehavior(QTableWidget.SelectRows)
        self.tbl.setSelectionMode(QTableWidget.SingleSelection)
        self.tbl.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tbl.verticalHeader().setVisible(False)
        hh = self.tbl.horizontalHeader()
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        self.tbl.setColumnWidth(0, 90)
        self.tbl.setColumnWidth(2, 70)
        self.tbl.setColumnWidth(3, 100)
        self.tbl.doubleClicked.connect(self._aceptar)
        vl.addWidget(self.tbl, stretch=1)

        bb = QHBoxLayout()
        bb.addStretch()
        btn_cancel = QPushButton("Cancelar")
        btn_cancel.clicked.connect(self.reject)
        bb.addWidget(btn_cancel)
        self.btn_ok = QPushButton("Reemplazar")
        self.btn_ok.setStyleSheet(_BTN_PRIMARY_SS_FALLBACK)
        self.btn_ok.clicked.connect(self._aceptar)
        bb.addWidget(self.btn_ok)
        vl.addLayout(bb)

        self._cargar()

    def _cargar(self):
        """Solo recursos usados en este proyecto (no toda la biblioteca) —
        reduce errores al fusionar duplicados: el destino plausible siempre
        es algo que ya existe en el presupuesto."""
        conn = get_db()
        rows = conn.execute(
            "SELECT DISTINCT r.id, r.codigo, r.descripcion, r.unidad,"
            "       r.tipo, COALESCE(r.precio, 0) AS precio"
            " FROM acu_items ai"
            " JOIN recursos r ON r.id = ai.recurso_id"
            " JOIN partidas p ON p.id = ai.partida_id"
            " WHERE p.proyecto_id=? AND r.id != ?"
            " ORDER BY r.descripcion",
            (self._proyecto_id, self._excluir)
        ).fetchall()
        conn.close()
        self._all = [dict(r) for r in rows]
        self._render(self._all)

    def _render(self, rows):
        self.tbl.setRowCount(0)
        for r in rows:
            ri = self.tbl.rowCount()
            self.tbl.insertRow(ri)
            it_cod = QTableWidgetItem(r['codigo'] or '')
            it_cod.setData(Qt.UserRole, r['id'])
            self.tbl.setItem(ri, 0, it_cod)
            self.tbl.setItem(ri, 1, QTableWidgetItem(r['descripcion'] or ''))
            self.tbl.setItem(ri, 2, QTableWidgetItem(r['unidad'] or ''))
            it_p = QTableWidgetItem(f"{(r['precio'] or 0):,.2f}")
            it_p.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.tbl.setItem(ri, 3, it_p)

    def _filtrar(self, q: str):
        from utils.formatting import norm_busqueda
        q = norm_busqueda((q or '').strip())
        if not q:
            self._render(self._all)
            return
        out = [
            r for r in self._all
            if q in norm_busqueda(f"{r['codigo'] or ''} {r['descripcion'] or ''} {r['unidad'] or ''}")
        ]
        self._render(out)

    def _aceptar(self):
        ri = self.tbl.currentRow()
        if ri < 0:
            return
        it_cod = self.tbl.item(ri, 0)
        if not it_cod:
            return
        self.selected_id = it_cod.data(Qt.UserRole)
        self.accept()


# Fallback de estilo si BTN_PRIMARY_SS no está disponible en el scope
_BTN_PRIMARY_SS_FALLBACK = (
    "QPushButton { background:#F37329; color:white; border:none;"
    " border-radius:6px; padding:6px 18px; font-weight:600; }"
    "QPushButton:hover { background:#E0651F; }"
)


class _EditarRecursoDialog(QDialog):
    """Diálogo para editar Descripción, Unidad y Tipo de un recurso del catálogo."""

    _UNIDADES = sorted({
        "m","m²","m³","ml","km","cm","mm",
        "kg","tn","ton","lb",
        "und","glb","pza","pzas","jgo","cjt","vj","est",
        "hh","hm","h","hr","día","mes","sem",
        "lt","l","gal","bls","bol",
        "pie²","pie³","p2","p3","ha","pto","rll",
    })

    def __init__(self, recurso: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Editar insumo")
        self.setMinimumWidth(460)
        self.setModal(True)

        vl = QVBoxLayout(self)
        vl.setContentsMargins(20, 16, 20, 16)
        vl.setSpacing(10)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setSpacing(8)

        # Descripción
        self._inp_desc = QLineEdit(recurso.get('descripcion', ''))
        self._inp_desc.setMinimumHeight(32)
        form.addRow("Descripción:", self._inp_desc)

        # Unidad con autocompletado
        self._inp_und = QLineEdit(recurso.get('unidad', ''))
        self._inp_und.setMinimumHeight(32)
        from PySide6.QtWidgets import QCompleter
        comp = QCompleter(self._UNIDADES, self._inp_und)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        comp.setFilterMode(Qt.MatchContains)
        comp.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        comp.popup().setStyleSheet(
            "QListView { background:white; border:1px solid #D4D4D4;"
            " border-radius:6px; font-size:12px; padding:4px; color:#273445; }"
            "QListView::item { padding:4px 10px; }"
            "QListView::item:selected { background:#FEF5EB; color:#C0621A; }"
        )
        self._inp_und.setCompleter(comp)
        form.addRow("Unidad:", self._inp_und)

        # Tipo
        self._cmb_tipo = QComboBox()
        self._cmb_tipo.addItems(["MO", "MAT", "EQ", "SC"])
        tipo_actual = recurso.get('tipo', 'MAT')
        idx = {"MO": 0, "MAT": 1, "EQ": 2, "SC": 3}.get(tipo_actual, 1)
        self._cmb_tipo.setCurrentIndex(idx)
        self._cmb_tipo.setMinimumHeight(32)
        form.addRow("Tipo:", self._cmb_tipo)

        # Índice INEI (catálogo unificado)
        self._cmb_inei = QComboBox()
        self._cmb_inei.setMinimumHeight(32)
        self._cmb_inei.setMaxVisibleItems(15)
        self._cmb_inei.setStyleSheet("QComboBox { combobox-popup: 0; }")
        self._cmb_inei.addItem("— Sin índice INEI —", "")
        try:
            from views.recursos_view import INEI_CATALOG
        except Exception:
            INEI_CATALOG = []
        cod_inei = (recurso.get('indice_inei') or '').strip()
        if cod_inei and cod_inei not in {c for c, _ in INEI_CATALOG}:
            self._cmb_inei.addItem(f"{cod_inei} — (personalizado)", cod_inei)
        for cod, desc in INEI_CATALOG:
            self._cmb_inei.addItem(f"{cod} — {desc}", cod)
        ix = self._cmb_inei.findData(cod_inei)
        self._cmb_inei.setCurrentIndex(ix if ix >= 0 else 0)
        form.addRow("Índice INEI:", self._cmb_inei)

        vl.addLayout(form)

        lbl_w = QLabel("Estos cambios se aplican al catálogo global de insumos.")
        lbl_w.setStyleSheet("font-size:10px; color:#7F8C8D;")
        vl.addWidget(lbl_w)

        self._lbl_err = QLabel("")
        self._lbl_err.setStyleSheet("color:#dc3545; font-size:11px;")
        vl.addWidget(self._lbl_err)

        btns = QHBoxLayout()
        btns.addStretch()
        btn_can = QPushButton("Cancelar")
        btn_can.clicked.connect(self.reject)
        btns.addWidget(btn_can)
        btn_ok = QPushButton("Guardar")
        btn_ok.setStyleSheet(
            "background:#485a6c; color:white; border-radius:6px; padding:6px 20px;"
        )
        btn_ok.clicked.connect(self._validar)
        btns.addWidget(btn_ok)
        vl.addLayout(btns)

    def _validar(self):
        if not self._inp_desc.text().strip():
            self._lbl_err.setText("La descripción no puede estar vacía.")
            return
        self.accept()

    def datos(self) -> dict:
        return {
            'descripcion': self._inp_desc.text().strip(),
            'unidad':      self._inp_und.text().strip(),
            'tipo':        self._cmb_tipo.currentText(),
            'indice_inei': self._cmb_inei.currentData() or '',
        }


def _parse_precio(texto: str) -> float:
    """Extrae float de un texto formateado tipo 'S/ 1,234.56' o '1.234,56'."""
    import re as _re
    limpio = _re.sub(r'[^\d,\.]', '', texto)
    # Detectar si la coma es separador de miles o decimal
    if ',' in limpio and '.' in limpio:
        if limpio.rindex('.') > limpio.rindex(','):
            limpio = limpio.replace(',', '')         # 1,234.56 → 1234.56
        else:
            limpio = limpio.replace('.', '').replace(',', '.')  # 1.234,56 → 1234.56
    elif ',' in limpio:
        limpio = limpio.replace(',', '.')
    try:
        return float(limpio)
    except ValueError:
        return 0.0




class _AcuBarrasWidget(QWidget):
    """Barras de porcentaje MO/MAT/EQ/SC para el espacio libre del ACU."""

    _TIPOS = [
        ('MO',  'Mano de Obra',     '#F39C12'),
        ('MAT', 'Materiales',       '#27AE60'),
        ('EQ',  'Equipos y Herr.',  '#607D8B'),
        ('SC',  'Sub-contratos',    '#7A36B1'),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._totales = {'MO': 0.0, 'MAT': 0.0, 'EQ': 0.0, 'SC': 0.0}
        self.setMinimumHeight(80)
        self.setMaximumHeight(120)
        self.setStyleSheet("background:white; border:none;")

    def actualizar(self, totales: dict):
        self._totales = {k: totales.get(k, 0.0)
                         for k in ('MO', 'MAT', 'EQ', 'SC')}
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        total = sum(self._totales.values())
        w = self.width()
        n = len(self._TIPOS)
        row_h = self.height() / n
        lbl_w = 100
        pct_w = 44
        bar_x = lbl_w + 8
        bar_w = max(1, w - lbl_w - pct_w - 24)
        bar_h = 10
        radius = 5

        for i, (tipo, label, color) in enumerate(self._TIPOS):
            y = int(i * row_h)
            cy = int(y + row_h / 2)
            val  = self._totales.get(tipo, 0.0)
            pct  = (val / total * 100) if total > 0 else 0.0
            fill = max(0, int(bar_w * pct / 100))

            # Label
            painter.setPen(QColor(color))
            painter.setFont(QFont('', 9, QFont.Bold))
            painter.drawText(8, cy - 6, lbl_w - 8, 16,
                             Qt.AlignLeft | Qt.AlignVCenter, label)

            # Fondo de la barra
            bar_rect = QRect(bar_x, cy - bar_h // 2, bar_w, bar_h)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor('#F0F2F5'))
            painter.drawRoundedRect(bar_rect, radius, radius)

            # Relleno
            if fill > 0:
                fill_rect = QRect(bar_x, cy - bar_h // 2, fill, bar_h)
                painter.setBrush(QColor(color))
                painter.drawRoundedRect(fill_rect, radius, radius)

            # Porcentaje
            painter.setPen(QColor(color))
            painter.setFont(QFont('', 9, QFont.Bold))
            painter.drawText(bar_x + bar_w + 6, cy - 6, pct_w, 16,
                             Qt.AlignRight | Qt.AlignVCenter, f"{pct:.1f}%")

        painter.end()


class _AcuTable(QTableWidget):
    """QTableWidget con navegación por teclado para el panel ACU."""

    def __init__(self, rows: int, cols: int, parent=None):
        super().__init__(rows, cols, parent)
        self._key_handler = None   # callable(event) → bool

    def keyPressEvent(self, event):
        if self._key_handler and self._key_handler(event):
            return
        super().keyPressEvent(event)


class _AcuBadgeDelegate(QStyledItemDelegate):
    """Pinta el badge MO/MAT/EQ/SC como píldora coloreada ignorando el stylesheet."""
    _PILL = {
        'MO':  ('#F39C12', '#FFFFFF'),
        'MAT': ('#27AE60', '#FFFFFF'),
        'EQ':  ('#607D8B', '#FFFFFF'),
        'SC':  ('#7A36B1', '#FFFFFF'),
    }

    def paint(self, painter, option, index):
        texto = index.data() or ''
        if texto not in self._PILL:
            super().paint(painter, option, index)
            return
        bg_hex, fg_hex = self._PILL[texto]
        painter.save()
        if option.state & QStyle.State_Selected:
            painter.fillRect(option.rect, QColor('#FEF0E0'))
        else:
            painter.fillRect(option.rect, QColor('#FFFFFF'))
        pill = option.rect.adjusted(4, 3, -4, -3)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(bg_hex))
        painter.drawRoundedRect(pill, 4, 4)
        painter.setPen(QColor(fg_hex))
        painter.setFont(QFont('', 8, QFont.Bold))
        painter.drawText(pill, Qt.AlignCenter, texto)
        painter.restore()


class _InputCellDelegate(QStyledItemDelegate):
    """Pinta celdas editables como campo de formulario y abre editor inline al clic.

    Reglas de visibilidad:
      col 3 (Cuadrilla) → MO y equipo por hora (hh/hm)
      col 4 (Cantidad)  → MAT, SC y equipo NO por hora (la de MO/equipo-hora se deriva)
      col 5 (Precio)    → todos
    """

    _ROW_BG = {'MO': '#FFF9C4', 'MAT': '#E8F5E9', 'EQ': '#ECEFF1',
               'SC': '#F3EAFA'}

    def __init__(self, view, save_col: int):
        super().__init__(view)
        self._save_col = save_col

    def _tipo(self, index) -> str:
        return index.model().index(index.row(), 0).data() or ''

    def _unidad(self, index) -> str:
        return index.model().index(index.row(), 2).data() or ''

    def _editable(self, index) -> bool:
        view = self.parent()
        row = index.row()
        if hasattr(view, '_acu_row_ids') and row < len(view._acu_row_ids):
            if view._acu_row_ids[row] == -1:
                return False
        tipo = self._tipo(index)
        col  = index.column()
        if getattr(view, '_acu_partida_global', False):
            # Partida global (glb/est/serv): sin cuadrilla; cantidad y
            # precio directos en todos los tipos.
            return col in (4, 5) and tipo in ('MO', 'MAT', 'EQ', 'SC')
        unidad   = self._unidad(index)
        por_dia  = _recurso_por_dia(tipo, unidad)
        por_hora = por_dia or _recurso_por_hora(tipo, unidad)
        if col == 3:   # Cuadrilla → MO y equipo por hora (hh/hm) o por día
            return por_hora
        if col == 4:   # Cantidad → editable salvo cuando se deriva de la cuadrilla
            return tipo in ('MAT', 'EQ', 'SC') and not por_hora
        if col == 5:   # Precio → todos
            return tipo in ('MO', 'MAT', 'EQ', 'SC')
        return False

    def paint(self, painter, option, index):
        painter.save()
        sel = bool(option.state & QStyle.State_Selected)

        if self._editable(index):
            # Campo activo: fondo blanco + borde gris input
            painter.fillRect(option.rect,
                             QColor('#FEF0E0') if sel else QColor('#FFFFFF'))
            field = option.rect.adjusted(2, 2, -2, -2)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(QColor('#CBD5E0'))
            painter.setBrush(QColor('#FFFFFF'))
            painter.drawRoundedRect(field, 2, 2)
            painter.setPen(QColor('#273445'))
            painter.setFont(option.font)
            painter.drawText(field.adjusted(4, 0, -6, 0),
                             Qt.AlignRight | Qt.AlignVCenter, index.data() or '')
        else:
            # Celda no editable: fondo neutro gris — no aplica ese tipo
            painter.fillRect(option.rect,
                             QColor('#FEF0E0') if sel else _NEUTRAL_BG)
            painter.setPen(QColor('#B0BEC5'))
            painter.setFont(option.font)
            painter.drawText(option.rect.adjusted(4, 0, -4, 0),
                             Qt.AlignRight | Qt.AlignVCenter, index.data() or '')

        painter.restore()

    def createEditor(self, parent, option, index):
        if not self._editable(index):
            return None
        ed = QLineEdit(parent)
        ed.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        ed.setStyleSheet(
            'background:white; border:2px solid #F37329; border-radius:2px;'
            ' padding:0 4px; font-size:11px;'
        )
        self._instalar_nav(ed, index)
        return ed

    def _instalar_nav(self, ed: QLineEdit, index):
        """Instala navegación con flechas/Tab dentro del editor inline."""
        from PySide6.QtCore import QObject, QEvent as _QE
        view     = self.parent()
        row      = index.row()
        col      = index.column()
        COLS_ED  = [3, 4, 5]
        delegate = self

        TIPOS_ED = {3: {'MO'}, 4: {'MAT', 'EQ', 'SC'},
                    5: {'MO', 'MAT', 'EQ', 'SC'}}

        def _tipo_fila(r: int) -> str:
            it = view.tbl_acu.item(r, 0)
            return it.text() if it else ''

        def _siguiente_col_editable(c: int, r: int, dc: int):
            """Devuelve la siguiente columna editable para este tipo de fila, saltando no editables.
            c=-1 significa buscar desde el inicio (dc=1) o final (dc=-1)."""
            tipo = _tipo_fila(r)
            if c == -1 or c not in COLS_ED:
                candidatos = COLS_ED if dc > 0 else list(reversed(COLS_ED))
            else:
                idx = COLS_ED.index(c)
                if dc > 0:
                    candidatos = COLS_ED[idx + 1:]
                else:
                    candidatos = list(reversed(COLS_ED[:idx]))
            for nc in candidatos:
                if tipo in TIPOS_ED.get(nc, set()):
                    return nc
            return None

        def _commit_and_go(dr: int, dc: int):
            """Guarda el valor actual y mueve al editor siguiente."""
            delegate.commitData.emit(ed)
            delegate.closeEditor.emit(ed, QAbstractItemDelegate.EndEditHint.NoHint)

            def _ir():
                n = view.tbl_acu.rowCount()
                new_row, new_col = row, col
                if dr != 0:
                    new_row = row + dr
                    while 0 <= new_row < n:
                        aid = view._acu_row_ids[new_row] if new_row < len(view._acu_row_ids) else -1
                        if aid != -1:
                            tipo_nueva = _tipo_fila(new_row)
                            # Mantener la misma columna si es editable, si no buscar la más próxima
                            if tipo_nueva in TIPOS_ED.get(col, set()):
                                new_col = col
                            else:
                                nc = _siguiente_col_editable(-1, new_row, 1)
                                new_col = nc if nc is not None else col
                            break
                        new_row += dr
                    else:
                        return
                elif dc != 0:
                    nc = _siguiente_col_editable(col, row, dc)
                    if nc is None:
                        return
                    new_col = nc
                if 0 <= new_row < n:
                    view.tbl_acu.setCurrentCell(new_row, new_col)
                    view.tbl_acu.edit(view.tbl_acu.model().index(new_row, new_col))
            QTimer.singleShot(30, _ir)

        class _NavFilt(QObject):
            def eventFilter(self_, obj, event):
                if event.type() != _QE.Type.KeyPress:
                    return False
                k = event.key()
                if k == Qt.Key_Up:
                    _commit_and_go(-1, 0); return True
                if k == Qt.Key_Down or k in (Qt.Key_Return, Qt.Key_Enter):
                    _commit_and_go(1, 0); return True
                if k == Qt.Key_Tab:
                    shift = bool(event.modifiers() & Qt.ShiftModifier)
                    _commit_and_go(0, -1 if shift else 1); return True
                if k == Qt.Key_Left and ed.cursorPosition() == 0 and not ed.hasSelectedText():
                    _commit_and_go(0, -1); return True
                if k == Qt.Key_Right and ed.cursorPosition() == len(ed.text()) and not ed.hasSelectedText():
                    _commit_and_go(0, 1); return True
                return False

        ed._nav_filt = _NavFilt(ed)
        ed.installEventFilter(ed._nav_filt)

    def setEditorData(self, editor, index):
        editor.setText(index.data() or '')
        editor.selectAll()

    def setModelData(self, editor, model, index):
        view = self.parent()
        row = index.row()
        if not hasattr(view, '_acu_row_ids') or row >= len(view._acu_row_ids):
            return
        acu_id = view._acu_row_ids[row]
        if acu_id <= 0:
            return
        try:
            val = float(editor.text().replace(',', '.'))
        except ValueError:
            return
        save_col = self._save_col
        # Diferir el guardado para que el editor se cierre antes de recargar la tabla
        QTimer.singleShot(0, lambda: view._aplicar_cambio_acu(acu_id, save_col, val))


def _cols_ppto():
    from utils.i18n import tr
    return [tr("Ítem"), tr("Descripción"), "Und.", tr("Cantidad"), "P.U.", tr("Parcial")]
def _cols_ins():
    from utils.i18n import tr
    return [tr("Tipo"), tr("Descripción"), "Und.", tr("Cantidad"), tr("Precio"), tr("Parcial")]
def _cols_met():
    from utils.i18n import tr
    return [tr("Descripción"), "N°Est.", "N°Elem.", tr("Área"), tr("Largo"), tr("Ancho"), tr("Alto"), tr("Parcial")]
def _cols_acero():
    from utils.i18n import tr
    return ["#", tr("Descripción"), tr("Diámetro"), "N°Estr.", "N°Elem.", "N°Var.",
            tr("Longitud"), "Parc.(m)", "kg/ml", "Parc.(kg)", ""]
COLS_PPTO = ["Ítem", "Descripción", "Unid.", "Metrado", "P.U.", "Parcial"]
COLS_INS  = ["Tipo", "Descripción", "Und.", "Cantidad", "Precio U.", "Parcial"]
COLS_MET   = ["Descripción", "N°Est.", "N°Elem.", "Área", "Largo", "Ancho", "Alto", "Parcial"]
COLS_ACERO = ["#", "Descripción", "Diámetro", "N°Estr.", "N°Elem.", "N°Var.",
              "Longitud", "Parc.(m)", "kg/ml", "Parc.(kg)", ""]

# Diámetros comerciales de acero corrugado en Perú (SIDERPERU / ACEROS AREQUIPA)
# Ordenados de menor a mayor; mezcla mm y pulgadas comerciales
_ACERO_KG_ML = {
    # ── métricos ─────────────────────────────────────────────
    '6':      0.222,   # Ø6 mm
    '8':      0.395,   # Ø8 mm
    '10':     0.617,   # Ø10 mm
    '12':     0.888,   # Ø12 mm
    '16':     1.578,   # Ø16 mm
    '19':     2.226,   # Ø19 mm
    '22':     2.984,   # Ø22 mm
    '25':     3.853,   # Ø25 mm
    '32':     6.313,   # Ø32 mm
    # ── pulgadas comerciales (ASTM A615 / NTP 341.031) ───────
    '1/4"':   0.249,   # 6.35 mm
    '3/8"':   0.560,   # 9.53 mm
    '1/2"':   0.994,   # 12.70 mm
    '5/8"':   1.552,   # 15.88 mm
    '3/4"':   2.235,   # 19.05 mm
    '1"':     3.973,   # 25.40 mm
    '1-1/4"': 6.204,   # 31.75 mm
    '1-3/8"': 7.507,   # 34.93 mm
    '1-1/2"': 8.938,   # 38.10 mm
}
_ACERO_DIAMS = [
    '6', '1/4"',
    '8',
    '3/8"',
    '10',
    '12', '1/2"',
    '5/8"',
    '16',
    '3/4"',
    '19',
    '22',
    '25', '1"',
    '1-1/4"',
    '32',
    '1-3/8"',
    '1-1/2"',
]


def _normalizar_diametro_acero(txt: str) -> str:
    """Normaliza la entrada de diámetro a una clave de `_ACERO_KG_ML`.

    Asume pulgadas cuando el usuario omite la comilla: '1/2' → '1/2\"',
    '1' → '1\"', '1-1/4' → '1-1/4\"'. Los métricos ('6', '12', …) quedan
    igual. Devuelve el texto tal cual si no logra normalizar.
    """
    t = (txt or '').strip().lstrip('ø').strip()
    if not t:
        return ''
    if t in _ACERO_KG_ML:
        return t
    cand = t.rstrip('"').strip() + '"'
    if cand in _ACERO_KG_ML:
        return cand
    return t


# ═══════════════════════════════════════════════════════════════════════════════
class _TreeColorDelegate(QStyledItemDelegate):
    """Pinta columnas del árbol preservando el color de fuente al seleccionar."""

    _SEL_BG   = QColor('#FDEBD0')
    _DEF_TEXT = QColor('#273445')

    def paint(self, painter, option, index):
        painter.save()
        painter.setClipRect(option.rect)

        # 1. Fondo — prioridad: seleccionado > custom BackgroundRole >
        # alternate-row (zebra del QSS) > blanco.
        if option.state & QStyle.State_Selected:
            painter.fillRect(option.rect, self._SEL_BG)
        else:
            bg = index.data(Qt.BackgroundRole)
            if bg and hasattr(bg, 'color') and bg.color().isValid():
                painter.fillRect(option.rect, bg.color())
            elif option.features & QStyleOptionViewItem.Alternate:
                # Respetar alternate-background-color del QSS / QPalette
                painter.fillRect(option.rect, option.palette.alternateBase())
            else:
                painter.fillRect(option.rect, QColor('#FFFFFF'))

        # 2. Texto con color original
        fg = index.data(Qt.ForegroundRole)
        if hasattr(fg, 'color'):
            painter.setPen(fg.color())
        elif isinstance(fg, QColor):
            painter.setPen(fg)
        else:
            painter.setPen(self._DEF_TEXT)

        font = index.data(Qt.FontRole)
        painter.setFont(font if font else option.font)

        text = index.data(Qt.DisplayRole) or ''
        align = index.data(Qt.TextAlignmentRole)
        if align is None:
            align = Qt.AlignLeft | Qt.AlignVCenter
        painter.drawText(option.rect.adjusted(4, 0, -4, 0), align, text)

        painter.restore()


class _PresupuestoTree(QTreeWidget):
    """QTreeWidget con drag & drop interno y renumeración automática de ítems."""

    partidas_reordenadas = Signal()

    def sizeHint(self):
        # Devuelve un tamaño fijo para que el QSplitter no se mueva
        # cuando cambia la altura de filas por word-wrap en descripciones largas
        return QSize(420, 400)

    def minimumSizeHint(self):
        return QSize(200, 100)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)

        # Timer para debounce: renumera solo cuando el usuario termina de soltar
        self._renumber_timer = QTimer(self)
        self._renumber_timer.setSingleShot(True)
        self._renumber_timer.setInterval(120)
        self._renumber_timer.timeout.connect(self._renumerar)

    def drawRow(self, painter, option, index):
        """Rellena el fondo completo de la fila solo para títulos/subtítulos,
        extendiéndolo hasta el borde del viewport para que cubra toda la fila."""
        item = self.itemFromIndex(index)
        # Solo actuar en filas de título (es_titulo = True, UserRole+1)
        if item and item.data(0, Qt.UserRole + 1):
            bg_color = item.background(0).color()
            if bg_color.isValid() and bg_color.alpha() > 0:
                full = option.rect
                full.setLeft(0)
                full.setRight(self.viewport().width())
                painter.fillRect(full, bg_color)
        super().drawRow(painter, option, index)

    def dropEvent(self, event):
        """Acepta el drop y programa la renumeración."""
        super().dropEvent(event)
        self._renumber_timer.start()

    def _renumerar(self):
        """Recorre el árbol y asigna nuevos ítems secuenciales en la BD."""
        conn = get_db()
        offset = self._offset_raiz(conn)
        self._procesar_nivel(self.invisibleRootItem(), "", 1, conn, offset)
        conn.commit()
        conn.close()
        self.partidas_reordenadas.emit()

    def _offset_raiz(self, conn) -> int:
        """Cuenta cuántos ítems raíz (nivel=1) hay en subpresupuestos anteriores
        al activo, para que la numeración continúe en vez de reiniciar en 01."""
        pid = getattr(self, '_proyecto_id', None)
        sub_id = getattr(self, '_sub_ppto_id', None)
        if pid is None or sub_id is None:
            return 0
        row = conn.execute(
            "SELECT COUNT(*) FROM partidas "
            "WHERE proyecto_id=? AND nivel=1 AND ("
            "  sub_presupuesto_id IS NULL OR "
            "  sub_presupuesto_id IN ("
            "    SELECT id FROM sub_presupuestos "
            "    WHERE proyecto_id=? AND orden < ("
            "      SELECT orden FROM sub_presupuestos WHERE id=?"
            "    )"
            "  )"
            ")",
            (pid, pid, sub_id)
        ).fetchone()
        return row[0] if row else 0

    def _procesar_nivel(self, parent_item, prefijo: str, nivel: int, conn,
                        offset: int = 0):
        for i in range(parent_item.childCount()):
            child = parent_item.child(i)
            pid   = child.data(0, Qt.UserRole)
            if pid is None:
                continue

            seq = (i + 1 + offset) if not prefijo else (i + 1)
            num_str = f"{seq:02d}"
            nuevo_item = f"{prefijo}.{num_str}" if prefijo else num_str

            # Actualizar BD
            conn.execute(
                "UPDATE partidas SET item=?, nivel=? WHERE id=?",
                (nuevo_item, nivel, pid)
            )

            # Actualizar texto visible en el árbol sin recargar todo
            child.setText(0, nuevo_item)

            # Procesar hijos recursivamente
            self._procesar_nivel(child, nuevo_item, nivel + 1, conn)


# ═══════════════════════════════════════════════════════════════════════════════
class _DescripcionDelegate(QStyledItemDelegate):
    """Delegate para la columna Descripción del árbol: dibuja texto con word-wrap.

    Calcula la altura necesaria según el ancho actual de la columna,
    permitiendo que los títulos largos ocupen varias líneas.
    """

    def __init__(self, tree, col: int = 1, parent=None):
        super().__init__(parent)
        self._tree = tree
        self._col  = col

    def _indent_px(self, index) -> int:
        """Sangría horizontal según la profundidad del ítem en el árbol,
        para reflejar la jerarquía (igual que la columna ÍTEM). Usa el mismo
        paso de indentación del árbol."""
        depth = 0
        p = index.parent()
        while p.isValid():
            depth += 1
            p = p.parent()
        return depth * self._tree.indentation()

    # ── Pintar ────────────────────────────────────────────────────────────────

    def paint(self, painter: QPainter, option, index):
        if index.column() != self._col:
            super().paint(painter, option, index)
            return

        self.initStyleOption(option, index)
        painter.save()
        painter.setClipRect(option.rect)

        # Fondo (respeta el color del ítem: tinte de nivel > zebra > blanco)
        bg = index.data(Qt.BackgroundRole)
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, QColor("#FDEBD0"))
        elif bg and isinstance(bg, QBrush) and bg.color().isValid():
            painter.fillRect(option.rect, bg.color())
        elif option.features & QStyleOptionViewItem.Alternate:
            painter.fillRect(option.rect, option.palette.alternateBase())
        else:
            painter.fillRect(option.rect, QColor("#FFFFFF"))

        # Fuente y color de texto
        font = index.data(Qt.FontRole)
        painter.setFont(font if font else option.font)

        fg = index.data(Qt.ForegroundRole)
        if fg:
            painter.setPen(fg.color())
        else:
            painter.setPen(QColor("#273445"))

        text = index.data(Qt.DisplayRole) or ""
        rect = option.rect.adjusted(4 + self._indent_px(index), 3, -4, -2)
        painter.drawText(rect,
                         Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap,
                         text)

        # ✓ verde negrita justo después del texto en la primera línea
        if index.data(Qt.UserRole):
            base_font = index.data(Qt.FontRole) or option.font
            chk_font  = QFont(base_font)
            chk_font.setBold(True)
            chk_fm = QFontMetrics(chk_font)
            fm     = QFontMetrics(base_font)

            # Medir cuánto ocupa el texto en la primera línea visual
            col_w = max(rect.width(), 20)
            line  = ''
            for word in text.split():
                candidate = (line + ' ' + word).lstrip()
                if fm.horizontalAdvance(candidate) > col_w:
                    break
                line = candidate
            first_line_w = fm.horizontalAdvance(line) if line else fm.horizontalAdvance(text[:20])

            chk   = " ✓"
            chk_w = chk_fm.horizontalAdvance(chk)
            x     = rect.left() + first_line_w
            y     = rect.top()
            h     = fm.height() + 6

            painter.setFont(chk_font)
            painter.setPen(QColor("#43A047"))
            painter.drawText(x, y, chk_w, h, Qt.AlignLeft | Qt.AlignVCenter, chk)

        painter.restore()

    # ── Tamaño ────────────────────────────────────────────────────────────────

    def sizeHint(self, option, index):
        if index.column() != self._col:
            return super().sizeHint(option, index)

        text = index.data(Qt.DisplayRole) or ""
        if not text:
            return QSize(-1, 20)

        font = index.data(Qt.FontRole) or option.font
        fm   = QFontMetrics(font)
        col_w = max(self._tree.header().sectionSize(self._col) - 8
                    - self._indent_px(index), 60)

        br = fm.boundingRect(QRect(0, 0, col_w, 5000),
                             Qt.AlignLeft | Qt.TextWordWrap,
                             text)
        height = max(20, br.height() + 2)
        return QSize(col_w, height)


# ── Delegate de navegación para planilla de Metrados ─────────────────────────

class _MetNavDelegate(QStyledItemDelegate):
    """Tab/Enter/↑↓ navegación Excel en la planilla de metrados."""
    _LAST_COL = 6   # cols editables: 0–6

    def __init__(self, pview, parent=None):
        super().__init__(parent)
        self._pv = pview

    def createEditor(self, parent, option, index):
        ed = QLineEdit(parent)
        ed.setAlignment(Qt.AlignLeft | Qt.AlignVCenter if index.column() == 0
                        else Qt.AlignRight | Qt.AlignVCenter)
        ed.setStyleSheet('background:white; border:2px solid #F37329;'
                         ' border-radius:2px; padding:0 4px; font-size:11px;')
        self._nav(ed, index.row(), index.column())
        return ed

    def setEditorData(self, editor, index):
        txt = index.data() or ''
        # Mostrar número sin separador de miles para editar más fácilmente
        if index.column() > 0:
            txt = txt.replace(',', '')
        editor.setText(txt)
        editor.selectAll()

    def _nav(self, ed, row, col):
        pv  = self._pv
        tbl = pv.tbl_met
        LC  = self._LAST_COL

        def commit():
            self.commitData.emit(ed)
            self.closeEditor.emit(ed, QAbstractItemDelegate.EndEditHint.NoHint)

        def goto(nr, nc):
            if nr < 0:
                return
            if nr >= tbl.rowCount():
                pv._metrado_nueva_fila()
            def _open():
                idx = tbl.model().index(nr, nc)
                tbl.setCurrentIndex(idx)
                tbl.edit(idx)
            QTimer.singleShot(0, _open)

        class _Nav(QObject):
            def eventFilter(s, obj, ev):
                if ev.type() != QEvent.Type.KeyPress:
                    return False
                k = ev.key()
                m = ev.modifiers()
                if k in (Qt.Key_Tab, Qt.Key_Backtab):
                    bk = k == Qt.Key_Backtab or bool(m & Qt.ShiftModifier)
                    commit()
                    nc, nr = (col-1, row) if bk else (col+1, row)
                    if nc < 0:    nc, nr = LC,  row-1
                    elif nc > LC: nc, nr = 0,   row+1
                    goto(nr, nc); return True
                if k in (Qt.Key_Return, Qt.Key_Enter):
                    bk = bool(m & Qt.ShiftModifier)
                    commit(); goto(row-1 if bk else row+1, col); return True
                if k == Qt.Key_Down:
                    commit(); goto(row+1, col); return True
                if k == Qt.Key_Up:
                    commit(); goto(row-1, col); return True
                if k == Qt.Key_Right:
                    nc = col+1
                    if nc > LC: nc, nr = 0, row+1
                    else: nr = row
                    commit(); goto(nr, nc); return True
                if k == Qt.Key_Left:
                    nc = col-1
                    if nc < 0: nc, nr = LC, row-1
                    else: nr = row
                    commit(); goto(nr, nc); return True
                return False

        ed._filt = _Nav(ed)
        ed.installEventFilter(ed._filt)


# ── Delegate de navegación para planilla de Acero ────────────────────────────

class _AceroNavDelegate(QStyledItemDelegate):
    """Tab/Enter/↑↓←→ en planilla de acero (cols 1,3-6,8)."""
    _COLS = [1, 2, 3, 4, 5, 6, 8]   # orden de navegación (2=combobox externo)

    def __init__(self, pview, parent=None):
        super().__init__(parent)
        self._pv = pview

    def createEditor(self, parent, option, index):
        ed = QLineEdit(parent)
        c  = index.column()
        ed.setAlignment(Qt.AlignLeft | Qt.AlignVCenter if c == 1
                        else Qt.AlignRight | Qt.AlignVCenter)
        ed.setStyleSheet('background:white; border:2px solid #F37329;'
                         ' border-radius:2px; padding:0 4px; font-size:11px;')
        self._nav(ed, index.row(), c)
        return ed

    def setEditorData(self, editor, index):
        txt = index.data() or ''
        if index.column() > 1:
            txt = txt.replace(',', '')
        editor.setText(txt)
        editor.selectAll()

    def _nav(self, ed, row, col):
        pv   = self._pv
        COLS = self._COLS

        def commit():
            self.commitData.emit(ed)
            self.closeEditor.emit(ed, QAbstractItemDelegate.EndEditHint.NoHint)

        class _Nav(QObject):
            def eventFilter(s, obj, ev):
                if ev.type() != QEvent.Type.KeyPress: return False
                k = ev.key()
                m = ev.modifiers()
                try: ci = COLS.index(col)
                except ValueError: ci = 0

                if k in (Qt.Key_Tab, Qt.Key_Backtab):
                    bk = k == Qt.Key_Backtab or bool(m & Qt.ShiftModifier)
                    commit()
                    nc, nr = (COLS[ci-1], row) if bk and ci > 0 else \
                             (COLS[-1], row-1) if bk else \
                             (COLS[ci+1], row) if ci < len(COLS)-1 else \
                             (COLS[0], row+1)
                    QTimer.singleShot(0, lambda nc=nc, nr=nr: pv._acero_ir_a(nr, nc))
                    return True
                if k in (Qt.Key_Return, Qt.Key_Enter):
                    commit(); QTimer.singleShot(0, lambda: pv._acero_ir_a(row+1, col)); return True
                if k == Qt.Key_Down:
                    commit(); QTimer.singleShot(0, lambda: pv._acero_ir_a(row+1, col)); return True
                if k == Qt.Key_Up:
                    commit(); QTimer.singleShot(0, lambda: pv._acero_ir_a(row-1, col)); return True
                if k == Qt.Key_Right:
                    nc, nr = (COLS[ci+1], row) if ci < len(COLS)-1 else (COLS[0], row+1)
                    commit(); QTimer.singleShot(0, lambda nc=nc, nr=nr: pv._acero_ir_a(nr, nc)); return True
                if k == Qt.Key_Left:
                    nc, nr = (COLS[ci-1], row) if ci > 0 else (COLS[-1], row-1)
                    commit(); QTimer.singleShot(0, lambda nc=nc, nr=nr: pv._acero_ir_a(nr, nc)); return True
                return False

        ed._filt = _Nav(ed)
        ed.installEventFilter(ed._filt)


# ── Delegate para edición inline del Metrado (con ✓ a la derecha) ────────────

class _MetradoDelegate(QStyledItemDelegate):

    navigate = Signal(int)   # +1 = siguiente, -1 = anterior

    def eventFilter(self, editor, event):
        if event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key_Down:
                self.commitData.emit(editor)
                self.closeEditor.emit(editor, QStyledItemDelegate.EndEditHint.NoHint)
                self.navigate.emit(1)
                return True
            if event.key() == Qt.Key_Up:
                self.commitData.emit(editor)
                self.closeEditor.emit(editor, QStyledItemDelegate.EndEditHint.NoHint)
                self.navigate.emit(-1)
                return True
        return super().eventFilter(editor, event)

    def paint(self, painter, option, index):
        has_planilla = bool(index.data(Qt.UserRole))
        sel          = bool(option.state & QStyle.StateFlag.State_Selected)
        painter.save()

        # Fondo — preservar colores de nivel igual que _TreeColorDelegate
        # (incluye zebra alt-row del QSS)
        if sel:
            painter.fillRect(option.rect, QColor("#FDEBD0"))
        else:
            bg = index.data(Qt.BackgroundRole)
            if bg and hasattr(bg, 'color') and bg.color().isValid():
                painter.fillRect(option.rect, bg.color())
            elif option.features & QStyleOptionViewItem.Alternate:
                painter.fillRect(option.rect, option.palette.alternateBase())
            else:
                painter.fillRect(option.rect, QColor("#FFFFFF"))

        font = index.data(Qt.FontRole) or option.font
        fg   = index.data(Qt.ForegroundRole)
        painter.setFont(font)
        if fg and hasattr(fg, 'color'):
            painter.setPen(fg.color())
        else:
            painter.setPen(QColor("#273445"))

        if not has_planilla:
            # Solo el número, sin check
            painter.drawText(option.rect.adjusted(0, 0, -4, 0),
                             Qt.AlignRight | Qt.AlignVCenter,
                             index.data(Qt.DisplayRole) or "")
            painter.restore()
            return

        # Con planilla: número + ✓ verde al extremo derecho
        chk_font = QFont(font)
        chk_font.setBold(True)
        chk_w = QFontMetrics(chk_font).horizontalAdvance("✓") + 6

        text_rect = option.rect.adjusted(0, 0, -chk_w, 0)
        painter.drawText(text_rect, Qt.AlignRight | Qt.AlignVCenter,
                         index.data(Qt.DisplayRole) or "")

        painter.setFont(chk_font)
        painter.setPen(QColor("#43A047"))
        chk_rect = QRect(option.rect.right() - chk_w + 2,
                         option.rect.top(), chk_w, option.rect.height())
        painter.drawText(chk_rect, Qt.AlignLeft | Qt.AlignVCenter, "✓")

        painter.restore()

    def createEditor(self, parent, option, index):
        ed = QLineEdit(parent)
        ed.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        ed.setStyleSheet(
            "QLineEdit { background: white; border: 2px solid #F37329;"
            " border-radius: 4px; padding: 0 6px; font-size: 13px;"
            " color: #273445; }"
        )
        return ed

    def setEditorData(self, editor, index):
        text = (index.data(Qt.DisplayRole) or "").replace(',', '').strip()
        editor.setText(text)
        editor.selectAll()

    def setModelData(self, editor, model, index):
        text = editor.text().strip().replace(',', '.')
        try:
            val = float(text)
            dec = get_decimales_metrado()
            model.setData(index, f"{val:,.{dec}f}", Qt.EditRole)
        except ValueError:
            pass



class _RubDragList(QListWidget):
    """QListWidget con arrastrar-y-soltar interno para reordenar plantillas."""
    reordered        = Signal()
    delete_requested = Signal(int)   # fila actual

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setContextMenuPolicy(Qt.CustomContextMenu)

    def dropEvent(self, event):
        super().dropEvent(event)
        self.reordered.emit()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            row = self.currentRow()
            if row >= 0:
                self.delete_requested.emit(row)
        else:
            super().keyPressEvent(event)

class _GGDelegate(QStyledItemDelegate):
    """Delegate Excel-like para la tabla de Gastos Generales.
    Col 1 (UND): QLineEdit con QCompleter de unidades comunes.
    Tab/Backtab navegan entre celdas editables; Enter/Return baja una fila.
    """
    _SKIP = {5, 6}    # columnas no editables: Total(calc), botón eliminar
    _UNIDADES = [
        "MES", "DÍA", "HORA", "SEM", "QNA", "AÑO",
        "GLB", "UND", "VJE", "KIT", "JGO", "EST", "VECES",
        "GAL", "LT", "M3", "KG", "TN",
    ]

    # UND usa el editor de texto por defecto (QLineEdit simple)


    def eventFilter(self, editor, event):
        if event.type() == QEvent.KeyPress:
            tbl = self.parent()
            key = event.key()
            cur   = tbl.currentIndex()
            row   = cur.row()
            col   = cur.column()
            n_col = tbl.columnCount()
            n_row = tbl.rowCount()

            # ← →: solo navegan si el cursor está en el borde del texto
            go_left  = (key == Qt.Key_Left  and
                        isinstance(editor, QLineEdit) and
                        editor.cursorPosition() == 0 and not editor.hasSelectedText())
            go_right = (key == Qt.Key_Right and
                        isinstance(editor, QLineEdit) and
                        editor.cursorPosition() == len(editor.text()) and
                        not editor.hasSelectedText())

            if key in (Qt.Key_Tab, Qt.Key_Backtab, Qt.Key_Return, Qt.Key_Enter,
                       Qt.Key_Up, Qt.Key_Down) or go_left or go_right:
                self.commitData.emit(editor)
                self.closeEditor.emit(editor, QStyledItemDelegate.NoHint)

                if key == Qt.Key_Up:
                    nrow = row - 1
                    if nrow >= 0:
                        tbl.setCurrentCell(nrow, col)
                        if col not in self._SKIP:
                            tbl.edit(tbl.model().index(nrow, col))
                elif key in (Qt.Key_Down, Qt.Key_Return, Qt.Key_Enter):
                    nrow = row + 1
                    if nrow < n_row:
                        tbl.setCurrentCell(nrow, col)
                        if col not in self._SKIP:
                            tbl.edit(tbl.model().index(nrow, col))
                else:  # Tab, Shift+Tab, ← →
                    back = (key == Qt.Key_Backtab or go_left)
                    nc, nr = col, row
                    for _ in range(n_col * n_row + 1):
                        nc += -1 if back else 1
                        if nc < 0:
                            nc = n_col - 1; nr -= 1
                        elif nc >= n_col:
                            nc = 0; nr += 1
                        if nr < 0 or nr >= n_row:
                            break
                        if nc in self._SKIP:
                            continue
                        it = tbl.item(nr, nc)
                        if it and (it.flags() & Qt.ItemIsEditable):
                            tbl.setCurrentCell(nr, nc)
                            tbl.edit(tbl.model().index(nr, nc))
                            break
                return True
        return super().eventFilter(editor, event)


class _StyledLineEdit(QLineEdit):
    """QLineEdit con menú contextual estilizado (evita menú negro en GTK)."""
    def contextMenuEvent(self, event):
        menu = self.createStandardContextMenu()
        menu.exec(event.globalPos())

class _HandleDragFilter(QObject):
    """Detecta arrastre desde el handle ⠿ e inicia drag en el QListWidget padre."""
    def __init__(self, list_widget, row_idx: int, parent=None):
        super().__init__(parent)
        self._list      = list_widget
        self._row_idx   = row_idx
        self._press_pos = None

    def eventFilter(self, obj, event):
        t = event.type()
        if t == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            self._press_pos = event.pos()
            self._list.setCurrentRow(self._row_idx)
            return False
        if t == QEvent.MouseMove and self._press_pos is not None:
            if ((event.pos() - self._press_pos).manhattanLength()
                    >= QApplication.startDragDistance()):
                self._press_pos = None
                self._list.setCurrentRow(self._row_idx)
                self._list.startDrag(Qt.MoveAction)
                return True
        if t == QEvent.MouseButtonRelease:
            self._press_pos = None
        return False



class ProyectoView(QWidget):
# ═══════════════════════════════════════════════════════════════════════════════

    editar_proyecto_solicitado = Signal(int)   # pid → MainWindow abre NuevoProyectoView en modo editar
    cambiar_a_proyecto         = Signal(int)   # pid → MainWindow activa otra pestaña
    cerrar_proyecto            = Signal(int)   # pid → MainWindow cierra esta pestaña
    ir_a_proyectos             = Signal()      # → MainWindow navega al dashboard
    toggle_sidebar             = Signal()      # → MainWindow muestra/oculta sidebar
    # Atajos a vistas globales desde la toolbar interna del proyecto
    ir_a_indices_inei          = Signal()      # → MainWindow navega a Índices INEI
    ir_a_ia                    = Signal()      # → MainWindow navega a IA / API Key
    ir_a_configuracion         = Signal()      # → MainWindow navega a Configuración
    ir_a_nuevo_proyecto        = Signal()      # → MainWindow abre el formulario de nuevo proyecto
    ir_a_importar              = Signal()      # → MainWindow navega a Importar
    ir_a_acerca                = Signal()      # → MainWindow navega a Acerca de

    def __init__(self, proyecto_id: int, usuario: Usuario, parent=None):
        super().__init__(parent)
        self.pid      = proyecto_id
        self.usuario  = usuario
        self._proy    = self._cargar_proyecto()
        # Memoria Tuxia: registrar el último proyecto abierto + timestamp
        try:
            from PySide6.QtCore import QSettings as _QS
            from datetime import datetime as _dt
            _qs = _QS("ingePresupuestos", "tuxia")
            _qs.setValue("last_proyecto_id", int(proyecto_id))
            _qs.setValue("last_proyecto_at",
                         _dt.now().isoformat(timespec='seconds'))
        except Exception:
            pass
        self._moneda  = self._proy.get('moneda', 'Soles')
        # Estado del proyecto + flags granulares por nivel (espejo del Flask
        # original):
        #   _ed_presupuesto → tree, ACU, metrados, sub-presupuestos
        #   _ed_pie         → pie_rubros, GG, IGV
        #   _ed_specs       → especificaciones técnicas
        #   _ed_cronograma  → barras Gantt, valorizado
        # Excepción: rol 'invitado' fuerza todo a solo lectura.
        self._recalcular_estado_flags()
        self._sub_ppto_id: int | None = None
        self._partida_actual_id: int | None = None
        # Partida cuyas filas están cargadas en el panel Metrados/Acero. Puede
        # diferir de _partida_actual_id: el panel solo se recarga con el tab
        # Metrados visible, así que los guardados deben escribir a esta partida.
        self._met_panel_pid: int | None = None
        self._acu_clipboard: list[dict] = []   # items copiados {recurso_id, cuadrilla, cantidad, precio}
        self._acu_loading = False
        self._met_loading = False
        self._spec_modificada = False
        self._con_planilla: set[int] = set()

        self._layout_user_set = False
        self._build_ui()
        self._restaurar_splitters()
        self._cargar_sub_pptos()
        # Cadena diferida: (1) la pestaña ya es visible con el árbol del
        # presupuesto; (2) a los 30 ms se construye el panel de tabs (lo
        # caro) y recién entonces (3) se cargan los datos. El usuario
        # percibe apertura inmediata.
        QTimer.singleShot(30, self._completar_panel_tabs)
        if not self._editable:
            self._aplicar_modo_solo_lectura()
        # Asistente Tuxia flotante en la esquina inferior derecha.
        # Opt-in: se muestra solo si el usuario lo activó en
        # Configuración → General → "Asistente Tuxia".
        # Si está apagado NO seteamos el atributo: los guards repartidos
        # por la vista usan `hasattr(self, '_tuxia')` y así devuelven False
        # de forma consistente, sin importar si el guard también verifica
        # `is not None` o no.
        from core.database import get_config as _gc_tuxia
        if _gc_tuxia('mostrar_tuxia', '1') == '1':
            self._tuxia = _TuxiaHelper(self)
            self._tuxia.chat_solicitado.connect(self._abrir_asistente_ia)
            self._tuxia.accion_solicitada.connect(self._on_tuxia_accion)
            QTimer.singleShot(300, self._tuxia_check_proyecto)
            # Recordatorio de backup cada 45 minutos de actividad continuada
            self._backup_timer = QTimer(self)
            self._backup_timer.setInterval(45 * 60 * 1000)
            self._backup_timer.timeout.connect(self._tuxia_recordar_backup)
            self._backup_timer.start()

    # ══════════════════════════════════════════════════════════════════════════
    # Datos
    # ══════════════════════════════════════════════════════════════════════════

    # ── Estado / solo lectura ─────────────────────────────────────────────

    def _aplicar_modo_solo_lectura(self):
        """Aplica a los widgets el estado editable/solo-lectura según las
        banderas actuales. REVERSIBLE: si el proyecto volvió a ser editable
        (p.ej. aprobado → elaboración vía «Editar»), re-habilita los widgets;
        si dejó de serlo, los bloquea. Los flags ItemIsEditable por item/celda
        se re-aplican al recargar cada tab (`recargar_partidas`, etc.); aquí se
        ajustan los editTriggers a nivel widget, el drag-drop y el readOnly de
        las specs."""
        try:
            ed = self._ed_presupuesto
            # Árbol: el doble-clic se maneja por handler (NoEditTriggers
            # siempre); el lock real es drag-drop + flags (estos últimos los
            # re-aplica recargar_partidas según _ed_presupuesto).
            if hasattr(self, 'tree') and self.tree:
                self.tree.setDragDropMode(
                    QAbstractItemView.InternalMove if ed
                    else QAbstractItemView.NoDragDrop)
                if not ed:
                    self._strip_tree_editable_flags()
            # Metrados/Acero se editan por doble-clic → restaurar el trigger.
            met_acero_triggers = (
                QAbstractItemView.DoubleClicked
                | QAbstractItemView.SelectedClicked
            )
            for nombre in ('tbl_met', 'tbl_acero'):
                tbl = getattr(self, nombre, None)
                if tbl is not None:
                    tbl.setEditTriggers(
                        met_acero_triggers if ed
                        else QAbstractItemView.NoEditTriggers)
                    if not ed:
                        self._strip_table_editable_flags(tbl)
            # ACU/Insumos se editan por handlers (NoEditTriggers siempre);
            # en solo-lectura además se les quita el flag de celda.
            if not ed:
                for nombre in ('tbl_acu', 'tbl_ins'):
                    tbl = getattr(self, nombre, None)
                    if tbl is not None:
                        tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
                        self._strip_table_editable_flags(tbl)
            # Specs y memoria descriptiva (nivel «specs»).
            for nombre in ('spec_edit', 'txt_spec', 'txt_memoria'):
                w = getattr(self, nombre, None)
                if w is not None and hasattr(w, 'setReadOnly'):
                    w.setReadOnly(not self._ed_specs)
        except Exception:
            pass

    def _strip_tree_editable_flags(self):
        """Walk del árbol removiendo el flag ItemIsEditable de cada item."""
        def _walk(parent):
            for i in range(parent.childCount()):
                child = parent.child(i)
                child.setFlags(child.flags() & ~Qt.ItemIsEditable)
                _walk(child)
        if hasattr(self, 'tree') and self.tree:
            _walk(self.tree.invisibleRootItem())

    def _strip_table_editable_flags(self, tbl):
        """Quita el flag ItemIsEditable de todas las celdas de una tabla."""
        for r in range(tbl.rowCount()):
            for c in range(tbl.columnCount()):
                it = tbl.item(r, c)
                if it is not None:
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)

    def _require_editable(self, accion: str = 'esta acción',
                          nivel: str = 'presupuesto') -> bool:
        """Devuelve True si el nivel está editable en el estado actual.
        Si no, muestra mensaje contextual y devuelve False. Niveles:
        'presupuesto' | 'pie' | 'specs' | 'cronograma'.
        """
        # Verificar el estado REAL en la BD antes de autorizar: el estado
        # puede haber cambiado por fuera de esta vista (badge de la card en
        # Inicio con el proyecto ya abierto en pestaña) y los flags cacheados
        # quedarían diciendo «editable» cuando ya no lo es.
        try:
            conn = get_db()
            row = conn.execute("SELECT estado FROM proyectos WHERE id=?",
                               (self.pid,)).fetchone()
            conn.close()
            if row and (row['estado'] or 'elaboracion') != self._estado:
                self._proy['estado'] = row['estado']
                self._recalcular_estado_flags()
                self._aplicar_modo_solo_lectura()
                if not self._ed_presupuesto:
                    for b in ('btn_ins_unificar', 'btn_ins_pu_acu'):
                        if hasattr(self, b):
                            getattr(self, b).setVisible(False)
        except Exception:
            pass
        flag = {
            'presupuesto': self._ed_presupuesto,
            'pie':         self._ed_pie,
            'specs':       self._ed_specs,
            'cronograma':  self._ed_cronograma,
        }.get(nivel, True)
        if flag:
            return True
        from core.config import ESTADOS_PROYECTO_NOMBRE
        estado_n = ESTADOS_PROYECTO_NOMBRE.get(self._estado, self._estado)
        # Listar lo que SÍ se puede editar en el estado actual.
        editables = [n for f, n in (
            (self._ed_presupuesto, "Presupuesto (partidas, ACU, metrados)"),
            (self._ed_pie,         "Pie de presupuesto"),
            (self._ed_specs,       "Especificaciones técnicas"),
            (self._ed_cronograma,  "Cronograma"),
        ) if f]
        if editables:
            puedes = ("En «" + estado_n + "» todavía puedes editar:\n  • "
                      + "\n  • ".join(editables))
        else:
            puedes = ("En «" + estado_n + "» el proyecto es de solo lectura "
                      "(no se puede editar contenido).")
        QMessageBox.information(
            self, "Operación no permitida",
            f"Esta acción no se puede realizar mientras el proyecto está "
            f"«{estado_n}».\n\n"
            f"{puedes}\n\n"
            f"Para {accion}, cambia el estado a «En elaboración» desde el "
            f"chip de estado (arriba a la derecha)."
        )
        return False

    def _cargar_proyecto(self) -> dict:
        conn = get_db()
        row = conn.execute("SELECT * FROM proyectos WHERE id=?", (self.pid,)).fetchone()
        conn.close()
        return dict(row) if row else {}

    def _total_proyecto(self, all_subs: bool = False) -> float:
        """Suma de parciales redondeados al mismo número de decimales que se muestra,
        para que el total coincida exactamente con la suma visual del presupuesto.
        all_subs=True suma todos los subpresupuestos (CD global del proyecto)."""
        dec = get_decimales_ppto()
        conn = get_db()
        if all_subs:
            rows = conn.execute(
                "SELECT metrado, precio_unitario FROM partidas "
                "WHERE proyecto_id=? AND es_titulo=0",
                (self.pid,)
            ).fetchall()
        elif self._sub_ppto_id is None:
            rows = conn.execute(
                "SELECT metrado, precio_unitario FROM partidas "
                "WHERE proyecto_id=? AND es_titulo=0 AND sub_presupuesto_id IS NULL",
                (self.pid,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT metrado, precio_unitario FROM partidas "
                "WHERE proyecto_id=? AND es_titulo=0 AND sub_presupuesto_id=?",
                (self.pid, self._sub_ppto_id)
            ).fetchall()
        conn.close()
        return sum(parcial_wysiwyg(r['metrado'], r['precio_unitario'], dec) for r in rows)

    # ══════════════════════════════════════════════════════════════════════════
    # Build UI
    # ══════════════════════════════════════════════════════════════════════════

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Stack raíz: page 0 = vista normal, page 1 = Pie full-page
        from PySide6.QtWidgets import QStackedWidget
        self._root_stack = QStackedWidget()

        # Topbar PERSISTENTE (logo + pestañas de proyectos + estado + total):
        # vive ARRIBA del _root_stack, no dentro de la página de presupuesto, así
        # las pestañas de proyectos siguen visibles al entrar a Cronograma /
        # Metrados / Pie / Reportes (que se anclan al stack). El sub-view trae su
        # propia barra «← Presupuesto» debajo de esta.
        root.addWidget(self._make_topbar())

        # ── Página 0: vista normal ────────────────────────────────────────────
        main_w = QWidget()
        main_vl = QVBoxLayout(main_w)
        main_vl.setContentsMargins(0, 0, 0, 0)
        main_vl.setSpacing(0)
        main_vl.addWidget(self._make_toolbar())
        self.hsplit = QSplitter(Qt.Horizontal)
        self.hsplit.setHandleWidth(3)
        self.hsplit.addWidget(self._make_panel_presupuesto())
        # El panel de tabs (ACU/Insumos/…) cuesta ~0.9 s de construcción
        # (medido): entra DIFERIDO vía _completar_panel_tabs para que la
        # pestaña aparezca ya con el árbol del presupuesto (~0.3 s).
        self._panel_tabs_ph = QWidget()
        self.hsplit.addWidget(self._panel_tabs_ph)
        self.hsplit.setStretchFactor(0, 55)
        self.hsplit.setStretchFactor(1, 45)
        main_vl.addWidget(self.hsplit, stretch=1)
        self._root_stack.addWidget(main_w)

        # ── Página 1: Pie de Presupuesto full-page ────────────────────────────
        self._root_stack.addWidget(self._make_pie_page())

        # ── Página 2: Cronograma — lazy, se crea al primer uso ────────────────
        self._cron_view = None
        # ── Control de Obra (valorizaciones…) — lazy ──────────────────────────
        self._control_view = None
        # ── Página 3: Centro de Reportes — lazy, se crea al primer uso ────────
        self._reportes_view = None

        # Ocultar Tuxia cuando se navega fuera de la vista principal (el icono
        # flotante no tiene sentido en reportes/cronograma/pie/etc.)
        self._root_stack.currentChanged.connect(self._on_root_stack_changed)

        root.addWidget(self._root_stack)

        # ── Atajos globales (cualquier widget de la ventana) ─────────────────
        QShortcut(QKeySequence("F5"),        self, self.recalcular)
        QShortcut(QKeySequence("Delete"),    self, self._supr_partida_seleccionada)
        QShortcut(QKeySequence("Escape"),    self, self._deseleccionar)
        QShortcut(QKeySequence("F1"),        self, self._mostrar_atajos)
        QShortcut(QKeySequence("Ctrl+F"),    self, self._focus_buscar)
        QShortcut(QKeySequence("Ctrl+Home"), self, self._ir_a_primera)
        QShortcut(QKeySequence("Ctrl+End"),  self, self._ir_a_ultima)

        # ── Atajos del árbol (solo con foco en el árbol o sus hijos) ─────────
        # Limitados a WidgetWithChildrenShortcut para no chocar con Ctrl+C/V/X
        # de celdas de tablas (ACU, Metrados, Acero, Insumos).
        def _sc_tree(seq, slot):
            sc = QShortcut(QKeySequence(seq), self.tree, slot)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            return sc

        _sc_tree(QKeySequence.Copy,  self._copiar_partidas_seleccionadas)
        _sc_tree(QKeySequence.Paste, self._pegar_partidas_clipboard)
        _sc_tree(QKeySequence.Cut,   self._cortar_partidas_seleccionadas)
        _sc_tree("Ins",        self._nueva_partida)         # Insertar partida
        _sc_tree("Ctrl+Ins",   self._nuevo_titulo)          # Insertar título
        _sc_tree("F2",         self._editar_partida_actual) # Renombrar/editar
        _sc_tree("Ctrl+D",     self._duplicar_actual)       # Duplicar
        _sc_tree("Alt+Up",     self._mover_arriba)
        _sc_tree("Alt+Down",   self._mover_abajo)
        _sc_tree("Alt+Right",  self._bajar_nivel)           # Indent
        _sc_tree("Alt+Left",   self._subir_nivel)           # Outdent

    # ── Topbar ────────────────────────────────────────────────────────────────

    def _make_topbar(self) -> QFrame:
        bar = QFrame()
        bar.setFixedHeight(44)
        bar.setStyleSheet(f"background:{SLATE_700};")
        hl = QHBoxLayout(bar)
        hl.setContentsMargins(6, 0, 14, 0)
        hl.setSpacing(4)

        # ── Botón logo (toggle sidebar) — visible cuando sidebar está oculto ──
        from core.config import BASE_DIR as _BASE_DIR
        self._btn_sb = QPushButton()
        self._btn_sb.setFixedSize(40, 36)
        self._btn_sb.setCursor(Qt.PointingHandCursor)
        from utils.tooltip import set_tooltip as _stt
        _stt(self._btn_sb, "Mostrar menú lateral")
        self._btn_sb.setStyleSheet(
            "QPushButton { background:transparent; border:none; border-radius:6px; }"
            "QPushButton:hover { background:rgba(255,255,255,0.15); }"
        )
        from core.config import get_product_icon_path as _get_prod_icon
        _icon_path = _get_prod_icon()
        if _icon_path and _icon_path.exists():
            from PySide6.QtGui import QIcon as _QIcon
            self._btn_sb.setIcon(_QIcon(str(_icon_path)))
            self._btn_sb.setIconSize(QSize(28, 28))
        self._btn_sb.setVisible(False)   # oculto por defecto (sidebar visible)
        self._btn_sb.clicked.connect(self.toggle_sidebar.emit)
        hl.addWidget(self._btn_sb)

        # ── Barra de pestañas de proyectos abiertos ───────────────────────────
        self._tabs_proy_frame = QFrame()
        self._tabs_proy_frame.setStyleSheet("background:transparent; border:none;")
        self._tabs_proy_hl = QHBoxLayout(self._tabs_proy_frame)
        self._tabs_proy_hl.setContentsMargins(0, 0, 0, 0)
        self._tabs_proy_hl.setSpacing(2)
        self._construir_tab_simple()
        hl.addWidget(self._tabs_proy_frame, stretch=1)

        hl.addStretch(0)

        # Pill de estado del proyecto: SIEMPRE visible (incl. elaboración).
        # Es un botón con menú desplegable para cambiar el estado rápido sin
        # ir a «Editar». _refrescar_pill_estado() ajusta texto/color/estado.
        self._pill_estado = QPushButton()
        self._pill_estado.setCursor(Qt.PointingHandCursor)
        self._pill_estado.clicked.connect(self._menu_cambiar_estado)
        hl.addWidget(self._pill_estado)
        hl.addSpacing(10)
        self._refrescar_pill_estado()

        lbl_tt = QLabel("TOTAL")
        lbl_tt.setStyleSheet(f"color:{SLATE_100}; font-size:10px; letter-spacing:0.5px; border:none;")
        hl.addWidget(lbl_tt)

        self.lbl_total = QLabel("—")
        self.lbl_total.setStyleSheet("color:#F9C440; font-size:15px; font-weight:700; border:none;")
        hl.addWidget(self.lbl_total)

        return bar

    # ── Toolbar ───────────────────────────────────────────────────────────────

    def _make_toolbar(self) -> QFrame:
        bar = QFrame()
        bar.setFixedHeight(34)
        bar.setStyleSheet(f"background:{SLATE_500};")
        hl = QHBoxLayout(bar)
        hl.setContentsMargins(6, 0, 6, 0)
        hl.setSpacing(0)

        def _tbtn(label, handler, color="white", sep_after=False, menu=None):
            b = QPushButton(label)
            b.setCursor(Qt.PointingHandCursor)
            # Hover: pill rounded translúcido, mismo lenguaje visual que las
            # pestañas internas (ACU/Insumos/Metrados/…). Sin línea inferior
            # — ese patrón se sentía "navegador antiguo" y chocaba con el
            # resto de la app.
            css = (
                f"QPushButton {{ color:{color}; background:transparent;"
                f" border:none; border-radius:6px;"
                f" padding:4px 10px; font-size:11px; font-weight:500; }}"
                f"QPushButton:hover {{ background:rgba(255,255,255,0.12);"
                f" color:white; }}"
                f"QPushButton:pressed {{ background:rgba(255,255,255,0.22); }}"
            )
            if menu is not None:
                # Sin indicador default ▾ — el texto ya lo lleva si aplica.
                css += "QPushButton::menu-indicator { image:none; width:0; }"
                b.setMenu(menu)
            else:
                b.clicked.connect(handler)
            b.setStyleSheet(css)
            hl.addWidget(b)
            if sep_after:
                s = QFrame(); s.setFrameShape(QFrame.VLine)
                s.setFixedWidth(1); s.setFixedHeight(18)
                s.setStyleSheet("color:#667885;")
                hl.addWidget(s)
            return b

        from utils.i18n import tr as _tr
        _tbtn(_tr("Inicio"),      lambda: self.ir_a_proyectos.emit(), sep_after=True)
        _tbtn(f"{_tr('Archivo')} ▾", None, sep_after=True, menu=self._build_archivo_menu())
        _tbtn(_tr("Editar"),      self._editar_proyecto)
        _tbtn(_tr("Reportes"),    self._abrir_centro_reportes, sep_after=True)
        _tbtn(_tr("Metrados"),    self._ir_metrados)
        _tbtn(f"{_tr('Cronogramas')} ▾", None, menu=self._build_cronograma_menu())
        _tbtn("Control de Obra ▾", None, menu=self._build_control_obra_menu())
        _tbtn(_tr("Fórmula Polinómica"), self._ir_formula)
        _tbtn("Pie", self._ir_pie, sep_after=True)
        _tbtn("IA ▾", None, menu=self._build_ia_menu())

        hl.addStretch()

        # ── Atajos globales al lado derecho ──────────────────────────────────
        # Solo lo más útil estando dentro de un proyecto: INEI (para fórmula
        # polinómica y reajuste). Configuración ahora vive en Archivo ▾.
        sep_global = QFrame()
        sep_global.setFrameShape(QFrame.VLine)
        sep_global.setFixedWidth(1); sep_global.setFixedHeight(18)
        sep_global.setStyleSheet(
            f"color:{SLATE_300}; background:transparent;"
        )
        hl.addWidget(sep_global)

        _tbtn("Índices", lambda: self.ir_a_indices_inei.emit())
        _tbtn("?",       None, menu=self._build_ayuda_menu())

        return bar

    # ══════════════════════════════════════════════════════════════════════════
    # Panel izquierdo: PRESUPUESTO
    # ══════════════════════════════════════════════════════════════════════════

    def _make_panel_presupuesto(self) -> QFrame:
        from utils.i18n import tr as _tr_b
        frame = QFrame()
        frame.setStyleSheet("background:white; border:none;")
        vl = QVBoxLayout(frame)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)

        # Barra de acciones del presupuesto
        hdr = QFrame()
        hdr.setFixedHeight(36)
        hdr.setStyleSheet(
            f"background:{SLATE_500}; border-bottom:1px solid {SLATE_700};"
        )
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(8, 0, 8, 0)
        hl.setSpacing(6)

        def _abtn(label, handler, bg=BLUE_500, hover=BLUE_700):
            b = QPushButton(label)
            b.setFixedHeight(26)
            b.setStyleSheet(
                f"QPushButton {{ background:{bg}; color:white; border:none;"
                f" border-radius:6px; font-size:11px; font-weight:700; padding:0 10px; }}"
                f"QPushButton:hover {{ background:{hover}; }}"
            )
            b.clicked.connect(handler)
            return b

        hl.addWidget(_abtn("+ " + _tr_b("Partida"), self._nueva_partida,
                           bg=BLUE_500,   hover=BLUE_700))
        hl.addWidget(_abtn("+ " + _tr_b("Título"),  self._nuevo_titulo,
                           bg=SLATE_700,  hover="#1a2535"))

        # Botones de desplazamiento ↑ ↓
        def _mbtn(label, handler):
            b = QPushButton(label)
            b.setFixedSize(26, 26)
            tips = {"↑": _tr_b("Subir"), "↓": _tr_b("Bajar"),
                    "←": _tr_b("Subir nivel"), "→": _tr_b("Bajar nivel")}
            b.setToolTip(tips.get(label, label))
            b.setStyleSheet(
                f"QPushButton {{ background:rgba(255,255,255,0.12); color:white; border:none;"
                f" border-radius:4px; font-size:13px; font-weight:700; min-height:0; padding:0; }}"
                f"QPushButton:hover {{ background:rgba(255,255,255,0.25); }}"
            )
            b.clicked.connect(handler)
            return b

        hl.addWidget(_mbtn("↑", self._mover_arriba))
        hl.addWidget(_mbtn("↓", self._mover_abajo))
        hl.addWidget(_mbtn("←", self._subir_nivel))
        hl.addWidget(_mbtn("→", self._bajar_nivel))

        hl.addSpacing(4)

        # Búsqueda de partida
        self.inp_buscar = QLineEdit()
        self.inp_buscar.setPlaceholderText(_tr_b("Buscar") + "…")
        self.inp_buscar.setFixedHeight(26)
        self.inp_buscar.setMinimumWidth(140)
        self.inp_buscar.setStyleSheet(
            "background:rgba(255,255,255,0.14); border:1px solid rgba(255,255,255,0.22);"
            " border-radius:6px; color:white; padding:0 8px; font-size:11px;"
        )
        self.inp_buscar.textChanged.connect(self._buscar_partida)
        hl.addWidget(self.inp_buscar, stretch=1)

        hl.addSpacing(4)

        # Recalcular
        btn_recalc = QPushButton("⟳")
        btn_recalc.setFixedSize(26, 26)
        btn_recalc.setToolTip(_tr_b("Recalcular"))
        btn_recalc.setStyleSheet(
            f"QPushButton {{ background:rgba(255,255,255,0.12); color:white; border:none;"
            f" border-radius:4px; font-size:13px; font-weight:700; min-height:0; padding:0; }}"
            f"QPushButton:hover {{ background:rgba(255,255,255,0.25); }}"
        )
        btn_recalc.clicked.connect(self.recalcular)
        hl.addWidget(btn_recalc)

        self._btn_layout = QPushButton("↕")
        self._btn_layout.setFixedSize(26, 26)
        self._btn_layout.setStyleSheet(
            f"QPushButton {{ background:rgba(255,255,255,0.12); color:white; border:none;"
            f" border-radius:4px; font-size:13px; font-weight:700; min-height:0; padding:0; }}"
            f"QPushButton:hover {{ background:rgba(255,255,255,0.25); }}"
        )
        self._btn_layout.clicked.connect(self._toggle_panel_layout)
        from utils.tooltip import set_tooltip
        set_tooltip(self._btn_layout, "Mover panel ACU abajo")
        hl.addWidget(self._btn_layout)

        vl.addWidget(hdr)

        # Árbol de partidas con drag & drop
        self.tree = _PresupuestoTree()
        self.tree.setHeaderLabels(_cols_ppto())
        hdr = self.tree.header()
        hdr.setStretchLastSection(False)
        # Descripción (col 1) en Stretch — llena el espacio sobrante del panel
        # Las columnas numéricas quedan en Interactive (ancho fijo, arrastrables)
        for c in range(len(COLS_PPTO)):
            mode = QHeaderView.Stretch if c == 1 else QHeaderView.Interactive
            hdr.setSectionResizeMode(c, mode)
        self.tree.setColumnWidth(0, 62)
        # col 1 (Descripción) no tiene setColumnWidth — su ancho lo gestiona Stretch
        self.tree.setColumnWidth(2, 44)
        self.tree.setColumnWidth(3, 76)
        self.tree.setColumnWidth(4, 80)
        self.tree.setColumnWidth(5, 90)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu_partida)
        self.tree.currentItemChanged.connect(self._on_partida_seleccionada)
        self.tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tree.setIndentation(14)
        # Zebra manual: aplicada solo a partidas no-título alternadas
        # (ver bucle de carga del árbol). El alt nativo de Qt cuenta TODAS
        # las filas — con títulos intercalados produce un patrón caótico
        # donde casi cada partida queda sombreada.
        self.tree.setAlternatingRowColors(False)
        self.tree.partidas_reordenadas.connect(self._on_reordenadas)
        self.tree.itemClicked.connect(self._on_tree_click_metrado)
        self.tree.itemChanged.connect(self._on_tree_metrado_cambiado)
        # Doble clic en título/subtítulo → diálogo de edición. Se desactiva
        # el expandir-con-doble-clic para que el gesto no haga dos cosas
        # (expandir/colapsar queda en la flechita del árbol).
        self.tree.setExpandsOnDoubleClick(False)
        self.tree.itemDoubleClicked.connect(self._on_tree_doble_clic)

        # Delegate de edición inline para col Metrado
        self._metrado_delegate = _MetradoDelegate(self.tree)
        self.tree.setItemDelegateForColumn(3, self._metrado_delegate)
        self._metrado_delegate.navigate.connect(self._navegar_metrado)

        # Delegate de word-wrap para la columna Descripción
        self._desc_delegate = _DescripcionDelegate(self.tree, col=1)
        self.tree.setItemDelegateForColumn(1, self._desc_delegate)

        # Delegate que preserva el color de fuente al seleccionar (cols numéricas)
        # Col 3 queda con _metrado_delegate; col 1 con _desc_delegate
        _color_del = _TreeColorDelegate(self.tree)
        for _c in (0, 2, 4, 5):
            self.tree.setItemDelegateForColumn(_c, _color_del)
        # Cuando el usuario redimensiona la columna, recalcular alturas de filas
        self.tree.header().sectionResized.connect(
            lambda: self.tree.scheduleDelayedItemsLayout()
        )

        # Estilo unificado con cronogramas (Gantt · Valorizado · Insumos):
        # borde silver-300, header slate-500 blanco, gridlines slate-200,
        # padding 3×8. Los colores de TEXTO de partidas/títulos quedan
        # intactos (los maneja _TreeColorDelegate vía setForeground por
        # nivel, no toco eso).
        # Border-top off para evitar el línea blanca/gris entre la barra
        # de acciones arriba y el header del tree. Lateral + bottom borders
        # se mantienen para enmarcar la tabla.
        self.tree.setStyleSheet("""
            QTreeWidget {
                font-size: 11px;
                border: 1px solid #D4D4D4;
                border-top: none;
                outline: none;
                background: white;
                alternate-background-color: #FBFCFD;
                gridline-color: #E8ECF1;
            }
            QTreeWidget::item {
                height: 20px;
                padding: 1px 8px;
                border: none;
                border-bottom: 1px solid #EEF1F5;
            }
            QTreeWidget::item:selected {
                background: #FDEBD0;
            }
            QTreeWidget::item:hover:!selected {
                background: #F4F8FD;
            }
            QHeaderView::section {
                background: #485A6C;
                color: white;
                font-size: 10px;
                font-weight: 700;
                padding: 4px 6px;
                border: none;
                border-right: 1px solid #3D4D63;
            }
            QHeaderView::section:last { border-right: none; }
        """)
        vl.addWidget(self.tree, stretch=1)

        # Estado vacío (proyecto sin partidas): banner con botón para sugerir
        # partidas, INDEPENDIENTE de Tuxia → si el usuario apaga Tuxia la función
        # no se pierde. Va DEBAJO del árbol y NO lo oculta, para que el clic
        # derecho «Agregar título/partida» siga disponible.
        self._empty_state = self._build_empty_state()
        self._empty_state.setVisible(False)
        vl.addWidget(self._empty_state)

        # ── Barra de pestañas de sub-presupuesto ─────────────────────────────
        # Layout: [scroll horizontal con pestañas] [sep | CD: valor]
        # El scroll evita que muchas pestañas compriman el panel ACU/Insumos.
        self._tab_bar_frame = QFrame()
        self._tab_bar_frame.setFixedHeight(34)
        self._tab_bar_frame.setStyleSheet(
            f"background:#EEF1F5; border:none;"
        )
        _outer_hl = QHBoxLayout(self._tab_bar_frame)
        _outer_hl.setContentsMargins(6, 0, 8, 0)
        _outer_hl.setSpacing(2)

        # Contenedor interno scrollable solo para pestañas + botón "+"
        self._tab_scroll = QScrollArea()
        self._tab_scroll.setWidgetResizable(True)
        self._tab_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._tab_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._tab_scroll.setFrameShape(QFrame.NoFrame)
        self._tab_scroll.setStyleSheet(
            "QScrollArea { background:transparent; border:none; }"
            "QScrollBar:horizontal { height:6px; background:transparent; border:none; }"
            f"QScrollBar::handle:horizontal {{ background:{SILVER_300};"
            " border-radius:4px; }}"
            "QScrollBar::add-line:horizontal,"
            "QScrollBar::sub-line:horizontal { width:0px; background:none; }"
        )

        _tab_inner = QWidget()
        _tab_inner.setStyleSheet("background:transparent;")
        self._tab_bar_hl = QHBoxLayout(_tab_inner)
        self._tab_bar_hl.setContentsMargins(0, 4, 0, 0)
        self._tab_bar_hl.setSpacing(0)
        self._tab_scroll.setWidget(_tab_inner)
        _outer_hl.addWidget(self._tab_scroll, stretch=1)

        # Bloque CD fijo en esquina derecha (fuera del scroll)
        sep_cd = QFrame()
        sep_cd.setFrameShape(QFrame.VLine)
        sep_cd.setFixedHeight(16)
        sep_cd.setStyleSheet(f"color:{SILVER_300};")
        self._tab_bar_sep_cd  = sep_cd
        lbl_cd_k = QLabel("CD:")
        lbl_cd_k.setStyleSheet(
            f"color:{SLATE_300}; font-size:10px; font-weight:700; border:none; padding:0 3px;"
        )
        self.lbl_cd = QLabel("—")
        self.lbl_cd.setStyleSheet(
            f"color:{SLATE_700}; font-size:11px; font-weight:700; border:none; padding:0 2px 0 0;"
        )
        self._lbl_cd_k = lbl_cd_k
        _outer_hl.addWidget(sep_cd)
        _outer_hl.addWidget(lbl_cd_k)
        _outer_hl.addWidget(self.lbl_cd)

        vl.addWidget(self._tab_bar_frame)

        return frame

    # ══════════════════════════════════════════════════════════════════════════
    # Panel derecho: TABS
    # ══════════════════════════════════════════════════════════════════════════

    def _make_panel_tabs(self) -> QWidget:
        # Contenedor: barra propia + QTabWidget sin tabBar nativo
        container = QWidget()
        container.setStyleSheet("background:white; border:none;")
        vl = QVBoxLayout(container)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)

        # ── Barra de tabs personalizada (llena todo el ancho) ─────────────────
        bar_frame = QFrame()
        bar_frame.setFixedHeight(34)
        bar_frame.setStyleSheet(
            f"background:{SLATE_500}; border:none;"
        )
        bar_hl = QHBoxLayout(bar_frame)
        bar_hl.setContentsMargins(6, 4, 6, 4)
        bar_hl.setSpacing(4)

        from utils.i18n import tr
        tab_labels = ["ACU", tr("Insumos"), tr("Metrados"), tr("Especificaciones"), tr("Resumen"), tr("Memoria")]
        # Tooltip por pestaña (vacío = sin tooltip). «Metrados» aclara que es
        # la cantidad/medición de obra.
        tab_tips = ["", "", tr("Cantidades"), "", "", ""]
        self._tab_btns: list[QPushButton] = []

        def _tab_btn_style(selected: bool) -> str:
            bg  = BLUE_500 if selected else "transparent"
            col = "white"
            hover = "" if selected else (
                f"QPushButton:hover {{ background: rgba(255,255,255,0.15); color:white; }}"
            )
            return (
                f"QPushButton {{ background:{bg}; color:{col}; border:none;"
                f" border-radius:6px; font-size:11px; font-weight:700;"
                f" padding:3px 12px; }}"
                + hover
            )

        def _select_tab(idx: int):
            self.tabs.setCurrentIndex(idx)
            for i, b in enumerate(self._tab_btns):
                b.setStyleSheet(_tab_btn_style(i == idx))

        for i, label in enumerate(tab_labels):
            btn = QPushButton(label)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(_tab_btn_style(i == 0))
            if tab_tips[i]:
                btn.setToolTip(tab_tips[i])
            btn.clicked.connect(lambda _, ix=i: _select_tab(ix))
            bar_hl.addWidget(btn)
            self._tab_btns.append(btn)
        bar_hl.addStretch()

        # El botón para mostrar/ocultar el chat IA vive en el toolbar
        # superior del proyecto ("Asistente") — un solo punto de entrada.
        # Aquí se mantiene una referencia pasiva si otras partes del código
        # leen self.btn_toggle_chat (no se agrega al layout).
        self.btn_toggle_chat = QPushButton("✨ Asistente")
        self.btn_toggle_chat.setCheckable(True)
        self.btn_toggle_chat.setChecked(False)

        vl.addWidget(bar_frame)

        # ── QTabWidget sin tabBar (solo para gestionar páginas) ───────────────
        self.tabs = QTabWidget()
        self.tabs.tabBar().setVisible(False)
        self.tabs.setStyleSheet(
            "QTabWidget::pane { border:none; background:white; }"
        )
        self.tabs.addTab(self._make_tab_acu(),      "ACU")
        self.tabs.addTab(self._make_tab_insumos(),  "Insumos")
        self.tabs.addTab(self._make_tab_metrados(), "Metrados")
        self.tabs.addTab(self._make_tab_spec(),     "Especificaciones")
        self.tabs.addTab(self._make_tab_resumen(),  "Resumen")
        self.tabs.addTab(self._make_tab_memoria(),  "Memoria")
        self.tabs.currentChanged.connect(self._on_tab_cambiado)
        # Sincronizar botones si se cambia el tab desde código
        self.tabs.currentChanged.connect(
            lambda idx: [b.setStyleSheet(_tab_btn_style(i == idx))
                         for i, b in enumerate(self._tab_btns)]
        )

        # ── QSplitter vertical: tabs arriba, chat IA al pie ───────────────────
        # El chat vive fuera de las tabs (compartido por todas) y se adapta al
        # modo de la tab activa. Redimensionable; oculto por default.
        self._chat_splitter = QSplitter(Qt.Vertical)
        self._chat_splitter.setHandleWidth(4)
        self._chat_splitter.setStyleSheet(
            f"QSplitter::handle {{ background:{SILVER_300}; }}"
            "QSplitter::handle:hover { background:#9B59B6; }"
        )
        self._chat_splitter.addWidget(self.tabs)
        self._chat_acu = _ChatACU()
        self._chat_acu.set_proyecto(self.pid)
        # Botón minimizar del chat: vuelve al estado plegado (Tuxia bubble)
        self._chat_acu.btn_minimizar.clicked.connect(
            lambda: self._abrir_asistente_ia()
        )
        self._chat_splitter.addWidget(self._chat_acu)
        self._chat_splitter.setCollapsible(0, False)
        self._chat_splitter.setCollapsible(1, True)
        # Chat oculto por default — sizes [todo, 0]
        self._chat_splitter.setSizes([1000, 0])

        vl.addWidget(self._chat_splitter, stretch=1)

        # Conectar cambio de tab → modo del chat
        def _sync_chat_modo(idx: int):
            modos = ['ACU', 'Insumos', 'Metrados', 'Especificaciones', 'Resumen']
            if 0 <= idx < len(modos):
                self._chat_acu.set_modo(modos[idx])
        self.tabs.currentChanged.connect(_sync_chat_modo)
        _sync_chat_modo(self.tabs.currentIndex())

        # El chat IA arranca SIEMPRE cerrado al abrir el proyecto.
        # El ratio guardado en QSettings solo se usa cuando el usuario abre
        # el chat manualmente (ver _toggle_chat_acu) — para que recupere su
        # alto preferido. No se auto-restaura al inicio para no superponer
        # con el saludo inicial de tuxia.
        self._chat_splitter.splitterMoved.connect(self._guardar_chat_ratio)

        return container

    # ── Tab ACU ───────────────────────────────────────────────────────────────

    def _make_tab_acu(self) -> QWidget:  # noqa: C901
        # Contenedor raíz con splitter vertical: tabla arriba, chat abajo
        w = QWidget()
        w.setStyleSheet("background:white;")
        root_vl = QVBoxLayout(w)
        root_vl.setContentsMargins(0, 0, 0, 0)
        root_vl.setSpacing(0)

        self._acu_splitter = QSplitter(Qt.Vertical)
        self._acu_splitter.setHandleWidth(4)
        self._acu_splitter.setStyleSheet(
            "QSplitter::handle { background:#E8EAED; }"
            "QSplitter::handle:hover { background:#C9BEE8; }"
        )
        root_vl.addWidget(self._acu_splitter)

        # Panel superior: todo el ACU existente
        acu_top = QWidget()
        acu_top.setStyleSheet("background:white;")
        vl = QVBoxLayout(acu_top)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)

        # Cabecera del ACU
        hdr = QFrame()
        hdr.setFixedHeight(36)
        hdr.setStyleSheet(f"background:{SILVER_100}; border-bottom:1px solid {SILVER_300};")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(10, 0, 8, 0)
        hl.setSpacing(8)

        self.lbl_acu_titulo = QLabel("Seleccione una partida")
        self.lbl_acu_titulo.setStyleSheet(
            f"color:{SLATE_700}; font-size:11px; font-weight:700; border:none;"
        )
        self.lbl_acu_titulo.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.lbl_acu_titulo.setMinimumWidth(0)
        hl.addWidget(self.lbl_acu_titulo, stretch=1)
        hl.addStretch()

        btn_add = QPushButton("+ Recurso")
        btn_add.setFixedHeight(22)
        btn_add.setCursor(QCursor(Qt.PointingHandCursor))
        btn_add.setStyleSheet(
            f"QPushButton {{ background:{BLUE_500}; color:white; border:none; border-radius:4px;"
            f" padding:0 8px; font-size:10px; font-weight:600; }}"
            f"QPushButton:hover {{ background:{BLUE_700}; }}"
        )
        btn_add.clicked.connect(self._agregar_recurso)
        hl.addWidget(btn_add)

        btn_bib = QPushButton("Guardar")
        btn_bib.setFixedHeight(22)
        btn_bib.setToolTip("Guardar en Biblioteca")
        btn_bib.setCursor(QCursor(Qt.PointingHandCursor))
        btn_bib.setStyleSheet(
            f"QPushButton {{ background:{GREEN_500}; color:white; border:none; border-radius:4px;"
            f" padding:0 10px; font-size:10px; font-weight:600; }}"
            f"QPushButton:hover {{ background:#5a9e1e; }}"
        )
        btn_bib.clicked.connect(self._guardar_en_biblioteca)
        self._btn_bib = btn_bib
        hl.addWidget(btn_bib)

        lbl_r = QLabel("Rend.:")
        lbl_r.setStyleSheet(f"color:{SLATE_300}; font-size:10px; border:none;")
        hl.addWidget(lbl_r)

        self.inp_rend = QLineEdit("1.00")
        self.inp_rend.setFixedSize(56, 24)
        self.inp_rend.setStyleSheet(
            f"background:white; border:1px solid {SILVER_300}; border-radius:4px;"
            f" padding:0 6px; font-size:11px; color:{SLATE_700};"
        )
        self.inp_rend.editingFinished.connect(self._guardar_rendimiento)
        hl.addWidget(self.inp_rend)

        # Unidad del rendimiento (unidad de la partida / día), ej. «m²/día»
        self.lbl_rend_unidad = QLabel("")
        self.lbl_rend_unidad.setStyleSheet(
            f"color:{SLATE_500}; font-size:10px; font-weight:600;"
            f" border:none; background:transparent;"
        )
        hl.addWidget(self.lbl_rend_unidad)

        self.lbl_jornada = QLabel("")
        self.lbl_jornada.setStyleSheet(
            f"color:{SLATE_300}; font-size:10px; border:none;"
            f" background:#F0F2F5; border-radius:4px; padding:1px 6px;"
        )
        hl.addWidget(self.lbl_jornada)

        vl.addWidget(hdr)

        # Tabla ACU
        self.tbl_acu = _AcuTable(0, len(COLS_ACU))
        self.tbl_acu.setHorizontalHeaderLabels(_cols_acu())
        self.tbl_acu.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tbl_acu.setColumnWidth(0, 38)   # Tip badge
        self.tbl_acu.setColumnWidth(2, 40)
        self.tbl_acu.setColumnWidth(3, 70)
        self.tbl_acu.setColumnWidth(4, 80)
        self.tbl_acu.setColumnWidth(5, 80)
        self.tbl_acu.setColumnWidth(6, 85)
        self.tbl_acu.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl_acu.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tbl_acu.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl_acu.setAlternatingRowColors(False)
        self.tbl_acu.verticalHeader().setVisible(False)
        self.tbl_acu.setShowGrid(False)
        self.tbl_acu.setStyleSheet(f"""
            QTableWidget {{
                border: none;
                font-size: 11px;
                outline: none;
                background: white;
            }}
            QTableWidget::item {{
                padding: 0 4px;
                border: none;
                border-bottom: 1px solid #F0F2F5;
            }}
            QTableWidget::item:selected {{
                background: #FDEBD0;
                color: {SLATE_700};
            }}
            QTableWidget::item:hover:!selected {{
                background: #EEF4FD;
            }}
            QHeaderView::section {{
                background: {SLATE_500};
                color: white;
                font-size: 10px;
                font-weight: 700;
                padding: 4px 4px;
                border: none;
            }}
        """)
        self.tbl_acu.setItemDelegateForColumn(0, _AcuBadgeDelegate(self))
        self.tbl_acu.setItemDelegateForColumn(3, _InputCellDelegate(self, 3))
        self.tbl_acu.setItemDelegateForColumn(4, _InputCellDelegate(self, 4))
        self.tbl_acu.setItemDelegateForColumn(5, _InputCellDelegate(self, 5))
        self.tbl_acu.cellClicked.connect(self._on_acu_cell_clicked)
        self.tbl_acu.doubleClicked.connect(self._editar_celda_acu)
        self.tbl_acu.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tbl_acu.customContextMenuRequested.connect(self._menu_acu)
        self.tbl_acu._key_handler = self._acu_key_press
        vl.addWidget(self.tbl_acu, stretch=1)

        self.lbl_acu_clipboard = QLabel("")
        self.lbl_acu_clipboard.setStyleSheet(
            f"color:#0F5132; font-size:10px; border:none;"
            f" background:#D1E7DD; border-radius:4px; padding:1px 7px;"
        )
        self.lbl_acu_clipboard.setVisible(False)

        # Subtotales por tipo
        self._make_acu_subtotales(vl)

        # ── Ensamblar splitter ─────────────────────────────────────────
        # El chat IA se movió al pie del panel derecho (debajo de las tabs)
        # para que sea contextual a la tab activa, no solo a ACU.
        self._acu_splitter.addWidget(acu_top)
        self._acu_splitter.setCollapsible(0, False)

        return w

    def _make_acu_subtotales(self, parent_layout):
        sub = QFrame()
        sub.setFixedHeight(32)
        sub.setStyleSheet(
            f"background:#EEF1F5; border-top:2px solid {SILVER_300};"
        )
        hl = QHBoxLayout(sub)
        hl.setContentsMargins(8, 0, 8, 0)
        hl.setSpacing(0)

        self._sub_labels = {}
        _TIPOS = [
            ('MO',  "#F39C12", "MO"),
            ('MAT', "#27AE60", "MAT"),
            ('EQ',  "#607D8B", "EQ"),
            ('SC',  "#7A36B1", "SC"),
        ]
        for tipo, color, abrev in _TIPOS:
            lbl_key = QLabel(f"{abrev}:")
            lbl_key.setStyleSheet(
                f"color:{color}; font-size:10px; font-weight:700; border:none;"
                f" padding:0 3px 0 10px;"
            )
            lbl_val = QLabel("—")
            lbl_val.setStyleSheet(
                f"color:{SLATE_700}; font-size:11px; font-weight:700; border:none;"
                f" padding:0 4px 0 0;"
            )
            hl.addWidget(lbl_key)
            hl.addWidget(lbl_val)
            self._sub_labels[tipo] = lbl_val

            sep = QFrame()
            sep.setFrameShape(QFrame.VLine)
            sep.setFixedHeight(16)
            sep.setStyleSheet(f"color:{SILVER_300};")
            hl.addWidget(sep)

        hl.addStretch()

        lbl_cu_k = QLabel("CU:")
        lbl_cu_k.setStyleSheet(
            f"color:{SLATE_300}; font-size:10px; font-weight:700; border:none; padding:0 3px;"
        )
        self.lbl_pu = QLabel("—")
        # Negro (como el total de metrados) — el naranja no era consistente.
        self.lbl_pu.setStyleSheet(
            f"color:{SLATE_700}; font-size:11px; font-weight:700; border:none; padding:0 4px 0 0;"
        )
        hl.addWidget(lbl_cu_k)
        hl.addWidget(self.lbl_pu)

        parent_layout.addWidget(sub)

    # ── Tab Insumos ───────────────────────────────────────────────────────────

    def _make_tab_insumos(self) -> QWidget:
        from utils.i18n import tr
        w = QWidget()
        w.setStyleSheet("background:white;")
        vl = QVBoxLayout(w)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)

        # Barra de búsqueda
        bar = QFrame()
        bar.setFixedHeight(36)
        bar.setStyleSheet(f"background:{SILVER_100}; border-bottom:1px solid {SILVER_300};")
        hl = QHBoxLayout(bar)
        hl.setContentsMargins(8, 0, 8, 0)
        self.lbl_ins_titulo = QLabel("INSUMOS TOTALES DEL PROYECTO")
        self.lbl_ins_titulo.setStyleSheet(f"color:{SLATE_700}; font-size:11px; font-weight:700; border:none;")
        hl.addWidget(self.lbl_ins_titulo)
        # Botón "Ver todos" — solo visible cuando se filtra por partida
        self.btn_ins_ver_todos = QPushButton("↩ Ver todos")
        self.btn_ins_ver_todos.setFixedHeight(22)
        self.btn_ins_ver_todos.setCursor(Qt.PointingHandCursor)
        self.btn_ins_ver_todos.setStyleSheet(
            f"QPushButton {{ background:transparent; border:none;"
            f" font-size:10px; color:{BLUE_500}; font-weight:600; padding:0 4px; }}"
            f"QPushButton:hover {{ color:{BLUE_700}; }}"
        )
        self.btn_ins_ver_todos.setVisible(False)
        self.btn_ins_ver_todos.clicked.connect(lambda: self.cargar_insumos(None))
        hl.addWidget(self.btn_ins_ver_todos)
        hl.addStretch()
        # Botón "Unificar precios" — solo visible si hay insumos con precio
        # inconsistente en el proyecto (mismo insumo a distinto precio).
        self.btn_ins_unificar = QPushButton("⚠ Unificar precios")
        self.btn_ins_unificar.setFixedHeight(22)
        self.btn_ins_unificar.setCursor(Qt.PointingHandCursor)
        self.btn_ins_unificar.setStyleSheet(
            "QPushButton { background:#FDECEA; border:1px solid #E6A29A;"
            " border-radius:4px; font-size:10px; color:#B23B2E; font-weight:700;"
            " padding:0 8px; }"
            "QPushButton:hover { background:#FBD9D4; }"
        )
        self.btn_ins_unificar.setVisible(False)
        self.btn_ins_unificar.clicked.connect(self._unificar_todos_precios)
        hl.addWidget(self.btn_ins_unificar)
        # Botón "PU ≠ ACU" — solo visible si hay partidas cuyo PU guardado
        # no coincide con la suma de su análisis (datos importados antiguos
        # o ediciones con versiones viejas del cálculo).
        self.btn_ins_pu_acu = QPushButton("⚠ PU ≠ ACU")
        self.btn_ins_pu_acu.setFixedHeight(22)
        self.btn_ins_pu_acu.setCursor(Qt.PointingHandCursor)
        self.btn_ins_pu_acu.setStyleSheet(
            "QPushButton { background:#FFF3E0; border:1px solid #E0B080;"
            " border-radius:4px; font-size:10px; color:#9A5B00; font-weight:700;"
            " padding:0 8px; }"
            "QPushButton:hover { background:#FFE8CC; }"
        )
        self.btn_ins_pu_acu.setVisible(False)
        self.btn_ins_pu_acu.clicked.connect(self._verificar_pu_acu)
        hl.addWidget(self.btn_ins_pu_acu)
        self.inp_buscar_ins = QLineEdit()
        self.inp_buscar_ins.setPlaceholderText(tr("Buscar") + "…")
        self.inp_buscar_ins.setFixedSize(160, 24)
        self.inp_buscar_ins.setStyleSheet(
            f"background:white; border:1px solid {SILVER_300}; border-radius:4px;"
            f" padding:0 8px; font-size:11px;"
        )
        self._ins_estado: 'int | list[int] | None' = None
        self._ins_titulo_label: str = ""
        self.inp_buscar_ins.textChanged.connect(
            lambda _: self.cargar_insumos(self._ins_estado)
        )
        hl.addWidget(self.inp_buscar_ins)
        vl.addWidget(bar)

        self.tbl_ins = _AcuTable(0, len(COLS_INS))
        self.tbl_ins.setHorizontalHeaderLabels(_cols_ins())
        self.tbl_ins.setColumnWidth(0, 42)              # Tipo badge
        self.tbl_ins.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tbl_ins.setColumnWidth(2, 44)              # Und.
        self.tbl_ins.setColumnWidth(3, 82)              # Cantidad
        self.tbl_ins.setColumnWidth(4, 76)              # Precio U.
        self.tbl_ins.setColumnWidth(5, 84)              # Parcial
        self.tbl_ins.setItemDelegateForColumn(0, _AcuBadgeDelegate(self))
        self.tbl_ins.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl_ins.setSelectionBehavior(QAbstractItemView.SelectRows)

        def _ins_key(event):
            if event.key() == Qt.Key_Escape:
                self.cargar_insumos(None)
                return True
            return False
        self.tbl_ins._key_handler = _ins_key
        self.tbl_ins.cellClicked.connect(self._ins_click_precio)
        self.tbl_ins.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tbl_ins.customContextMenuRequested.connect(self._ins_menu_contextual)
        self.tbl_ins.verticalHeader().setVisible(False)
        self.tbl_ins.setShowGrid(True)
        self.tbl_ins.setStyleSheet(f"""
            QTableWidget {{ border:none; font-size:11px; gridline-color:#E8EAED; }}
            QTableWidget::item {{ padding:2px 4px; }}
            QTableWidget::item:selected {{ background:#FEF0E0; }}
            QHeaderView::section {{
                background:{SLATE_500}; color:white; font-size:10px;
                font-weight:700; padding:4px 4px; border:none;
            }}
        """)
        vl.addWidget(self.tbl_ins, stretch=1)

        # Pie: total CD + subtotales MO/MAT/EQ
        pie = QFrame()
        pie.setFixedHeight(32)
        pie.setStyleSheet(f"background:#EEF1F5; border-top:2px solid {SILVER_300};")
        hl2 = QHBoxLayout(pie)
        hl2.setContentsMargins(10, 0, 10, 0)
        hl2.setSpacing(0)
        hl2.addStretch()
        # Subtotales por tipo — solo en modo proyecto total
        self._ins_tipo_labels: dict[str, QLabel] = {}
        self._ins_tipo_widgets: list = []   # todos los widgets del bloque tipo
        for tipo, color in [('MO', '#F39C12'), ('MAT', '#27AE60'),
                            ('EQ', '#607D8B'), ('SC', '#7A36B1')]:
            sep = QFrame(); sep.setFrameShape(QFrame.VLine)
            sep.setStyleSheet(f"border:none; border-left:1px solid {SILVER_300}; margin:4px 8px;")
            sep.setFixedWidth(17)
            hl2.addWidget(sep)
            lk = QLabel(f"{tipo}:")
            lk.setStyleSheet(f"color:{color}; font-size:10px; font-weight:700; border:none; padding:0 3px 0 10px;")
            hl2.addWidget(lk)
            lv = QLabel("—")
            lv.setStyleSheet(f"color:{SLATE_700}; font-size:11px; font-weight:700; border:none; padding:0 4px 0 0;")
            hl2.addWidget(lv)
            self._ins_tipo_labels[tipo] = lv
            self._ins_tipo_widgets += [sep, lk, lv]
        vl.addWidget(pie)

        return w

    # ── Tab Metrados ──────────────────────────────────────────────────────────

    def _make_tab_metrados(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background:white;")
        vl = QVBoxLayout(w)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)

        # Cabecera
        hdr = QFrame()
        hdr.setFixedHeight(36)
        hdr.setStyleSheet(f"background:{SILVER_100}; border-bottom:1px solid {SILVER_300};")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(10, 0, 8, 0)
        self.lbl_met_titulo = QLabel("Seleccione una partida")
        self.lbl_met_titulo.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.lbl_met_titulo.setStyleSheet(
            f"color:{SLATE_700}; font-size:11px; font-weight:700; border:none;"
        )
        hl.addWidget(self.lbl_met_titulo, stretch=1)
        # Toggle Metrados / Acero
        self._met_modo = 'met'
        _TOGGLE_ON  = (f"background:{BLUE_500}; color:white; border:none;"
                       f" border-radius:4px; padding:0 10px; font-size:10px; font-weight:700;")
        _TOGGLE_OFF = (f"background:{SILVER_100}; color:{SLATE_500};"
                       f" border:1px solid {SILVER_300}; border-radius:4px;"
                       f" padding:0 10px; font-size:10px;")
        self.btn_modo_met   = QPushButton("⊞ Metrados")
        self.btn_modo_acero = QPushButton("⊞ Acero")
        self.btn_modo_met.setFixedHeight(24)
        self.btn_modo_acero.setFixedHeight(24)
        self.btn_modo_met.setStyleSheet(_TOGGLE_ON)
        self.btn_modo_acero.setStyleSheet(_TOGGLE_OFF)
        self.btn_modo_met.clicked.connect(lambda: self._toggle_met_modo('met'))
        self.btn_modo_acero.clicked.connect(lambda: self._toggle_met_modo('acero'))
        self._met_toggle_on  = _TOGGLE_ON
        self._met_toggle_off = _TOGGLE_OFF
        hl.addWidget(self.btn_modo_met)
        hl.addWidget(self.btn_modo_acero)
        hl.addSpacing(6)
        btn_met_add = QPushButton("+ Fila")
        btn_met_add.setFixedHeight(24)
        btn_met_add.setStyleSheet(
            f"background:{BLUE_500}; color:white; border:none; border-radius:4px;"
            f" padding:0 10px; font-size:10px; font-weight:600;"
        )
        btn_met_add.clicked.connect(self._metrado_fila_btn)
        hl.addWidget(btn_met_add)
        btn_met_save = QPushButton("✓ Guardar")
        btn_met_save.setFixedHeight(24)
        btn_met_save.setStyleSheet(
            f"background:{GREEN_500}; color:white; border:none; border-radius:4px;"
            f" padding:0 10px; font-size:10px; font-weight:600;"
        )
        btn_met_save.clicked.connect(self._metrado_guardar)
        hl.addWidget(btn_met_save)
        vl.addWidget(hdr)

        # Tabla de metrados (planilla)
        self.tbl_met = _AcuTable(0, len(COLS_MET))
        self.tbl_met.setHorizontalHeaderLabels(_cols_met())
        self.tbl_met.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tbl_met.setColumnWidth(1, 52)   # N°Est.
        self.tbl_met.setColumnWidth(2, 52)   # N°Elem.
        self.tbl_met.setColumnWidth(3, 68)   # Área
        self.tbl_met.setColumnWidth(4, 68)   # Largo
        self.tbl_met.setColumnWidth(5, 68)   # Ancho
        self.tbl_met.setColumnWidth(6, 68)   # Alto
        self.tbl_met.setColumnWidth(7, 80)   # Parcial
        self.tbl_met.setEditTriggers(QAbstractItemView.DoubleClicked |
                                     QAbstractItemView.SelectedClicked)
        self.tbl_met.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl_met.verticalHeader().setVisible(False)
        self.tbl_met.setStyleSheet(f"""
            QTableWidget {{ border:none; font-size:11px; gridline-color:#E8EAED; }}
            QTableWidget::item {{ padding:2px 4px; color:#273445; }}
            QTableWidget::item:selected {{ background:#FEF5EB; color:#273445; }}
            QHeaderView::section {{
                background:{SLATE_500}; color:white; font-size:10px;
                font-weight:700; padding:4px; border:none;
            }}
        """)
        # Delegate de navegación Excel en cols editables 0-6
        _nav_del = _MetNavDelegate(self)
        for _c in range(7):
            self.tbl_met.setItemDelegateForColumn(_c, _nav_del)
        self.tbl_met.itemChanged.connect(self._metrado_item_cambiado)

        # Copiar / Cortar / Pegar filas — key handler en _AcuTable.
        # El portapapeles vive a nivel módulo (_MET_CLIPBOARD) para cruzar
        # proyectos; aquí no se inicializa por-instancia.

        def _met_keys(event):
            k = event.key()
            m = event.modifiers()
            if k == Qt.Key_Delete:
                self._met_eliminar_seleccionadas(); return True
            if m == Qt.ControlModifier:
                if k == Qt.Key_C: self._met_copiar(); return True
                if k == Qt.Key_X: self._met_cortar(); return True
                if k == Qt.Key_V: self._met_pegar();  return True
            # Tab/Enter/Flechas abren el editor en la celda actual
            if k in (Qt.Key_Tab, Qt.Key_Return, Qt.Key_Enter,
                     Qt.Key_Up, Qt.Key_Down, Qt.Key_Left, Qt.Key_Right):
                idx = self.tbl_met.currentIndex()
                if idx.isValid() and idx.column() < 7:
                    QTimer.singleShot(0, lambda: self.tbl_met.edit(idx))
                return False   # dejar que Qt también mueva la selección
            return False

        self.tbl_met._key_handler = _met_keys
        self.tbl_met.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tbl_met.customContextMenuRequested.connect(self._met_menu_contextual)

        # ── Tabla Acero ───────────────────────────────────────────────────────
        self._acero_loading = False
        self.tbl_acero = _AcuTable(0, len(COLS_ACERO))
        self.tbl_acero.setHorizontalHeaderLabels(_cols_acero())
        self.tbl_acero.setColumnWidth(0, 26)    # #
        self.tbl_acero.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tbl_acero.setColumnWidth(2, 92)    # Diámetro
        self.tbl_acero.setColumnWidth(3, 52)    # N°Estr.
        self.tbl_acero.setColumnWidth(4, 52)    # N°Elem.
        self.tbl_acero.setColumnWidth(5, 52)    # N°Var.
        self.tbl_acero.setColumnWidth(6, 68)    # Longitud
        self.tbl_acero.setColumnWidth(7, 68)    # Parc.(m)
        self.tbl_acero.setColumnWidth(8, 56)    # kg/ml
        self.tbl_acero.setColumnWidth(9, 72)    # Parc.(kg)
        self.tbl_acero.setColumnWidth(10, 28)   # ×
        self.tbl_acero.setEditTriggers(QAbstractItemView.DoubleClicked |
                                       QAbstractItemView.SelectedClicked)
        self.tbl_acero.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl_acero.verticalHeader().setVisible(False)
        self.tbl_acero.setStyleSheet(f"""
            QTableWidget {{ border:none; font-size:11px; gridline-color:#E8EAED; }}
            QTableWidget::item {{ padding:2px 4px; color:#273445; }}
            QTableWidget::item:selected {{ background:#FEF5EB; color:#273445; }}
            QHeaderView::section {{
                background:{SLATE_500}; color:white; font-size:10px;
                font-weight:700; padding:4px; border:none;
            }}
        """)
        # Delegate de navegación en cols editables (no col 2 que es combobox)
        _acero_nav = _AceroNavDelegate(self)
        for _c in (1, 3, 4, 5, 6, 8):
            self.tbl_acero.setItemDelegateForColumn(_c, _acero_nav)
        self.tbl_acero.itemChanged.connect(self._acero_item_cambiado)
        # Clipboard a nivel módulo (_ACERO_CLIPBOARD) para cruzar proyectos.
        def _acero_keys(event):
            k = event.key()
            m = event.modifiers()
            if k == Qt.Key_Delete:
                self._acero_eliminar_seleccionadas(); return True
            if m == Qt.ControlModifier:
                if k == Qt.Key_C: self._acero_copiar(); return True
                if k == Qt.Key_X: self._acero_cortar(); return True
                if k == Qt.Key_V: self._acero_pegar();  return True
            # Tab/Enter/flechas abren editor en celda actual
            if k in (Qt.Key_Tab, Qt.Key_Return, Qt.Key_Enter,
                     Qt.Key_Up, Qt.Key_Down, Qt.Key_Left, Qt.Key_Right):
                idx = self.tbl_acero.currentIndex()
                if idx.isValid() and idx.column() not in (0, 7, 9, 10):
                    QTimer.singleShot(0, lambda: self._acero_ir_a(idx.row(), idx.column()))
                return False
            return False
        self.tbl_acero._key_handler = _acero_keys
        self.tbl_acero.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tbl_acero.customContextMenuRequested.connect(self._acero_menu_contextual)

        # Stack: página 0 = metrados, página 1 = acero
        from PySide6.QtWidgets import QStackedWidget
        self._met_stack = QStackedWidget()
        self._met_stack.addWidget(self.tbl_met)
        self._met_stack.addWidget(self.tbl_acero)
        vl.addWidget(self._met_stack, stretch=1)

        # Total metrado
        pie = QFrame()
        pie.setFixedHeight(32)
        pie.setStyleSheet(f"background:#EEF1F5; border-top:2px solid {SILVER_300};")
        hl2 = QHBoxLayout(pie)
        hl2.setContentsMargins(10, 0, 10, 0)
        self.lbl_met_total_key = QLabel("METRADO TOTAL:")
        self.lbl_met_total_key.setStyleSheet(
            f"color:{SLATE_300}; font-size:10px; font-weight:700; border:none; padding:0 3px;"
        )
        self.lbl_met_total = QLabel("0.00")
        self.lbl_met_total.setStyleSheet(
            f"color:{SLATE_700}; font-size:11px; font-weight:700; border:none; padding:0 4px 0 0;"
        )
        # Total alineado a la derecha (consistente con los demás pies).
        hl2.addStretch()
        hl2.addWidget(self.lbl_met_total_key)
        hl2.addWidget(self.lbl_met_total)
        vl.addWidget(pie)

        return w

    # ── Tab Especificaciones ──────────────────────────────────────────────────

    def _make_tab_spec(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background:white;")
        vl = QVBoxLayout(w)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)

        # ── Cabecera ────────────────────────────────────────────────
        hdr = QFrame()
        hdr.setFixedHeight(36)
        hdr.setStyleSheet(f"background:{SILVER_100}; border-bottom:1px solid {SILVER_300};")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(10, 0, 8, 0)
        hl.setSpacing(6)

        self.lbl_spec_titulo = QLabel("Especificaciones técnicas")
        self.lbl_spec_titulo.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.lbl_spec_titulo.setStyleSheet(
            f"color:{SLATE_700}; font-size:11px; font-weight:700; border:none;"
        )
        hl.addWidget(self.lbl_spec_titulo, stretch=1)

        self.lbl_spec_estado = QLabel("")
        self.lbl_spec_estado.setFixedWidth(80)
        self.lbl_spec_estado.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.lbl_spec_estado.setStyleSheet("font-size:10px; color:#95A3AB; border:none;")
        hl.addWidget(self.lbl_spec_estado)

        btn_todo = QPushButton("✨  Todo  ▾")
        btn_todo.setFixedHeight(24)
        from utils.i18n import tr as _tr_spec
        btn_todo.setToolTip(_tr_spec("Generar especificaciones para todas las partidas del proyecto"))
        btn_todo.setStyleSheet(
            "QPushButton { background:#E8E4F0; color:#6C3483; border:none; border-radius:4px;"
            " padding:0 10px; font-size:10px; font-weight:600; }"
            "QPushButton:hover { background:#D2C9E8; }"
            "QPushButton::menu-indicator { image:none; width:0; }"
        )
        menu_todo = QMenu(btn_todo)
        act_faltantes = menu_todo.addAction("✨  Solo las que faltan")
        act_faltantes.setToolTip(
            "Generar especificaciones únicamente para partidas que aún no tienen una."
        )
        act_faltantes.triggered.connect(
            lambda: self._ia_generar_todo(omitir_existentes=True)
        )
        act_todas = menu_todo.addAction("✨  Todas las partidas (regenerar)")
        act_todas.setToolTip(
            "Regenerar la especificación de TODAS las partidas, incluso las que ya tienen una."
        )
        act_todas.triggered.connect(
            lambda: self._ia_generar_todo(omitir_existentes=False)
        )
        btn_todo.setMenu(menu_todo)
        hl.addWidget(btn_todo)

        btn_ia = QPushButton("✨  IA")
        btn_ia.setFixedHeight(24)
        btn_ia.setToolTip(_tr_spec("Generar especificación con IA para la partida seleccionada"))
        btn_ia.setStyleSheet(
            "QPushButton { background:#9B59B6; color:white; border:none; border-radius:4px;"
            " padding:0 10px; font-size:10px; font-weight:600; }"
            "QPushButton:hover { background:#8E44AD; }"
        )
        btn_ia.clicked.connect(self._ia_generar_spec)
        hl.addWidget(btn_ia)

        btn_save = QPushButton("Guardar")
        btn_save.setFixedHeight(24)
        btn_save.setStyleSheet(
            f"QPushButton {{ background:{GREEN_500}; color:white; border:none; border-radius:4px;"
            f" padding:0 12px; font-size:10px; font-weight:600; }}"
            f"QPushButton:hover {{ background:#5a9e1e; }}"
        )
        btn_save.clicked.connect(self._guardar_spec)
        hl.addWidget(btn_save)
        vl.addWidget(hdr)

        # ── Toolbar de formato ───────────────────────────────────────
        toolbar = QFrame()
        toolbar.setFixedHeight(30)
        toolbar.setStyleSheet(
            f"background:#F5F5F5; border-bottom:1px solid {SILVER_300};"
        )
        ht = QHBoxLayout(toolbar)
        ht.setContentsMargins(8, 0, 8, 0)
        ht.setSpacing(2)

        _BTN_FMT = (
            "QPushButton { background:transparent; border:none; border-radius:4px;"
            " padding:0 5px; font-size:12px; min-width:24px; min-height:22px; }"
            "QPushButton:hover { background:#E0E0E0; }"
            "QPushButton:checked { background:#D4C9F0; color:#6C3483; }"
        )

        def _fmt_btn(texto, tooltip, callback, checkable=False):
            b = QPushButton(texto)
            b.setFixedHeight(22)
            b.setToolTip(tooltip)
            b.setCheckable(checkable)
            b.setStyleSheet(_BTN_FMT)
            b.clicked.connect(callback)
            return b

        def _sep():
            s = QFrame()
            s.setFrameShape(QFrame.VLine)
            s.setFixedWidth(1)
            s.setStyleSheet(f"color:{SILVER_300};")
            return s

        # Negrita / Cursiva / Subrayado
        self.btn_bold = _fmt_btn("B", "Negrita (Ctrl+B)", self._spec_bold, True)
        self.btn_bold.setStyleSheet(_BTN_FMT + "QPushButton { font-weight:900; }")
        self.btn_italic = _fmt_btn("I", "Cursiva (Ctrl+I)", self._spec_italic, True)
        self.btn_italic.setStyleSheet(_BTN_FMT + "QPushButton { font-style:italic; }")
        self.btn_underline = _fmt_btn("U", "Subrayado (Ctrl+U)", self._spec_underline, True)
        self.btn_underline.setStyleSheet(_BTN_FMT + "QPushButton { text-decoration:underline; }")
        ht.addWidget(self.btn_bold)
        ht.addWidget(self.btn_italic)
        ht.addWidget(self.btn_underline)
        ht.addWidget(_sep())

        # Alineación
        for icono, tooltip, alin in [
            ("≡←", "Alinear izquierda",  Qt.AlignLeft),
            ("≡≡", "Centrar",            Qt.AlignHCenter),
            ("≡→", "Alinear derecha",    Qt.AlignRight),
            ("≡≡", "Justificar",         Qt.AlignJustify),
        ]:
            alin_val = alin
            b = _fmt_btn(icono, tooltip, lambda _ch, a=alin_val: self._spec_align(a))
            ht.addWidget(b)
        ht.addWidget(_sep())

        # Listas
        ht.addWidget(_fmt_btn("•  Lista", "Viñetas",        self._spec_bullet_list))
        ht.addWidget(_fmt_btn("1. Lista", "Lista numerada", self._spec_numbered_list))
        ht.addWidget(_sep())

        # Imagen
        ht.addWidget(_fmt_btn("🖼  Imagen", "Insertar imagen", self._spec_insertar_imagen))
        ht.addStretch()
        vl.addWidget(toolbar)

        # ── Editor ─────────────────────────────────────────────────
        self.txt_spec = QTextEdit()
        self.txt_spec.setAcceptRichText(True)
        self.txt_spec.setPlaceholderText(
            "Seleccione una partida para ver o editar sus especificaciones técnicas…"
        )
        self.txt_spec.setStyleSheet(
            f"QTextEdit {{ border:none; font-size:12px; padding:12px;"
            f" color:{SLATE_700}; }}"
        )
        self.txt_spec.textChanged.connect(self._on_spec_modificada)
        self.txt_spec.cursorPositionChanged.connect(self._spec_actualizar_toolbar)
        vl.addWidget(self.txt_spec, stretch=1)
        return w

    # ── Tab Pie ───────────────────────────────────────────────────────────────

    def _make_pie_page(self) -> QWidget:
        """Vista completa de Pie — page 1 del root stack.
        Layout: topbar | QSplitter(izq: Resumen, der: tabs de detalle)
        """
        page = QWidget()
        page.setStyleSheet("background:white;")
        vl = QVBoxLayout(page)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)

        # ── Barra única compacta (mismo patrón que Cronograma/Metrados) ───────
        hdr = QFrame()
        hdr.setFixedHeight(36)
        hdr.setStyleSheet(f"background:{SLATE_500}; border:none;")
        hdr_hl = QHBoxLayout(hdr)
        hdr_hl.setContentsMargins(8, 4, 10, 4)
        hdr_hl.setSpacing(6)

        btn_back = QPushButton("← Presupuesto")
        btn_back.setCursor(Qt.PointingHandCursor)
        btn_back.setStyleSheet(
            f"QPushButton {{ background:rgba(255,255,255,0.12); color:white;"
            f" border:1px solid rgba(255,255,255,0.25); border-radius:6px;"
            f" font-size:11px; padding:3px 10px; }}"
            f"QPushButton:hover {{ background:rgba(255,255,255,0.22); }}"
        )
        btn_back.clicked.connect(lambda: self._root_stack.setCurrentIndex(0))
        hdr_hl.addWidget(btn_back)
        hdr_hl.addSpacing(8)

        lbl_title = QLabel("Pie de Presupuesto")
        lbl_title.setStyleSheet(
            "color:white; font-size:12px; font-weight:700;"
            " background:transparent; border:none;")
        hdr_hl.addWidget(lbl_title)
        hdr_hl.addSpacing(14)

        # Host de las pestañas de rubros (Gastos Generales · Supervisión · …).
        # Se llenan en _render_pie; viven aquí arriba para ahorrar la fila que
        # antes ocupaban dentro del panel derecho.
        self._pie_tabs_host = QWidget()
        self._pie_tabs_host.setStyleSheet("background:transparent;")
        self._pie_tabs_host_hl = QHBoxLayout(self._pie_tabs_host)
        self._pie_tabs_host_hl.setContentsMargins(0, 0, 0, 0)
        self._pie_tabs_host_hl.setSpacing(4)
        hdr_hl.addWidget(self._pie_tabs_host)

        hdr_hl.addStretch(1)
        # El total ya se muestra en la barra de pestañas de proyecto (arriba).
        vl.addWidget(hdr)

        # ── Splitter izq | der ────────────────────────────────────────────────
        self._pie_split = QSplitter(Qt.Horizontal)
        self._pie_split.setHandleWidth(3)
        self._pie_split.setStyleSheet(
            "QSplitter::handle { background:#D4D4D4; }"
        )

        # Panel izquierdo: scroll con Resumen + Plantillas inline
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.NoFrame)
        left_scroll.setStyleSheet("background:white;")
        self._pie_left_w = QWidget()
        self._pie_left_w.setStyleSheet("background:white;")
        self._pie_left_vl = QVBoxLayout(self._pie_left_w)
        self._pie_left_vl.setContentsMargins(10, 10, 10, 10)
        self._pie_left_vl.setSpacing(12)
        self._pie_left_vl.addStretch()
        left_scroll.setWidget(self._pie_left_w)
        self._pie_split.addWidget(left_scroll)

        # Panel derecho: tab bar + QTabWidget de detalles (contenedor recargable)
        self._pie_right = QWidget()
        self._pie_right.setStyleSheet(f"background:{SILVER_100};")
        self._pie_right_vl = QVBoxLayout(self._pie_right)
        self._pie_right_vl.setContentsMargins(0, 0, 0, 0)
        self._pie_right_vl.setSpacing(0)
        self._pie_split.addWidget(self._pie_right)

        self._pie_split.setStretchFactor(0, 35)
        self._pie_split.setStretchFactor(1, 65)
        self._pie_split.setSizes([320, 680])

        vl.addWidget(self._pie_split, stretch=1)
        return page

    def _rub_color(self, _cod: str) -> str:
        return SLATE_500

    def _pie_crear_rubros_default(self, proy):
        gf   = proy['gf_pct']       or 10.0
        util = proy['utilidad_pct'] or 5.0
        igv  = proy['igv_pct']      or 18.0
        conn = get_db()
        for codigo, nombre, pct, activo, orden, tipo, mostrar_pct in [
            ('GG',   'Gastos Generales',   gf,   1, 0, 'rubro',    1),
            ('UTIL', 'Utilidad',            util, 1, 1, 'pct_cd',   1),
            ('SUB',  'Sub Total',           0,    1, 2, 'subtotal', 1),
            ('SUP',  'Supervisión',         5.0,  0, 3, 'rubro',    0),
            ('ET',   'Expediente Técnico',  3.0,  0, 4, 'rubro',    0),
            ('LQ',   'Liquidación de Obra', 2.0,  0, 5, 'rubro',    0),
            ('IGV',  f'IGV ({int(igv)}%)',  igv,  1, 6, 'pct_sub',  1),
        ]:
            conn.execute(
                "INSERT INTO pie_rubros"
                " (proyecto_id, codigo, nombre, pct, activo, orden, tipo, mostrar_pct)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (self.pid, codigo, nombre, pct, activo, orden, tipo, mostrar_pct)
            )
        conn.commit()
        conn.close()

    def cargar_pie(self):
        conn = get_db()
        proy   = conn.execute("SELECT * FROM proyectos WHERE id=?", (self.pid,)).fetchone()
        rubros = conn.execute(
            "SELECT * FROM pie_rubros WHERE proyecto_id=? ORDER BY orden", (self.pid,)
        ).fetchall()
        conn.close()
        if not rubros:
            self._pie_crear_rubros_default(proy)
        self._render_pie()

    def _render_pie(self):
        from utils.i18n import tr
        conn = get_db()
        rubros   = conn.execute(
            "SELECT * FROM pie_rubros WHERE proyecto_id=? ORDER BY orden", (self.pid,)
        ).fetchall()
        gg_items = conn.execute(
            "SELECT * FROM gastos_generales WHERE proyecto_id=? ORDER BY orden, id",
            (self.pid,)
        ).fetchall()
        conn.close()

        _, totales = calcular_totales(self.pid)
        cd       = totales.get('cd', 0)
        rubros_l = list(rubros)
        gg_l     = [dict(g) for g in gg_items]

        # ── Panel izquierdo: Resumen + Plantillas inline ──────────────────────
        while self._pie_left_vl.count() > 1:   # preserva el stretch final
            it = self._pie_left_vl.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self._pie_left_vl.insertWidget(0, self._build_resumen())
        self._pie_left_vl.insertWidget(1, self._build_plantillas_inline(rubros_l))

        # ── Panel derecho: tabs de detalle ────────────────────────────────────
        while self._pie_right_vl.count():
            it = self._pie_right_vl.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        # Limpiar las pestañas de rubros de la barra superior (se reconstruyen).
        while self._pie_tabs_host_hl.count():
            it = self._pie_tabs_host_hl.takeAt(0)
            if it.widget():
                it.widget().deleteLater()

        # Refrescar la topbar del proyecto SIEMPRE (también cuando no hay rubros
        # activos), porque cambiar checkboxes desde el editor llama _render_pie
        # y la topbar debe reflejar el nuevo total inmediatamente.
        QTimer.singleShot(0, self.actualizar_total)

        rubros_det = [dict(r) for r in rubros_l if r['tipo'] == 'rubro' and r['activo']]

        if not rubros_det:
            # Sin rubros de detalle — placeholder
            lbl_empty = QLabel("Sin tablas de detalle activas.\nActiva rubros tipo «Con detalle» en Plantillas.")
            lbl_empty.setAlignment(Qt.AlignCenter)
            lbl_empty.setStyleSheet(f"color:{SLATE_100}; font-size:12px;")
            self._pie_right_vl.addWidget(lbl_empty)
            return

        # Las pestañas de rubros van en la barra SUPERIOR (self._pie_tabs_host);
        # aquí abajo solo se construye su contenido.
        bar_hl = self._pie_tabs_host_hl

        tab_w = QTabWidget()
        tab_w.tabBar().setVisible(False)
        tab_w.setStyleSheet("QTabWidget::pane { border:none; background:white; }")

        tab_btns: list[QPushButton] = []

        def _tab_style(sel: bool) -> str:
            bg = BLUE_500 if sel else "transparent"
            hov = "" if sel else "QPushButton:hover { background:rgba(255,255,255,0.15); color:white; }"
            return (f"QPushButton {{ background:{bg}; color:white; border:none;"
                    f" border-radius:6px; font-size:11px; font-weight:700; padding:3px 12px; }}"
                    + hov)

        # Recordar el rubro activo entre re-renders (para no rebotar al tab 0
        # cada vez que se toca un botón en otro rubro).
        rubros_codes = [r['codigo'] for r in rubros_det]
        idx_activo = 0
        if getattr(self, '_pie_rubro_actual', None) in rubros_codes:
            idx_activo = rubros_codes.index(self._pie_rubro_actual)
        else:
            self._pie_rubro_actual = rubros_codes[0] if rubros_codes else None

        def _select(idx: int):
            tab_w.setCurrentIndex(idx)
            for i, b in enumerate(tab_btns):
                b.setStyleSheet(_tab_style(i == idx))
            if 0 <= idx < len(rubros_codes):
                self._pie_rubro_actual = rubros_codes[idx]

        for i, rub in enumerate(rubros_det):
            btn = QPushButton(rub['nombre'])
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(_tab_style(i == idx_activo))
            btn.clicked.connect(lambda _, ix=i: _select(ix))
            bar_hl.addWidget(btn)
            tab_btns.append(btn)
            tab_w.addTab(self._build_detalle_rubro(rub, cd, gg_l), rub['nombre'])

        self._pie_right_vl.addWidget(tab_w, stretch=1)
        tab_w.setCurrentIndex(idx_activo)
        # Actualizar topbar del presupuesto con el nuevo total
        QTimer.singleShot(0, self.actualizar_total)

    def _filas_resumen(self, all_subs: bool = False):
        """Calcula las filas del Resumen según los pie_rubros activos del proyecto.
        Retorna lista de (nombre, monto, color, bold) + total_final.
        all_subs=True usa el CD global del proyecto (todos los subpresupuestos)."""
        conn = get_db()
        rubros   = conn.execute(
            "SELECT * FROM pie_rubros WHERE proyecto_id=? AND activo=1 ORDER BY orden",
            (self.pid,)
        ).fetchall()
        gg_items = conn.execute(
            "SELECT * FROM gastos_generales WHERE proyecto_id=? ORDER BY orden",
            (self.pid,)
        ).fetchall()
        conn.close()

        cd = self._total_proyecto(all_subs=all_subs)
        filas = [("Costo Directo", cd, SLATE_700, False)]
        acum = cd; last_sub = cd

        for rub in rubros:
            tipo = rub['tipo']; pct = rub['pct'] or 0; cod = rub['codigo']
            if tipo == 'subtotal':
                last_sub = acum
                filas.append((rub['nombre'], acum, SLATE_700, True))
            elif tipo == 'pct_sub':
                val = last_sub * pct / 100; acum += val
                filas.append((rub['nombre'], val, SLATE_500, False))
            elif tipo == 'pct_cd':
                val = cd * pct / 100; acum += val
                filas.append((rub['nombre'], val, SLATE_500, False))
            else:  # rubro con detalle
                manual = next((i for i in gg_items if i['rubro'] == cod and i['tipo'] == 'manual'), None)
                if manual:
                    val = manual['precio'] or 0
                else:
                    items_r = [i for i in gg_items if i['rubro'] == cod and i['tipo'] == 'item']
                    if items_r:
                        val = sum(
                            (i['cantidad'] or 0)
                            * ((i['pct_participacion'] or 100) / 100) * (i['precio'] or 0)
                            for i in items_r
                        )
                    else:
                        val = cd * pct / 100
                acum += val
                filas.append((rub['nombre'], val, SLATE_500, False))

        filas.append(("PRESUPUESTO TOTAL", acum, BLUE_500, True))
        return filas, acum

    def _build_resumen_card(self, title="RESUMEN DE COSTOS", all_subs: bool = False):
        """Card de Resumen de Costos basado en pie_rubros activos.
        all_subs=True usa el CD global del proyecto (todos los subpresupuestos)."""
        filas, total = self._filas_resumen(all_subs=all_subs)

        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background:white; border:1px solid {SILVER_300}; border-radius:8px; }}"
        )
        vl = QVBoxLayout(card)
        vl.setContentsMargins(14, 12, 14, 14)
        vl.setSpacing(6)

        lbl_sec = QLabel(title)
        lbl_sec.setStyleSheet(
            f"color:{SLATE_500}; font-size:10px; font-weight:700;"
            f" letter-spacing:0.8px; border:none;"
        )
        vl.addWidget(lbl_sec)
        sep0 = QFrame(); sep0.setFrameShape(QFrame.HLine)
        sep0.setStyleSheet(f"color:{SILVER_300};"); vl.addWidget(sep0)

        for nombre, monto, color, bold in filas:
            f = QFrame(); f.setStyleSheet("border:none; background:transparent;")
            hl = QHBoxLayout(f); hl.setContentsMargins(0, 0, 0, 0)
            ln = QLabel(nombre); lv = QLabel(fmt(monto, self._moneda))
            lv.setAlignment(Qt.AlignRight)
            fs = "12px" if bold else "11px"; fw = "700" if bold else "500"
            for lbl in (ln, lv):
                lbl.setStyleSheet(
                    f"color:{color}; font-size:{fs}; font-weight:{fw}; border:none;"
                )
            hl.addWidget(ln); hl.addWidget(lv)
            vl.addWidget(f)

        return card, total

    def _build_resumen(self, rubros=None, cd=None, gg_items=None):
        """Card del Pie — usa pie_rubros activos del proyecto (global, todos los subs)."""
        card, _total = self._build_resumen_card(all_subs=True)
        # El total se muestra SOLO en la barra de pestañas de proyecto; aquí
        # mantenerlo en sync al reconstruir el resumen del pie.
        if hasattr(self, 'lbl_total'):
            self.actualizar_total()
        return card

    def _build_detalle_rubro(self, rub, cd, gg_items):
        """Panel de detalle de un rubro con toggle Con detalle / Monto manual."""
        cod     = rub['codigo']
        pct_val = rub['pct'] or 0
        rows    = [i for i in gg_items if i['rubro'] == cod]
        manual_row = next((r for r in rows if r['tipo'] == 'manual'), None)
        is_manual  = manual_row is not None
        detail_rows = [r for r in rows if r['tipo'] in ('grupo', 'item')]
        detail_total = sum(
            (i['cantidad'] or 0)
            * ((i['pct_participacion'] or 100) / 100) * (i['precio'] or 0)
            for i in detail_rows if i['tipo'] == 'item'
        )

        outer = QFrame()
        outer.setStyleSheet("QFrame { background:white; border:none; }")
        vl = QVBoxLayout(outer)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)

        # ── Header ────────────────────────────────────────────────────────────
        hdr = QFrame()
        hdr.setFixedHeight(36)
        hdr.setStyleSheet(
            f"background:{SILVER_100}; border-bottom:1px solid {SILVER_300};"
        )
        hdr_hl = QHBoxLayout(hdr)
        hdr_hl.setContentsMargins(10, 0, 8, 0)
        hdr_hl.setSpacing(6)

        lbl_h = QLabel(rub['nombre'].upper())
        lbl_h.setStyleSheet(
            f"color:{SLATE_500}; font-size:10px; font-weight:700;"
            f" letter-spacing:0.5px; border:none;"
        )
        hdr_hl.addWidget(lbl_h)
        lbl_pct = QLabel(f"{pct_val:.1f}% CD")
        lbl_pct.setStyleSheet(f"color:{SLATE_100}; font-size:10px; border:none;")
        hdr_hl.addWidget(lbl_pct)

        # Botones + Grupo / + Ítem — izquierda, junto al título
        if not is_manual:
            def _hbtn_left(text, slot):
                b = QPushButton(text)
                b.setCursor(Qt.PointingHandCursor)
                b.setFixedHeight(22)
                b.setStyleSheet(
                    f"QPushButton {{ background:#E8EAED; border:1px solid {SILVER_300};"
                    f" border-radius:4px; font-size:10px; color:{SLATE_500}; padding:0 8px; }}"
                    f"QPushButton:hover {{ background:#D8DADD; }}"
                )
                b.clicked.connect(slot)
                return b
            hdr_hl.addWidget(_hbtn_left("+ Grupo",   lambda: self._gg_agregar_grupo(cod)))
            hdr_hl.addWidget(_hbtn_left("+ Ítem",    lambda: self._gg_agregar_item(cod)))
            btn_pl = _hbtn_left("Cargar plantilla ▾", lambda: None)
            btn_pl.setMenu(self._gg_plantilla_menu(cod))
            btn_pl.setStyleSheet(
                btn_pl.styleSheet()
                + "QPushButton::menu-indicator{image:none;width:0;}")
            hdr_hl.addWidget(btn_pl)
            hdr_hl.addWidget(_hbtn_left("Guardar plantilla",
                                        lambda: self._gg_guardar_plantilla_usuario(cod)))
            hdr_hl.addWidget(_hbtn_left("Exportar",  lambda: self._gg_export_plantilla(cod)))

        hdr_hl.addStretch()

        def _toggle_btn(text, active):
            b = QPushButton(text)
            b.setCursor(Qt.PointingHandCursor)
            b.setFixedHeight(22)
            if active:
                b.setStyleSheet(
                    f"QPushButton {{ background:{SLATE_500}; color:white; border:none;"
                    f" border-radius:4px; font-size:10px; padding:0 8px; }}"
                )
            else:
                b.setStyleSheet(
                    f"QPushButton {{ background:#E8EAED; color:{SLATE_300};"
                    f" border:1px solid {SILVER_300}; border-radius:4px;"
                    f" font-size:10px; padding:0 8px; }}"
                    f"QPushButton:hover {{ background:#D8DADD; color:{SLATE_500}; }}"
                )
            return b

        btn_det = _toggle_btn("Con detalle", not is_manual)
        btn_man = _toggle_btn("Monto manual", is_manual)

        def _ir_detalle():
            conn = get_db()
            conn.execute(
                "DELETE FROM gastos_generales WHERE proyecto_id=? AND rubro=? AND tipo='manual'",
                (self.pid, cod)
            )
            conn.commit(); conn.close()
            self._render_pie()

        def _ir_manual():
            monto_actual = manual_row['precio'] if manual_row else 0.0
            conn = get_db()
            conn.execute(
                "DELETE FROM gastos_generales WHERE proyecto_id=? AND rubro=? AND tipo='manual'",
                (self.pid, cod)
            )
            conn.execute(
                "INSERT INTO gastos_generales"
                " (proyecto_id, rubro, tipo, descripcion, precio, orden)"
                " VALUES (?,?,?,?,?,?)",
                (self.pid, cod, 'manual', '__manual__', monto_actual, 0)
            )
            conn.commit(); conn.close()
            self._render_pie()

        btn_det.clicked.connect(_ir_detalle)
        btn_man.clicked.connect(_ir_manual)
        # Total del rubro — visible arriba, antes de los toggles, para no tener
        # que bajar al pie a leerlo. En modo manual = el monto ingresado.
        total_hdr = (manual_row['precio'] or 0) if is_manual else detail_total
        lbl_tot_hdr = QLabel(f"Total: {fmt(total_hdr, self._moneda)}")
        lbl_tot_hdr.setStyleSheet(
            f"color:{SLATE_700}; font-size:11px; font-weight:700;"
            f" background:transparent; border:none;"
        )
        hdr_hl.addWidget(lbl_tot_hdr)
        hdr_hl.addSpacing(10)
        hdr_hl.addWidget(btn_det)
        hdr_hl.addWidget(btn_man)

        vl.addWidget(hdr)

        # ── Contenido según modo ───────────────────────────────────────────────
        if is_manual:
            # Modo monto manual — input anclado arriba
            body = QFrame()
            body.setStyleSheet("background:white; border:none;")
            body_vl = QVBoxLayout(body)
            body_vl.setContentsMargins(20, 16, 20, 16)
            body_vl.setSpacing(8)

            lbl_m = QLabel("Monto total del rubro:")
            lbl_m.setStyleSheet(f"color:{SLATE_500}; font-size:11px; border:none;")
            lbl_m.setAlignment(Qt.AlignCenter)
            body_vl.addWidget(lbl_m)

            inp_row = QFrame(); inp_row.setStyleSheet("border:none;")
            inp_hl = QHBoxLayout(inp_row)
            inp_hl.setContentsMargins(0, 0, 0, 0)
            inp_hl.setSpacing(6)

            inp_monto = QLineEdit(f"{manual_row['precio'] or 0:.2f}")
            inp_monto.setAlignment(Qt.AlignRight)
            inp_monto.setFixedWidth(180)
            inp_monto.setStyleSheet(
                f"border:1px solid {SILVER_300}; border-radius:6px;"
                f" padding:6px 10px; font-size:14px; font-weight:600;"
                f" color:{SLATE_700};"
            )
            inp_monto.setPlaceholderText("0.00")

            def _save_manual():
                try:
                    monto = parse_num(inp_monto.text())
                except Exception:
                    monto = 0.0
                conn = get_db()
                conn.execute(
                    "UPDATE gastos_generales SET precio=?"
                    " WHERE proyecto_id=? AND rubro=? AND tipo='manual'",
                    (monto, self.pid, cod)
                )
                conn.commit(); conn.close()
                QTimer.singleShot(0, self._render_pie)

            inp_monto.editingFinished.connect(_save_manual)
            inp_hl.addStretch()
            inp_hl.addWidget(inp_monto)
            inp_hl.addStretch()
            body_vl.addWidget(inp_row)

            lbl_hint = QLabel(
                "Ingresa el monto total directamente.\n"
                "Puedes volver a «Con detalle» para usar la tabla de ítems."
            )
            lbl_hint.setStyleSheet(f"color:{SLATE_100}; font-size:10px; border:none;")
            lbl_hint.setAlignment(Qt.AlignCenter)
            body_vl.addWidget(lbl_hint)
            body_vl.addStretch()
            vl.addWidget(body, stretch=1)

        else:
            # Modo con detalle — tabla de ítems
            cols = ["Descripción", "Unidad", "% Participación", "Cantidad",
                    "Precio", "Total", ""]
            tbl = QTableWidget(0, len(cols))
            tbl.setHorizontalHeaderLabels(cols)
            th = tbl.horizontalHeader()
            th.setSectionResizeMode(0, QHeaderView.Stretch)
            for c in range(1, len(cols) - 1):
                th.setSectionResizeMode(c, QHeaderView.ResizeToContents)
            th.setSectionResizeMode(len(cols) - 1, QHeaderView.Fixed)
            tbl.horizontalHeader().resizeSection(len(cols) - 1, 26)
            tbl.verticalHeader().setVisible(False)
            tbl.setAlternatingRowColors(False)
            tbl.setSelectionMode(QAbstractItemView.ExtendedSelection)
            tbl.setEditTriggers(
                QAbstractItemView.CurrentChanged  |
                QAbstractItemView.AnyKeyPressed   |
                QAbstractItemView.SelectedClicked
            )
            tbl.setItemDelegate(_GGDelegate(tbl))
            tbl.setStyleSheet(f"""
                QTableWidget {{ border:none; font-size:11px; gridline-color:#E8EAED; }}
                QTableWidget::item {{ padding:2px 4px; }}
                QTableWidget::item:selected {{ background:#FEF0E0; }}
                QHeaderView::section {{
                    background:{SLATE_500}; color:white; font-size:10px;
                    font-weight:700; padding:4px 4px; border:none;
                }}
            """)

            HDR_BG = QColor(SILVER_100)
            HDR_FG = QColor(SLATE_700)
            COL_DEL = len(cols) - 1     # columna del botón eliminar (6)
            RDONLY = {5}                # Total (calculado)

            def _del_btn_for(rid):
                b = QPushButton("✕")
                b.setFixedSize(18, 18)
                b.setStyleSheet(
                    f"QPushButton {{ color:{SLATE_100}; border:none; background:none;"
                    f" font-size:12px; padding:0; }}"
                    f"QPushButton:hover {{ color:{RED_500}; }}"
                )
                b.clicked.connect(lambda _, r=rid: self._gg_del_item(r))
                return b

            for row in detail_rows:
                r = tbl.rowCount()
                tbl.insertRow(r)
                if row['tipo'] == 'grupo':
                    for c in range(len(cols)):
                        cell = QTableWidgetItem(row['descripcion'] if c == 0 else '')
                        cell.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsDragEnabled)
                        cell.setBackground(QBrush(HDR_BG))
                        cell.setForeground(QBrush(HDR_FG))
                        f = QFont(); f.setBold(True); cell.setFont(f)
                        tbl.setItem(r, c, cell)
                    tbl.setRowHeight(r, 22)
                    tbl.setCellWidget(r, COL_DEL, _del_btn_for(row['id']))
                else:
                    pp  = row['pct_participacion']
                    cant = row['cantidad']
                    pr  = row['precio']
                    def _s(v): return f"{v:g}" if v is not None else ''
                    # % Participación: vacío ⇒ 100% por defecto (mostrado y usado).
                    pp_eff = pp if pp is not None else 100
                    # Total = Cantidad × (% Participación / 100) × Precio
                    if cant is not None and pr is not None:
                        tot = (cant or 0) * (pp_eff / 100) * (pr or 0)
                        tot_s = fmt(tot, self._moneda)
                    else:
                        tot_s = ''
                    for c, val in enumerate([
                        row['descripcion'] or '',
                        row['unidad'] or '',
                        _s(pp_eff), _s(cant), _s(pr),
                        tot_s,
                        '',
                    ]):
                        cell = QTableWidgetItem(val)
                        if c in RDONLY:
                            cell.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsDragEnabled)
                            cell.setBackground(QBrush(_NEUTRAL_BG))
                        cell.setTextAlignment(
                            (Qt.AlignRight | Qt.AlignVCenter) if c > 0
                            else (Qt.AlignLeft | Qt.AlignVCenter)
                        )
                        tbl.setItem(r, c, cell)
                    tbl.setCellWidget(r, COL_DEL, _del_btn_for(row['id']))

                tbl.item(r, 0).setData(Qt.UserRole,     row['id'])
                tbl.item(r, 0).setData(Qt.UserRole + 1, row['tipo'])

            tbl.cellChanged.connect(lambda row, col: self._gg_save_cell(tbl, row, col))
            tbl.resizeRowsToContents()

            # Drag & drop para reordenar filas
            tbl.setDragEnabled(True)
            tbl.setAcceptDrops(True)
            tbl.setDragDropMode(QAbstractItemView.InternalMove)
            tbl.setDragDropOverwriteMode(False)
            tbl.setDropIndicatorShown(True)
            tbl.setDefaultDropAction(Qt.MoveAction)

            def _sync_drag_order(*_):
                ids = [tbl.item(r, 0).data(Qt.UserRole)
                       for r in range(tbl.rowCount())
                       if tbl.item(r, 0) and tbl.item(r, 0).data(Qt.UserRole)]
                if not ids: return
                conn = get_db()
                for i, iid in enumerate(ids):
                    conn.execute("UPDATE gastos_generales SET orden=? WHERE id=?", (i, iid))
                conn.commit(); conn.close()
                QTimer.singleShot(0, self._render_pie)

            tbl.model().rowsMoved.connect(_sync_drag_order)

            # ── Copiar / Pegar / Eliminar con selección múltiple ────────────────────
            def _copy_sel():
                rows_s = sorted(set(i.row() for i in tbl.selectedIndexes()))
                _GG_CLIPBOARD.clear()
                for r in rows_s:
                    ic = tbl.item(r, 0)
                    if not ic or not ic.data(Qt.UserRole): continue
                    e = {'tipo': ic.data(Qt.UserRole + 1),
                         'descripcion': ic.text()}
                    if e['tipo'] == 'item':
                        def _txt(col, defv=None):
                            c = tbl.item(r, col)
                            if not c or not c.text().strip(): return defv
                            try: return float(c.text().replace(',','.'))
                            except: return defv
                        e.update({'unidad': (tbl.item(r,1).text() if tbl.item(r,1) else ''),
                                  'pct_participacion': _txt(2), 'cantidad': _txt(3),
                                  'precio': _txt(4)})
                    _GG_CLIPBOARD.append(e)

            def _paste_sel():
                if not _GG_CLIPBOARD: return
                conn = get_db()
                base_o = (conn.execute(
                    "SELECT COALESCE(MAX(orden),0) FROM gastos_generales WHERE proyecto_id=?",
                    (self.pid,)
                ).fetchone()[0] or 0) + 1
                for i, it in enumerate(_GG_CLIPBOARD):
                    cant = it.get('cantidad')
                    if cant is None:
                        cant = (it.get('n_personas', 1) or 1) * (it.get('tiempo', 1) or 1)
                    conn.execute(
                        "INSERT INTO gastos_generales (proyecto_id,rubro,tipo,descripcion,"
                        "unidad,cantidad,pct_participacion,precio,orden)"
                        " VALUES (?,?,?,?,?,?,?,?,?)",
                        (self.pid, cod, it.get('tipo','item'), it.get('descripcion',''),
                         it.get('unidad','MES'), cant,
                         it.get('pct_participacion',100), it.get('precio',0), base_o+i)
                    )
                conn.commit(); conn.close()
                self._render_pie()

            def _del_sel():
                rows_s = sorted(set(i.row() for i in tbl.selectedIndexes()), reverse=True)
                ids = [tbl.item(r,0).data(Qt.UserRole)
                       for r in rows_s if tbl.item(r,0) and tbl.item(r,0).data(Qt.UserRole)]
                if not ids: return
                conn = get_db()
                for iid in ids: conn.execute("DELETE FROM gastos_generales WHERE id=?",(iid,))
                conn.commit(); conn.close()
                QTimer.singleShot(0, self._render_pie)

            def _dup_sel():
                """Duplica las filas seleccionadas (ítems/grupos) al final del rubro."""
                rows_s = sorted(set(i.row() for i in tbl.selectedIndexes()))
                dup = []
                for r in rows_s:
                    ic = tbl.item(r, 0)
                    if not ic or not ic.data(Qt.UserRole): continue
                    tp = ic.data(Qt.UserRole + 1)
                    e = {'tipo': tp, 'descripcion': ic.text()}
                    if tp == 'item':
                        def _txt(col):
                            c = tbl.item(r, col)
                            if not c or not c.text().strip(): return None
                            try: return float(c.text().replace(',', '.'))
                            except: return None
                        e.update({'unidad': (tbl.item(r,1).text() if tbl.item(r,1) else ''),
                                  'pct_participacion': _txt(2), 'cantidad': _txt(3),
                                  'precio': _txt(4)})
                    dup.append(e)
                if not dup: return
                conn = get_db()
                base_o = (conn.execute(
                    "SELECT COALESCE(MAX(orden),0) FROM gastos_generales WHERE proyecto_id=?",
                    (self.pid,)).fetchone()[0] or 0) + 1
                for i, it in enumerate(dup):
                    conn.execute(
                        "INSERT INTO gastos_generales (proyecto_id,rubro,tipo,descripcion,"
                        "unidad,cantidad,pct_participacion,precio,orden)"
                        " VALUES (?,?,?,?,?,?,?,?,?)",
                        (self.pid, cod, it.get('tipo','item'), it.get('descripcion',''),
                         it.get('unidad','') or '', it.get('cantidad'),
                         it.get('pct_participacion'), it.get('precio'), base_o+i))
                conn.commit(); conn.close()
                QTimer.singleShot(0, self._render_pie)

            # QShortcuts con WidgetWithChildrenShortcut (prioridad sobre el global)
            for _key, _fn in [(Qt.Key_Delete, _del_sel), (Qt.Key_Backspace, _del_sel),
                               (Qt.Key_C|Qt.ControlModifier, _copy_sel),
                               (Qt.Key_V|Qt.ControlModifier, _paste_sel),
                               (Qt.Key_D|Qt.ControlModifier, _dup_sel)]:
                _sc = QShortcut(QKeySequence(_key), tbl)
                _sc.setContext(Qt.WidgetWithChildrenShortcut)
                _sc.activated.connect(_fn)

            # Menú contextual clic derecho
            tbl.setContextMenuPolicy(Qt.CustomContextMenu)
            def _ctx_menu(pos, base=tbl):
                from utils.i18n import tr
                rows_s = sorted(set(i.row() for i in base.selectedIndexes()))
                n = len(rows_s)
                menu = QMenu(base)
                # Agregar
                menu.addAction("+ " + tr("Ítem")).triggered.connect(
                    lambda: self._gg_agregar_item(cod))
                menu.addAction("+ " + tr("Grupo")).triggered.connect(
                    lambda: self._gg_agregar_grupo(cod))
                # Operaciones sobre la selección
                if rows_s:
                    menu.addSeparator()
                    menu.addAction(f"{tr('Duplicar')} ({n})  Ctrl+D")\
                        .triggered.connect(_dup_sel)
                    menu.addAction(f"{tr('Copiar')} ({n})  Ctrl+C")\
                        .triggered.connect(_copy_sel)
                if _GG_CLIPBOARD:
                    menu.addAction(f"{tr('Pegar')} ({len(_GG_CLIPBOARD)})  Ctrl+V")\
                        .triggered.connect(_paste_sel)
                if rows_s:
                    menu.addSeparator()
                    menu.addAction(f"{tr('Eliminar')} ({n})").triggered.connect(_del_sel)
                menu.exec(base.viewport().mapToGlobal(pos))
            tbl.customContextMenuRequested.connect(_ctx_menu)

            vl.addWidget(tbl, stretch=1)

            # Pie de totales
            tot      = detail_total
            pct_real = tot / cd * 100 if cd > 0 else 0
            ref      = cd * pct_val / 100

            footer = QFrame()
            footer.setFixedHeight(36)
            footer.setStyleSheet(
                f"background:{SILVER_100}; border-top:1px solid {SILVER_300};"
            )
            f_hl = QHBoxLayout(footer)
            f_hl.setContentsMargins(12, 0, 12, 0)
            f_hl.setSpacing(0)
            f_hl.addStretch()
            for lbl_t, val_t in [
                ("Total detallado:",          fmt(tot, self._moneda)),
                ("   % sobre CD:",             f"{pct_real:.2f}%"),
                (f"   Ref. {pct_val:.1f}% CD:", fmt(ref, self._moneda)),
            ]:
                ll = QLabel(lbl_t)
                ll.setStyleSheet(
                    f"color:{SLATE_500}; font-size:10px;"
                    f" background:transparent; border:none;"
                )
                lv = QLabel(val_t)
                lv.setStyleSheet(
                    f"color:{SLATE_700}; font-size:11px; font-weight:700;"
                    f" background:transparent; border:none;"
                )
                f_hl.addWidget(ll); f_hl.addWidget(lv)
            vl.addWidget(footer)

        return outer

    def _gg_save_cell(self, tbl, row, col):
        # Columnas: 0 Desc · 1 Unidad · 2 %Part · 3 Cantidad · 4 Precio ·
        #           5 Total(calc) · 6 botón. Solo 0-4 son editables.
        if col in (5, 6):
            return
        id_cell = tbl.item(row, 0)
        if not id_cell:
            return
        item_id = id_cell.data(Qt.UserRole)
        tipo    = id_cell.data(Qt.UserRole + 1)
        if not item_id or tipo != 'item':
            return
        val   = tbl.item(row, col).text().strip() if tbl.item(row, col) else ''
        field = {0: 'descripcion', 1: 'unidad', 2: 'pct_participacion',
                 3: 'cantidad', 4: 'precio'}.get(col)
        if not field:
            return
        conn = get_db()
        is_numeric = field in ('pct_participacion', 'cantidad', 'precio')
        if is_numeric:
            try: num = parse_num(val) if val else None
            except: num = None
            # % Participación: vacío ⇒ 100% por defecto.
            if field == 'pct_participacion' and num is None:
                num = 100
            conn.execute(f"UPDATE gastos_generales SET {field}=? WHERE id=?", (num, item_id))
        else:
            conn.execute(f"UPDATE gastos_generales SET {field}=? WHERE id=?", (val, item_id))
        conn.commit()
        conn.close()

        if is_numeric:
            # Si el % quedó vacío, reflejá el 100 por defecto en la celda.
            if field == 'pct_participacion' and not val:
                tbl.blockSignals(True)
                if tbl.item(row, 2): tbl.item(row, 2).setText('100')
                tbl.blockSignals(False)
            # Actualizar Total en la misma fila SIN re-renderizar
            # (evita destruir la tabla y cortar la navegación con teclado)
            def _v(c):
                it = tbl.item(row, c)
                try: return parse_num(it.text()) if it and it.text().strip() else None
                except: return None
            pp, cant, pr = _v(2), _v(3), _v(4)
            if cant is not None and pr is not None:
                tot = (cant or 0) * (((pp if pp is not None else 100)) / 100) * (pr or 0)
                tot_s = fmt(tot, self._moneda)
            else:
                tot_s = ''
            tbl.blockSignals(True)
            if tbl.item(row, 5): tbl.item(row, 5).setText(tot_s)
            tbl.blockSignals(False)
            # Refrescar Resumen diferido 600ms — no interrumpe la navegación
            if not hasattr(self, '_gg_render_timer'):
                self._gg_render_timer = QTimer()
                self._gg_render_timer.setSingleShot(True)
                self._gg_render_timer.timeout.connect(self._render_pie)
            self._gg_render_timer.start(600)

    def _gg_agregar_grupo(self, cod: str):
        nombre, ok = QInputDialog.getText(self, "Nuevo grupo", "Nombre del grupo:")
        if not ok or not nombre.strip():
            return
        conn  = get_db()
        orden = (conn.execute(
            "SELECT COALESCE(MAX(orden),0) FROM gastos_generales WHERE proyecto_id=?",
            (self.pid,)
        ).fetchone()[0] or 0) + 1
        conn.execute(
            "INSERT INTO gastos_generales (proyecto_id, rubro, tipo, descripcion, orden)"
            " VALUES (?,?,?,?,?)",
            (self.pid, cod, 'grupo', nombre.strip(), orden)
        )
        conn.commit()
        conn.close()
        self._render_pie()

    def _gg_agregar_item(self, cod: str):
        conn  = get_db()
        orden = (conn.execute(
            "SELECT COALESCE(MAX(orden),0) FROM gastos_generales WHERE proyecto_id=?",
            (self.pid,)
        ).fetchone()[0] or 0) + 1
        conn.execute(
            "INSERT INTO gastos_generales"
            " (proyecto_id, rubro, tipo, descripcion, unidad, cantidad,"
            "  pct_participacion, precio, orden)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (self.pid, cod, 'item', '', '', None, 100, None, orden)
        )
        conn.commit()
        conn.close()
        self._render_pie()

    def _gg_export_plantilla(self, cod: str):
        import json as _json
        conn = get_db()
        rows = conn.execute(
            "SELECT tipo,descripcion,unidad,cantidad,pct_participacion,precio"
            " FROM gastos_generales WHERE proyecto_id=? AND rubro=? AND tipo!='manual'"
            " ORDER BY orden",
            (self.pid, cod)
        ).fetchall()
        conn.close()
        data = {'rubro': cod, 'items': [dict(r) for r in rows]}
        path_f, _ = _QFileDialog.getSaveFileName(
            self, "Exportar plantilla",
            f"plantilla_{cod}.json", "JSON (*.json)"
        )
        if not path_f:
            return
        with open(path_f, 'w', encoding='utf-8') as f:
            _json.dump(data, f, ensure_ascii=False, indent=2)
        QMessageBox.information(self, "Exportar",
                                f"Plantilla «{cod}» exportada correctamente.")

    def _gg_import_plantilla(self, cod: str):
        import json as _json
        path_f, _ = _QFileDialog.getOpenFileName(
            self, "Importar plantilla", "", "JSON (*.json)"
        )
        if not path_f:
            return
        try:
            with open(path_f, 'r', encoding='utf-8') as f:
                data = _json.load(f)
        except Exception as e:
            QMessageBox.warning(self, "Error", f"No se pudo leer el archivo: {e}")
            return
        self._gg_aplicar_plantilla_items(cod, data.get('items', []))

    def _gg_aplicar_plantilla_items(self, cod: str, items: list):
        """Vuelca una lista de ítems de plantilla en el rubro `cod`.
        Pregunta si reemplazar los ítems actuales o añadir al final.
        Compartido por la importación desde archivo y las plantillas
        precargadas (`core/plantillas_pie.py`)."""
        if not items:
            QMessageBox.warning(self, "Plantilla", "La plantilla no contiene ítems.")
            return
        reply = QMessageBox.question(
            self, "Cargar plantilla",
            f"¿Reemplazar los ítems actuales de «{cod}»?\n«No» añade los ítems al final.",
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel
        )
        if reply == QMessageBox.Cancel:
            return
        conn = get_db()
        if reply == QMessageBox.Yes:
            conn.execute(
                "DELETE FROM gastos_generales"
                " WHERE proyecto_id=? AND rubro=? AND tipo!='manual'",
                (self.pid, cod)
            )
        base_o = (conn.execute(
            "SELECT COALESCE(MAX(orden),0) FROM gastos_generales WHERE proyecto_id=?",
            (self.pid,)
        ).fetchone()[0] or 0) + 1
        for i, it in enumerate(items):
            # La plantilla puede traer 'cantidad' (modelo nuevo) o el modelo
            # antiguo 'n_personas'×'tiempo' → se colapsan en cantidad.
            cant = it.get('cantidad')
            if cant is None:
                cant = (it.get('n_personas', 1) or 1) * (it.get('tiempo', 1) or 1)
            conn.execute(
                "INSERT INTO gastos_generales"
                " (proyecto_id,rubro,tipo,descripcion,unidad,cantidad,"
                "  pct_participacion,precio,orden) VALUES (?,?,?,?,?,?,?,?,?)",
                (self.pid, cod, it.get('tipo','item'), it.get('descripcion',''),
                 it.get('unidad','MES'), cant,
                 it.get('pct_participacion',100), it.get('precio',0), base_o+i)
            )
        conn.commit(); conn.close()
        self._render_pie()

    def _gg_cargar_plantilla_builtin(self, cod: str, key: str):
        """Carga una plantilla precargada (borrador) en el rubro `cod`."""
        from core.plantillas_pie import obtener_plantilla_pie
        self._gg_aplicar_plantilla_items(cod, obtener_plantilla_pie(key))

    def _gg_plantilla_menu(self, cod: str):
        """Menú del botón «Cargar plantilla»: mis plantillas guardadas +
        borradores precargados + importar desde archivo JSON."""
        from PySide6.QtWidgets import QMenu
        from core.plantillas_pie import listar_plantillas_pie
        from core.database import listar_plantillas_pie_guardadas
        m = QMenu(self)

        # Mis plantillas (guardadas por el usuario en la app)
        guardadas = listar_plantillas_pie_guardadas()
        hdr = m.addAction("Mis plantillas")
        hdr.setEnabled(False)
        if guardadas:
            for pid, nombre in guardadas:
                act = m.addAction("   " + nombre)
                act.triggered.connect(
                    lambda _=False, p=pid, c=cod: self._gg_cargar_plantilla_guardada(c, p))
        else:
            vacia = m.addAction("   — ninguna guardada —")
            vacia.setEnabled(False)
        m.addSeparator()

        # Borradores precargados (biblioteca de fábrica)
        prec = m.addAction("Precargadas")
        prec.setEnabled(False)
        for key, nombre, _items in listar_plantillas_pie():
            act = m.addAction("   " + nombre)
            act.triggered.connect(
                lambda _=False, k=key, c=cod: self._gg_cargar_plantilla_builtin(c, k))
        m.addSeparator()

        if guardadas:
            act_del = m.addAction("Eliminar plantilla guardada…")
            act_del.triggered.connect(lambda _=False: self._gg_eliminar_plantilla_guardada())
        act_file = m.addAction("Cargar desde archivo…")
        act_file.triggered.connect(lambda _=False, c=cod: self._gg_import_plantilla(c))
        return m

    def _gg_recolectar_items(self, cod: str) -> list:
        """Lee los ítems de detalle (grupos/ítems, sin el monto manual) del
        rubro `cod` del proyecto activo, en orden, para guardarlos/exportarlos."""
        conn = get_db()
        rows = conn.execute(
            "SELECT tipo,descripcion,unidad,cantidad,pct_participacion,precio"
            " FROM gastos_generales WHERE proyecto_id=? AND rubro=? AND tipo!='manual'"
            " ORDER BY orden", (self.pid, cod)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def _gg_guardar_plantilla_usuario(self, cod: str):
        """Guarda el detalle actual del rubro como plantilla reutilizable en la
        app (no un archivo). Se podrá cargar luego desde «Cargar plantilla ▾»."""
        items = self._gg_recolectar_items(cod)
        if not items:
            QMessageBox.warning(self, "Guardar plantilla",
                                "Este rubro no tiene ítems con detalle para guardar.")
            return
        from core.database import (listar_plantillas_pie_guardadas,
                                    guardar_plantilla_pie)
        nombre, ok = QInputDialog.getText(
            self, "Guardar plantilla",
            "Nombre de la plantilla:\n(si ya existe, se reemplaza)")
        nombre = (nombre or '').strip()
        if not ok or not nombre:
            return
        existe = any(n.lower() == nombre.lower()
                     for _, n in listar_plantillas_pie_guardadas())
        if existe:
            r = QMessageBox.question(
                self, "Guardar plantilla",
                f"Ya existe una plantilla «{nombre}». ¿Reemplazarla?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if r != QMessageBox.Yes:
                return
        guardar_plantilla_pie(nombre, items)
        QMessageBox.information(self, "Guardar plantilla",
                                f"Plantilla «{nombre}» guardada.")
        QTimer.singleShot(0, self._render_pie)   # refresca el menú

    def _gg_cargar_plantilla_guardada(self, cod: str, plantilla_id: int):
        from core.database import obtener_plantilla_pie_guardada
        self._gg_aplicar_plantilla_items(cod, obtener_plantilla_pie_guardada(plantilla_id))

    def _gg_eliminar_plantilla_guardada(self):
        from core.database import (listar_plantillas_pie_guardadas,
                                    eliminar_plantilla_pie_guardada)
        guardadas = listar_plantillas_pie_guardadas()
        if not guardadas:
            return
        nombres = [n for _, n in guardadas]
        nombre, ok = QInputDialog.getItem(
            self, "Eliminar plantilla guardada",
            "Selecciona la plantilla a eliminar:", nombres, 0, False)
        if not ok or not nombre:
            return
        pid = next((p for p, n in guardadas if n == nombre), None)
        if pid is None:
            return
        r = QMessageBox.question(
            self, "Eliminar plantilla",
            f"¿Eliminar la plantilla «{nombre}»?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if r != QMessageBox.Yes:
            return
        eliminar_plantilla_pie_guardada(pid)
        QTimer.singleShot(0, self._render_pie)

    def _gg_del_item(self, item_id: int):
        conn = get_db()
        conn.execute("DELETE FROM gastos_generales WHERE id=?", (item_id,))
        conn.commit()
        conn.close()
        QTimer.singleShot(0, self._render_pie)

    def _build_plantillas_inline(self, rubros) -> QFrame:
        """Plantillas con drag-and-drop para reordenar — panel izquierdo del Pie."""
        from utils.i18n import tr
        TIPO_BADGE = {
            'rubro':    'Con detalle',
            'pct_cd':   '% CD',
            'pct_sub':  '% SubTot.',
            'subtotal': 'Separador',
        }

        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background:white; border:1px solid {SILVER_300}; border-radius:8px; }}"
        )
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        vl = QVBoxLayout(card)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)

        # Header
        hdr = QFrame()
        hdr.setFixedHeight(32)
        hdr.setStyleSheet(
            f"background:{SILVER_100}; border-radius:8px 8px 0 0;"
            f" border-bottom:1px solid {SILVER_300};"
            f" border-top:none; border-left:none; border-right:none;"
        )
        hdr_hl = QHBoxLayout(hdr)
        hdr_hl.setContentsMargins(14, 0, 14, 0)
        lbl_h = QLabel("PLANTILLAS")
        lbl_h.setStyleSheet(
            f"color:{SLATE_500}; font-size:10px; font-weight:700;"
            f" letter-spacing:0.8px; border:none;"
        )
        hdr_hl.addWidget(lbl_h)
        hdr_hl.addStretch()
        lbl_hint = QLabel("Arrastra ⠿ para reordenar")
        lbl_hint.setStyleSheet(f"color:{SLATE_100}; font-size:9px; border:none;")
        hdr_hl.addWidget(lbl_hint)
        vl.addWidget(hdr)

        # Lista drag & drop
        self._pl_data = [dict(r) for r in rubros]

        list_w = _RubDragList()
        list_w.setFrameShape(QFrame.NoFrame)
        list_w.setStyleSheet(f"""
            QListWidget {{
                border:none; background:white; outline:none;
            }}
            QListWidget::item {{
                border-bottom:1px solid {SILVER_300};
                padding:0px;
            }}
            QListWidget::item:selected {{
                background:transparent;
            }}
        """)

        def _save_all():
            conn = get_db()
            conn.execute("DELETE FROM pie_rubros WHERE proyecto_id=?", (self.pid,))
            for i, r in enumerate(self._pl_data):
                conn.execute(
                    "INSERT INTO pie_rubros"
                    " (proyecto_id, codigo, nombre, pct, activo, orden, tipo, mostrar_pct)"
                    " VALUES (?,?,?,?,?,?,?,?)",
                    (self.pid, r['codigo'], r['nombre'],
                     r.get('pct') or 0, 1 if r['activo'] else 0,
                     i, r['tipo'], r.get('mostrar_pct', 1))
                )
            conn.commit(); conn.close()
            self._render_pie()

        def _save_field(idx, field, value):
            self._pl_data[idx][field] = value
            rid = self._pl_data[idx].get('id')
            if rid:
                conn = get_db()
                conn.execute(f"UPDATE pie_rubros SET {field}=? WHERE id=?", (value, rid))
                conn.commit(); conn.close()

        def _sync_order():
            """Llamado tras soltar — lee el orden actual del QListWidget y guarda."""
            new_data = [list_w.item(i).data(Qt.UserRole)
                        for i in range(list_w.count())]
            self._pl_data = new_data
            _save_all()

        list_w.reordered.connect(_sync_order)

        def _del_by_row(row):
            if 0 <= row < len(self._pl_data):
                self._pl_data.pop(row)
                _save_all()

        list_w.delete_requested.connect(_del_by_row)

        def _ctx_menu(pos):
            from utils.i18n import tr
            row = list_w.currentRow()
            if row < 0:
                return
            menu = QMenu(list_w)
            act = menu.addAction(tr("Eliminar"))
            act.triggered.connect(lambda: _del_by_row(row))
            menu.exec(list_w.viewport().mapToGlobal(pos))

        list_w.customContextMenuRequested.connect(_ctx_menu)

        def _del(idx):
            self._pl_data.pop(idx)
            _save_all()

        def rebuild():
            list_w.clear()
            for i, rub in enumerate(self._pl_data):
                tipo  = rub['tipo']
                badge = TIPO_BADGE.get(tipo, tipo)
                has_pct = tipo in ('pct_cd', 'pct_sub')

                # Widget de fila
                row_f = QFrame()
                row_f.setStyleSheet("QFrame { background:white; border:none; }")
                row_hl = QHBoxLayout(row_f)
                row_hl.setContentsMargins(6, 4, 8, 4)
                row_hl.setSpacing(4)

                # Handle de arrastre
                handle = QLabel("⠿")
                handle.setFixedWidth(14)
                handle.setStyleSheet(
                    f"color:{SLATE_100}; font-size:15px; border:none;"
                )
                handle.setCursor(Qt.OpenHandCursor)
                handle.setToolTip(tr("Arrastra para reordenar"))
                # Filtro de drag: selecciona la fila y arranca el drag del QListWidget
                _df = _HandleDragFilter(list_w, i, parent=handle)
                handle.installEventFilter(_df)
                handle.setMouseTracking(True)
                row_hl.addWidget(handle)

                # Checkbox activo
                chk = QCheckBox()
                chk.setChecked(bool(rub['activo']))
                chk.setToolTip(tr("Activar / desactivar"))
                chk.stateChanged.connect(
                    lambda v, idx=i: (_save_field(idx, 'activo', 1 if v else 0),
                                      _save_all())
                )
                def _sel_chk(ev, idx=i, base=chk):
                    list_w.setCurrentRow(idx)
                    QCheckBox.mousePressEvent(base, ev)
                chk.mousePressEvent = _sel_chk
                row_hl.addWidget(chk)

                # Nombre editable
                inp_n = _StyledLineEdit(rub['nombre'])
                inp_n.setStyleSheet(
                    f"border:none; border-bottom:1px solid {SILVER_300};"
                    f" border-radius:0; padding:1px 2px; font-size:11px;"
                    f" color:{SLATE_700}; background:transparent;"
                )
                inp_n.editingFinished.connect(
                    lambda idx=i, w=inp_n: _save_field(idx, 'nombre', w.text())
                )
                # Seleccionar fila al recibir foco
                def _select_on_focus(ev, idx=i, base=inp_n):
                    list_w.setCurrentRow(idx)
                    QLineEdit.focusInEvent(base, ev)
                inp_n.focusInEvent = _select_on_focus
                row_hl.addWidget(inp_n, stretch=1)

                # Badge tipo
                lbl_b = QLabel(badge)
                lbl_b.setFixedWidth(72)
                lbl_b.setAlignment(Qt.AlignCenter)
                lbl_b.setStyleSheet(
                    f"background:{SILVER_100}; color:{SLATE_300};"
                    f" border:1px solid {SILVER_300}; border-radius:4px;"
                    f" font-size:9px; padding:1px 0;"
                )
                row_hl.addWidget(lbl_b)

                # % editable
                if has_pct:
                    inp_pct = _StyledLineEdit(f"{rub['pct'] or 0:.2f}")
                    inp_pct.setFixedWidth(46)
                    inp_pct.setAlignment(Qt.AlignRight)
                    inp_pct.setToolTip(tr("Porcentaje"))
                    inp_pct.setStyleSheet(
                        f"border:none; border-bottom:1px solid {SILVER_300};"
                        f" border-radius:0; padding:1px 2px; font-size:11px;"
                        f" color:{SLATE_500}; background:transparent;"
                    )
                    def _sel_pct(ev, idx=i, base=inp_pct):
                        list_w.setCurrentRow(idx)
                        QLineEdit.focusInEvent(base, ev)
                    inp_pct.focusInEvent = _sel_pct
                    def _pct_done(idx=i, w=inp_pct):
                        try:
                            val = float(w.text().replace(',', '.'))
                        except ValueError:
                            return
                        _save_field(idx, 'pct', val)
                        self._render_pie()
                    inp_pct.editingFinished.connect(_pct_done)
                    row_hl.addWidget(inp_pct)
                    lbl_p = QLabel("%")
                    lbl_p.setStyleSheet(f"color:{SLATE_100}; font-size:10px; border:none;")
                    row_hl.addWidget(lbl_p)
                else:
                    sp = QWidget(); sp.setFixedWidth(58)
                    row_hl.addWidget(sp)

                # Botón eliminar
                def _del_row(idx=i):
                    self._pl_data.pop(idx); _save_all()

                btn_x = QPushButton("✕")
                btn_x.setFixedSize(20, 20)
                btn_x.setCursor(Qt.PointingHandCursor)
                btn_x.setStyleSheet(
                    f"QPushButton {{ color:{SLATE_300}; border:none; background:transparent;"
                    f" font-size:15px; font-weight:400;"
                    f" padding:0px; min-height:0px; min-width:0px; }}"
                    f"QPushButton:hover {{ color:{RED_500}; background:transparent; border:none;"
                    f" padding:0px; min-height:0px; min-width:0px; }}"
                )
                btn_x.clicked.connect(lambda: _del_row())
                row_hl.addWidget(btn_x)

                # Crear item y asignar widget
                item = QListWidgetItem()
                item.setData(Qt.UserRole, dict(rub))
                item.setFlags(
                    Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled
                )
                item.setSizeHint(QSize(0, 36))
                list_w.addItem(item)
                list_w.setItemWidget(item, row_f)

        rebuild()

        # Altura fija del QListWidget — sin scroll interno
        list_w.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        list_w.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        _ITEM_H  = 37
        _LIST_H  = max(_ITEM_H, list_w.count() * _ITEM_H)
        _HDR_H   = 32
        _FOOT_H  = 68
        list_w.setFixedHeight(_LIST_H)

        vl.addWidget(list_w)

        # Footer: agregar líneas — altura fija para evitar expansión
        footer = QFrame()
        footer.setFixedHeight(_FOOT_H)
        footer.setStyleSheet(
            f"QFrame {{ background:{SILVER_100}; border:none;"
            f" border-top:1px solid {SILVER_300}; }}"
        )
        f_vl = QVBoxLayout(footer)
        f_vl.setContentsMargins(10, 6, 10, 8)
        f_vl.setSpacing(4)
        lbl_add = QLabel("Agregar línea:")
        lbl_add.setStyleSheet(f"color:{SLATE_300}; font-size:10px; border:none;")
        f_vl.addWidget(lbl_add)

        add_hl = QHBoxLayout()
        add_hl.setSpacing(4)
        add_hl.setContentsMargins(0, 0, 0, 0)

        def _agregar(tipo):
            mp = 0 if tipo == 'rubro' else 1
            self._pl_data.append({
                'id': 0, 'codigo': f'CUSTOM_{len(self._pl_data)}',
                'nombre': 'Nueva línea', 'pct': 0.0, 'activo': 1,
                'orden': len(self._pl_data), 'tipo': tipo, 'mostrar_pct': mp,
            })
            _save_all()

        for lbl_t, tipo in [
            ("Con detalle", "rubro"),
            ("% CD",        "pct_cd"),
            ("% Sub Tot.",  "pct_sub"),
            ("Separador",   "subtotal"),
        ]:
            b = QPushButton(lbl_t)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(
                f"QPushButton {{ border:1px solid {SILVER_300}; border-radius:4px;"
                f" font-size:10px; padding:3px 8px; background:white; color:{SLATE_500}; }}"
                f"QPushButton:hover {{ background:{SILVER_300}; }}"
            )
            b.clicked.connect(lambda _, t=tipo: _agregar(t))
            add_hl.addWidget(b)
        add_hl.addStretch()
        f_vl.addLayout(add_hl)
        vl.addWidget(footer)
        # Fijar altura total de la card para evitar expansión en el scroll
        card.setFixedHeight(_HDR_H + _LIST_H + _FOOT_H + 2)
        return card

    # ── Tab Resumen ───────────────────────────────────────────────────────────

    def _make_tab_memoria(self) -> QWidget:
        """Pestaña «Memoria» — documento de memoria descriptiva del proyecto
        (nivel proyecto): editable a mano y generable con IA."""
        from utils.i18n import tr as _tr_m
        w = QWidget()
        w.setStyleSheet("background:white;")
        vl = QVBoxLayout(w)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)

        hdr = QFrame()
        hdr.setFixedHeight(36)
        hdr.setStyleSheet(f"background:{SILVER_100}; border-bottom:1px solid {SILVER_300};")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(10, 0, 8, 0)
        hl.setSpacing(6)

        lbl = QLabel(_tr_m("Memoria descriptiva del proyecto"))
        lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        lbl.setStyleSheet(f"color:{SLATE_700}; font-size:11px; font-weight:700; border:none;")
        hl.addWidget(lbl, stretch=1)

        self.lbl_memoria_estado = QLabel("")
        self.lbl_memoria_estado.setStyleSheet("font-size:10px; color:#95A3AB; border:none;")
        hl.addWidget(self.lbl_memoria_estado)

        btn_ia = QPushButton("✨  IA")
        btn_ia.setFixedHeight(24)
        btn_ia.setToolTip(_tr_m("Generar la memoria descriptiva con IA "
                                "(usa ubicación, presupuesto, plazo, modalidad y notas)"))
        btn_ia.setStyleSheet(
            "QPushButton { background:#9B59B6; color:white; border:none; border-radius:4px;"
            " padding:0 10px; font-size:10px; font-weight:600; }"
            "QPushButton:hover { background:#8E44AD; }"
        )
        btn_ia.clicked.connect(self._ia_generar_memoria)
        hl.addWidget(btn_ia)

        btn_save = QPushButton(_tr_m("Guardar"))
        btn_save.setFixedHeight(24)
        btn_save.setStyleSheet(
            f"QPushButton {{ background:{GREEN_500}; color:white; border:none; border-radius:4px;"
            f" padding:0 12px; font-size:10px; font-weight:600; }}"
            f"QPushButton:hover {{ background:#5a9e1e; }}"
        )
        btn_save.clicked.connect(self._guardar_memoria)
        hl.addWidget(btn_save)
        vl.addWidget(hdr)

        # ── Toolbar de formato (igual que Especificaciones) ──────────
        toolbar = QFrame()
        toolbar.setFixedHeight(30)
        toolbar.setStyleSheet(f"background:#F5F5F5; border-bottom:1px solid {SILVER_300};")
        htb = QHBoxLayout(toolbar)
        htb.setContentsMargins(8, 0, 8, 0)
        htb.setSpacing(2)
        _BTN_FMT_M = (
            "QPushButton { background:transparent; border:none; border-radius:4px;"
            " padding:0 5px; font-size:12px; min-width:24px; min-height:22px; }"
            "QPushButton:hover { background:#E0E0E0; }"
            "QPushButton:checked { background:#D4C9F0; color:#6C3483; }"
        )

        def _mfmt(texto, tooltip, cb, checkable=False, extra=""):
            b = QPushButton(texto)
            b.setFixedHeight(22)
            b.setToolTip(tooltip)
            b.setCheckable(checkable)
            b.setStyleSheet(_BTN_FMT_M + extra)
            b.clicked.connect(cb)
            return b

        def _msep():
            s = QFrame(); s.setFrameShape(QFrame.VLine); s.setFixedWidth(1)
            s.setStyleSheet(f"color:{SILVER_300};")
            return s

        self.btn_mem_bold = _mfmt("B", "Negrita (Ctrl+B)", self._mem_bold, True,
                                  "QPushButton { font-weight:900; }")
        self.btn_mem_italic = _mfmt("I", "Cursiva (Ctrl+I)", self._mem_italic, True,
                                    "QPushButton { font-style:italic; }")
        self.btn_mem_underline = _mfmt("U", "Subrayado (Ctrl+U)", self._mem_underline, True,
                                       "QPushButton { text-decoration:underline; }")
        htb.addWidget(self.btn_mem_bold)
        htb.addWidget(self.btn_mem_italic)
        htb.addWidget(self.btn_mem_underline)
        htb.addWidget(_msep())
        for icono, tip, alin in [("≡←", "Alinear izquierda", Qt.AlignLeft),
                                 ("≡≡", "Centrar", Qt.AlignHCenter),
                                 ("≡→", "Alinear derecha", Qt.AlignRight),
                                 ("≣", "Justificar", Qt.AlignJustify)]:
            htb.addWidget(_mfmt(icono, tip, lambda _c, a=alin: self._mem_align(a)))
        htb.addWidget(_msep())
        htb.addWidget(_mfmt("•  Lista", "Viñetas", self._mem_bullet_list))
        htb.addWidget(_mfmt("1. Lista", "Lista numerada", self._mem_numbered_list))
        htb.addWidget(_msep())
        htb.addWidget(_mfmt("🖼  Imagen", "Insertar imagen (se incrusta en el documento)",
                            self._mem_insertar_imagen))
        htb.addStretch()
        vl.addWidget(toolbar)

        # Barra de «Ampliar sección»: elige una sección y la IA la extiende.
        secbar = QFrame()
        secbar.setFixedHeight(32)
        secbar.setStyleSheet(f"background:#F5F5F5; border-bottom:1px solid {SILVER_300};")
        sh = QHBoxLayout(secbar)
        sh.setContentsMargins(10, 0, 8, 0)
        sh.setSpacing(6)
        lbl_sec = QLabel(_tr_m("Ampliar sección:"))
        lbl_sec.setStyleSheet("font-size:10px; color:#485A6C; border:none;")
        sh.addWidget(lbl_sec)
        self.cmb_memoria_seccion = QComboBox()
        self.cmb_memoria_seccion.setFixedHeight(24)
        for i, nom in enumerate(_SECCIONES_MEMORIA, 1):
            self.cmb_memoria_seccion.addItem(f"{i}. {nom.title()}", i)
        self.cmb_memoria_seccion.setStyleSheet(
            "QComboBox { background:white; border:1px solid #CBD5E1; border-radius:4px;"
            " padding:1px 8px; font-size:10px; min-height:0; }"
        )
        sh.addWidget(self.cmb_memoria_seccion, stretch=1)
        btn_amp = QPushButton("✨  " + _tr_m("Ampliar"))
        btn_amp.setFixedHeight(24)
        btn_amp.setToolTip(_tr_m("La IA reescribe esa sección más extensa y detallada"))
        btn_amp.setStyleSheet(
            "QPushButton { background:#E8E4F0; color:#6C3483; border:none; border-radius:4px;"
            " padding:0 12px; font-size:10px; font-weight:600; }"
            "QPushButton:hover { background:#D2C9E8; }"
        )
        btn_amp.clicked.connect(self._ampliar_seccion_memoria)
        sh.addWidget(btn_amp)
        vl.addWidget(secbar)

        self.txt_memoria = QTextEdit()
        self.txt_memoria.setPlaceholderText(_tr_m(
            "Escribe aquí la memoria descriptiva, o pulsa «✨ IA» para "
            "generarla a partir de los datos del proyecto."))
        self.txt_memoria.setStyleSheet(
            "QTextEdit { border:none; font-size:12px; padding:12px;"
            " line-height:1.4; }"
        )
        self._memoria_set_texto(self._proy.get('memoria_descriptiva') or '')
        self.txt_memoria.textChanged.connect(self._on_memoria_editada)
        self.txt_memoria.cursorPositionChanged.connect(self._mem_actualizar_toolbar)
        vl.addWidget(self.txt_memoria, stretch=1)
        return w

    # ── Formato de la memoria (espejo de Especificaciones) ──────────
    def _mem_bold(self):
        from PySide6.QtGui import QTextCharFormat, QFont
        fmt = QTextCharFormat()
        peso = QFont.Normal if self.txt_memoria.fontWeight() >= QFont.Bold else QFont.Bold
        fmt.setFontWeight(peso)
        self.txt_memoria.mergeCurrentCharFormat(fmt)

    def _mem_italic(self):
        from PySide6.QtGui import QTextCharFormat
        fmt = QTextCharFormat()
        fmt.setFontItalic(not self.txt_memoria.fontItalic())
        self.txt_memoria.mergeCurrentCharFormat(fmt)

    def _mem_underline(self):
        from PySide6.QtGui import QTextCharFormat
        fmt = QTextCharFormat()
        fmt.setFontUnderline(not self.txt_memoria.fontUnderline())
        self.txt_memoria.mergeCurrentCharFormat(fmt)

    def _mem_align(self, alineacion):
        self.txt_memoria.setAlignment(alineacion)

    def _mem_bullet_list(self):
        from PySide6.QtGui import QTextListFormat
        fmt = QTextListFormat()
        fmt.setStyle(QTextListFormat.ListDisc)
        self.txt_memoria.textCursor().createList(fmt)

    def _mem_numbered_list(self):
        from PySide6.QtGui import QTextListFormat
        fmt = QTextListFormat()
        fmt.setStyle(QTextListFormat.ListDecimal)
        self.txt_memoria.textCursor().createList(fmt)

    def _mem_actualizar_toolbar(self):
        from PySide6.QtGui import QFont
        fmt = self.txt_memoria.currentCharFormat()
        self.btn_mem_bold.setChecked(fmt.fontWeight() >= QFont.Bold)
        self.btn_mem_italic.setChecked(fmt.fontItalic())
        self.btn_mem_underline.setChecked(fmt.fontUnderline())

    def _mem_insertar_imagen(self):
        """Inserta una imagen incrustada (base64) en la memoria, para que
        viaje dentro del documento/`.db` sin archivos externos."""
        if not self._require_editable('editar la memoria descriptiva', 'specs'):
            return
        path, _ = _QFileDialog.getOpenFileName(
            self, "Seleccionar imagen", "",
            "Imágenes (*.png *.jpg *.jpeg *.bmp *.gif)")
        if not path:
            return
        img = QImage(path)
        if img.isNull():
            return
        if img.width() > 560:
            img = img.scaledToWidth(560, Qt.SmoothTransformation)
        import base64
        from PySide6.QtCore import QBuffer, QByteArray, QIODeviceBase
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODeviceBase.WriteOnly)
        img.save(buf, "PNG")
        buf.close()
        b64 = base64.b64encode(bytes(ba)).decode('ascii')
        self.txt_memoria.textCursor().insertHtml(
            f'<img src="data:image/png;base64,{b64}" width="{img.width()}" />')

    def _memoria_set_texto(self, valor: str):
        """Carga el contenido en el editor. Si ya es HTML (guardado con
        formato), lo respeta; si es texto plano (de la IA), lo convierte
        poniendo los encabezados de sección en negrita."""
        self.txt_memoria.blockSignals(True)
        v = valor or ''
        if not v.strip():
            self.txt_memoria.clear()
        elif '</' in v or '<p' in v or '<body' in v.lower():
            self.txt_memoria.setHtml(v)
        else:
            self.txt_memoria.setHtml(self._plain_to_html_spec(v))
        self.txt_memoria.blockSignals(False)

    def _on_memoria_editada(self):
        if getattr(self, 'lbl_memoria_estado', None):
            self.lbl_memoria_estado.setText("● Sin guardar")
            self.lbl_memoria_estado.setStyleSheet("font-size:10px; color:#C0621A; border:none;")

    def _guardar_memoria(self):
        if not self._require_editable('editar la memoria descriptiva', 'specs'):
            return
        # Guardar como HTML para conservar el formato (negrita/cursiva/listas).
        valor = self.txt_memoria.toHtml() if self.txt_memoria.toPlainText().strip() else ''
        conn = get_db()
        conn.execute("UPDATE proyectos SET memoria_descriptiva=? WHERE id=?",
                     (valor, self.pid))
        conn.commit()
        conn.close()
        self._proy['memoria_descriptiva'] = valor
        if getattr(self, 'lbl_memoria_estado', None):
            self.lbl_memoria_estado.setText("✓ Guardado")
            self.lbl_memoria_estado.setStyleSheet("font-size:10px; color:#68B723; border:none;")

    def _ia_generar_memoria(self):
        if not self._require_editable('generar la memoria descriptiva', 'specs'):
            return
        dlg = _DialogIAMemoria(self, self.pid, self._proy.get('nombre', ''),
                               notas=self._proy.get('notas', '') or '')
        if dlg.exec() == QDialog.Accepted:
            texto = dlg.resultado()
            if texto:
                # Renderizar (negritas en títulos) y persistir como HTML.
                self._memoria_set_texto(texto)
                html = self.txt_memoria.toHtml()
                conn = get_db()
                conn.execute("UPDATE proyectos SET memoria_descriptiva=? WHERE id=?",
                             (html, self.pid))
                conn.commit()
                conn.close()
                self._proy['memoria_descriptiva'] = html
                if getattr(self, 'lbl_memoria_estado', None):
                    self.lbl_memoria_estado.setText("✓ Generado")
                    self.lbl_memoria_estado.setStyleSheet(
                        "font-size:10px; color:#68B723; border:none;")

    def _extraer_seccion_memoria(self, texto: str, numero: int):
        """Devuelve (contenido, ini_linea, fin_linea, lineas) de la sección
        `numero` del documento (encabezado «N. …» hasta el siguiente «N+1. …»),
        o None si no se encuentra."""
        import re as _re
        lineas = texto.split('\n')
        pat_ini = _re.compile(rf'^\s*{numero}\.\s')
        pat_fin = _re.compile(rf'^\s*{numero + 1}\.\s')
        ini = next((i for i, l in enumerate(lineas) if pat_ini.match(l)), None)
        if ini is None:
            return None
        fin = next((i for i in range(ini + 1, len(lineas)) if pat_fin.match(lineas[i])),
                   len(lineas))
        contenido = '\n'.join(lineas[ini:fin]).strip()
        return contenido, ini, fin, lineas

    def _ampliar_seccion_memoria(self):
        if not self._require_editable('ampliar la memoria descriptiva', 'specs'):
            return
        texto = self.txt_memoria.toPlainText()
        if not texto.strip():
            QMessageBox.information(self, "Ampliar sección",
                "Primero genera o escribe la memoria descriptiva.")
            return
        numero = self.cmb_memoria_seccion.currentData()
        nombre = _SECCIONES_MEMORIA[numero - 1]
        bloque = self._extraer_seccion_memoria(texto, numero)
        if bloque is None:
            QMessageBox.information(self, "Ampliar sección",
                f"No se encontró la sección «{numero}. {nombre.title()}» en la "
                "memoria.\nGenérala con IA primero o revisa que el encabezado "
                f"empiece con «{numero}.».")
            return
        contenido, ini, fin, lineas = bloque
        dlg = _DialogAmpliarSeccion(self, self.pid, numero, nombre, contenido)
        if dlg.exec() != QDialog.Accepted:
            return
        nuevo = (dlg.resultado() or '').strip()
        if not nuevo:
            return
        nuevas = lineas[:ini] + [nuevo, ''] + lineas[fin:]
        nuevo_texto = '\n'.join(nuevas).strip()
        self._memoria_set_texto(nuevo_texto)
        html = self.txt_memoria.toHtml()
        conn = get_db()
        conn.execute("UPDATE proyectos SET memoria_descriptiva=? WHERE id=?",
                     (html, self.pid))
        conn.commit()
        conn.close()
        self._proy['memoria_descriptiva'] = html
        if getattr(self, 'lbl_memoria_estado', None):
            self.lbl_memoria_estado.setText("✓ Sección ampliada")
            self.lbl_memoria_estado.setStyleSheet(
                "font-size:10px; color:#68B723; border:none;")

    def _make_tab_resumen(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background:white;")
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("background:white;")

        self._resumen_widget = QWidget()
        self._resumen_widget.setStyleSheet("background:white;")
        self._resumen_layout = QVBoxLayout(self._resumen_widget)
        self._resumen_layout.setContentsMargins(16, 16, 16, 16)
        self._resumen_layout.setSpacing(12)
        self._resumen_layout.addStretch()

        scroll.setWidget(self._resumen_widget)

        vl = QVBoxLayout(w)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.addWidget(scroll)
        return w

    # ══════════════════════════════════════════════════════════════════════════
    # Carga de datos en los paneles
    # ══════════════════════════════════════════════════════════════════════════

    def _build_empty_state(self):
        """Banner compacto de estado vacío: invita a sugerir partidas con IA o
        plantilla. Independiente de Tuxia y NO oculta el árbol (el clic derecho
        para «Agregar título/partida» sigue disponible)."""
        from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton
        fr = QFrame()
        fr.setObjectName("emptyState")
        fr.setStyleSheet(
            "QFrame#emptyState { background:#FEF5EB; border:1px solid #F6C99A;"
            "  border-radius:8px; }"
            "QLabel { background:transparent; border:none; color:#8A5A2B;"
            "  font-size:11px; }")
        lay = QHBoxLayout(fr)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(10)
        lbl = QLabel("Este proyecto aún no tiene partidas. ¿Quieres que la IA o "
                     "una plantilla te sugieran la estructura? (también puedes "
                     "agregarlas a mano con clic derecho en la lista).")
        lbl.setWordWrap(True)
        btn = QPushButton("✨  Sugerir partidas")
        btn.setObjectName("emptyStateBtn")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(
            "QPushButton#emptyStateBtn { background:#F37329; color:white;"
            "  border:none; border-radius:6px; padding:6px 16px; font-size:11px;"
            "  font-weight:600; }"
            "QPushButton#emptyStateBtn:hover { background:#E0631F; }")
        btn.clicked.connect(self._abrir_sugerir_partidas)
        lay.addWidget(lbl, 1)
        lay.addWidget(btn, 0)
        return fr

    def _toggle_empty_state(self):
        """Muestra el banner de estado vacío SOLO si el proyecto no tiene
        partidas y es editable. NO oculta el árbol."""
        try:
            conn = get_db()
            n = conn.execute(
                "SELECT COUNT(*) FROM partidas WHERE proyecto_id=?",
                (self.pid,)).fetchone()[0]
            conn.close()
        except Exception:
            n = 1
        vacio = (n == 0) and getattr(self, '_ed_presupuesto', True)
        if hasattr(self, '_empty_state'):
            self._empty_state.setVisible(vacio)

    def recargar_partidas(self):
        from utils.i18n import tr
        # El árbol se reconstruye → los items resaltados quedan obsoletos.
        self._ins_resaltados = []
        self.tree._proyecto_id = self.pid
        self.tree._sub_ppto_id = self._sub_ppto_id
        conn = get_db()
        if self._sub_ppto_id is None:
            rows = conn.execute(
                "SELECT * FROM partidas WHERE proyecto_id=? AND sub_presupuesto_id IS NULL ORDER BY item",
                (self.pid,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM partidas WHERE proyecto_id=? AND sub_presupuesto_id=? ORDER BY item",
                (self.pid, self._sub_ppto_id)
            ).fetchall()
        # IDs de partidas con planilla de metrados
        con_planilla = {r[0] for r in conn.execute(
            "SELECT DISTINCT partida_id FROM metrados_detalle md "
            "JOIN partidas p ON p.id=md.partida_id WHERE p.proyecto_id=?",
            (self.pid,)
        ).fetchall()}
        conn.close()

        self.tree.blockSignals(True)
        self.tree.clear()
        self._id_to_item: dict[int, QTreeWidgetItem] = {}
        self._con_planilla = con_planilla

        n_partidas = 0
        # Índice ítem→nodo para localizar padres en O(1). El bucle anterior
        # recorría TODOS los items insertados comparando .text(0) por cada
        # fila (O(n²)): con 900 partidas eran ~400k comparaciones y ~0.7 s.
        _nodo_por_item: dict[str, QTreeWidgetItem] = {}
        for row in rows:
            niv   = int(row['nivel'] or 1)
            es_tt = bool(row['es_titulo'])
            item_num = row['item'] or ""

            # Buscar padre por prefijo de ítem
            parent = self.tree.invisibleRootItem()
            if '.' in item_num:
                prefijo = '.'.join(item_num.split('.')[:-1])
                parent = _nodo_por_item.get(prefijo, parent)

            tw = QTreeWidgetItem(parent)
            _nodo_por_item.setdefault(item_num, tw)
            tw.setText(0, item_num)
            tw.setText(1, row['descripcion'] or "")
            tw.setData(0, Qt.UserRole, row['id'])
            tw.setData(0, Qt.UserRole + 1, es_tt)

            if es_tt:
                # Color de texto por nivel (rojo, arándano, morado, rosa) +
                # negrita. El fondo distingue solo los TÍTULOS (nivel 1) con una
                # banda neutra; los SUBTÍTULOS (nivel ≥2) no se tintan: siguen la
                # zebra como una partida más y se distinguen solo por el texto.
                txt_col, _bg_tinte_ignored, pt = NIVEL_ESTILO.get(niv, ("#273445", "#F8F9FA", 10))
                fg = QBrush(QColor(txt_col))
                font = QFont()
                font.setBold(True)
                font.setPointSize(pt)
                font.setLetterSpacing(QFont.AbsoluteSpacing, 0.3)
                if niv == 1:
                    font.setUnderline(True)
                    title_bg = QBrush(QColor("#E2E8F0"))
                else:
                    # Subtítulo: parte de la zebra (cuenta como fila de detalle).
                    # Se rellena SIEMPRE (blanco o tinte) — None dejaría la zona
                    # del indicador de rama sin pintar y se vería un cuadro negro.
                    n_partidas += 1
                    title_bg = QBrush(QColor(
                        "#F6F8FB" if (n_partidas % 2 == 0) else "#FFFFFF"))
                for c in range(6):
                    tw.setForeground(c, fg)
                    tw.setBackground(c, title_bg)
                    tw.setFont(c, font)
            else:
                n_partidas += 1
                fg_part = QBrush(QColor(SLATE_700))
                # Zebra manual: cada 2ª partida (n_partidas par) en alt-bg.
                # Cuenta solo partidas, ignora títulos → patrón estable
                # incluso con muchos títulos intercalados.
                # Zebra MUY sutil: apenas un tinte sobre blanco para que las
                # bandas se perciban sin gritar — mismo criterio que la zebra
                # de cronograma valorizado/insumos (ver _BgFillDelegate).
                alt_bg = QBrush(QColor("#F6F8FB")) if (n_partidas % 2 == 0) else None
                for c in range(6):
                    tw.setForeground(c, fg_part)
                    if alt_bg is not None:
                        tw.setBackground(c, alt_bg)
                tw.setText(2, row['unidad'] or "")
                met = row['metrado'] or 0
                pu  = row['precio_unitario'] or 0
                tiene_planilla = row['id'] in con_planilla
                tiene_specs    = bool((row['especificaciones'] or '').strip())
                tw.setData(1, Qt.UserRole, tiene_specs)      # ✓ en Descripción = specs
                dec = get_decimales_ppto()
                tw.setText(3, f"{met:,.{get_decimales_metrado()}f}")
                tw.setData(3, Qt.UserRole, tiene_planilla)   # ✓ en Metrado = planilla
                tw.setText(4, f"{pu:,.{dec}f}")
                parcial = parcial_wysiwyg(met, pu, dec)
                tw.setText(5, fmt_num(parcial, self._moneda, dec))
                tw.setData(5, Qt.UserRole, float(parcial))  # valor numérico para totales de títulos
                for c in (3, 4, 5):
                    tw.setTextAlignment(c, Qt.AlignRight | Qt.AlignVCenter)
                if tiene_planilla:
                    tw.setToolTip(3, tr("Metrado calculado desde la planilla"))
                # Editable vía clic en col 3 — solo si el presupuesto lo permite
                if getattr(self, '_ed_presupuesto', True):
                    tw.setFlags(tw.flags() | Qt.ItemIsEditable)
                else:
                    tw.setFlags(tw.flags() & ~Qt.ItemIsEditable)

            self.tree.expandItem(tw)
            self._id_to_item[row['id']] = tw

        self.tree.blockSignals(False)
        self._calcular_totales_titulos(self.tree.invisibleRootItem())
        self.tree.resizeColumnToContents(0)   # ajustar col Ítem al contenido
        self.actualizar_total()
        # Reaplicar bloqueos tras recargar (flags pueden haberse perdido)
        if not getattr(self, '_ed_presupuesto', True):
            self._strip_tree_editable_flags()
        # Estado vacío (sin partidas) ↔ árbol: independiente de Tuxia.
        self._toggle_empty_state()

    def _calcular_totales_titulos(self, parent_item) -> float:
        """Recorre el árbol recursivamente y pone el total en col 5 de cada título."""
        subtotal = 0.0
        for i in range(parent_item.childCount()):
            child = parent_item.child(i)
            es_titulo = bool(child.data(0, Qt.UserRole + 1))
            if es_titulo:
                total_hijo = self._calcular_totales_titulos(child)
                child.setText(5, fmt_num(_r2(total_hijo), self._moneda))
                child.setTextAlignment(5, Qt.AlignRight | Qt.AlignVCenter)
                subtotal += total_hijo
            else:
                # Partida hoja: leer el valor numérico guardado en UserRole de col 5
                val = child.data(5, Qt.UserRole)
                if val is not None:
                    subtotal += float(val)
        return subtotal

    def actualizar_total(self):
        cd = self._total_proyecto()
        # CD en el panel ACU (etiqueta "CD:")
        if hasattr(self, 'lbl_cd'):
            self.lbl_cd.setText(fmt(cd, self._moneda))
        # Presupuesto Total en el topbar (CD + GG + Utilidad + IGV...)
        try:
            _, totales = calcular_totales(self.pid)
            total = totales.get('total', cd)
        except Exception:
            total = cd
        self.lbl_total.setText(fmt(total, self._moneda))

    def cargar_acu(self, part_id: int):
        from utils.i18n import tr
        self._partida_actual_id = part_id
        conn = get_db()
        partida = conn.execute("SELECT * FROM partidas WHERE id=?", (part_id,)).fetchone()
        conn.close()
        if not partida:
            return

        titulo = f"{partida['item']}  {partida['descripcion']}"
        self.lbl_acu_titulo.setText(titulo)
        self.lbl_spec_titulo.setText(titulo)
        self.lbl_met_titulo.setText(titulo)

        self._acu_partida_global = _partida_global(partida['unidad'])

        rend = partida['rendimiento'] or 1.0
        self.inp_rend.setText(f"{rend:.4f}".rstrip('0').rstrip('.') or "0")

        # Unidad del rendimiento = unidad de la partida por día (ej. m²/día)
        und_part = (partida['unidad'] or '').strip()
        self.lbl_rend_unidad.setText(f"{und_part}/día" if und_part else "")

        jornada = self._proy.get('jornada_laboral') or 8
        self.lbl_jornada.setText(f"Jornada: {jornada} h/día")

        self.txt_spec.blockSignals(True)
        contenido = partida['especificaciones'] or ""
        if contenido.strip().startswith('<'):
            self.txt_spec.setHtml(contenido)
        elif contenido.strip():
            self.txt_spec.setHtml(self._plain_to_html_spec(contenido))
        else:
            self.txt_spec.clear()
        self.txt_spec.blockSignals(False)
        self._spec_modificada = False
        self.lbl_spec_estado.setText("")
        self._chat_acu.set_partida(part_id)

        conn = get_db()
        items, totales_tipo = get_acu_items(conn, part_id)
        conn.close()

        self._acu_loading = True
        self.tbl_acu.setRowCount(0)
        self._acu_row_ids: list[int] = []

        current_tipo = None
        for it in items:
            tipo = it['tipo'] or 'MAT'

            # Fila-cabecera de sección cuando cambia el tipo
            if tipo != current_tipo:
                current_tipo = tipo
                sec_bg, sec_fg, sec_label = ACU_SECTION.get(
                    tipo, ('#f5f5f5', '#333333', tipo)
                )
                r = self.tbl_acu.rowCount()
                self.tbl_acu.insertRow(r)
                self.tbl_acu.setRowHeight(r, 24)
                self._acu_row_ids.append(-1)
                hdr = QTableWidgetItem(sec_label)
                hdr.setBackground(QColor(sec_bg))
                hdr.setForeground(QColor(sec_fg))
                hdr.setFont(QFont("", 9, QFont.Bold))
                hdr.setFlags(Qt.ItemIsEnabled)
                self.tbl_acu.setItem(r, 0, hdr)
                self.tbl_acu.setSpan(r, 0, 1, len(COLS_ACU))

            r = self.tbl_acu.rowCount()
            self.tbl_acu.insertRow(r)
            self.tbl_acu.setRowHeight(r, 24)
            self._acu_row_ids.append(it['id'])

            bg     = ACU_COLOR.get(tipo, QColor("#FFFFFF"))
            precio = it['precio'] or 0
            cant   = it['cantidad'] or 0
            cuad   = it['cuadrilla'] or 0

            # Col 0: badge de tipo
            badge = QTableWidgetItem(tipo)
            b_bg, b_fg = ACU_BADGE.get(tipo, (SLATE_300, "#FFFFFF"))
            badge.setBackground(QColor(b_bg))
            badge.setForeground(QColor(b_fg))
            badge.setTextAlignment(Qt.AlignCenter)
            badge.setFont(QFont("", 8, QFont.Bold))
            badge.setFlags(badge.flags() & ~Qt.ItemIsEditable)
            self.tbl_acu.setItem(r, 0, badge)

            vals = [
                it['descripcion'] or '',
                it['unidad'] or '',
                f"{cuad:.3f}",
                f"{cant:.{get_decimales_cant_acu()}f}",
                f"{precio:.4f}",
                fmt(it['parcial'] or 0, self._moneda),
            ]
            for c, v in enumerate(vals, start=1):
                cell = QTableWidgetItem(str(v))
                if c in (3, 4, 5):
                    # El delegate pinta estos; setBackground como fallback neutro
                    cell.setBackground(_NEUTRAL_BG)
                    cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    cell.setToolTip(tr("Doble clic para editar"))
                else:
                    # Cols no editables: neutro siempre
                    cell.setBackground(_NEUTRAL_BG)
                    cell.setFlags(cell.flags() & ~Qt.ItemIsEditable)
                if c == 6:
                    cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    cell.setFlags(cell.flags() & ~Qt.ItemIsEditable)
                self.tbl_acu.setItem(r, c, cell)

        self._acu_loading = False

        # Actualizar subtotales y barras
        for tipo, lbl in self._sub_labels.items():
            lbl.setText(fmt(totales_tipo.get(tipo, 0), self._moneda))
        pu = partida['precio_unitario'] or 0
        self.lbl_pu.setText(fmt(pu, self._moneda))

        # Cargar metrados si el tab es visible
        if self.tabs.currentIndex() == 2:
            self.cargar_metrados(part_id)

        # Reaplicar bloqueo de flags si el estado lo requiere
        if not getattr(self, '_ed_presupuesto', True):
            self._strip_table_editable_flags(self.tbl_acu)

        # Tuxia: chequear si la partida tiene problemas (sin metrado/ACU)
        if hasattr(self, '_tuxia') and self._tuxia is not None:
            QTimer.singleShot(150, lambda pid=part_id: self._tuxia_check_partida(pid))

    def _partidas_bajo_titulo(self, tree_item) -> list[int]:
        """Recoge recursivamente IDs de partidas (no títulos) bajo un item del árbol."""
        ids = []
        for i in range(tree_item.childCount()):
            child = tree_item.child(i)
            pid   = child.data(0, Qt.UserRole)
            es_tt = child.data(0, Qt.UserRole + 1)
            if pid and not es_tt:
                ids.append(pid)
            elif pid and es_tt:
                ids.extend(self._partidas_bajo_titulo(child))
        return ids

    def cargar_insumos(self, estado: 'int | list[int] | None' = None):
        """
        estado=None       → insumos totales del proyecto
        estado=int        → insumos de una partida
        estado=list[int]  → insumos agrupados de un título/subtítulo
        """
        from utils.i18n import tr
        self._ins_estado = estado
        from utils.formatting import norm_busqueda
        buscar = norm_busqueda(self.inp_buscar_ins.text().strip()) if hasattr(self, 'inp_buscar_ins') else ""
        conn   = get_db()

        if isinstance(estado, list):
            # ── Grupo (título/subtítulo) ──────────────────────────────────────
            # Usar `get_insumos_para_partidas` (que incluye overhead `%MO`/`%MAT`
            # con parcial correctamente calculado via get_acu_items).
            rows  = get_insumos_para_partidas(conn, estado) if estado else []
            label = getattr(self, '_ins_titulo_label', 'INSUMOS — GRUPO')

        elif isinstance(estado, int):
            # ── Partida individual ────────────────────────────────────────────
            desc_row = conn.execute(
                "SELECT descripcion FROM partidas WHERE id=?", (estado,)
            ).fetchone()
            desc_p = (desc_row['descripcion'] or '') if desc_row else ''
            rows   = get_insumos_para_partidas(conn, [estado])
            label  = f"INSUMOS  ·  {desc_p[:50]}"

        else:
            # ── Proyecto total ────────────────────────────────────────────────
            rows  = get_insumos_proyecto(conn, self.pid)
            label = "INSUMOS TOTALES DEL PROYECTO"

        # Insumos con precio inconsistente (mismo recurso a distinto precio en
        # el proyecto). Se calcula project-wide sin importar la vista activa.
        try:
            self._ins_incon = precios_inconsistentes(conn, self.pid)
        except Exception:
            self._ins_incon = {}

        # Partidas cuyo PU guardado no coincide con la suma de su ACU
        try:
            self._pu_incon = partidas_pu_inconsistente(conn, self.pid)
        except Exception:
            self._pu_incon = []

        conn.close()

        if hasattr(self, 'lbl_ins_titulo'):
            self.lbl_ins_titulo.setText(label)

        tipo_color = {'MO': QColor("#FFF9C4"), 'MAT': QColor("#E8F5E9"),
                      'EQ': QColor("#ECEFF1"), 'SC': QColor("#F3EAFA")}
        dec = get_decimales_ppto()
        totales_tipo: dict[str, float] = {'MO': 0.0, 'MAT': 0.0, 'EQ': 0.0, 'SC': 0.0}

        self.tbl_ins.setRowCount(0)
        for row in rows:
            desc = row['descripcion'] or ''
            if buscar and buscar not in norm_busqueda(desc):
                continue
            ri = self.tbl_ins.rowCount()
            self.tbl_ins.insertRow(ri)
            self.tbl_ins.setRowHeight(ri, 22)

            parcial = _rn(float(row['parcial_total'] or 0), dec)
            cant    = float(row['cantidad_total'] or 0)
            precio  = float(row['precio'] or 0)
            tipo    = row['tipo'] or 'MAT'
            bg      = tipo_color.get(tipo, QColor("#FFFFFF"))
            totales_tipo[tipo] = totales_tipo.get(tipo, 0.0) + parcial

            rid_row = row.get('recurso_id')
            incon   = getattr(self, '_ins_incon', {}).get(rid_row)
            if incon:
                # Precio inconsistente: mostrar el sugerido (modal) y marcar.
                precio = float(incon['sugerido'] or 0)

            codigo  = (row.get('codigo') or '').strip()
            tip_ins = (f"{tr('Código')}: {codigo or '—'}   ·   "
                       f"{row['unidad'] or '—'}   ·   {fmt(precio, self._moneda)}")

            badge = QTableWidgetItem(tipo)
            badge.setBackground(QColor("#FFFFFF"))
            badge.setData(Qt.UserRole,     rid_row)                 # recurso_id
            badge.setData(Qt.UserRole + 1, desc)                   # descripción
            badge.setData(Qt.UserRole + 2, cant)                   # cantidad_total
            badge.setToolTip(tip_ins)
            self.tbl_ins.setItem(ri, 0, badge)

            tip_precio = tr("Clic para editar precio · Clic derecho → actualizar catálogo")
            if incon:
                variantes_txt = ", ".join(
                    f"{fmt(p, self._moneda)}×{n}" for p, n in incon['variantes']
                )
                tip_precio = (
                    f"⚠ {tr('Este insumo tiene varios precios en el proyecto')}:\n"
                    f"{variantes_txt}\n"
                    f"{tr('Sugerido (más usado)')}: {fmt(incon['sugerido'], self._moneda)}\n"
                    f"{tr('Clic derecho → Unificar precio')}"
                )

            vals = [desc, row['unidad'] or '', f"{cant:.2f}",
                    fmt(precio, self._moneda), fmt(parcial, self._moneda)]
            for c, v in enumerate(vals, start=1):
                it = QTableWidgetItem(str(v))
                it.setBackground(bg)
                if c in (3, 4, 5):
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if c == 4:
                    it.setToolTip(tip_precio)
                    if incon:
                        it.setBackground(QColor("#FDECEA"))
                        it.setForeground(QColor("#B23B2E"))
                        f = it.font(); f.setBold(True); it.setFont(f)
                else:
                    it.setToolTip(tip_ins)
                self.tbl_ins.setItem(ri, c, it)

        es_total = estado is None

        if hasattr(self, 'btn_ins_ver_todos'):
            self.btn_ins_ver_todos.setVisible(not es_total)

        if hasattr(self, 'btn_ins_unificar'):
            n_incon = len(getattr(self, '_ins_incon', {}))
            self.btn_ins_unificar.setVisible(n_incon > 0 and self._ed_presupuesto)
            if n_incon > 0:
                self.btn_ins_unificar.setText(f"⚠ Unificar precios ({n_incon})")

        if hasattr(self, 'btn_ins_pu_acu'):
            n_pu = len(getattr(self, '_pu_incon', []))
            self.btn_ins_pu_acu.setVisible(n_pu > 0 and self._ed_presupuesto)
            if n_pu > 0:
                self.btn_ins_pu_acu.setText(f"⚠ PU ≠ ACU ({n_pu})")

        if hasattr(self, '_ins_tipo_labels'):
            for tipo, lv in self._ins_tipo_labels.items():
                lv.setText(fmt(totales_tipo.get(tipo, 0), self._moneda))
            for w in self._ins_tipo_widgets:
                w.setVisible(True)

        # Ajustar ancho de Precio U. y Parcial al contenido
        self.tbl_ins.resizeColumnToContents(4)
        self.tbl_ins.resizeColumnToContents(5)

        # Reaplicar bloqueo de flags si el estado lo requiere
        if not getattr(self, '_ed_presupuesto', True):
            self._strip_table_editable_flags(self.tbl_ins)

    def _ins_doble_clic_recurso(self, ri: int, col: int):
        if not self._ed_presupuesto:
            return
        """Doble clic en cualquier col excepto Precio → editar recurso."""
        if col == 4:
            return   # Precio U. usa el editor inline de un clic
        badge = self.tbl_ins.item(ri, 0)
        if not badge or not badge.data(Qt.UserRole):
            return
        recurso_id = badge.data(Qt.UserRole)
        conn = get_db()
        row = conn.execute("SELECT * FROM recursos WHERE id=?", (recurso_id,)).fetchone()
        conn.close()
        if not row:
            return
        dlg = _EditarRecursoDialog(dict(row), self)
        if dlg.exec() != QDialog.Accepted:
            return
        datos = dlg.datos()
        conn = get_db()
        conn.execute(
            "UPDATE recursos SET descripcion=?, unidad=?, tipo=?, indice_inei=? WHERE id=?",
            (datos['descripcion'], datos['unidad'], datos['tipo'],
             datos['indice_inei'], recurso_id)
        )
        conn.commit()
        conn.close()
        # Recargar insumos para reflejar cambios
        self.cargar_insumos(self._ins_estado)

    def _ins_click_precio(self, ri: int, col: int):
        if col == 4:
            self._abrir_editor_precio_ins(ri)

    def _abrir_editor_precio_ins(self, ri: int):
        """Abre un QLineEdit overlay sobre la celda Precio U. de la fila ri."""
        # El precio de insumo se propaga al proyecto y cambia el monto del
        # presupuesto → bloquear si el estado no permite editar el presupuesto.
        if not self._require_editable('cambiar el precio de un insumo', 'presupuesto'):
            return
        tbl = self.tbl_ins
        if not (0 <= ri < tbl.rowCount()):
            return
        it_precio = tbl.item(ri, 4)
        badge     = tbl.item(ri, 0)
        if not it_precio or not badge or not badge.data(Qt.UserRole):
            return

        # Cerrar editor previo si existe
        prev = getattr(self, '_ins_ed', None)
        if prev:
            try:
                prev.hide()
                prev.deleteLater()
            except RuntimeError:
                pass
            self._ins_ed = None

        rect   = tbl.visualItemRect(it_precio)
        rec_id = badge.data(Qt.UserRole)
        cant   = badge.data(Qt.UserRole + 2) or 0.0

        ed = QLineEdit(tbl.viewport())
        ed.setGeometry(rect)
        ed.setText(f"{_parse_precio(it_precio.text()):.4f}")
        ed.selectAll()
        ed.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        ed.setStyleSheet(
            'background:white; border:2px solid #F37329;'
            ' border-radius:2px; padding:0 2px; font-size:11px;'
        )
        ed.show()
        ed.setFocus()
        self._ins_ed = ed
        done = [False]

        def guardar_y_mover(delta=0):
            if done[0]:
                return
            done[0] = True
            self._ins_ed = None
            ed.hide()
            txt = ed.text().strip().replace(',', '.')
            try:
                nuevo = float(txt)
            except ValueError:
                nuevo = None
            if nuevo is not None:
                dec = get_decimales_ppto()
                it_precio.setText(fmt(nuevo, self._moneda))
                it_p = tbl.item(ri, 5)
                if it_p:
                    it_p.setText(fmt(_rn(cant * nuevo, dec), self._moneda))
                QTimer.singleShot(0, lambda: self._guardar_precio_insumo_inline(rec_id, nuevo))
            if delta:
                QTimer.singleShot(20, lambda: self._abrir_editor_precio_ins(ri + delta))
            else:
                tbl.setFocus()

        class _Nav(QObject):
            def eventFilter(s, obj, ev):
                if ev.type() != QEvent.Type.KeyPress:
                    return False
                k = ev.key()
                if k in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Tab, Qt.Key_Down):
                    guardar_y_mover(+1); return True
                if k in (Qt.Key_Up, Qt.Key_Backtab):
                    guardar_y_mover(-1); return True
                if k == Qt.Key_Escape:
                    done[0] = True
                    self._ins_ed = None
                    ed.hide()
                    tbl.setFocus()
                    return True
                return False

        ed._filt = _Nav(ed)
        ed.installEventFilter(ed._filt)
        # Guardar también al perder el foco (clic fuera)
        ed.editingFinished.connect(lambda: guardar_y_mover(0))

    def _guardar_precio_insumo_inline(self, recurso_id: int, nuevo_precio: float):
        """Actualiza acu_items.precio en el proyecto y recalcula partidas afectadas."""
        try:
            conn = get_db()
            conn.execute(
                """UPDATE acu_items SET precio=?
                   WHERE recurso_id=?
                   AND partida_id IN (SELECT id FROM partidas WHERE proyecto_id=?)""",
                (nuevo_precio, recurso_id, self.pid)
            )
            afectadas = conn.execute(
                """SELECT DISTINCT ai.partida_id FROM acu_items ai
                   JOIN partidas p ON p.id=ai.partida_id
                   WHERE ai.recurso_id=? AND p.proyecto_id=?""",
                (recurso_id, self.pid)
            ).fetchall()
            for (pid_af,) in afectadas:
                _recalcular_pu(conn, pid_af)
            conn.commit()
            conn.close()
            self.recargar_partidas()
            self.actualizar_total()
            if self._partida_actual_id:
                self.cargar_acu(self._partida_actual_id)
        except Exception as e:
            import traceback; traceback.print_exc()
            print(f"[precio_insumo] ERROR: {e}")

    def _unificar_precio_insumo(self, recurso_id: int, precio: float,
                                 desc: str = ""):
        """Unifica el precio de un insumo en todo el proyecto al valor dado."""
        if not self._require_editable('unificar el precio'):
            return
        try:
            conn = get_db()
            unificar_precio_recurso(conn, self.pid, recurso_id, precio)
            conn.commit()
            conn.close()
        except Exception as e:
            import traceback; traceback.print_exc()
            print(f"[unificar_precio] ERROR: {e}")
            return
        self.recargar_partidas()
        self.actualizar_total()
        self.cargar_insumos(self._ins_estado)
        if self._partida_actual_id:
            self.cargar_acu(self._partida_actual_id)

    def _unificar_todos_precios(self):
        """Unifica de una vez el precio de todos los insumos con precio
        inconsistente en el proyecto, usando el precio sugerido (más usado;
        empate → catálogo). Pide confirmación mostrando el detalle."""
        if not self._require_editable('unificar precios'):
            return
        from utils.i18n import tr
        conn = get_db()
        try:
            incon = precios_inconsistentes(conn, self.pid)
        except Exception:
            incon = {}
        if not incon:
            conn.close()
            QMessageBox.information(
                self, tr("Precios consistentes"),
                tr("No hay insumos con precios distintos en este proyecto.")
            )
            return

        # Detalle ordenado por mayor dispersión (max - min).
        def _disp(info):
            ps = [p for p, _ in info['variantes']]
            return max(ps) - min(ps)
        items = sorted(incon.items(), key=lambda kv: _disp(kv[1]), reverse=True)
        lineas = []
        for _rid, info in items[:12]:
            variantes_txt = ", ".join(
                f"{fmt(p, self._moneda)}×{n}" for p, n in info['variantes']
            )
            lineas.append(
                f"• {(info['descripcion'] or '')[:38]}\n"
                f"    {variantes_txt}  →  {fmt(info['sugerido'], self._moneda)}"
            )
        if len(items) > 12:
            lineas.append(tr("… y {n} más").format(n=len(items) - 12))
        detalle = "\n".join(lineas)

        resp = QMessageBox.question(
            self, tr("Unificar precios"),
            tr("{n} insumo(s) tienen precios distintos en el proyecto.\n"
               "Se fijará el precio más usado (empate → catálogo) en todas "
               "las partidas:\n\n{detalle}\n\n¿Unificar ahora?").format(
                   n=len(incon), detalle=detalle),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
        )
        if resp != QMessageBox.Yes:
            conn.close()
            return
        try:
            for rid, info in incon.items():
                unificar_precio_recurso(conn, self.pid, rid, float(info['sugerido'] or 0))
            conn.commit()
        except Exception as e:
            import traceback; traceback.print_exc()
            print(f"[unificar_precios] ERROR: {e}")
        finally:
            conn.close()
        self.recargar_partidas()
        self.actualizar_total()
        self.cargar_insumos(self._ins_estado)
        if self._partida_actual_id:
            self.cargar_acu(self._partida_actual_id)

    def _verificar_pu_acu(self):
        """Muestra las partidas cuyo PU guardado no coincide con la suma de su
        ACU y deja elegir: recalcular el PU desde el análisis (presupuestos
        hechos en la app) o quitar el análisis manteniendo el PU (importaciones
        antiguas con ACU incompleto, p.ej. sub-análisis «---» a precio 0)."""
        if not self._require_editable('verificar PU vs ACU'):
            return
        from utils.i18n import tr
        conn = get_db()
        try:
            incon = partidas_pu_inconsistente(conn, self.pid)
        except Exception:
            incon = []
        if not incon:
            conn.close()
            QMessageBox.information(
                self, tr("PU consistentes"),
                tr("El precio unitario de todas las partidas coincide con su análisis.")
            )
            return

        lineas = []
        for d in incon[:12]:
            lineas.append(
                f"• {d['item']} {(d['descripcion'] or '')[:36]}\n"
                f"    {tr('guardado')}: {fmt(d['pu_guardado'], self._moneda)}  ·  "
                f"ACU: {fmt(d['pu_acu'], self._moneda)}"
            )
        if len(incon) > 12:
            lineas.append(tr("… y {n} más").format(n=len(incon) - 12))
        detalle = "\n".join(lineas)

        # Impacto en el Costo Directo si se recalcula: la diferencia entre
        # parciales con el PU del ACU vs el PU guardado. Hace evidente el
        # riesgo de recalcular sobre análisis incompletos.
        delta_cd = 0.0
        for d in incon:
            met = conn.execute("SELECT metrado FROM partidas WHERE id=?",
                               (d['partida_id'],)).fetchone()
            met = (met['metrado'] if met else 0) or 0
            delta_cd += (parcial_wysiwyg(met, d['pu_acu'])
                         - parcial_wysiwyg(met, d['pu_guardado']))
        signo = '+' if delta_cd >= 0 else '−'
        impacto = f"{signo} {fmt(abs(delta_cd), self._moneda)}"

        box = QMessageBox(self)
        box.setWindowTitle(tr("PU distinto a su análisis"))
        box.setIcon(QMessageBox.Warning)
        box.setText(tr(
            "{n} partida(s) tienen un PU guardado que NO coincide con la suma "
            "de su análisis de costos.\n\n{detalle}\n\n"
            "⚠ Recalcular cambiaría el Costo Directo en {impacto}.\n"
            "Quitar análisis NO cambia ningún monto del presupuesto.\n\n"
            "• Si el presupuesto se elaboró en ingePresupuestos, lo correcto es "
            "RECALCULAR el PU desde el ACU.\n"
            "• Si viene de una importación antigua con análisis incompletos "
            "(insumos «---» a precio 0), el PU guardado es el del software "
            "origen: conviene QUITAR esos análisis y conservar el PU."
        ).format(n=len(incon), detalle=detalle, impacto=impacto))
        btn_recalc = box.addButton(tr("Recalcular PU desde ACU"), QMessageBox.AcceptRole)
        btn_quitar = box.addButton(tr("Quitar análisis (mantener PU)"), QMessageBox.DestructiveRole)
        box.addButton(QMessageBox.Cancel)
        box.setDefaultButton(QMessageBox.Cancel)
        box.exec()

        clicked = box.clickedButton()
        try:
            if clicked is btn_recalc:
                if abs(delta_cd) > 0.01:
                    resp = QMessageBox.question(
                        self, tr("Confirmar recálculo"),
                        tr("El Costo Directo del proyecto cambiará en {impacto}.\n"
                           "Esta acción reemplaza el PU guardado de {n} partida(s).\n\n"
                           "¿Recalcular de todas formas?").format(
                               impacto=impacto, n=len(incon)),
                        QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                    if resp != QMessageBox.Yes:
                        conn.close()
                        return
                for d in incon:
                    _recalcular_pu(conn, d['partida_id'])
                conn.commit()
            elif clicked is btn_quitar:
                for d in incon:
                    conn.execute("DELETE FROM acu_items WHERE partida_id=?",
                                 (d['partida_id'],))
                conn.commit()
            else:
                conn.close()
                return
        except Exception as e:
            import traceback; traceback.print_exc()
            print(f"[verificar_pu_acu] ERROR: {e}")
        finally:
            conn.close()
        self.recargar_partidas()
        self.actualizar_total()
        self.cargar_insumos(self._ins_estado)
        if self._partida_actual_id:
            self.cargar_acu(self._partida_actual_id)

    def _ins_menu_contextual(self, pos):
        """Menú contextual en tabla Insumos."""
        item = self.tbl_ins.itemAt(pos)
        if not item:
            return
        ri = item.row()
        badge = self.tbl_ins.item(ri, 0)
        if not badge or not badge.data(Qt.UserRole):
            return
        recurso_id = badge.data(Qt.UserRole)
        desc       = badge.data(Qt.UserRole + 1) or ""
        precio_txt = (self.tbl_ins.item(ri, 4) or QTableWidgetItem("0")).text()
        precio     = _parse_precio(precio_txt)

        from PySide6.QtWidgets import QMenu
        from utils.i18n import tr
        menu = QMenu(self)
        incon = getattr(self, '_ins_incon', {}).get(recurso_id)
        if incon and self._ed_presupuesto:
            sug = float(incon['sugerido'] or 0)
            act_uni = menu.addAction(
                f"⚠ {tr('Unificar precio')} ({fmt(sug, self._moneda)})"
            )
            act_uni.triggered.connect(
                lambda: self._unificar_precio_insumo(recurso_id, sug, desc)
            )
            menu.addSeparator()
        act_part = menu.addAction(tr("Mostrar partidas que usan este insumo"))
        act_part.triggered.connect(
            lambda: self._resaltar_partidas_con_insumo(recurso_id, desc))
        if getattr(self, '_ins_resaltados', None):
            act_limp = menu.addAction(tr("Quitar resaltado de partidas"))
            act_limp.triggered.connect(self._limpiar_resaltado_insumo)
        menu.addSeparator()
        act_edit = menu.addAction(tr("Editar"))
        act_edit.triggered.connect(lambda: self._ins_doble_clic_recurso(ri, 0))
        menu.addSeparator()
        act_swap = menu.addAction(tr("Reemplazar") + "…")
        act_swap.triggered.connect(
            lambda: self._ins_reemplazar_recurso(recurso_id, desc)
        )
        menu.addSeparator()
        act_cat = menu.addAction(tr("Actualizar catálogo") + f" ({precio_txt})")
        act_cat.triggered.connect(lambda: self._actualizar_precio_catalogo(recurso_id, precio, desc))
        menu.exec(self.tbl_ins.viewport().mapToGlobal(pos))

    def _limpiar_resaltado_insumo(self):
        """Restaura el fondo original de las partidas resaltadas."""
        for item, brushes in getattr(self, '_ins_resaltados', []):
            try:
                for c, br in enumerate(brushes):
                    item.setBackground(c, br)
            except RuntimeError:
                pass   # el item ya no existe (árbol recargado)
        self._ins_resaltados = []

    def _resaltar_partidas_con_insumo(self, recurso_id: int, desc: str):
        """Resalta en verde, en el árbol del presupuesto, las partidas cuyo ACU
        usa este insumo. Útil para trazar dónde se consume un recurso."""
        from utils.i18n import tr
        self._limpiar_resaltado_insumo()
        conn = get_db()
        ids = [r[0] for r in conn.execute(
            "SELECT DISTINCT ai.partida_id FROM acu_items ai "
            "JOIN partidas p ON p.id = ai.partida_id "
            "WHERE ai.recurso_id=? AND p.proyecto_id=?",
            (recurso_id, self.pid)).fetchall()]
        conn.close()
        if not ids:
            QMessageBox.information(
                self, tr("Insumo"),
                tr("Ninguna partida usa este insumo en el proyecto."))
            return
        verde = QColor("#C9F0D2")
        ncol = self.tree.columnCount()
        resaltados = []
        primero = None
        for pid in ids:
            it = self._id_to_item.get(pid)
            if it is None:
                continue
            brushes = [QBrush(it.background(c)) for c in range(ncol)]
            resaltados.append((it, brushes))
            for c in range(ncol):
                it.setBackground(c, QBrush(verde))
            # Expandir ancestros para que la fila sea visible.
            anc = it.parent()
            while anc is not None:
                anc.setExpanded(True)
                anc = anc.parent()
            if primero is None:
                primero = it
        self._ins_resaltados = resaltados
        if primero is not None:
            self.tree.scrollToItem(primero)
            self.tree.setCurrentItem(primero)
        win = self.window()
        if hasattr(win, 'statusBar') and win.statusBar():
            n = len(resaltados)
            extra = len(ids) - n
            msg = (f"{n} partida(s) usan «{desc[:40]}» — resaltadas en verde "
                   "(clic derecho en Insumos → Quitar resaltado).")
            if extra > 0:
                msg += f"  (+{extra} en otro subpresupuesto)"
            win.statusBar().showMessage(msg, 6000)

    def _ins_reemplazar_recurso(self, recurso_id_viejo: int,
                                 desc_viejo: str):
        """Sustituye todas las apariciones de `recurso_id_viejo` en los ACUs
        del proyecto activo por otro recurso elegido. Útil para fusionar
        insumos duplicados detectados con /duplicados.

        Mantiene `acu_items.precio` (override) si existe — el usuario
        puede ajustarlo después. Recalcula PU de las partidas afectadas.
        """
        if not self._require_editable('ACU'):
            return
        dlg = _SeleccionarRecursoDialog(self.pid, recurso_id_viejo,
                                         desc_viejo, parent=self)
        if dlg.exec() != QDialog.Accepted:
            return
        nuevo_id = dlg.selected_id
        if not nuevo_id or nuevo_id == recurso_id_viejo:
            return
        conn = get_db()
        try:
            # Partidas afectadas (las que usan el recurso viejo en este proyecto)
            partidas = conn.execute(
                "SELECT DISTINCT ai.partida_id FROM acu_items ai"
                " JOIN partidas p ON p.id = ai.partida_id"
                " WHERE ai.recurso_id=? AND p.proyecto_id=?",
                (recurso_id_viejo, self.pid)
            ).fetchall()
            part_ids = [r['partida_id'] for r in partidas]
            if not part_ids:
                conn.close()
                QMessageBox.information(
                    self, "Sin cambios",
                    "Este recurso no aparece en ningún ACU del proyecto."
                )
                return
            # Verificar si la fusión crearía colisión: el nuevo recurso ya
            # existe en algunas de esas partidas. Si sí, hay que sumar
            # cantidades en lugar de simplemente cambiar el id.
            placeholders = ','.join('?' * len(part_ids))
            colisiones = conn.execute(
                f"SELECT partida_id, id, cuadrilla, cantidad, precio"
                f" FROM acu_items"
                f" WHERE recurso_id=? AND partida_id IN ({placeholders})",
                (nuevo_id, *part_ids)
            ).fetchall()
            colision_por_part = {c['partida_id']: c for c in colisiones}

            n_fusionadas = 0
            n_simples = 0
            for pid_aff in part_ids:
                viejo = conn.execute(
                    "SELECT id, cuadrilla, cantidad, precio FROM acu_items"
                    " WHERE recurso_id=? AND partida_id=?",
                    (recurso_id_viejo, pid_aff)
                ).fetchone()
                if not viejo:
                    continue
                col = colision_por_part.get(pid_aff)
                if col:
                    # Hay colisión: sumar cantidad+cuadrilla al item existente,
                    # borrar el viejo. Para precio override, conservar el del
                    # item destino (no del nuevo) salvo que sea NULL.
                    cuad_total = (col['cuadrilla'] or 0) + (viejo['cuadrilla'] or 0)
                    cant_total = (col['cantidad'] or 0) + (viejo['cantidad'] or 0)
                    conn.execute(
                        "UPDATE acu_items SET cuadrilla=?, cantidad=? WHERE id=?",
                        (cuad_total, cant_total, col['id'])
                    )
                    conn.execute("DELETE FROM acu_items WHERE id=?", (viejo['id'],))
                    n_fusionadas += 1
                else:
                    conn.execute(
                        "UPDATE acu_items SET recurso_id=? WHERE id=?",
                        (nuevo_id, viejo['id'])
                    )
                    n_simples += 1
                # Recalcular PU de la partida afectada
                _recalcular_pu(conn, pid_aff)
            conn.commit()
        finally:
            conn.close()
        self.cargar_insumos()
        self.recargar_partidas()
        QMessageBox.information(
            self, "Reemplazo aplicado",
            f"Reemplazado en {n_simples + n_fusionadas} partida(s).\n"
            f"  • {n_simples} simples (solo cambió el recurso)\n"
            f"  • {n_fusionadas} fusionadas (se sumaron cuad/cant al existente)"
        )

    def _actualizar_precio_catalogo(self, recurso_id: int, precio: float, desc: str):
        if not self._require_editable('actualizar el precio en el catálogo', 'presupuesto'):
            return
        res = QMessageBox.question(
            self, "Actualizar catálogo",
            f"¿Actualizar el precio de\n«{desc}»\nen el catálogo global a {precio:.4f}?",
            QMessageBox.Yes | QMessageBox.No
        )
        if res == QMessageBox.Yes:
            conn = get_db()
            conn.execute("UPDATE recursos SET precio=? WHERE id=?", (precio, recurso_id))
            conn.commit()
            conn.close()

    def cargar_metrados(self, part_id: int):
        self._met_panel_pid = part_id
        self._met_loading = True
        conn = get_db()
        rows = conn.execute(
            "SELECT * FROM metrados_detalle WHERE partida_id=? ORDER BY orden",
            (part_id,)
        ).fetchall()
        partida_row = conn.execute(
            "SELECT item, descripcion FROM partidas WHERE id=?", (part_id,)
        ).fetchone()
        conn.close()

        if partida_row and hasattr(self, 'lbl_met_titulo'):
            self.lbl_met_titulo.setText(
                f"{partida_row['item']}  {partida_row['descripcion'] or ''}"
            )

        dec = get_decimales_metrado()
        self.tbl_met.setRowCount(0)
        total = 0.0
        for row in rows:
            r = self.tbl_met.rowCount()
            self.tbl_met.insertRow(r)
            self.tbl_met.setRowHeight(r, 24)

            vals = [
                row['descripcion'] or '',
                str(row['n_estructuras'] or ''),
                str(row['n_elementos'] or ''),
                str(row['area'] or ''),
                str(row['largo'] or ''),
                str(row['ancho'] or ''),
                str(row['alto'] or ''),
                f"{(row['parcial'] or 0):,.{dec}f}",
            ]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if c == 7:   # parcial — no editable
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    it.setBackground(QColor(SILVER_100))
                elif c > 0:
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.tbl_met.setItem(r, c, it)
            total += float(row['parcial'] or 0)

        self.lbl_met_total.setText(f"{total:,.{dec}f}")
        self._met_loading = False
        self._met_dirty   = False   # datos recién cargados, sin cambios
        self._metrado_nueva_fila()   # fila en blanco lista al final
        # Reaplicar bloqueo de flags si el estado lo requiere
        if not getattr(self, '_ed_presupuesto', True):
            self._strip_table_editable_flags(self.tbl_met)

    def cargar_resumen(self):
        _, totales = calcular_totales(self.pid)

        # Limpiar layout
        while self._resumen_layout.count():
            item = self._resumen_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # ── Datos MO/MAT/EQ ──────────────────────────────────────────
        conn = get_db()
        tipos = conn.execute(
            """SELECT r.tipo,
                      SUM(ai.cantidad * p.metrado * COALESCE(ai.precio, r.precio, 0)) as total
               FROM acu_items ai
               JOIN recursos r ON r.id = ai.recurso_id
               JOIN partidas p ON p.id = ai.partida_id
               WHERE p.proyecto_id = ? AND p.es_titulo = 0
                 AND SUBSTR(r.unidad,1,1) != '%'
               GROUP BY r.tipo""",
            (self.pid,)
        ).fetchall()
        _dec = get_decimales_ppto()
        _dm  = get_decimales_metrado()
        top5 = conn.execute(
            f"""SELECT item, descripcion,
                       ROUND(ROUND(COALESCE(metrado,0), {_dm}) * COALESCE(precio_unitario,0), {_dec}) as total
               FROM partidas WHERE proyecto_id=? AND es_titulo=0
               ORDER BY total DESC LIMIT 5""",
            (self.pid,)
        ).fetchall()
        conn.close()

        mo_val  = next((r['total'] or 0 for r in tipos if r['tipo'] == 'MO'),  0)
        mat_val = next((r['total'] or 0 for r in tipos if r['tipo'] == 'MAT'), 0)
        eq_val  = next((r['total'] or 0 for r in tipos if r['tipo'] == 'EQ'),  0)
        sc_val  = next((r['total'] or 0 for r in tipos if r['tipo'] == 'SC'),  0)

        # ── Fila top: Resumen izq + Donut der ────────────────────────
        top_row = QWidget()
        top_row.setStyleSheet("background:transparent;")
        hl_top = QHBoxLayout(top_row)
        hl_top.setContentsMargins(0, 0, 0, 0)
        hl_top.setSpacing(12)

        # Card Resumen de costos
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background:white; border:1px solid {SILVER_300}; border-radius:8px; }}"
        )
        vl = QVBoxLayout(card)
        vl.setContentsMargins(14, 12, 14, 12)
        vl.setSpacing(6)

        lbl_sec = QLabel("RESUMEN DE COSTOS")
        lbl_sec.setStyleSheet(
            f"color:{SLATE_500}; font-size:10px; font-weight:700; letter-spacing:0.8px; border:none;"
        )
        vl.addWidget(lbl_sec)
        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        # Card de costos dinámica según pie_rubros activos — project-wide
        # (suma todos los subpresupuestos; el resto del tab Resumen también
        # consulta WHERE proyecto_id=? sin filtro de sub)
        card, _ = self._build_resumen_card(all_subs=True)
        hl_top.addWidget(card, stretch=3)

        cd = totales.get('cd', 0)

        # Card Gráfico donut
        if mo_val + mat_val + eq_val + sc_val > 0:
            card_chart = QFrame()
            card_chart.setStyleSheet(
                f"QFrame {{ background:white; border:1px solid {SILVER_300}; border-radius:8px; }}"
            )
            vl_c = QVBoxLayout(card_chart)
            vl_c.setContentsMargins(10, 12, 10, 12)
            vl_c.setSpacing(6)

            lbl_ch = QLabel("DISTRIBUCIÓN CD")
            lbl_ch.setAlignment(Qt.AlignCenter)
            lbl_ch.setStyleSheet(
                f"color:{SLATE_500}; font-size:10px; font-weight:700; letter-spacing:0.8px; border:none;"
            )
            vl_c.addWidget(lbl_ch)

            slices = [
                ("Mano de Obra",   mo_val,  "#F39C12"),
                ("Materiales",     mat_val, "#27AE60"),
                ("Equipo",         eq_val,  "#607D8B"),
            ]
            if sc_val > 0:
                slices.append(("Sub-contratos", sc_val, "#7A36B1"))
            self._donut = _DonutChart(slices)
            vl_c.addWidget(self._donut, stretch=1)
            hl_top.addWidget(card_chart, stretch=2)

        self._resumen_layout.addWidget(top_row)

        # ── Top 5 partidas ───────────────────────────────────────────
        if top5:
            card2 = QFrame()
            card2.setStyleSheet(
                f"QFrame {{ background:white; border:1px solid {SILVER_300}; border-radius:8px; }}"
            )
            vl2 = QVBoxLayout(card2)
            vl2.setContentsMargins(14, 12, 14, 12)
            vl2.setSpacing(6)
            lbl_t = QLabel("TOP 5 PARTIDAS MÁS COSTOSAS")
            lbl_t.setStyleSheet(
                f"color:{SLATE_500}; font-size:10px; font-weight:700; letter-spacing:0.8px; border:none;"
            )
            vl2.addWidget(lbl_t)
            sep3 = QFrame(); sep3.setFrameShape(QFrame.HLine)
            sep3.setStyleSheet(f"color:{SILVER_300};"); vl2.addWidget(sep3)

            cd_total = cd if cd > 0 else 1
            for p in top5:
                monto = p['total'] or 0
                pct   = monto / cd_total * 100
                hl = QHBoxLayout()
                ln = QLabel(f"{p['item']}  {(p['descripcion'] or '')[:45]}")
                ln.setStyleSheet(f"color:{SLATE_700}; font-size:11px; border:none;")
                lv = QLabel(f"{fmt(monto, self._moneda)}  ({pct:.1f}%)")
                lv.setAlignment(Qt.AlignRight)
                lv.setStyleSheet(
                    f"color:{SLATE_500}; font-size:11px; border:none;"
                )
                hl.addWidget(ln, stretch=1); hl.addWidget(lv)
                vl2.addLayout(hl)
            self._resumen_layout.addWidget(card2)

        self._resumen_layout.addStretch()

    # ══════════════════════════════════════════════════════════════════════════
    # Recalcular
    # ══════════════════════════════════════════════════════════════════════════

    def recalcular(self):
        conn = get_db()
        partidas = conn.execute(
            "SELECT id FROM partidas WHERE proyecto_id=? AND es_titulo=0", (self.pid,)
        ).fetchall()
        for (pid,) in partidas:
            _recalcular_pu(conn, pid)
        conn.commit()
        conn.close()
        self.recargar_partidas()
        self.cargar_insumos()
        self.cargar_resumen()
        if self._partida_actual_id:
            self.cargar_acu(self._partida_actual_id)

    # ══════════════════════════════════════════════════════════════════════════
    # Eventos
    # ══════════════════════════════════════════════════════════════════════════

    def _on_reordenadas(self):
        """Llamado tras drag & drop: recarga colores y totales sin perder la selección."""
        pid_sel = self._partida_actual_id
        self.recargar_partidas()
        # Restaurar selección si sigue existiendo
        if pid_sel and pid_sel in self._id_to_item:
            self.tree.blockSignals(True)
            self.tree.setCurrentItem(self._id_to_item[pid_sel])
            self.tree.blockSignals(False)
        self.actualizar_total()

    def _deseleccionar(self):
        self.tree.clearSelection()
        self.tree.setCurrentItem(None)
        self._partida_actual_id = None
        # Esc también quita el resaltado verde de «partidas que usan el insumo».
        self._limpiar_resaltado_insumo()
        if self.tabs.currentIndex() == 1:
            self.cargar_insumos()

    def _mostrar_atajos(self):
        """Muestra un diálogo con todos los atajos de teclado del proyecto,
        distribuidos en 3 columnas balanceadas."""
        from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                                          QDialogButtonBox, QGridLayout, QWidget,
                                          QFrame)
        from PySide6.QtGui import QPalette, QColor as _QColor

        dlg = QDialog()
        dlg.setWindowTitle("Atajos de teclado")
        dlg.resize(920, 540)
        dlg.setAttribute(Qt.WA_StyledBackground, True)
        dlg.setWindowModality(Qt.ApplicationModal)
        pal = dlg.palette()
        pal.setColor(QPalette.Window, _QColor("#FFFFFF"))
        pal.setColor(QPalette.WindowText, _QColor("#1F2A38"))
        dlg.setPalette(pal)
        dlg.setStyleSheet(
            "QDialog { background:#FFFFFF; color:#1F2A38; }"
            "QLabel { color:#1F2A38; background:transparent; font-size:11px; }"
            "QLabel#section { color:#C0621A; font-size:12px; font-weight:700;"
            " padding:8px 0 2px 0; border-bottom:1px solid #E2E8F0; }"
            "QLabel#key { color:#1F2A38; background:#F8F9FA; font-size:11px;"
            " font-weight:700; padding:2px 6px; border:1px solid #CBD5E1;"
            " border-radius:4px; }"
            "QDialogButtonBox QPushButton { min-width:88px; padding:5px 12px;"
            " font-size:11px; background:#F37329; color:#FFFFFF;"
            " border:1px solid #C0621A; border-radius:4px; }"
            "QDialogButtonBox QPushButton:hover { background:#C0621A; }"
        )
        vl = QVBoxLayout(dlg)
        vl.setContentsMargins(16, 12, 16, 12)
        vl.setSpacing(10)

        # Tres columnas balanceadas (~12 items c/u). Cada columna agrupa
        # secciones relacionadas verticalmente.
        columnas = [
            # Columna 1
            [
                ('Generales', [
                    ('F1',                 'Mostrar este diálogo'),
                    ('F5',                 'Recalcular precios y totales'),
                    ('Esc',                'Deseleccionar partida'),
                    ('Ctrl+F',             'Enfocar buscador del topbar'),
                    ('Ctrl+N',             'Nuevo proyecto'),
                    ('Ctrl+O',             'Abrir otro proyecto'),
                    ('Ctrl+P',             'Imprimir reporte'),
                ]),
                ('Cronograma — Gantt', [
                    ('Ctrl + rueda',       'Zoom horizontal (acercar/alejar)'),
                    ('Rueda',              'Scroll vertical sincronizado'),
                    ('Arrastrar barra',    'Mover tarea (snap a día)'),
                    ('Arrastrar borde',    'Cambiar duración'),
                    ('Clic derecho',       'Menú: dividir, hito, etc.'),
                ]),
            ],
            # Columna 2 — la más larga
            [
                ('Árbol de partidas', [
                    ('Insert',             'Insertar partida hermana'),
                    ('Ctrl+Insert',        'Insertar título / rama'),
                    ('F2',                 'Editar partida seleccionada'),
                    ('Ctrl+D',             'Duplicar partida'),
                    ('Supr / Delete',      'Eliminar partida(s)'),
                    ('Ctrl+C / Ctrl+V',    'Copiar / Pegar + subárbol'),
                    ('Ctrl+X',             'Cortar (copia y elimina)'),
                    ('Alt+↑ / Alt+↓',      'Mover arriba / abajo'),
                    ('Alt+← / Alt+→',      'Subir / bajar nivel'),
                    ('Ctrl+Inicio',        'Ir a la primera partida'),
                    ('Ctrl+Fin',           'Ir a la última partida'),
                    ('Doble clic',         'Editar metrado inline'),
                    ('Clic derecho',       'Menú de partida'),
                ]),
            ],
            # Columna 3
            [
                ('Tablas (ACU · Insumos · Metrados · Acero)', [
                    ('Ctrl+C',             'Copiar celdas seleccionadas'),
                    ('Ctrl+V',             'Pegar al rango seleccionado'),
                    ('Supr / Backspace',   'Limpiar / eliminar fila'),
                    ('Doble clic',         'Editar valor de la celda'),
                    ('Tab / Shift+Tab',    'Navegar entre celdas'),
                ]),
                ('Predecesoras (columna "Pred.")', [
                    ('5',                  'FS: inicia cuando 5 termina'),
                    ('5+3',                'FS con 3 días de lag'),
                    ('5SS  /  5SS+2',      'Start-to-Start (± lag)'),
                    ('5FF  /  5FF-1',      'Finish-to-Finish (± lag)'),
                    ('5SF',                'Start-to-Finish (raro)'),
                    ('5+50%',              'Arranca cuando 5 lleva 50%'),
                    ('3, 4SS',             'Múltiples preds. con coma'),
                ]),
            ],
        ]

        cols_hbox = QHBoxLayout()
        cols_hbox.setSpacing(20)

        for col_secciones in columnas:
            col_w = QWidget()
            col_vl = QVBoxLayout(col_w)
            col_vl.setContentsMargins(0, 0, 0, 0)
            col_vl.setSpacing(6)
            for seccion, items in col_secciones:
                lbl_sec = QLabel(seccion)
                lbl_sec.setObjectName("section")
                lbl_sec.setWordWrap(True)
                col_vl.addWidget(lbl_sec)
                grid = QGridLayout()
                grid.setSpacing(4)
                grid.setColumnStretch(1, 1)
                grid.setColumnMinimumWidth(0, 110)
                for r_, (key, desc) in enumerate(items):
                    lbl_k = QLabel(key)
                    lbl_k.setObjectName("key")
                    lbl_k.setAlignment(Qt.AlignCenter)
                    grid.addWidget(lbl_k, r_, 0)
                    lbl_d = QLabel(desc)
                    lbl_d.setWordWrap(True)
                    grid.addWidget(lbl_d, r_, 1)
                holder = QWidget()
                holder.setLayout(grid)
                col_vl.addWidget(holder)
            col_vl.addStretch(1)
            cols_hbox.addWidget(col_w, 1)

        vl.addLayout(cols_hbox, 1)

        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.button(QDialogButtonBox.Close).setText("Cerrar")
        bb.rejected.connect(dlg.reject)
        bb.accepted.connect(dlg.accept)
        bb.button(QDialogButtonBox.Close).clicked.connect(dlg.accept)
        vl.addWidget(bb)
        dlg.exec()

    def _on_partida_seleccionada(self, current, previous):
        # Guardar planilla y specs antes de cambiar de partida
        if self._spec_modificada and self._partida_actual_id:
            self._guardar_spec()
        if self._met_modo == 'met' and self._met_panel_pid:
            from PySide6.QtCore import QModelIndex as _QMI
            self.tbl_met.setCurrentIndex(_QMI())   # cierra editor → guarda via itemChanged
        elif self._met_modo == 'acero' and self._met_panel_pid:
            self._acero_guardar_silencioso()
        if not current:
            return
        pid   = current.data(0, Qt.UserRole)
        es_tt = current.data(0, Qt.UserRole + 1)
        if not pid:
            return
        # Memoria Tuxia: guardar último partida (no-título) editada en este proyecto
        if not es_tt and hasattr(self, '_tuxia') and self._tuxia is not None:
            try:
                self._tuxia._qs.setValue(f"last_partida/{self.pid}", int(pid))
            except Exception:
                pass
        if not es_tt:
            self.cargar_acu(pid)
        tab = self.tabs.currentIndex()
        if tab == 1:
            if es_tt:
                ids = self._partidas_bajo_titulo(current)
                desc = current.text(1)
                self._ins_titulo_label = f"INSUMOS  ·  {desc[:50]}"
                self.cargar_insumos(ids)
            else:
                self.cargar_insumos(pid)
        elif tab == 2 and not es_tt:
            self._cargar_metrados_auto(pid)

    def _cargar_metrados_auto(self, pid: int):
        """Detecta si la partida tiene acero o metrados normales y activa el modo correcto."""
        conn = get_db()
        tiene_acero = conn.execute(
            "SELECT 1 FROM acero_detalle WHERE partida_id=? LIMIT 1", (pid,)
        ).fetchone() is not None
        tiene_met   = conn.execute(
            "SELECT 1 FROM metrados_detalle WHERE partida_id=? LIMIT 1", (pid,)
        ).fetchone() is not None
        prow = conn.execute(
            "SELECT descripcion, unidad, metrado_tipo FROM partidas WHERE id=?", (pid,)
        ).fetchone()
        conn.close()

        # Decisión centralizada (datos → flag explícito → heurística). Si nada
        # define el modo (partida vacía sin flag ni pista), respetar el toggle.
        flag = prow['metrado_tipo'] if prow else None
        desc = prow['descripcion'] if prow else ''
        und = prow['unidad'] if prow else ''
        if tiene_acero or tiene_met:
            modo = 'acero' if tiene_acero else 'met'
        elif flag in ('acero', 'met'):
            modo = flag
        elif partida_usa_acero(False, False, None, desc, und):
            modo = 'acero'
        else:
            modo = self._met_modo   # respetar selección del usuario

        if modo != self._met_modo:
            self._toggle_met_modo(modo)   # actualiza botones y stack
        else:
            if modo == 'acero':
                self.cargar_acero(pid)
            else:
                self.cargar_metrados(pid)

    def _on_tab_cambiado(self, idx: int):
        if idx == 1:   # Insumos — respetar estado actual (partida, grupo o total)
            current = self.tree.currentItem()
            if current:
                pid   = current.data(0, Qt.UserRole)
                es_tt = current.data(0, Qt.UserRole + 1)
                if pid and es_tt:
                    ids = self._partidas_bajo_titulo(current)
                    self._ins_titulo_label = f"INSUMOS  ·  {current.text(1)[:50]}"
                    self.cargar_insumos(ids)
                elif pid:
                    self.cargar_insumos(pid)
                else:
                    self.cargar_insumos(None)
            else:
                self.cargar_insumos(None)
        elif idx == 2 and self._partida_actual_id:  # Metrados
            self._cargar_metrados_auto(self._partida_actual_id)
        elif idx == 4:  # Resumen
            self.cargar_resumen()
        # Tuxia: tips contextuales por tab + partida activa
        if hasattr(self, '_tuxia') and self._partida_actual_id:
            QTimer.singleShot(200, lambda i=idx: self._tuxia_check_tab(i))

    def _tuxia_check_tab(self, idx: int):
        """Tips inteligentes cuando se cambia de tab con contenido vacío."""
        if not hasattr(self, '_tuxia') or not self._partida_actual_id:
            return
        part_id = self._partida_actual_id
        # idx: 0=ACU, 1=Insumos, 2=Metrados, 3=Specs, 4=Resumen
        try:
            conn = get_db()
            if idx == 2:  # Metrados
                n_met = conn.execute(
                    "SELECT COUNT(*) FROM metrados_detalle WHERE partida_id=?",
                    (part_id,)
                ).fetchone()[0]
                try:
                    n_acero = conn.execute(
                        "SELECT COUNT(*) FROM acero_detalle WHERE partida_id=?",
                        (part_id,)
                    ).fetchone()[0]
                except Exception:
                    n_acero = 0
                conn.close()
                if n_met == 0 and n_acero == 0 and self._ed_presupuesto:
                    self._tuxia.show_tip(
                        "No hay planilla cargada para esta partida. Cárgala "
                        "fila por fila (largo × ancho × alto), o usa el chat "
                        "para que la IA te sugiera la fórmula geométrica.",
                        titulo="tuxia · planilla vacía",
                        key=f"tip_metrados_vacios:{part_id}",
                        fade_ms=8000,
                    )
                return
            if idx == 3:  # Especificaciones
                p = conn.execute(
                    "SELECT especificaciones FROM partidas WHERE id=?",
                    (part_id,)
                ).fetchone()
                conn.close()
                spec_vacio = not (p and (p['especificaciones'] or '').strip())
                if spec_vacio and self._ed_specs:
                    self._tuxia.show_tip(
                        "Esta partida no tiene especificaciones técnicas. "
                        "Puedo redactártelas con IA en base a la descripción "
                        "y el ACU.",
                        accion_id=f'generar_specs:{part_id}',
                        accion_label="Generar con IA",
                        titulo="tuxia · sin specs",
                        key=f"tip_specs_vacio:{part_id}",
                        fade_ms=10000,
                    )
                return
            conn.close()
        except Exception:
            try: conn.close()
            except Exception: pass

    def _buscar_partida(self, texto: str):
        from utils.formatting import norm_busqueda
        texto = norm_busqueda(texto.strip())
        for i in range(self.tree.topLevelItemCount()):
            self._filtrar_item(self.tree.topLevelItem(i), texto)

    def _filtrar_item(self, item, texto, padre_visible=False):
        from utils.formatting import norm_busqueda
        match = not texto or texto in norm_busqueda(item.text(0) + item.text(1))
        es_titulo = bool(item.data(0, Qt.UserRole + 1))
        mostrar_hijos = padre_visible or (match and es_titulo)
        item.setHidden(not match and not padre_visible)
        for c in range(item.childCount()):
            self._filtrar_item(item.child(c), texto, mostrar_hijos)
            if not item.child(c).isHidden():
                item.setHidden(False)
        if match and es_titulo:
            item.setExpanded(True)

    # ══════════════════════════════════════════════════════════════════════════
    # CRUD Partidas
    # ══════════════════════════════════════════════════════════════════════════

    def _menu_partida(self, pos):
        item = self.tree.itemAt(pos)
        menu = QMenu(self)
        seleccionados = self.tree.selectedItems()
        n_sel = len([it for it in seleccionados if it.data(0, Qt.UserRole)])

        from utils.i18n import tr
        menu.addAction(tr("Agregar partida"),  self._nueva_partida)
        menu.addAction(tr("Agregar título"),   self._nuevo_titulo)
        # Pegar siempre visible si hay clipboard
        if _pclip.hay_clipboard():
            menu.addSeparator()
            menu.addAction(
                f"Pegar partidas — {_pclip.descripcion_clipboard()}\tCtrl+V",
                lambda: self._pegar_partidas_clipboard()
            )
        if item:
            menu.addSeparator()
            pid = item.data(0, Qt.UserRole)
            if n_sel <= 1:
                menu.addAction(tr("Editar"),    lambda: self._editar_partida(pid))
                menu.addAction(tr("Duplicar"),  lambda: self._duplicar_partida(pid))
                menu.addSeparator()
                menu.addAction(tr("Copiar") + "\tCtrl+C", lambda: self._copiar_partidas_seleccionadas())
                sub_caso = menu.addMenu(tr("Cambiar texto") + "…")
                sub_caso.setStyleSheet(menu.styleSheet())
                sub_caso.addAction("UPPERCASE",            lambda: self._cambiar_caso(pid, str.upper))
                sub_caso.addAction("lowercase",            lambda: self._cambiar_caso(pid, str.lower))
                sub_caso.addAction("Title Case",           lambda: self._cambiar_caso(pid, str.title))
                menu.addSeparator()
                menu.addAction(tr("Eliminar"), lambda: self._eliminar_partida(pid, item.text(1)))
            else:
                ids = [(it.data(0, Qt.UserRole), it.text(1))
                       for it in seleccionados if it.data(0, Qt.UserRole)]
                menu.addAction(
                    f"Copiar {n_sel} partidas\tCtrl+C",
                    lambda: self._copiar_partidas_seleccionadas()
                )
                menu.addAction(
                    f"Eliminar {n_sel} partidas seleccionadas",
                    lambda: self._eliminar_partidas_multiple(ids)
                )
        menu.exec(self.tree.mapToGlobal(pos))

    def _copiar_partidas_seleccionadas(self):
        """Copia las partidas seleccionadas del árbol al clipboard global.
        Si una raíz seleccionada es título, trae también el subárbol completo.
        Filtra raíces redundantes (si la madre y la hija están seleccionadas,
        solo cuenta la madre).
        """
        seleccionados = self.tree.selectedItems()
        ids = [it.data(0, Qt.UserRole) for it in seleccionados
               if it.data(0, Qt.UserRole)]
        if not ids:
            QMessageBox.information(self, "Copiar partidas",
                                    "Selecciona al menos una partida en el árbol.")
            return
        conn = get_db()
        # Filtrar redundancias: si un ítem está bajo otro ya seleccionado,
        # quitarlo. Comparamos por prefijo de item.
        rows = conn.execute(
            "SELECT id, item FROM partidas WHERE id IN ({})".format(
                ','.join('?' * len(ids))), ids
        ).fetchall()
        items_por_id = {r['id']: r['item'] for r in rows}
        items_sel = list(items_por_id.values())
        ids_top: list[int] = []
        for r in rows:
            it = r['item'] or ''
            es_descendiente = any(
                it != otro and it.startswith(otro + '.') for otro in items_sel
            )
            if not es_descendiente:
                ids_top.append(r['id'])

        n = _pclip.copiar(conn, ids_top, self.pid)
        conn.close()
        if n == 0:
            return
        # Indicación visual ligera en la barra de estado
        win = self.window()
        if hasattr(win, 'statusBar') and win.statusBar():
            win.statusBar().showMessage(
                f"Copiadas {n} partida(s) — usa Ctrl+V para pegar", 4000
            )

    def _pegar_partidas_clipboard(self):
        """Pega el contenido del clipboard según la selección actual:
        - Título seleccionado → pega como hijas dentro del título
        - Partida seleccionada → pega como hermanas al mismo nivel
        - Sin selección → pega como raíces al final
        """
        if not self._require_editable("pegar partidas"):
            return
        if not _pclip.hay_clipboard():
            QMessageBox.information(self, "Pegar partidas",
                                    "El portapapeles de partidas está vacío.")
            return
        ctx_item, ctx_es_titulo = self._contexto_seleccion()
        conn = get_db()
        try:
            nuevos = _pclip.pegar(conn, self.pid, self._sub_ppto_id,
                                  contexto_item=ctx_item,
                                  contexto_es_titulo=ctx_es_titulo)
            conn.commit()
        except Exception as e:
            conn.rollback()
            conn.close()
            QMessageBox.critical(self, "Pegar partidas",
                                 f"Error al pegar:\n{e}")
            return
        conn.close()
        self.recargar_partidas()
        self.tree._renumerar()
        self.actualizar_total()
        win = self.window()
        if hasattr(win, 'statusBar') and win.statusBar():
            if ctx_item and ctx_es_titulo:
                donde = f"dentro de {ctx_item}"
            elif ctx_item:
                donde = f"junto a {ctx_item}"
            else:
                donde = "al final del presupuesto"
            win.statusBar().showMessage(
                f"Pegadas {len(nuevos)} raíz(es) {donde}.", 4000
            )

    def _mover_arriba(self):
        if not self._require_editable("mover partidas"):
            return
        self._mover_item(-1)

    def _mover_abajo(self):
        if not self._require_editable("mover partidas"):
            return
        self._mover_item(1)

    def _seleccion_nivel(self) -> list:
        """Ítems seleccionados en ORDEN VISUAL para subir/bajar nivel.
        Excluye los que ya son descendientes de otro seleccionado (esos se
        mueven junto con su padre). Sin selección → el ítem actual."""
        sel = self.tree.selectedItems()
        if not sel:
            it = self.tree.currentItem()
            return [it] if it else []
        sel_set = set(sel)
        from PySide6.QtWidgets import QTreeWidgetItemIterator
        out = []
        it = QTreeWidgetItemIterator(self.tree)
        while it.value():
            w = it.value()
            if w in sel_set:
                p = w.parent()
                dentro = False
                while p is not None:
                    if p in sel_set:
                        dentro = True
                        break
                    p = p.parent()
                if not dentro:
                    out.append(w)
            it += 1
        return out

    def _restaurar_seleccion_nivel(self, items: list):
        """Re-selecciona los ítems movidos (setCurrentItem limpia la selección)."""
        self.tree.setCurrentItem(items[-1])
        for it in items:
            it.setSelected(True)

    def _subir_nivel(self):
        """← Saca la selección del padre: cada ítem pasa a hermano de su padre
        (un nivel arriba). Con varias partidas, todas suben manteniendo orden."""
        if not self._require_editable("reorganizar partidas"):
            return
        items = [it for it in self._seleccion_nivel() if it.parent() is not None]
        if not items:
            return
        # En orden inverso: cada uno se inserta justo después de su padre,
        # así el grupo queda en el orden original.
        for it in reversed(items):
            padre = it.parent()
            abuelo = padre.parent() or self.tree.invisibleRootItem()
            idx_padre = abuelo.indexOfChild(padre)
            padre.takeChild(padre.indexOfChild(it))
            abuelo.insertChild(idx_padre + 1, it)
        self._restaurar_seleccion_nivel(items)
        self.tree._renumerar()

    def _bajar_nivel(self):
        """→ Anida la selección dentro del hermano anterior del PRIMER ítem
        seleccionado. Con varias partidas, TODAS quedan al mismo nivel como
        hijas de ese hermano, en su orden original."""
        if not self._require_editable("reorganizar partidas"):
            return
        items = self._seleccion_nivel()
        if not items:
            return
        primero = items[0]
        padre = primero.parent() or self.tree.invisibleRootItem()
        idx = padre.indexOfChild(primero)
        if idx == 0:
            return  # no hay hermano anterior donde anidar
        destino = padre.child(idx - 1)
        if destino in items:
            return  # defensa: no anidar dentro de la propia selección
        for it in items:
            p = it.parent() or self.tree.invisibleRootItem()
            p.takeChild(p.indexOfChild(it))
            destino.addChild(it)
        destino.setExpanded(True)
        self._restaurar_seleccion_nivel(items)
        self.tree._renumerar()

    def _mover_item(self, direccion: int):
        """Mueve el ítem seleccionado hacia arriba (-1) o abajo (+1) entre sus hermanos."""
        item = self.tree.currentItem()
        if not item:
            return
        parent = item.parent() or self.tree.invisibleRootItem()
        idx = parent.indexOfChild(item)
        nuevo_idx = idx + direccion
        if nuevo_idx < 0 or nuevo_idx >= parent.childCount():
            return
        parent.takeChild(idx)
        parent.insertChild(nuevo_idx, item)
        self.tree.setCurrentItem(item)
        self.tree._renumerar()
        # Actualizar parcial visible del ítem movido
        if item.data(0, Qt.UserRole) and not item.data(0, Qt.UserRole + 1):
            self.actualizar_total()

    def _cambiar_caso(self, part_id: int, fn):
        if not self._require_editable("cambiar el texto"):
            return
        conn = get_db()
        row = conn.execute("SELECT descripcion FROM partidas WHERE id=?", (part_id,)).fetchone()
        if not row:
            conn.close()
            return
        nueva = fn(row['descripcion'] or '')
        conn.execute("UPDATE partidas SET descripcion=? WHERE id=?", (nueva, part_id))
        conn.commit()
        conn.close()
        if part_id in self._id_to_item:
            self._id_to_item[part_id].setText(1, nueva)

    def _contexto_seleccion(self) -> tuple[str | None, bool]:
        """Retorna (item_codigo, es_titulo) del ítem REALMENTE seleccionado.

        Usa selectedItems() y no currentItem(): Qt marca un ítem como "actual"
        al recuperar el foco aunque el usuario no lo haya seleccionado (selección
        fantasma). Sin selección real → (None, False) y la nueva partida cuelga
        del último título.
        """
        sel = self.tree.selectedItems()
        tw = sel[0] if sel else None
        if tw:
            return tw.text(0) or None, bool(tw.data(0, Qt.UserRole + 1))
        return None, False

    def _nueva_partida(self):
        if not self._require_editable("agregar partidas"):
            return
        from views.agregar_partida_dialog import AgregarPartidaDialog
        ctx_item, ctx_es_titulo = self._contexto_seleccion()
        dlg = AgregarPartidaDialog(
            self.pid, self.usuario,
            tab_inicial=0,
            contexto_item=ctx_item,
            contexto_es_titulo=ctx_es_titulo,
            sub_presupuesto_id=self._sub_ppto_id,
            parent=self
        )
        dlg.partidas_agregadas.connect(self._on_partidas_agregadas)
        dlg.exec()

    def _nuevo_titulo(self):
        if not self._require_editable("agregar títulos"):
            return
        from views.agregar_titulo_dialog import AgregarTituloDialog
        ctx_item, ctx_es_titulo = self._contexto_seleccion()
        dlg = AgregarTituloDialog(
            self.pid, self.usuario,
            contexto_item=ctx_item,
            contexto_es_titulo=ctx_es_titulo,
            sub_presupuesto_id=self._sub_ppto_id,
            parent=self
        )
        dlg.partidas_agregadas.connect(self._on_partidas_agregadas)
        dlg.exec()

    def _on_partidas_agregadas(self):
        self.recargar_partidas()
        # Sin selección tras agregar → la próxima partida cuelga del ÚLTIMO título
        # (evita que quede "pegada" al primer título por una selección fantasma).
        self.tree.blockSignals(True)
        self.tree.clearSelection()
        self.tree.setCurrentItem(None)
        self.tree.blockSignals(False)
        self.cargar_insumos()
        self.actualizar_total()

    def _on_tree_doble_clic(self, item, col):
        """Doble clic en el árbol → editar la fila.
        - Títulos/subtítulos: en cualquier columna.
        - Partidas normales: SOLO sobre la Descripción (col 1), para no
          chocar con el editor inline del metrado (col 3, un clic)."""
        pid = item.data(0, Qt.UserRole)
        if not pid:
            return
        conn = get_db()
        row = conn.execute(
            "SELECT es_titulo FROM partidas WHERE id=?", (pid,)
        ).fetchone()
        conn.close()
        if not row:
            return
        if row['es_titulo'] or col == 1:
            self._editar_partida(pid)

    def _editar_partida(self, part_id: int):
        if not self._require_editable("editar partidas"):
            return
        from views.partida_form_dialog import PartidaFormDialog
        dlg = PartidaFormDialog(self.pid, part_id, self.usuario, parent=self)
        if dlg.exec():
            self.recargar_partidas()
            if self._partida_actual_id == part_id:
                self.cargar_acu(part_id)

    def _duplicar_partida(self, part_id: int):
        if not self._require_editable("duplicar partidas"):
            return
        conn = get_db()
        orig = conn.execute("SELECT * FROM partidas WHERE id=?", (part_id,)).fetchone()
        if not orig:
            conn.close()
            return
        cur = conn.execute(
            """INSERT INTO partidas (proyecto_id, item, descripcion, unidad, metrado,
               precio_unitario, nivel, es_titulo, especificaciones, rendimiento, grupo,
               sub_presupuesto_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (self.pid, orig['item']+'.x', orig['descripcion'], orig['unidad'] or '',
             orig['metrado'] or 0, orig['precio_unitario'] or 0, orig['nivel'] or 1,
             orig['es_titulo'] or 0, orig['especificaciones'] or '',
             orig['rendimiento'] or 1, orig['grupo'] or '',
             self._sub_ppto_id)
        )
        new_id = cur.lastrowid
        for ai in conn.execute("SELECT * FROM acu_items WHERE partida_id=?", (part_id,)).fetchall():
            conn.execute(
                "INSERT INTO acu_items (partida_id, recurso_id, cuadrilla, cantidad, precio)"
                " VALUES (?,?,?,?,?)",
                (new_id, ai['recurso_id'], ai['cuadrilla'], ai['cantidad'], ai['precio'])
            )
        conn.commit()
        conn.close()
        self.recargar_partidas()

    # ── Wrappers para atajos de teclado ──────────────────────────────────────

    def _duplicar_actual(self):
        """Ctrl+D — duplica la partida seleccionada en el árbol."""
        item = self.tree.currentItem()
        if not item:
            return
        pid = item.data(0, Qt.UserRole)
        if pid:
            self._duplicar_partida(pid)

    def _editar_partida_actual(self):
        """F2 — abre el diálogo de edición de la partida seleccionada."""
        item = self.tree.currentItem()
        if not item:
            return
        pid = item.data(0, Qt.UserRole)
        if pid:
            self._editar_partida(pid)

    def _cortar_partidas_seleccionadas(self):
        """Ctrl+X — copia las partidas seleccionadas al portapapeles y las elimina."""
        items = self.tree.selectedItems()
        if not items:
            return
        self._copiar_partidas_seleccionadas()
        self._supr_partida_seleccionada()

    def _focus_buscar(self):
        """Ctrl+F — enfoca el buscador del topbar y selecciona su texto."""
        if hasattr(self, 'inp_buscar'):
            self.inp_buscar.setFocus()
            self.inp_buscar.selectAll()

    def _ir_a_primera(self):
        """Ctrl+Home — navega al primer ítem del árbol."""
        if self.tree.topLevelItemCount() > 0:
            item = self.tree.topLevelItem(0)
            self.tree.setCurrentItem(item)
            self.tree.scrollToItem(item)

    def _ir_a_ultima(self):
        """Ctrl+End — navega al último descendiente visible del árbol."""
        n = self.tree.topLevelItemCount()
        if n == 0:
            return
        item = self.tree.topLevelItem(n - 1)
        while item.childCount() > 0:
            item = item.child(item.childCount() - 1)
        self.tree.setCurrentItem(item)
        self.tree.scrollToItem(item)

    def _on_tree_click_metrado(self, item, col):
        """Clic en col Metrado (3) → activa edición inline."""
        if col != 3 or item.data(0, Qt.UserRole + 1):
            return
        self.tree.editItem(item, 3)

    def _navegar_metrado(self, direction: int):
        """Mueve la edición al siguiente/anterior metrado (↓/↑ desde el editor)."""
        # Recolectar todas las partidas visibles (no títulos) en orden de árbol
        items: list = []

        def _collect(parent):
            for i in range(parent.childCount()):
                child = parent.child(i)
                if not child.data(0, Qt.UserRole + 1):   # no es título
                    items.append(child)
                _collect(child)

        _collect(self.tree.invisibleRootItem())

        current = self.tree.currentItem()
        if current not in items:
            return
        new_idx = items.index(current) + direction
        if 0 <= new_idx < len(items):
            dest = items[new_idx]
            self.tree.setCurrentItem(dest)
            self.tree.scrollToItem(dest)
            QTimer.singleShot(0, lambda: self.tree.editItem(dest, 3))

    def _on_tree_metrado_cambiado(self, item, col):
        """Guarda el metrado editado inline en la BD y refresca el parcial."""
        if col != 3 or item.data(0, Qt.UserRole + 1):
            return
        # Bloqueo defensivo por estado: aunque NoEditTriggers esté activo, el
        # signal itemChanged se puede disparar desde código. Si el nivel
        # presupuesto no es editable, ignorar.
        if not self._ed_presupuesto:
            return
        part_id = item.data(0, Qt.UserRole)
        if not part_id:
            return
        try:
            met = float(item.text(3).replace(",", ".").strip())
        except ValueError:
            return
        conn = get_db()
        conn.execute("UPDATE partidas SET metrado=? WHERE id=?", (met, part_id))
        conn.commit()
        pu_row = conn.execute(
            "SELECT precio_unitario FROM partidas WHERE id=?", (part_id,)
        ).fetchone()
        conn.close()
        pu = (pu_row['precio_unitario'] or 0) if pu_row else 0
        self.tree.blockSignals(True)
        item.setText(3, f"{met:,.3f}")
        item.setText(5, fmt(_r2(met * pu), self._moneda))
        # Si tenía planilla (normal o de acero), borrarla y quitar el indicador ✓
        if part_id in getattr(self, '_con_planilla', set()):
            conn2 = get_db()
            conn2.execute("DELETE FROM metrados_detalle WHERE partida_id=?", (part_id,))
            conn2.execute("DELETE FROM acero_detalle WHERE partida_id=?", (part_id,))
            conn2.commit()
            conn2.close()
            self._con_planilla.discard(part_id)
            item.setData(1, Qt.UserRole, False)
            item.setData(3, Qt.UserRole, False)
            item.setToolTip(3, "")
        # Si la planilla de metrados (panel derecho) está mostrando ESTA partida,
        # limpiar sus tablas en memoria. El metrado manual descarta la planilla;
        # de no limpiarlas, `tbl_met`/`tbl_acero` conservan las filas viejas y el
        # guardado silencioso reescribiría el detalle y recalcularía el metrado
        # desde la planilla → sobrescribe el valor manual "después de un tiempo".
        # Con las tablas vacías, los guards `_met_tiene_datos()` /
        # `_acero_tiene_datos()` evitan el re-guardado.
        if getattr(self, '_met_panel_pid', None) == part_id:
            if hasattr(self, 'tbl_met'):
                self._met_loading = True
                self.tbl_met.setRowCount(0)
                self._met_loading = False
                self._met_dirty = False
            if hasattr(self, 'tbl_acero'):
                self._acero_loading = True
                self.tbl_acero.setRowCount(0)
                self._acero_loading = False
            if hasattr(self, 'lbl_met_total'):
                self.lbl_met_total.setText(f"{0:,.{get_decimales_metrado()}f}")
            self._metrado_nueva_fila()
        self.tree.blockSignals(False)
        self.actualizar_total()

    def _supr_partida_seleccionada(self):
        # Si el cronograma está activo y hay una flecha (dependencia)
        # seleccionada, eliminarla antes que cualquier otra acción.
        if (self._cron_view is not None
                and self._root_stack.currentWidget() is self._cron_view):
            try:
                gantt = getattr(self._cron_view, '_gantt_w', None)
                if gantt is not None and gantt._delete_selected_arrow_if_any():
                    return
            except Exception:
                pass
        # Usar focusWidget para detectar qué widget tiene el foco real
        from PySide6.QtWidgets import QApplication
        fw = QApplication.focusWidget()
        # Ignorar si el foco está en alguna tabla o su viewport
        for tbl in (self.tbl_met, self.tbl_acero, self.tbl_ins, self.tbl_acu):
            if fw is tbl or fw is tbl.viewport():
                if tbl is self.tbl_met:
                    self._met_eliminar_seleccionadas()
                elif tbl is self.tbl_acero:
                    self._acero_eliminar_seleccionadas()
                elif tbl is self.tbl_acu:
                    row = self.tbl_acu.currentRow()
                    if 0 <= row < len(self._acu_row_ids):
                        acu_id = self._acu_row_ids[row]
                        if acu_id != -1:
                            self._eliminar_acu_item(acu_id)
                return
        # Si el foco está en la tabla ACU, eliminar el ítem ACU seleccionado
        if self.tbl_acu.hasFocus():
            row = self.tbl_acu.currentRow()
            if 0 <= row < len(self._acu_row_ids):
                acu_id = self._acu_row_ids[row]
                if acu_id != -1:
                    self._eliminar_acu_item(acu_id)
            return

        # Recoger todos los ítems seleccionados en el árbol
        items = self.tree.selectedItems()
        if not items:
            return
        ids = [(it.data(0, Qt.UserRole), it.text(1))
               for it in items if it.data(0, Qt.UserRole)]
        if not ids:
            return

        if len(ids) == 1:
            self._eliminar_partida(ids[0][0], ids[0][1])
        else:
            self._eliminar_partidas_multiple(ids)

    def _eliminar_partidas_multiple(self, ids: list[tuple[int, str]]):
        """Elimina varias partidas a la vez tras confirmar."""
        from utils.i18n import tr
        if not self._require_editable("eliminar partidas"):
            return
        n = len(ids)
        msg = QMessageBox(self)
        msg.setWindowTitle("Eliminar partidas")
        msg.setText(
            f"¿Eliminar las {n} partidas seleccionadas?\n"
            "Esta acción no se puede deshacer."
        )
        msg.setIcon(QMessageBox.Icon.Warning)
        b_si = msg.addButton(f"Eliminar {n} partidas", QMessageBox.ButtonRole.AcceptRole)
        msg.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
        msg.exec()
        if msg.clickedButton() != b_si:
            return
        conn = get_db()
        for part_id, _ in ids:
            conn.execute("DELETE FROM partidas WHERE id=?", (part_id,))
            if self._partida_actual_id == part_id:
                self._partida_actual_id = None
                self.tbl_acu.setRowCount(0)
                self.lbl_acu_titulo.setText(tr("Seleccione una partida"))
        conn.commit()
        conn.close()
        self.recargar_partidas()
        self.tree._renumerar()   # recorre la numeración para cerrar los huecos
        self.actualizar_total()
        self.cargar_insumos()

    def _eliminar_partida(self, part_id: int, desc: str):
        from utils.i18n import tr
        if not self._require_editable("eliminar partidas"):
            return
        msg = QMessageBox(self)
        msg.setWindowTitle("Eliminar partida")
        msg.setText(f"¿Eliminar «{desc}»?\nEsta acción no se puede deshacer.")
        msg.setIcon(QMessageBox.Icon.Warning)
        b_si = msg.addButton("Eliminar", QMessageBox.ButtonRole.AcceptRole)
        msg.addButton("Cancelar",        QMessageBox.ButtonRole.RejectRole)
        msg.exec()
        if msg.clickedButton() != b_si:
            return
        conn = get_db()
        conn.execute("DELETE FROM partidas WHERE id=?", (part_id,))
        conn.commit()
        conn.close()
        if self._partida_actual_id == part_id:
            self._partida_actual_id = None
            self.tbl_acu.setRowCount(0)
            self.lbl_acu_titulo.setText(tr("Seleccione una partida"))
        self.recargar_partidas()
        self.tree._renumerar()   # recorre la numeración para cerrar los huecos
        self.actualizar_total()
        self.cargar_insumos()

    # ══════════════════════════════════════════════════════════════════════════
    # ACU — edición
    # ══════════════════════════════════════════════════════════════════════════

    # ── Navegación por teclado en ACU ─────────────────────────────────────────

    def _acu_key_press(self, event) -> bool:
        mods = event.modifiers()
        key  = event.key()

        if mods & Qt.ControlModifier:
            if key == Qt.Key_C:
                self._copiar_acu_seleccionados()
                return True
            if key == Qt.Key_V:
                self._pegar_acu()
                return True

        row = self.tbl_acu.currentRow()
        col = self.tbl_acu.currentColumn()
        COLS_ED = [3, 4, 5]

        if key in (Qt.Key_Return, Qt.Key_Enter):
            if self._es_celda_acu_editable(row, col):
                QTimer.singleShot(0, lambda: self.tbl_acu.edit(
                    self.tbl_acu.model().index(row, col)))
            else:
                self._acu_ir_a(row + 1, col if col in COLS_ED else 3)
            return True

        elif key == Qt.Key_Up:
            self._acu_ir_a(row - 1, col)
            return True

        elif key == Qt.Key_Down:
            self._acu_ir_a(row + 1, col)
            return True

        elif key == Qt.Key_Left:
            if col in COLS_ED:
                idx = COLS_ED.index(col)
                if idx > 0:
                    self._acu_ir_a(row, COLS_ED[idx - 1])
            return True

        elif key == Qt.Key_Right:
            if col in COLS_ED:
                idx = COLS_ED.index(col)
                if idx < len(COLS_ED) - 1:
                    self._acu_ir_a(row, COLS_ED[idx + 1])
            elif col not in COLS_ED:
                self._acu_ir_a(row, COLS_ED[0])
            return True

        elif key == Qt.Key_Tab:
            if col in COLS_ED:
                idx = COLS_ED.index(col)
                if idx < len(COLS_ED) - 1:
                    self._acu_ir_a(row, COLS_ED[idx + 1])
                else:
                    self._acu_ir_a(row + 1, COLS_ED[0])
            return True

        return False

    def _es_celda_acu_editable(self, row: int, col: int) -> bool:
        if col not in (3, 4, 5):
            return False
        if row < 0 or row >= len(self._acu_row_ids):
            return False
        if self._acu_row_ids[row] == -1:
            return False
        tipos = {3: {'MO'}, 4: {'MAT', 'EQ'}, 5: {'MO', 'MAT', 'EQ'}}
        it = self.tbl_acu.item(row, 0)
        return (it.text() if it else '') in tipos.get(col, set())

    def _acu_ir_a(self, row: int, col: int):
        """Mueve la selección a (row, col) saltando filas-cabecera."""
        n = self.tbl_acu.rowCount()
        dr = 1 if row >= self.tbl_acu.currentRow() else -1
        while 0 <= row < n:
            acu_id = self._acu_row_ids[row] if row < len(self._acu_row_ids) else -1
            if acu_id != -1:
                self.tbl_acu.setCurrentCell(row, col)
                return
            row += dr

    def _on_acu_cell_clicked(self, row, col):
        """Un clic en una celda editable abre el editor inline (no con Ctrl/Shift)."""
        # Bloqueo defensivo por estado: no abrir editor si el presupuesto
        # no es editable en este estado.
        if not self._ed_presupuesto:
            return
        from PySide6.QtWidgets import QApplication
        mods = QApplication.keyboardModifiers()
        if mods & (Qt.ControlModifier | Qt.ShiftModifier):
            return  # multi-selección, no editar
        if col not in (3, 4, 5):
            return
        if not hasattr(self, '_acu_row_ids') or row >= len(self._acu_row_ids):
            return
        if self._acu_row_ids[row] == -1:
            return
        if getattr(self, '_acu_partida_global', False):
            # Partida global: cantidad directa en todos los tipos, sin cuadrilla
            tipos_editables = {4: {'MO', 'MAT', 'EQ', 'SC'},
                               5: {'MO', 'MAT', 'EQ', 'SC'}}
        else:
            tipos_editables = {3: {'MO', 'EQ'}, 4: {'MAT', 'EQ'}, 5: {'MO', 'MAT', 'EQ'}}
        tipo_item = self.tbl_acu.item(row, 0)
        tipo = tipo_item.text() if tipo_item else ''
        if tipo not in tipos_editables.get(col, set()):
            return
        idx = self.tbl_acu.model().index(row, col)
        QTimer.singleShot(0, lambda: self.tbl_acu.edit(idx))

    def _editar_celda_acu(self, index):
        col = index.column()
        if col not in (3, 4, 5):
            return
        row = index.row()
        if row >= len(self._acu_row_ids):
            return
        acu_id = self._acu_row_ids[row]
        if acu_id == -1:
            return
        self.tbl_acu.edit(index)

    def _aplicar_cambio_acu(self, acu_id: int, col: int, valor: float):
        # Bloqueo defensivo: si el presupuesto no es editable, ignorar.
        if not self._ed_presupuesto:
            return
        conn = get_db()
        row_data = conn.execute(
            """SELECT ai.*, r.tipo, r.unidad, p.rendimiento, p.proyecto_id as proy_id,
                      p.unidad AS p_unidad
               FROM acu_items ai JOIN recursos r ON r.id=ai.recurso_id
               JOIN partidas p ON p.id=ai.partida_id WHERE ai.id=?""", (acu_id,)
        ).fetchone()
        if not row_data:
            conn.close()
            return
        part_id = row_data['partida_id']
        rend    = row_data['rendimiento'] or 1
        proy    = conn.execute("SELECT jornada_laboral FROM proyectos WHERE id=?",
                               (row_data['proy_id'],)).fetchone()
        jornada = (proy['jornada_laboral'] if proy else None) or 8

        if col == 3:   # cuadrilla
            # La cantidad se deriva de la cuadrilla para MO y equipo por hora (hh/hm):
            #   cant = cuadrilla / rendimiento × jornada
            # y para MO/EQ por día (día/jor), sin jornada:
            #   cant = cuadrilla / rendimiento
            # En partidas globales (glb/est/serv) la cantidad es directa.
            es_glb  = _partida_global(row_data['p_unidad'])
            por_dia = _recurso_por_dia(row_data['tipo'], row_data['unidad'])
            if not es_glb and (por_dia
                               or _recurso_por_hora(row_data['tipo'], row_data['unidad'])):
                cant = _rn(valor / (rend if rend > 0 else 1)
                           * (1 if por_dia else jornada), get_decimales_cant_acu())
                conn.execute("UPDATE acu_items SET cuadrilla=?, cantidad=? WHERE id=?",
                             (valor, cant, acu_id))
            else:
                conn.execute("UPDATE acu_items SET cuadrilla=? WHERE id=?", (valor, acu_id))
        elif col == 4:  # cantidad
            conn.execute("UPDATE acu_items SET cantidad=? WHERE id=?", (valor, acu_id))
        elif col == 5:  # precio — actualiza todo el recurso en el proyecto
            rid  = row_data['recurso_id']
            poid = row_data['proy_id']
            conn.execute(
                """UPDATE acu_items SET precio=? WHERE recurso_id=?
                   AND partida_id IN (SELECT id FROM partidas WHERE proyecto_id=?)""",
                (valor, rid, poid)
            )
            afectadas = conn.execute(
                """SELECT DISTINCT ai.partida_id FROM acu_items ai
                   JOIN partidas p ON p.id=ai.partida_id
                   WHERE ai.recurso_id=? AND p.proyecto_id=?""", (rid, poid)
            ).fetchall()
            for (pid_af,) in afectadas:
                _recalcular_pu(conn, pid_af)
            conn.commit(); conn.close()
            self.recargar_partidas()
            self.cargar_acu(part_id)
            self.cargar_insumos()
            return

        _recalcular_pu(conn, part_id)
        conn.commit(); conn.close()
        self.cargar_acu(part_id)
        self._actualizar_arbol_partida(part_id)
        self.actualizar_total()

    def _menu_acu(self, pos):
        menu = QMenu(self)

        # Opciones sobre el ítem bajo el cursor (si hay)
        row = self.tbl_acu.rowAt(pos.y())
        tiene_item = (0 <= row < len(self._acu_row_ids) and
                      self._acu_row_ids[row] != -1)
        from utils.i18n import tr
        if tiene_item:
            acu_id = self._acu_row_ids[row]
            menu.addAction(tr("Editar"), lambda: self._editar_recurso_de_acu(acu_id))
            menu.addSeparator()
            menu.addAction(tr("Eliminar"), lambda: self._eliminar_acu_item(acu_id))
            menu.addSeparator()

        menu.addAction(tr("Agregar recurso"), self._agregar_recurso)

        if tiene_item or self.tbl_acu.selectedIndexes():
            menu.addSeparator()
            menu.addAction(tr("Copiar") + "  Ctrl+C", self._copiar_acu_seleccionados)

        if self._acu_clipboard:
            n = len(self._acu_clipboard)
            menu.addAction(
                tr("Pegar") + f" ({n})  Ctrl+V",
                self._pegar_acu
            )

        menu.exec(self.tbl_acu.mapToGlobal(pos))

    def _eliminar_acu_item(self, acu_id: int):
        msg = QMessageBox(self)
        msg.setWindowTitle("Eliminar recurso")
        msg.setText("¿Eliminar este recurso del análisis de costos?")
        msg.setIcon(QMessageBox.Icon.Warning)
        b_si = msg.addButton("Eliminar", QMessageBox.ButtonRole.AcceptRole)
        msg.addButton("Cancelar",        QMessageBox.ButtonRole.RejectRole)
        msg.exec()
        if msg.clickedButton() != b_si:
            return
        conn = get_db()
        row = conn.execute("SELECT partida_id FROM acu_items WHERE id=?", (acu_id,)).fetchone()
        if not row:
            conn.close()
            return
        part_id = row['partida_id']
        conn.execute("DELETE FROM acu_items WHERE id=?", (acu_id,))
        _recalcular_pu(conn, part_id)
        conn.commit()
        conn.close()
        self.cargar_acu(part_id)
        self._actualizar_arbol_partida(part_id)
        self.actualizar_total()

    def _editar_recurso_de_acu(self, acu_id: int):
        """Abre el diálogo de edición del recurso asociado a un ítem ACU."""
        if not self._require_editable("editar insumos"):
            return
        conn = get_db()
        row = conn.execute(
            "SELECT recurso_id, partida_id FROM acu_items WHERE id=?", (acu_id,)
        ).fetchone()
        if not row:
            conn.close()
            return
        recurso_id = row['recurso_id']
        part_id    = row['partida_id']
        rec = conn.execute("SELECT * FROM recursos WHERE id=?", (recurso_id,)).fetchone()
        conn.close()
        if not rec:
            return
        dlg = _EditarRecursoDialog(dict(rec), self)
        if dlg.exec() != QDialog.Accepted:
            return
        datos = dlg.datos()
        conn = get_db()
        conn.execute(
            "UPDATE recursos SET descripcion=?, unidad=?, tipo=?, indice_inei=? WHERE id=?",
            (datos['descripcion'], datos['unidad'], datos['tipo'],
             datos['indice_inei'], recurso_id)
        )
        conn.commit()
        conn.close()
        self.cargar_acu(part_id)
        if self.tabs.currentIndex() == 1:
            self.cargar_insumos(self._ins_estado)

    def _actualizar_arbol_partida(self, part_id: int):
        """Actualiza P.U. y Parcial del ítem en el árbol después de un cambio en ACU."""
        if part_id not in self._id_to_item:
            return
        conn = get_db()
        p = conn.execute(
            "SELECT metrado, precio_unitario FROM partidas WHERE id=?", (part_id,)
        ).fetchone()
        conn.close()
        if not p:
            return
        tw      = self._id_to_item[part_id]
        pu      = p['precio_unitario'] or 0
        met     = p['metrado'] or 0
        dec     = get_decimales_ppto()
        parcial = parcial_wysiwyg(met, pu, dec)
        tw.setText(4, f"{pu:,.{dec}f}")
        tw.setText(5, fmt(parcial, self._moneda, dec))
        tw.setData(5, Qt.UserRole, float(parcial))
        # Recalcular totales de los títulos padres
        self._calcular_totales_titulos(self.tree.invisibleRootItem())

    def _copiar_acu_seleccionados(self):
        """Ctrl+C — copia los items ACU seleccionados al portapapeles interno."""
        filas = sorted({idx.row() for idx in self.tbl_acu.selectedIndexes()})
        items = []
        conn = get_db()
        for r in filas:
            if r >= len(self._acu_row_ids) or self._acu_row_ids[r] == -1:
                continue
            acu_id = self._acu_row_ids[r]
            row = conn.execute(
                "SELECT recurso_id, cuadrilla, cantidad, COALESCE(precio,0) as precio "
                "FROM acu_items WHERE id=?", (acu_id,)
            ).fetchone()
            if row:
                items.append(dict(row))
        conn.close()
        if items:
            self._acu_clipboard = items
            self._actualizar_lbl_clipboard()

    def _pegar_acu(self):
        """Ctrl+V — pega los items del portapapeles en la partida activa."""
        if not self._acu_clipboard:
            return
        if self._partida_actual_id is None:
            QMessageBox.information(self, "Pegar", "Seleccione una partida primero.")
            return
        conn = get_db()
        partida = conn.execute(
            "SELECT rendimiento, proyecto_id, unidad FROM partidas WHERE id=?",
            (self._partida_actual_id,)
        ).fetchone()
        if not partida:
            conn.close()
            return
        proy = conn.execute("SELECT jornada_laboral FROM proyectos WHERE id=?",
                            (partida['proyecto_id'],)).fetchone()
        jornada = (proy['jornada_laboral'] if proy else None) or 8
        rend    = partida['rendimiento'] or 1
        es_global = _partida_global(partida['unidad'])

        for it in self._acu_clipboard:
            rec = conn.execute("SELECT tipo, unidad FROM recursos WHERE id=?",
                               (it['recurso_id'],)).fetchone()
            if not rec:
                continue
            cuad = it['cuadrilla'] or 0
            cant = it['cantidad'] or 0
            if not es_global and cuad > 0:
                if _recurso_por_dia(rec['tipo'], rec['unidad']):
                    cant = cuad / rend
                elif _recurso_por_hora(rec['tipo'], rec['unidad']):
                    cant = cuad / rend * jornada
            # Un insumo = un precio por proyecto: si el recurso ya se usa
            # aquí, el pegado adopta ese precio (no el del origen).
            precio_ins = precio_recurso_en_proyecto(
                conn, partida['proyecto_id'], it['recurso_id'])
            if precio_ins is None:
                precio_ins = it['precio']
            conn.execute(
                "INSERT INTO acu_items (partida_id, recurso_id, cuadrilla, cantidad, precio) "
                "VALUES (?,?,?,?,?)",
                (self._partida_actual_id, it['recurso_id'], cuad, cant, precio_ins)
            )
        _recalcular_pu(conn, self._partida_actual_id)
        conn.commit()
        conn.close()
        self.cargar_acu(self._partida_actual_id)
        self._actualizar_arbol_partida(self._partida_actual_id)
        self.actualizar_total()
        self.cargar_insumos()

    def _actualizar_lbl_clipboard(self):
        n = len(self._acu_clipboard)
        if n == 0:
            self.lbl_acu_clipboard.setVisible(False)
        else:
            self.lbl_acu_clipboard.setText(
                f"📋  {n} insumo{'s' if n > 1 else ''} copiado{'s' if n > 1 else ''}"
            )
            self.lbl_acu_clipboard.setVisible(True)

    def _toggle_chat_acu(self, visible: bool):
        if visible:
            self.btn_toggle_chat.setText("✨ Asistente ▾")
            sizes = self._chat_splitter.sizes()
            total = sum(sizes) or 1
            if sizes[1] < 100:
                # Restaurar último ratio guardado o 0.35 por defecto
                from PySide6.QtCore import QSettings as _QS
                s = _QS("ingePresupuestos", "layout")
                ratio = float(s.value(f"chat_ratio_{self.pid}", 0.35) or 0.35)
                ratio = max(0.15, min(0.6, ratio))
                self._chat_splitter.setSizes([
                    int(total * (1 - ratio)), int(total * ratio)
                ])
            # Mientras el chat está abierto, ocultar el floating tuxia
            # (el chat ES la versión expandida del asistente).
            if hasattr(self, '_tuxia') and self._tuxia is not None:
                self._tuxia.setVisible(False)
        else:
            self.btn_toggle_chat.setText("✨ Asistente ▸")
            self._chat_splitter.setSizes([sum(self._chat_splitter.sizes()), 0])
            # Chat cerrado → re-mostrar el floating tuxia
            if hasattr(self, '_tuxia') and self._tuxia is not None:
                self._tuxia.setVisible(True)
                self._tuxia.reposicionar()

    def _on_root_stack_changed(self, idx: int):
        """Tuxia (icono flotante) solo se muestra en la vista principal.
        En cronograma se oculta porque el footer del Gantt ya tiene su
        botón "Ayúdame" con el icono de Tuxia (evita redundancia)."""
        if not hasattr(self, '_tuxia') or self._tuxia is None:
            return
        if idx == 0:
            self._tuxia.setVisible(True)
            self._tuxia.reposicionar()
        else:
            self._tuxia.setVisible(False)

    def _tuxia_check_cronograma(self):
        """Tips contextuales al entrar al cronograma. Detecta el estado del
        cronograma y muestra el tip más relevante: bienvenida para principiantes,
        ayuda para auto-programar, tipos de dependencias avanzadas, etc."""
        if not hasattr(self, '_tuxia') or self._tuxia is None:
            return

        cmap = getattr(self, '_cron_map', {}) or {}
        tareas_con_dur = sum(1 for d in cmap.values()
                              if (d.get('duracion') or 0) > 0)
        tareas_con_pred = sum(1 for d in cmap.values()
                               if (d.get('predecesoras') or '').strip())
        n_partidas = sum(1 for p in (self._partidas or [])
                          if not p.get('es_titulo'))

        # 1. Bienvenida — primera vez en cronograma de cualquier proyecto
        if tareas_con_dur == 0:
            self._tuxia.show_tip(
                "<b>¡Bienvenido al Diagrama de Gantt!</b><br><br>"
                "Aquí planificas <b>cuándo</b> se ejecuta cada partida. Cada "
                "barra horizontal representa una tarea en el tiempo.<br><br>"
                "<b>Para empezar:</b><br>"
                "1️⃣ Click en <b>Calcular duración</b> — usa metrado/rendimiento<br>"
                "2️⃣ Click en <b>Auto-programar ▾ → Por fases</b> — agrupa "
                "automáticamente (preliminares → estructuras → acabados)<br>"
                "3️⃣ Ajusta arrastrando las barras o editando las celdas<br><br>"
                "Si necesitas ayuda, ¡pregúntame por chat!",
                titulo="tuxia · cómo empezar tu cronograma",
                key="cronograma_bienvenida",
                once_per_session=True, fade_ms=600,
            )
            return

        # 2. Tiene duraciones pero NO predecesoras → enseñar conexiones
        if tareas_con_pred == 0 and tareas_con_dur > 0:
            self._tuxia.show_tip(
                "Veo que tus tareas ya tienen duración pero <b>todas arrancan "
                "el día 1</b>. En la realidad, unas necesitan terminar antes "
                "que otras (no puedes pintar antes de tarrajear).<br><br>"
                "<b>Cómo conectar tareas:</b><br>"
                "• Escribe en la columna <b>Pred.</b> el número de la tarea "
                "anterior (ej. <b>5</b> = empezar cuando termine la #5)<br>"
                "• O usa <b>Auto-programar ▾ → Con IA</b> y la IA detecta el "
                "orden constructivo correcto<br><br>"
                "Las tareas que no se pueden retrasar sin atrasar el proyecto "
                "se pintan en <b style='color:#C6262E'>rojo</b> (ruta crítica).",
                titulo="tuxia · conecta tus tareas",
                key="cronograma_predecesoras_intro",
                once_per_session=True, fade_ms=600,
            )
            return

        # 3. Ya tiene un cronograma básico → tipos avanzados FS/SS/FF/SF
        self._tuxia.show_tip(
            "Tu cronograma ya está armado. Si quieres mayor control, las "
            "<b>predecesoras soportan los 4 tipos de MS Project</b>:<br><br>"
            "• <b>5</b> → FS (default): empieza cuando 5 termina<br>"
            "• <b>5+3</b> → FS con 3 días de lag (esperar 3 días)<br>"
            "• <b>5SS+2</b> → SS: misma fecha de inicio + lag<br>"
            "• <b>5FF-1</b> → FF: misma fecha de fin (lead negativo)<br>"
            "• <b>5SF</b> → SF: raro, termina cuando 5 inicia<br><br>"
            "Tip: usa <b>Ctrl+rueda</b> para zoom horizontal y <b>F1</b> "
            "para ver todos los atajos.",
            titulo="tuxia · dependencias avanzadas (FS/SS/FF/SF)",
            key="cronograma_dependencias_avanzadas",
            once_per_session=True, fade_ms=600,
        )

    def _restaurar_chat_ratio(self, ratio: float):
        sizes = self._chat_splitter.sizes()
        total = sum(sizes) or 1
        ratio = max(0.15, min(0.6, ratio))
        self._chat_splitter.setSizes([
            int(total * (1 - ratio)), int(total * ratio)
        ])

    def _guardar_chat_ratio(self, *_):
        sizes = self._chat_splitter.sizes()
        total = sum(sizes)
        if total <= 0 or sizes[1] <= 0:
            return
        ratio = sizes[1] / total
        from PySide6.QtCore import QSettings as _QS
        s = _QS("ingePresupuestos", "layout")
        s.setValue(f"chat_ratio_{self.pid}", round(ratio, 3))

    def _agregar_recurso(self):
        if not self._require_editable("agregar insumos al ACU"):
            return
        if self._partida_actual_id is None:
            QMessageBox.information(self, "ACU", "Seleccione una partida primero.")
            return
        from views.recurso_selector_dialog import RecursoSelectorDialog
        dlg = RecursoSelectorDialog(self._partida_actual_id, self._proy, parent=self)
        if dlg.exec():
            self.cargar_acu(self._partida_actual_id)
            self.recargar_partidas()
            self.cargar_insumos()

    def _guardar_en_biblioteca(self):
        if self._partida_actual_id is None:
            QMessageBox.information(self, "Biblioteca", "Seleccione una partida primero.")
            return
        conn = get_db()
        p = conn.execute("SELECT * FROM partidas WHERE id=?",
                         (self._partida_actual_id,)).fetchone()
        if not p or p['es_titulo']:
            conn.close()
            QMessageBox.warning(self, "Biblioteca", "Los títulos no se guardan en la biblioteca.")
            return

        existe = conn.execute(
            "SELECT id, grupo FROM biblioteca_cu WHERE descripcion=?", (p['descripcion'],)
        ).fetchone()

        # Grupos del catálogo base (seed): no se deben sobrescribir a la ligera.
        GRUPOS_SEED = {'INGEPRESUPUESTOS', 'LLAMKASUN', 'CAPECO'}

        modo = 'nuevo'   # por defecto cuando no existe ninguna con ese nombre
        if existe:
            grupo_exist = (existe['grupo'] or '').strip().upper()
            es_seed = grupo_exist in GRUPOS_SEED
            box = QMessageBox(self)
            box.setWindowTitle("Guardar en biblioteca")
            box.setIcon(QMessageBox.Question)
            if es_seed:
                box.setText(
                    f'«{p["descripcion"]}» ya existe en la biblioteca '
                    f'(grupo {grupo_exist}, del catálogo base).'
                )
                box.setInformativeText(
                    "Para no alterar el catálogo base, se recomienda guardarla "
                    "como copia nueva en «MIS PARTIDAS»."
                )
            else:
                box.setText(f'«{p["descripcion"]}» ya existe en la biblioteca.')
                box.setInformativeText(
                    "¿Actualizar la existente o guardar una copia nueva?"
                )
            btn_upd    = box.addButton("Actualizar existente",     QMessageBox.AcceptRole)
            btn_new    = box.addButton("Guardar como copia nueva", QMessageBox.ActionRole)
            btn_cancel = box.addButton("Cancelar",                 QMessageBox.RejectRole)
            box.setDefaultButton(btn_new if es_seed else btn_upd)
            box.exec()
            clicked = box.clickedButton()
            if clicked is btn_cancel:
                conn.close()
                return
            modo = 'actualizar' if clicked is btn_upd else 'nuevo'

        if existe and modo == 'actualizar':
            cu_id = existe['id']
            conn.execute(
                "UPDATE biblioteca_cu SET unidad=?, rendimiento=?, costo_unitario=? WHERE id=?",
                (p['unidad'], p['rendimiento'], p['precio_unitario'], cu_id)
            )
            msg = f'"{p["descripcion"]}" actualizado en la Biblioteca.'
        else:
            # Copia nueva (ya existía y eligió copiar) o primera vez que se guarda.
            # La copia siempre va a MIS PARTIDAS para no contaminar el catálogo base.
            grupo_nuevo = 'MIS PARTIDAS' if existe else (p['grupo'] or 'MIS PARTIDAS')
            cur = conn.execute(
                "INSERT INTO biblioteca_cu "
                "(descripcion, unidad, rendimiento, costo_unitario, grupo) VALUES (?,?,?,?,?)",
                (p['descripcion'], p['unidad'], p['rendimiento'],
                 p['precio_unitario'], grupo_nuevo)
            )
            cu_id = cur.lastrowid
            msg = (f'"{p["descripcion"]}" guardado como copia nueva en MIS PARTIDAS.'
                   if existe else f'"{p["descripcion"]}" guardado en la Biblioteca.')

        # Reemplazar ACU items en biblioteca (con precio efectivo del proyecto)
        conn.execute("DELETE FROM biblioteca_acu_items WHERE cu_id=?", (cu_id,))
        acu_items = conn.execute(
            "SELECT a.recurso_id, a.cuadrilla, a.cantidad, "
            "       COALESCE(a.precio, r.precio) AS precio "
            "FROM acu_items a JOIN recursos r ON r.id = a.recurso_id "
            "WHERE a.partida_id=?", (self._partida_actual_id,)
        ).fetchall()
        for it in acu_items:
            conn.execute(
                "INSERT INTO biblioteca_acu_items (cu_id, recurso_id, cuadrilla, cantidad, precio) "
                "VALUES (?,?,?,?,?)",
                (cu_id, it['recurso_id'], it['cuadrilla'], it['cantidad'], it['precio'])
            )
        conn.commit()
        conn.close()

        btn = getattr(self, '_btn_bib', None)
        if btn:
            btn.setText("✓ Guardado")
            btn.setStyleSheet(
                "QPushButton { background:#0F5132; color:white; border:none; border-radius:4px;"
                " padding:0 10px; font-size:10px; font-weight:600; }"
            )
            QTimer.singleShot(2500, lambda: (
                btn.setText("Guardar"),
                btn.setStyleSheet(
                    f"QPushButton {{ background:{GREEN_500}; color:white; border:none; border-radius:4px;"
                    f" padding:0 10px; font-size:10px; font-weight:600; }}"
                    f"QPushButton:hover {{ background:#5a9e1e; }}"
                )
            ))

        QMessageBox.information(self, "Biblioteca", msg)

    # ══════════════════════════════════════════════════════════════════════════
    # Rendimiento
    # ══════════════════════════════════════════════════════════════════════════

    def _guardar_rendimiento(self):
        if self._partida_actual_id is None:
            return
        if not self._ed_presupuesto:
            return
        try:
            rend = float(self.inp_rend.text().replace(',', '.'))
            if rend <= 0:
                rend = 1.0
        except ValueError:
            rend = 1.0
        conn = get_db()
        conn.execute("UPDATE partidas SET rendimiento=? WHERE id=?",
                     (rend, self._partida_actual_id))
        # En partidas globales (glb/est/serv) la cantidad es directa:
        # no recalcular al cambiar el rendimiento.
        if not getattr(self, '_acu_partida_global', False):
            proy = conn.execute("SELECT jornada_laboral FROM proyectos WHERE id=?", (self.pid,)).fetchone()
            jornada = (proy['jornada_laboral'] if proy else None) or 8
            # La cantidad derivada de la cuadrilla abarca MO y equipo por hora
            # (hh/hm) y MO/EQ por día (día/jor) — misma regla que al editar la
            # cuadrilla en _aplicar_cambio_acu. Solo se recalcula cuando hay
            # cuadrilla (>0); los insumos con cantidad directa (MAT, equipo-día
            # sin cuadrilla) conservan su valor.
            items = conn.execute(
                """SELECT ai.id, ai.cuadrilla, r.tipo, r.unidad FROM acu_items ai
                   JOIN recursos r ON r.id=ai.recurso_id
                   WHERE ai.partida_id=?""",
                (self._partida_actual_id,)
            ).fetchall()
            for it in items:
                cuad = it['cuadrilla'] or 0
                if cuad <= 0:
                    continue
                por_dia = _recurso_por_dia(it['tipo'], it['unidad'])
                if not (por_dia or _recurso_por_hora(it['tipo'], it['unidad'])):
                    continue
                # Por día (día/jor) → sin jornada: cant = cuadrilla / rend
                factor = 1 if por_dia else jornada
                conn.execute("UPDATE acu_items SET cantidad=? WHERE id=?",
                             (_rn(cuad / rend * factor,
                                  get_decimales_cant_acu()), it['id']))
        _recalcular_pu(conn, self._partida_actual_id)
        conn.commit()
        conn.close()
        self.cargar_acu(self._partida_actual_id)
        self.recargar_partidas()

    # ══════════════════════════════════════════════════════════════════════════
    # Metrados
    # ══════════════════════════════════════════════════════════════════════════

    # ── Toggle Metrados / Acero ───────────────────────────────────────────────

    def _toggle_met_modo(self, modo: str):
        self._met_modo = modo
        self.btn_modo_met.setStyleSheet(
            self._met_toggle_on if modo == 'met' else self._met_toggle_off)
        self.btn_modo_acero.setStyleSheet(
            self._met_toggle_on if modo == 'acero' else self._met_toggle_off)
        self._met_stack.setCurrentIndex(0 if modo == 'met' else 1)
        from utils.i18n import tr
        self.lbl_met_total_key.setText(tr("METRADO TOTAL:") if modo == 'met' else tr("TOTAL ACERO:"))
        if self._partida_actual_id:
            if modo == 'acero':
                self.cargar_acero(self._partida_actual_id)
            else:
                self.cargar_metrados(self._partida_actual_id)

    # ── Acero ─────────────────────────────────────────────────────────────────

    def _acero_ir_a(self, r: int, c: int):
        """Navega a la celda (r, c) de tbl_acero abriendo el editor."""
        tbl = self.tbl_acero
        if r >= tbl.rowCount():
            self._acero_nueva_fila_vacia()
        if r < 0:
            return
        if c == 2:
            cmb = tbl.cellWidget(r, 2)
            if cmb:
                tbl.setCurrentIndex(tbl.model().index(r, 2))
                QTimer.singleShot(0, cmb.setFocus)
        else:
            idx = tbl.model().index(r, c)
            tbl.setCurrentIndex(idx)
            QTimer.singleShot(0, lambda: tbl.edit(idx))

    def _acero_ultima_vacia(self) -> bool:
        """True si la última fila de tbl_acero está completamente vacía."""
        tbl = self.tbl_acero
        n   = tbl.rowCount()
        if n == 0:
            return False
        last = n - 1
        cmb  = tbl.cellWidget(last, 2)
        if cmb and cmb.currentIndex() > 0:
            return False
        return not any(tbl.item(last, c) and tbl.item(last, c).text().strip()
                       for c in (1, 3, 4, 5, 6, 8))

    def _acero_nueva_fila_vacia(self):
        if self._acero_ultima_vacia():
            return   # ya hay una fila vacía al final
        self._acero_loading = True
        self._acero_fila_insertar(self.tbl_acero.rowCount(), {})
        self._acero_loading = False

    def _acero_tiene_datos(self) -> bool:
        """True si la tabla acero tiene al menos una fila con datos reales."""
        tbl = self.tbl_acero
        for r in range(tbl.rowCount()):
            cmb = tbl.cellWidget(r, 2)
            if cmb and cmb.currentIndex() > 0:
                return True
            if any(tbl.item(r, c) and tbl.item(r, c).text().strip()
                   for c in (1, 3, 4, 5, 6, 8)):
                return True
        return False

    def _acero_guardar_silencioso(self):
        """Guarda acero en DB y actualiza árbol sin recargar todo."""
        # Escribir a la partida cargada en el panel, NO a la seleccionada en el
        # árbol: pueden diferir si se cambió de partida fuera del tab Metrados.
        pid = self._met_panel_pid
        if pid is None:
            return
        if not self._ed_presupuesto:
            return
        # No guardar si la tabla está vacía — evita borrar metrados existentes
        if not self._acero_tiene_datos():
            return
        tbl  = self.tbl_acero
        dec  = get_decimales_metrado()
        conn = get_db()
        # Exclusividad mutua: borrar metrados normales solo cuando hay datos reales de acero
        conn.execute("DELETE FROM metrados_detalle WHERE partida_id=?", (pid,))
        conn.execute("DELETE FROM acero_detalle WHERE partida_id=?",    (pid,))
        total_kg = 0.0
        orden = 0
        for r in range(tbl.rowCount()):
            cmb      = tbl.cellWidget(r, 2)
            diametro = _normalizar_diametro_acero(cmb.currentText()) if cmb else ''
            desc     = (tbl.item(r, 1).text() if tbl.item(r, 1) else '').strip()
            def _v(c, _r=r):
                it = tbl.item(_r, c)
                if it and it.text().strip():
                    try: return float(it.text().replace(',', '.'))
                    except: return None
                return None
            n_est = _v(3); n_el = _v(4); n_var = _v(5)
            llong = _v(6); kgml = _v(8)
            if not desc and not diametro and all(v is None for v in (n_est, n_el, n_var, llong)):
                continue
            dims    = [v for v in (n_est, n_el, n_var, llong) if v is not None]
            parc_m  = 1.0
            for d in dims: parc_m *= d
            parc_m  = round(parc_m, 4) if dims else 0.0
            parc_kg = round(parc_m * kgml, 4) if kgml else 0.0
            total_kg += parc_kg
            orden += 1
            conn.execute(
                """INSERT INTO acero_detalle
                   (partida_id, orden, descripcion, diametro,
                    n_estructuras, n_elementos, n_veces, longitud, kg_ml, parcial)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (pid, orden, desc, diametro,
                 n_est, n_el, n_var, llong, kgml, parc_kg)
            )
        total_kg = round(total_kg, dec)
        conn.execute("UPDATE partidas SET metrado=? WHERE id=?",
                     (total_kg, pid))
        conn.commit()
        conn.close()
        # Actualizar árbol sin recargar todo
        self.tree.blockSignals(True)
        self._con_planilla.add(pid)
        tw = self._id_to_item.get(pid)
        if tw:
            tw.setText(3, f"{total_kg:,.{dec}f}")
            tw.setData(3, Qt.UserRole, True)
            try: pu = float(tw.text(4).replace(',', ''))
            except: pu = 0.0
            parcial_tree = parcial_wysiwyg(total_kg, pu, dec)
            tw.setText(5, fmt(parcial_tree, self._moneda, dec))
            tw.setData(5, Qt.UserRole, float(parcial_tree))
        self.tree.blockSignals(False)
        self._calcular_totales_titulos(self.tree.invisibleRootItem())
        self.actualizar_total()

    # ── Copiar / Cortar / Pegar filas de acero ────────────────────────────────

    def _acero_filas_datos(self) -> list[dict]:
        tbl  = self.tbl_acero
        rows = sorted({idx.row() for idx in tbl.selectedIndexes()})
        result = []
        for r in rows:
            cmb = tbl.cellWidget(r, 2)
            def _v(c, _r=r):
                it = tbl.item(_r, c)
                if it and it.text().strip():
                    try: return float(it.text().replace(',', '.'))
                    except: return None
                return None
            result.append({
                'descripcion':   (tbl.item(r, 1).text() if tbl.item(r, 1) else '').strip(),
                'diametro':      _normalizar_diametro_acero(cmb.currentText()) if cmb else '',
                'n_estructuras': _v(3), 'n_elementos': _v(4), 'n_veces': _v(5),
                'longitud':      _v(6), 'kg_ml':       _v(8),
            })
        return result

    def _acero_copiar(self):
        datos = self._acero_filas_datos()
        if datos:
            _ACERO_CLIPBOARD[:] = datos
            from PySide6.QtWidgets import QToolTip
            from PySide6.QtGui import QCursor
            QToolTip.showText(QCursor.pos(), f"{len(datos)} fila(s) copiada(s)", self.tbl_acero)

    def _acero_cortar(self):
        rows  = sorted({idx.row() for idx in self.tbl_acero.selectedIndexes()}, reverse=True)
        datos = self._acero_filas_datos()
        if not datos: return
        _ACERO_CLIPBOARD[:] = datos
        self._acero_loading = True
        for r in rows:
            self.tbl_acero.removeRow(r)
        self._acero_actualizar_numeros()
        self._acero_loading = False
        self._acero_guardar_silencioso()

    def _acero_pegar(self):
        if not _ACERO_CLIPBOARD or self._met_panel_pid is None:
            return
        insert_at = max(0, self.tbl_acero.rowCount() - 1)
        self._acero_loading = True
        for i, datos in enumerate(_ACERO_CLIPBOARD):
            self._acero_fila_insertar(insert_at + i, datos)
        self._acero_actualizar_numeros()
        self._acero_loading = False
        self._acero_guardar_silencioso()

    def _acero_eliminar_seleccionadas(self):
        rows = sorted({idx.row() for idx in self.tbl_acero.selectedIndexes()}, reverse=True)
        if not rows: return
        self._acero_loading = True
        for r in rows:
            self.tbl_acero.removeRow(r)
        self._acero_actualizar_numeros()
        self._acero_loading = False
        if self.tbl_acero.rowCount() == 0:
            self._acero_nueva_fila_vacia()
        self._acero_guardar_silencioso()

    def _acero_menu_contextual(self, pos):
        from PySide6.QtWidgets import QMenu
        from utils.i18n import tr
        rows = {idx.row() for idx in self.tbl_acero.selectedIndexes()}
        n    = len(rows)
        menu = QMenu(self)
        if n:
            menu.addAction(f"{tr('Copiar')} {n}  Ctrl+C",  self._acero_copiar)
            menu.addAction(f"{tr('Cortar')} {n}  Ctrl+X",  self._acero_cortar)
            menu.addAction(f"{tr('Eliminar')} {n}  Del",   self._acero_eliminar_seleccionadas)
        if _ACERO_CLIPBOARD:
            menu.addSeparator()
            nc = len(_ACERO_CLIPBOARD)
            menu.addAction(f"{tr('Pegar')} ({nc})  Ctrl+V",  self._acero_pegar)
        if not menu.isEmpty():
            menu.exec(self.tbl_acero.viewport().mapToGlobal(pos))

    def _acero_fila_insertar(self, r: int, datos: dict):
        """Inserta una fila en tbl_acero con los datos dados."""
        tbl = self.tbl_acero
        tbl.insertRow(r)
        tbl.setRowHeight(r, 26)

        # Col 0: # (número de fila)
        it0 = QTableWidgetItem(str(r + 1))
        it0.setFlags(Qt.ItemIsEnabled)
        it0.setTextAlignment(Qt.AlignCenter)
        tbl.setItem(r, 0, it0)

        # Col 1: Descripción
        tbl.setItem(r, 1, QTableWidgetItem(datos.get('descripcion', '')))

        # Col 2: Diámetro — combo editable con autocompletado
        from PySide6.QtWidgets import QCompleter as _QComp
        cmb = QComboBox()
        cmb.setEditable(True)
        cmb.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        cmb.setMaxVisibleItems(14)
        # Popup styling cubierto por `install_global_popup_styles(app)`.
        # `combobox-popup: 0` fuerza el popup de lista redimensionable; sin esto
        # el desplegable hereda el ancho de la celda (70px) y recorta los
        # diámetros con fracción largos (ø1/2", ø1/4"…).
        cmb.setStyleSheet(
            "QComboBox { font-size:11px; border:none; padding:0 2px;"
            " background:transparent; color:#273445; combobox-popup:0; }"
            "QComboBox::drop-down { border:none; }"
        )
        cmb.addItem('')
        for d in _ACERO_DIAMS:
            cmb.addItem(f'ø{d}')
        # Ancho del desplegable independiente de la celda → texto completo.
        cmb.view().setMinimumWidth(120)
        diametro = str(datos.get('diametro', '') or '')
        if diametro:
            cmb.setCurrentText(f'ø{diametro}')
        else:
            cmb.setCurrentIndex(0)
        cmb.lineEdit().setPlaceholderText("ø…")
        # Completer con MatchContains
        _comp = _QComp([f'ø{d}' for d in _ACERO_DIAMS], cmb)
        _comp.setFilterMode(Qt.MatchContains)
        _comp.setCaseSensitivity(Qt.CaseInsensitive)
        _comp.setCompletionMode(_QComp.CompletionMode.PopupCompletion)
        _popup = _comp.popup()
        _popup.setMinimumWidth(130)
        _popup.setStyleSheet(
            "QListView { background:white; border:1px solid #D4D4D4; border-radius:6px;"
            " font-size:12px; padding:4px; outline:none; }"
            "QListView::item { padding:4px 10px; background:white; color:#273445; }"
            "QListView::item:hover { background:#FEF5EB; color:#C0621A; }"
            "QListView::item:selected { background:#FEF5EB; color:#C0621A; }"
        )
        from PySide6.QtGui import QPalette as _QPal
        _pal = _popup.palette()
        _pal.setColor(_QPal.ColorRole.Text, QColor('#273445'))
        _pal.setColor(_QPal.ColorRole.Base, QColor('white'))
        _pal.setColor(_QPal.ColorRole.Highlight, QColor('#FEF5EB'))
        _pal.setColor(_QPal.ColorRole.HighlightedText, QColor('#C0621A'))
        _popup.setPalette(_pal)
        cmb.setCompleter(_comp)
        # Señales: dropdown + completer + edición manual
        cmb.currentIndexChanged.connect(lambda _, c=cmb: self._acero_diametro_cambiado(c))
        _comp.activated.connect(lambda txt, c=cmb: (c.setCurrentText(txt),
                                                     self._acero_diametro_cambiado(c)))
        cmb.lineEdit().editingFinished.connect(lambda c=cmb: self._acero_diametro_cambiado(c))
        # Filtro Tab/Enter en combobox para navegación
        class _CmbNav(QObject):
            def eventFilter(s, obj, ev):
                if ev.type() != QEvent.Type.KeyPress: return False
                k = ev.key()
                if k in (Qt.Key_Tab, Qt.Key_Return, Qt.Key_Enter):
                    QTimer.singleShot(0, lambda: self._acero_ir_a(r, 3)); return True
                if k == Qt.Key_Backtab:
                    QTimer.singleShot(0, lambda: self._acero_ir_a(r, 1)); return True
                return False
        cmb._nav = _CmbNav(cmb)
        cmb.installEventFilter(cmb._nav)
        tbl.setCellWidget(r, 2, cmb)

        # Cols 3-6: numéricos (N°Estr, N°Elem, N°Var, Longitud)
        for c, key in [(3, 'n_estructuras'), (4, 'n_elementos'), (5, 'n_veces'), (6, 'longitud')]:
            val = datos.get(key)
            it = QTableWidgetItem(str(val) if val is not None else '')
            it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            tbl.setItem(r, c, it)

        # Col 7: Parc.(m) — solo lectura
        it7 = QTableWidgetItem('')
        it7.setFlags(it7.flags() & ~Qt.ItemIsEditable)
        it7.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        it7.setBackground(QColor(SILVER_100))
        tbl.setItem(r, 7, it7)

        # Col 8: kg/ml
        kg_ml = datos.get('kg_ml')
        it8 = QTableWidgetItem(f"{kg_ml:.3f}" if kg_ml else '')
        it8.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        tbl.setItem(r, 8, it8)

        # Col 9: Parc.(kg) — solo lectura
        it9 = QTableWidgetItem('')
        it9.setFlags(it9.flags() & ~Qt.ItemIsEditable)
        it9.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        it9.setBackground(QColor(SILVER_100))
        tbl.setItem(r, 9, it9)

        # Col 10: botón ×
        btn_del = QPushButton("×")
        btn_del.setStyleSheet(
            "QPushButton { color:#dc3545; border:none; font-size:14px; font-weight:700;"
            " background:transparent; }"
            "QPushButton:hover { color:#a00; }"
        )
        btn_del.clicked.connect(lambda _, b=btn_del: self._acero_eliminar_fila(b))
        tbl.setCellWidget(r, 10, btn_del)

        # Calcular parciales si hay datos
        if any(datos.get(k) for k in ('n_estructuras', 'n_elementos', 'n_veces', 'longitud')):
            self._acero_recalc_fila(r)

    def cargar_acero(self, part_id: int):
        self._met_panel_pid = part_id
        self._acero_loading = True
        conn = get_db()
        rows = conn.execute(
            "SELECT * FROM acero_detalle WHERE partida_id=? ORDER BY orden",
            (part_id,)
        ).fetchall()
        conn.close()
        self.tbl_acero.setRowCount(0)
        for row in rows:
            r = self.tbl_acero.rowCount()
            self._acero_fila_insertar(r, dict(row))
        self._acero_loading = False
        self._acero_actualizar_total()
        self._acero_nueva_fila_vacia()   # fila vacía lista al final
        partida = None
        conn = get_db()
        partida = conn.execute(
            "SELECT descripcion FROM partidas WHERE id=?", (part_id,)
        ).fetchone()
        conn.close()
        if partida and hasattr(self, 'lbl_met_titulo'):
            self.lbl_met_titulo.setText(f"ACERO  ·  {(partida['descripcion'] or '')[:60]}")
        # Reaplicar bloqueo de flags si el estado lo requiere
        if not getattr(self, '_ed_presupuesto', True):
            self._strip_table_editable_flags(self.tbl_acero)

    def _acero_eliminar_fila(self, btn):
        tbl = self.tbl_acero
        for r in range(tbl.rowCount()):
            if tbl.cellWidget(r, 10) is btn:
                tbl.removeRow(r)
                self._acero_actualizar_numeros()
                self._acero_actualizar_total()
                return

    def _acero_actualizar_numeros(self):
        for r in range(self.tbl_acero.rowCount()):
            it = self.tbl_acero.item(r, 0)
            if it:
                it.setText(str(r + 1))

    def _acero_diametro_cambiado(self, cmb):
        if self._acero_loading:
            return
        tbl = self.tbl_acero
        for r in range(tbl.rowCount()):
            if tbl.cellWidget(r, 2) is cmb:
                raw  = cmb.currentText().lstrip('ø').strip()
                diam = _normalizar_diametro_acero(raw)
                # Reflejar la interpretación (p.ej. '1/2' → 'ø1/2"') en el combo
                if diam and diam != raw:
                    self._acero_loading = True
                    cmb.setCurrentText(f'ø{diam}')
                    self._acero_loading = False
                kg_ml = _ACERO_KG_ML.get(diam, 0.0)
                it8 = tbl.item(r, 8)
                if it8:
                    self._acero_loading = True
                    it8.setText(f"{kg_ml:.3f}" if kg_ml else '')
                    self._acero_loading = False
                self._acero_recalc_fila(r)
                self._acero_guardar_silencioso()
                return

    def _acero_item_cambiado(self, item):
        if self._acero_loading:
            return
        if not self._ed_presupuesto:
            return
        r = item.row()
        if item.column() in (3, 4, 5, 6, 8):
            nt = _norm_lead_zero(item.text())
            if nt != item.text():
                self._acero_loading = True
                item.setText(nt)
                self._acero_loading = False
            self._acero_recalc_fila(r)
        # Añadir fila vacía si el usuario llenó la última
        last = self.tbl_acero.rowCount() - 1
        if r == last:
            tbl = self.tbl_acero
            cmb = tbl.cellWidget(last, 2)
            tiene_dato = (
                (cmb and cmb.currentIndex() > 0) or
                any(tbl.item(last, c) and tbl.item(last, c).text().strip()
                    for c in (1, 3, 4, 5, 6, 8))
            )
            if tiene_dato:
                self._acero_nueva_fila_vacia()
        # Auto-guardado sincrónico
        self._acero_guardar_silencioso()

    def _acero_recalc_fila(self, r: int):
        tbl = self.tbl_acero

        def val(c):
            it = tbl.item(r, c)
            if it and it.text().strip():
                try:
                    return float(it.text().replace(',', '.'))
                except ValueError:
                    return None
            return None

        dims  = [v for v in (val(3), val(4), val(5), val(6)) if v is not None]
        kgml  = val(8)
        parc_m = round(
            __import__('functools').reduce(lambda a, b: a * b, dims, 1.0), 4
        ) if dims else 0.0
        parc_kg = round(parc_m * kgml, 4) if kgml else 0.0

        dec = get_decimales_metrado()
        self._acero_loading = True
        it7 = tbl.item(r, 7)
        it9 = tbl.item(r, 9)
        if it7:
            it7.setText(f"{parc_m:,.{dec}f}" if dims else '')
        if it9:
            it9.setText(f"{parc_kg:,.{dec}f}" if (dims and kgml) else '')
        self._acero_loading = False
        self._acero_actualizar_total()

    def _acero_actualizar_total(self):
        dec   = get_decimales_metrado()
        total = 0.0
        for r in range(self.tbl_acero.rowCount()):
            it = self.tbl_acero.item(r, 9)
            if it and it.text().strip():
                try:
                    total += float(it.text().replace(',', ''))
                except ValueError:
                    pass
        self.lbl_met_total.setText(f"{total:,.{dec}f}")

    def _acero_guardar_impl(self):
        pid = self._met_panel_pid
        if pid is None:
            return
        if not self._ed_presupuesto:
            return
        tbl  = self.tbl_acero
        conn = get_db()
        # Exclusividad mutua: borrar metrados normales si se guardan metrados de acero
        conn.execute("DELETE FROM metrados_detalle WHERE partida_id=?",
                     (pid,))
        conn.execute("DELETE FROM acero_detalle WHERE partida_id=?",
                     (pid,))
        total_kg = 0.0
        orden = 0
        for r in range(tbl.rowCount()):
            cmb      = tbl.cellWidget(r, 2)
            diametro = _normalizar_diametro_acero(cmb.currentText()) if cmb else ''
            desc     = (tbl.item(r, 1).text() if tbl.item(r, 1) else '').strip()

            def _v(c):
                it = tbl.item(r, c)
                if it and it.text().strip():
                    try: return float(it.text().replace(',', '.'))
                    except: return None
                return None

            n_est = _v(3); n_el = _v(4); n_var = _v(5)
            llong = _v(6); kgml = _v(8)
            dims  = [v for v in (n_est, n_el, n_var, llong) if v is not None]
            # Saltar filas totalmente vacías (evita blancos intercalados)
            if not desc and not diametro and not dims:
                continue
            parc_m  = round(
                __import__('functools').reduce(lambda a, b: a*b, dims, 1.0), 4
            ) if dims else 0.0
            parc_kg = round(parc_m * kgml, 4) if kgml else 0.0
            total_kg += parc_kg
            orden += 1
            conn.execute(
                """INSERT INTO acero_detalle
                   (partida_id, orden, descripcion, diametro,
                    n_estructuras, n_elementos, n_veces, longitud, kg_ml, parcial)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (pid, orden, desc, diametro,
                 n_est, n_el, n_var, llong, kgml, parc_kg)
            )

        total_kg = round(total_kg, 4)
        conn.execute("UPDATE partidas SET metrado=? WHERE id=?",
                     (total_kg, pid))
        conn.commit()
        conn.close()
        self.lbl_met_total.setText(f"{total_kg:.3f}")
        self.recargar_partidas()

    # ── Metrados normales ─────────────────────────────────────────────────────

    # ── Copiar / Cortar / Pegar / Eliminar filas de metrados ─────────────────

    def _met_filas_datos(self) -> list[dict]:
        """Devuelve los datos de las filas seleccionadas."""
        rows = sorted({idx.row() for idx in self.tbl_met.selectedIndexes()})
        result = []
        for r in rows:
            def _v(c, _r=r):
                it = self.tbl_met.item(_r, c)
                if it and it.text().strip():
                    try: return float(it.text().replace(',', '.'))
                    except: return None
                return None
            result.append({
                'descripcion':  (self.tbl_met.item(r, 0).text()
                                 if self.tbl_met.item(r, 0) else '').strip(),
                'n_estructuras': _v(1), 'n_elementos': _v(2), 'area': _v(3),
                'largo': _v(4),  'ancho': _v(5),  'alto': _v(6),
            })
        return result

    def _met_copiar(self):
        datos = self._met_filas_datos()
        if datos:
            _MET_CLIPBOARD[:] = datos
            from PySide6.QtWidgets import QToolTip
            from PySide6.QtGui import QCursor
            QToolTip.showText(QCursor.pos(),
                              f"{len(datos)} fila(s) copiada(s)", self.tbl_met)

    def _met_cortar(self):
        if not self._ed_presupuesto:
            return
        rows = sorted({idx.row() for idx in self.tbl_met.selectedIndexes()},
                      reverse=True)
        datos = self._met_filas_datos()
        if not datos or not rows:
            return
        _MET_CLIPBOARD[:] = datos
        self._met_loading = True
        for r in rows:
            self.tbl_met.removeRow(r)
        self._met_loading = False
        self._metrado_guardar_silencioso()

    def _met_pegar(self):
        if not self._ed_presupuesto:
            return
        if not _MET_CLIPBOARD or self._met_panel_pid is None:
            return
        dec = get_decimales_metrado()
        # Insertar antes de la última fila vacía
        insert_at = max(0, self.tbl_met.rowCount() - 1)
        self._met_loading = True
        for i, datos in enumerate(_MET_CLIPBOARD):
            r = insert_at + i
            self.tbl_met.insertRow(r)
            self.tbl_met.setRowHeight(r, 24)
            self.tbl_met.setItem(r, 0, QTableWidgetItem(datos.get('descripcion', '')))
            for c, key in [(1, 'n_estructuras'), (2, 'n_elementos'), (3, 'area'),
                           (4, 'largo'), (5, 'ancho'), (6, 'alto')]:
                val = datos.get(key)
                it = QTableWidgetItem(str(val) if val is not None else '')
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.tbl_met.setItem(r, c, it)
            # Parcial calculado
            dims = [v for v in [datos.get(k) for k in
                    ('n_estructuras','n_elementos','area','largo','ancho','alto')]
                    if v is not None]
            parc = 1.0
            for d in dims: parc *= d
            parc = _rn(parc, dec) if dims else 0.0
            it7 = QTableWidgetItem(f"{parc:,.{dec}f}")
            it7.setFlags(it7.flags() & ~Qt.ItemIsEditable)
            it7.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            it7.setBackground(QColor(SILVER_100))
            self.tbl_met.setItem(r, 7, it7)
        self._met_loading = False
        self._metrado_guardar_silencioso()

    def _met_eliminar_seleccionadas(self):
        if not self._ed_presupuesto:
            return
        rows = sorted({idx.row() for idx in self.tbl_met.selectedIndexes()},
                      reverse=True)
        if not rows:
            return
        self._met_loading = True
        for r in rows:
            self.tbl_met.removeRow(r)
        self._met_loading = False
        # Asegurar que quede al menos una fila vacía
        if self.tbl_met.rowCount() == 0:
            self._metrado_nueva_fila()
        self._metrado_guardar_silencioso()

    def _met_menu_contextual(self, pos):
        from PySide6.QtWidgets import QMenu
        from utils.i18n import tr
        rows = {idx.row() for idx in self.tbl_met.selectedIndexes()}
        n    = len(rows)
        target = self.tbl_met.rowAt(pos.y())
        menu = QMenu(self)
        if self._ed_presupuesto:
            menu.addAction(tr("Insertar fila"),
                           lambda: self._met_insertar_fila(target))
            if n:
                menu.addAction(f"{tr('Borrar contenido')} ({n})",
                               self._met_borrar_contenido)
            menu.addSeparator()
        if n:
            menu.addAction(f"{tr('Copiar')} {n}  Ctrl+C",  self._met_copiar)
            menu.addAction(f"{tr('Cortar')} {n}  Ctrl+X",  self._met_cortar)
            menu.addAction(f"{tr('Eliminar')} {n}  Del",   self._met_eliminar_seleccionadas)
        if _MET_CLIPBOARD:
            menu.addSeparator()
            nc = len(_MET_CLIPBOARD)
            menu.addAction(f"{tr('Pegar')} ({nc})  Ctrl+V",  self._met_pegar)
        if not menu.isEmpty():
            menu.exec(self.tbl_met.viewport().mapToGlobal(pos))

    def _met_ultima_vacia(self) -> bool:
        """True si la última fila de tbl_met está completamente vacía."""
        tbl = self.tbl_met
        n   = tbl.rowCount()
        if n == 0:
            return False
        last = n - 1
        return not any(tbl.item(last, c) and tbl.item(last, c).text().strip()
                       for c in range(7))

    def _metrado_nueva_fila(self):
        if self._met_panel_pid is None:
            return
        if self._met_modo == 'acero':
            if not self._acero_ultima_vacia():
                self._acero_fila_insertar(self.tbl_acero.rowCount(), {})
            return
        if self._met_ultima_vacia():
            return   # ya hay una fila vacía al final
        self._met_loading = True
        r = self.tbl_met.rowCount()
        self.tbl_met.insertRow(r)
        self.tbl_met.setRowHeight(r, 24)
        for c in range(8):
            it = QTableWidgetItem("")
            if c == 7:
                it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                it.setBackground(QColor(SILVER_100))
            elif c > 0:
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.tbl_met.setItem(r, c, it)
        self._met_loading = False

    def _metrado_fila_btn(self):
        """Botón '+ Fila': agrega una fila al final y empieza a editarla."""
        if self._partida_actual_id is None:
            QMessageBox.information(self, "Metrados", "Seleccione una partida primero.")
            return
        if not self._ed_presupuesto:
            return
        if self._met_modo == 'acero':
            if not self._acero_ultima_vacia():
                self._acero_fila_insertar(self.tbl_acero.rowCount(), {})
            r = self.tbl_acero.rowCount() - 1
            if r >= 0:
                self.tbl_acero.setCurrentCell(r, 0)
                self.tbl_acero.scrollToBottom()
            return
        if not self._met_ultima_vacia():
            self._metrado_nueva_fila()
        last = self.tbl_met.rowCount() - 1
        if last >= 0:
            self.tbl_met.setCurrentCell(last, 0)
            self.tbl_met.scrollToBottom()
            QTimer.singleShot(0, lambda: self.tbl_met.edit(
                self.tbl_met.model().index(last, 0)))

    def _met_insertar_fila(self, at_row: int):
        """Inserta una fila vacía antes de `at_row` (o al final si es inválido)."""
        if not self._ed_presupuesto:
            return
        if at_row is None or at_row < 0:
            at_row = self.tbl_met.rowCount()
        dec = get_decimales_metrado()
        self._met_loading = True
        self.tbl_met.insertRow(at_row)
        self.tbl_met.setRowHeight(at_row, 24)
        for c in range(8):
            it = QTableWidgetItem("" if c < 7 else f"{0:,.{dec}f}")
            if c == 7:
                it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                it.setBackground(QColor(SILVER_100))
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            elif c > 0:
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.tbl_met.setItem(at_row, c, it)
        self._met_loading = False
        self._metrado_guardar_silencioso()
        self.tbl_met.setCurrentCell(at_row, 0)
        QTimer.singleShot(0, lambda: self.tbl_met.edit(
            self.tbl_met.model().index(at_row, 0)))

    def _met_borrar_contenido(self):
        """Vacía las celdas de las filas seleccionadas sin eliminar las filas."""
        if not self._ed_presupuesto:
            return
        rows = sorted({idx.row() for idx in self.tbl_met.selectedIndexes()})
        if not rows:
            return
        dec = get_decimales_metrado()
        self._met_loading = True
        for r in rows:
            for c in range(7):
                it = self.tbl_met.item(r, c)
                if it:
                    it.setText("")
            itp = self.tbl_met.item(r, 7)
            if itp:
                itp.setText(f"{0:,.{dec}f}")
        self._met_loading = False
        total = 0.0
        for rr in range(self.tbl_met.rowCount()):
            it2 = self.tbl_met.item(rr, 7)
            if it2:
                try:
                    total += float(it2.text().replace(',', ''))
                except ValueError:
                    pass
        self.lbl_met_total.setText(f"{total:,.{dec}f}")
        self._metrado_guardar_silencioso()

    def _metrado_guardar(self):
        pid = self._met_panel_pid
        if pid is None:
            return
        if not self._ed_presupuesto:
            return
        if self._met_modo == 'acero':
            self._acero_guardar_impl()
            self.cargar_acero(pid)   # compacta blancos intercalados
            return
        conn = get_db()
        conn.execute("DELETE FROM metrados_detalle WHERE partida_id=?",
                     (pid,))
        total = 0.0
        for r in range(self.tbl_met.rowCount()):
            def _val(c):
                it = self.tbl_met.item(r, c)
                try:
                    return float(it.text().replace(',', '.')) if it and it.text().strip() else None
                except ValueError:
                    return None

            desc  = (self.tbl_met.item(r, 0).text() if self.tbl_met.item(r, 0) else "").strip()
            n_est = _val(1); n_el = _val(2)
            area  = _val(3)
            largo = _val(4); ancho = _val(5); alto = _val(6)

            # Saltar filas completamente vacías
            dims = [x for x in [n_est, n_el, area, largo, ancho, alto] if x is not None]
            if not desc and not dims:
                continue
            parcial = 1.0
            for d in dims:
                parcial *= d
            dec = get_decimales_metrado()
            parcial = _rn(parcial, dec) if dims else 0.0
            total += parcial

            conn.execute(
                """INSERT INTO metrados_detalle
                   (partida_id, orden, descripcion, n_estructuras, n_elementos,
                    area, largo, ancho, alto, parcial)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (pid, r+1, desc, n_est, n_el, area, largo, ancho, alto, parcial)
            )
            it_parc = self.tbl_met.item(r, 7)
            if it_parc:
                it_parc.setText(f"{parcial:,.{dec}f}")

        dec   = get_decimales_metrado()
        total = _rn(total, dec)
        conn.execute("UPDATE partidas SET metrado=? WHERE id=?",
                     (total, pid))
        conn.commit()
        conn.close()
        self.lbl_met_total.setText(f"{total:,.{dec}f}")
        self.recargar_partidas()

    def _met_tiene_datos(self) -> bool:
        """True si la tabla de metrados normales tiene al menos una fila con datos reales."""
        tbl = self.tbl_met
        for r in range(tbl.rowCount()):
            desc = (tbl.item(r, 0).text() if tbl.item(r, 0) else '').strip()
            if desc:
                return True
            if any(tbl.item(r, c) and tbl.item(r, c).text().strip()
                   for c in range(1, 7)):
                return True
        return False

    def _metrado_guardar_silencioso(self):
        """Guarda metrados en DB y actualiza el árbol sin recargar todo."""
        # Escribir a la partida cargada en el panel, NO a la seleccionada en el
        # árbol: pueden diferir si se cambió de partida fuera del tab Metrados.
        pid = self._met_panel_pid
        if pid is None:
            return
        if not self._ed_presupuesto:
            return
        # No guardar si la tabla está vacía — evita borrar datos existentes
        if not self._met_tiene_datos():
            return
        dec  = get_decimales_metrado()
        conn = get_db()
        # Exclusividad mutua: borrar acero solo cuando hay datos reales de metrados
        conn.execute("DELETE FROM acero_detalle WHERE partida_id=?",
                     (pid,))
        conn.execute("DELETE FROM metrados_detalle WHERE partida_id=?",
                     (pid,))
        total = 0.0
        for r in range(self.tbl_met.rowCount()):
            def _v(c, _r=r):
                it = self.tbl_met.item(_r, c)
                if it and it.text().strip():
                    try: return float(it.text().replace(',', '.'))
                    except: return None
                return None
            desc  = (self.tbl_met.item(r, 0).text() if self.tbl_met.item(r, 0) else '').strip()
            n_est = _v(1); n_el = _v(2); area = _v(3)
            largo = _v(4); ancho = _v(5); alto = _v(6)
            dims  = [x for x in [n_est, n_el, area, largo, ancho, alto] if x is not None]
            if not desc and not dims:
                continue
            parcial = 1.0
            for d in dims: parcial *= d
            parcial = _rn(parcial, dec) if dims else 0.0
            total  += parcial
            conn.execute(
                """INSERT INTO metrados_detalle
                   (partida_id, orden, descripcion, n_estructuras, n_elementos,
                    area, largo, ancho, alto, parcial)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (pid, r+1, desc, n_est, n_el, area, largo, ancho, alto, parcial)
            )
        total = _rn(total, dec)
        conn.execute("UPDATE partidas SET metrado=? WHERE id=?",
                     (total, pid))
        conn.commit()
        # Verificar que los datos quedaron guardados
        check = conn.execute("SELECT COUNT(*) FROM metrados_detalle WHERE partida_id=?",
                             (pid,)).fetchone()[0]
        conn.close()
        # Segunda verificación con nueva conexión
        conn2 = get_db()
        check2 = conn2.execute("SELECT COUNT(*) FROM metrados_detalle WHERE partida_id=?",
                               (pid,)).fetchone()[0]
        conn2.close()

        # Actualizar árbol — bloquear señales para no disparar _on_tree_metrado_cambiado
        self.tree.blockSignals(True)
        self._con_planilla.add(pid)
        tw = self._id_to_item.get(pid)
        if tw:
            tw.setText(3, f"{total:,.{dec}f}")
            tw.setData(3, Qt.UserRole, True)   # ✓ planilla
            try:
                pu = float(tw.text(4).replace(',', ''))
            except ValueError:
                pu = 0.0
            parcial_tree = parcial_wysiwyg(total, pu, dec)
            tw.setText(5, fmt(parcial_tree, self._moneda, dec))
            tw.setData(5, Qt.UserRole, float(parcial_tree))
        self.tree.blockSignals(False)
        self._calcular_totales_titulos(self.tree.invisibleRootItem())
        self.actualizar_total()

    def _metrado_item_cambiado(self, item):
        if self._met_loading:
            return
        # Guard de estado: no recalcular ni guardar si el presupuesto está bloqueado
        if not self._ed_presupuesto:
            return
        r   = item.row()
        dec = get_decimales_metrado()
        # Completar el «0» a la izquierda en la celda editada («.1» → «0.1»).
        if 1 <= item.column() <= 6:
            nt = _norm_lead_zero(item.text())
            if nt != item.text():
                self._met_loading = True
                item.setText(nt)
                self._met_loading = False
        try:
            dims = []
            for c in range(1, 7):   # cols 1-6: N°Est, N°Elem, Área, Largo, Ancho, Alto
                it = self.tbl_met.item(r, c)
                if it and it.text().strip():
                    dims.append(float(it.text().replace(',', '.')))
            parc = 1.0
            for d in dims:
                parc *= d
            parc = _rn(parc, dec) if dims else 0.0
            it_p = self.tbl_met.item(r, 7)
            if it_p:
                self._met_loading = True
                it_p.setText(f"{parc:,.{dec}f}")
                self._met_loading = False
            # Recalcular total
            total = 0.0
            for rr in range(self.tbl_met.rowCount()):
                it2 = self.tbl_met.item(rr, 7)
                if it2:
                    try:
                        total += float(it2.text().replace(',', ''))
                    except ValueError:
                        pass
            self.lbl_met_total.setText(f"{total:,.{dec}f}")
            # Añadir fila vacía si el usuario llenó la última
            last = self.tbl_met.rowCount() - 1
            if r == last:
                ultima_vacia = all(
                    not (self.tbl_met.item(last, c) and
                         self.tbl_met.item(last, c).text().strip())
                    for c in range(7)
                )
                if not ultima_vacia:
                    self._metrado_nueva_fila()
            # Guardar sincrónicamente — SQLite + tabla pequeña es inmediato
            self._metrado_guardar_silencioso()
        except Exception as e:
            import traceback; traceback.print_exc()

    # ══════════════════════════════════════════════════════════════════════════
    # Especificaciones
    # ══════════════════════════════════════════════════════════════════════════

    def _on_spec_modificada(self):
        if self._partida_actual_id is None:
            return
        self._spec_modificada = True
        self.lbl_spec_estado.setText("● Sin guardar")
        self.lbl_spec_estado.setStyleSheet("font-size:10px; color:#F37329; border:none;")

    def _spec_actualizar_toolbar(self):
        """Sincroniza el estado de los botones de formato con el cursor."""
        fmt = self.txt_spec.currentCharFormat()
        self.btn_bold.setChecked(fmt.fontWeight() >= QFont.Bold)
        self.btn_italic.setChecked(fmt.fontItalic())
        self.btn_underline.setChecked(fmt.fontUnderline())

    # ── Acciones de formato ──────────────────────────────────────────

    def _spec_bold(self):
        fmt = QTextCharFormat()
        peso = QFont.Normal if self.txt_spec.fontWeight() >= QFont.Bold else QFont.Bold
        fmt.setFontWeight(peso)
        self.txt_spec.mergeCurrentCharFormat(fmt)

    def _spec_italic(self):
        fmt = QTextCharFormat()
        fmt.setFontItalic(not self.txt_spec.fontItalic())
        self.txt_spec.mergeCurrentCharFormat(fmt)

    def _spec_underline(self):
        fmt = QTextCharFormat()
        fmt.setFontUnderline(not self.txt_spec.fontUnderline())
        self.txt_spec.mergeCurrentCharFormat(fmt)

    def _spec_align(self, alineacion):
        self.txt_spec.setAlignment(alineacion)

    def _spec_bullet_list(self):
        cursor = self.txt_spec.textCursor()
        fmt = QTextListFormat()
        fmt.setStyle(QTextListFormat.ListDisc)
        cursor.createList(fmt)

    def _spec_numbered_list(self):
        cursor = self.txt_spec.textCursor()
        fmt = QTextListFormat()
        fmt.setStyle(QTextListFormat.ListDecimal)
        cursor.createList(fmt)

    def _spec_insertar_imagen(self):
        path, _ = _QFileDialog.getOpenFileName(
            self, "Seleccionar imagen", "",
            "Imágenes (*.png *.jpg *.jpeg *.bmp *.gif)"
        )
        if not path:
            return
        img = QImage(path)
        if img.isNull():
            return
        if img.width() > 560:
            img = img.scaledToWidth(560, Qt.SmoothTransformation)

        # Embeber como base64 para que persista al guardar/recargar
        import base64
        from PySide6.QtCore import QBuffer, QByteArray, QIODeviceBase
        ba  = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODeviceBase.WriteOnly)
        img.save(buf, "PNG")
        buf.close()
        b64 = base64.b64encode(bytes(ba)).decode('ascii')
        self.txt_spec.textCursor().insertHtml(
            f'<img src="data:image/png;base64,{b64}" width="{img.width()}" />'
        )

    # ── Helper: convierte texto plano de IA a HTML con secciones en negrita ──

    @staticmethod
    def _plain_to_html_spec(texto: str) -> str:
        import re, html
        lineas = texto.split('\n')
        partes = []
        for linea in lineas:
            linea_strip = linea.strip()
            escaped = html.escape(linea_strip)
            es_titulo = (
                re.match(r'^\d+\.\s+[A-ZÁÉÍÓÚÑÜ\s\/\-]+$', linea_strip) or
                (len(linea_strip) >= 5
                 and linea_strip == linea_strip.upper()
                 and re.search(r'[A-ZÁÉÍÓÚÑ]', linea_strip))
            )
            if es_titulo:
                partes.append(
                    f'<p style="text-align:left;">'
                    f'<b><span style="color:#000000;">{escaped}</span></b></p>'
                )
            elif linea_strip:
                partes.append(f'<p style="text-align:justify;">{escaped}</p>')
            else:
                partes.append('<p></p>')
        return ''.join(partes)

    def _insertar_seccion_spec(self, titulo: str):
        cursor = self.txt_spec.textCursor()
        cursor.insertText('\n')
        cursor.insertText(titulo + '\n')
        self.txt_spec.setTextCursor(cursor)
        self.txt_spec.setFocus()

    def _guardar_spec(self):
        if self._partida_actual_id is None:
            return
        if not self._ed_specs:
            return
        conn = get_db()
        conn.execute("UPDATE partidas SET especificaciones=? WHERE id=?",
                     (self.txt_spec.toHtml(), self._partida_actual_id))
        conn.commit()
        conn.close()
        self._spec_modificada = False
        self.lbl_spec_estado.setText("✓ Guardado")
        self.lbl_spec_estado.setStyleSheet("font-size:10px; color:#68B723; border:none;")
        self._actualizar_indicador_spec(self._partida_actual_id,
                                        bool(self.txt_spec.toPlainText().strip()))

    def _actualizar_indicador_spec(self, part_id: int, tiene: bool):
        def _buscar(item):
            if item.data(0, Qt.UserRole) == part_id:
                item.setData(1, Qt.UserRole, tiene)
                return
            for i in range(item.childCount()):
                _buscar(item.child(i))
        for i in range(self.tree.topLevelItemCount()):
            _buscar(self.tree.topLevelItem(i))

    def _ia_generar_spec(self):
        if self._partida_actual_id is None:
            QMessageBox.information(self, "Generar spec", "Seleccione una partida primero.")
            return
        conn = get_db()
        p = conn.execute("SELECT item, descripcion FROM partidas WHERE id=?",
                         (self._partida_actual_id,)).fetchone()
        conn.close()
        if not p:
            return
        dlg = _DialogIASpec(self, self._partida_actual_id,
                            f"{p['item']}  {p['descripcion']}")
        if dlg.exec() == QDialog.Accepted:
            texto = dlg.resultado()
            if texto:
                html = self._plain_to_html_spec(texto)
                self.txt_spec.blockSignals(True)
                self.txt_spec.setHtml(html)
                self.txt_spec.blockSignals(False)
                # Guardar como HTML en DB
                conn = get_db()
                conn.execute("UPDATE partidas SET especificaciones=? WHERE id=?",
                             (html, self._partida_actual_id))
                conn.commit()
                conn.close()
                self._spec_modificada = False
                self.lbl_spec_estado.setText("✓ Guardado")
                self.lbl_spec_estado.setStyleSheet("font-size:10px; color:#68B723; border:none;")
                self._actualizar_indicador_spec(self._partida_actual_id, True)

    def _ia_generar_todo(self, omitir_existentes: bool = True):
        nombre = self._proy.get('nombre', '')
        dlg = _DialogIATodo(self, self.pid, nombre,
                            omitir_existentes=omitir_existentes)
        dlg.exec()
        # Recargar spec de la partida actual si estaba visible
        if self._partida_actual_id:
            conn = get_db()
            p = conn.execute("SELECT especificaciones FROM partidas WHERE id=?",
                             (self._partida_actual_id,)).fetchone()
            conn.close()
            if p:
                contenido = p['especificaciones'] or ""
                self.txt_spec.blockSignals(True)
                if contenido.strip().startswith('<'):
                    self.txt_spec.setHtml(contenido)
                elif contenido.strip():
                    html = self._plain_to_html_spec(contenido)
                    self.txt_spec.setHtml(html)
                    conn2 = get_db()
                    conn2.execute("UPDATE partidas SET especificaciones=? WHERE id=?",
                                  (html, self._partida_actual_id))
                    conn2.commit()
                    conn2.close()
                else:
                    self.txt_spec.clear()
                self.txt_spec.blockSignals(False)
                self._spec_modificada = False
                self.lbl_spec_estado.setText("")
        self.recargar_partidas()

    # ══════════════════════════════════════════════════════════════════════════
    # Menu "Archivo" — dropdown del topbar (Nuevo/Abrir/Imprimir/Exportar/…)
    # ══════════════════════════════════════════════════════════════════════════

    def _build_archivo_menu(self):
        """QMenu del botón "Archivo ▾" del topbar. Reúne acciones globales
        (nuevo/abrir/importar/configuración) y específicas del proyecto
        activo (imprimir, exportar PDF, cerrar)."""
        from PySide6.QtWidgets import QMenu
        from PySide6.QtGui import QAction, QKeySequence
        from utils.i18n import tr
        menu = QMenu(self)

        a_new = QAction(tr("Nuevo Proyecto"), self)
        a_new.setShortcut(QKeySequence("Ctrl+N"))
        a_new.triggered.connect(self.ir_a_nuevo_proyecto.emit)
        menu.addAction(a_new)

        # Abrir → submenú: proyectos ya en el programa | abrir un archivo .db.
        abrir_menu = QMenu(tr("Abrir"), self)
        a_open = QAction(tr("Mis proyectos") + "…", self)
        a_open.setShortcut(QKeySequence("Ctrl+O"))
        a_open.triggered.connect(self.ir_a_proyectos.emit)
        abrir_menu.addAction(a_open)
        a_open_db = QAction(tr("Desde archivo") + " (.db)…", self)
        a_open_db.triggered.connect(self._archivo_abrir_db)
        abrir_menu.addAction(a_open_db)
        menu.addMenu(abrir_menu)

        menu.addSeparator()

        a_print = QAction(tr("Imprimir") + "…", self)
        a_print.setShortcut(QKeySequence("Ctrl+P"))
        a_print.triggered.connect(self._archivo_imprimir)
        menu.addAction(a_print)

        a_db = QAction(tr("Exportar") + " (.db)…", self)
        a_db.triggered.connect(self._archivo_exportar_db)
        menu.addAction(a_db)

        a_imp = QAction(tr("Importar") + "…", self)
        a_imp.triggered.connect(self.ir_a_importar.emit)
        menu.addAction(a_imp)

        # Plantillas de estructura (guardar el presupuesto / insertar en otro).
        plant_menu = QMenu("Plantillas", self)
        a_pl_save = QAction("Guardar presupuesto como plantilla…", self)
        a_pl_save.triggered.connect(self._guardar_como_plantilla)
        plant_menu.addAction(a_pl_save)
        a_pl_ins = QAction("Insertar desde plantilla…", self)
        a_pl_ins.triggered.connect(self._insertar_desde_plantilla)
        plant_menu.addAction(a_pl_ins)
        plant_menu.addSeparator()
        a_pl_imp = QAction("Importar plantilla (.db)…", self)
        a_pl_imp.triggered.connect(self._importar_plantilla_db)
        plant_menu.addAction(a_pl_imp)
        menu.addMenu(plant_menu)

        menu.addSeparator()

        a_cfg = QAction(tr("Configuración"), self)
        a_cfg.triggered.connect(self.ir_a_configuracion.emit)
        menu.addAction(a_cfg)

        a_close = QAction(tr("Cerrar"), self)
        a_close.triggered.connect(lambda: self.cerrar_proyecto.emit(self.pid))
        menu.addAction(a_close)

        a_restart = QAction("Reiniciar", self)
        a_restart.triggered.connect(self._archivo_reiniciar)
        menu.addAction(a_restart)

        # Atajos accesibles aun con el menu cerrado (no solo al abrirlo).
        for act in (a_new, a_open, a_print):
            act.setShortcutContext(Qt.WindowShortcut)
            self.addAction(act)

        return menu

    def _guardar_como_plantilla(self):
        """Guarda la estructura del presupuesto (o de un sub-presupuesto) como
        plantilla reutilizable en otros proyectos. Estructura + ACU + specs, sin
        metrados (salvo que se marque)."""
        from PySide6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout,
            QLineEdit, QComboBox, QCheckBox, QHBoxLayout, QPushButton, QLabel,
            QMessageBox)
        from core import plantillas_estructura as PL
        conn = get_db()
        subs = conn.execute(
            "SELECT id, nombre FROM sub_presupuestos WHERE proyecto_id=? "
            "ORDER BY orden, id", (self.pid,)).fetchall()
        conn.close()

        dlg = QDialog(self); dlg.setWindowTitle("Guardar como plantilla")
        dlg.setMinimumWidth(420)
        v = QVBoxLayout(dlg); v.setContentsMargins(16, 14, 16, 14); v.setSpacing(8)
        v.addWidget(QLabel("Guarda la ESTRUCTURA del presupuesto (ítems, ACU y "
                           "especificaciones) para reutilizarla en otros "
                           "proyectos."))
        form = QFormLayout()
        ed_nombre = QLineEdit()
        ed_nombre.setText((self._proy.get('nombre') or '')[:60])
        ed_tipo = QLineEdit(); ed_tipo.setPlaceholderText("Ej. Canales, Saneamiento… (opcional)")
        ed_notas = QLineEdit(); ed_notas.setPlaceholderText("Notas (opcional)")
        cmb_scope = QComboBox()
        cmb_scope.addItem("Todo el proyecto", '__all__')
        for s in subs:
            cmb_scope.addItem(f"Sub-presupuesto: {s['nombre']}", s['id'])
        chk_metr = QCheckBox("Incluir metrados (cantidades del proyecto)")
        form.addRow("Nombre:", ed_nombre)
        form.addRow("Tipo/sector:", ed_tipo)
        form.addRow("Notas:", ed_notas)
        form.addRow("Alcance:", cmb_scope)
        v.addLayout(form)
        v.addWidget(chk_metr)
        bar = QHBoxLayout(); bar.addStretch()
        b_ca = QPushButton("Cancelar"); b_ok = QPushButton("Guardar plantilla")
        b_ok.setStyleSheet(_BTN_PRIMARY_SS_FALLBACK)
        b_ca.clicked.connect(dlg.reject); b_ok.clicked.connect(dlg.accept)
        bar.addWidget(b_ca); bar.addWidget(b_ok); v.addLayout(bar)
        ed_nombre.setFocus()
        if dlg.exec() != QDialog.Accepted:
            return
        nombre = ed_nombre.text().strip()
        if not nombre:
            QMessageBox.information(self, "Plantilla", "Ponle un nombre a la plantilla.")
            return
        try:
            pid_pl = PL.guardar_plantilla(
                self.pid, nombre, tipo=ed_tipo.text(), notas=ed_notas.text(),
                sub_ppto_id=cmb_scope.currentData(),
                incluir_metrados=chk_metr.isChecked())
        except Exception as e:  # noqa: BLE001
            import traceback; traceback.print_exc()
            QMessageBox.critical(self, "Plantilla", f"No se pudo guardar:\n{e}")
            return
        if pid_pl:
            QMessageBox.information(self, "Plantilla",
                f"Plantilla «{nombre}» guardada.\nDisponible en Archivo → "
                "Plantillas → Insertar desde plantilla, en cualquier proyecto.")

    def _insertar_desde_plantilla(self):
        """Inserta la estructura de una plantilla guardada en el proyecto actual
        (reutiliza el pegado del clipboard: respeta la selección/subpresupuesto)."""
        if not self._require_editable("insertar plantilla"):
            return
        from PySide6.QtWidgets import (QDialog, QVBoxLayout, QListWidget,
            QListWidgetItem, QHBoxLayout, QPushButton, QLabel, QLineEdit,
            QMessageBox)
        from core import plantillas_estructura as PL
        plantillas = PL.listar_plantillas()
        if not plantillas:
            QMessageBox.information(self, "Plantillas",
                "Aún no tienes plantillas. Créalas desde Archivo → Plantillas → "
                "«Guardar presupuesto como plantilla».")
            return

        dlg = QDialog(self); dlg.setWindowTitle("Insertar desde plantilla")
        dlg.setMinimumSize(460, 420)
        v = QVBoxLayout(dlg); v.setContentsMargins(16, 14, 16, 14); v.setSpacing(8)
        v.addWidget(QLabel("Elige una plantilla para insertar su estructura en "
                           "este proyecto (según tu selección en el árbol)."))
        buscador = QLineEdit(); buscador.setPlaceholderText("Buscar…")
        v.addWidget(buscador)
        lst = QListWidget(); v.addWidget(lst, 1)

        def _llenar(filtro=''):
            lst.clear()
            f = filtro.strip().lower()
            for p in plantillas:
                txt = f"{p['nombre']}"
                if p.get('tipo'):
                    txt += f"   ·  {p['tipo']}"
                txt += f"   ·  {p['n_partidas']} partidas"
                if f and f not in txt.lower():
                    continue
                it = QListWidgetItem(txt)
                it.setData(Qt.UserRole, p['id'])
                if p.get('notas'):
                    it.setToolTip(p['notas'])
                lst.addItem(it)
        _llenar()
        buscador.textChanged.connect(_llenar)

        bar = QHBoxLayout()
        b_del = QPushButton("Eliminar")
        b_del.setToolTip("Borra la plantilla seleccionada (no afecta a ningún proyecto).")
        b_exp = QPushButton("Exportar (.db)…")
        b_exp.setToolTip("Guarda la plantilla como archivo .db para compartirla.")
        bar.addWidget(b_del); bar.addWidget(b_exp); bar.addStretch()
        b_ca = QPushButton("Cancelar"); b_ok = QPushButton("Insertar")
        b_ok.setStyleSheet(_BTN_PRIMARY_SS_FALLBACK)
        bar.addWidget(b_ca); bar.addWidget(b_ok); v.addLayout(bar)
        b_ca.clicked.connect(dlg.reject)
        b_ok.clicked.connect(dlg.accept)

        def _exportar():
            import os
            from PySide6.QtWidgets import QFileDialog
            it = lst.currentItem()
            if not it:
                return
            nombre = it.text().split('   ·')[0].strip()
            sug = "".join(c for c in nombre if c.isalnum() or c in " _-").strip() or "plantilla"
            # Carpeta por defecto: Descargas (fácil de encontrar para compartir).
            base = next((d for d in (os.path.expanduser("~/Descargas"),
                                     os.path.expanduser("~/Downloads"))
                         if os.path.isdir(d)), os.path.expanduser("~"))
            ruta, _f = QFileDialog.getSaveFileName(
                dlg, "Exportar plantilla", os.path.join(base, f"{sug}.db"),
                "Plantilla (*.db)")
            if not ruta:
                return
            if not ruta.lower().endswith('.db'):
                ruta += '.db'
            try:
                PL.exportar_plantilla_db(it.data(Qt.UserRole), ruta)
                QMessageBox.information(dlg, "Exportar",
                    f"Plantilla guardada en:\n{ruta}\n\nComparte este archivo; el "
                    "otro usuario lo abre con Archivo → Plantillas → «Importar "
                    "plantilla (.db)».")
            except Exception as e:  # noqa: BLE001
                QMessageBox.critical(dlg, "Exportar", f"No se pudo exportar:\n{e}")
        b_exp.clicked.connect(_exportar)

        def _eliminar():
            it = lst.currentItem()
            if not it:
                return
            if QMessageBox.question(dlg, "Eliminar plantilla",
                    f"¿Eliminar la plantilla «{it.text().split('   ·')[0]}»?"
                    ) != QMessageBox.Yes:
                return
            PL.eliminar_plantilla(it.data(Qt.UserRole))
            plantillas[:] = PL.listar_plantillas()
            _llenar(buscador.text())
        b_del.clicked.connect(_eliminar)
        lst.itemDoubleClicked.connect(lambda _i: dlg.accept())

        if dlg.exec() != QDialog.Accepted:
            return
        it = lst.currentItem()
        if not it:
            return
        subarboles = PL.subarboles_de_plantilla(it.data(Qt.UserRole))
        if not subarboles:
            QMessageBox.information(self, "Plantilla", "La plantilla está vacía.")
            return
        ctx_item, ctx_es_titulo = self._contexto_seleccion()
        conn = get_db()
        try:
            nuevos = _pclip.pegar_datos(conn, subarboles, self.pid,
                                        self._sub_ppto_id,
                                        contexto_item=ctx_item,
                                        contexto_es_titulo=ctx_es_titulo)
            conn.commit()
        except Exception as e:  # noqa: BLE001
            conn.rollback(); conn.close()
            import traceback; traceback.print_exc()
            QMessageBox.critical(self, "Insertar plantilla", f"Error al insertar:\n{e}")
            return
        conn.close()
        self.recargar_partidas()
        self.tree._renumerar()
        self.actualizar_total()
        QMessageBox.information(self, "Plantilla",
            f"Insertadas {len(nuevos)} raíz(es) de la plantilla en el proyecto.")

    def _importar_plantilla_db(self):
        """Importa una plantilla compartida por otro usuario (archivo .db)."""
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        from core import plantillas_estructura as PL
        ruta, _f = QFileDialog.getOpenFileName(
            self, "Importar plantilla (.db)", "", "Plantilla (*.db)")
        if not ruta:
            return
        try:
            n = PL.importar_plantillas_db(ruta)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Importar plantilla",
                                 f"No se pudo importar:\n{e}")
            return
        if n:
            QMessageBox.information(self, "Importar plantilla",
                f"Importada{'s' if n != 1 else ''} {n} plantilla"
                f"{'s' if n != 1 else ''}. Úsala desde Archivo → Plantillas → "
                "«Insertar desde plantilla».")
        else:
            QMessageBox.information(self, "Importar plantilla",
                "No se importó nada nuevo (ya la tenías).")

    def _archivo_abrir_db(self):
        """Abre un proyecto desde un archivo .db de ingePresupuestos: lo importa
        al programa (si trae varios, deja elegir cuál) y lo abre en una pestaña."""
        from PySide6.QtWidgets import (QFileDialog, QMessageBox, QInputDialog,
                                       QApplication)
        from core.ingepresupuestos_db_importer import (
            listar_proyectos_db, importar_proyecto_db_directo)
        ruta, _f = QFileDialog.getOpenFileName(
            self, "Abrir proyecto desde archivo (.db)", "",
            "Bases ingePresupuestos (*.db *.sqlite)"
        )
        if not ruta:
            return
        try:
            proyectos = listar_proyectos_db(ruta)
        except Exception as e:
            QMessageBox.warning(self, "Abrir desde .db",
                                f"No se pudo leer el archivo:\n{e}")
            return
        if not proyectos:
            QMessageBox.information(self, "Abrir desde .db",
                                    "El archivo no contiene proyectos.")
            return
        if len(proyectos) == 1:
            elegido = proyectos[0]
        else:
            etiquetas = [f"{p['nombre']}  (#{p['id_ppto']})" for p in proyectos]
            etq, ok = QInputDialog.getItem(
                self, "Abrir desde .db",
                "El archivo contiene varios proyectos. Elige uno:",
                etiquetas, 0, False
            )
            if not ok:
                return
            elegido = proyectos[etiquetas.index(etq)]

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            pid = importar_proyecto_db_directo(ruta, elegido['id_ppto'])
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Abrir desde .db",
                                f"No se pudo abrir el proyecto:\n{e}")
            return
        QApplication.restoreOverrideCursor()
        # Importar crea una copia nueva en el programa; abrirla en su pestaña.
        self.cambiar_a_proyecto.emit(pid)

    def _archivo_exportar_db(self):
        """Exporta el proyecto activo a un archivo SQLite (.db) independiente.
        Útil para compartirlo con otra instalación de ingePresupuestos."""
        import re as _re
        from PySide6.QtWidgets import QFileDialog, QMessageBox, QApplication
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        from core.exporter import exportar_proyecto_db

        nombre = (self._proy.get('nombre') if self._proy else None) or f"proyecto_{self.pid}"
        safe = _re.sub(r'[\\/:*?"<>|]', '_', nombre).strip() or f"proyecto_{self.pid}"
        sugerido = f"{safe}.db"
        ruta, _f = QFileDialog.getSaveFileName(
            self, "Exportar proyecto a SQLite (.db)", sugerido,
            "Base de datos SQLite (*.db)"
        )
        if not ruta:
            return
        if not ruta.lower().endswith('.db'):
            ruta += '.db'

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            exportar_proyecto_db(self.pid, ruta)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(
                self, "Exportar proyecto",
                f"No se pudo exportar el proyecto:\n{e}"
            )
            return
        QApplication.restoreOverrideCursor()

        res = QMessageBox.information(
            self, "Exportar proyecto",
            f"Proyecto exportado correctamente:\n\n{ruta}\n\n"
            f"Puedes importarlo en otra instalación desde el menu "
            f"Importar → ingePresupuestos (.db).",
            QMessageBox.StandardButton.Open | QMessageBox.StandardButton.Ok,
            QMessageBox.StandardButton.Ok,
        )
        if res == QMessageBox.StandardButton.Open:
            # Abre la carpeta contenedora del archivo en el explorador.
            import os
            QDesktopServices.openUrl(
                QUrl.fromLocalFile(os.path.dirname(ruta) or ruta)
            )

    def _archivo_reiniciar(self):
        """Relanza la aplicación. Cierra el proceso actual y arranca uno
        nuevo (mismo intérprete y argumentos). La BD auto-guarda, así que
        no hay riesgo de perder datos."""
        import sys
        from PySide6.QtCore import QProcess
        from PySide6.QtWidgets import QApplication, QMessageBox

        res = QMessageBox.question(
            self, "Reiniciar aplicación",
            "¿Reiniciar ingePresupuestos ahora?\n\n"
            "Se cerrará la ventana actual y se abrirá una nueva. Los "
            "cambios del proyecto ya están guardados automáticamente.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if res != QMessageBox.StandardButton.Yes:
            return
        QProcess.startDetached(sys.executable, sys.argv)
        QApplication.instance().quit()

    def _archivo_imprimir(self):
        """Diálogo con lista de tipos de reporte. Al seleccionar, genera el
        PDF temporal del tipo elegido y abre QPrintPreviewDialog para imprimir."""
        from PySide6.QtWidgets import (
            QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
            QListWidgetItem, QPushButton, QApplication, QMessageBox,
        )
        from PySide6.QtPrintSupport import QPrinter, QPrintPreviewDialog
        from core import pdf_reports as _pr
        import tempfile

        # Diálogo modal con la lista de tipos
        dlg = QDialog(self)
        dlg.setWindowTitle("Imprimir reporte")
        dlg.setMinimumWidth(440)
        dlg.setMinimumHeight(420)
        v = QVBoxLayout(dlg)
        v.setContentsMargins(20, 18, 20, 16)
        v.setSpacing(12)

        lbl = QLabel("Selecciona el tipo de reporte a imprimir:")
        lbl.setStyleSheet("background:transparent; border:none;")
        v.addWidget(lbl)

        lw = QListWidget()
        for key, nombre, desc in _pr.REPORT_TYPES:
            it = QListWidgetItem(nombre)
            it.setData(Qt.UserRole, key)
            it.setToolTip(desc)
            lw.addItem(it)
        lw.setCurrentRow(0)
        lw.itemDoubleClicked.connect(lambda _: dlg.accept())
        v.addWidget(lw, stretch=1)

        hl = QHBoxLayout()
        hl.addStretch()
        btn_cancel = QPushButton("Cancelar")
        btn_cancel.clicked.connect(dlg.reject)
        hl.addWidget(btn_cancel)
        btn_ok = QPushButton("Vista previa  →")
        btn_ok.setDefault(True)
        btn_ok.clicked.connect(dlg.accept)
        hl.addWidget(btn_ok)
        v.addLayout(hl)

        if dlg.exec() != QDialog.Accepted:
            return
        it = lw.currentItem()
        if it is None:
            return
        tipo = it.data(Qt.UserRole)

        # Generar PDF temporal del tipo elegido
        fp = tempfile.NamedTemporaryFile(
            prefix=f'imprimir_{tipo}_', suffix='.pdf', delete=False
        )
        fp.close()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            _pr.generar_pdf_archivo(tipo, self.pid, fp.name)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(
                self, "Imprimir reporte",
                f"No se pudo generar el PDF:\n{e}"
            )
            return
        QApplication.restoreOverrideCursor()

        # Vista previa de impresión
        printer = QPrinter(QPrinter.HighResolution)
        preview = QPrintPreviewDialog(printer, self)
        preview.setWindowTitle(f"Vista previa de impresión — {it.text()}")
        preview.resize(940, 760)
        preview.paintRequested.connect(
            lambda p, pdf=fp.name: self._paint_pdf_to_printer(pdf, p)
        )
        preview.exec()

    def _paint_pdf_to_printer(self, pdf_path: str, printer):
        """Renderiza cada página del PDF al QPrinter (usado por la vista
        previa de impresión). Espejo de ReportesView::_paint_pdf_a_printer."""
        from PySide6.QtGui import QPageLayout, QPainter
        from PySide6.QtPdf import QPdfDocument
        from PySide6.QtCore import QSize

        doc = QPdfDocument()
        doc.load(pdf_path)
        n = doc.pageCount()
        if n <= 0:
            return
        painter = QPainter(printer)
        try:
            layout = printer.pageLayout()
            paint_pts = layout.paintRect(QPageLayout.Unit.Point)
            dpi = printer.resolution()
            target_w_px = int(paint_pts.width() * dpi / 72.0)
            target_h_px = int(paint_pts.height() * dpi / 72.0)
            if target_w_px <= 0 or target_h_px <= 0:
                return
            for i in range(n):
                if i > 0:
                    printer.newPage()
                page_size_pts = doc.pagePointSize(i)
                pw, ph = page_size_pts.width(), page_size_pts.height()
                if pw <= 0 or ph <= 0:
                    continue
                scale = min(paint_pts.width() / pw, paint_pts.height() / ph)
                render_w = int(pw * scale * dpi / 72.0)
                render_h = int(ph * scale * dpi / 72.0)
                if render_w <= 0 or render_h <= 0:
                    continue
                img = doc.render(i, QSize(render_w, render_h))
                ox = max(0, (target_w_px - render_w) // 2)
                oy = max(0, (target_h_px - render_h) // 2)
                painter.drawImage(ox, oy, img)
        finally:
            painter.end()

    # ══════════════════════════════════════════════════════════════════════════
    # Centro de Reportes — vista anclada (page del root_stack)
    # ══════════════════════════════════════════════════════════════════════════

    def _abrir_centro_reportes(self):
        if not hasattr(self, '_reportes_view') or self._reportes_view is None:
            from views.reportes_view import ReportesView
            self._reportes_view = ReportesView(
                self.pid,
                self._proy.get('nombre', ''),
                on_back=lambda: self._root_stack.setCurrentIndex(0),
                parent=self,
            )
            self._root_stack.addWidget(self._reportes_view)
        idx = self._root_stack.indexOf(self._reportes_view)
        self._root_stack.setCurrentIndex(idx)
        # Diferimos la carga al siguiente frame para que el topbar/skeleton
        # aparezca instantáneamente y el usuario perciba navegación fluida.
        QTimer.singleShot(0, self._reportes_view.cargar)

    def _abrir_validador_ia(self):
        from views.ia_dialogs import ValidadorDialog
        dlg = ValidadorDialog(
            self.pid, self._proy.get('nombre', ''), parent=self
        )
        dlg.exec()

    def recibir_tip_externo(self, *args, **kwargs):
        """No-op defensivo: el footer rotativo se quitó a pedido del usuario.
        Las llamadas a `_TuxiaHelper.show_tip` ya no producen UI; el chat
        sigue accesible vía el botón 'Ayúdame' inline en la fila del CD."""
        return

    def _abrir_asistente_ia(self):
        """Toggle del chat IA del pie del panel derecho.

        Si NO estamos en la vista principal del proyecto (ej. cronograma),
        abre un `_ChatTuxiaDialog` flotante con el mismo tema terminal
        elementary OS que el chat embebido — para mantener consistencia
        visual.
        """
        # Detectar si estamos en otro stack (cronograma, reportes, etc.)
        if hasattr(self, '_root_stack') and self._root_stack.currentIndex() != 0:
            cron_active = (self._cron_view is not None
                           and self._root_stack.currentWidget() is self._cron_view)
            modo = 'Cronograma' if cron_active else 'Resumen'
            # Reusar la ventana si ya existe abierta para no clonar contexto
            existente = getattr(self, '_chat_floating', None)
            if existente is not None:
                try:
                    if existente.isVisible():
                        existente.raise_()
                        existente.activateWindow()
                        return
                except RuntimeError:
                    pass  # ventana ya destruida
            dlg = _ChatTuxiaDialog(self.pid, modo=modo,
                                    titulo=f"Tuxia · {modo}", parent=self)
            self._chat_floating = dlg
            dlg.show()
            return
        nuevo_estado = not self.btn_toggle_chat.isChecked()
        self.btn_toggle_chat.setChecked(nuevo_estado)
        self._toggle_chat_acu(nuevo_estado)

    # ══════════════════════════════════════════════════════════════════════════
    # Tuxia Helper — tips contextuales estilo Clippy
    # ══════════════════════════════════════════════════════════════════════════

    def _tuxia_check_proyecto(self):
        """Al abrir el proyecto, escanear y emitir tips relevantes.

        Orden de prioridad (solo se muestra el primero detectado):
          1. Estado solo lectura
          2. Saludo contextual (1 vez por sesión por proyecto)
          3. Fórmula polinómica ΣK ≠ 1.000 (no en admin. directa)
          4. Partidas sin metrado
          5. Partidas sin ACU
          6. Insumos duplicados con precios diferentes
        """
        if not hasattr(self, '_tuxia'):
            return
        # Si el chat IA ya está abierto, no mostrar saludo (sería redundante)
        if (hasattr(self, '_chat_splitter')
                and self._chat_splitter.sizes()[1] > 0):
            return
        # 1) Estado solo lectura
        if not self._editable:
            from core.config import ESTADOS_PROYECTO_NOMBRE
            est = ESTADOS_PROYECTO_NOMBRE.get(self._estado, self._estado)
            self._tuxia.show_tip(
                f"Este proyecto está «{est}». La mayoría de cambios "
                "están bloqueados (puedes ver pero no editar).",
                titulo="tuxia · solo lectura",
                key=f"solo_lectura:{self.pid}",
            )
            return
        # 2) Saludo contextual con mini resumen (1 vez por sesión, por proyecto)
        try:
            from core.database import get_db as _gdb
            _, totales = calcular_totales(self.pid)
            conn_s = _gdb()
            n_part = conn_s.execute(
                "SELECT COUNT(*) FROM partidas WHERE proyecto_id=? AND es_titulo=0",
                (self.pid,)
            ).fetchone()[0]
            # Proyecto vacío → ofrecer sugerir partidas (IA o plantilla)
            if n_part == 0:
                conn_s.close()
                self._tuxia.show_tip(
                    "<b>¡Bienvenido a tu nuevo proyecto!</b><br><br>"
                    "Aún no tienes partidas. ¿Quieres que te <b>sugiera "
                    "partidas típicas</b> usando IA o una plantilla local "
                    "(vivienda, agua, vías…)?<br><br>"
                    "Después podrás revisar y elegir cuáles importar.",
                    titulo="tuxia · proyecto vacío",
                    accion_id='sugerir_partidas',
                    accion_label="Sugerirme partidas",
                    key=f"sugerir_partidas:{self.pid}",
                    fade_ms=20000,
                )
                return
            top = conn_s.execute(
                "SELECT item, descripcion FROM partidas "
                "WHERE proyecto_id=? AND es_titulo=0 "
                "ORDER BY (COALESCE(metrado,0) * COALESCE(precio_unitario,0)) DESC "
                "LIMIT 1",
                (self.pid,)
            ).fetchone()
            conn_s.close()
            cd_fmt = fmt(totales.get('cd', 0), self._moneda)
            top_txt = ""
            if top:
                desc = (top['descripcion'] or '')[:38]
                top_txt = f"<br>Top costo: <b>{top['item']}</b> · {desc}"

            # Saludo personalizado con el nombre del usuario
            from utils.auth import usuario_actual as _ua
            usr = _ua()
            primer_nombre = ''
            if usr is not None:
                primer_nombre = (usr.nombre or usr.username or '').strip().split(' ')[0]
            hola = f"¡Hola {primer_nombre}!" if primer_nombre else "¡Hola!"

            # Memoria de sesión: ¿última partida que editó en este proyecto?
            mem = self._tuxia._qs   # QSettings("ingePresupuestos","tuxia")
            ult_part_id = mem.value(f"last_partida/{self.pid}", None, type=int)
            recordatorio = ""
            if ult_part_id:
                try:
                    conn_m = _gdb()
                    row = conn_m.execute(
                        "SELECT item, descripcion FROM partidas WHERE id=?",
                        (ult_part_id,)
                    ).fetchone()
                    conn_m.close()
                    if row:
                        d = (row['descripcion'] or '')[:38]
                        recordatorio = (f"<br>📌 Te quedaste en: "
                                         f"<b>{row['item']}</b> · {d}")
                except Exception:
                    pass

            saludo = (f"{hola} este proyecto tiene <b>{n_part}</b> partida(s) "
                      f"y CD <b>{cd_fmt}</b>.{top_txt}{recordatorio}<br><br>"
                      "Click en mí para abrir el chat.")
            self._tuxia.show_tip(
                saludo, titulo="tuxia · resumen",
                key=f"saludo_inicial:{self.pid}",
                fade_ms=14000,
            )
        except Exception:
            pass
        # 2) Detectar pendientes globales
        try:
            from core.asistente_local import pendientes as _pend
            # Inspeccionar conteos rápidos en BD
            conn = get_db()
            n_sin_metr = conn.execute(
                "SELECT COUNT(*) FROM partidas WHERE proyecto_id=? "
                "AND es_titulo=0 AND (metrado IS NULL OR metrado=0)",
                (self.pid,)
            ).fetchone()[0]
            n_sin_acu = conn.execute(
                "SELECT COUNT(*) FROM partidas p WHERE p.proyecto_id=? "
                "AND p.es_titulo=0 AND NOT EXISTS "
                "(SELECT 1 FROM acu_items WHERE partida_id=p.id)",
                (self.pid,)
            ).fetchone()[0]
            sum_k = conn.execute(
                "SELECT SUM(coeficiente) FROM formula_monomios WHERE proyecto_id=?",
                (self.pid,)
            ).fetchone()[0]
            conn.close()
        except Exception:
            return
        # La fórmula polinómica de reajuste NO aplica en obras por
        # Administración Directa (sólo en Contrata / Llave en mano / etc.),
        # por eso saltamos esa alerta para ese régimen.
        modalidad = (self._proy.get('modalidad') or '').strip().lower()
        es_admin_directa = 'administraci' in modalidad and 'directa' in modalidad

        # Prioridad: fórmula polinómica > metrados > ACU
        if sum_k is not None and not es_admin_directa:
            try:
                sk = float(sum_k)
                if sk > 0 and abs(sk - 1.0) > 0.001:
                    self._tuxia.show_tip(
                        f"Tu fórmula polinómica suma ΣK = {sk:.4f}, "
                        "debería ser exactamente 1.000.",
                        accion_id='ir_formula',
                        accion_label='Ir a Fórmula',
                        titulo="tuxia · fórmula polinómica",
                        key=f"formula_k:{self.pid}",
                    )
                    return
            except Exception:
                pass
        if n_sin_metr > 0:
            self._tuxia.show_tip(
                f"Detecté {n_sin_metr} partida(s) sin metrado. "
                "Puedo darte la lista completa.",
                accion_id='ver_pendientes',
                accion_label='Ver lista',
                titulo="tuxia · pendientes",
                key=f"sin_metr_proy:{self.pid}",
            )
            return
        if n_sin_acu > 0:
            self._tuxia.show_tip(
                f"Tienes {n_sin_acu} partida(s) sin ACU cargado.",
                accion_id='ver_pendientes',
                accion_label='Ver lista',
                titulo="tuxia · pendientes",
                key=f"sin_acu_proy:{self.pid}",
            )
            return
        # 6) Insumos duplicados con precios diferentes en el mismo proyecto
        try:
            conn2 = get_db()
            duplicados = conn2.execute(
                """SELECT r.descripcion,
                          COUNT(DISTINCT ROUND(COALESCE(ai.precio, r.precio, 0), 2)) as variantes,
                          MIN(COALESCE(ai.precio, r.precio, 0)) as p_min,
                          MAX(COALESCE(ai.precio, r.precio, 0)) as p_max
                   FROM acu_items ai
                     JOIN partidas p ON p.id = ai.partida_id
                     JOIN recursos r ON r.id = ai.recurso_id
                   WHERE p.proyecto_id = ?
                     AND SUBSTR(r.unidad,1,1) != '%'
                   GROUP BY ai.recurso_id
                   HAVING variantes > 1
                   ORDER BY (p_max - p_min) DESC
                   LIMIT 1""",
                (self.pid,)
            ).fetchone()
            conn2.close()
        except Exception:
            duplicados = None
        if duplicados:
            desc = (duplicados['descripcion'] or '')[:40]
            self._tuxia.show_tip(
                f"«{desc}» aparece en este proyecto con "
                f"precios distintos: S/ {duplicados['p_min']:.2f} ↔ "
                f"S/ {duplicados['p_max']:.2f}. ¿Quizá deba unificarse?",
                titulo="tuxia · precios duplicados",
                key=f"precios_dup:{self.pid}:{duplicados['descripcion']}",
                fade_ms=10000,
            )
            return
        # 7) Fórmula polinómica faltante (solo Contrata, no admin. directa)
        if not es_admin_directa and (sum_k is None or float(sum_k or 0) == 0):
            self._tuxia.show_tip(
                "Este proyecto es por <b>Contrata</b> pero no tiene "
                "<b>fórmula polinómica</b> configurada. La RNE la exige "
                "para reajustes de precios.",
                accion_id='ir_formula',
                accion_label='Ir a Fórmula',
                titulo="tuxia · falta fórmula polinómica",
                key=f"formula_missing:{self.pid}",
                fade_ms=12000,
            )
            return
        # 8) Hito XP — celebrar cuando el usuario alcanza milestones de partidas
        try:
            mem = self._tuxia._qs
            # Detectar cuántas partidas se agregaron desde la última visita
            # comparando contra la cuenta guardada por proyecto
            conn_xp = get_db()
            cnt_total = conn_xp.execute(
                "SELECT COUNT(*) FROM partidas WHERE proyecto_id=?",
                (self.pid,)
            ).fetchone()[0]
            conn_xp.close()
            cnt_prev = int(mem.value(f"part_count/{self.pid}", 0, type=int) or 0)
            if cnt_total > cnt_prev:
                delta = cnt_total - cnt_prev
                total_xp = int(mem.value("total_partidas_creadas", 0, type=int) or 0)
                total_xp += delta
                mem.setValue("total_partidas_creadas", total_xp)
                mem.setValue(f"part_count/{self.pid}", cnt_total)
            else:
                total_xp = int(mem.value("total_partidas_creadas", 0, type=int) or 0)

            milestones = [10, 50, 100, 250, 500, 1000, 2500, 5000, 10000]
            ya_celebrado = int(mem.value("xp_ult_milestone", 0, type=int) or 0)
            siguiente = next((m for m in milestones if m > ya_celebrado), None)
            if siguiente and total_xp >= siguiente:
                mem.setValue("xp_ult_milestone", siguiente)
                emojis = {10:'🌱', 50:'⚡', 100:'🚀', 250:'💪',
                          500:'🏆', 1000:'🎯', 2500:'⭐', 5000:'👑', 10000:'🐉'}
                self._tuxia.show_tip(
                    f"<b>{emojis.get(siguiente,'✨')} ¡{siguiente} partidas!</b><br><br>"
                    f"Llevas <b>{total_xp}</b> partidas creadas en total. "
                    "Sigues cogiendo el ritmo de un experto.",
                    titulo=f"tuxia · hito {siguiente} partidas",
                    key=f"xp_milestone:{siguiente}",
                    fade_ms=10000,
                )
                return
        except Exception:
            pass

    def _tuxia_check_partida(self, part_id: int):
        """Al cargar una partida, emitir tip si tiene problemas detectables.

        Checks ordenados por urgencia:
        1) Sin ACU
        2) Sin metrado
        3) Cantidades MO inconsistentes con cuadrilla/rendimiento×jornada
        """
        if not hasattr(self, '_tuxia'):
            return
        try:
            conn = get_db()
            p = conn.execute(
                "SELECT metrado, especificaciones, rendimiento, unidad FROM partidas "
                "WHERE id=?", (part_id,)
            ).fetchone()
            acu_items = conn.execute(
                "SELECT ai.id, ai.cuadrilla, ai.cantidad, r.tipo, r.unidad "
                "FROM acu_items ai JOIN recursos r ON r.id=ai.recurso_id "
                "WHERE ai.partida_id=?", (part_id,)
            ).fetchall()
            conn.close()
        except Exception:
            return
        if not p:
            return
        n_acu = len(acu_items)
        # 1) Sin ACU
        if n_acu == 0:
            self._tuxia.show_tip(
                "Esta partida aún no tiene insumos cargados en el ACU. "
                "Agrega recursos para que el precio unitario se calcule.",
                titulo="tuxia · ACU vacío",
                key=f"acu_vacio:{part_id}",
                fade_ms=8000,
            )
            return
        # 2) Sin metrado
        if not (p['metrado'] or 0):
            self._tuxia.show_tip(
                "Esta partida no tiene metrado. El parcial será 0 hasta "
                "que lo cargues (escribe en la columna metrado del árbol "
                "o usa la planilla detallada).",
                titulo="tuxia · sin metrado",
                key=f"sin_metrado:{part_id}",
                fade_ms=8000,
            )
            return
        # 3) Cantidades MO inconsistentes con la fórmula
        # (no aplica en partidas globales glb/est/serv: cantidad directa)
        rend = p['rendimiento'] or 0
        jornada = self._proy.get('jornada_laboral') or 8
        if rend > 0 and self._ed_presupuesto and not _partida_global(p['unidad']):
            inconsistentes = 0
            for it in acu_items:
                cuad = it['cuadrilla'] or 0
                cant = it['cantidad'] or 0
                unidad_l = (it['unidad'] or '').lower()
                por_dia = _recurso_por_dia(it['tipo'], it['unidad'])
                es_hora = (por_dia or it['tipo'] == 'MO'
                           or unidad_l in ('hh', 'hm', 'h-h', 'h-m', 'jph', 'jh')
                           or 'hora' in unidad_l)
                if cuad > 0 and es_hora:
                    esperado = (cuad / rend) * (1 if por_dia else jornada)
                    # Tolerancia 5% para evitar falsos positivos
                    if esperado > 0 and abs(cant - esperado) / esperado > 0.05:
                        inconsistentes += 1
            if inconsistentes > 0:
                self._tuxia.show_tip(
                    f"Detecté {inconsistentes} insumo(s) con cantidad MO que "
                    f"no coincide con la fórmula cuadrilla × jornada / "
                    f"rendimiento. Puedo recalcular ahora.",
                    accion_id=f'recalc_mo:{part_id}',
                    accion_label="Recalcular",
                    titulo="tuxia · cantidades MO",
                    key=f"mo_inconsistente:{part_id}",
                    fade_ms=10000,
                )
                return

    def _tuxia_recordar_backup(self):
        """Sugiere hacer un backup si pasaron > 45 min de actividad y nunca
        se ha hecho (o el último fue hace mucho)."""
        if not hasattr(self, '_tuxia') or self._tuxia is None:
            return
        # Verificar último backup en QSettings
        from datetime import datetime as _dt
        try:
            mem = self._tuxia._qs
            last_iso = mem.value("last_backup_iso", "", type=str) or ''
            horas = 999
            if last_iso:
                try:
                    last = _dt.fromisoformat(last_iso)
                    horas = (_dt.now() - last).total_seconds() / 3600.0
                except Exception:
                    pass
            if horas < 24:
                return  # backup reciente, no molestar
            self._tuxia.show_tip(
                "Llevas un buen rato editando. Te recomiendo hacer un "
                "<b>backup completo</b> de la BD desde <b>Exportar → Backup</b>.",
                titulo="tuxia · ¿hace cuánto no haces backup?",
                key=f"backup_recordatorio:{self.pid}",
                fade_ms=10000,
            )
        except Exception:
            pass

    def _abrir_sugerir_partidas(self):
        """Abre el dialog para sugerir e importar partidas a un proyecto vacío."""
        dlg = _DialogSugerirPartidas(self.pid, self._proy.get('nombre', ''),
                                       parent=self)
        if dlg.exec() == QDialog.Accepted:
            # Recargar el árbol de partidas y totales
            self.recargar_partidas()
            self.actualizar_total()

    def _on_tuxia_accion(self, accion_id: str):
        """Despacha acciones desde el botón 'Ir' del helper."""
        if accion_id == 'sugerir_partidas':
            self._abrir_sugerir_partidas()
        elif accion_id == 'ir_formula':
            self._ir_formula()
        elif accion_id == 'ver_pendientes':
            # Abre el chat y dispara /pendientes
            if not self.btn_toggle_chat.isChecked():
                self.btn_toggle_chat.setChecked(True)
                self._toggle_chat_acu(True)
            try:
                self._chat_acu._enviar('/pendientes')
            except Exception:
                pass
        elif accion_id.startswith('recalc_mo:'):
            try:
                part_id = int(accion_id.split(':', 1)[1])
                self._tuxia_recalcular_mo(part_id)
            except Exception:
                pass
        elif accion_id.startswith('generar_specs:'):
            try:
                part_id = int(accion_id.split(':', 1)[1])
                # Asegurar que la partida sea la actual
                if self._partida_actual_id != part_id:
                    self._partida_actual_id = part_id
                # Llevar al tab Especificaciones (idx 3)
                self.tabs.setCurrentIndex(3)
                self._ia_generar_spec()
            except Exception:
                pass
        elif accion_id == 'ir_metrados':
            self._ir_metrados()
        elif accion_id == 'ir_cronograma':
            self._ir_cronograma()

    def _tuxia_recalcular_mo(self, part_id: int):
        """Recalcula las cantidades MO de una partida según la fórmula
        canónica: cant = cuadrilla / rendimiento × jornada."""
        if not self._ed_presupuesto:
            QMessageBox.information(self, "Tuxia",
                "El proyecto no está en estado editable.")
            return
        conn = get_db()
        try:
            p = conn.execute(
                "SELECT rendimiento, unidad FROM partidas WHERE id=?", (part_id,)
            ).fetchone()
            if p and _partida_global(p['unidad']):
                return  # partida global: cantidad directa, no recalcular
            rend = (p['rendimiento'] if p else None) or 0
            jornada = self._proy.get('jornada_laboral') or 8
            if rend <= 0:
                QMessageBox.warning(self, "Tuxia",
                    "Esta partida no tiene rendimiento definido.")
                return
            items = conn.execute(
                "SELECT ai.id, ai.cuadrilla, r.tipo, r.unidad "
                "FROM acu_items ai JOIN recursos r ON r.id=ai.recurso_id "
                "WHERE ai.partida_id=?", (part_id,)
            ).fetchall()
            n = 0
            for it in items:
                cuad = it['cuadrilla'] or 0
                if cuad <= 0:
                    continue
                unidad_l = (it['unidad'] or '').lower()
                por_dia = _recurso_por_dia(it['tipo'], it['unidad'])
                es_hora = (por_dia or it['tipo'] == 'MO'
                           or unidad_l in ('hh', 'hm', 'h-h', 'h-m', 'jph', 'jh')
                           or 'hora' in unidad_l)
                if not es_hora:
                    continue
                nueva = (cuad / rend) * (1 if por_dia else jornada)
                conn.execute(
                    "UPDATE acu_items SET cantidad=? WHERE id=?",
                    (nueva, it['id'])
                )
                n += 1
            _recalcular_pu(conn, part_id)
            conn.commit()
        finally:
            conn.close()
        self.recargar_partidas()
        self.actualizar_total()
        if self._partida_actual_id == part_id:
            self.cargar_acu(part_id)
        # Confirmación discreta
        if hasattr(self, '_tuxia'):
            self._tuxia.show_tip(
                f"Listo, recalculé {n} cantidad(es) MO en esta partida.",
                titulo="tuxia · hecho", fade_ms=4000,
                key=f"recalc_done:{part_id}",
                once_per_session=False,
            )

    # ══════════════════════════════════════════════════════════════════════════
    # Navegación
    # ══════════════════════════════════════════════════════════════════════════

    def _ir_inicio(self):
        parent = self.parent()
        while parent and not hasattr(parent, 'stack'):
            parent = parent.parent()
        if parent:
            for i in range(parent.stack.count()):
                if parent.stack.widget(i).property("vista_nombre") == "dashboard":
                    parent.stack.setCurrentIndex(i)
                    return

    def _editar_proyecto(self):
        self.editar_proyecto_solicitado.emit(self.pid)

    # ══════════════════════════════════════════════════════════════════════════
    # Pestañas de proyectos abiertos
    # ══════════════════════════════════════════════════════════════════════════

    def actualizar_btn_sidebar(self, colapsado: bool):
        """Muestra u oculta el botón logo según si el sidebar está oculto."""
        self._btn_sb.setVisible(colapsado)

    def _construir_tab_simple(self):
        """Muestra solo el proyecto actual hasta que MainWindow llame set_proyectos_abiertos."""
        self._limpiar_tabs_proy()
        nombre = self._proy.get('nombre', '—')
        self._agregar_tab_widget(self.pid, nombre, activo=True)
        self._agregar_btn_proyectos()
        self._tabs_proy_hl.addStretch()

    def _limpiar_tabs_proy(self):
        while self._tabs_proy_hl.count():
            item = self._tabs_proy_hl.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _agregar_tab_widget(self, pid: int, nombre: str, activo: bool):
        tab = QFrame()
        tab.setMinimumWidth(90)
        tab.setMaximumWidth(220)
        tab.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tab.setStyleSheet(
            f"QFrame {{ background:{'rgba(255,255,255,0.18)' if activo else 'transparent'};"
            f" border-radius:6px; margin:4px 1px; }}"
            f"QFrame:hover {{ background:rgba(255,255,255,0.12); }}"
        )
        th = QHBoxLayout(tab)
        th.setContentsMargins(10, 0, 4, 0)
        th.setSpacing(4)

        lbl = QLabel(nombre)
        lbl.setStyleSheet(
            f"color:{'white' if activo else '#95A3AB'}; font-size:11px;"
            f" font-weight:{'700' if activo else '400'}; border:none; background:transparent;"
        )
        lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        lbl.setMinimumWidth(0)
        th.addWidget(lbl, stretch=1)

        btn_x = QPushButton("×")
        btn_x.setFixedSize(16, 16)
        btn_x.setStyleSheet(
            f"QPushButton {{ background:transparent; color:#95A3AB; border:none;"
            f" font-size:13px; font-weight:700; min-height:0; padding:0; }}"
            f"QPushButton:hover {{ color:white; }}"
        )
        btn_x.clicked.connect(lambda _, p=pid: self.cerrar_proyecto.emit(p))
        th.addWidget(btn_x)

        # Clic central (rueda) cierra la pestaña; clic izquierdo en inactiva la activa
        handler = lambda e, p=pid, act=activo: self._tab_mouse_press(e, p, act)
        tab.mousePressEvent = handler
        lbl.mousePressEvent = handler

        self._tabs_proy_hl.addWidget(tab, stretch=1)

    def _tab_mouse_press(self, e, pid: int, activo: bool):
        """Maneja clics sobre una pestaña de proyecto:
        - botón central (rueda) → cerrar la pestaña
        - botón izquierdo en pestaña inactiva → activarla
        """
        if e.button() == Qt.MiddleButton:
            self.cerrar_proyecto.emit(pid)
        elif e.button() == Qt.LeftButton and not activo:
            self.cambiar_a_proyecto.emit(pid)

    def _agregar_btn_proyectos(self):
        """Botón ⊞ para volver al listado de proyectos."""
        btn = QPushButton("+")
        btn.setFixedSize(26, 26)
        btn.setStyleSheet(
            f"QPushButton {{ background:transparent; color:#95A3AB; border:none;"
            f" border-radius:4px; font-size:16px; font-weight:700; min-height:0; padding:0 2px; }}"
            f"QPushButton:hover {{ background:rgba(255,255,255,0.15); color:white; }}"
        )
        from utils.tooltip import set_tooltip
        set_tooltip(btn, "Abrir otro proyecto")
        btn.clicked.connect(self.ir_a_proyectos.emit)
        self._tabs_proy_hl.addWidget(btn)

    def set_proyectos_abiertos(self, proyectos: list[dict]):
        """Llamado por MainWindow cuando cambia la lista de proyectos abiertos.
        proyectos = [{'pid': int, 'nombre': str}, ...]
        """
        self._limpiar_tabs_proy()
        for p in proyectos:
            self._agregar_tab_widget(p['pid'], p['nombre'], activo=(p['pid'] == self.pid))
        self._agregar_btn_proyectos()
        self._tabs_proy_hl.addStretch()

    def _recalcular_estado_flags(self):
        """Deriva `self._estado` y las banderas de edición granulares
        (`_ed_presupuesto/_ed_pie/_ed_specs/_ed_cronograma` + `_editable`)
        desde `self._proy`. El rol 'invitado' fuerza todo a solo lectura.
        Llamado en __init__ y tras editar el proyecto (cambio de estado)."""
        from core.config import puede_editar as _pe
        self._estado = (self._proy.get('estado') or 'elaboracion')
        rol = getattr(self.usuario, 'rol', 'usuario') if self.usuario else 'usuario'
        _is_invitado = (rol == 'invitado')
        self._ed_presupuesto = _pe(self._estado, 'presupuesto') and not _is_invitado
        self._ed_pie         = _pe(self._estado, 'pie')         and not _is_invitado
        self._ed_specs       = _pe(self._estado, 'specs')       and not _is_invitado
        self._ed_cronograma  = _pe(self._estado, 'cronograma')  and not _is_invitado
        self._editable = (self._ed_presupuesto and self._ed_pie
                          and self._ed_specs and self._ed_cronograma)

    # Colores canónicos de estado (espejo de dashboard_view.ESTADO_COLOR):
    # bg = shade 100 elementary OS, fg = slate oscuro.
    _ESTADO_PILL_COLOR = {
        'elaboracion': ('#FFC27D', '#273445'),   # Orange 100
        'revision':    ('#8CD5FF', '#273445'),   # BlueBerry 100
        'aprobado':    ('#9BDB4D', '#273445'),   # Lime 300
        'ejecutado':   ('#FF8C82', '#273445'),   # Strawberry 100
    }

    def _refrescar_pill_estado(self):
        """Actualiza el botón-pill de estado del topbar según `self._estado`.
        SIEMPRE visible (incl. elaboración). Muestra ▾ y permite cambiar el
        estado salvo para invitados (solo lectura)."""
        pill = getattr(self, '_pill_estado', None)
        if pill is None:
            return
        from core.config import ESTADOS_PROYECTO_NOMBRE
        est_nombre = ESTADOS_PROYECTO_NOMBRE.get(self._estado, self._estado)
        bg, fg = self._ESTADO_PILL_COLOR.get(self._estado, ('#E2E8F0', '#273445'))
        rol = getattr(self.usuario, 'rol', 'usuario') if self.usuario else 'usuario'
        puede = (rol != 'invitado')
        icono = '🔒 ' if self._estado != 'elaboracion' else '🔓 '
        flecha = '  ▾' if puede else ''
        pill.setText(f"{icono}{est_nombre}{flecha}")
        pill.setEnabled(puede)
        pill.setCursor(Qt.PointingHandCursor if puede else Qt.ArrowCursor)
        editables = [n for n, f in (("presupuesto", self._ed_presupuesto),
                                    ("pie", self._ed_pie), ("specs", self._ed_specs),
                                    ("cronograma", self._ed_cronograma)) if f]
        sub = ("Editable: " + ", ".join(editables)) if editables else "Solo lectura"
        pill.setToolTip(
            f"Estado: {est_nombre}\n{sub}\n\n"
            + ("Clic para cambiar el estado del proyecto." if puede else
               "Los invitados no pueden cambiar el estado.")
        )
        pill.setStyleSheet(
            f"QPushButton {{ background:{bg}; color:{fg}; border:none;"
            f"  border-radius:11px; padding:4px 12px; font-size:11px;"
            f"  font-weight:700; letter-spacing:0.3px; }}"
            f"QPushButton:hover {{ border:1.5px solid {fg}; padding:2.5px 10.5px; }}"
            f"QPushButton:disabled {{ color:{fg}; }}"
        )

    def _menu_cambiar_estado(self):
        """Menú desplegable bajo el pill para cambiar el estado del proyecto."""
        rol = getattr(self.usuario, 'rol', 'usuario') if self.usuario else 'usuario'
        if rol == 'invitado':
            return
        from core.config import ESTADOS_PROYECTO, ESTADOS_PROYECTO_NOMBRE
        menu = QMenu(self)
        _emoji = {'elaboracion': '🔓', 'revision': '🔍',
                  'aprobado': '✅', 'ejecutado': '🏗'}
        for est in ESTADOS_PROYECTO:
            nombre = ESTADOS_PROYECTO_NOMBRE.get(est, est)
            marca = '  ✓' if est == self._estado else ''
            act = menu.addAction(f"{_emoji.get(est, '')}  {nombre}{marca}")
            act.setData(est)
            act.setEnabled(est != self._estado)
        accion = menu.exec(self._pill_estado.mapToGlobal(
            self._pill_estado.rect().bottomLeft()))
        if accion is not None:
            self._aplicar_cambio_estado(accion.data())

    def _aplicar_cambio_estado(self, nuevo: str):
        """Persiste el nuevo estado y refresca la vista in-place (pill,
        banderas de edición, bloqueo/desbloqueo de widgets, totales)."""
        if not nuevo or nuevo == self._estado:
            return
        conn = get_db()
        try:
            conn.execute("UPDATE proyectos SET estado=? WHERE id=?",
                         (nuevo, self.pid))
            conn.commit()
        finally:
            conn.close()
        self._proy['estado'] = nuevo
        self._recalcular_estado_flags()
        self._refrescar_pill_estado()
        self._aplicar_modo_solo_lectura()   # reversible
        self.recargar_partidas()
        self.actualizar_total()
        # Si Control de Obra está abierto, refrescar su aviso de estado.
        if getattr(self, '_control_view', None) is not None:
            self._control_view._proy = self._proy
            if self._root_stack.currentWidget() is self._control_view:
                self._control_view.cargar()

    def recargar_tras_edicion(self):
        """Llamado por MainWindow al volver del formulario de edición."""
        self._proy   = self._cargar_proyecto()
        self._moneda = self._proy.get('moneda', 'Soles')
        # Recalcular estado/banderas: un cambio de estado (p.ej. aprobado →
        # elaboración) debe desbloquear la edición y refrescar la pill SIN
        # reconstruir la vista. Antes esto no ocurría y el presupuesto seguía
        # bloqueado con el estado viejo.
        self._recalcular_estado_flags()
        self._refrescar_pill_estado()
        self.recargar_partidas()
        self._aplicar_modo_solo_lectura()   # reversible: re/des-bloquea widgets
        self.actualizar_total()
        # Propagar al cronograma si ya existe: sincronizar su copia del proyecto
        # (plazo, fechas, jornada…) y recargarlo si está visible, para que el
        # plazo y la línea de «fin de plazo» reflejen la edición sin tener que
        # salir y volver a entrar.
        if getattr(self, '_cron_view', None) is not None:
            self._cron_view._proy   = self._proy
            self._cron_view._moneda = self._proy.get('moneda', 'Soles')
            if self._root_stack.currentWidget() is self._cron_view:
                self._cron_view.cargar()
        # Igual para Control de Obra (lee moneda/estado del proyecto).
        if getattr(self, '_control_view', None) is not None:
            self._control_view._proy = self._proy
            if self._root_stack.currentWidget() is self._control_view:
                self._control_view.cargar()

    def _completar_panel_tabs(self):
        """Segunda etapa de la construcción (ver _build_ui): reemplaza el
        placeholder del splitter por el panel real de tabs y encadena el
        ajuste de layout y la carga de datos."""
        try:
            panel = self._make_panel_tabs()
            self.hsplit.replaceWidget(1, panel)
            self._panel_tabs_ph.deleteLater()
        except RuntimeError:
            return   # la pestaña se cerró antes de completarse
        self.hsplit.setStretchFactor(0, 55)
        self.hsplit.setStretchFactor(1, 45)
        self._restaurar_splitters()
        self._on_resize_settled()
        if not self._editable:
            self._aplicar_modo_solo_lectura()
        QTimer.singleShot(0, self._cargar_datos_inicial)

    def _cargar_datos_inicial(self):
        """Carga diferida (un frame después del show) de partidas + total.
        Permite que la cáscara del proyecto sea visible al instante para
        que la apertura no se sienta "frizada"."""
        self.recargar_partidas()
        self.actualizar_total()

    def _ir_metrados(self):
        # Recrear la Hoja si no existe o si cambió la editabilidad (p.ej. el
        # usuario cambió el estado del proyecto desde el chip).
        ed = self._ed_presupuesto
        mv = getattr(self, '_metrados_view', None)
        if mv is None or getattr(mv, '_editable', None) != ed:
            if mv is not None:
                self._root_stack.removeWidget(mv)
                mv.deleteLater()
            from views.metrados_view import MetradosView
            self._metrados_view = MetradosView(
                self.pid,
                self._proy.get('nombre', ''),
                on_back=self._volver_de_metrados,
                parent=self,
                editable=ed,
            )
            self._root_stack.addWidget(self._metrados_view)
        idx = self._root_stack.indexOf(self._metrados_view)
        self._root_stack.setCurrentIndex(idx)
        QTimer.singleShot(0, self._metrados_view.cargar)

    def _volver_de_metrados(self):
        """Al volver de la Hoja de Metrados, los metrados editados cambiaron
        partida.metrado → refrescar presupuesto, totales y la planilla de la
        partida abierta para que se vea el efecto."""
        self._root_stack.setCurrentIndex(0)
        # Capturar la partida activa ANTES de recargar (recargar_partidas
        # puede reiniciar la selección).
        _pid = getattr(self, '_partida_actual_id', None)
        self.recargar_partidas()
        self.actualizar_total()
        if _pid is not None:
            try:
                # Auto: recarga la planilla correcta (acero o metrados normal)
                # según lo que tenga la partida — así el acero editado en la
                # Hoja también se refleja en la planilla lateral.
                self._cargar_metrados_auto(_pid)
            except Exception:
                pass

    def _ir_cronograma(self, tab_idx: int = 0):
        """Navega a la vista Cronograma. `tab_idx` selecciona la pestaña
        interna: 0=Gantt, 1=Valorizado, 2=Adquisiciones, 3=Curva S."""
        if self._cron_view is None:
            from views.cronograma_view import CronogramaView
            self._cron_view = CronogramaView(
                self.pid, self._proy,
                on_back=lambda: self._root_stack.setCurrentIndex(0),
                parent=self,
                on_editar=self._editar_proyecto,
            )
            self._root_stack.addWidget(self._cron_view)
        else:
            # El proyecto pudo editarse (plazo, fechas, jornada…) desde que se
            # construyó la vista. `recargar_tras_edicion` reasigna self._proy a
            # un dict nuevo, pero el cronograma conserva su referencia al viejo;
            # sincronizar antes de cargar para que plazo y «fin de plazo» se
            # recalculen con los datos actuales.
            self._cron_view._proy = self._proy
        idx = self._root_stack.indexOf(self._cron_view)
        self._root_stack.setCurrentIndex(idx)
        QTimer.singleShot(0, self._cron_view.cargar)
        if tab_idx:
            # Después de cargar, activar la pestaña pedida.
            QTimer.singleShot(0, lambda: self._cron_view.mostrar_tab(tab_idx))

    def _ir_control_obra(self, tab_idx: int = 0):
        """Navega a la vista Control de Obra (valorizaciones, avance, etc.).
        Se ancla al root_stack igual que Cronograma; SOLO lee del presupuesto."""
        if self._control_view is None:
            from views.control_obra_view import ControlObraView
            self._control_view = ControlObraView(
                self.pid, self._proy,
                on_back=lambda: self._root_stack.setCurrentIndex(0),
                parent=self,
                on_editar=self._editar_proyecto,
            )
            self._root_stack.addWidget(self._control_view)
        else:
            self._control_view._proy = self._proy
        idx = self._root_stack.indexOf(self._control_view)
        self._root_stack.setCurrentIndex(idx)
        QTimer.singleShot(0, self._control_view.cargar)
        if tab_idx:
            QTimer.singleShot(0, lambda: self._control_view.mostrar_tab(tab_idx))

    def _build_cronograma_menu(self):
        """QMenu del botón "Cronogramas ▾" del topbar. Atajos directos a
        cada sub-pestaña de la vista Cronograma."""
        from PySide6.QtWidgets import QMenu
        from PySide6.QtGui import QAction
        from utils.i18n import tr
        menu = QMenu(self)

        opciones = [
            (tr("Cronograma") + " Gantt",   0),
            (tr("Cronograma") + " Valorizado", 1),
            (tr("Insumos") + " - Adquisición", 2),
            ("Curva S",                     3),
        ]
        for label, idx in opciones:
            a = QAction(label, self)
            a.triggered.connect(lambda _c=False, i=idx: self._ir_cronograma(i))
            menu.addAction(a)
        return menu

    def _build_control_obra_menu(self):
        """QMenu del botón "Control de Obra ▾" del topbar. Atajos directos a cada
        pestaña del módulo de ejecución de obra."""
        from PySide6.QtWidgets import QMenu
        from PySide6.QtGui import QAction
        menu = QMenu(self)
        opciones = [
            ("Requerimientos",   0),
            ("Almacén",          1),
            ("Cuaderno de obra", 2),
            ("Valorizaciones",   3),
            ("Curva S real",     4),
        ]
        for label, idx in opciones:
            a = QAction(label, self)
            a.triggered.connect(lambda _c=False, i=idx: self._ir_control_obra(i))
            menu.addAction(a)
        return menu

    def _build_ia_menu(self):
        """QMenu del botón "IA ▾" del topbar. Reúne Validador, Asistente y
        la pantalla de Configuración de proveedores/API keys."""
        from PySide6.QtWidgets import QMenu
        from PySide6.QtGui import QAction
        from utils.i18n import tr
        menu = QMenu(self)

        a_val = QAction(tr("Revisar proyecto con IA") + "…", self)
        a_val.triggered.connect(self._abrir_validador_ia)
        menu.addAction(a_val)

        a_asis = QAction(tr("Asistente del proyecto"), self)
        a_asis.triggered.connect(self._abrir_asistente_ia)
        menu.addAction(a_asis)

        menu.addSeparator()

        a_cfg = QAction(tr("Configuración") + " IA…", self)
        a_cfg.triggered.connect(self.ir_a_ia.emit)
        menu.addAction(a_cfg)
        return menu

    def _build_ayuda_menu(self):
        """QMenu del botón "?" del topbar. Reúne ayuda, info del producto y
        acciones de licencia/actualización."""
        from PySide6.QtWidgets import QMenu
        from PySide6.QtGui import QAction, QDesktopServices, QKeySequence
        from PySide6.QtCore import QUrl
        menu = QMenu(self)

        a_manual = QAction("Manual de usuario…", self)
        a_manual.triggered.connect(self._ayuda_manual)
        menu.addAction(a_manual)

        a_atajos = QAction("Atajos de teclado…", self)
        a_atajos.setShortcut(QKeySequence("F1"))
        a_atajos.triggered.connect(self._mostrar_atajos)
        menu.addAction(a_atajos)

        menu.addSeparator()

        a_web = QAction("Sitio web", self)
        a_web.triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://ingepresupuestos.com"))
        )
        menu.addAction(a_web)

        a_lic = QAction("Licencia…", self)
        a_lic.triggered.connect(self._ayuda_licencia)
        menu.addAction(a_lic)

        a_upd = QAction("Comprobar actualizaciones…", self)
        a_upd.triggered.connect(self._ayuda_buscar_actualizaciones)
        menu.addAction(a_upd)

        menu.addSeparator()

        a_about = QAction("Acerca de…", self)
        a_about.triggered.connect(self.ir_a_acerca.emit)
        menu.addAction(a_about)
        return menu

    def _ayuda_manual(self):
        QMessageBox.information(
            self, "Manual de usuario",
            "El manual de usuario en línea estará disponible próximamente "
            "en ingepresupuestos.com/manual.\n\n"
            "Mientras tanto: F1 muestra los atajos de teclado, y Tuxia "
            "(asistente IA) responde dudas sobre cualquier pantalla."
        )

    def _ayuda_licencia(self):
        from views.licencia_dialog import mostrar_dialogo_licencia
        mostrar_dialogo_licencia(self)

    def _ayuda_buscar_actualizaciones(self):
        from views.update_dialog import lanzar_check
        lanzar_check(self, silencioso=False)

    def _ir_formula(self):
        if not hasattr(self, '_formula_view') or self._formula_view is None:
            from views.formula_view import FormulaView
            self._formula_view = FormulaView(
                self.pid,
                self._proy.get('nombre', ''),
                on_back=lambda: self._root_stack.setCurrentIndex(0),
                parent=self,
            )
            self._root_stack.addWidget(self._formula_view)
        idx = self._root_stack.indexOf(self._formula_view)
        self._root_stack.setCurrentIndex(idx)
        QTimer.singleShot(0, self._formula_view.cargar)

    def _ir_pie(self):
        self._root_stack.setCurrentIndex(1)
        QTimer.singleShot(0, self.cargar_pie)

    # ═════════════════════════════��════════════════════════════════════════════
    # Sub-presupuestos
    # ═══════════���════════════════════════════════���═════════════════════════════

    def _cargar_sub_pptos(self):
        """Reconstruye la barra de pestañas de sub-presupuestos."""
        from utils.i18n import tr
        conn = get_db()
        subs = conn.execute(
            "SELECT id, nombre FROM sub_presupuestos WHERE proyecto_id=? ORDER BY orden, id",
            (self.pid,)
        ).fetchall()
        conn.close()

        # Limpiar barra existente
        while self._tab_bar_hl.count():
            item = self._tab_bar_hl.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        nombre_principal = self._proy.get('sub_presupuesto') or 'Principal'
        tabs = [{'id': None, 'nombre': nombre_principal}] + [dict(s) for s in subs]

        for tab in tabs:
            tid    = tab['id']
            activo = (tid == self._sub_ppto_id)
            btn = _SubPptoTab(tab['nombre'], editable=True,
                              borrable=(tid is not None),
                              parent=self._tab_bar_frame)
            btn.setFixedHeight(26)
            # Ancho natural según texto, acotado entre 80-220 px. Las que no
            # quepan disparan scroll horizontal en el QScrollArea contenedor.
            btn.setMinimumWidth(80)
            btn.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            # Estilo tipo pestaña real: borde inferior solo al activo, fondo
            # gris suave para inactivos para que se distingan del frame.
            if activo:
                btn.setStyleSheet(
                    f"QPushButton {{ background:white;"
                    f" border:1px solid {SILVER_300}; border-bottom:none;"
                    f" border-top-left-radius:6px; border-top-right-radius:6px;"
                    f" border-bottom-left-radius:0; border-bottom-right-radius:0;"
                    f" padding:0 12px; font-size:11px; font-weight:700;"
                    f" color:{SLATE_700}; min-height:0; }}"
                )
            else:
                btn.setStyleSheet(
                    f"QPushButton {{ background:#DDE2EA;"
                    f" border:1px solid {SILVER_300}; border-bottom:none;"
                    f" border-top-left-radius:6px; border-top-right-radius:6px;"
                    f" border-bottom-left-radius:0; border-bottom-right-radius:0;"
                    f" padding:0 12px; font-size:11px; font-weight:500;"
                    f" color:{SLATE_500}; min-height:0; }}"
                    f"QPushButton:hover {{ background:#E8EBF0; color:{SLATE_700}; }}"
                )
            btn.clicked.connect(lambda _, t=tid: self._on_sub_ppto_cambiado(t))
            if tid is None:
                btn.renombrar.connect(self._renombrar_principal)
            else:
                btn.renombrar.connect(lambda nuevo, t=tid: self._renombrar_sub_ppto(t, nuevo))
                btn.eliminar.connect(lambda t=tid, n=tab['nombre']: self._eliminar_sub_ppto(t, n))
            btn.copiar.connect(lambda t=tid, n=tab['nombre']: self._copiar_subppto(t, n))
            btn.pegar_sub.connect(self._pegar_subppto)
            self._tab_bar_hl.addWidget(btn)

        # Botón "+" pegado al lado de las pestañas, mismo estilo pasivo
        btn_add = QPushButton("+")
        btn_add.setFixedSize(24, 24)
        btn_add.setToolTip(tr("Nuevo sub-presupuesto"))
        btn_add.setStyleSheet(
            f"QPushButton {{ background:#D6DCE8; color:{SLATE_500}; border:none;"
            f" border-radius:4px; font-size:16px; font-weight:700; min-height:0; padding:0; }}"
            f"QPushButton:hover {{ background:{BLUE_500}; color:white; }}"
        )
        btn_add.clicked.connect(self._nuevo_sub_ppto)
        self._tab_bar_hl.addWidget(btn_add)
        # Stretch al final → cuando hay pocas pestañas quedan agrupadas al
        # inicio sin huecos entre ellas. Cuando hay muchas y no caben, el
        # QScrollArea externo activa scroll horizontal automáticamente.
        self._tab_bar_hl.addStretch(1)
        # El bloque CD vive fuera del scroll (en _make_panel_presupuesto),
        # siempre visible al ras derecho aunque haya muchas pestañas.
        self._lbl_cd_k.show()
        self.lbl_cd.show()

    def _on_sub_ppto_cambiado(self, sub_id):
        from utils.i18n import tr
        self._sub_ppto_id = sub_id
        self._partida_actual_id = None
        self.tbl_acu.setRowCount(0)
        self.lbl_acu_titulo.setText(tr("Seleccione una partida"))
        self._cargar_sub_pptos()   # redibuja tabs con nuevo activo
        self.recargar_partidas()
        self.actualizar_total()

    def _nuevo_sub_ppto(self):
        if not self._require_editable("crear sub-presupuestos"):
            return
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout
        dlg = QDialog(self)
        dlg.setWindowTitle("Nuevo sub-presupuesto")
        dlg.setFixedSize(340, 120)
        dlg.setStyleSheet(
            "QDialog { background:white; }"
            f"QLabel {{ color:{SLATE_700}; background:transparent; }}"
            f"QLineEdit {{ background:white; color:{SLATE_700};"
            f" border:1px solid {SILVER_300}; border-radius:6px; padding:0 8px; }}"
            f"QLineEdit:focus {{ border:1.5px solid {BLUE_500}; }}"
            f"QPushButton {{ background:#F0F1F2; color:{SLATE_700};"
            f" border:1px solid {SILVER_300}; border-radius:6px;"
            f" padding:5px 14px; min-width:80px; }}"
            f"QPushButton:hover {{ background:#E8EAED; }}"
        )
        vl = QVBoxLayout(dlg)
        vl.setContentsMargins(16, 16, 16, 14)
        vl.setSpacing(8)
        inp = QLineEdit()
        inp.setPlaceholderText("Ej. Cerco Perimétrico, Piscina, Módulo A…")
        inp.setMinimumHeight(32)
        inp.returnPressed.connect(dlg.accept)
        vl.addWidget(QLabel("Nombre del sub-presupuesto:"))
        vl.addWidget(inp)
        hl = QHBoxLayout()
        hl.addStretch()
        b_can = QPushButton("Cancelar"); b_can.clicked.connect(dlg.reject)
        b_ok  = QPushButton("Crear")
        b_ok.setStyleSheet(
            f"background:{BLUE_500}; color:white; border:none;"
            f" border-radius:6px; padding:4px 16px;"
        )
        b_ok.clicked.connect(dlg.accept)
        hl.addWidget(b_can); hl.addWidget(b_ok)
        vl.addLayout(hl)

        if not dlg.exec():
            return
        nombre = inp.text().strip()
        if not nombre:
            return

        conn = get_db()
        orden = conn.execute(
            "SELECT COALESCE(MAX(orden),0)+1 FROM sub_presupuestos WHERE proyecto_id=?",
            (self.pid,)
        ).fetchone()[0]
        cur = conn.execute(
            "INSERT INTO sub_presupuestos (proyecto_id, nombre, orden) VALUES (?,?,?)",
            (self.pid, nombre, orden)
        )
        nuevo_id = cur.lastrowid
        conn.commit()
        conn.close()

        self._on_sub_ppto_cambiado(nuevo_id)

    def _copiar_subppto(self, tid, nombre: str):
        """Copia el sub-presupuesto completo (nombre + partidas con metrados/
        ACU/acero/specs) al clipboard de sesión, para pegarlo en otro proyecto."""
        conn = get_db()
        n = _pclip.copiar_subppto(conn, self.pid, tid, nombre)
        conn.close()
        win = self.window()
        if hasattr(win, 'statusBar') and win.statusBar():
            win.statusBar().showMessage(
                f"Sub-presupuesto «{nombre}» copiado ({n} partidas). "
                "Clic derecho en una pestaña → Pegar sub-presupuesto.", 6000)

    def _pegar_subppto(self):
        """Crea un sub-presupuesto nuevo en este proyecto con el contenido del
        clipboard de sub-presupuestos (evita colisión de nombre con « (n)»)."""
        if not self._require_editable("pegar sub-presupuesto"):
            return
        if not _pclip.hay_subppto_clipboard():
            return
        nombre = _pclip.nombre_subppto_clipboard()
        conn = get_db()
        existentes = {r[0] for r in conn.execute(
            "SELECT nombre FROM sub_presupuestos WHERE proyecto_id=?", (self.pid,)
        ).fetchall()}
        existentes.add(self._proy.get('sub_presupuesto') or 'Principal')
        final = nombre or 'Sub-presupuesto'
        i = 2
        while final in existentes:
            final = f"{nombre} ({i})"
            i += 1
        try:
            orden = conn.execute(
                "SELECT COALESCE(MAX(orden),0)+1 FROM sub_presupuestos "
                "WHERE proyecto_id=?", (self.pid,)
            ).fetchone()[0]
            cur = conn.execute(
                "INSERT INTO sub_presupuestos (proyecto_id, nombre, orden) "
                "VALUES (?,?,?)", (self.pid, final, orden))
            nuevo_id = cur.lastrowid
            _pclip.pegar_subppto(conn, self.pid, nuevo_id)
            conn.commit()
        except Exception as e:
            conn.rollback()
            conn.close()
            QMessageBox.critical(self, "Pegar sub-presupuesto", f"Error:\n{e}")
            return
        conn.close()
        self._on_sub_ppto_cambiado(nuevo_id)
        win = self.window()
        if hasattr(win, 'statusBar') and win.statusBar():
            win.statusBar().showMessage(f"Sub-presupuesto «{final}» pegado.", 4000)

    def _renombrar_principal(self, nuevo_nombre: str):
        if not self._require_editable("renombrar"):
            return
        conn = get_db()
        conn.execute("UPDATE proyectos SET sub_presupuesto=? WHERE id=?",
                     (nuevo_nombre, self.pid))
        conn.commit()
        conn.close()
        self._proy['sub_presupuesto'] = nuevo_nombre
        self._cargar_sub_pptos()

    def _renombrar_sub_ppto(self, sub_id: int, nuevo_nombre: str):
        if not self._require_editable("renombrar sub-presupuestos"):
            return
        conn = get_db()
        conn.execute("UPDATE sub_presupuestos SET nombre=? WHERE id=?",
                     (nuevo_nombre, sub_id))
        conn.commit()
        conn.close()
        self._cargar_sub_pptos()

    def _eliminar_sub_ppto(self, sub_id: int, nombre: str):
        """Elimina un sub-presupuesto. Sus partidas se mueven al destino
        elegido (Principal u otro sub-presupuesto del mismo proyecto)."""
        if not self._require_editable("eliminar sub-presupuestos"):
            return
        conn = get_db()
        n_part = conn.execute(
            "SELECT COUNT(*) FROM partidas WHERE proyecto_id=? AND sub_presupuesto_id=?",
            (self.pid, sub_id)
        ).fetchone()[0]
        otros = conn.execute(
            "SELECT id, nombre FROM sub_presupuestos "
            "WHERE proyecto_id=? AND id<>? ORDER BY orden, id",
            (self.pid, sub_id)
        ).fetchall()
        conn.close()

        # Diálogo de confirmación con selector de destino si hay partidas
        # y al menos un destino alternativo además del Principal.
        nombre_principal = self._proy.get('sub_presupuesto') or 'Principal'
        destino_id: int | None = None   # None = Principal

        borrar_partidas = False
        if n_part == 0:
            resp = QMessageBox.question(
                self, "Eliminar sub-presupuesto",
                f"¿Eliminar el sub-presupuesto «{nombre}»?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if resp != QMessageBox.Yes:
                return
        else:
            from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout,
                                            QLabel, QComboBox, QPushButton,
                                            QRadioButton, QButtonGroup)
            dlg = QDialog(self)
            dlg.setWindowTitle("Eliminar sub-presupuesto")
            dlg.setMinimumWidth(420)
            dlg.setStyleSheet(
                "QDialog { background:white; }"
                f"QLabel {{ color:{SLATE_700}; background:transparent; }}"
                f"QRadioButton {{ color:{SLATE_700}; background:transparent;"
                f" padding:3px; }}"
                f"QComboBox {{ background:white; color:{SLATE_700};"
                f" border:1px solid {SILVER_300}; border-radius:6px;"
                f" padding:3px 8px; }}"
                f"QPushButton {{ background:#F0F1F2; color:{SLATE_700};"
                f" border:1px solid {SILVER_300}; border-radius:6px;"
                f" padding:5px 14px; min-width:80px; }}"
                f"QPushButton:hover {{ background:#E8EAED; }}"
            )
            vl = QVBoxLayout(dlg)
            vl.setContentsMargins(18, 16, 18, 14)
            vl.setSpacing(10)
            lbl = QLabel(
                f"¿Eliminar el sub-presupuesto «{nombre}»?\n"
                f"Tiene {n_part} partida(s). Elige qué hacer con ellas:"
            )
            lbl.setWordWrap(True)
            vl.addWidget(lbl)

            grp = QButtonGroup(dlg)
            rb_mover = QRadioButton("Mover las partidas a:")
            rb_mover.setChecked(True)
            grp.addButton(rb_mover)
            vl.addWidget(rb_mover)

            cmb = QComboBox()
            cmb.setMinimumHeight(28)
            cmb.addItem(f"{nombre_principal} (Principal)", None)
            for o in otros:
                cmb.addItem(o['nombre'], o['id'])
            _hl_cmb = QHBoxLayout()
            _hl_cmb.addSpacing(22)
            _hl_cmb.addWidget(cmb, 1)
            vl.addLayout(_hl_cmb)

            rb_borrar = QRadioButton(
                f"Eliminar también las {n_part} partidas (no recuperable)"
            )
            rb_borrar.setStyleSheet(f"color:{_C.error};")
            grp.addButton(rb_borrar)
            vl.addWidget(rb_borrar)

            # Habilitar/deshabilitar combo según radio activo
            cmb.setEnabled(True)
            rb_mover.toggled.connect(cmb.setEnabled)

            hl = QHBoxLayout()
            hl.addStretch()
            b_can = QPushButton("Cancelar"); b_can.clicked.connect(dlg.reject)
            b_ok  = QPushButton("Eliminar")
            b_ok.setStyleSheet(
                f"background:{BLUE_500}; color:white; border:none;"
                f" border-radius:6px; padding:5px 18px; font-weight:700;"
            )
            b_ok.clicked.connect(dlg.accept)
            hl.addWidget(b_can); hl.addWidget(b_ok)
            vl.addLayout(hl)
            if not dlg.exec():
                return
            if rb_borrar.isChecked():
                borrar_partidas = True
            else:
                destino_id = cmb.currentData()

        conn = get_db()
        if borrar_partidas:
            # FK CASCADE limpia acu_items, metrados, acero, specs, etc.
            conn.execute(
                "DELETE FROM partidas WHERE proyecto_id=? AND sub_presupuesto_id=?",
                (self.pid, sub_id)
            )
        else:
            conn.execute(
                "UPDATE partidas SET sub_presupuesto_id=? "
                "WHERE proyecto_id=? AND sub_presupuesto_id=?",
                (destino_id, self.pid, sub_id)
            )
        conn.execute("DELETE FROM sub_presupuestos WHERE id=?", (sub_id,))
        conn.commit()
        conn.close()

        # Si era el activo, volver al Principal (esto ya refresca todo)
        if self._sub_ppto_id == sub_id:
            self._on_sub_ppto_cambiado(None)
        else:
            # Si era otro sub, igual hay que refrescar: las partidas del sub
            # eliminado pasaron al Principal y pueden estar visibles ahora.
            self._cargar_sub_pptos()
            self.recargar_partidas()
            self.actualizar_total()

    # ══════════════════════════════════════════════════════════════════════════
    # Persistencia splitters
    # ══════════════════════════════════════════════════════════════════════════

    # ══════════════════════════════════════════════════════════════════════════
    # Layout responsivo (H ↔ V)
    # ══════════════════════════════════════════════════════════════════════════

    # Por debajo de este ancho el panel ACU se oculta y solo se muestra
    # el árbol del presupuesto (en ventanas pequeñas no caben los dos).
    # Bajo este ancho el panel ACU se oculta y el árbol del presupuesto
    # ocupa todo. 1050px deja la columna "Descripción" legible.
    _MIN_WIDTH_BOTH_PANELS = 1050

    def _toggle_panel_layout(self):
        # Marcar que el usuario eligió manualmente la orientación; a
        # partir de aquí el auto-toggle por aspecto de pantalla no la
        # sobrescribe en resize, y el threshold de min-width tampoco
        # oculta el panel ACU.
        self._layout_user_set = True
        # Garantizar que el panel ACU esté visible (puede estar oculto
        # por el threshold si la ventana es pequeña).
        self._set_acu_panel_visible(True)
        if self.hsplit.orientation() == Qt.Horizontal:
            self._set_layout(Qt.Vertical)
        else:
            self._set_layout(Qt.Horizontal)

    def _set_layout(self, orientacion):
        from utils.tooltip import set_tooltip
        self.hsplit.setOrientation(orientacion)
        self._aplicar_ratio_splitter()
        if orientacion == Qt.Vertical:
            self._btn_layout.setText("↔")
            set_tooltip(self._btn_layout, "Mover panel ACU a la derecha")
        else:
            self._btn_layout.setText("↕")
            set_tooltip(self._btn_layout, "Mover panel ACU abajo")

    def _screen_es_horizontal(self) -> bool:
        """True si la pantalla actual es apaisada (ancho > alto)."""
        try:
            scr = self.screen()
            if scr is None:
                from PySide6.QtGui import QGuiApplication
                scr = QGuiApplication.primaryScreen()
            if scr is None:
                return True
            g = scr.availableGeometry()
            return g.width() > g.height()
        except Exception:
            return True

    def _set_acu_panel_visible(self, visible: bool):
        """Muestra/oculta el segundo widget del splitter (panel ACU)."""
        panel = self.hsplit.widget(1)
        if panel is None:
            return
        if panel.isVisible() != visible:
            panel.setVisible(visible)
        # Cuando solo queda el presupuesto, ocupa todo el splitter.
        if not visible:
            total = (self.hsplit.width() if self.hsplit.orientation() == Qt.Horizontal
                     else self.hsplit.height())
            self.hsplit.setSizes([max(10, total), 0])

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Reposicionar Tuxia inmediatamente (sin debounce) para que el
        # icono flotante siga la esquina inferior-derecha al redimensionar.
        # Solo en la vista principal (idx 0); en cronograma/pie/reportes el
        # icono debe quedar oculto (el footer del Gantt ya tiene "Ayúdame").
        if hasattr(self, '_tuxia') and self._tuxia is not None:
            en_main = (not hasattr(self, '_root_stack')
                        or self._root_stack.currentIndex() == 0)
            if en_main:
                if not self._tuxia.isVisible():
                    self._tuxia.setVisible(True)
                self._tuxia.reposicionar()
            else:
                self._tuxia.setVisible(False)
        # Debounce: esperar 200ms después del último resize antes de ajustar
        if not hasattr(self, '_resize_timer'):
            self._resize_timer = QTimer(self)
            self._resize_timer.setSingleShot(True)
            self._resize_timer.timeout.connect(self._on_resize_settled)
        self._resize_timer.start(200)

    def _on_resize_settled(self):
        """Se llama 200ms después de que el resize terminó.

        - Ventana angosta (< _MIN_WIDTH_BOTH_PANELS) Y sin acción del
          usuario en el toggle de layout: oculta el panel ACU.
        - Si el usuario clickeó el toggle (`_layout_user_set`), respetar
          su elección sin importar el ancho actual.
        - Ventana cómoda: muestra ambos y, si el usuario no eligió
          manualmente la orientación, la deriva del aspecto de la pantalla
          (apaisada → side-by-side; vertical/cuadrada → apilado).
        """
        w = self.width()
        user_override = getattr(self, '_layout_user_set', False)
        if w < self._MIN_WIDTH_BOTH_PANELS and not user_override:
            self._set_acu_panel_visible(False)
            return
        # Ventana lo bastante ancha (o el usuario forzó ambos paneles).
        self._set_acu_panel_visible(True)
        if not user_override:
            deseada = Qt.Horizontal if self._screen_es_horizontal() else Qt.Vertical
            if self.hsplit.orientation() != deseada:
                self._set_layout(deseada)
                return
        self._aplicar_ratio_splitter()

    def _aplicar_ratio_splitter(self):
        """Aplica la proporción guardada al tamaño actual del splitter."""
        ratio = getattr(self, '_splitter_ratio', 0.55)
        if self.hsplit.orientation() == Qt.Horizontal:
            total = self.hsplit.width()
        else:
            total = self.hsplit.height()
        if total < 20:
            return
        a = max(10, int(total * ratio))
        b = max(10, total - a)
        self.hsplit.setSizes([a, b])

    def _restaurar_splitters(self):
        s = QSettings("ingePresupuestos", "layout")
        ratio = s.value(f"hsplit_ratio_{self.pid}", 0.55, type=float)
        self._splitter_ratio = ratio
        self._aplicar_ratio_splitter()
        self.hsplit.splitterMoved.connect(self._guardar_splitters)

    def _guardar_splitters(self):
        sizes = self.hsplit.sizes()
        total = sum(sizes)
        if total > 0:
            self._splitter_ratio = sizes[0] / total
            s = QSettings("ingePresupuestos", "layout")
            s.setValue(f"hsplit_ratio_{self.pid}", self._splitter_ratio)


# ══════════════════════════════════════════════════════════════════════════════
# Widget gráfico pastel (donut)
# ══════════════════════════════════════════════════════════════════════════════

class _DonutChart(QWidget):
    """Gráfico de donut con leyenda. datos = [(label, valor, color_hex), ...]"""

    def __init__(self, datos: list, titulo: str = "", parent=None):
        super().__init__(parent)
        self._datos  = [(l, v, QColor(c)) for l, v, c in datos if v > 0]
        self._titulo = titulo
        self.setMinimumSize(160, 200)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setAttribute(Qt.WA_TranslucentBackground)

    def actualizar(self, datos: list, titulo: str = ""):
        self._datos  = [(l, v, QColor(c)) for l, v, c in datos if v > 0]
        self._titulo = titulo
        self.update()

    def paintEvent(self, event):
        if not self._datos:
            return

        from PySide6.QtGui import QPainterPath
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        total = sum(v for _, v, _ in self._datos)
        if total <= 0:
            return

        W, H = self.width(), self.height()

        # Área del donut: cuadrado centrado en la mitad superior
        leyenda_h = len(self._datos) * 20 + 10
        donut_h   = max(80, H - leyenda_h - 10)
        size      = min(W - 20, donut_h)
        cx        = W // 2
        cy        = 10 + size // 2
        r_ext     = size // 2
        r_int     = int(r_ext * 0.55)   # grosor del donut

        pie_rect = QRect(cx - r_ext, cy - r_ext, size, size)

        # Dibujar sectores
        start = 90 * 16
        for i, (label, value, color) in enumerate(self._datos):
            span = int(360 * 16 * value / total)
            if i == len(self._datos) - 1:
                span = 360 * 16 - (start - 90 * 16)   # corregir redondeo
            painter.setBrush(QBrush(color))
            painter.setPen(Qt.NoPen)
            painter.drawPie(pie_rect, start, span)
            start += span

        # Hueco interior (efecto donut)
        painter.setBrush(QBrush(QColor("white")))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(cx - r_int, cy - r_int, r_int * 2, r_int * 2)

        # Porcentaje total en el centro
        painter.setPen(QColor("#273445"))
        f_big = QFont(); f_big.setPointSize(11); f_big.setBold(True)
        f_sm  = QFont(); f_sm.setPointSize(7)
        painter.setFont(f_big)
        painter.drawText(QRect(cx - r_int, cy - 14, r_int * 2, 18),
                         Qt.AlignCenter, "100%")
        if self._titulo:
            painter.setFont(f_sm)
            painter.setPen(QColor("#95A3AB"))
            painter.drawText(QRect(cx - r_int, cy + 2, r_int * 2, 14),
                             Qt.AlignCenter, self._titulo)

        # Leyenda debajo del donut
        y_ley = 10 + size + 10
        f_ley = QFont(); f_ley.setPointSize(8)
        painter.setFont(f_ley)
        for label, value, color in self._datos:
            pct = value / total * 100
            # Cuadrito de color
            painter.setBrush(QBrush(color))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(10, y_ley + 3, 12, 12, 3, 3)
            # Texto
            painter.setPen(QColor("#485A6C"))
            painter.drawText(QRect(28, y_ley, W - 38, 18),
                             Qt.AlignLeft | Qt.AlignVCenter,
                             f"{label}")
            painter.setPen(QColor("#273445"))
            pct_txt = f"{pct:.1f}%"
            painter.drawText(QRect(28, y_ley, W - 38, 18),
                             Qt.AlignRight | Qt.AlignVCenter, pct_txt)
            y_ley += 20


# ══════════════════════════════════════════════════════════════════════════════
# Workers IA — corren en hilo separado para no bloquear la UI
# ══════════════════════════════════════════════════════════════════════════════

class _WorkerSpec(QThread):
    """Genera spec para una partida individual."""
    terminado = Signal(str, str)   # (texto_resultado, mensaje_error)

    def __init__(self, partida_id: int, prompt_extra: str = ''):
        super().__init__()
        self.partida_id   = partida_id
        self.prompt_extra = prompt_extra

    def run(self):
        try:
            from core.ai_specs import generar_spec_partida
            texto, error = generar_spec_partida(self.partida_id,
                                                self.prompt_extra or None)
            self.terminado.emit(texto or '', error or '')
        except Exception as e:
            self.terminado.emit('', str(e))


_SECCIONES_MEMORIA = [
    "NOMBRE DEL PROYECTO", "ANTECEDENTES", "JUSTIFICACIÓN",
    "LOCALIZACIÓN DEL PROYECTO", "VÍAS DE COMUNICACIÓN",
    "OBJETIVOS GENERALES Y ESPECÍFICOS", "METAS DEL PROYECTO",
    "PRESUPUESTO DEL PROYECTO", "PLAZO DE EJECUCIÓN",
    "MODALIDAD DE EJECUCIÓN PRESUPUESTARIA",
]


class _WorkerAmpliarSeccion(QThread):
    """Reescribe una sección de la memoria, más extensa."""
    terminado = Signal(str, str)   # (texto_seccion, error)

    def __init__(self, proyecto_id, numero, nombre, contenido, prompt_extra=''):
        super().__init__()
        self.proyecto_id = proyecto_id
        self.numero = numero
        self.nombre = nombre
        self.contenido = contenido
        self.prompt_extra = prompt_extra

    def run(self):
        try:
            from core.ai_specs import ampliar_seccion_memoria
            texto, error = ampliar_seccion_memoria(
                self.proyecto_id, self.numero, self.nombre,
                self.contenido, self.prompt_extra or None)
            self.terminado.emit(texto or '', error or '')
        except Exception as e:
            self.terminado.emit('', str(e))


class _WorkerMemoria(QThread):
    """Genera la memoria descriptiva del proyecto (nivel proyecto)."""
    terminado = Signal(str, str)   # (texto_resultado, mensaje_error)

    def __init__(self, proyecto_id: int, prompt_extra: str = '', datos: dict = None):
        super().__init__()
        self.proyecto_id  = proyecto_id
        self.prompt_extra = prompt_extra
        self.datos        = datos

    def run(self):
        try:
            from core.ai_specs import generar_memoria_descriptiva
            texto, error = generar_memoria_descriptiva(
                self.proyecto_id, self.prompt_extra or None, self.datos)
            self.terminado.emit(texto or '', error or '')
        except Exception as e:
            self.terminado.emit('', str(e))


class _WorkerEspecsTodo(QThread):
    """Genera specs partida por partida con señales de progreso."""
    progreso  = Signal(int, int, str)   # (actual, total, descripcion_partida)
    terminado = Signal(int, str)        # (n_guardadas, error_o_vacio)

    def __init__(self, proyecto_id: int, omitir_existentes: bool = True):
        super().__init__()
        self.proyecto_id       = proyecto_id
        self.omitir_existentes = omitir_existentes
        self._cancelar         = False

    def cancelar(self):
        self._cancelar = True

    def run(self):
        import time
        try:
            from core.ai_specs import generar_spec_partida
            from core.database import get_db as _get_db
            conn = _get_db()
            partidas = conn.execute(
                "SELECT id, item, descripcion, especificaciones FROM partidas "
                "WHERE proyecto_id=? AND es_titulo=0 ORDER BY item",
                (self.proyecto_id,)
            ).fetchall()
            conn.close()

            total     = len(partidas)
            guardadas = 0
            for i, p in enumerate(partidas):
                if self._cancelar:
                    break
                desc = p['descripcion'] or ''
                if self.omitir_existentes and (p['especificaciones'] or '').strip():
                    self.progreso.emit(i + 1, total, f"[omitida]  {desc}")
                    continue
                self.progreso.emit(i + 1, total, desc)
                texto, _err = generar_spec_partida(p['id'])
                if texto:
                    guardadas += 1
                time.sleep(0.4)   # evitar rate-limit

            self.terminado.emit(guardadas, '')
        except Exception as e:
            self.terminado.emit(0, str(e))


# ══════════════════════════════════════════════════════════════════════════════
# Diálogos IA
# ══════════════════════════════════════════════════════════════════════════════

_DLG_BTN_CANCEL = (
    "QPushButton { background:#F8F9FA; color:#273445; border:1px solid #D4D4D4;"
    " border-radius:6px; padding:0 16px; font-size:11px; }"
    "QPushButton:hover { background:#E8EAED; }"
)
_DLG_BTN_IA = (
    "QPushButton { background:#9B59B6; color:white; border:none;"
    " border-radius:6px; padding:0 18px; font-size:11px; font-weight:600; }"
    "QPushButton:hover { background:#8E44AD; }"
    "QPushButton:disabled { background:#D4D4D4; color:#888; }"
)
_DLG_PB = (
    "QProgressBar { border:none; background:#E8EAED; border-radius:4px;"
    " text-align:center; color:white; font-size:11px; font-weight:600; }"
    "QProgressBar::chunk { background:#9B59B6; border-radius:4px; }"
)


class _DialogIASpec(QDialog):
    """Genera especificación técnica para una sola partida con IA."""

    def __init__(self, parent, partida_id: int, descripcion: str):
        super().__init__(parent)
        self.partida_id       = partida_id
        self.descripcion      = descripcion
        self._worker          = None
        self._texto_resultado = ''
        self.setWindowTitle("Generar especificación con IA")
        self.setMinimumWidth(500)
        self.setModal(True)
        self._build()

    def _build(self):
        vl = QVBoxLayout(self)
        vl.setSpacing(12)
        vl.setContentsMargins(18, 18, 18, 18)

        lbl_partida = QLabel(f"Partida: <b>{self.descripcion[:80]}</b>")
        lbl_partida.setWordWrap(True)
        lbl_partida.setStyleSheet("font-size:12px;")
        vl.addWidget(lbl_partida)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color:#E8EAED;")
        vl.addWidget(sep)

        lbl2 = QLabel("Instrucciones adicionales (opcional):")
        lbl2.setStyleSheet("font-size:11px; color:#485A6C;")
        vl.addWidget(lbl2)

        self.txt_extra = QTextEdit()
        self.txt_extra.setFixedHeight(72)
        self.txt_extra.setPlaceholderText(
            "Ej: Detallar tolerancias según ACI 318, incluir ensayos de laboratorio…"
        )
        self.txt_extra.setStyleSheet(
            "QTextEdit { border:1px solid #D4D4D4; border-radius:6px;"
            " font-size:11px; padding:6px; }"
        )
        vl.addWidget(self.txt_extra)

        self.pb = QProgressBar()
        self.pb.setRange(0, 0)   # indeterminado
        self.pb.setFixedHeight(6)
        self.pb.setStyleSheet(_DLG_PB)
        self.pb.hide()
        vl.addWidget(self.pb)

        self.lbl_estado = QLabel("")
        self.lbl_estado.setWordWrap(True)
        self.lbl_estado.setStyleSheet("font-size:10px; color:#667885;")
        self.lbl_estado.hide()
        vl.addWidget(self.lbl_estado)

        hl = QHBoxLayout()
        hl.addStretch()
        self.btn_cancelar = QPushButton("Cancelar")
        self.btn_cancelar.setFixedHeight(32)
        self.btn_cancelar.setStyleSheet(_DLG_BTN_CANCEL)
        self.btn_cancelar.clicked.connect(self.reject)
        hl.addWidget(self.btn_cancelar)

        self.btn_generar = QPushButton("✨  Generar")
        self.btn_generar.setFixedHeight(32)
        self.btn_generar.setStyleSheet(_DLG_BTN_IA)
        self.btn_generar.clicked.connect(self._generar)
        hl.addWidget(self.btn_generar)
        vl.addLayout(hl)

    def _generar(self):
        self.btn_generar.setEnabled(False)
        self.txt_extra.setEnabled(False)
        self.btn_cancelar.setText("Cerrar")
        self.pb.show()
        self.lbl_estado.setText("Consultando IA… esto puede tardar unos segundos.")
        self.lbl_estado.setStyleSheet("font-size:10px; color:#667885;")
        self.lbl_estado.show()

        prompt_extra = self.txt_extra.toPlainText().strip()
        self._worker = _WorkerSpec(self.partida_id, prompt_extra)
        self._worker.terminado.connect(self._on_terminado)
        self._worker.start()

    def _on_terminado(self, texto: str, error: str):
        self.pb.hide()
        if error:
            self.lbl_estado.setStyleSheet("font-size:10px; color:#C6262E;")
            self.lbl_estado.setText(error)
            self.btn_generar.setEnabled(True)
            self.btn_generar.setText("✨  Reintentar")
            self.txt_extra.setEnabled(True)
            return
        self._texto_resultado = texto
        self.accept()

    def resultado(self) -> str:
        return self._texto_resultado


class _DialogIAMemoria(QDialog):
    """Genera la memoria descriptiva del proyecto con IA."""

    def __init__(self, parent, proyecto_id: int, proyecto_nombre: str,
                 notas: str = ''):
        super().__init__(parent)
        self.proyecto_id      = proyecto_id
        self._notas           = notas or ''
        self._worker          = None
        self._texto_resultado = ''
        self.setWindowTitle("Generar memoria descriptiva con IA")
        self.setMinimumWidth(520)
        self.setModal(True)
        vl = QVBoxLayout(self)
        vl.setSpacing(12)
        vl.setContentsMargins(18, 18, 18, 18)

        lbl = QLabel(f"Proyecto: <b>{(proyecto_nombre or '')[:90]}</b>")
        lbl.setWordWrap(True)
        lbl.setStyleSheet("font-size:12px;")
        vl.addWidget(lbl)

        info = QLabel(
            "La IA usará la ubicación, el presupuesto, el plazo, la modalidad y "
            "las notas. Completa los siguientes datos para que NO salgan como "
            "«(por confirmar)»:"
        )
        info.setWordWrap(True)
        info.setStyleSheet("font-size:11px; color:#667885;")
        vl.addWidget(info)

        from PySide6.QtWidgets import QFormLayout, QLineEdit
        _ss_in = ("QLineEdit, QComboBox { border:1px solid #D4D4D4;"
                  " border-radius:6px; padding:4px 8px; font-size:11px;"
                  " min-height:0; }")
        form = QFormLayout()
        form.setSpacing(8)
        self.cmb_tipo = QComboBox()
        self.cmb_tipo.addItems(["Proyecto de inversión", "IOARR",
                                "Mantenimiento", "Ficha de emergencia"])
        self.cmb_tipo.setStyleSheet(_ss_in)
        self.inp_cui = QLineEdit()
        self.inp_cui.setPlaceholderText("Ej: 2654321 — mantenimiento/emergencia no llevan CUI")
        self.inp_cui.setStyleSheet(_ss_in)
        self.inp_benef = QLineEdit()
        self.inp_benef.setPlaceholderText("Ej: 120 familias / 480 habitantes")
        self.inp_benef.setStyleSheet(_ss_in)
        form.addRow("Tipo de intervención:", self.cmb_tipo)
        form.addRow("CUI (si aplica):", self.inp_cui)
        form.addRow("N° de beneficiarios:", self.inp_benef)
        vl.addLayout(form)

        lbl2 = QLabel("Antecedentes y condiciones (se trae de las Notas del "
                      "proyecto — puedes editarlo):")
        lbl2.setWordWrap(True)
        lbl2.setStyleSheet("font-size:11px; color:#485A6C;")
        vl.addWidget(lbl2)
        self.txt_extra = QTextEdit()
        self.txt_extra.setFixedHeight(90)
        self.txt_extra.setPlaceholderText(
            "Antigüedad de la infraestructura, problema actual, contexto de la "
            "obra (altitud, clima, acceso, suelo)…"
        )
        self.txt_extra.setStyleSheet(
            "QTextEdit { border:1px solid #D4D4D4; border-radius:6px;"
            " font-size:11px; padding:6px; }"
        )
        if self._notas.strip():
            self.txt_extra.setPlainText(self._notas.strip())
        vl.addWidget(self.txt_extra)

        self.pb = QProgressBar()
        self.pb.setRange(0, 0)
        self.pb.setFixedHeight(6)
        self.pb.setStyleSheet(_DLG_PB)
        self.pb.hide()
        vl.addWidget(self.pb)

        self.lbl_estado = QLabel("")
        self.lbl_estado.setWordWrap(True)
        self.lbl_estado.setStyleSheet("font-size:10px; color:#667885;")
        self.lbl_estado.hide()
        vl.addWidget(self.lbl_estado)

        hl = QHBoxLayout()
        hl.addStretch()
        self.btn_cancelar = QPushButton("Cancelar")
        self.btn_cancelar.setFixedHeight(32)
        self.btn_cancelar.setStyleSheet(_DLG_BTN_CANCEL)
        self.btn_cancelar.clicked.connect(self.reject)
        hl.addWidget(self.btn_cancelar)
        self.btn_generar = QPushButton("✨  Generar")
        self.btn_generar.setFixedHeight(32)
        self.btn_generar.setStyleSheet(_DLG_BTN_IA)
        self.btn_generar.clicked.connect(self._generar)
        hl.addWidget(self.btn_generar)
        vl.addLayout(hl)

    def _generar(self):
        self.btn_generar.setEnabled(False)
        self.txt_extra.setEnabled(False)
        self.btn_cancelar.setText("Cerrar")
        self.pb.show()
        self.lbl_estado.setText("Consultando IA… la memoria es larga, puede "
                                "tardar bastante.")
        self.lbl_estado.setStyleSheet("font-size:10px; color:#667885;")
        self.lbl_estado.show()
        datos = {
            'tipo':          self.cmb_tipo.currentText(),
            'cui':           self.inp_cui.text().strip(),
            'beneficiarios': self.inp_benef.text().strip(),
            'antecedentes':  self.txt_extra.toPlainText().strip(),
        }
        self._worker = _WorkerMemoria(self.proyecto_id, '', datos)
        self._worker.terminado.connect(self._on_terminado)
        self._worker.start()

    def _on_terminado(self, texto: str, error: str):
        self.pb.hide()
        if error:
            self.lbl_estado.setStyleSheet("font-size:10px; color:#C6262E;")
            self.lbl_estado.setText(error)
            self.btn_generar.setEnabled(True)
            self.btn_generar.setText("✨  Reintentar")
            self.txt_extra.setEnabled(True)
            return
        self._texto_resultado = texto
        self.accept()

    def resultado(self) -> str:
        return self._texto_resultado


class _DialogAmpliarSeccion(QDialog):
    """Amplía una sección de la memoria descriptiva con IA."""

    def __init__(self, parent, proyecto_id, numero, nombre, contenido):
        super().__init__(parent)
        self.proyecto_id = proyecto_id
        self.numero = numero
        self.nombre = nombre
        self.contenido = contenido
        self._worker = None
        self._texto_resultado = ''
        self.setWindowTitle("Ampliar sección con IA")
        self.setMinimumWidth(520)
        self.setModal(True)
        vl = QVBoxLayout(self)
        vl.setSpacing(12)
        vl.setContentsMargins(18, 18, 18, 18)

        lbl = QLabel(f"Sección: <b>{numero}. {nombre.title()}</b>")
        lbl.setStyleSheet("font-size:12px;")
        vl.addWidget(lbl)
        info = QLabel("La IA reescribirá esta sección más extensa y detallada, "
                      "y reemplazará su contenido en la memoria.")
        info.setWordWrap(True)
        info.setStyleSheet("font-size:11px; color:#667885;")
        vl.addWidget(info)

        lbl2 = QLabel("Instrucciones adicionales (opcional):")
        lbl2.setStyleSheet("font-size:11px; color:#485A6C;")
        vl.addWidget(lbl2)
        self.txt_extra = QTextEdit()
        self.txt_extra.setFixedHeight(60)
        self.txt_extra.setPlaceholderText(
            "Ej: enfatiza el impacto social y agrega indicadores cuantitativos.")
        self.txt_extra.setStyleSheet(
            "QTextEdit { border:1px solid #D4D4D4; border-radius:6px;"
            " font-size:11px; padding:6px; }")
        vl.addWidget(self.txt_extra)

        self.pb = QProgressBar()
        self.pb.setRange(0, 0)
        self.pb.setFixedHeight(6)
        self.pb.setStyleSheet(_DLG_PB)
        self.pb.hide()
        vl.addWidget(self.pb)
        self.lbl_estado = QLabel("")
        self.lbl_estado.setWordWrap(True)
        self.lbl_estado.setStyleSheet("font-size:10px; color:#667885;")
        self.lbl_estado.hide()
        vl.addWidget(self.lbl_estado)

        hl = QHBoxLayout()
        hl.addStretch()
        self.btn_cancelar = QPushButton("Cancelar")
        self.btn_cancelar.setFixedHeight(32)
        self.btn_cancelar.setStyleSheet(_DLG_BTN_CANCEL)
        self.btn_cancelar.clicked.connect(self.reject)
        hl.addWidget(self.btn_cancelar)
        self.btn_generar = QPushButton("✨  Ampliar")
        self.btn_generar.setFixedHeight(32)
        self.btn_generar.setStyleSheet(_DLG_BTN_IA)
        self.btn_generar.clicked.connect(self._generar)
        hl.addWidget(self.btn_generar)
        vl.addLayout(hl)

    def _generar(self):
        self.btn_generar.setEnabled(False)
        self.txt_extra.setEnabled(False)
        self.btn_cancelar.setText("Cerrar")
        self.pb.show()
        self.lbl_estado.setText("Consultando IA…")
        self.lbl_estado.setStyleSheet("font-size:10px; color:#667885;")
        self.lbl_estado.show()
        self._worker = _WorkerAmpliarSeccion(
            self.proyecto_id, self.numero, self.nombre, self.contenido,
            self.txt_extra.toPlainText().strip())
        self._worker.terminado.connect(self._on_terminado)
        self._worker.start()

    def _on_terminado(self, texto, error):
        self.pb.hide()
        if error:
            self.lbl_estado.setStyleSheet("font-size:10px; color:#C6262E;")
            self.lbl_estado.setText(error)
            self.btn_generar.setEnabled(True)
            self.btn_generar.setText("✨  Reintentar")
            self.txt_extra.setEnabled(True)
            return
        self._texto_resultado = texto
        self.accept()

    def resultado(self) -> str:
        return self._texto_resultado


class _WorkerSugerirPartidas(QThread):
    """Sugiere partidas con IA en segundo plano. Incluye TODO el RAG: cargar el
    modelo de embeddings la 1ª vez (~6 s), recuperación y la llamada al LLM. Va
    en un hilo para que la ventana NO se congele (el SO mostraba «No responde /
    Forzar salida» al correrlo en el hilo de la interfaz)."""
    terminado = Signal(object, str)   # (lista_partidas | None, mensaje_error)

    def __init__(self, proyecto_id: int):
        super().__init__()
        self.proyecto_id = proyecto_id

    def run(self):
        try:
            from core.ai_specs import sugerir_partidas_ia
            ps, err = sugerir_partidas_ia(self.proyecto_id)
            self.terminado.emit(ps, err or '')
        except Exception as e:
            self.terminado.emit(None, f"Error inesperado: {e}")


class _DialogSugerirPartidas(QDialog):
    """Sugiere partidas para un proyecto vacío. Dos modos:
       - IA: el LLM genera lista a partir del nombre/ubicación del proyecto
       - Plantilla local: catálogos predefinidos por tipo de obra

    El usuario revisa la lista (con checkboxes) y marca cuáles importar."""

    def __init__(self, proyecto_id: int, proyecto_nombre: str = '',
                 parent=None):
        super().__init__(parent)
        self.proyecto_id = proyecto_id
        self._sugerencias: list[dict] = []
        self._worker_sug = None
        self.setWindowTitle("Sugerir partidas para el proyecto")
        self.setWindowModality(Qt.ApplicationModal)
        self.setMinimumSize(720, 560)
        self.setStyleSheet(
            "QDialog { background:#FFFFFF; color:#1F2A38; }"
            "QLabel { color:#1F2A38; background:transparent; font-size:11px; }"
            "QLabel#title { font-size:14px; font-weight:700; padding:4px 0; }"
            "QPushButton { padding:6px 14px; border-radius:6px; font-size:11px;"
            "  background:#F8F9FA; color:#1F2A38; border:1px solid #CBD5E1; }"
            "QPushButton:hover { background:#FEF5EB; color:#C0621A;"
            "  border-color:#F37329; }"
            "QPushButton#primary { background:#F37329; color:white;"
            "  border:1px solid #C0621A; font-weight:600; }"
            "QPushButton#primary:hover { background:#C0621A; }"
            "QComboBox { background:white; padding:4px 8px; font-size:11px;"
            "  border:1px solid #CBD5E1; border-radius:4px; min-height:0; }"
            "QTreeWidget { background:white; border:1px solid #E2E8F0;"
            "  font-size:11px; }"
            "QTreeWidget::item { padding:3px 4px; }"
            "QTreeWidget::item:selected { background:#FEF5EB; color:#C0621A; }"
            "QHeaderView::section { background:#F8F9FA; color:#1F2A38;"
            "  padding:5px; border:none; border-bottom:1px solid #E2E8F0;"
            "  font-weight:600; font-size:11px; }"
            "QPlainTextEdit { background:white; border:1px solid #E2E8F0;"
            "  font-size:11px; padding:4px; }"
        )
        from PySide6.QtGui import QPalette as _QPal, QColor as _QC
        pal = self.palette()
        pal.setColor(_QPal.Window, _QC("#FFFFFF"))
        pal.setColor(_QPal.WindowText, _QC("#1F2A38"))
        self.setPalette(pal)

        from PySide6.QtWidgets import (QVBoxLayout, QHBoxLayout, QPushButton,
                                          QLabel, QTreeWidget, QTreeWidgetItem,
                                          QComboBox, QApplication, QMessageBox)
        vl = QVBoxLayout(self)
        vl.setContentsMargins(16, 14, 16, 14)
        vl.setSpacing(8)

        title = QLabel("Sugerir partidas para tu nuevo proyecto")
        title.setObjectName("title")
        vl.addWidget(title)
        sub = QLabel(
            f"<i>{proyecto_nombre}</i><br>"
            "Elige una opción y revisa la lista; marca solo las partidas que "
            "quieras importar. Después podrás agregar metrados, ACUs y más."
        )
        sub.setWordWrap(True)
        vl.addWidget(sub)

        # ── Botones de origen: IA o plantilla local ──
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.btn_ia = QPushButton("🌐  Sugerir con IA")
        self.btn_ia.setObjectName("primary")
        self.btn_ia.clicked.connect(self._cargar_ia)
        btn_row.addWidget(self.btn_ia)

        from core.ai_specs import listar_plantillas
        self.cmb_plantilla = QComboBox()
        self.cmb_plantilla.addItem("— Plantilla local —", '')
        for k, t in listar_plantillas():
            self.cmb_plantilla.addItem(t, k)
        self.cmb_plantilla.currentIndexChanged.connect(self._cargar_plantilla)
        btn_row.addWidget(self.cmb_plantilla)
        btn_row.addStretch()
        vl.addLayout(btn_row)

        # ── Tree con sugerencias ──
        from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Importar", "Ítem", "Descripción", "Und"])
        self.tree.setColumnWidth(0, 70)
        self.tree.setColumnWidth(1, 80)
        self.tree.setColumnWidth(3, 60)
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        vl.addWidget(self.tree, stretch=1)

        # ── Acciones de selección ──
        sel_row = QHBoxLayout()
        sel_row.setSpacing(6)
        b_all = QPushButton("Marcar todas")
        b_all.clicked.connect(lambda: self._marcar_todas(True))
        b_none = QPushButton("Desmarcar todas")
        b_none.clicked.connect(lambda: self._marcar_todas(False))
        sel_row.addWidget(b_all)
        sel_row.addWidget(b_none)
        sel_row.addStretch()
        self.lbl_count = QLabel("0 partidas")
        sel_row.addWidget(self.lbl_count)
        vl.addLayout(sel_row)

        # ── Toggle: usar biblioteca para traer ACUs ──
        from PySide6.QtWidgets import QCheckBox
        self.chk_biblio = QCheckBox(
            "Usar mi biblioteca de CUs cuando coincida — copia ACU completo"
            " (recursos, cantidades, rendimientos)"
        )
        self.chk_biblio.setChecked(True)
        self.chk_biblio.setStyleSheet(
            "QCheckBox { color:#1F2A38; font-size:11px; padding:4px 0; }"
        )
        vl.addWidget(self.chk_biblio)

        # ── Botones inferiores ──
        bot_row = QHBoxLayout()
        bot_row.addStretch()
        b_cancel = QPushButton("Cancelar")
        b_cancel.clicked.connect(self.reject)
        self.b_imp = QPushButton("Importar")
        self.b_imp.setObjectName("primary")
        self.b_imp.clicked.connect(self._importar)
        bot_row.addWidget(b_cancel)
        bot_row.addWidget(self.b_imp)
        vl.addLayout(bot_row)

    def _cargar_ia(self):
        # Corre en SEGUNDO PLANO (no congela la ventana). Ver _WorkerSugerirPartidas.
        if self._worker_sug and self._worker_sug.isRunning():
            return
        self.btn_ia.setEnabled(False)
        self.btn_ia.setText("⏳  Consultando IA…")
        self._worker_sug = _WorkerSugerirPartidas(self.proyecto_id)
        self._worker_sug.terminado.connect(self._on_ia_terminado)
        self._worker_sug.start()

    def _on_ia_terminado(self, ps, err):
        from PySide6.QtWidgets import QMessageBox
        self.btn_ia.setEnabled(True)
        self.btn_ia.setText("🌐  Sugerir con IA")
        if err:
            QMessageBox.warning(self, "Sugerir con IA",
                f"No se pudo obtener la sugerencia:\n\n{err}\n\n"
                "Verifica tu clave API en Configuración → IA, o usa una "
                "plantilla local mientras tanto.")
            return
        if not ps:
            QMessageBox.information(self, "Sugerir con IA",
                "La IA no devolvió partidas. Intenta agregar más detalle al "
                "nombre del proyecto (incluye el tipo de obra) y vuelve a "
                "intentarlo.")
            return
        self._poblar(ps)

    def done(self, r):
        # QDialog + QThread: esperar al worker en vuelo antes de cerrar para no
        # destruir el hilo con la tarea corriendo (CLAUDE.md). No usar closeEvent.
        w = getattr(self, '_worker_sug', None)
        if w and w.isRunning():
            w.wait(15000)
        super().done(r)

    def _cargar_plantilla(self, idx: int):
        clave = self.cmb_plantilla.itemData(idx)
        if not clave:
            return
        from core.ai_specs import sugerir_partidas_local
        self._poblar(sugerir_partidas_local(clave))

    def _poblar(self, partidas: list):
        from PySide6.QtWidgets import QTreeWidgetItem
        self._sugerencias = partidas
        self.tree.clear()
        for p in partidas:
            it = QTreeWidgetItem([
                '',
                p.get('item', ''),
                p.get('descripcion', ''),
                p.get('unidad', ''),
            ])
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(0, Qt.Checked)
            if p.get('es_titulo'):
                from PySide6.QtGui import QFont as _QF, QBrush as _QB, QColor as _QC2
                f = _QF(); f.setBold(True); it.setFont(2, f)
                it.setForeground(2, _QB(_QC2("#1F2A38")))
            self.tree.addTopLevelItem(it)
        self._actualizar_count()
        self.tree.itemChanged.connect(lambda *_: self._actualizar_count())

    def _marcar_todas(self, on: bool):
        st = Qt.Checked if on else Qt.Unchecked
        for i in range(self.tree.topLevelItemCount()):
            self.tree.topLevelItem(i).setCheckState(0, st)

    def _actualizar_count(self):
        n = sum(
            1 for i in range(self.tree.topLevelItemCount())
            if self.tree.topLevelItem(i).checkState(0) == Qt.Checked
        )
        self.lbl_count.setText(f"{n} partidas marcadas para importar")

    def _importar(self):
        from PySide6.QtWidgets import QMessageBox, QApplication
        marcadas = []
        for i, p in enumerate(self._sugerencias):
            it = self.tree.topLevelItem(i)
            if it and it.checkState(0) == Qt.Checked:
                marcadas.append(p)
        if not marcadas:
            QMessageBox.information(self, "Importar partidas",
                "No hay partidas marcadas. Marca al menos una.")
            return
        usar_bib = self.chk_biblio.isChecked()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            from core.ai_specs import importar_partidas_con_biblioteca
            creadas, con_acu = importar_partidas_con_biblioteca(
                self.proyecto_id, marcadas, usar_biblioteca=usar_bib
            )
        finally:
            QApplication.restoreOverrideCursor()
        if usar_bib and con_acu > 0:
            extra = (f"\n\n✨ <b>{con_acu}</b> de ellas se importaron con su "
                     "ACU completo (recursos, rendimientos y precios) "
                     "desde tu biblioteca.")
        else:
            extra = ""
        QMessageBox.information(self, "Importar partidas",
            f"Se importaron <b>{creadas}</b> partidas al proyecto.{extra}")
        self.accept()


class _DialogIATodo(QDialog):
    """Genera especificaciones para todas las partidas del proyecto."""

    def __init__(self, parent, proyecto_id: int, nombre_proyecto: str,
                 omitir_existentes: bool = True):
        super().__init__(parent)
        self.proyecto_id     = proyecto_id
        self.nombre_proyecto = nombre_proyecto
        self._omitir_inicial = bool(omitir_existentes)
        self._worker         = None
        self.setWindowTitle("Generar especificaciones — Todo el proyecto")
        self.setMinimumWidth(540)
        self.setModal(True)
        self._build()

    def _build(self):
        vl = QVBoxLayout(self)
        vl.setSpacing(12)
        vl.setContentsMargins(18, 18, 18, 18)

        lbl = QLabel(f"Proyecto: <b>{self.nombre_proyecto}</b>")
        lbl.setWordWrap(True)
        lbl.setStyleSheet("font-size:12px;")
        vl.addWidget(lbl)

        info = QLabel(
            "Se generará una especificación técnica para cada partida hoja.\n"
            "El proceso puede tardar varios minutos según la cantidad de partidas."
        )
        info.setWordWrap(True)
        info.setStyleSheet("font-size:11px; color:#485A6C; line-height:1.5;")
        vl.addWidget(info)

        self.chk_omitir = QCheckBox("Omitir partidas que ya tienen especificaciones")
        self.chk_omitir.setChecked(self._omitir_inicial)
        self.chk_omitir.setStyleSheet("font-size:11px;")
        vl.addWidget(self.chk_omitir)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color:#E8EAED;")
        vl.addWidget(sep)

        self.pb = QProgressBar()
        self.pb.setRange(0, 100)
        self.pb.setValue(0)
        self.pb.setFixedHeight(20)
        self.pb.setTextVisible(True)
        self.pb.setStyleSheet(_DLG_PB)
        self.pb.hide()
        vl.addWidget(self.pb)

        self.lbl_estado = QLabel("")
        self.lbl_estado.setWordWrap(True)
        self.lbl_estado.setStyleSheet("font-size:10px; color:#667885;")
        self.lbl_estado.hide()
        vl.addWidget(self.lbl_estado)

        hl = QHBoxLayout()
        hl.addStretch()
        self.btn_cancelar = QPushButton("Cancelar")
        self.btn_cancelar.setFixedHeight(32)
        self.btn_cancelar.setStyleSheet(_DLG_BTN_CANCEL)
        self.btn_cancelar.clicked.connect(self._on_cancelar)
        hl.addWidget(self.btn_cancelar)

        self.btn_generar = QPushButton("✨  Generar Todo")
        self.btn_generar.setFixedHeight(32)
        self.btn_generar.setStyleSheet(_DLG_BTN_IA)
        self.btn_generar.clicked.connect(self._generar)
        hl.addWidget(self.btn_generar)
        vl.addLayout(hl)

    def _generar(self):
        self.btn_generar.setEnabled(False)
        self.chk_omitir.setEnabled(False)
        self.pb.show()
        self.pb.setValue(0)
        self.lbl_estado.setText("Iniciando generación…")
        self.lbl_estado.setStyleSheet("font-size:10px; color:#667885;")
        self.lbl_estado.show()
        self.btn_cancelar.setText("Detener")

        self._worker = _WorkerEspecsTodo(
            self.proyecto_id,
            omitir_existentes=self.chk_omitir.isChecked()
        )
        self._worker.progreso.connect(self._on_progreso)
        self._worker.terminado.connect(self._on_terminado)
        self._worker.start()

    def _on_progreso(self, actual: int, total: int, nombre: str):
        pct = int(actual * 100 / total) if total else 0
        self.pb.setValue(pct)
        self.lbl_estado.setText(f"{actual} / {total}  ·  {nombre[:65]}")

    def _on_terminado(self, n_guardadas: int, error: str):
        self.pb.setValue(100)
        if error:
            self.lbl_estado.setStyleSheet("font-size:10px; color:#C6262E;")
            self.lbl_estado.setText(f"Error: {error}")
            self.btn_generar.setEnabled(True)
            self.btn_generar.setText("✨  Reintentar")
            self.chk_omitir.setEnabled(True)
        else:
            self.lbl_estado.setStyleSheet("font-size:10px; color:#68B723; font-weight:600;")
            self.lbl_estado.setText(
                f"Completado. {n_guardadas} especificaciones guardadas."
            )
            self.btn_generar.setEnabled(True)
            self.btn_generar.setText("✨  Generar de nuevo")
            self.chk_omitir.setEnabled(True)
        self.btn_cancelar.setText("Cerrar")

    def _on_cancelar(self):
        if self._worker and self._worker.isRunning():
            self._worker.cancelar()
            self._worker.wait(3000)
            self.lbl_estado.setText("Proceso detenido.")
        self.accept()


# ══════════════════════════════════════════════════════════════════════════════
# Worker Chat ACU
# ══════════════════════════════════════════════════════════════════════════════

class _WorkerChat(QThread):
    terminado = Signal(str, str)   # (respuesta, error)

    def __init__(self, partida_id: int | None, proyecto_id: int,
                 historial: list, mensaje: str, modo: str = 'ACU',
                 parent=None):
        super().__init__(parent)
        self.partida_id  = partida_id
        self.proyecto_id = proyecto_id
        self.historial   = historial
        self.mensaje     = mensaje
        self.modo        = modo

    def run(self):
        # Captura amplia para que ninguna excepción del módulo IA mate el
        # proceso. Cualquier error termina como error visible en el chat.
        try:
            if self.partida_id is None:
                from core.ai_specs import chat_proyecto_asistente
                resp, error = chat_proyecto_asistente(
                    self.proyecto_id, self.historial, self.mensaje
                )
            else:
                from core.ai_specs import chat_acu_asistente
                resp, error = chat_acu_asistente(
                    self.partida_id, self.historial, self.mensaje, self.modo
                )
            self.terminado.emit(resp or '', error or '')
        except BaseException as e:
            import traceback
            try:
                err = f"{type(e).__name__}: {e}\n\n{traceback.format_exc()[:1500]}"
            except Exception:
                err = "Error desconocido al consultar la IA."
            self.terminado.emit('', err)


# ══════════════════════════════════════════════════════════════════════════════
# Widget Chat ACU
# ══════════════════════════════════════════════════════════════════════════════

class _ChatACU(QWidget):
    """Asistente IA contextual — se acopla al pie del panel derecho de tabs.

    `set_modo(modo)` adapta su rol según la tab activa (ACU, Insumos,
    Metrados, Especificaciones, Resumen), cambiando placeholder, botones
    rápidos y el system prompt enviado al modelo.
    """

    # Paleta IA — elementary OS Terminal (pantheon-terminal).
    # Charcoal background con paleta oficial elementary (Strawberry/Orange/
    # Banana/Lime/Mint/BlueBerry/Grape/Slate/Silver).
    # Ref: https://elementary.io/brand
    # Look "terminal moderna" (estilo Warp/Ghostty): fondo slate profundo con
    # matiz azulado, respuestas en bloques redondeados, texto blanco suave.
    _TERM_BG     = "#11151A"        # slate-negro profundo — fondo terminal
    _TERM_CARD   = "#1A222B"        # bloque de respuesta (estilo Warp)
    _TERM_FG     = "#E6EDF3"        # blanco suave — texto base
    _TERM_DIM    = "#8B98A5"        # gris azulado — texto secundario
    _TERM_USER   = "#68B723"        # Lime 500 — prompt usuario ($) clásico bash
    _TERM_AI     = "#A56DE2"        # Grape 500 — prompt ai (tuxia>)
    _TERM_ERR    = "#ED5353"        # Strawberry 300 — errores (legible en oscuro)
    _TERM_HDR_BG = "#1A222B"        # cabecera, igual que los bloques
    _TERM_HDR_FG = "#E6EDF3"        # texto cabecera
    _TERM_BORDER = "#2A3340"        # bordes finos azulados
    _TERM_ACCENT = "#3689E6"        # BlueBerry 500 — focus rings, botón run
    _TERM_HOVER  = "#4D9FEF"        # hover MÁS claro (convención dark)
    # Fuente monoespaciada del sistema (caprichosa al SO, pero universalmente disponible)
    _FONT_MONO   = ('"JetBrains Mono", "Fira Code", "Consolas", '
                    '"Liberation Mono", "DejaVu Sans Mono", monospace')

    # Botones rápidos por modo: (icono+texto, pregunta enviada)
    _QUICK_BY_MODO = {
        'ACU': [
            ("📐 Rendimiento",      "Dime SOLO el rendimiento estimado de esta partida, en UN párrafo de máximo 3 líneas: la cifra con su unidad (ej. 25 m2/día), la cuadrilla típica CAPECO y el ajuste por la ubicación del proyecto si aplica. Texto plano sin markdown. Sin introducción, sin explicación larga, sin cierre."),
            ("📦 Insumos esperados","Dame SOLO la lista de insumos que debería tener el ACU de esta partida. Agrupa bajo los encabezados MANO DE OBRA, MATERIALES, EQUIPOS (y SUBCONTRATOS solo si aplica). Una línea por insumo con el formato:  - nombre (unidad). Texto plano: sin markdown, sin asteriscos, sin tablas. Sin cantidades, sin explicaciones, sin introducción ni cierre."),
            ("📊 Cantidades",       "Dame SOLO las cantidades recomendadas de los MATERIALES del ACU de esta partida — NO incluyas mano de obra ni equipos (esos se derivan de cuadrilla/rendimiento). Una línea por material con el formato:  - nombre: cantidad unidad por 1 [unidad de la partida]. La cantidad ya debe incluir la merma típica peruana (cemento 5-10%, agregados 5%, acero 7-10% por traslapes, madera 10-15%, ladrillo 5%). Texto plano: sin markdown, sin tablas, sin justificar el cálculo, sin introducción ni cierre. Ejemplo:  - Madera tornillo: 4.80 p2 por 1 m (incluye 10% merma)."),
            ("⚠️ Revisar todo",     "Revisa esta partida completa: rendimiento vs CAPECO, cuadrilla coherente, insumos cargados (¿falta MO/MAT/EQ típico?), precios vs mercado peruano. Cierra con 1-3 recomendaciones priorizadas."),
            ("🧮 Calc",             "/calc"),
        ],
        'Insumos': [
            ("💲 Precios ref.", "Revisa los precios de los insumos de esta partida y dime cuáles podrían estar fuera de rango de mercado en Perú."),
            ("📊 Top insumos", "/insumos"),
            ("🔁 Repetidos",   "/duplicados"),
            ("🧮 Calc",        "/calc"),
        ],
        'Metrados': [
            ("📏 Verificar",   "Verifica si la planilla de metrados es coherente con la unidad y el alcance de esta partida."),
            ("➗ Fórmula",      "¿Qué fórmula geométrica es la correcta para calcular el metrado de esta partida?"),
            ("🔩 Tabla acero", "Dame la tabla de kg/m por diámetro según NTP 341.031 / ASTM A615: 6mm, 8mm, 3/8\", 1/2\", 5/8\", 3/4\", 1\", 1 3/8\". Útil para metrados de acero."),
            ("🧮 Calc",        "/calc"),
        ],
        'Especificaciones': [
            ("📝 Redactar", "Redacta una especificación técnica completa para esta partida (Descripción, Materiales con normas, Procedimiento, Control, Medición, Pago)."),
            ("📚 Normas",   "¿Qué normas técnicas peruanas (RNE, NTP, ASTM) aplican a esta partida?"),
            ("📋 Resumir",  "Resume la especificación actual de esta partida en 1 párrafo conciso, conservando las normas citadas y el procedimiento esencial."),
            ("🧮 Calc",     "/calc"),
        ],
        'Resumen': [
            ("🏆 Top partidas", "/partidas"),
            ("🧮 Totales",      "/total"),
            ("📊 Análisis IA",  "¿Qué riesgos típicos tiene este proyecto en obras similares en Perú? Identifica las partidas más críticas por costo o riesgo y sugiere mitigaciones priorizadas."),
            ("🧮 Calc",         "/calc"),
        ],
        'Cronograma': [
            ("📅 Programar",   "Sugiere un orden constructivo realista para las partidas de este proyecto, indicando dependencias FS/SS/FF y duraciones aproximadas."),
            ("🔗 Dependencias","Explícame qué tipo de dependencia (FS, SS, FF, SF, pct, tgt_pct) debería usar entre dos partidas y cuándo conviene cada una."),
            ("🚧 Ruta crítica","¿Qué partidas suelen estar en la ruta crítica de este tipo de obra? ¿Cómo puedo reducir el plazo total?"),
            ("🗓 Calendario",   "¿Cómo debo manejar feriados, lluvias y domingos en el cronograma? ¿Qué porcentaje de holgura recomiendas?"),
            ("◐ Paralelos",    "¿Cuándo conviene que el sucesor esté al 50% cuando termine la predecesora (tgt_pct)? Da 3 ejemplos en obra peruana."),
            ("🧮 Calc",        "/calc"),
        ],
    }

    _PLACEHOLDER_BY_MODO = {
        'ACU':              "Pregunta sobre rendimientos, cuadrillas, insumos… o calcula: 12.5*8",
        'Insumos':          "Pregunta sobre precios referenciales, índices INEI… o calcula: 12.5*8",
        'Metrados':         "Pregunta sobre planilla, fórmulas geométricas… o calcula: 2.4*0.15*6.8",
        'Especificaciones': "Pregunta sobre redacción técnica, normas RNE/NTP/ASTM… o calcula: 12.5*8",
        'Resumen':          "Pregunta sobre análisis general, riesgos… o calcula: 5400*1.18",
        'Cronograma':       "Pregunta sobre dependencias FS/SS/FF/SF, ruta crítica, plazos… o calcula: 850/30",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._partida_id: int | None = None
        self._proyecto_id: int | None = None
        self._historial: list        = []
        self._worker: _WorkerChat | None = None
        self._modo: str = 'ACU'
        self.setMinimumHeight(140)
        self._build()

    def set_proyecto(self, proyecto_id: int):
        """Establece el proyecto activo. Solo limpia el historial si es un
        proyecto distinto del que se estaba conversando (es razonable: cada
        proyecto es un contexto independiente).
        """
        if proyecto_id != self._proyecto_id:
            self._proyecto_id = proyecto_id
            self._historial = []
            self._limpiar_mensajes()
            self._mostrar_bienvenida()

    def _mostrar_bienvenida(self):
        """Saludo inicial con ASCII tux + nombre del proyecto + tip aleatorio.
        Se muestra al abrir el chat por primera vez (proyecto cargado).
        """
        try:
            from core.asistente_local import bienvenida
            from core.database import get_db as _gdb
            nombre = ''
            if self._proyecto_id:
                conn = _gdb()
                row = conn.execute(
                    "SELECT nombre FROM proyectos WHERE id=?",
                    (self._proyecto_id,)
                ).fetchone()
                conn.close()
                nombre = row['nombre'] if row else ''
            self._agregar_burbuja("asistente", bienvenida(nombre))
        except Exception:
            pass

    def _build(self):
        vl = QVBoxLayout(self)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)

        # ── Cabecera estilo terminal moderna ──────────────────────────
        hdr = QFrame()
        hdr.setFixedHeight(32)
        hdr.setStyleSheet(
            f"background:{self._TERM_HDR_BG};"
            f" border-top:1px solid {self._TERM_BORDER};"
            f" border-bottom:1px solid {self._TERM_BORDER};"
        )
        hl_hdr = QHBoxLayout(hdr)
        hl_hdr.setContentsMargins(12, 0, 8, 0)
        hl_hdr.setSpacing(8)

        # Icono tuxia (pingüino + cerebro)
        from PySide6.QtWidgets import QToolButton
        ico = QToolButton()
        ico.setIcon(load_icon("tuxia"))
        ico.setIconSize(QSize(18, 18))
        ico.setStyleSheet("QToolButton { border:none; background:transparent; }")
        ico.setEnabled(False)
        hl_hdr.addWidget(ico)

        self.lbl_titulo = QLabel("tuxia@proyecto: ~/acu")
        self.lbl_titulo.setStyleSheet(
            f"color:{self._TERM_HDR_FG}; font-size:11px; font-weight:600;"
            f" border:none; font-family:{self._FONT_MONO};"
        )
        hl_hdr.addWidget(self.lbl_titulo)
        hl_hdr.addStretch()

        self.lbl_estado_chat = QLabel("")
        self.lbl_estado_chat.setStyleSheet(
            f"font-size:10px; color:{self._TERM_DIM}; border:none;"
            f" font-family:{self._FONT_MONO};"
        )
        hl_hdr.addWidget(self.lbl_estado_chat)

        # Botones separados: Notas (proyecto, privadas) y Memoria (global, va al LLM)
        _bloc_btn_ss = (
            f"QPushButton {{ background:transparent; color:{self._TERM_DIM};"
            f" border:none; border-radius:10px;"
            f" font-size:10px; padding:0 10px;"
            f" font-family:{self._FONT_MONO}; }}"
            f"QPushButton:hover {{ background:#243040;"
            f" color:{self._TERM_AI}; }}"
        )
        btn_notas = QPushButton("🗒️ notas")
        btn_notas.setFixedHeight(20)
        btn_notas.setCursor(Qt.PointingHandCursor)
        btn_notas.setStyleSheet(_bloc_btn_ss)
        try:
            from utils.tooltip import set_tooltip as _stt_m
            _stt_m(btn_notas,
                   "Notas del proyecto (privadas — NO se envían al LLM)")
        except Exception:
            pass
        btn_notas.clicked.connect(self._abrir_panel_notas)
        hl_hdr.addWidget(btn_notas)

        btn_memoria = QPushButton("🧠 memoria")
        btn_memoria.setFixedHeight(20)
        btn_memoria.setCursor(Qt.PointingHandCursor)
        btn_memoria.setStyleSheet(_bloc_btn_ss)
        try:
            from utils.tooltip import set_tooltip as _stt_m2
            _stt_m2(btn_memoria,
                    "Memoria global — el LLM la usa como contexto en cada pregunta")
        except Exception:
            pass
        btn_memoria.clicked.connect(self._abrir_panel_memoria)
        hl_hdr.addWidget(btn_memoria)

        btn_limpiar = QPushButton("clear")
        btn_limpiar.setFixedHeight(20)
        btn_limpiar.setStyleSheet(
            f"QPushButton {{ background:transparent; color:{self._TERM_DIM};"
            f" border:none; border-radius:10px;"
            f" font-size:10px; padding:0 10px;"
            f" font-family:{self._FONT_MONO}; }}"
            f"QPushButton:hover {{ background:#243040;"
            f" color:{self._TERM_HDR_FG}; }}"
        )
        btn_limpiar.clicked.connect(self._limpiar_chat)
        hl_hdr.addWidget(btn_limpiar)

        # Botón "minimizar" — devuelve el chat a estado plegado (Tuxia bubble)
        self.btn_minimizar = QPushButton("⨉")
        self.btn_minimizar.setFixedHeight(20)
        self.btn_minimizar.setFixedWidth(28)
        self.btn_minimizar.setCursor(Qt.PointingHandCursor)
        self.btn_minimizar.setStyleSheet(
            f"QPushButton {{ background:transparent; color:{self._TERM_DIM};"
            f" border:none; border-radius:10px;"
            f" font-size:13px; padding:0; font-weight:700;"
            f" font-family:{self._FONT_MONO}; }}"
            f"QPushButton:hover {{ color:#FFFFFF;"
            f" background:{self._TERM_ERR}; }}"
        )
        try:
            from utils.tooltip import set_tooltip as _stt
            _stt(self.btn_minimizar, "Cerrar chat — vuelve al icono Tuxia")
        except Exception:
            pass
        hl_hdr.addWidget(self.btn_minimizar)
        vl.addWidget(hdr)

        # ── Área de mensajes (fondo terminal) ─────────────────────────
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setStyleSheet(
            f"QScrollArea {{ background:{self._TERM_BG}; border:none; }}"
            f"QScrollBar:vertical {{ background:{self._TERM_BG};"
            f" width:8px; border:none; }}"
            f"QScrollBar::handle:vertical {{ background:{self._TERM_BORDER};"
            f" border-radius:4px; min-height:24px; }}"
            f"QScrollBar::handle:vertical:hover {{ background:#3A4654; }}"
            f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical"
            f" {{ height:0; background:none; }}"
        )
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._msgs_widget = QWidget()
        self._msgs_widget.setStyleSheet(f"background:{self._TERM_BG};")
        self._msgs_layout = QVBoxLayout(self._msgs_widget)
        self._msgs_layout.setContentsMargins(12, 10, 12, 10)
        self._msgs_layout.setSpacing(6)
        self._msgs_layout.addStretch()

        self._scroll.setWidget(self._msgs_widget)

        # Stack para alternar mensajes (idx 0) ↔ editor de memoria (idx 1).
        # Ambos comparten el mismo área para que el editor se vea integrado
        # en el chat estilo terminal en vez de en un diálogo flotante.
        from PySide6.QtWidgets import QStackedWidget
        self._msgs_stack = QStackedWidget()
        self._msgs_stack.addWidget(self._scroll)
        self._memoria_panel = self._build_memoria_panel()
        self._msgs_stack.addWidget(self._memoria_panel)
        vl.addWidget(self._msgs_stack, stretch=1)

        # ── Botones rápidos (paleta terminal) ─────────────────────────
        bar_quick = QFrame()
        bar_quick.setFixedHeight(34)
        bar_quick.setStyleSheet(
            f"background:{self._TERM_BG};"
            f" border-top:1px solid {self._TERM_BORDER};"
        )
        hl_q = QHBoxLayout(bar_quick)
        hl_q.setContentsMargins(10, 0, 10, 0)
        hl_q.setSpacing(6)

        self._bar_quick = bar_quick
        self._hl_q = hl_q
        self._BTN_Q = (
            f"QPushButton {{ background:{self._TERM_CARD}; color:{self._TERM_AI};"
            f" border:1px solid {self._TERM_BORDER}; border-radius:11px;"
            f" padding:2px 12px; font-size:11px; font-weight:600;"
            f" font-family:{self._FONT_MONO}; }}"
            f"QPushButton:hover {{ background:#243040;"
            f" color:{self._TERM_HDR_FG}; border-color:{self._TERM_AI}; }}"
        )
        # Botones rápidos: se reconstruyen al cambiar de modo
        self._rebuild_quick_buttons()
        vl.addWidget(bar_quick)

        # ── Entrada estilo prompt terminal moderna ────────────────────
        # Caja redondeada (estilo Warp) con el sigil $, el campo y el botón
        # run dentro; el borde se enciende en azul al recibir el foco.
        bar_inp = QFrame()
        bar_inp.setFixedHeight(46)
        bar_inp.setStyleSheet(
            f"background:{self._TERM_BG};"
            f" border-top:1px solid {self._TERM_BORDER};"
        )
        hl_bar = QHBoxLayout(bar_inp)
        hl_bar.setContentsMargins(10, 6, 10, 6)
        hl_bar.setSpacing(0)

        self._inp_box = QFrame()
        self._inp_box_ss = (
            "QFrame#inpBox {{ background:%s; border:1px solid {borde};"
            " border-radius:8px; }}" % self._TERM_CARD
        )
        self._inp_box.setObjectName("inpBox")
        self._inp_box.setStyleSheet(
            self._inp_box_ss.format(borde=self._TERM_BORDER))
        hl_inp = QHBoxLayout(self._inp_box)
        hl_inp.setContentsMargins(10, 2, 6, 2)
        hl_inp.setSpacing(6)

        # Prompt sigil (Lime elementary, clásico bash)
        lbl_prompt = QLabel("$")
        lbl_prompt.setStyleSheet(
            f"color:{self._TERM_USER}; font-family:{self._FONT_MONO};"
            f" font-size:15px; font-weight:700; background:transparent;"
            f" border:none;"
        )
        hl_inp.addWidget(lbl_prompt)

        self.inp_chat = QLineEdit()
        self.inp_chat.setPlaceholderText(
            "Pregunta sobre rendimientos, insumos… o calcula: 12.5*8"
        )
        self.inp_chat.setStyleSheet(
            f"QLineEdit {{ border:none; background:transparent;"
            f" color:{self._TERM_FG}; font-family:{self._FONT_MONO};"
            f" font-size:13px; selection-background-color:{self._TERM_ACCENT};"
            f" selection-color:white; }}"
            f"QLineEdit::placeholder {{ color:{self._TERM_DIM}; }}"
        )
        self.inp_chat.returnPressed.connect(self._enviar_desde_input)
        hl_inp.addWidget(self.inp_chat, stretch=1)

        # Focus ring: borde azul cuando el campo tiene el foco
        from PySide6.QtCore import QObject as _QO, QEvent as _QEv
        outer = self

        class _FocusRing(_QO):
            def eventFilter(s, obj, ev):
                if ev.type() == _QEv.FocusIn:
                    outer._inp_box.setStyleSheet(
                        outer._inp_box_ss.format(borde=outer._TERM_ACCENT))
                elif ev.type() == _QEv.FocusOut:
                    outer._inp_box.setStyleSheet(
                        outer._inp_box_ss.format(borde=outer._TERM_BORDER))
                return False

        self._focus_ring = _FocusRing(self)
        self.inp_chat.installEventFilter(self._focus_ring)

        self.btn_enviar = QPushButton("⏎ run")
        self.btn_enviar.setFixedHeight(26)
        self.btn_enviar.setCursor(Qt.PointingHandCursor)
        self.btn_enviar.setStyleSheet(
            f"QPushButton {{ background:{self._TERM_ACCENT}; color:white;"
            f" border:none; border-radius:6px; padding:0 14px;"
            f" font-size:12px; font-weight:600;"
            f" font-family:{self._FONT_MONO}; }}"
            f"QPushButton:hover {{ background:{self._TERM_HOVER}; }}"
            f"QPushButton:disabled {{ background:{self._TERM_BORDER};"
            f" color:{self._TERM_DIM}; }}"
        )
        self.btn_enviar.clicked.connect(self._enviar_desde_input)
        hl_inp.addWidget(self.btn_enviar)

        hl_bar.addWidget(self._inp_box)
        self._bar_inp = bar_inp
        vl.addWidget(bar_inp)

    # ── API pública ───────────────────────────────────────────────────

    def set_modo(self, modo: str):
        """Adapta el chat a la tab activa (ACU/Insumos/Metrados/etc.).

        Cambia título, placeholder, botones rápidos y el system prompt
        que el worker envía al modelo. No limpia el historial existente
        para que el usuario pueda continuar la conversación al cambiar
        de tab.
        """
        if modo not in self._QUICK_BY_MODO:
            modo = 'ACU'
        if modo == self._modo:
            return
        self._modo = modo
        self._actualizar_titulo()
        if self._partida_id is None:
            self.inp_chat.setPlaceholderText(
                f"Seleccione una partida — modo {modo}…"
            )
        else:
            self.inp_chat.setPlaceholderText(self._PLACEHOLDER_BY_MODO[modo])
        self._rebuild_quick_buttons()

    def _rebuild_quick_buttons(self):
        """Vuelve a poblar la barra de botones rápidos según self._modo."""
        # Limpiar
        while self._hl_q.count():
            it = self._hl_q.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        for texto, pregunta in self._QUICK_BY_MODO.get(self._modo, []):
            btn = QPushButton(texto)
            btn.setFixedHeight(20)
            btn.setStyleSheet(self._BTN_Q)
            btn.clicked.connect(lambda _ch, p=pregunta: self._enviar(p, eco=False))
            self._hl_q.addWidget(btn)
        self._hl_q.addStretch()

    def set_partida(self, partida_id: int | None):
        """Llamar cuando cambia la partida seleccionada.

        Preserva el historial de la conversación: solo agrega un marcador
        visual indicando que el contexto cambió. Esto permite continuar la
        misma sesión refiriéndose a varias partidas, o pulsar 'Limpiar' si
        se quiere empezar de cero.
        """
        if partida_id == self._partida_id:
            return
        self._partida_id = partida_id
        self.lbl_estado_chat.setText("")
        # El contexto se refleja en el TÍTULO del terminal (ruta estilo
        # shell con el ítem de la partida) — sin marcadores en el chat,
        # para que la conversación se vea limpia.
        self._partida_item = ''
        if partida_id is not None:
            try:
                conn = get_db()
                row = conn.execute(
                    "SELECT item FROM partidas WHERE id=?", (partida_id,)
                ).fetchone()
                conn.close()
                self._partida_item = (row['item'] or '') if row else ''
            except Exception:
                self._partida_item = ''
        self._actualizar_titulo()
        if partida_id is None:
            self.inp_chat.setPlaceholderText(
                "Modo proyecto — pregunta sobre el proyecto completo…"
            )
        else:
            self.inp_chat.setPlaceholderText(
                self._PLACEHOLDER_BY_MODO.get(self._modo, "")
            )

    def _actualizar_titulo(self):
        """Título estilo path de shell: tuxia@proyecto: ~/modo/ítem-partida."""
        ruta = f"~/{(self._modo or 'acu').lower()}"
        if getattr(self, '_partida_item', ''):
            ruta += f"/{self._partida_item}"
        self.lbl_titulo.setText(f"tuxia@proyecto: {ruta}")

    # ── Internos ──────────────────────────────────────────────────────

    def _enviar_desde_input(self):
        texto = self.inp_chat.text().strip()
        if texto:
            self.inp_chat.clear()
            self._enviar(texto)

    def _enviar_ia_prompt(self, prompt_optimizado: str):
        """Despacha un prompt optimizado a la IA sin mostrar el texto crudo
        al usuario (lo lanza un comando local con su propia burbuja)."""
        if self._worker and self._worker.isRunning():
            return
        self._historial.append({'rol': 'usuario', 'texto': prompt_optimizado})
        self.btn_enviar.setEnabled(False)
        if self._partida_id is None:
            self.lbl_estado_chat.setText("● running · proyecto")
        else:
            self.lbl_estado_chat.setText(f"● running · {self._modo.lower()}")
        self._worker = _WorkerChat(
            self._partida_id, self._proyecto_id, list(self._historial),
            prompt_optimizado, self._modo, parent=self
        )
        self._worker.terminado.connect(self._on_respuesta)
        self._worker.start()

    def _enviar(self, texto: str, eco: bool = True):
        """`eco=False` (botones rápidos): el prompt NO se muestra en el chat
        — solo la respuesta. Igual se agrega al historial para el contexto IA."""
        if self._partida_id is None and self._proyecto_id is None:
            self._agregar_burbuja("asistente",
                "No hay proyecto activo.", error=True)
            return
        if self._worker and self._worker.isRunning():
            return

        if eco:
            self._agregar_burbuja("usuario", texto)
        self._historial.append({'rol': 'usuario', 'texto': texto})

        # ── Comandos especiales locales (no requieren IA) ─────────────────
        cmd = texto.strip().lower()
        from core.asistente_local import (
            analizar_proyecto, tip_aleatorio, mensaje_motivacional,
            chiste_aleatorio, top_insumos, top_partidas, pendientes,
            totales_detalle, ayuda_completa, respuesta_offline,
            TUX_TIP, TUX_FELIZ
        )

        def _resp(resp_text: str):
            self._agregar_burbuja("asistente", resp_text)
            self._historial.append({'rol': 'asistente', 'texto': resp_text})

        # ── Comandos que usan IA con prompt optimizado si está configurada ──
        from core.database import get_config as _gc
        _prov   = _gc('ia_proveedor', '')
        _apikey = _gc('api_key', '')
        _hay_ia = bool(_apikey) or _prov == 'ollama'

        if cmd in ('/analizar', '/analiza', '/revisar', '/check'):
            if _hay_ia and self._proyecto_id:
                # Prompt optimizado: pide insights priorizados, no solo datos
                self._enviar_ia_prompt(
                    "Analiza este proyecto a fondo. Identifica:\n"
                    "1. Las 3 partidas más críticas por costo o riesgo.\n"
                    "2. Inconsistencias detectadas (metrados faltantes, ACUs vacíos, "
                    "fórmula polinómica desbalanceada, precios anómalos).\n"
                    "3. Tres recomendaciones priorizadas, accionables.\n"
                    "Formato: viñetas, máximo 250 palabras. Cita cifras "
                    "exactas del resumen del proyecto."
                )
            else:
                _resp(analizar_proyecto(self._proyecto_id)
                      if self._proyecto_id else "Abre un proyecto primero.")
            return
        if cmd in ('/total', '/totales', '/montos'):
            _resp(totales_detalle(self._proyecto_id))
            return
        if cmd in ('/duplicados', '/dup', '/duplicados-insumos',
                   '/check-insumos'):
            from core.asistente_local import duplicados_detalle as _dd
            _resp(_dd(self._proyecto_id))
            return
        if cmd in ('/partidas', '/top', '/topcost'):
            _resp(top_partidas(self._proyecto_id))
            return
        if cmd in ('/insumos', '/recursos'):
            _resp(top_insumos(self._proyecto_id))
            return
        if cmd in ('/pendientes', '/faltan', '/falta'):
            _resp(pendientes(self._proyecto_id))
            return
        if cmd in ('/tip', '/consejo'):
            if _hay_ia:
                # Prompt optimizado: tip personalizado al contexto actual
                if self._partida_id:
                    self._enviar_ia_prompt(
                        "Dame UN solo consejo práctico y específico para la "
                        "partida abierta actualmente. Que sea aplicable hoy, "
                        "no una generalidad. Máximo 2 líneas."
                    )
                else:
                    self._enviar_ia_prompt(
                        "Dame UN solo consejo práctico aplicable hoy al "
                        "proyecto actual, basado en sus datos. No una "
                        "generalidad. Máximo 2 líneas."
                    )
            else:
                _resp(f"{TUX_TIP}\n\n💡 {tip_aleatorio()}")
            return
        if cmd in ('/animo', '/motivame', '/aliento'):
            _resp(f"{TUX_FELIZ}\n\n✦ {mensaje_motivacional()}")
            return
        if cmd in ('/chiste', '/broma', '/humor'):
            _resp(f"{TUX_FELIZ}\n\n😄 {chiste_aleatorio()}")
            return
        if cmd in ('/clear', '/cls'):
            self._limpiar_chat()
            self._mostrar_bienvenida()
            return
        if cmd in ('/help', '/ayuda', '/comandos'):
            _resp(ayuda_completa())
            return
        if cmd in ('/calc', '/calculadora', '/calcular'):
            from core.asistente_local import ayuda_calculadora
            _resp(ayuda_calculadora())
            return
        if cmd in ('/manual', '/tutorial', '/temas'):
            from core.asistente_local import listar_temas_manual
            _resp(listar_temas_manual())
            return
        if cmd in ('/notas',):
            self._abrir_panel_notas()
            return
        if cmd in ('/memoria', '/memos', '/recuerdos'):
            self._abrir_panel_memoria()
            return

        # ── Captura: "recuérdame que X" → append al bloc apropiado ──────────
        # Heurística: si menciona "este proyecto"/"aquí"/"la obra" → va a
        # NOTAS del proyecto (privadas, no contaminan el LLM). Si no, va
        # a MEMORIA GLOBAL (sí se inyecta al LLM como contexto).
        from core.memo_manager import detectar_captura, append_memoria
        _captura = detectar_captura(texto)
        if _captura:
            try:
                lower = _captura.lower()
                es_del_proyecto = any(t in lower for t in (
                    'este proyecto', 'del proyecto', 'la obra',
                    'esta obra', 'aqui', 'aquí'
                ))
                if es_del_proyecto and self._proyecto_id:
                    append_memoria(self._proyecto_id, _captura)
                    alcance = "🗒️ notas del proyecto (no se envía al LLM)"
                else:
                    append_memoria(None, _captura)
                    alcance = "🧠 memoria global (el LLM la usará)"
                _resp(f"{TUX_FELIZ}\n\nAnotado en {alcance}:\n"
                      f"«{_captura}»\n\nAbre los botones del header o "
                      "escribe «/notas» / «/memoria» para ver/editar.")
            except Exception as e:
                _resp(f"{TUX_TIP}\n\nNo pude guardar: {e}")
            return

        # ── Detección de mensajes conversacionales (hola, gracias, etc) ──
        # Se responde localmente sin pasar por la IA — instantáneo, sin
        # gastar tokens y con la personalidad de tuxia.
        from core.asistente_local import (
            detectar_conversacional, buscar_manual as _buscar_manual,
            evaluar_calculo,
        )
        resp_local = detectar_conversacional(texto)
        if resp_local is not None:
            _resp(resp_local)
            return

        # ── Calculadora local ─────────────────────────────────────────────
        # Si el usuario manda una operación aritmética, la resolvemos al
        # vuelo sin gastar tokens. Acepta + - * / ^ % (), 1,5*2, "calcula…".
        resp_calc = evaluar_calculo(texto)
        if resp_calc is not None:
            _resp(resp_calc)
            return

        # ── Búsqueda en el manual embebido (tutorial de la app) ──────────
        # Si la pregunta es del tipo "¿cómo X?" y matchea con un tema
        # conocido, respondemos del manual sin gastar tokens IA.
        resp_manual = _buscar_manual(texto)
        if resp_manual is not None:
            _resp(resp_manual)
            return

        # ── Búsqueda en memos del usuario ────────────────────────────────
        # Si la pregunta matchea con algún memo guardado, lo traemos. Solo
        # disparamos si el mensaje "huele a consulta" (palabras como cuál,
        # qué dije, recordé, precio, costo…) — para no over-trigger.
        try:
            t_low = texto.lower()
            es_consulta = any(t in t_low for t in (
                'cual era', 'cuál era', 'que dije', 'qué dije', 'recordas',
                'recuerdas', 'que recordas', 'tenia un memo', 'tenía un memo',
                'el memo', 'tu memo', 'cuanto era', 'cuánto era',
                '?', 'precio', 'costo'
            ))
            if es_consulta:
                from core.memo_manager import search_memos as _sm
                hits = _sm(texto, proyecto_id=self._proyecto_id, limit=3)
                hits = [(s, m) for s, m in hits if s >= 65]
                if hits:
                    lineas = [TUX_TIP, "", "📌 De mis memos:"]
                    for s, m in hits:
                        alcance = '(global)' if m['proyecto_id'] is None else ''
                        lineas.append(f"  [{m['id']}] {m['texto']} {alcance}".rstrip())
                    _resp("\n".join(lineas))
                    return
        except Exception:
            pass

        # ── Fallback offline: si no hay api_key, respuesta local ──────────
        from core.database import get_config
        prov = get_config('ia_proveedor', '')
        api_key = get_config('api_key', '')
        if not api_key and prov != 'ollama':
            resp = respuesta_offline(texto, self._proyecto_id)
            self._agregar_burbuja("asistente", resp)
            self._historial.append({'rol': 'asistente', 'texto': resp})
            return

        self.btn_enviar.setEnabled(False)
        if self._partida_id is None:
            self.lbl_estado_chat.setText("● running · proyecto")
        else:
            self.lbl_estado_chat.setText(f"● running · {self._modo.lower()}")

        # parent=self → previene que el GC mate el QThread antes de terminar
        self._worker = _WorkerChat(
            self._partida_id, self._proyecto_id, list(self._historial),
            texto, self._modo, parent=self
        )
        self._worker.terminado.connect(self._on_respuesta)
        self._worker.start()

    def _on_respuesta(self, respuesta: str, error: str):
        self.btn_enviar.setEnabled(True)
        self.lbl_estado_chat.setText("")
        if error:
            self._agregar_burbuja("asistente", f"Error: {error}", error=True)
            return
        # Truncar respuestas extremadamente largas — QLabel.setWordWrap con
        # texto enorme puede consumir mucha memoria y crashear el proceso al
        # recalcular layout. Si excede el límite, mostrar versión recortada
        # con botón para abrir el texto completo en un diálogo scrollable.
        MAX = 8000
        if len(respuesta) > MAX:
            corto = respuesta[:MAX].rsplit('\n', 1)[0]
            self._agregar_burbuja(
                "asistente",
                corto + f"\n\n[respuesta truncada — {len(respuesta):,} caracteres]"
            )
            self._agregar_boton_ver_completo(respuesta)
        else:
            self._agregar_burbuja("asistente", respuesta)
        self._historial.append({'rol': 'asistente', 'texto': respuesta})

    def _agregar_boton_ver_completo(self, texto: str):
        """Inserta un botón inline 'Ver respuesta completa' que abre un
        diálogo scrollable con el texto íntegro."""
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QTextEdit
        btn = QPushButton("  ⤴  Ver respuesta completa …")
        btn.setStyleSheet(
            f"QPushButton {{ background:transparent; color:{self._TERM_ACCENT};"
            f" border:1px dashed {self._TERM_BORDER}; border-radius:4px;"
            f" padding:4px 10px; font-size:11px;"
            f" font-family:{self._FONT_MONO}; text-align:left; }}"
            f"QPushButton:hover {{ background:{self._TERM_HDR_BG};"
            f" border-style:solid; }}"
        )
        def _abrir():
            dlg = QDialog(self.window())
            dlg.setWindowTitle("Respuesta completa")
            dlg.resize(720, 520)
            vl = QVBoxLayout(dlg)
            vl.setContentsMargins(0, 0, 0, 0)
            te = QTextEdit()
            te.setReadOnly(True)
            te.setPlainText(texto)
            te.setStyleSheet(
                f"QTextEdit {{ background:{self._TERM_BG};"
                f" color:{self._TERM_FG}; border:none;"
                f" font-family:{self._FONT_MONO}; font-size:12px;"
                f" padding:12px; }}"
            )
            vl.addWidget(te)
            dlg.exec()
        btn.clicked.connect(_abrir)
        count = self._msgs_layout.count()
        self._msgs_layout.insertWidget(count - 1, btn)

    def _agregar_burbuja(self, rol: str, texto: str, error: bool = False):
        """Renderiza una línea estilo terminal: prompt sigil + contenido.
        - Usuario:  `$ <mensaje>`     (sigil verde estilo bash)
        - Asistente: `tuxia> <resp>`  (sigil indigo)
        - Error:    `! <mensaje>`     (sigil rojo)
        """
        if error:
            sigil_txt   = "!"
            sigil_color = self._TERM_ERR
            text_color  = self._TERM_ERR
        elif rol == 'usuario':
            sigil_txt   = "$"
            sigil_color = self._TERM_USER   # Lime elementary
            text_color  = self._TERM_FG
        else:
            sigil_txt   = "tuxia>"
            sigil_color = self._TERM_AI
            text_color  = self._TERM_FG

        row = QFrame()
        if rol == 'usuario':
            # Línea de comando: plana sobre el fondo, como en una shell
            row.setStyleSheet("background:transparent; border:none;")
            margenes = (2, 2, 2, 2)
        elif error:
            # Error: bloque redondeado con tinte rojizo
            row.setStyleSheet(
                "background:#2A191B; border:none; border-radius:8px;")
            margenes = (10, 7, 10, 7)
        else:
            # Respuesta de tuxia: bloque redondeado (estilo Warp)
            row.setStyleSheet(
                f"background:{self._TERM_CARD}; border:none;"
                f" border-radius:8px;")
            margenes = (10, 7, 10, 7)
        hl = QHBoxLayout(row)
        hl.setContentsMargins(*margenes)
        hl.setSpacing(6)

        lbl_sigil = QLabel(sigil_txt)
        lbl_sigil.setStyleSheet(
            f"color:{sigil_color}; background:transparent; border:none;"
            f" font-family:{self._FONT_MONO}; font-size:13px; font-weight:700;"
        )
        lbl_sigil.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        hl.addWidget(lbl_sigil, 0, Qt.AlignTop)

        lbl_texto = QLabel(texto)
        lbl_texto.setWordWrap(True)
        lbl_texto.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lbl_texto.setStyleSheet(
            f"color:{text_color}; background:transparent; border:none;"
            f" font-family:{self._FONT_MONO}; font-size:13px;"
        )
        lbl_texto.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        hl.addWidget(lbl_texto, 1)

        count = self._msgs_layout.count()
        self._msgs_layout.insertWidget(count - 1, row)

        QTimer.singleShot(50, lambda: self._scroll.verticalScrollBar().setValue(
            self._scroll.verticalScrollBar().maximum()
        ))

    def _agregar_marker(self, texto: str):
        """Inserta un marcador sutil tipo comentario shell (# ...) cuando
        cambia el contexto. No se envía al modelo."""
        lbl = QLabel(f"# {texto}")
        lbl.setStyleSheet(
            f"color:{self._TERM_DIM}; font-size:12px; font-style:italic;"
            f" background:transparent; border:none; padding:3px 0;"
            f" font-family:{self._FONT_MONO};"
        )
        count = self._msgs_layout.count()
        self._msgs_layout.insertWidget(count - 1, lbl)
        QTimer.singleShot(50, lambda: self._scroll.verticalScrollBar().setValue(
            self._scroll.verticalScrollBar().maximum()
        ))

    def _limpiar_mensajes(self):
        # `_agregar_burbuja` mete cada mensaje como QFrame (widget item).
        # El layout también puede tener un addStretch() final que NO se quita
        # (de ahí el `> 1`, preserva el último item = stretch).
        # Antes esta función solo limpiaba items con .layout(); los widgets
        # quedaban en pantalla aunque takeAt los desligara del layout.
        while self._msgs_layout.count() > 1:
            item = self._msgs_layout.takeAt(0)
            if item is None:
                break
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
                continue
            inner = item.layout()
            if inner is not None:
                while inner.count():
                    sub = inner.takeAt(0)
                    sub_w = sub.widget() if sub else None
                    if sub_w is not None:
                        sub_w.setParent(None)
                        sub_w.deleteLater()

    def _limpiar_chat(self):
        self._historial = []
        self._limpiar_mensajes()

    def _build_memoria_panel(self) -> QWidget:
        """Construye el panel embebido tipo bloc — reutilizable para NOTAS
        del proyecto (privadas) o MEMORIA global (se inyecta al LLM). El
        modo se setea al entrar vía `_abrir_panel_notas`/`_abrir_panel_memoria`,
        que reconfiguran título, placeholder y target de guardado.
        """
        from PySide6.QtWidgets import QTextEdit
        from PySide6.QtGui import QShortcut, QKeySequence

        panel = QWidget()
        panel.setStyleSheet(f"background:{self._TERM_BG};")
        vl = QVBoxLayout(panel)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)

        # ── Barra superior ────────────────────────────────────────────────
        bar = QFrame()
        bar.setFixedHeight(30)
        bar.setStyleSheet(
            f"background:{self._TERM_HDR_BG};"
            f" border-bottom:1px solid {self._TERM_BORDER};"
        )
        hl = QHBoxLayout(bar)
        hl.setContentsMargins(10, 0, 8, 0)
        hl.setSpacing(8)

        btn_back = QPushButton("← chat")
        btn_back.setFixedHeight(20)
        btn_back.setCursor(Qt.PointingHandCursor)
        btn_back.setStyleSheet(
            f"QPushButton {{ background:transparent; color:{self._TERM_DIM};"
            f" border:1px solid {self._TERM_BORDER}; border-radius:4px;"
            f" font-size:10px; padding:0 8px;"
            f" font-family:{self._FONT_MONO}; }}"
            f"QPushButton:hover {{ color:{self._TERM_HDR_FG};"
            f" border-color:{self._TERM_ACCENT}; }}"
        )
        btn_back.clicked.connect(self._volver_a_chat)
        hl.addWidget(btn_back)

        self.lbl_bloc_titulo = QLabel("🗒️ notas")
        self.lbl_bloc_titulo.setStyleSheet(
            f"color:{self._TERM_HDR_FG}; font-size:11px; font-weight:600;"
            f" border:none; background:transparent;"
            f" font-family:{self._FONT_MONO};"
        )
        hl.addWidget(self.lbl_bloc_titulo)

        self.lbl_bloc_sub = QLabel("")
        self.lbl_bloc_sub.setStyleSheet(
            f"color:{self._TERM_DIM}; font-size:10px;"
            f" border:none; background:transparent;"
            f" font-family:{self._FONT_MONO};"
        )
        hl.addWidget(self.lbl_bloc_sub)
        hl.addStretch()

        self.lbl_mem_estado = QLabel("")
        self.lbl_mem_estado.setStyleSheet(
            f"color:{self._TERM_DIM}; font-size:10px;"
            f" background:transparent; border:none;"
            f" font-family:{self._FONT_MONO};"
        )
        hl.addWidget(self.lbl_mem_estado)

        btn_save = QPushButton("💾 guardar")
        btn_save.setFixedHeight(20)
        btn_save.setCursor(Qt.PointingHandCursor)
        btn_save.setStyleSheet(
            f"QPushButton {{ background:{self._TERM_ACCENT}; color:white;"
            f" border:none; border-radius:4px; padding:0 10px;"
            f" font-size:10px; font-weight:600;"
            f" font-family:{self._FONT_MONO}; }}"
            f"QPushButton:hover {{ background:{self._TERM_HOVER}; }}"
        )
        btn_save.clicked.connect(self._guardar_bloc)
        hl.addWidget(btn_save)
        vl.addWidget(bar)

        # ── Editor único (sin tabs) ───────────────────────────────────────
        edit_style = (
            f"QTextEdit {{ background:{self._TERM_BG};"
            f" color:{self._TERM_FG}; border:none;"
            f" font-family:{self._FONT_MONO}; font-size:13px;"
            f" padding:10px 12px;"
            f" selection-background-color:{self._TERM_ACCENT};"
            f" selection-color:white; }}"
            f"QScrollBar:vertical {{ background:{self._TERM_BG};"
            f" width:8px; border:none; }}"
            f"QScrollBar::handle:vertical {{ background:{self._TERM_BORDER};"
            f" border-radius:4px; min-height:24px; }}"
            f"QScrollBar::handle:vertical:hover {{ background:#3A4654; }}"
            f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical"
            f" {{ height:0; background:none; }}"
        )
        self.txt_bloc = QTextEdit()
        self.txt_bloc.setAcceptRichText(False)
        self.txt_bloc.setStyleSheet(edit_style)
        vl.addWidget(self.txt_bloc, stretch=1)
        self.txt_bloc.textChanged.connect(self._on_bloc_mod)

        # Ctrl+S
        QShortcut(QKeySequence("Ctrl+S"), self).activated.connect(
            self._guardar_bloc_si_visible
        )

        # Estado: 'notas' (proyecto_id) | 'memoria' (None) | None
        self._bloc_modo: str | None = None
        self._bloc_mod = False
        return panel

    def _abrir_panel_notas(self):
        """Abre el bloc de NOTAS del proyecto (privadas, no van al LLM)."""
        if not self._proyecto_id:
            self._agregar_burbuja(
                "asistente",
                "Las notas son del proyecto activo. Abre un proyecto primero "
                "o usa «🧠 memoria» para notas globales."
            )
            return
        self._abrir_bloc('notas', self._proyecto_id,
                         "🗒️ notas",
                         "(privadas del proyecto — NO se envían al LLM)",
                         "# notas de este proyecto\n"
                         "# clientes, decisiones, pendientes administrativos…")

    def _abrir_panel_memoria(self):
        """Abre el bloc MEMORIA GLOBAL (el LLM lo recibe como contexto)."""
        self._abrir_bloc('memoria', None,
                         "🧠 memoria",
                         "(global — el LLM la recibe como contexto en cada pregunta)",
                         "# memoria global de Tuxia\n"
                         "# precios referenciales, fórmulas habituales, "
                         "datos técnicos que quieres que la IA tenga presente…")

    def _abrir_bloc(self, modo: str, proyecto_id: int | None,
                    titulo: str, subtitulo: str, placeholder: str):
        from core.memo_manager import get_memoria
        self._bloc_modo = modo
        self._bloc_proyecto_id = proyecto_id
        self.lbl_bloc_titulo.setText(titulo)
        self.lbl_bloc_sub.setText(subtitulo)
        self.txt_bloc.setPlaceholderText(placeholder)
        self.txt_bloc.blockSignals(True)
        self.txt_bloc.setPlainText(get_memoria(proyecto_id))
        self.txt_bloc.blockSignals(False)
        self._bloc_mod = False
        self.lbl_mem_estado.setText("")
        self._msgs_stack.setCurrentIndex(1)
        if hasattr(self, '_bar_quick'):
            self._bar_quick.setVisible(False)
        if hasattr(self, '_bar_inp'):
            self._bar_inp.setVisible(False)

    def _volver_a_chat(self):
        if self._bloc_mod:
            res = QMessageBox.question(
                self, "Cambios sin guardar",
                "Tienes cambios sin guardar. ¿Guardar antes de volver al chat?",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel
            )
            if res == QMessageBox.Cancel:
                return
            if res == QMessageBox.Yes:
                self._guardar_bloc()
        self._msgs_stack.setCurrentIndex(0)
        if hasattr(self, '_bar_quick'):
            self._bar_quick.setVisible(True)
        if hasattr(self, '_bar_inp'):
            self._bar_inp.setVisible(True)

    def _on_bloc_mod(self):
        self._bloc_mod = True
        self.lbl_mem_estado.setText("● sin guardar")
        self.lbl_mem_estado.setStyleSheet(
            f"color:#FFC857; font-size:10px; background:transparent;"
            f" border:none; font-family:{self._FONT_MONO};"
        )

    def _guardar_bloc_si_visible(self):
        if self._msgs_stack.currentIndex() == 1:
            self._guardar_bloc()

    def _guardar_bloc(self):
        if self._bloc_modo is None:
            return
        from core.memo_manager import set_memoria
        set_memoria(self._bloc_proyecto_id, self.txt_bloc.toPlainText())
        self._bloc_mod = False
        self.lbl_mem_estado.setText("✓ guardado")
        self.lbl_mem_estado.setStyleSheet(
            f"color:#9EE493; font-size:10px; background:transparent;"
            f" border:none; font-family:{self._FONT_MONO};"
        )
        QTimer.singleShot(2200, lambda: self.lbl_mem_estado.setText(""))



# ══════════════════════════════════════════════════════════════════════════════
# Diálogo flotante con _ChatACU embebido (para usar fuera de la vista principal)
# ══════════════════════════════════════════════════════════════════════════════

class _ChatTuxiaDialog(QDialog):
    """Ventana flotante estilo Messenger (esquina inferior derecha) con un
    `_ChatACU` embebido y tema terminal elementary OS. Usada cuando el
    usuario abre Tuxia desde el cronograma u otra vista anclada."""

    WIDTH  = 380
    HEIGHT = 520
    MARGIN = 18    # separación de los bordes del padre

    def __init__(self, proyecto_id: int, modo: str = 'Cronograma',
                 titulo: str = "Asistente Tuxia", parent=None):
        super().__init__(parent)
        self.setWindowTitle(titulo)
        # Ventana tipo Tool — ligera, sin botones max/min, no aparece en taskbar
        self.setWindowFlags(
            Qt.Tool | Qt.WindowTitleHint | Qt.WindowCloseButtonHint
        )
        self.setFixedSize(self.WIDTH, self.HEIGHT)
        self.setStyleSheet("QDialog { background:#1E1E1E; }")
        vl = QVBoxLayout(self)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)
        self.chat = _ChatACU(self)
        self.chat.set_proyecto(proyecto_id)
        self.chat.set_partida(None)
        self.chat.set_modo(modo)
        vl.addWidget(self.chat)
        # Anclar a la esquina inferior derecha del padre
        QTimer.singleShot(0, self._anclar_inferior_derecha)

    def _anclar_inferior_derecha(self):
        p = self.parent()
        if p is None:
            return
        # Mover a la esquina inferior derecha del padre, mapeado a global
        from PySide6.QtCore import QPoint
        bottom_right_global = p.mapToGlobal(QPoint(p.width(), p.height()))
        x = bottom_right_global.x() - self.WIDTH - self.MARGIN
        y = bottom_right_global.y() - self.HEIGHT - self.MARGIN
        self.move(max(0, x), max(0, y))


# ══════════════════════════════════════════════════════════════════════════════
# Tuxia Helper — asistente flotante estilo Clippy
# ══════════════════════════════════════════════════════════════════════════════

class _TuxiaSpeechBubble(QFrame):
    """Globo de diálogo que aparece al lado del icono tuxia con un tip
    contextual. Tiene texto, opcional botón 'Aplicar', y un cierre X."""

    cerrado    = Signal()      # X presionado o auto-fade
    accion_clk = Signal()      # botón "Aplicar" presionado
    cuerpo_clk = Signal()      # click en cuerpo → abrir chat

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("tuxiaBubble")
        # Fondo blanco forzado vía QPalette + autoFillBackground. Algunos
        # sistemas con tema oscuro (XCB / GTK adwaita-dark) ignoran el
        # stylesheet del QFrame y pintan con la palette del sistema. Esto
        # se ve como un cuadro negro con texto ilegible.
        from PySide6.QtGui import QPalette as _QPal
        pal = self.palette()
        pal.setColor(_QPal.Window,     QColor("#FFFFFF"))
        pal.setColor(_QPal.Base,       QColor("#FFFFFF"))
        pal.setColor(_QPal.WindowText, QColor("#0F172A"))
        pal.setColor(_QPal.Text,       QColor("#0F172A"))
        pal.setColor(_QPal.ButtonText, QColor("#4F46E5"))
        self.setPalette(pal)
        self.setAutoFillBackground(True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        # Stylesheet redundante (para mostrar borde redondeado donde el QSS sí
        # se aplica). El bg ya está forzado vía palette arriba.
        self.setStyleSheet(
            "QFrame#tuxiaBubble {"
            " background:#FFFFFF; border:1px solid #C7D2FE;"
            " border-radius:10px;"
            "}"
            "#tuxiaBubble QLabel {"
            " background:transparent; color:#0F172A;"
            "}"
            "#tuxiaBubble QPushButton {"
            " background:transparent; color:#4F46E5; border:none;"
            "}"
        )
        # Sombra suave
        try:
            from utils.theme import apply_shadow
            apply_shadow(self, 'md')
        except Exception:
            pass
        self.setMinimumWidth(250)
        self.setMaximumWidth(340)
        self._build()

    def _build(self):
        vl = QVBoxLayout(self)
        vl.setContentsMargins(12, 8, 8, 10)
        vl.setSpacing(6)

        from PySide6.QtGui import QPalette as _QPal
        hl_top = QHBoxLayout()
        hl_top.setSpacing(0)
        self.lbl_titulo = QLabel("tuxia · tip")
        # Palette explícita en el label para sistemas con tema oscuro
        _pal_t = self.lbl_titulo.palette()
        _pal_t.setColor(_QPal.WindowText, QColor("#4F46E5"))
        _pal_t.setColor(_QPal.Text,       QColor("#4F46E5"))
        self.lbl_titulo.setPalette(_pal_t)
        self.lbl_titulo.setAutoFillBackground(False)
        self.lbl_titulo.setStyleSheet(
            "color:#4F46E5; font-size:10px; font-weight:700;"
            " background:transparent; border:none;"
            " letter-spacing:0.3px;"
        )
        hl_top.addWidget(self.lbl_titulo)
        hl_top.addStretch()
        self.btn_x = QPushButton("✕")
        self.btn_x.setFixedSize(18, 18)
        self.btn_x.setCursor(Qt.PointingHandCursor)
        self.btn_x.setStyleSheet(
            "QPushButton { background:transparent; color:#94A3B8;"
            " border:none; font-size:13px; }"
            "QPushButton:hover { color:#475569; }"
        )
        self.btn_x.clicked.connect(self.cerrado.emit)
        hl_top.addWidget(self.btn_x)
        vl.addLayout(hl_top)

        self.lbl_texto = QLabel("")
        self.lbl_texto.setWordWrap(True)
        # Palette explícita: texto oscuro siempre legible sobre el bg blanco
        _pal_x = self.lbl_texto.palette()
        _pal_x.setColor(_QPal.WindowText, QColor("#0F172A"))
        _pal_x.setColor(_QPal.Text,       QColor("#0F172A"))
        self.lbl_texto.setPalette(_pal_x)
        self.lbl_texto.setStyleSheet(
            "color:#0F172A; font-size:11px; background:transparent;"
            " border:none; padding-right:4px;"
        )
        self.lbl_texto.setTextInteractionFlags(Qt.TextSelectableByMouse)
        vl.addWidget(self.lbl_texto)

        hl_b = QHBoxLayout()
        hl_b.setSpacing(6)
        hl_b.addStretch()
        self.btn_chat = QPushButton("Abrir chat")
        self.btn_chat.setCursor(Qt.PointingHandCursor)
        self.btn_chat.setFixedHeight(22)
        self.btn_chat.setStyleSheet(
            "QPushButton { background:transparent; color:#4F46E5;"
            " border:none; font-size:10px; font-weight:600;"
            " padding:0 6px; }"
            "QPushButton:hover { color:#312E81; text-decoration:underline; }"
        )
        self.btn_chat.clicked.connect(self.cuerpo_clk.emit)
        hl_b.addWidget(self.btn_chat)

        self.btn_aplicar = QPushButton("Ir")
        self.btn_aplicar.setCursor(Qt.PointingHandCursor)
        self.btn_aplicar.setFixedHeight(22)
        self.btn_aplicar.setStyleSheet(
            "QPushButton { background:#6366F1; color:white; border:none;"
            " border-radius:6px; padding:0 12px; font-size:10px;"
            " font-weight:600; }"
            "QPushButton:hover { background:#4F46E5; }"
        )
        self.btn_aplicar.clicked.connect(self.accion_clk.emit)
        self.btn_aplicar.setVisible(False)
        hl_b.addWidget(self.btn_aplicar)
        vl.addLayout(hl_b)

    def set_tip(self, texto: str, accion_label: str | None = None,
                titulo: str = "tuxia · tip"):
        self.lbl_titulo.setText(titulo)
        self.lbl_texto.setText(texto)
        if accion_label:
            self.btn_aplicar.setText(accion_label)
            self.btn_aplicar.setVisible(True)
        else:
            self.btn_aplicar.setVisible(False)
        self.adjustSize()


class _TuxiaCircleButton(QPushButton):
    """QPushButton circular pintado manualmente con QPainter.

    Esquivamos el QSS porque el cascade del stylesheet global
    (`QPushButton { border-radius:6px; padding:4px 14px; min-height:28px }`)
    pisaba el `border-radius:24` local tras un ciclo hide/show del helper
    — el ícono salía como un rect pequeño con esquinas suaves en vez de
    círculo. Con paintEvent propio la forma queda blindada.
    """

    drag_moved = Signal(object)     # QPoint delta global
    drag_finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hovered = False
        self._glow = False
        self._drag_start_global = None
        self._is_dragging = False
        self.setStyleSheet("QPushButton { background:transparent; border:none;"
                           " padding:0; min-height:0; min-width:0; }")
        self.setAttribute(Qt.WA_Hover, True)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._drag_start_global = ev.globalPosition().toPoint()
            self._is_dragging = False
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if self._drag_start_global is not None:
            delta = ev.globalPosition().toPoint() - self._drag_start_global
            if not self._is_dragging and (abs(delta.x()) + abs(delta.y())) > 6:
                self._is_dragging = True
            if self._is_dragging:
                self.drag_moved.emit(delta)
                return
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            was_dragging = self._is_dragging
            self._drag_start_global = None
            self._is_dragging = False
            if was_dragging:
                self.drag_finished.emit()
                return
        super().mouseReleaseEvent(ev)

    def enterEvent(self, ev):
        self._hovered = True
        self.update()
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        self._hovered = False
        self.update()
        super().leaveEvent(ev)

    def set_glow(self, glow: bool):
        if self._glow != glow:
            self._glow = glow
            self.update()

    def paintEvent(self, _ev):
        from PySide6.QtGui import QPainter, QColor, QPen
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        rect = self.rect().adjusted(1, 1, -1, -1)  # 1px margen para el borde
        # Fondo: círculo blanco
        p.setBrush(QColor("#FFFFFF"))
        if self._hovered:
            pen = QPen(QColor("#6366F1"), 2)
        elif self._glow:
            pen = QPen(QColor("#6366F1"), 2)
        else:
            pen = QPen(QColor("#C7D2FE"), 1)
        p.setPen(pen)
        p.drawEllipse(rect)
        # Icono centrado — QIcon.pixmap(isz) preserva el aspect ratio del PNG
        # fuente (Tux: 650×782 ≈ 0.83), así que el pixmap real puede ser
        # más chico que iconSize en una dimensión. Lo dibujamos en su
        # tamaño natural (no en un rect 36×36 que lo estiraría) usando
        # las dimensiones LÓGICAS = pixels / devicePixelRatio para
        # centrar correctamente en HiDPI.
        ic = self.icon()
        if not ic.isNull():
            pm = ic.pixmap(self.iconSize())
            dpr = pm.devicePixelRatio() or 1.0
            logical_w = int(pm.width() / dpr)
            logical_h = int(pm.height() / dpr)
            x = (self.width() - logical_w) // 2
            y = (self.height() - logical_h) // 2
            p.drawPixmap(x, y, pm)
        p.end()


class _TuxiaHelper(QWidget):
    """Asistente flotante: icono tuxia + speech bubble contextual.

    Se ancla al `parent` (ProyectoView) y se posiciona en la esquina
    inferior derecha. Eventos del proyecto disparan `show_tip(texto, ...)`
    que muestra el globo durante ~12s (configurable).
    """

    chat_solicitado = Signal()   # usuario clickeó el icono → abrir chat
    accion_solicitada = Signal(str)  # accion_id → handler externo

    BUBBLE_AUTO_FADE_MS = 12000

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        # Estado del tip actual
        self._accion_id: str | None = None
        # Key del tip actual (para tracking anti-repetición)
        self._tip_key: str | None = None
        # Tips ya mostrados en esta sesión (in-memory). Persistencia
        # permanente via QSettings.
        self._tips_sesion: set[str] = set()
        from PySide6.QtCore import QSettings as _QS
        self._qs = _QS("ingePresupuestos", "tuxia")
        self._build()
        # Arranca oculto: se mostrará tras reposicionar correctamente para
        # evitar un flash en (0,0) antes de anclarse a la esquina derecha.
        super().setVisible(False)
        # Timer de auto-fade del globo
        self._fade_timer = QTimer(self)
        self._fade_timer.setSingleShot(True)
        self._fade_timer.timeout.connect(self._ocultar_bubble)
        # Timer de animación pulsante del icono
        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(450)
        self._pulse_step = 0
        self._pulse_timer.timeout.connect(self._tick_pulse)
        # ── Animaciones Nivel 1 (idle bounce, entry, pop al hablar, hover) ──
        self._setup_animations()
        self._first_show = True
        # ── Tips ambient: capacidades + motivacional + técnico ────────────
        # Cada 10-15 min, Tuxia muestra espontáneamente una de sus
        # capacidades o un mensaje motivador. Se pausa cuando el chat está
        # abierto o el usuario está en otra vista (cronograma/reportes/etc).
        self._ambient_history: list[str] = []  # últimas keys mostradas
        self._ambient_timer = QTimer(self)
        self._ambient_timer.timeout.connect(self._tick_ambient)
        # Primer tip al cabo de 2-4 min (no inmediatamente — dejar al
        # usuario aterrizar primero).
        import random as _rnd
        self._ambient_timer.start(_rnd.randint(120_000, 240_000))

    # ── Drag para mover Tuxia ────────────────────────────────────────────
    def _install_drag(self):
        self._user_pos = None
        self._drag_origin = None
        self.btn_tux.drag_moved.connect(self._on_drag_moved)
        self.btn_tux.drag_finished.connect(self._on_drag_finished)

    def _on_drag_moved(self, delta):
        if self._drag_origin is None:
            self._drag_origin = self.pos()
            self._bounce.stop()
        new_pos = self._drag_origin + delta
        p = self.parent()
        if p:
            new_pos.setX(max(0, min(new_pos.x(), p.width() - self.width())))
            new_pos.setY(max(0, min(new_pos.y(), p.height() - self.height())))
        self.move(new_pos)

    def _on_drag_finished(self):
        self._user_pos = self.pos()
        self._drag_origin = None
        self._btn_home = QRect(
            self.btn_tux.geometry().x(),
            self.btn_tux.geometry().y(), 48, 48)
        self._start_idle_bounce()

    def _setup_animations(self):
        """Prepara las QPropertyAnimation reutilizables — idle bounce
        infinito, entry slide-up+fade, pop al hablar, hover scale."""
        from PySide6.QtCore import QPropertyAnimation, QEasingCurve, QRect

        # El QGraphicsOpacityEffect se crea/destruye on-demand en
        # _animate_entry — mantenerlo permanentemente introduce un dithering
        # sutil que se ve como "ícono ligeramente transparente".

        # Idle bounce: respira ±3 px en Y cada 2 s, loop infinito.
        # Anima `geometry` (no `pos`) para que el pop pueda coexistir.
        self._bounce = QPropertyAnimation(self.btn_tux, b"geometry", self)
        self._bounce.setDuration(2200)
        self._bounce.setLoopCount(-1)
        self._bounce.setEasingCurve(QEasingCurve.Type.InOutSine)
        # Pop al hablar (scale ±5 px, vuelta a base).
        self._pop = QPropertyAnimation(self.btn_tux, b"geometry", self)
        self._pop.setDuration(220)
        self._pop.setEasingCurve(QEasingCurve.Type.OutBack)
        self._pop.finished.connect(self._resume_bounce_after_pop)

    def _set_btn_home(self, x: int, y: int):
        """Registra la posición canónica del botón. Llamado cada vez que
        el layout decide moverlo (mostrar/ocultar bubble). Reinicia el
        bounce si está activo para que loopee desde la nueva home."""
        from PySide6.QtCore import QRect, QAbstractAnimation
        self._btn_home = QRect(x, y, 48, 48)
        self.btn_tux.setGeometry(self._btn_home)
        # Si el bounce estaba corriendo, lo reiniciamos desde la nueva home.
        if (hasattr(self, '_bounce')
                and self._bounce.state() == QAbstractAnimation.State.Running):
            self._start_idle_bounce()

    def _start_idle_bounce(self):
        from PySide6.QtCore import QRect
        if not hasattr(self, '_btn_home'):
            return
        base = self._btn_home
        up = QRect(base.x(), base.y() - 3, base.width(), base.height())
        self._bounce.stop()
        self._bounce.setStartValue(base)
        self._bounce.setKeyValueAt(0.5, up)
        self._bounce.setEndValue(base)
        self._bounce.start()

    def _stop_idle_bounce(self):
        self._bounce.stop()
        # Restaurar la pos canónica (sin forzar (0,0) — el helper la maneja).
        if hasattr(self, '_btn_home'):
            self.btn_tux.setGeometry(self._btn_home)

    def _animate_pop(self):
        """Pequeño "salto" vertical cuando aparece un tip. NO cambia size,
        solo position — así el botón permanece circular. Pausa el bounce
        mientras dura y lo reanuda al terminar."""
        from PySide6.QtCore import QAbstractAnimation, QRect
        if not hasattr(self, '_btn_home'):
            return
        if self._bounce.state() == QAbstractAnimation.State.Running:
            self._bounce.stop()
        base = self._btn_home
        # Salto vertical: -10 px en el punto medio, vuelve a la home.
        up = QRect(base.x(), base.y() - 10, base.width(), base.height())
        self._pop.stop()
        self._pop.setStartValue(base)
        self._pop.setKeyValueAt(0.5, up)
        self._pop.setEndValue(base)
        self._pop.start()

    def _resume_bounce_after_pop(self):
        """Slot conectado a `self._pop.finished`. Vuelve al idle bounce
        siempre que el helper siga visible."""
        if self.isVisible():
            self._start_idle_bounce()

    def _animate_entry(self):
        """Slide-up desde abajo al mostrarse por primera vez.

        Intencionalmente SIN fade-in (sin QGraphicsOpacityEffect) — el effect
        deja residuo de rendering "translúcido" en Wayland/X11 con compositing
        que se ve como ícono fantasma todo el tiempo. El slide-up solo ya da
        la sensación de "aparición" sin ese costo."""
        from PySide6.QtCore import (
            QPropertyAnimation, QEasingCurve, QAbstractAnimation, QRect,
        )
        if not hasattr(self, '_btn_home'):
            self._set_btn_home(0, 0)
        # Garantía defensiva: si por alguna razón quedó un effect aplicado,
        # quitarlo antes de animar. El botón debe quedar opaco 100 %.
        if self.btn_tux.graphicsEffect() is not None:
            self.btn_tux.setGraphicsEffect(None)

        base = self._btn_home
        offset = QRect(base.x(), base.y() + 18, base.width(), base.height())
        self.btn_tux.setGeometry(offset)

        move = QPropertyAnimation(self.btn_tux, b"geometry", self)
        move.setDuration(380)
        move.setStartValue(offset)
        move.setEndValue(base)
        move.setEasingCurve(QEasingCurve.Type.OutCubic)
        move.finished.connect(self._start_idle_bounce)
        move.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)

    def eventFilter(self, obj, ev):
        # El hover ya se maneja vía QSS `QPushButton:hover` (cambia el
        # border a azul). NO animamos size en hover para mantener el
        # botón siempre circular.
        return super().eventFilter(obj, ev)

    def setVisible(self, visible: bool):
        was_visible = self.isVisible()
        super().setVisible(visible)
        if visible:
            if self._first_show:
                self._first_show = False
                self._animate_entry()
            elif not was_visible:
                # Re-show después de oculto: directo a idle (sin entry).
                self._start_idle_bounce()
        else:
            self._stop_idle_bounce()

    def _build(self):
        """Layout libre con posicionamiento absoluto.

        Evitamos QLayout porque los layouts reservan espacio incluso para
        widgets hidden, lo que hacía que el helper saliera enorme y se
        ubicara mal en el flujo del padre.
        """
        self.setStyleSheet("background: transparent;")
        self.setAttribute(Qt.WA_StyledBackground, False)

        # Icono tuxia (botón circular pintado a mano — ver _TuxiaCircleButton).
        self.btn_tux = _TuxiaCircleButton(self)
        self.btn_tux.setFixedSize(48, 48)
        self.btn_tux.setCursor(Qt.PointingHandCursor)
        self.btn_tux.setIcon(load_icon("tuxia"))
        self.btn_tux.setIconSize(QSize(36, 36))
        # Usar el helper de tooltip propio (evita el bug del tema oscuro
        # del sistema que pinta el tooltip de Qt en negro).
        try:
            from utils.tooltip import set_tooltip as _set_tt
            _set_tt(self.btn_tux,
                    "Asistente Tuxia — click para abrir el chat")
        except Exception:
            from utils.i18n import tr as _tr_tux
            self.btn_tux.setToolTip(_tr_tux("Asistente Tuxia — click para abrir el chat"))
        self._set_btn_style()
        self.btn_tux.clicked.connect(self._on_chat)
        self._install_drag()

        # Speech bubble (hidden by default)
        self.bubble = _TuxiaSpeechBubble(self)
        self.bubble.setVisible(False)
        self.bubble.cerrado.connect(self._on_cerrar)
        self.bubble.cuerpo_clk.connect(self._on_chat)
        self.bubble.accion_clk.connect(self._on_accion)

        # Tamaño inicial = solo el botón (el bubble se muestra encima
        # cuando llega un tip y el widget se redimensiona).
        self.setFixedSize(48, 48)
        self.btn_tux.setGeometry(0, 0, 48, 48)
        self.btn_tux.setVisible(True)

    def _set_btn_style(self, glow: bool = False):
        # El botón se pinta a mano (_TuxiaCircleButton.paintEvent); aquí solo
        # le pasamos el flag de glow para que cambie el color del borde.
        self.btn_tux.set_glow(glow)

    def _tick_pulse(self):
        self._pulse_step = (self._pulse_step + 1) % 6
        self._set_btn_style(glow=(self._pulse_step % 2 == 0))

    def _start_pulse(self):
        self._pulse_step = 0
        self._pulse_timer.start()

    def _stop_pulse(self):
        self._pulse_timer.stop()
        self._set_btn_style(glow=False)

    def _tick_ambient(self):
        """Tip ambient periódico — capacidad / motivador / tip técnico.

        Skip si:
          - El parent no existe.
          - Estamos fuera de la vista principal del proyecto.
          - El chat embebido está abierto.
          - Ya hay un bubble visible.
        Re-programa el siguiente fire con un intervalo aleatorio 10-15 min.
        """
        import random as _rnd
        p = self.parent()
        if p is None:
            return
        try:
            stack = getattr(p, '_root_stack', None)
            if stack is not None and stack.currentIndex() != 0:
                self._ambient_timer.setInterval(_rnd.randint(600_000, 900_000))
                return
            splitter = getattr(p, '_chat_splitter', None)
            if splitter is not None:
                sizes = splitter.sizes()
                if len(sizes) > 1 and sizes[1] > 100:
                    # Chat abierto → re-intentar luego, no molestar.
                    self._ambient_timer.setInterval(
                        _rnd.randint(600_000, 900_000))
                    return
            if self.bubble.isVisible():
                self._ambient_timer.setInterval(
                    _rnd.randint(600_000, 900_000))
                return
            # Pickea un tip que NO esté en las últimas 6 keys mostradas.
            from core.asistente_local import tip_ambient_aleatorio
            excluir = set(self._ambient_history[-6:])
            pick = tip_ambient_aleatorio(excluir_keys=excluir)
            if pick is None:
                self._ambient_timer.setInterval(
                    _rnd.randint(600_000, 900_000))
                return
            msg, key = pick
            self._ambient_history.append(key)
            # Mantén el history acotado.
            if len(self._ambient_history) > 20:
                self._ambient_history = self._ambient_history[-20:]
            # Decide el título según el tipo de tip.
            if key.startswith('cap_'):
                titulo = "tuxia · ¿sabías que…?"
            elif key.startswith('motiv_'):
                titulo = "tuxia · ánimo"
            else:
                titulo = "tuxia · tip del día"
            # Usamos once_per_session=False porque el filtrado ya lo hace
            # `_ambient_history`. fade más largo (18s) para dar tiempo de leer.
            self.show_tip(msg, titulo=titulo, fade_ms=18_000,
                          once_per_session=False)
        finally:
            # Siempre re-programa el próximo fire.
            self._ambient_timer.setInterval(_rnd.randint(600_000, 900_000))

    # ── API pública ───────────────────────────────────────────────────

    def show_tip(self, texto: str, *, accion_id: str | None = None,
                 accion_label: str | None = None,
                 titulo: str = "tuxia · tip",
                 fade_ms: int | None = None,
                 key: str | None = None,
                 once_per_session: bool = True):
        """Muestra el globo con un tip.

        - `accion_id`+`accion_label`: aparece botón 'Ir' que emite
          `accion_solicitada(accion_id)`.
        - `key`: identificador único del tip para anti-repetición. Si el
          usuario lo descartó permanentemente (clic en X), no se muestra.
        - `once_per_session`: si True, solo se muestra una vez por sesión
          aunque el trigger ocurra varias veces.
        """
        # No mostrar tips fuera de la vista principal del proyecto
        # (cronograma/pie/reportes tienen sus propios canales de ayuda).
        try:
            stack = getattr(self.parent(), '_root_stack', None)
            if stack is not None and stack.currentIndex() != 0:
                return
        except Exception:
            pass
        # Con el chat del asistente ABIERTO no interrumpir con globos
        # (motivación, tips, chequeos): solo cuando tuxia está minimizada
        # en el botón flotante. El usuario ya tiene el canal del chat.
        try:
            spl = getattr(self.parent(), '_chat_splitter', None)
            if spl is not None and spl.sizes()[1] > 0:
                return
        except Exception:
            pass
        # Filtro anti-repetición
        if key:
            # ¿Descartado permanentemente?
            if self._qs.value(f"dismiss/{key}", False, type=bool):
                return
            # ¿Ya mostrado en esta sesión?
            if once_per_session and key in self._tips_sesion:
                return
            self._tips_sesion.add(key)
        self._tip_key = key
        self._accion_id = accion_id
        # Bubble arriba + icono debajo, anclado a la esquina inferior derecha.
        p = self.parent()
        max_w_parent = (p.width() - 28) if p else 340
        max_w = max(220, min(340, max_w_parent))
        self.bubble.setMaximumWidth(max_w)
        self.bubble.set_tip(texto, accion_label, titulo)
        self.bubble.adjustSize()
        bw, bh = self.bubble.width(), self.bubble.height()
        gap = 6
        total_w = max(bw, 48)
        total_h = bh + gap + 48
        self.setFixedSize(total_w, total_h)
        # Alinear bubble e icono a la derecha del contenedor.
        self.bubble.move(total_w - bw, 0)
        self._set_btn_home(total_w - 48, bh + gap)
        self.btn_tux.setVisible(True)
        self.bubble.setVisible(True)
        super().setVisible(True)
        self._reposicionar()
        self._start_pulse()
        # Pop al hablar — el botón hace un pequeño "salto" cuando aparece un tip.
        self._animate_pop()
        self._fade_timer.start(fade_ms or self.BUBBLE_AUTO_FADE_MS)

    def _ocultar_bubble(self):
        self.bubble.setVisible(False)
        self._stop_pulse()
        # Vuelve al tamaño solo-botón; el icono flotante sigue visible
        # SOLO si estamos en la vista principal (idx 0 del root_stack) Y el
        # chat del asistente NO está abierto (el chat ES la versión expandida
        # del asistente — si el fade del globo cae después de abrir el chat,
        # no debe re-aparecer el icono).
        self.setFixedSize(48, 48)
        self._set_btn_home(0, 0)
        p = self.parent()
        en_main = True
        chat_abierto = False
        try:
            stack = getattr(p, '_root_stack', None)
            if stack is not None:
                en_main = (stack.currentIndex() == 0)
            spl = getattr(p, '_chat_splitter', None)
            chat_abierto = (spl is not None and spl.sizes()[1] > 0)
        except Exception:
            pass
        if en_main and not chat_abierto:
            self.btn_tux.setVisible(True)
            super().setVisible(True)
            self._reposicionar()
        else:
            super().setVisible(False)

    def _on_cerrar(self):
        self._fade_timer.stop()
        self._ocultar_bubble()

    def _on_chat(self):
        self._fade_timer.stop()
        self._ocultar_bubble()
        self.chat_solicitado.emit()

    def _on_accion(self):
        self._fade_timer.stop()
        self._ocultar_bubble()
        if self._accion_id:
            self.accion_solicitada.emit(self._accion_id)

    def reposicionar(self):
        """Anclar el widget a la esquina inferior-derecha del parent.
        NO toca la visibilidad — el caller decide cuándo mostrar/ocultar
        (p.ej. _on_root_stack_changed lo oculta en cronograma)."""
        self._reposicionar()

    def _reposicionar(self):
        """Posiciona el widget. Si el usuario lo arrastró, respeta esa
        posición (ajustando si se sale del parent). Si no, esquina
        inferior-derecha con margen."""
        p = self.parent()
        if not p:
            return
        if hasattr(self, '_user_pos') and self._user_pos is not None:
            x = max(0, min(self._user_pos.x(), p.width() - self.width()))
            y = max(0, min(self._user_pos.y(), p.height() - self.height()))
            self.move(x, y)
        else:
            margin_right = 14
            margin_bottom = 50
            x = p.width() - self.width() - margin_right
            y = p.height() - self.height() - margin_bottom
            self.move(max(8, x), max(8, y))
        self.raise_()
