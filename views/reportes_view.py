# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""Centro de Reportes — vista anclada con vista previa PDF + acciones de exportación.

Layout:
- Topbar: ← Volver | título | total proyecto
- Sidebar izquierdo (290px): tarjetas con los tipos de reporte
- Área central: QPdfView con la vista previa del PDF generado
- Barra inferior: Guardar PDF / Guardar Excel / Imprimir
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Qt, QSize, QThread, Signal, QPoint, QSettings, QTimer
from PySide6.QtCore import QPointF, QRectF, QMimeData
from PySide6.QtGui import QColor, QDrag, QFont, QIcon, QImage, QPainter, QPen, QPixmap
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPdfWidgets import QPdfView
from PySide6.QtPrintSupport import QPrinter, QPrintPreviewDialog
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QMessageBox, QProgressBar, QPushButton, QScrollArea, QSizePolicy,
    QSpacerItem, QStackedLayout, QToolButton, QVBoxLayout, QWidget,
)

from core import pdf_reports, word_reports, odt_reports, ods_reports
from utils.icons import icon

# Tipos soportados por cada exportador (PDF y Print aplican siempre).
_EXCEL_TIPOS = {'presupuesto', 'acus', 'insumos', 'metrados', 'gastos_generales',
                'completo', 'cronograma_valorizado', 'cronograma_adquisiciones'}
_WORD_TIPOS = word_reports.tipos_soportados()
_ODT_TIPOS = odt_reports.tipos_soportados()
_ODS_TIPOS = ods_reports.tipos_soportados() | {
    'cronograma_valorizado', 'cronograma_adquisiciones',
}
_MPP_TIPOS = {'cronograma'}

# Secciones del Reporte Completo (código, etiqueta corta de la casilla).
# Las 8 primeras son secciones del núcleo HTML (pdf_reports, A4 portrait);
# las 'cron_*' usan los renderizadores ricos de cronograma (papel auto).
# El orden de esta lista ES el orden del documento final.
_SECCIONES_COMPLETO = [
    ('memoria_descriptiva',  'Memoria'),
    ('resumen',              'Resumen'),
    ('presupuesto',          'Presupuesto'),
    ('gastos_generales',     'Pie'),
    ('insumos',              'Insumos'),
    ('acus',                 'ACU'),
    ('metrados',             'Metrados'),
    ('especificaciones',     'Especif.'),
    ('cron_gantt',           'Gantt'),
    ('cron_valorizado',      'Valorizado'),
    ('cron_adquisiciones',   'Adquisic.'),
    ('cron_curva',           'Curva S'),
]
_SECCIONES_NUCLEO = {c for c, _ in _SECCIONES_COMPLETO[:8]}

# Tarjeta del sidebar → sección del Reporte Completo. El orden de las
# tarjetas (arrastrables) define el orden de las secciones del Completo.
# 'completo' no mapea (es el agregado).
_CARD_A_SECCION = {
    'memoria_descriptiva':      'memoria_descriptiva',
    'resumen':                  'resumen',
    'presupuesto':              'presupuesto',
    'gastos_generales':         'gastos_generales',
    'insumos':                  'insumos',
    'acus':                     'acus',
    'metrados':                 'metrados',
    'especificaciones':         'especificaciones',
    'cronograma':               'cron_gantt',
    'cronograma_valorizado':    'cron_valorizado',
    'cronograma_adquisiciones': 'cron_adquisiciones',
    'cronograma_curva_s':       'cron_curva',
}

# ── Paleta ────────────────────────────────────────────────────────────────────
ORANGE      = "#F37329"
ORANGE_DARK = "#C0621A"
ORANGE_SOFT = "#FEF5EB"
SLATE_900   = "#1F2A38"
SLATE_700   = "#2E3C52"
SLATE_500   = "#485A6C"
SLATE_300   = "#94A3B8"
SLATE_100   = "#E2E8F0"
SILVER_50   = "#FAFBFC"
SILVER_100  = "#F8F9FA"
WHITE       = "#FFFFFF"


# ── Tarjeta de reporte ────────────────────────────────────────────────────────

class _ReportCard(QPushButton):
    """Tarjeta clickeable para seleccionar un tipo de reporte."""
    def __init__(self, codigo: str, titulo: str, descripcion: str, icono: str, parent=None):
        super().__init__(parent)
        self.codigo = codigo
        self.setObjectName("reportCard")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(82)
        self.setMaximumHeight(82)

        hl = QHBoxLayout(self)
        hl.setContentsMargins(14, 12, 14, 12)
        hl.setSpacing(12)

        # Ícono cuadrado a la izquierda — pixmap del SVG elementary
        ico = QLabel()
        ico.setFixedSize(40, 40)
        ico.setAlignment(Qt.AlignCenter)
        ico.setPixmap(icon(icono).pixmap(26, 26))
        ico.setStyleSheet(
            f"background:{ORANGE_SOFT}; border-radius:8px;"
        )
        self._ico = ico
        self._icono_nombre = icono
        hl.addWidget(ico)

        # Texto: título + descripción
        col = QVBoxLayout()
        col.setSpacing(2)
        col.setContentsMargins(0, 0, 0, 0)
        self._lbl_t = QLabel(titulo)
        self._lbl_t.setStyleSheet(f"color:{SLATE_900}; font-size:13px; font-weight:600;")
        self._lbl_d = QLabel(descripcion)
        self._lbl_d.setStyleSheet(f"color:{SLATE_500}; font-size:11px;")
        self._lbl_d.setWordWrap(True)
        col.addWidget(self._lbl_t)
        col.addWidget(self._lbl_d)
        hl.addLayout(col, stretch=1)

        self._press_pos: QPoint | None = None

        # Pista de descubrimiento: la tarjeta se puede arrastrar para
        # reordenar (y ese orden gobierna el Reporte Completo).
        from utils.tooltip import set_tooltip
        from utils.i18n import tr
        set_tooltip(self, tr("Clic para ver el reporte.") + "\n↕ "
                    + tr("Arrastra para cambiar el orden — también define "
                         "el orden de las secciones del Reporte Completo."))

        self._update_style(False)

    # ── Arrastre para reordenar (el orden define el del Reporte Completo) ──
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._press_pos = e.position().toPoint()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if (self._press_pos is not None
                and (e.buttons() & Qt.LeftButton)
                and ((e.position().toPoint() - self._press_pos).manhattanLength()
                     >= QApplication.startDragDistance())):
            self.setDown(False)
            md = QMimeData()
            md.setData(_CardsPanel.MIME, self.codigo.encode('utf-8'))
            drag = QDrag(self)
            drag.setMimeData(md)
            pm = self.grab()
            drag.setPixmap(pm)
            drag.setHotSpot(self._press_pos)
            self._press_pos = None
            drag.exec(Qt.MoveAction)
            return
        super().mouseMoveEvent(e)

    def _update_style(self, active: bool):
        # Reglas comunes: los QLabels internos deben llevar background
        # transparente y border:none — si no, Qt les pinta su rectángulo
        # blanco por defecto y se ve "sucio" cuando el card está naranja.
        labels_ss = (
            "QPushButton#reportCard QLabel {"
            " background:transparent; border:none; }"
        )
        if active:
            self.setStyleSheet(
                f"QPushButton#reportCard {{ background:{ORANGE_SOFT};"
                f"  border:2px solid {ORANGE}; border-radius:10px;"
                f"  padding:0px; text-align:left; }}"
                f"QPushButton#reportCard:hover {{ background:{ORANGE_SOFT}; }}"
                + labels_ss
            )
            self._ico.setStyleSheet(
                f"background:{ORANGE}; border-radius:8px;"
            )
        else:
            self.setStyleSheet(
                f"QPushButton#reportCard {{ background:{WHITE};"
                f"  border:1px solid {SLATE_100}; border-radius:10px;"
                f"  padding:0px; text-align:left; }}"
                f"QPushButton#reportCard:hover {{ background:{SILVER_100};"
                f"  border-color:{ORANGE}; }}"
                + labels_ss
            )
            self._ico.setStyleSheet(
                f"background:{ORANGE_SOFT}; border-radius:8px;"
            )

    def nextCheckState(self):
        # Solo permitir activar; desactivación la maneja el grupo
        if not self.isChecked():
            self.setChecked(True)

    def setChecked(self, checked: bool):
        super().setChecked(checked)
        self._update_style(checked)


# ── Worker thread para generar PDF sin bloquear UI ────────────────────────────

class _CardsPanel(QWidget):
    """Contenedor de las tarjetas del sidebar con reordenamiento por arrastre.
    Al soltar, reordena el layout y emite el nuevo orden de códigos."""

    MIME = 'application/x-ingeppto-reportcard'
    orden_cambiado = Signal(list)   # códigos en el nuevo orden visual

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._vl = QVBoxLayout(self)
        self._vl.setContentsMargins(12, 12, 12, 12)
        self._vl.setSpacing(8)
        self._drop_y: float | None = None   # y de la línea indicadora de drop

    def layout_cards(self) -> QVBoxLayout:
        return self._vl

    def _cards(self) -> list:
        out = []
        for i in range(self._vl.count()):
            w = self._vl.itemAt(i).widget()
            if isinstance(w, _ReportCard):
                out.append(w)
        return out

    def _target_index(self, y: float, cards: list) -> int:
        """Índice de inserción: primera tarjeta cuyo centro queda bajo el cursor."""
        for i, c in enumerate(cards):
            if y < c.y() + c.height() / 2:
                return i
        return len(cards)

    def _gap_y(self, target: int, cards: list) -> float:
        """Posición vertical del hueco `target` (donde se dibuja la línea)."""
        if target <= 0:
            return max(3.0, cards[0].y() - self._vl.spacing() / 2)
        if target >= len(cards):
            c = cards[-1]
            return c.y() + c.height() + self._vl.spacing() / 2
        arriba = cards[target - 1]
        return (arriba.y() + arriba.height() + cards[target].y()) / 2

    def _set_drop_y(self, val):
        if val != self._drop_y:
            self._drop_y = val
            self.update()

    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(self.MIME):
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if not e.mimeData().hasFormat(self.MIME):
            return
        e.acceptProposedAction()
        cards = self._cards()
        if not cards:
            return
        y = e.position().y()
        # Auto-scroll del QScrollArea cuando el cursor ronda los bordes
        viewport = self.parentWidget()
        sa = viewport.parentWidget() if viewport is not None else None
        if isinstance(sa, QScrollArea):
            y_vp = self.mapTo(viewport, e.position().toPoint()).y()
            sb = sa.verticalScrollBar()
            if y_vp < 50:
                sb.setValue(sb.value() - 14)
            elif y_vp > viewport.height() - 50:
                sb.setValue(sb.value() + 14)
        # Línea indicadora del punto de inserción. Si soltar ahí no cambia
        # nada (mismo lugar de la tarjeta arrastrada), no se muestra.
        codigo = bytes(e.mimeData().data(self.MIME)).decode('utf-8')
        target = self._target_index(y, cards)
        idx_src = next((i for i, c in enumerate(cards) if c.codigo == codigo), None)
        if idx_src is not None and target in (idx_src, idx_src + 1):
            self._set_drop_y(None)
        else:
            self._set_drop_y(self._gap_y(target, cards))

    def dragLeaveEvent(self, e):
        self._set_drop_y(None)

    def paintEvent(self, e):
        super().paintEvent(e)
        if self._drop_y is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        m = self._vl.contentsMargins()
        x1, x2 = m.left() + 2.0, self.width() - m.right() - 2.0
        pen = QPen(QColor(ORANGE), 3)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawLine(QPointF(x1 + 6, self._drop_y), QPointF(x2, self._drop_y))
        p.setBrush(QColor(ORANGE))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(x1 + 3, self._drop_y), 4.0, 4.0)
        p.end()

    def dropEvent(self, e):
        self._set_drop_y(None)
        if not e.mimeData().hasFormat(self.MIME):
            return
        codigo = bytes(e.mimeData().data(self.MIME)).decode('utf-8')
        cards = self._cards()
        src = next((c for c in cards if c.codigo == codigo), None)
        if src is None:
            return
        target = self._target_index(e.position().y(), cards)
        idx_src = cards.index(src)
        if idx_src < target:
            target -= 1
        cards.remove(src)
        cards.insert(min(target, len(cards)), src)
        # Reinsertar en el nuevo orden (el stretch final queda al fondo)
        for c in cards:
            self._vl.removeWidget(c)
        for i, c in enumerate(cards):
            self._vl.insertWidget(i, c)
        e.acceptProposedAction()
        self.orden_cambiado.emit([c.codigo for c in cards])


class _PdfWorker(QThread):
    finished_ok = Signal(str)        # path al PDF temporal
    failed      = Signal(str)        # mensaje de error

    def __init__(self, tipo: str, pid: int, parent=None):
        super().__init__(parent)
        self.tipo = tipo
        self.pid  = pid

    def run(self):
        try:
            tmp = tempfile.NamedTemporaryFile(
                prefix=f"reporte_{self.tipo}_", suffix='.pdf', delete=False
            )
            tmp.close()
            # Solo el reporte completo lleva carátula principal; los demás
            # van sin portada — ahorra páginas y tinta. En completo además
            # se insertan mini-portadas para separar las secciones.
            with_cover = (self.tipo == 'completo')
            pdf_reports.generar_pdf_archivo(self.tipo, self.pid, tmp.name,
                                              with_cover=with_cover)
            self.finished_ok.emit(tmp.name)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.failed.emit(f"{type(e).__name__}: {e}")


# ── Vista principal anclada ──────────────────────────────────────────────────

class ReportesView(QWidget):
    """Centro de Reportes anclado al stack del proyecto.
    Sidebar de tipos + vista previa PDF + acciones de exportación.
    """

    def __init__(self, proyecto_id: int, proyecto_nombre: str = '',
                 on_back: Optional[Callable[[], None]] = None, parent=None):
        super().__init__(parent)
        self.pid = proyecto_id
        self._proy_nombre = proyecto_nombre
        self._on_back = on_back
        self._tipo_actual: Optional[str] = None
        self._tmp_pdf: Optional[str] = None
        self._cards: dict[str, _ReportCard] = {}
        self._worker: Optional[_PdfWorker] = None
        self._mos_mode_on = False
        self._mosaico_cols = 2

        self.setStyleSheet(f"background:{SILVER_100};")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self._build_ui()
        # Auto-seleccionar primer reporte (Resumen Ejecutivo)
        if pdf_reports.REPORT_TYPES:
            self._on_card_clicked(pdf_reports.REPORT_TYPES[0][0])

    def cargar(self):
        """Hook llamado al activar la vista (para refrescar)."""
        if self._tipo_actual:
            self._regenerar_preview()

    # ─── UI builders ─────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_topbar())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        body.addWidget(self._build_sidebar())
        body.addWidget(self._build_preview_area(), stretch=1)

        body_w = QWidget()
        body_w.setLayout(body)
        root.addWidget(body_w, stretch=1)

        root.addWidget(self._build_actionbar())

    def _build_topbar(self) -> QWidget:
        bar = QFrame()
        bar.setFixedHeight(44)
        bar.setStyleSheet(f"background:{SLATE_700}; border:none;")
        hl = QHBoxLayout(bar)
        hl.setContentsMargins(10, 0, 10, 0)
        hl.setSpacing(10)

        # Botón Atrás
        from utils.i18n import tr
        btn_back = QPushButton(tr("Presupuesto"))
        btn_back.setIcon(icon("atras"))
        btn_back.setIconSize(QSize(18, 18))
        btn_back.setCursor(Qt.PointingHandCursor)
        btn_back.setStyleSheet(
            f"QPushButton {{ background:rgba(255,255,255,0.12); color:white;"
            f" border:1px solid rgba(255,255,255,0.25); border-radius:6px;"
            f" font-size:11px; padding:4px 12px; }}"
            f"QPushButton:hover {{ background:rgba(255,255,255,0.22); }}"
        )
        if self._on_back:
            btn_back.clicked.connect(self._on_back)
        hl.addWidget(btn_back)

        # Título central — sin nombre del proyecto al lado (es redundante,
        # ya aparece en la barra de título de la ventana).
        lbl_title = QLabel(tr("CENTRO DE REPORTES"))
        lbl_title.setStyleSheet(
            "color:white; font-size:13px; font-weight:700; letter-spacing:0.5px;"
        )
        lbl_title.setAlignment(Qt.AlignCenter)
        hl.addWidget(lbl_title, stretch=1)

        return bar

    def _build_sidebar(self) -> QWidget:
        side = QFrame()
        side.setFixedWidth(290)
        side.setStyleSheet(f"background:{WHITE}; border-right:1px solid {SLATE_100};")

        outer = QVBoxLayout(side)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        from utils.i18n import tr
        hdr = QLabel("  " + tr("Tipos de reporte"))
        hdr.setFixedHeight(38)
        hdr.setStyleSheet(
            f"color:{SLATE_500}; font-size:10px; font-weight:700;"
            f" letter-spacing:1px; padding-left:14px;"
            f" border-bottom:1px solid {SLATE_100}; background:{SILVER_50};"
        )
        outer.addWidget(hdr)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(f"background:{WHITE};")

        cont = _CardsPanel()
        cont.orden_cambiado.connect(self._on_orden_cards)
        vl = cont.layout_cards()

        iconos = {
            'memoria_descriptiva':      'rep-especificaciones',
            'resumen':                  'rep-resumen',
            'presupuesto':              'rep-presupuesto',
            'acus':                     'rep-acus',
            'metrados':                 'rep-metrados',
            'insumos':                  'rep-insumos',
            'especificaciones':         'rep-especificaciones',
            'gastos_generales':         'rep-presupuesto',
            'cronograma':               'rep-cronograma',
            'cronograma_valorizado':    'rep-valorizado',
            'cronograma_curva_s':       'rep-curva-s',
            'cronograma_adquisiciones': 'rep-adquisiciones',
            'presupuesto_cerrado':      'rep-presupuesto',
            'completo':                 'rep-completo',
        }
        # Orden de tarjetas: el guardado por el usuario (arrastre) primero;
        # los tipos no listados (nuevos) se agregan al final en orden default.
        qs = QSettings('ingePresupuestos', 'reportes')
        # Orden POR PROYECTO (sufijo pid): cada proyecto recuerda el suyo.
        guardado = (qs.value(f'orden_tarjetas_{self.pid}', '', type=str) or '').split(',')
        por_codigo = {t[0]: t for t in pdf_reports.REPORT_TYPES}
        orden = [c for c in guardado if c in por_codigo]
        orden += [c for c, _t, _d in pdf_reports.REPORT_TYPES if c not in orden]
        self._orden_cards = orden

        for codigo in orden:
            _c, titulo, descripcion = por_codigo[codigo]
            card = _ReportCard(codigo, titulo, descripcion, iconos.get(codigo, 'document'))
            card.clicked.connect(lambda _=False, c=codigo: self._on_card_clicked(c))
            self._cards[codigo] = card
            vl.addWidget(card)

        vl.addStretch(1)
        scroll.setWidget(cont)
        outer.addWidget(scroll, stretch=1)
        return side

    def _build_preview_area(self) -> QWidget:
        cont = QFrame()
        cont.setStyleSheet(f"background:{SILVER_100};")
        vl = QVBoxLayout(cont)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)

        # Sub-toolbar de vista previa
        sub = QFrame()
        sub.setFixedHeight(44)
        sub.setStyleSheet(f"background:{WHITE}; border-bottom:1px solid {SLATE_100};")
        sl = QHBoxLayout(sub)
        sl.setContentsMargins(14, 0, 14, 0)
        sl.setSpacing(8)

        from utils.i18n import tr
        self._lbl_titulo = QLabel(tr("Vista previa"))
        self._lbl_titulo.setStyleSheet(f"color:{SLATE_900}; font-size:13px; font-weight:600;")
        sl.addWidget(self._lbl_titulo)

        # Opciones específicas por tipo de reporte (visibles según contexto)
        from PySide6.QtWidgets import QComboBox, QCheckBox
        self._opts_frame = QFrame()
        self._opts_frame.setStyleSheet("background:transparent; border:none;")
        op_hl = QHBoxLayout(self._opts_frame)
        op_hl.setContentsMargins(16, 0, 0, 0); op_hl.setSpacing(6)
        # Período
        lbl_per = QLabel(tr("Período") + ":")
        lbl_per.setStyleSheet(f"color:{SLATE_500}; font-size:11px;")
        op_hl.addWidget(lbl_per)
        self._cmb_periodo = QComboBox()
        self._cmb_periodo.addItems(["Auto", tr("Semanal"), tr("Mensual")])
        self._cmb_periodo.setCurrentIndex(2)  # default Mensual (Marco)
        # Popup styling cubierto por `install_global_popup_styles(app)`.
        combo_qss = (
            "QComboBox { min-height:0; padding:2px 8px; font-size:11px;"
            f" border:1px solid {SLATE_100}; border-radius:4px;"
            f" background:white; color:{SLATE_700}; }}"
            f"QComboBox::drop-down {{ border:none; width:18px; }}"
        )
        self._cmb_periodo.setStyleSheet(combo_qss)
        self._cmb_periodo.currentIndexChanged.connect(
            lambda _i: self._regenerar_preview()
        )
        op_hl.addWidget(self._cmb_periodo)
        # Tamaño de papel
        lbl_pap = QLabel(tr("Papel") + ":")
        lbl_pap.setStyleSheet(f"color:{SLATE_500}; font-size:11px; padding-left:8px;")
        op_hl.addWidget(lbl_pap)
        self._cmb_papel = QComboBox()
        self._cmb_papel.addItems(["Auto", "A4", "A3", "A2", "A1", "A0"])
        self._cmb_papel.setCurrentIndex(1)   # A4 por defecto (Gantt usa su propio gran formato)
        self._cmb_papel.setStyleSheet(combo_qss)
        self._cmb_papel.currentIndexChanged.connect(
            lambda _i: self._regenerar_preview()
        )
        op_hl.addWidget(self._cmb_papel)
        # Toggle "Una sola hoja"
        self._chk_unahoja = QCheckBox(tr("Una sola hoja"))
        self._chk_unahoja.setChecked(True)
        self._chk_unahoja.setStyleSheet(
            f"QCheckBox {{ color:{SLATE_500}; font-size:11px; padding:0 8px; }}"
        )
        self._chk_unahoja.toggled.connect(lambda _o: self._regenerar_preview())
        op_hl.addWidget(self._chk_unahoja)
        self._opts_frame.setVisible(False)
        sl.addWidget(self._opts_frame)

        sl.addStretch(1)

        # Zoom
        self._btn_zoom_out = self._mk_subtbtn("−", "Reducir zoom")
        self._btn_zoom_out.clicked.connect(lambda: self._cambiar_zoom(-0.1))
        sl.addWidget(self._btn_zoom_out)
        self._lbl_zoom = QLabel("100%")
        self._lbl_zoom.setFixedWidth(46)
        self._lbl_zoom.setAlignment(Qt.AlignCenter)
        self._lbl_zoom.setStyleSheet(f"color:{SLATE_500}; font-size:11px;")
        sl.addWidget(self._lbl_zoom)
        self._btn_zoom_in = self._mk_subtbtn("+", "Aumentar zoom")
        self._btn_zoom_in.clicked.connect(lambda: self._cambiar_zoom(+0.1))
        sl.addWidget(self._btn_zoom_in)
        self._btn_fit = self._mk_subtbtn("", "Ajustar al ancho")
        self._btn_fit.setIcon(icon("ajustar"))
        self._btn_fit.setIconSize(QSize(18, 18))
        self._btn_fit.clicked.connect(self._fit_width)
        sl.addWidget(self._btn_fit)

        # Separador visual
        sep = QFrame()
        sep.setFixedSize(1, 20)
        sep.setStyleSheet(f"background:{SLATE_100};")
        sl.addWidget(sep)

        # Vista — combo único que reemplaza los toggles Página/Mosaico y el
        # selector de cols (Marco: "el botón está de más, solo el desplegable").
        # "📄 Página" = vista de página; "▦ N cols" = mosaico con N columnas.
        self._cmb_vista = QComboBox()
        self._cmb_vista.addItem("📄  Página", userData=('pagina', None))
        for n in (1, 2, 3, 4, 5, 6):
            etiqueta = f"▦  {n} col" if n == 1 else f"▦  {n} cols"
            self._cmb_vista.addItem(etiqueta, userData=('mosaico', n))
        self._cmb_vista.setCurrentIndex(0)
        self._mosaico_cols = 2
        # Popup styling cubierto por `install_global_popup_styles(app)`.
        self._cmb_vista.setStyleSheet(
            f"QComboBox {{ background:white; color:{SLATE_700};"
            f" border:1px solid {SLATE_100}; border-radius:4px;"
            f" font-size:11px; padding:2px 8px; min-height:24px;"
            f" min-width:96px; }}"
            f"QComboBox::drop-down {{ border:none; width:16px; }}"
        )
        self._cmb_vista.currentIndexChanged.connect(self._on_vista_cambiada)
        from utils.tooltip import set_tooltip
        set_tooltip(self._cmb_vista, "Modo de vista del PDF")
        sl.addWidget(self._cmb_vista)

        vl.addWidget(sub)

        # Fila «Secciones» — casillas para elegir qué incluye el Reporte
        # Completo (solo visible con ese reporte activo). La numeración de
        # secciones y páginas se recalcula sobre lo seleccionado.
        self._sec_frame = QFrame()
        self._sec_frame.setStyleSheet(
            f"background:{WHITE}; border-bottom:1px solid {SLATE_100};")
        sec_hl = QHBoxLayout(self._sec_frame)
        sec_hl.setContentsMargins(14, 4, 14, 6)
        sec_hl.setSpacing(10)
        lbl_sec = QLabel(tr("Secciones") + ":")
        lbl_sec.setStyleSheet(
            f"color:{SLATE_500}; font-size:11px; font-weight:600;")
        sec_hl.addWidget(lbl_sec)
        self._chk_sec: dict[str, QCheckBox] = {}
        _qs_sec = QSettings('ingePresupuestos', 'reportes')
        # Selección POR PROYECTO (sufijo pid)
        _guardadas = _qs_sec.value(f'completo_secciones_{self.pid}', '', type=str) or ''
        _marcadas = set(_guardadas.split(',')) if _guardadas else None  # None=todas
        # Debounce: regenerar el Completo es caro; esperar a que el usuario
        # termine de marcar/desmarcar antes de regenerar la vista previa.
        self._sec_timer = QTimer(self)
        self._sec_timer.setSingleShot(True)
        self._sec_timer.setInterval(700)
        self._sec_timer.timeout.connect(self._on_secciones_cambiadas)
        self._sec_hl = sec_hl
        _etiqueta_sec = dict(_SECCIONES_COMPLETO)
        for cod_s in self._orden_secciones():
            chk = QCheckBox(_etiqueta_sec.get(cod_s, cod_s))
            chk.setChecked(_marcadas is None or cod_s in _marcadas)
            chk.setStyleSheet(
                f"QCheckBox {{ color:{SLATE_700}; font-size:11px; }}")
            chk.toggled.connect(lambda _o: self._sec_timer.start())
            self._chk_sec[cod_s] = chk
            sec_hl.addWidget(chk)
        sec_hl.addStretch(1)
        # Toggle «Sin separadores»: omite las páginas divisoras «— SECCIÓN n —»
        # entre secciones (presupuesto rápido, ahorra papel). El encabezado de
        # página ya identifica cada sección, así que siguen distinguibles.
        _sin_sep = _qs_sec.value(
            f'completo_sin_separadores_{self.pid}', False, type=bool)
        self._chk_sin_sep = QCheckBox(tr("Sin separadores"))
        self._chk_sin_sep.setChecked(bool(_sin_sep))
        self._chk_sin_sep.setStyleSheet(
            f"QCheckBox {{ color:{SLATE_500}; font-size:11px; font-weight:600; }}")
        set_tooltip(self._chk_sin_sep, tr(
            "Imprime el Reporte Completo sin las páginas divisoras «— SECCIÓN n —» "
            "entre secciones. Cada sección se identifica igual por el encabezado."))
        self._chk_sin_sep.toggled.connect(self._on_sin_sep_cambiado)
        sec_hl.addWidget(self._chk_sin_sep)
        self._sec_frame.setVisible(False)
        vl.addWidget(self._sec_frame)

        # Stack: vista previa PDF | mensaje "generando..."
        self._preview_stack = QStackedLayout()
        self._preview_stack.setContentsMargins(0, 0, 0, 0)

        # PDF view
        self._pdf_doc  = QPdfDocument(self)
        self._pdf_view = QPdfView(self)
        self._pdf_view.setDocument(self._pdf_doc)
        self._pdf_view.setPageMode(QPdfView.PageMode.MultiPage)
        self._pdf_view.setZoomMode(QPdfView.ZoomMode.Custom)
        self._pdf_view.setZoomFactor(1.0)
        self._pdf_view.setStyleSheet(f"background:{SILVER_100}; border:none;")
        # Ctrl+wheel = zoom in/out — instalamos eventFilter en el viewport
        # (los wheel events vienen ahí, no en el QPdfView mismo).
        self._pdf_view.viewport().installEventFilter(self)

        self._lbl_state = QLabel(tr("Selecciona un reporte"))
        self._lbl_state.setAlignment(Qt.AlignCenter)
        self._lbl_state.setStyleSheet(
            f"color:{SLATE_300}; background:{SILVER_100};"
            " font-size:13px; font-style:italic;"
        )

        self._pdf_view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        w_pdf = QWidget(); l_pdf = QVBoxLayout(w_pdf)
        l_pdf.setContentsMargins(0, 0, 0, 0); l_pdf.addWidget(self._pdf_view)
        w_pdf.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # Barra de progreso para reportes que se generan en el hilo principal
        # (Completo, cronogramas): le da feedback al usuario y evita que crea
        # que la app se colgó. Oculta salvo durante la generación.
        self._progress = QProgressBar()
        self._progress.setVisible(False)
        self._progress.setFixedWidth(260)
        self._progress.setFixedHeight(8)
        self._progress.setTextVisible(False)
        self._progress.setStyleSheet(
            f"QProgressBar {{ background:{SILVER_100}; border:1px solid {SLATE_300};"
            f" border-radius:4px; }}"
            f"QProgressBar::chunk {{ background:{ORANGE}; border-radius:3px; }}"
        )

        w_lbl = QWidget(); l_lbl = QVBoxLayout(w_lbl)
        l_lbl.setContentsMargins(0, 0, 0, 0)
        l_lbl.addStretch(1)
        l_lbl.addWidget(self._lbl_state)
        l_lbl.addSpacing(12)
        l_lbl.addWidget(self._progress, 0, Qt.AlignHCenter)
        l_lbl.addStretch(1)
        w_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # Vista mosaico: scroll area + grid de thumbnails
        self._mos_scroll = QScrollArea()
        self._mos_scroll.setWidgetResizable(True)
        self._mos_scroll.setStyleSheet(f"QScrollArea {{ background:{SILVER_100}; border:none; }}")
        self._mos_container = QWidget()
        self._mos_container.setStyleSheet(f"background:{SILVER_100};")
        self._mos_grid = QGridLayout(self._mos_container)
        self._mos_grid.setContentsMargins(16, 16, 16, 16)
        self._mos_grid.setSpacing(14)
        self._mos_scroll.setWidget(self._mos_container)

        self._preview_stack.addWidget(w_lbl)              # 0 = mensaje
        self._preview_stack.addWidget(w_pdf)              # 1 = pdf
        self._preview_stack.addWidget(self._mos_scroll)   # 2 = mosaico

        wrap = QWidget(); wrap.setLayout(self._preview_stack)
        wrap.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        vl.addWidget(wrap, stretch=1)
        cont.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        return cont

    def _mk_subtbtn(self, text: str, tooltip: str = '') -> QToolButton:
        b = QToolButton()
        b.setText(text)
        b.setToolTip(tooltip)
        b.setCursor(Qt.PointingHandCursor)
        b.setFixedSize(30, 28)
        b.setStyleSheet(
            f"QToolButton {{ background:{WHITE}; border:1px solid {SLATE_100};"
            f"  border-radius:6px; color:{SLATE_700}; font-size:14px; }}"
            f"QToolButton:hover {{ background:{ORANGE_SOFT}; border-color:{ORANGE};"
            f"  color:{ORANGE_DARK}; }}"
        )
        return b

    def _build_actionbar(self) -> QWidget:
        bar = QFrame()
        bar.setFixedHeight(60)
        bar.setStyleSheet(f"background:{WHITE}; border-top:1px solid {SLATE_100};")
        hl = QHBoxLayout(bar)
        hl.setContentsMargins(18, 8, 18, 8)
        hl.setSpacing(10)

        # Botón "Configurar formato…" — abre diálogo para editar logo, color, encabezados
        from utils.i18n import tr
        btn_fmt = QPushButton(tr("Configurar formato") + "…")
        btn_fmt.setIcon(icon("palette"))
        btn_fmt.setIconSize(QSize(18, 18))
        btn_fmt.setCursor(Qt.PointingHandCursor)
        btn_fmt.setFixedHeight(38)
        btn_fmt.setStyleSheet(
            f"QPushButton {{ background:{WHITE}; color:{SLATE_700};"
            f"  border:1px solid {SLATE_100}; border-radius:8px;"
            f"  font-weight:500; font-size:12px; padding:0 14px; }}"
            f"QPushButton:hover {{ background:{ORANGE_SOFT}; border-color:{ORANGE};"
            f"  color:{ORANGE_DARK}; }}"
        )
        btn_fmt.clicked.connect(self._abrir_editor_formato)
        hl.addWidget(btn_fmt)

        hl.addStretch(1)

        def mk(text: str, primary: bool, handler):
            b = QPushButton(text)
            b.setCursor(Qt.PointingHandCursor)
            b.setFixedHeight(38)
            b.setMinimumWidth(140)
            if primary:
                from utils.theme import BTN_PRIMARY_SS
                b.setStyleSheet(BTN_PRIMARY_SS)
            else:
                b.setStyleSheet(
                    f"QPushButton {{ background:{WHITE}; color:{SLATE_700};"
                    f"  border:1px solid {SLATE_100}; border-radius:8px;"
                    f"  font-weight:500; font-size:12px; padding:0 14px; }}"
                    f"QPushButton:hover {{ background:{SILVER_100}; border-color:{ORANGE};"
                    f"  color:{ORANGE_DARK}; }}"
                )
            b.clicked.connect(handler)
            return b

        self._btn_xlsx = mk("Excel", False, self._guardar_excel)
        hl.addWidget(self._btn_xlsx)
        self._btn_ods = mk("ODS", False, self._guardar_ods)
        hl.addWidget(self._btn_ods)
        self._btn_word = mk("Word", False, self._guardar_word)
        hl.addWidget(self._btn_word)
        self._btn_odt = mk("ODT", False, self._guardar_odt)
        hl.addWidget(self._btn_odt)
        self._btn_mpp = mk("MPP", False, self._guardar_mpp)
        self._btn_mpp.setToolTip(
            "Exportar a Microsoft Project (XML). Incluye plazo, calendario "
            "peruano, dependencias y colores."
        )
        hl.addWidget(self._btn_mpp)
        self._btn_png = mk("PNG", False, self._guardar_png)
        self._btn_png.setToolTip(
            "Exportar la vista previa como imagen PNG (fondo blanco, sin "
            "transparencias). Si el reporte tiene varias páginas se guarda "
            "una PNG por página."
        )
        hl.addWidget(self._btn_png)
        # Packs (solo visibles en Reporte Completo)
        self._btn_pack_office = mk("📦 Pack Office", False, self._guardar_pack_office)
        self._btn_pack_office.setToolTip(
            "Descarga TODOS los archivos editables Office en una sola carpeta:\n"
            "Word (.docx) + Excel (.xlsx) + MPP (.xml)"
        )
        hl.addWidget(self._btn_pack_office)
        self._btn_pack_libre = mk("📦 Pack LibreOffice", False,
                                     self._guardar_pack_libre)
        self._btn_pack_libre.setToolTip(
            "Descarga TODOS los archivos editables ODF en una sola carpeta:\n"
            "ODT (.odt) + ODS (.ods). Requiere LibreOffice instalado."
        )
        hl.addWidget(self._btn_pack_libre)
        self._btn_print = mk(tr("Imprimir") + "…", False, self._imprimir)
        hl.addWidget(self._btn_print)
        self._btn_pdf = mk(tr("Guardar") + " PDF", True, self._guardar_pdf)
        hl.addWidget(self._btn_pdf)

        return bar

    # ─── Editor de formato ───────────────────────────────────────────────────

    def _abrir_editor_formato(self):
        from views.formato_reporte_dialog import FormatoReporteDialog
        dlg = FormatoReporteDialog(self)
        if dlg.exec() == FormatoReporteDialog.Accepted:
            # Regenerar la vista previa con el nuevo formato
            self._regenerar_preview()

    # ─── Lógica ──────────────────────────────────────────────────────────────

    def _on_card_clicked(self, codigo: str):
        for c, card in self._cards.items():
            card.setChecked(c == codigo)
        self._tipo_actual = codigo
        titulo = next((t[1] for t in pdf_reports.REPORT_TYPES if t[0] == codigo), codigo)
        self._lbl_titulo.setText(titulo)
        self._regenerar_preview()
        self._actualizar_visibilidad_export(codigo)

    def _odf_export_oculto(self) -> bool:
        """True si hay que OCULTAR los botones ODS/ODT/Pack-LibreOffice: solo en
        la edición Flathub (Flatpak sin LibreOffice del host). Ver
        core.soffice.odf_export_ofrecible()."""
        from core.soffice import odf_export_ofrecible
        return not odf_export_ofrecible()

    def _actualizar_visibilidad_export(self, codigo: str):
        """Muestra/oculta Excel/ODS/Word/ODT/MPP según si el tipo soporta el formato.
        Para 'completo' solo se permite Guardar PDF + Imprimir."""
        es_completo = (codigo == 'completo')
        odf_oculto  = self._odf_export_oculto()   # Flathub sin LibreOffice del host
        # Word / ODT — además de los tipos del módulo, agregar curva_s
        word_ok = ((codigo in _WORD_TIPOS) or (codigo == 'cronograma_curva_s'))
        odt_ok  = ((codigo in _ODT_TIPOS)  or (codigo == 'cronograma_curva_s'))
        self._btn_xlsx.setVisible((codigo in _EXCEL_TIPOS) and not es_completo)
        self._btn_ods.setVisible((codigo in _ODS_TIPOS) and not es_completo and not odf_oculto)
        self._btn_word.setVisible(word_ok and not es_completo)
        self._btn_odt.setVisible(odt_ok and not es_completo and not odf_oculto)
        self._btn_mpp.setVisible((codigo in _MPP_TIPOS) and not es_completo)
        # PNG aplica a todos los reportes excepto el Completo.
        self._btn_png.setVisible(not es_completo)
        # Packs solo en Reporte Completo
        self._btn_pack_office.setVisible(es_completo)
        self._btn_pack_libre.setVisible(es_completo and not odf_oculto)
        # Fila de casillas de secciones solo en Reporte Completo
        if hasattr(self, '_sec_frame'):
            self._sec_frame.setVisible(es_completo)
        # Opciones contextuales (combo Período / Papel / Una sola hoja):
        if hasattr(self, '_opts_frame'):
            en_cron_tabular = codigo in ('cronograma_valorizado',
                                            'cronograma_adquisiciones')
            en_cron_curva = (codigo == 'cronograma_curva_s')
            self._opts_frame.setVisible(
                en_cron_tabular or en_cron_curva or es_completo
            )
            try:
                # Período aplica para cronogramas individuales y para completo
                self._cmb_periodo.setVisible(
                    en_cron_tabular or en_cron_curva or es_completo
                )
                for child in self._opts_frame.findChildren(QLabel):
                    if child.text() == "Período:":
                        child.setVisible(
                            en_cron_tabular or en_cron_curva or es_completo
                        )
                # Papel y "Una sola hoja" no aplican en completo (cada
                # sección se auto-ajusta).
                self._cmb_papel.setVisible(en_cron_tabular or en_cron_curva)
                for child in self._opts_frame.findChildren(QLabel):
                    if child.text() == "Papel:":
                        child.setVisible(en_cron_tabular or en_cron_curva)
                self._chk_unahoja.setVisible(en_cron_tabular)
            except Exception:
                pass

    def _orden_secciones(self) -> list[str]:
        """Códigos de sección del Completo en el ORDEN DE LAS TARJETAS del
        sidebar (reordenables por arrastre). Secciones sin tarjeta mapeada
        caen al final en el orden del catálogo."""
        orden = [_CARD_A_SECCION[c] for c in getattr(self, '_orden_cards', [])
                 if c in _CARD_A_SECCION]
        orden += [c for c, _ in _SECCIONES_COMPLETO if c not in orden]
        return orden

    def _on_orden_cards(self, codes: list):
        """Tras arrastrar una tarjeta: persistir orden, reordenar las casillas
        del Completo y regenerar la vista previa si el Completo está activo."""
        qs = QSettings('ingePresupuestos', 'reportes')
        qs.setValue(f'orden_tarjetas_{self.pid}', ','.join(codes))
        self._orden_cards = list(codes)
        if hasattr(self, '_sec_hl'):
            for i, sec in enumerate(self._orden_secciones(), start=1):
                chk = self._chk_sec.get(sec)
                if chk is not None:
                    self._sec_hl.removeWidget(chk)
                    self._sec_hl.insertWidget(i, chk)
        if getattr(self, '_tipo_actual', None) == 'completo':
            self._sec_timer.start()

    def _secciones_completo_sel(self) -> list[str]:
        """Códigos de sección marcados, en el orden elegido por el usuario."""
        return [c for c in self._orden_secciones()
                if self._chk_sec[c].isChecked()]

    def _on_secciones_cambiadas(self):
        """Persiste la selección y regenera la vista previa del Completo."""
        qs = QSettings('ingePresupuestos', 'reportes')
        qs.setValue(f'completo_secciones_{self.pid}',
                    ','.join(self._secciones_completo_sel()))
        if self._tipo_actual == 'completo':
            self._regenerar_preview()

    def _sin_separadores(self) -> bool:
        """True si el usuario pidió el Completo sin páginas divisoras."""
        chk = getattr(self, '_chk_sin_sep', None)
        return bool(chk is not None and chk.isChecked())

    def _on_sin_sep_cambiado(self, _checked: bool):
        """Persiste el toggle «Sin separadores» y regenera la vista previa."""
        qs = QSettings('ingePresupuestos', 'reportes')
        qs.setValue(f'completo_sin_separadores_{self.pid}',
                    self._sin_separadores())
        if getattr(self, '_tipo_actual', None) == 'completo':
            self._sec_timer.start()

    def _set_busy_cursor(self, on: bool):
        """Cursor de espera balanceado (evita push/pop desbalanceado)."""
        if on and not getattr(self, '_cursor_busy', False):
            QApplication.setOverrideCursor(Qt.WaitCursor)
            self._cursor_busy = True
        elif not on and getattr(self, '_cursor_busy', False):
            QApplication.restoreOverrideCursor()
            self._cursor_busy = False

    def _progreso(self, frac, mensaje=None):
        """Callback de progreso para reportes síncronos (Completo/cronogramas).
        `frac` 0..1 (o None = indeterminado). Repinta YA con processEvents."""
        if mensaje is not None:
            self._lbl_state.setText(mensaje)
        if frac is None:
            self._progress.setRange(0, 0)        # indeterminado (rebote)
        else:
            self._progress.setRange(0, 100)
            self._progress.setValue(max(0, min(100, int(frac * 100))))
        QApplication.processEvents()

    def _regenerar_preview(self):
        if not self._tipo_actual:
            return
        # Guard de reentrada: el progreso usa processEvents() y el usuario
        # podría clicar otro reporte mientras se genera → ignorarlo.
        if getattr(self, '_generando', False):
            return
        self._generando = True
        from utils.i18n import tr as _tr_rep
        self._lbl_state.setText(_tr_rep("Generando vista previa") + "…")
        self._progress.setRange(0, 0)            # indeterminado por defecto
        self._progress.setVisible(True)
        self._preview_stack.setCurrentIndex(0)
        for b in (self._btn_pdf, self._btn_print):
            b.setEnabled(False)
        # Cursor de espera + repintar la página de carga ANTES del trabajo
        # pesado (los reportes síncronos bloquean el hilo principal y, sin
        # esto, el usuario no veía nada y creía que la app se colgó).
        self._set_busy_cursor(True)
        QApplication.processEvents()

        if self._worker and self._worker.isRunning():
            self._worker.quit()
            self._worker.wait(500)

        # Cronograma — usa el renderizador rico (CronogramaView), no el HTML.
        # Se ejecuta en main thread porque construye QGraphicsScenes.
        if self._tipo_actual == 'cronograma':
            try:
                path = self._render_gantt_rich_pdf()
                if path:
                    self._on_pdf_listo(path)
                else:
                    self._on_pdf_falla("No se pudo cargar el proyecto.")
            except Exception as e:
                import traceback; traceback.print_exc()
                self._on_pdf_falla(f"{type(e).__name__}: {e}")
            return

        # Cronograma valorizado / adquisiciones — forzar una sola hoja y auto-papel.
        if self._tipo_actual in ('cronograma_valorizado', 'cronograma_adquisiciones'):
            try:
                path = self._render_cronograma_tabular_pdf(self._tipo_actual)
                if path:
                    self._on_pdf_listo(path)
                else:
                    self._on_pdf_falla("No se pudo cargar el proyecto.")
            except Exception as e:
                import traceback; traceback.print_exc()
                self._on_pdf_falla(f"{type(e).__name__}: {e}")
            return

        # Curva S — render rico (gráfico + KPIs + tabla) en una sola hoja.
        if self._tipo_actual == 'cronograma_curva_s':
            try:
                path = self._render_curva_s_rich_pdf()
                if path:
                    self._on_pdf_listo(path)
                else:
                    self._on_pdf_falla("No se pudo cargar el proyecto.")
            except Exception as e:
                import traceback; traceback.print_exc()
                self._on_pdf_falla(f"{type(e).__name__}: {e}")
            return

        # Reporte Completo — merge de PDFs (núcleo HTML + cronogramas ricos).
        if self._tipo_actual == 'completo':
            try:
                path = self._render_completo_merged_pdf(progress=self._progreso)
                if path:
                    self._on_pdf_listo(path)
                else:
                    self._on_pdf_falla("No se pudo generar el reporte.")
            except Exception as e:
                import traceback; traceback.print_exc()
                self._on_pdf_falla(f"{type(e).__name__}: {e}")
            return

        self._worker = _PdfWorker(self._tipo_actual, self.pid, parent=self)
        self._worker.finished_ok.connect(self._on_pdf_listo)
        self._worker.failed.connect(self._on_pdf_falla)
        self._worker.start()

    def _render_gantt_rich_pdf(self) -> Optional[str]:
        """Renderiza el Gantt usando el pipeline rico de CronogramaView
        (con barras gráficas redondeadas, flechas tipadas, hitos coloreados,
        línea HOY, sombreado de feriados, etc.) en lugar del HTML básico.

        Auto-selecciona tamaño de papel según volumen del proyecto y fuerza
        modo 'fit' (todo en una sola hoja apaisada). Retorna la ruta al PDF
        temporal o None si no hay datos."""
        try:
            self._ensure_cron_helper()
        except Exception:
            return None

        partidas = getattr(self._cron_helper, '_partidas', []) or []
        tasks    = getattr(self._cron_helper, '_tasks', {}) or {}
        if not partidas:
            return None
        n_partidas = sum(1 for p in partidas if not p.get('es_titulo'))
        n_dias = max((t.get('EF', 0) for t in tasks.values()), default=0)
        plazo  = self._cron_helper._proy.get('plazo') or 0
        n_dias = max(n_dias, plazo, 30)

        # Auto-selección de papel — buscar que todo entre cómodo en una hoja
        if n_partidas <= 25 and n_dias <= 60:
            papel = 'A4'
        elif n_partidas <= 60 and n_dias <= 180:
            papel = 'A3'
        elif n_partidas <= 120 and n_dias <= 360:
            papel = 'A2'
        else:
            papel = 'A1'

        tmp = tempfile.NamedTemporaryFile(
            prefix="reporte_gantt_", suffix='.pdf', delete=False
        )
        tmp.close()
        gantt = self._cron_helper._gantt_w
        gantt._render_pdf_completo(
            tmp.name,
            modo='fit', orient='landscape',
            incluir_pred=False, escala='auto',
            hojas_x=0, papel=papel,
            incluir_header=True, incluir_footer=True,
            incluir_legend=True, incluir_page=True,
        )
        return tmp.name

    def _render_cronograma_tabular_pdf(self, tipo: str) -> Optional[str]:
        """Genera Cronograma Valorizado o Adquisición de Insumos en una sola
        hoja apaisada con papel auto-seleccionado. Usa el renderizador HTML
        con `periodos_por_pagina=-1` para comprimir todo en una hoja."""
        from core import pdf_reports as _pr
        from core.database import get_db, calcular_totales
        from core.cronograma import get_cronograma_map

        conn = get_db()
        row = conn.execute("SELECT * FROM proyectos WHERE id=?",
                              (self.pid,)).fetchone()
        if not row:
            conn.close()
            return None
        proy = dict(row)
        items, _ = calcular_totales(self.pid)
        cron_map = get_cronograma_map(conn, self.pid)
        conn.close()

        plazo = int(proy.get('plazo') or 30)
        max_end = 0
        for cd in cron_map.values():
            end = (cd.get('inicio_dia') or 1) + (cd.get('duracion') or 0) - 1
            max_end = max(max_end, end)
        n_partidas = sum(1 for entry in items
                          if not entry['partida'].get('es_titulo'))

        # Selección de escala — combo del usuario manda (Auto/Semanal/Mensual).
        n_dias = max(max_end, plazo, 7)
        sel_per = (self._cmb_periodo.currentIndex()
                    if hasattr(self, '_cmb_periodo') else 0)
        if sel_per == 1:        # Semanal
            escala, period_days = 'semana', 7
        elif sel_per == 2:      # Mensual
            escala, period_days = 'mes', 30
        else:                    # Auto
            # Default Mensual (Marco preferencia general). Para plazos muy
            # cortos (≤ 60 días, ~2 meses) cae a Semanal porque mostrar 1-2
            # columnas de mes pierde detalle.
            escala, period_days = 'mes', 30
            if n_dias <= 60:
                escala, period_days = 'semana', 7
        n_periods = max(1, (n_dias + period_days - 1) // period_days)

        # Toggle: una sola hoja vs multipágina
        una_hoja = (self._chk_unahoja.isChecked()
                     if hasattr(self, '_chk_unahoja') else True)

        # Papel: combo del usuario manda; Auto = elegir según volumen.
        sel_pap = (self._cmb_papel.currentIndex()
                    if hasattr(self, '_cmb_papel') else 0)
        if sel_pap == 0:
            # Auto — papel más generoso para mejor legibilidad
            if n_periods <= 10 and n_partidas <= 25:
                papel = 'A4'
            elif n_periods <= 20 and n_partidas <= 50:
                papel = 'A3'
            elif n_periods <= 36 and n_partidas <= 100:
                papel = 'A2'
            elif n_periods <= 60 and n_partidas <= 180:
                papel = 'A1'
            else:
                papel = 'A0'
        else:
            papel = ["A4", "A3", "A2", "A1", "A0"][sel_pap - 1]

        # Configurar el helper compartido y generar
        _pr._BUILD_HTML_PAPER['paper'] = papel
        _pr._BUILD_HTML_PAPER['orient'] = 'landscape'
        _pr._BUILD_HTML_PAPER['escala'] = escala
        _pr._BUILD_HTML_PAPER['periodos_por_pagina'] = (-1 if una_hoja else 0)
        _pr._BUILD_HTML_PAPER['show_fechas'] = False

        prefix = ('reporte_valorizado_' if tipo == 'cronograma_valorizado'
                   else 'reporte_adquisiciones_')
        tmp = tempfile.NamedTemporaryFile(
            prefix=prefix, suffix='.pdf', delete=False
        )
        tmp.close()
        _pr.generar_pdf_archivo(
            tipo, self.pid, tmp.name,
            with_cover=False, paper=papel, orient='landscape',
        )
        return tmp.name

    def _render_curva_s_rich_pdf(self) -> Optional[str]:
        """Genera la Curva S usando el renderizador pulido del CurvaSWidget
        (header + KPIs + gráfico embebido + tabla). Papel auto-seleccionado;
        el usuario puede sobreescribirlo desde el combo Papel."""
        try:
            self._ensure_cron_helper()
        except Exception:
            return None
        curva = getattr(self._cron_helper, '_curva_w', None)
        if curva is None:
            return None
        self._aplicar_periodo_curva(curva)
        # Forzar recarga para tener _last_data fresco con el período aplicado.
        curva.cargar()
        data = getattr(curva, '_last_data', None)
        if not data or data.get('total_general', 0) <= 0:
            return None
        n_periods = data.get('n_periods', 0)

        # Papel: combo del usuario o auto.
        sel_pap = (self._cmb_papel.currentIndex()
                    if hasattr(self, '_cmb_papel') else 0)
        if sel_pap == 0:
            # Auto — Curva S tiene chart + tabla; el ancho de tabla depende
            # del número de períodos.
            if n_periods <= 16:
                papel = 'A4'
            elif n_periods <= 30:
                papel = 'A3'
            elif n_periods <= 60:
                papel = 'A2'
            else:
                papel = 'A1'
        else:
            papel = ["A4", "A3", "A2", "A1", "A0"][sel_pap - 1]

        tmp = tempfile.NamedTemporaryFile(
            prefix="reporte_curva_s_", suffix='.pdf', delete=False
        )
        tmp.close()
        curva._render_pdf(tmp.name, paper=papel, orient='portrait')
        return tmp.name

    def _on_pdf_listo(self, path: str):
        self._generando = False
        self._progress.setVisible(False)
        self._set_busy_cursor(False)
        # Limpiar PDF temporal anterior
        if self._tmp_pdf and self._tmp_pdf != path:
            try:
                os.unlink(self._tmp_pdf)
            except OSError:
                pass
        self._tmp_pdf = path
        self._pdf_doc.load(path)
        # Restaurar vista activa (página o mosaico)
        if getattr(self, '_mos_mode_on', False):
            self._rebuild_mosaico()
            self._preview_stack.setCurrentIndex(2)
        else:
            self._preview_stack.setCurrentIndex(1)
            self._fit_width()
        for b in (self._btn_pdf, self._btn_print):
            b.setEnabled(True)

    # ── Vista (Página / Mosaico) ───────────────────────────────────────
    def _on_vista_cambiada(self, idx: int):
        """Handler del combo único: índice 0 = Página, 1-6 = Mosaico Ncol."""
        data = self._cmb_vista.itemData(idx)
        if not data:
            return
        modo, cols = data
        self._mos_mode_on = (modo == 'mosaico')
        if cols:
            self._mosaico_cols = int(cols)
        # Zoom +/-/fit aplica a vista de página solamente
        for b in (self._btn_zoom_in, self._btn_zoom_out, self._btn_fit):
            b.setEnabled(not self._mos_mode_on)
        if self._mos_mode_on:
            if self._pdf_doc.pageCount() <= 0:
                return
            self._rebuild_mosaico()
            self._preview_stack.setCurrentIndex(2)
        else:
            self._preview_stack.setCurrentIndex(1)

    def _rebuild_mosaico(self):
        """Renderiza cada página del PDF y la coloca en la grilla."""
        # Limpiar grilla previa
        while self._mos_grid.count():
            it = self._mos_grid.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        n = self._pdf_doc.pageCount()
        if n <= 0:
            return
        # Cap a `cols ≤ n` — si el user pidió 4 cols y solo hay 3 páginas,
        # las 3 ocupan TODO el ancho (no se ven aplastadas en 3/4).
        cols = max(1, min(int(self._mosaico_cols), n))
        # Limpiar stretch de cols previos (si antes había más).
        prev_cols = max(1, int(self._mosaico_cols))
        for c in range(prev_cols + 1):
            self._mos_grid.setColumnStretch(c, 0)
        # Calcular ancho disponible del scroll area para distribuir las páginas
        avail = max(400, self._mos_scroll.viewport().width() - 32)
        thumb_w = max(140, int((avail - (cols - 1) * 14) / cols) - 4)
        for i in range(n):
            # Tamaño de la página en puntos → píxeles a 96dpi
            page_pts = self._pdf_doc.pagePointSize(i)
            if page_pts.width() <= 0 or page_pts.height() <= 0:
                continue
            aspect = page_pts.height() / page_pts.width()
            tw = thumb_w
            th = int(tw * aspect)
            img = self._pdf_doc.render(i, QSize(tw, th))
            pix = QPixmap.fromImage(img)
            # Card contenedor: sombra simulada + número de página
            card = QFrame()
            card.setStyleSheet(
                f"QFrame {{ background:{WHITE}; border:1px solid {SLATE_100};"
                f" border-radius:4px; }}"
                f"QFrame:hover {{ border:1px solid {ORANGE}; }}"
            )
            cv = QVBoxLayout(card)
            cv.setContentsMargins(4, 4, 4, 4)
            cv.setSpacing(2)
            lbl = QLabel()
            lbl.setPixmap(pix)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet("background:white; border:none;")
            cv.addWidget(lbl)
            cap = QLabel(f"Página {i + 1} de {n}")
            cap.setAlignment(Qt.AlignCenter)
            cap.setStyleSheet(
                f"color:{SLATE_500}; font-size:10px; padding:2px 0;"
                " background:transparent; border:none;"
            )
            cv.addWidget(cap)
            # Doble clic en la página → cambiar a vista normal en esa página
            lbl.mouseDoubleClickEvent = (
                lambda _e, page=i: self._abrir_pagina_en_vista(page)
            )
            self._mos_grid.addWidget(card, i // cols, i % cols)
        # Stretch para que las columnas no se desperdiguen
        for c in range(cols):
            self._mos_grid.setColumnStretch(c, 1)

    def _abrir_pagina_en_vista(self, page_index: int):
        """Doble clic en una página del mosaico → vuelve a vista de página
        y navega a esa página."""
        self._cmb_vista.setCurrentIndex(0)   # 0 = Página
        try:
            self._pdf_view.pageNavigator().jump(page_index, QPoint(0, 0), 1.0)
        except Exception:
            pass

    def _on_pdf_falla(self, msg: str):
        self._generando = False
        self._progress.setVisible(False)
        self._set_busy_cursor(False)
        self._lbl_state.setText(f"Error al generar el reporte:\n\n{msg}")
        self._preview_stack.setCurrentIndex(0)
        for b in (self._btn_pdf, self._btn_print):
            b.setEnabled(True)

    # ─── Zoom ────────────────────────────────────────────────────────────────

    def _cambiar_zoom(self, delta: float):
        z = self._pdf_view.zoomFactor() + delta
        z = max(0.4, min(3.0, z))
        self._pdf_view.setZoomMode(QPdfView.ZoomMode.Custom)
        self._pdf_view.setZoomFactor(z)
        self._lbl_zoom.setText(f"{int(z * 100)}%")

    def eventFilter(self, obj, event):
        """Sobre el viewport del QPdfView:
        - Ctrl+wheel  → zoom in/out
        - Mid-click + drag → pan (manito) — clásico de visores PDF.
        """
        from PySide6.QtCore import QEvent
        if obj is not self._pdf_view.viewport():
            return super().eventFilter(obj, event)

        et = event.type()
        # ── Zoom con Ctrl+rueda ───────────────────────────────────────────
        if et == QEvent.Wheel and (event.modifiers() & Qt.ControlModifier):
            angle = event.angleDelta().y()
            if angle != 0:
                self._cambiar_zoom(0.1 if angle > 0 else -0.1)
            return True

        # ── Pan con mid-click ─────────────────────────────────────────────
        if et == QEvent.MouseButtonPress and event.button() == Qt.MiddleButton:
            self._pan_start_pos = event.position().toPoint()
            sb_h = self._pdf_view.horizontalScrollBar()
            sb_v = self._pdf_view.verticalScrollBar()
            self._pan_start_h = sb_h.value() if sb_h else 0
            self._pan_start_v = sb_v.value() if sb_v else 0
            self._pdf_view.viewport().setCursor(Qt.ClosedHandCursor)
            return True
        if et == QEvent.MouseMove and (event.buttons() & Qt.MiddleButton):
            if getattr(self, '_pan_start_pos', None) is not None:
                delta = event.position().toPoint() - self._pan_start_pos
                sb_h = self._pdf_view.horizontalScrollBar()
                sb_v = self._pdf_view.verticalScrollBar()
                if sb_h:
                    sb_h.setValue(self._pan_start_h - delta.x())
                if sb_v:
                    sb_v.setValue(self._pan_start_v - delta.y())
            return True
        if et == QEvent.MouseButtonRelease and event.button() == Qt.MiddleButton:
            self._pan_start_pos = None
            self._pdf_view.viewport().unsetCursor()
            return True

        return super().eventFilter(obj, event)

    def _fit_width(self):
        self._pdf_view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        # Estimar zoom para mostrar en label (aproximado)
        self._lbl_zoom.setText("Ajus.")

    # ─── Acciones ────────────────────────────────────────────────────────────

    def _resumen_nombre_obra(self, n_palabras: int = 5) -> str:
        """Toma el nombre del proyecto, lo recorta a `n_palabras` palabras y
        lo sanitiza para uso como nombre de archivo. Espejo de la regla
        validada con Marco: primero el tipo de reporte, después el nombre
        de la obra resumido (≤5 palabras) para evitar paths kilométricos.
        """
        import re
        s = (self._proy_nombre or 'proyecto').strip()
        palabras = re.split(r'\s+', s)
        s = ' '.join(palabras[:n_palabras])
        s = re.sub(r'[^\w\-_. ]', '_', s)
        s = re.sub(r'\s+', '_', s)
        return s or 'proyecto'

    def _nombre_archivo(self, ext: str) -> str:
        """Nombre sugerido: `<tipo>_<obra resumida>.<ext>`."""
        tipo = self._tipo_actual or 'reporte'
        obra = self._resumen_nombre_obra()
        return f"{tipo}_{obra}.{ext}"

    def _dir_descargas(self) -> str:
        """Última carpeta usada para guardar reportes (persistida en QSettings).
        Por defecto la ruta configurada, luego Descargas, luego HOME."""
        s = QSettings("ingePresupuestos", "reportes")
        guardado = s.value("last_export_dir", "")
        if guardado and os.path.isdir(guardado):
            return guardado
        from core.database import get_config
        ruta_cfg = get_config('ruta_exportacion', '')
        if ruta_cfg and os.path.isdir(ruta_cfg):
            return ruta_cfg
        candidatos = [os.path.expanduser("~/Descargas"),
                      os.path.expanduser("~/Downloads"),
                      os.path.expanduser("~")]
        return next((c for c in candidatos if os.path.isdir(c)), os.getcwd())

    def _save_dir(self, path: str):
        """Persiste la carpeta del archivo recién guardado."""
        if not path:
            return
        d = os.path.dirname(path)
        if d and os.path.isdir(d):
            QSettings("ingePresupuestos", "reportes").setValue("last_export_dir", d)

    def _ruta_default(self, ext: str) -> str:
        return os.path.join(self._dir_descargas(), self._nombre_archivo(ext))

    def _guardar_pdf(self):
        if not self._tmp_pdf or not os.path.exists(self._tmp_pdf):
            QMessageBox.warning(self, "Reportes", "Aún no hay un PDF generado.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Guardar PDF", self._ruta_default('pdf'), "PDF (*.pdf)"
        )
        if not path:
            return
        self._save_dir(path)
        try:
            import shutil
            shutil.copyfile(self._tmp_pdf, path)
            QMessageBox.information(self, "Reportes", f"Guardado en:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Reportes", f"No se pudo guardar:\n{e}")

    def _render_pdf_pagina_a_png(self, page: int, path: str, dpi: int = 200):
        """Renderiza una página del PDF temporal a PNG sin transparencia.
        El render de QPdfDocument incluye alfa; lo componemos sobre un
        QImage RGB32 con fondo blanco para asegurar opacidad total."""
        pts = self._pdf_doc.pagePointSize(page)
        if pts.width() <= 0 or pts.height() <= 0:
            raise RuntimeError(f"Página {page + 1} con dimensiones inválidas.")
        scale = dpi / 72.0
        w = max(1, int(round(pts.width()  * scale)))
        h = max(1, int(round(pts.height() * scale)))
        rendered = self._pdf_doc.render(page, QSize(w, h))
        out = QImage(w, h, QImage.Format_RGB32)
        out.fill(Qt.white)
        p = QPainter(out)
        p.drawImage(0, 0, rendered)
        p.end()
        if not out.save(path, "PNG"):
            raise RuntimeError("Qt no pudo escribir el PNG en el disco.")

    def _guardar_png(self):
        if not self._tmp_pdf or not os.path.exists(self._tmp_pdf):
            QMessageBox.warning(self, "Reportes", "Aún no hay un PDF generado.")
            return
        n = self._pdf_doc.pageCount()
        if n <= 0:
            QMessageBox.warning(self, "Reportes", "El PDF no tiene páginas.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Guardar PNG", self._ruta_default('png'), "PNG (*.png)"
        )
        if not path:
            return
        self._save_dir(path)
        try:
            if n == 1:
                self._render_pdf_pagina_a_png(0, path)
                QMessageBox.information(self, "Reportes",
                                            f"Guardado en:\n{path}")
                return
            # Varias páginas → sufijo _pNN al stem elegido por el usuario.
            base, ext = os.path.splitext(path)
            if not ext:
                ext = '.png'
            ancho = len(str(n))
            archivos = []
            for i in range(n):
                out = f"{base}_p{str(i + 1).zfill(ancho)}{ext}"
                self._render_pdf_pagina_a_png(i, out)
                archivos.append(out)
            QMessageBox.information(self, "Reportes",
                f"Guardadas {n} imágenes en:\n{os.path.dirname(path)}\n\n"
                f"Primera: {os.path.basename(archivos[0])}\n"
                f"Última:  {os.path.basename(archivos[-1])}"
            )
        except Exception as e:
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "Reportes",
                f"No se pudo exportar a PNG:\n{e}")

    def _guardar_excel(self):
        if not self._tipo_actual:
            return
        from core.licencia import require_premium
        if not require_premium('export_editable', self):
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Guardar Excel", self._ruta_default('xlsx'), "Excel (*.xlsx)"
        )
        if not path:
            return
        self._save_dir(path)
        try:
            # Cronograma valorizado / adquisiciones → render directo desde
            # los widgets enriquecidos (mismo .xlsx que el botón de la vista).
            if self._tipo_actual in ('cronograma_valorizado',
                                       'cronograma_adquisiciones'):
                self._ensure_cron_helper()
                if self._tipo_actual == 'cronograma_valorizado':
                    self._cron_helper._valorz_w._build_xlsx_valorizado(path)
                else:
                    self._cron_helper._insumos_w._build_xlsx(path)
                QMessageBox.information(self, "Reportes",
                                            f"Guardado en:\n{path}")
                return
            from core.exporter import (
                exportar_presupuesto, exportar_acus,
                exportar_insumos, exportar_metrados,
                exportar_gastos_generales, exportar_reporte_completo,
            )
            fn = {
                'presupuesto':      exportar_presupuesto,
                'acus':             exportar_acus,
                'insumos':          exportar_insumos,
                'metrados':         exportar_metrados,
                'gastos_generales': exportar_gastos_generales,
                'completo':         exportar_reporte_completo,
            }.get(self._tipo_actual)
            if not fn:
                QMessageBox.warning(self, "Reportes",
                                    "Excel no disponible para este tipo de reporte.")
                return
            buf = fn(self.pid)
            with open(path, 'wb') as f:
                f.write(buf.getvalue())
            QMessageBox.information(self, "Reportes", f"Guardado en:\n{path}")
        except Exception as e:
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "Reportes", f"No se pudo exportar a Excel:\n{e}")

    def _guardar_word(self):
        if not self._tipo_actual:
            return
        from core.licencia import require_premium
        if not require_premium('export_editable', self):
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Guardar Word", self._ruta_default('docx'),
            "Word (*.docx)"
        )
        if not path:
            return
        self._save_dir(path)
        try:
            # Curva S — usa el _build_docx del CurvaSWidget
            if self._tipo_actual == 'cronograma_curva_s':
                self._ensure_cron_helper()
                curva = self._cron_helper._curva_w
                self._aplicar_periodo_curva(curva)
                curva.cargar()
                curva._build_docx(path)
                QMessageBox.information(self, "Reportes",
                                            f"Guardado en:\n{path}")
                return
            from core import word_reports
            word_reports.generar_word(self._tipo_actual, self.pid, path)
            QMessageBox.information(self, "Reportes", f"Guardado en:\n{path}")
        except NotImplementedError as e:
            QMessageBox.warning(self, "Reportes",
                f"Este reporte aún no tiene export a Word.\n\n{e}\n\n"
                "Usa PDF mientras tanto.")
        except Exception as e:
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "Reportes",
                f"No se pudo exportar a Word:\n{e}")

    def _guardar_odt(self):
        if not self._tipo_actual:
            return
        from core.licencia import require_premium
        if not require_premium('export_editable', self):
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Guardar ODT", self._ruta_default('odt'),
            "OpenDocument Text (*.odt)"
        )
        if not path:
            return
        self._save_dir(path)
        try:
            # Curva S — generamos .docx y lo convertimos a .odt
            if self._tipo_actual == 'cronograma_curva_s':
                import os, subprocess, tempfile
                from core.soffice import find_soffice, mensaje_instalacion
                soffice = find_soffice()
                if not soffice:
                    QMessageBox.warning(self, "Exportar ODT",
                                          mensaje_instalacion())
                    return
                self._ensure_cron_helper()
                curva = self._cron_helper._curva_w
                self._aplicar_periodo_curva(curva)
                curva.cargar()
                tmp_fd, tmp_docx = tempfile.mkstemp(suffix='.docx',
                                                       prefix='curva_odt_')
                os.close(tmp_fd)
                try:
                    curva._build_docx(tmp_docx)
                    out_dir = os.path.dirname(os.path.abspath(path))
                    subprocess.run(
                        [soffice, '--headless', '--convert-to', 'odt',
                         '--outdir', out_dir, tmp_docx],
                        check=True, capture_output=True, timeout=60,
                    )
                    generated = os.path.join(
                        out_dir,
                        os.path.splitext(os.path.basename(tmp_docx))[0] + '.odt'
                    )
                    if os.path.exists(generated) and generated != path:
                        os.replace(generated, path)
                    if not os.path.exists(path):
                        raise RuntimeError("LibreOffice no generó el .odt")
                finally:
                    try: os.unlink(tmp_docx)
                    except Exception: pass
                QMessageBox.information(self, "Reportes",
                                            f"Guardado en:\n{path}")
                return
            from core import odt_reports
            odt_reports.generar_odt(self._tipo_actual, self.pid, path)
            QMessageBox.information(self, "Reportes", f"Guardado en:\n{path}")
        except NotImplementedError as e:
            QMessageBox.warning(self, "Reportes",
                f"Este reporte aún no tiene export a ODT.\n\n{e}\n\n"
                "Usa PDF mientras tanto.")
        except Exception as e:
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "Reportes",
                f"No se pudo exportar a ODT:\n{e}")

    def _guardar_ods(self):
        if not self._tipo_actual:
            return
        from core.licencia import require_premium
        if not require_premium('export_editable', self):
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Guardar ODS", self._ruta_default('ods'),
            "OpenDocument Spreadsheet (*.ods)"
        )
        if not path:
            return
        self._save_dir(path)
        try:
            # Cronograma valorizado / adquisiciones → reuso del flujo del
            # widget (xlsx temporal + LibreOffice convert-to ods).
            if self._tipo_actual in ('cronograma_valorizado',
                                       'cronograma_adquisiciones'):
                import os, subprocess, tempfile
                from core.soffice import find_soffice, mensaje_instalacion
                soffice = find_soffice()
                if not soffice:
                    QMessageBox.warning(self, "Exportar ODS",
                                          mensaje_instalacion())
                    return
                self._ensure_cron_helper()
                tmp_fd, tmp_xlsx = tempfile.mkstemp(suffix='.xlsx',
                                                       prefix='cron_ods_')
                os.close(tmp_fd)
                try:
                    if self._tipo_actual == 'cronograma_valorizado':
                        self._cron_helper._valorz_w._build_xlsx_valorizado(tmp_xlsx)
                    else:
                        self._cron_helper._insumos_w._build_xlsx(tmp_xlsx)
                    out_dir = os.path.dirname(os.path.abspath(path))
                    subprocess.run(
                        [soffice, '--headless', '--convert-to', 'ods',
                         '--outdir', out_dir, tmp_xlsx],
                        check=True, capture_output=True, timeout=60,
                    )
                    generated = os.path.join(
                        out_dir,
                        os.path.splitext(os.path.basename(tmp_xlsx))[0] + '.ods'
                    )
                    if os.path.exists(generated) and generated != path:
                        os.replace(generated, path)
                    if not os.path.exists(path):
                        raise RuntimeError("LibreOffice no generó el .ods")
                finally:
                    try: os.unlink(tmp_xlsx)
                    except Exception: pass
                QMessageBox.information(self, "Reportes",
                                            f"Guardado en:\n{path}")
                return
            from core import ods_reports
            ods_reports.generar_ods(self._tipo_actual, self.pid, path)
            QMessageBox.information(self, "Reportes", f"Guardado en:\n{path}")
        except NotImplementedError as e:
            QMessageBox.warning(self, "Reportes",
                f"Este reporte aún no tiene export a ODS.\n\n{e}\n\n"
                "Usa Excel mientras tanto.")
        except Exception as e:
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "Reportes",
                f"No se pudo exportar a ODS:\n{e}")

    def _guardar_mpp(self):
        """Exporta el cronograma actual a Microsoft Project XML (.xml)."""
        if self._tipo_actual != 'cronograma':
            return
        from core.licencia import require_premium
        if not require_premium('export_editable', self):
            return
        import os
        sugerido = os.path.join(self._dir_descargas(),
                                  f"gantt_{self.pid}.xml")
        path, _ = QFileDialog.getSaveFileName(
            self, "Guardar como MS Project (.xml)",
            sugerido, "MS Project XML (*.xml)"
        )
        if not path:
            return
        self._save_dir(path)
        try:
            self._ensure_cron_helper()
            gantt = self._cron_helper._gantt_w
            # _exportar_mpp del GanttWidget escribe el XML directamente; lo
            # invocamos pasando el path destino vía save_dir bypass.
            from PySide6.QtCore import QSettings
            QSettings("ingePresupuestos", "exports").setValue("last_dir_gantt", os.path.dirname(path))
            self._mpp_a_path(gantt, path)
            QMessageBox.information(self, "Reportes",
                                       f"Cronograma exportado a:\n{path}")
        except Exception as e:
            import traceback; traceback.print_exc()
            QMessageBox.critical(self, "Reportes",
                f"No se pudo exportar a MPP:\n{e}")

    def _render_section_divider_pdf(self, n: int, nombre: str,
                                       descripcion: str = '') -> str:
        """Renderiza un divisor de sección como PDF de una sola página A4
        portrait, con título grande naranja + número + descripción centrados."""
        from PySide6.QtGui import QPdfWriter, QPageSize
        from PySide6.QtCore import QMarginsF
        from PySide6.QtGui import QPageLayout as _QPL
        tmp = tempfile.NamedTemporaryFile(
            prefix='completo_div_', suffix='.pdf', delete=False
        )
        tmp.close()
        writer = QPdfWriter(tmp.name)
        writer.setResolution(150)
        writer.setPageSize(QPageSize(QPageSize.A4))
        layout = _QPL(writer.pageLayout())
        layout.setOrientation(_QPL.Portrait)
        layout.setMargins(QMarginsF(20, 20, 20, 20))
        writer.setPageLayout(layout)
        painter = QPainter(writer)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            dpi = writer.logicalDpiX()
            mm = lambda v: v * dpi / 25.4
            paint_rect = writer.pageLayout().paintRect(_QPL.Unit.Point)
            page_w = paint_rect.width() * dpi / 72.0
            page_h = paint_rect.height() * dpi / 72.0
            # Centro vertical ~ 35% desde arriba
            cy = page_h * 0.32

            from PySide6.QtCore import QRectF as _QRectF
            painter.setPen(QColor("#F37329"))
            f = painter.font(); f.setPointSizeF(13); f.setBold(True)
            painter.setFont(f)
            painter.drawText(_QRectF(0, cy, page_w, mm(8)),
                                Qt.AlignCenter, f"— SECCIÓN {n} —")
            cy += mm(18)
            painter.setPen(QColor("#1F2A38"))
            f.setPointSizeF(26); painter.setFont(f)
            painter.drawText(_QRectF(0, cy, page_w, mm(18)),
                                Qt.AlignCenter, nombre)
            cy += mm(22)
            painter.setPen(QPen(QColor("#F37329"), 2.0))
            line_w = page_w * 0.28
            painter.drawLine(QPointF((page_w - line_w) / 2, cy),
                                QPointF((page_w + line_w) / 2, cy))
            if descripcion:
                cy += mm(8)
                painter.setPen(QColor("#485A6C"))
                f.setPointSizeF(11); f.setBold(False); f.setItalic(True)
                painter.setFont(f)
                painter.drawText(
                    _QRectF(page_w * 0.12, cy, page_w * 0.76, mm(25)),
                    int(Qt.AlignCenter) | int(Qt.TextWordWrap), descripcion
                )
        finally:
            painter.end()
        return tmp.name

    def _render_completo_merged_pdf(self, progress=None) -> Optional[str]:
        """Genera el Reporte Completo como merge de varios PDFs:
        - Núcleo HTML A4 portrait (memoria → resumen → presupuesto → ACU →
          metrados → insumos → especificaciones) con portada principal + divisores.
        - Divisor + Gantt rich (auto-papel landscape, una hoja).
        - Divisor + Valorizado one-page (auto-papel landscape).
        - Divisor + Adquisiciones one-page (auto-papel landscape).
        - Divisor + Curva S rich (auto-papel portrait, espejo del individual).

        Dos pasadas para numeración global continua: primero render normal y
        cuento páginas, luego re-render pasando `pie_offset` y `pie_total`
        a cada pieza para que el footer muestre `Página N de TOTAL` global.
        """
        try:
            from pypdf import PdfWriter, PdfReader
        except ImportError:
            QMessageBox.warning(self, "Reporte Completo",
                "Se necesita el paquete `pypdf`. Instálalo con:\n"
                "  pip install pypdf")
            return None

        from core import pdf_reports as _pr
        from core.database import get_db
        # Verificar que el proyecto existe
        conn = get_db()
        if not conn.execute("SELECT id FROM proyectos WHERE id=?",
                               (self.pid,)).fetchone():
            conn.close()
            return None
        conn.close()

        # Renderizadores parametrizables por offset+total (cada uno devuelve
        # una ruta a PDF). Los divisores son siempre 1 página y no muestran
        # número (decisión de diseño — son "tabs" entre secciones).
        def _r_sec_nucleo(code, num, cover, cover_title, offset, total):
            # Cada sección del núcleo es un PDF propio: su encabezado de
            # página muestra el nombre de la sección (no «Expediente
            # Técnico»), para distinguir las hojas en documentos gruesos.
            p = tempfile.NamedTemporaryFile(prefix=f'completo_{code}_',
                                              suffix='.pdf', delete=False)
            p.close()
            _pr.generar_pdf_seccion_archivo(code, num, self.pid, p.name,
                                              with_cover=cover,
                                              titulo_cover=cover_title,
                                              pie_offset=offset,
                                              pie_total=total,
                                              con_divisor=not self._sin_separadores())
            return p.name

        def _r_divider(num, titulo, desc):
            # Divisores son páginas "tab" — no participan en la numeración
            # de pie, pero ocupan 1 página en el merge final.
            return self._render_section_divider_pdf(num, titulo, desc)

        def _r_gantt(offset, total):
            try:
                self._ensure_cron_helper()
            except Exception:
                return None
            gantt = getattr(self._cron_helper, '_gantt_w', None)
            if gantt is None:
                return None
            from core.database import get_db as _gdb
            cn = _gdb()
            cnt_part = cn.execute(
                "SELECT COUNT(*) FROM partidas WHERE proyecto_id=? AND es_titulo=0",
                (self.pid,)).fetchone()[0] or 0
            cn.close()
            if cnt_part == 0:
                return None
            from views.cronograma_view import GanttWidget as _GW
            day_w = getattr(gantt, 'DAY_W', _GW.DAY_W)
            papel = 'A4'
            if day_w >= 8 or cnt_part > 40:
                papel = 'A3'
            if day_w >= 16 or cnt_part > 100:
                papel = 'A2'
            if cnt_part > 200:
                papel = 'A1'
            tmp = tempfile.NamedTemporaryFile(prefix="reporte_gantt_",
                                                  suffix='.pdf', delete=False)
            tmp.close()
            try:
                gantt._render_pdf_completo(
                    tmp.name, 'fit', 'landscape', True, escala='auto',
                    hojas_x=0, papel=papel,
                    incluir_header=True, incluir_footer=True,
                    incluir_legend=True, incluir_page=True,
                    pie_offset=offset, pie_total=total,
                )
                return tmp.name
            except Exception:
                return None

        def _r_tabular(tipo, offset, total):
            from core import pdf_reports as _pr2
            from core.database import get_db as _gdb, calcular_totales
            from core.cronograma import get_cronograma_map
            cn = _gdb()
            row = cn.execute("SELECT * FROM proyectos WHERE id=?",
                                (self.pid,)).fetchone()
            if not row: cn.close(); return None
            proy = dict(row)
            items, _ = calcular_totales(self.pid)
            cron_map = get_cronograma_map(cn, self.pid)
            cn.close()
            plazo = int(proy.get('plazo') or 30)
            max_end = 0
            for cd in cron_map.values():
                end = (cd.get('inicio_dia') or 1) + (cd.get('duracion') or 0) - 1
                max_end = max(max_end, end)
            n_partidas = sum(1 for e in items if not e['partida'].get('es_titulo'))
            n_dias = max(max_end, plazo, 7)
            # Auto: mensual por default
            escala, period_days = 'mes', 30
            if n_dias <= 60:
                escala, period_days = 'semana', 7
            n_periods = max(1, (n_dias + period_days - 1) // period_days)
            if n_periods <= 10 and n_partidas <= 25: papel = 'A4'
            elif n_periods <= 20 and n_partidas <= 50: papel = 'A3'
            elif n_periods <= 36 and n_partidas <= 100: papel = 'A2'
            elif n_periods <= 60 and n_partidas <= 180: papel = 'A1'
            else: papel = 'A0'
            _pr2._BUILD_HTML_PAPER['paper'] = papel
            _pr2._BUILD_HTML_PAPER['orient'] = 'landscape'
            _pr2._BUILD_HTML_PAPER['escala'] = escala
            _pr2._BUILD_HTML_PAPER['periodos_por_pagina'] = -1
            _pr2._BUILD_HTML_PAPER['show_fechas'] = False
            prefix = ('reporte_valorizado_' if tipo == 'cronograma_valorizado'
                       else 'reporte_adquisiciones_')
            tmp = tempfile.NamedTemporaryFile(prefix=prefix, suffix='.pdf',
                                                  delete=False)
            tmp.close()
            _pr2.generar_pdf_archivo(tipo, self.pid, tmp.name,
                                       with_cover=False, paper=papel,
                                       orient='landscape',
                                       pie_offset=offset, pie_total=total)
            return tmp.name

        def _r_curva(offset, total):
            try:
                self._ensure_cron_helper()
            except Exception:
                return None
            curva = getattr(self._cron_helper, '_curva_w', None)
            if curva is None:
                return None
            self._aplicar_periodo_curva(curva)
            curva.cargar()
            data = getattr(curva, '_last_data', None)
            if not data or data.get('total_general', 0) <= 0:
                return None
            tmp = tempfile.NamedTemporaryFile(prefix="reporte_curva_s_",
                                                  suffix='.pdf', delete=False)
            tmp.close()
            curva._render_pdf(tmp.name, paper='A4', orient='portrait',
                                 pie_offset=offset, pie_total=total)
            return tmp.name

        # ── Secciones según las casillas marcadas ──
        # La numeración «SECCIÓN n» es secuencial SOLO sobre lo seleccionado,
        # igual que la numeración global de páginas.
        sel = self._secciones_completo_sel()
        if not sel:
            QMessageBox.information(self, "Reporte Completo",
                "Marca al menos una sección en la fila «Secciones:».")
            return None
        etiqueta_de = dict(_SECCIONES_COMPLETO)
        # Título de la carátula: todo seleccionado → «Expediente Técnico»;
        # subconjunto → lista de secciones (o genérico si no cabe).
        if len(sel) == len(_SECCIONES_COMPLETO):
            titulo_cover = 'Expediente Técnico — Reporte Completo'
        else:
            unido = ' · '.join(etiqueta_de[c] for c in sel)
            titulo_cover = (f'Reporte — {unido}' if len(unido) <= 52
                            else 'Reporte del Proyecto')
        cron_info = {
            'cron_gantt': ('Cronograma — Diagrama Gantt',
                'Tabla y barras Gantt con duración, inicio, fin y predecesoras.',
                _r_gantt),
            'cron_valorizado': ('Cronograma — Valorizado',
                'Distribución del costo por semana o mes a lo largo del plazo.',
                lambda o, t: _r_tabular('cronograma_valorizado', o, t)),
            'cron_adquisiciones': ('Cronograma — Adquisiciones',
                'Insumos a comprar por período, agrupados por categoría.',
                lambda o, t: _r_tabular('cronograma_adquisiciones', o, t)),
            'cron_curva': ('Cronograma — Curva S',
                'Avance acumulado del proyecto en porcentaje, gráfico y tabla.',
                _r_curva),
        }
        # Estructura: lista de tuplas (kind, generador_callback)
        # kind=='paged' → contribuye a la numeración; kind=='divider' → no.
        # La portada principal va en la PRIMERA sección de núcleo seleccionada.
        secciones = []
        nombres = []   # etiquetas para el indicador de progreso
        sin_sep = self._sin_separadores()
        primera_nucleo = next((c for c in sel if c in _SECCIONES_NUCLEO), None)
        for num, code in enumerate(sel, start=1):
            if code in _SECCIONES_NUCLEO:
                secciones.append(('paged',
                    lambda o, t, c=code, n=num: _r_sec_nucleo(
                        c, n, c == primera_nucleo, titulo_cover, o, t)))
                nombres.append(etiqueta_de[code])
            else:
                titulo_c, desc_c, fn_c = cron_info[code]
                # La divisora de cronograma es una página aparte; con «Sin
                # separadores» se omite (el reporte de cronograma trae su
                # propio encabezado, así que sigue identificándose).
                if not sin_sep:
                    secciones.append(('divider',
                        lambda n=num, tt=titulo_c, dd=desc_c: _r_divider(n, tt, dd)))
                    nombres.append('preparando')
                secciones.append(('paged', fn_c))
                nombres.append(etiqueta_de[code])
        # Progreso: PASS 1 + PASS 2 + merge.
        _total_pasos = len(secciones) * 2 + 1
        _paso = [0]
        def _avanzar(nombre):
            _paso[0] += 1
            if progress:
                progress(_paso[0] / _total_pasos,
                         f"Generando reporte completo… ({nombre})")

        all_paths: list[str] = []
        try:
            # ── PASS 1: render con valores dummy (offset=0, total=1) para
            # poder contar páginas de cada pieza con pypdf. Las páginas de
            # los divisores no llevan número en su footer.
            counts: list[int] = []
            tmp_p1: list[Optional[str]] = []
            for _i, (kind, fn) in enumerate(secciones):
                _avanzar(nombres[_i] if _i < len(nombres) else 'sección')
                if kind == 'divider':
                    p = fn()
                else:
                    p = fn(0, 1)  # dummy
                tmp_p1.append(p)
                if p:
                    try:
                        with open(p, 'rb') as fh:
                            counts.append(len(PdfReader(fh).pages))
                    except Exception:
                        counts.append(0)
                else:
                    counts.append(0)
            # Limpiar PDFs de la pasada 1
            for p in tmp_p1:
                if p:
                    try: os.unlink(p)
                    except Exception: pass

            # Total global = suma de TODAS las páginas (incluyendo divisores).
            total_pages = sum(counts)
            # Offsets para piezas `paged`: número de páginas ANTES de cada una.
            offsets: list[int] = []
            acc = 0
            for c in counts:
                offsets.append(acc)
                acc += c

            # ── PASS 2: regenerar con offset/total para numeración continua
            for idx, (kind, fn) in enumerate(secciones):
                _avanzar(nombres[idx] if idx < len(nombres) else 'sección')
                if kind == 'divider':
                    p = fn()
                else:
                    p = fn(offsets[idx], total_pages)
                if p:
                    all_paths.append(p)

            # ── Merge final ──
            _avanzar('uniendo')
            writer = PdfWriter()
            for p in all_paths:
                try:
                    writer.append(p)
                except Exception as e:
                    print(f"[completo] merge omitido {p}: {e}")
            out = tempfile.NamedTemporaryFile(
                prefix='reporte_completo_', suffix='.pdf', delete=False
            )
            out.close()
            with open(out.name, 'wb') as f:
                writer.write(f)
            writer.close()
            return out.name
        finally:
            # Limpiar PDFs intermedios
            for p in all_paths:
                try: os.unlink(p)
                except Exception: pass

    def _aplicar_periodo_curva(self, curva):
        """Aplica la selección del combo Período al CurvaSWidget oculto."""
        sel_per = (self._cmb_periodo.currentIndex()
                    if hasattr(self, '_cmb_periodo') else 0)
        if sel_per == 1:
            curva._period_days = 7
        elif sel_per == 2:
            curva._period_days = 30
        else:
            # Auto: mensual por default; para plazos ≤ 60 días cae a semanal.
            plazo = int(self._cron_helper._proy.get('plazo') or 0)
            curva._period_days = 7 if plazo <= 60 else 30

    # ── Packs (Office / LibreOffice) ──────────────────────────────────
    def _safe_name(self, s: str, n_palabras: int = 5) -> str:
        """Sanitiza un string para usar como nombre de archivo, recortando
        a las primeras `n_palabras` palabras (default 5 — regla de Marco
        para mantener nombres cortos)."""
        import re
        s = (s or 'proyecto').strip()
        palabras = re.split(r'\s+', s)
        s = ' '.join(palabras[:n_palabras])
        s = re.sub(r'[^\w\-_. ]', '_', s)
        s = re.sub(r'\s+', '_', s)
        return s or 'proyecto'

    def _proyecto_nombre(self) -> str:
        from core.database import get_db
        conn = get_db()
        row = conn.execute("SELECT nombre FROM proyectos WHERE id=?",
                              (self.pid,)).fetchone()
        conn.close()
        return (row['nombre'] if row else '') or f"proyecto_{self.pid}"

    def _pedir_carpeta(self, titulo: str) -> Optional[str]:
        d = QFileDialog.getExistingDirectory(self, titulo, self._dir_descargas())
        if not d:
            return None
        self._save_dir(os.path.join(d, "_"))
        return d

    def _guardar_pack_office(self):
        """Descarga todos los archivos editables Office (Word/Excel/MPP) en
        una carpeta. Reporta al final qué se generó y qué falló."""
        from core.licencia import require_premium
        if not require_premium('export_editable', self):
            return
        carpeta = self._pedir_carpeta("Carpeta para Pack Office")
        if not carpeta:
            return
        base = self._safe_name(self._proyecto_nombre())
        from core import word_reports
        from core.exporter import (
            exportar_presupuesto, exportar_acus,
            exportar_insumos, exportar_metrados,
            exportar_gastos_generales,
        )

        ok, fallos = [], []

        def _try(nombre, fn):
            try:
                fn()
                ok.append(nombre)
            except Exception as e:
                fallos.append(f"{nombre}: {e}")

        def _xlsx_from_exporter(suffix, exp_fn):
            path = os.path.join(carpeta, f"{suffix}_{base}.xlsx")
            buf = exp_fn(self.pid)
            with open(path, 'wb') as f:
                f.write(buf.getvalue())

        # Word
        _try("memoria_descriptiva.docx",
              lambda: word_reports.generar_word('memoria_descriptiva', self.pid,
                          os.path.join(carpeta, f"memoria_descriptiva_{base}.docx")))
        _try("resumen.docx",
              lambda: word_reports.generar_word('resumen', self.pid,
                          os.path.join(carpeta, f"resumen_{base}.docx")))
        _try("especificaciones.docx",
              lambda: word_reports.generar_word('especificaciones', self.pid,
                          os.path.join(carpeta, f"especificaciones_{base}.docx")))
        # Excel
        _try("presupuesto.xlsx",
              lambda: _xlsx_from_exporter('presupuesto', exportar_presupuesto))
        _try("desagregado_pie.xlsx",
              lambda: _xlsx_from_exporter('desagregado_pie', exportar_gastos_generales))
        _try("acus.xlsx",
              lambda: _xlsx_from_exporter('acus', exportar_acus))
        _try("insumos.xlsx",
              lambda: _xlsx_from_exporter('insumos', exportar_insumos))
        _try("metrados.xlsx",
              lambda: _xlsx_from_exporter('metrados', exportar_metrados))

        # Cronogramas (necesitan cron_helper cargado)
        try:
            self._ensure_cron_helper()
        except Exception as e:
            fallos.append(f"cronograma_view: {e}")
            self._mostrar_pack_resultado("Pack Office", carpeta, ok, fallos)
            return

        # Valorizado xlsx
        _try("cronograma_valorizado.xlsx",
              lambda: self._cron_helper._valorz_w._build_xlsx_valorizado(
                  os.path.join(carpeta, f"cronograma_valorizado_{base}.xlsx")))
        # Adquisiciones xlsx
        _try("cronograma_adquisiciones.xlsx",
              lambda: self._cron_helper._insumos_w._build_xlsx(
                  os.path.join(carpeta, f"cronograma_adquisiciones_{base}.xlsx")))
        # Curva S docx
        def _curva_docx():
            self._aplicar_periodo_curva(self._cron_helper._curva_w)
            self._cron_helper._curva_w.cargar()
            self._cron_helper._curva_w._build_docx(
                os.path.join(carpeta, f"curva_s_{base}.docx"))
        _try("curva_s.docx", _curva_docx)
        # Gantt → XML de Microsoft Project (MSPDI). No es .mpp binario (formato
        # propietario que solo MS Project o tooling pago pueden escribir); este
        # XML lo abre Project nativamente con Archivo → Abrir.
        def _gantt_mpp():
            self._mpp_a_path(self._cron_helper._gantt_w,
                              os.path.join(carpeta, f"gantt_msproject_{base}.xml"))
        _try("gantt_msproject.xml", _gantt_mpp)

        nota = ("El Gantt se exporta como XML de Microsoft Project (MSPDI), no como "
                ".mpp binario. Ábrelo en MS Project con Archivo → Abrir; una vez "
                "abierto, si quieres el binario, usa Guardar como → .mpp."
                if any(o.startswith('gantt') for o in ok) else None)
        self._mostrar_pack_resultado("Pack Office", carpeta, ok, fallos, nota=nota)

    def _guardar_pack_libre(self):
        """Descarga todos los archivos editables LibreOffice (ODT/ODS).
        Convierte vía LibreOffice headless."""
        from core.licencia import require_premium
        if not require_premium('export_editable', self):
            return
        import subprocess
        from core.soffice import find_soffice, mensaje_instalacion
        soffice = find_soffice()
        if not soffice:
            QMessageBox.warning(self, "Pack LibreOffice",
                                  mensaje_instalacion())
            return
        carpeta = self._pedir_carpeta("Carpeta para Pack LibreOffice")
        if not carpeta:
            return
        base = self._safe_name(self._proyecto_nombre())
        from core import odt_reports
        ok, fallos = [], []

        def _try(nombre, fn):
            try:
                fn()
                ok.append(nombre)
            except Exception as e:
                fallos.append(f"{nombre}: {e}")

        def _xlsx_to_ods(suffix, xlsx_builder):
            """Genera xlsx temp, lo convierte a ods con soffice."""
            import tempfile
            target = os.path.join(carpeta, f"{suffix}_{base}.ods")
            fd, tmp_xlsx = tempfile.mkstemp(suffix='.xlsx', prefix='pack_')
            os.close(fd)
            try:
                xlsx_builder(tmp_xlsx)
                subprocess.run(
                    [soffice, '--headless', '--convert-to', 'ods',
                     '--outdir', carpeta, tmp_xlsx],
                    check=True, capture_output=True, timeout=60,
                )
                gen = os.path.join(carpeta,
                                      os.path.splitext(os.path.basename(tmp_xlsx))[0] + '.ods')
                if os.path.exists(gen):
                    os.replace(gen, target)
                if not os.path.exists(target):
                    raise RuntimeError("LibreOffice no generó el .ods")
            finally:
                try: os.unlink(tmp_xlsx)
                except Exception: pass

        # ODT — memoria, resumen y especificaciones
        _try("memoria_descriptiva.odt",
              lambda: odt_reports.generar_odt('memoria_descriptiva', self.pid,
                          os.path.join(carpeta, f"memoria_descriptiva_{base}.odt")))
        _try("resumen.odt",
              lambda: odt_reports.generar_odt('resumen', self.pid,
                          os.path.join(carpeta, f"resumen_{base}.odt")))
        _try("especificaciones.odt",
              lambda: odt_reports.generar_odt('especificaciones', self.pid,
                          os.path.join(carpeta, f"especificaciones_{base}.odt")))

        # ODS — vía xlsx + soffice convert
        from core.exporter import (
            exportar_presupuesto, exportar_acus,
            exportar_insumos, exportar_metrados,
            exportar_gastos_generales,
        )
        def _build_xlsx_via_exporter(exp_fn, dest):
            buf = exp_fn(self.pid)
            with open(dest, 'wb') as f:
                f.write(buf.getvalue())

        _try("presupuesto.ods",
              lambda: _xlsx_to_ods('presupuesto',
                  lambda p: _build_xlsx_via_exporter(exportar_presupuesto, p)))
        _try("desagregado_pie.ods",
              lambda: _xlsx_to_ods('desagregado_pie',
                  lambda p: _build_xlsx_via_exporter(exportar_gastos_generales, p)))
        _try("acus.ods",
              lambda: _xlsx_to_ods('acus',
                  lambda p: _build_xlsx_via_exporter(exportar_acus, p)))
        _try("insumos.ods",
              lambda: _xlsx_to_ods('insumos',
                  lambda p: _build_xlsx_via_exporter(exportar_insumos, p)))
        _try("metrados.ods",
              lambda: _xlsx_to_ods('metrados',
                  lambda p: _build_xlsx_via_exporter(exportar_metrados, p)))

        # Cronogramas
        try:
            self._ensure_cron_helper()
        except Exception as e:
            fallos.append(f"cronograma_view: {e}")
            self._mostrar_pack_resultado("Pack LibreOffice", carpeta, ok, fallos)
            return

        _try("cronograma_valorizado.ods",
              lambda: _xlsx_to_ods('cronograma_valorizado',
                  self._cron_helper._valorz_w._build_xlsx_valorizado))
        _try("cronograma_adquisiciones.ods",
              lambda: _xlsx_to_ods('cronograma_adquisiciones',
                  self._cron_helper._insumos_w._build_xlsx))

        # Curva S → docx → odt
        def _curva_odt():
            import tempfile
            self._aplicar_periodo_curva(self._cron_helper._curva_w)
            self._cron_helper._curva_w.cargar()
            target = os.path.join(carpeta, f"curva_s_{base}.odt")
            fd, tmp_docx = tempfile.mkstemp(suffix='.docx', prefix='curva_pack_')
            os.close(fd)
            try:
                self._cron_helper._curva_w._build_docx(tmp_docx)
                subprocess.run(
                    [soffice, '--headless', '--convert-to', 'odt',
                     '--outdir', carpeta, tmp_docx],
                    check=True, capture_output=True, timeout=60,
                )
                gen = os.path.join(carpeta,
                                      os.path.splitext(os.path.basename(tmp_docx))[0] + '.odt')
                if os.path.exists(gen):
                    os.replace(gen, target)
                if not os.path.exists(target):
                    raise RuntimeError("LibreOffice no generó el .odt")
            finally:
                try: os.unlink(tmp_docx)
                except Exception: pass
        _try("curva_s.odt", _curva_odt)

        self._mostrar_pack_resultado("Pack LibreOffice", carpeta, ok, fallos)

    def _mostrar_pack_resultado(self, titulo: str, carpeta: str,
                                   ok: list, fallos: list, nota: str = None):
        ok_txt = ('\n  • ' + '\n  • '.join(ok)) if ok else "\n  (ninguno)"
        msg = (
            f"Carpeta destino:\n{carpeta}\n\n"
            f"Generados ({len(ok)}):{ok_txt}"
        )
        if fallos:
            fl_txt = '\n  • ' + '\n  • '.join(fallos[:8])
            if len(fallos) > 8:
                fl_txt += f"\n  • … {len(fallos) - 8} más"
            msg += f"\n\nFallaron ({len(fallos)}):{fl_txt}"
        if nota:
            msg += f"\n\nℹ {nota}"
        QMessageBox.information(self, titulo, msg)

    def _ensure_cron_helper(self):
        """Garantiza que existe el CronogramaView oculto con datos cargados
        en todos sus sub-widgets (Gantt, Valorizado, CurvaS, Insumos)."""
        from views.cronograma_view import CronogramaView
        from core.database import get_db
        if not getattr(self, '_cron_helper', None):
            conn = get_db()
            row = conn.execute("SELECT * FROM proyectos WHERE id=?",
                                  (self.pid,)).fetchone()
            conn.close()
            if not row:
                raise RuntimeError("Proyecto no encontrado.")
            self._cron_helper = CronogramaView(
                self.pid, dict(row), on_back=lambda: None, parent=None
            )
        self._cron_helper.cargar()
        # Cargar sub-widgets que usan QTableWidget — necesarios para Excel/ODS
        for w_attr in ('_valorz_w', '_insumos_w'):
            try:
                w = getattr(self._cron_helper, w_attr, None)
                if w is not None and hasattr(w, 'cargar'):
                    w.cargar()
            except Exception:
                pass

    def _mpp_a_path(self, gantt, path: str):
        """Helper: invoca la lógica del MPP del GanttWidget escribiendo al
        path indicado. Replica la parte de I/O sin abrir el QFileDialog."""
        # _exportar_mpp del GanttWidget se basa en preguntar al usuario el
        # path. Aquí monkey-patchamos QFileDialog.getSaveFileName para
        # devolver el path elegido y dejar que la función haga su trabajo.
        from PySide6.QtWidgets import QFileDialog as _QFD
        orig = _QFD.getSaveFileName
        def _fake(*args, **kwargs):
            return (path, '')
        _QFD.getSaveFileName = staticmethod(_fake)
        try:
            gantt._exportar_mpp()
        finally:
            _QFD.getSaveFileName = orig

    def _imprimir(self):
        if not self._tmp_pdf or not os.path.exists(self._tmp_pdf):
            QMessageBox.warning(self, "Reportes", "Aún no hay un PDF generado.")
            return
        printer = QPrinter(QPrinter.HighResolution)
        # Renderiza páginas del PDF temporal en el QPainter
        dlg = QPrintPreviewDialog(printer, self)
        dlg.setWindowTitle("Vista previa de impresión")
        dlg.resize(900, 700)
        dlg.paintRequested.connect(lambda p: self._paint_pdf_a_printer(p))
        dlg.exec()

    def _paint_pdf_a_printer(self, printer: QPrinter):
        """Renderiza cada página del PDF temporal sobre el QPrinter.
        Usa pageLayout().paintRect en puntos (Qt6) y centra cada página
        en el área imprimible respetando aspect ratio."""
        if not self._tmp_pdf:
            return
        from PySide6.QtGui import QPageLayout
        doc = QPdfDocument()
        doc.load(self._tmp_pdf)
        n = doc.pageCount()
        if n <= 0:
            return
        painter = QPainter(printer)
        try:
            layout = printer.pageLayout()
            paint_pts = layout.paintRect(QPageLayout.Unit.Point)
            dpi = printer.resolution()
            # En Qt6 el QPainter sobre QPrinter trabaja en device pixels;
            # convertimos el área imprimible de puntos → px.
            target_w_px = int(paint_pts.width()  * dpi / 72.0)
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
                # Escala que cabe en el área imprimible (aspect ratio)
                scale = min(paint_pts.width() / pw, paint_pts.height() / ph)
                render_w = int(pw * scale * dpi / 72.0)
                render_h = int(ph * scale * dpi / 72.0)
                if render_w <= 0 or render_h <= 0:
                    continue
                img = doc.render(i, QSize(render_w, render_h))
                # Centrar la página en el área imprimible
                ox = max(0, (target_w_px - render_w) // 2)
                oy = max(0, (target_h_px - render_h) // 2)
                painter.drawImage(ox, oy, img)
        finally:
            painter.end()

    # ─── Cleanup ─────────────────────────────────────────────────────────────

    def closeEvent(self, ev):
        try:
            if self._worker and self._worker.isRunning():
                self._worker.quit()
                self._worker.wait(500)
        except Exception:
            pass
        try:
            self._pdf_doc.close()
        except Exception:
            pass
        if self._tmp_pdf and os.path.exists(self._tmp_pdf):
            try:
                os.unlink(self._tmp_pdf)
            except OSError:
                pass
        super().closeEvent(ev)
