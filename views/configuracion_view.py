# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""Configuración general del programa.

Vista unificada con tabs:
  - General        — decimales, apariencia
  - IA             — embebe IAView (proveedor, API key, modelos, conexión)
  - Accesibilidad  — placeholder, atajos/contraste/tamaños (próximamente)
  - Idioma         — placeholder (próximamente)

Para abrir la vista en una tab específica usar `set_tab(nombre)`.
"""
import os
import base64
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QSpinBox, QFormLayout,
    QButtonGroup, QScrollArea, QTabWidget,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QDialog, QLineEdit, QComboBox, QMessageBox,
    QFileDialog,
)
from PySide6.QtCore import Qt, QByteArray
from PySide6.QtGui import QFont, QPixmap

from core.database import (get_db, get_decimales_ppto, set_decimales_ppto,
                           get_decimales_metrado, set_decimales_metrado,
                           get_decimales_cant_acu, set_decimales_cant_acu,
                           get_config, set_config)
from core.config import MONEDAS, BACKUPS_DIR
from utils.theme import BTN_PRIMARY_SS
from utils.auth import (
    usuario_actual, listar_usuarios, crear_admin,
    actualizar_usuario, cambiar_password, toggle_activo, eliminar_usuario,
)

SLATE_700  = "#273445"
SLATE_500  = "#485A6C"
SLATE_300  = "#667885"
SILVER_100 = "#F8F9FA"
SILVER_300 = "#D4D4D4"
ORANGE     = "#F37329"
ORANGE_DRK = "#C0621A"
GREEN      = "#68B723"

_CARD_SS = "QFrame#cfgCard { background:white; border-radius:10px; border:1px solid #E3E6E9; }"
_SEC_SS  = (
    f"color:{SLATE_700}; font-size:13px; font-weight:700; "
    f"background:transparent; border:none;"
)
_NOTE_SS = (
    f"color:{SLATE_300}; font-size:11px; "
    f"background:transparent; border:none;"
)
_BTN_SAVE = BTN_PRIMARY_SS  # alias retro-compatible


class ConfiguracionView(QWidget):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setStyleSheet(f"background:{SILVER_100};")
        self._build_ui()

    _TAB_INDEX = {
        'general':       0,
        'ia':            1,
        'accesibilidad': 2,
        'idioma':        3,
        'usuarios':      4,
    }

    def _build_ui(self):
        from utils.i18n import tr
        main = QVBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)

        # Topbar oscuro con título + pestañas integradas
        hdr = QFrame()
        hdr.setFixedHeight(44)
        hdr.setStyleSheet(f"background:{SLATE_700};")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(16, 0, 16, 0)
        hl.setSpacing(0)

        lbl_t = QLabel(tr("Configuración"))
        lbl_t.setStyleSheet(
            "color:white; font-size:13px; font-weight:700; letter-spacing:0.5px;"
            " background:transparent; border:none;"
        )
        hl.addWidget(lbl_t)
        hl.addSpacing(20)

        # Pestañas como botones pill en el topbar
        self._tab_btns: list[QPushButton] = []
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(
            f"QTabWidget::pane {{ border:none; background:{SILVER_100}; }}"
            f"QTabBar {{ background:transparent; }}"
            f"QTabBar::tab {{ width:0; height:0; margin:0; padding:0; border:none; }}"
        )
        self._tabs.tabBar().setVisible(False)

        u = usuario_actual()
        es_admin = u and u.es_admin
        _TAB_NAMES = [tr("General"), tr("IA"), tr("Accesibilidad"), tr("Idioma")]
        if es_admin:
            _TAB_NAMES.append(tr("Usuarios"))
        for i, name in enumerate(_TAB_NAMES):
            b = QPushButton(name)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(
                f"QPushButton {{ color:rgba(255,255,255,0.55); background:transparent;"
                f" border:none; border-radius:6px;"
                f" padding:4px 14px; font-size:11px; font-weight:600; }}"
                f"QPushButton:hover {{ background:rgba(255,255,255,0.12); color:white; }}"
            )
            b.clicked.connect(lambda _, idx=i: self._switch_tab(idx))
            hl.addWidget(b)
            self._tab_btns.append(b)

        hl.addStretch()
        main.addWidget(hdr)

        # Contenido con márgenes
        content = QWidget()
        content.setStyleSheet(f"background:{SILVER_100};")
        cv = QVBoxLayout(content)
        cv.setContentsMargins(20, 14, 20, 16)
        cv.setSpacing(0)

        self._tabs.addTab(self._make_tab_general(),       "General")
        self._tabs.addTab(self._make_tab_ia(),            "IA")
        self._tabs.addTab(self._make_tab_accesibilidad(), "Accesibilidad")
        self._tabs.addTab(self._make_tab_idioma(),        "Idioma")
        if es_admin:
            self._tabs.addTab(self._make_tab_usuarios(), "Usuarios")
        cv.addWidget(self._tabs, stretch=1)
        main.addWidget(content, stretch=1)

        self._switch_tab(0)
        # Fix Qt: los labels auto-creados por QFormLayout pintan palette-Window
        # (#f8f9fa) como fondo pese al QSS global transparente → cajita gris.
        self._fix_form_label_bg()

    def _fix_form_label_bg(self):
        """Quita el fondo gris (#f8f9fa) que Qt pinta en los labels de
        QFormLayout aplicando un stylesheet transparente a nivel de widget
        (el QSS global `QLabel{background:transparent}` no basta para estos)."""
        from PySide6.QtWidgets import QFormLayout, QLabel
        for form in self.findChildren(QFormLayout):
            for i in range(form.rowCount()):
                item = form.itemAt(i, QFormLayout.LabelRole)
                w = item.widget() if item else None
                if isinstance(w, QLabel) and not w.styleSheet():
                    w.setStyleSheet("background: transparent; border: none;")

    def _switch_tab(self, idx: int):
        self._tabs.setCurrentIndex(idx)
        for i, b in enumerate(self._tab_btns):
            if i == idx:
                b.setStyleSheet(
                    f"QPushButton {{ color:white; background:rgba(255,255,255,0.15);"
                    f" border:none; border-radius:6px;"
                    f" padding:4px 14px; font-size:11px; font-weight:700; }}"
                    f"QPushButton:hover {{ background:rgba(255,255,255,0.22); }}"
                )
            else:
                b.setStyleSheet(
                    f"QPushButton {{ color:rgba(255,255,255,0.55); background:transparent;"
                    f" border:none; border-radius:6px;"
                    f" padding:4px 14px; font-size:11px; font-weight:600; }}"
                    f"QPushButton:hover {{ background:rgba(255,255,255,0.12); color:white; }}"
                )

    def set_tab(self, nombre: str):
        """Selecciona la tab por nombre (general|ia|accesibilidad|idioma)."""
        idx = self._TAB_INDEX.get(nombre.lower())
        if idx is not None:
            self._switch_tab(idx)

    # ── Tab General (Decimales + Apariencia) ──────────────────────────────

    def _make_tab_general(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(f"background:{SILVER_100};")
        inner = QWidget()
        inner.setStyleSheet(f"background:{SILVER_100};")
        root = QVBoxLayout(inner)
        root.setContentsMargins(0, 18, 0, 24)
        root.setSpacing(20)
        root.addWidget(self._card_empresa())
        root.addWidget(self._card_jornada())
        root.addWidget(self._card_moneda())
        root.addWidget(self._card_backups())
        root.addWidget(self._card_ruta_exportacion())
        root.addWidget(self._card_decimales())
        root.addWidget(self._card_barra_titulo())
        root.addStretch()
        scroll.setWidget(inner)
        return scroll

    # ── Tab IA (embebe IAView) ────────────────────────────────────────────

    def _make_tab_ia(self) -> QWidget:
        from views.ia_view import IAView
        ia = IAView()
        # Asistente Tuxia es funcionalidad IA — anexamos la card a esta tab
        # para mantener todo lo relacionado con IA en un solo lugar.
        ia.agregar_seccion(self._card_tuxia())
        return ia

    # ── Tab Accesibilidad ────────────────────────────────────────────────

    def _make_tab_accesibilidad(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(f"background:{SILVER_100};")
        inner = QWidget()
        inner.setStyleSheet(f"background:{SILVER_100};")
        root = QVBoxLayout(inner)
        root.setContentsMargins(0, 18, 0, 24)
        root.setSpacing(20)
        root.addWidget(self._card_apariencia())
        root.addWidget(self._card_atajos())
        root.addStretch()
        scroll.setWidget(inner)
        return scroll

    # ── Tab Idioma ────────────────────────────────────────────────────────

    def _make_tab_idioma(self) -> QWidget:
        from utils.theme import apply_shadow
        from utils.i18n import tr
        wrap = QWidget()
        wrap.setStyleSheet(f"background:{SILVER_100};")
        vl_outer = QVBoxLayout(wrap)
        vl_outer.setContentsMargins(0, 18, 0, 24)

        card = QFrame()
        card.setObjectName("cfgCard")
        card.setAttribute(Qt.WA_StyledBackground, True)
        card.setStyleSheet(_CARD_SS)
        vl = QVBoxLayout(card)
        vl.setContentsMargins(24, 20, 24, 24)
        vl.setSpacing(12)

        lbl = QLabel(tr("Idioma"))
        lbl.setStyleSheet(_SEC_SS)
        vl.addWidget(lbl)
        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color:{SILVER_300};")
        vl.addWidget(sep)

        nota = QLabel(
            tr("Selecciona el idioma de la interfaz.") + "\n"
            + tr("Los reportes se mantienen en el idioma del proyecto.")
        )
        nota.setWordWrap(True)
        nota.setStyleSheet(_NOTE_SS)
        vl.addWidget(nota)

        actual = get_config('idioma', 'es')
        self._bg_idioma = QButtonGroup(self)
        hl = QHBoxLayout()
        hl.setSpacing(8)

        _IDIOMAS = [
            ('es', "Español (Perú)", "Idioma principal de la aplicación"),
            ('en', "English", "Interface in English (partial — expanding)"),
        ]

        for codigo, nombre, desc in _IDIOMAS:
            btn = QPushButton(nombre)
            btn.setCheckable(True)
            btn.setFixedHeight(36)
            btn.setToolTip(desc)
            btn.setStyleSheet(
                f"QPushButton {{ background:{SILVER_100}; color:{SLATE_700};"
                f" border:1px solid {SILVER_300}; border-radius:6px;"
                f" font-size:12px; padding:0 14px; }}"
                f"QPushButton:hover {{ background:#E8EAED; }}"
                f"QPushButton:checked {{ background:{ORANGE}; color:white;"
                f" border-color:{ORANGE}; font-weight:600; }}"
            )
            if codigo == actual:
                btn.setChecked(True)
            btn.clicked.connect(lambda _ch, c=codigo, n=nombre: self._aplicar_idioma(c, n))
            self._bg_idioma.addButton(btn)
            hl.addWidget(btn)
        hl.addStretch()
        vl.addLayout(hl)

        nota2 = QLabel(
            "La traducción al inglés se está expandiendo gradualmente.\n"
            "Textos sin traducción se muestran en español."
        )
        nota2.setWordWrap(True)
        nota2.setStyleSheet(_NOTE_SS)
        vl.addWidget(nota2)

        self._lbl_idioma_estado = QLabel("")
        self._lbl_idioma_estado.setStyleSheet(
            f"color:{GREEN}; font-size:11px; background:transparent; border:none;"
        )
        vl.addWidget(self._lbl_idioma_estado)

        vl_outer.addWidget(card)
        vl_outer.addStretch()
        return wrap

    def _aplicar_idioma(self, codigo: str, nombre: str):
        set_config('idioma', codigo)
        from utils.i18n import set_idioma, tr
        set_idioma(codigo)
        self._lbl_idioma_estado.setText(
            tr("Idioma aplicado. Reinicia la aplicación para ver el cambio completo.")
        )

    def _placeholder_card(self, titulo: str, descripcion: str) -> QWidget:
        from utils.theme import apply_shadow
        wrap = QWidget()
        wrap.setStyleSheet(f"background:{SILVER_100};")
        vl_outer = QVBoxLayout(wrap)
        vl_outer.setContentsMargins(0, 18, 0, 24)

        card = QFrame()
        card.setObjectName("cfgCard")
        card.setAttribute(Qt.WA_StyledBackground, True)
        card.setStyleSheet(_CARD_SS)
        vl = QVBoxLayout(card)
        vl.setContentsMargins(24, 20, 24, 24)
        vl.setSpacing(12)
        lbl = QLabel(titulo)
        lbl.setStyleSheet(_SEC_SS)
        vl.addWidget(lbl)
        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color:{SILVER_300};")
        vl.addWidget(sep)
        nota = QLabel(descripcion)
        nota.setWordWrap(True)
        nota.setStyleSheet(_NOTE_SS)
        vl.addWidget(nota)
        vl_outer.addWidget(card)
        vl_outer.addStretch()
        return wrap

    # ── Card empresa/profesional ─────────────────────────────────────────

    def _card_empresa(self) -> QFrame:
        from utils.theme import apply_shadow
        from utils.i18n import tr
        card = QFrame()
        card.setObjectName("cfgCard")
        card.setAttribute(Qt.WA_StyledBackground, True)
        card.setStyleSheet(_CARD_SS)
        vl = QVBoxLayout(card)
        vl.setContentsMargins(24, 20, 24, 24)
        vl.setSpacing(12)

        lbl = QLabel(tr("Datos de empresa / profesional"))
        lbl.setStyleSheet(_SEC_SS)
        vl.addWidget(lbl)
        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color:{SILVER_300};")
        vl.addWidget(sep)

        nota = QLabel(
            tr("Estos datos aparecen en el encabezado de los reportes (PDF, Excel, Word).")
        )
        nota.setWordWrap(True)
        nota.setStyleSheet(_NOTE_SS)
        vl.addWidget(nota)

        _INP = (
            f"QLineEdit {{ border:1.5px solid {SILVER_300}; border-radius:6px;"
            f" padding:0 12px; font-size:12px; color:{SLATE_700}; background:white;"
            f" min-height:34px; }}"
            f"QLineEdit:focus {{ border-color:{ORANGE}; }}"
        )

        form = QFormLayout()
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignRight)

        self._inp_emp_nombre = QLineEdit()
        self._inp_emp_nombre.setStyleSheet(_INP)
        self._inp_emp_nombre.setPlaceholderText(tr("Nombre de empresa o profesional"))
        self._inp_emp_nombre.setText(get_config('empresa_nombre', ''))
        form.addRow(tr("Nombre:"), self._inp_emp_nombre)

        self._inp_emp_ruc = QLineEdit()
        self._inp_emp_ruc.setStyleSheet(_INP)
        self._inp_emp_ruc.setPlaceholderText(tr("RUC / DNI"))
        self._inp_emp_ruc.setText(get_config('empresa_ruc', ''))
        form.addRow(tr("RUC:"), self._inp_emp_ruc)

        self._inp_emp_direccion = QLineEdit()
        self._inp_emp_direccion.setStyleSheet(_INP)
        self._inp_emp_direccion.setPlaceholderText(tr("Dirección"))
        self._inp_emp_direccion.setText(get_config('empresa_direccion', ''))
        form.addRow(tr("Dirección:"), self._inp_emp_direccion)

        self._inp_emp_telefono = QLineEdit()
        self._inp_emp_telefono.setStyleSheet(_INP)
        self._inp_emp_telefono.setPlaceholderText(tr("Teléfono / celular"))
        self._inp_emp_telefono.setText(get_config('empresa_telefono', ''))
        form.addRow(tr("Teléfono:"), self._inp_emp_telefono)

        vl.addLayout(form)

        # Logo
        hl_logo = QHBoxLayout()
        hl_logo.setSpacing(10)
        self._lbl_logo_preview = QLabel()
        self._lbl_logo_preview.setFixedSize(64, 64)
        self._lbl_logo_preview.setStyleSheet(
            f"background:white; border:1px solid {SILVER_300}; border-radius:6px;"
        )
        self._lbl_logo_preview.setAlignment(Qt.AlignCenter)
        self._cargar_logo_preview()
        hl_logo.addWidget(self._lbl_logo_preview)

        vl_logo_btns = QVBoxLayout()
        vl_logo_btns.setSpacing(4)
        btn_logo = QPushButton(tr("Cargar logo"))
        btn_logo.setFixedHeight(28)
        btn_logo.setCursor(Qt.PointingHandCursor)
        btn_logo.setStyleSheet(
            f"QPushButton {{ background:white; color:{SLATE_700};"
            f" border:1px solid {SILVER_300}; border-radius:5px;"
            f" font-size:11px; padding:0 10px; }}"
            f"QPushButton:hover {{ background:#E8EAED; }}"
        )
        btn_logo.clicked.connect(self._emp_cargar_logo)
        vl_logo_btns.addWidget(btn_logo)

        btn_quitar_logo = QPushButton(tr("Quitar"))
        btn_quitar_logo.setFixedHeight(28)
        btn_quitar_logo.setCursor(Qt.PointingHandCursor)
        btn_quitar_logo.setStyleSheet(
            f"QPushButton {{ background:white; color:{SLATE_300};"
            f" border:1px solid {SILVER_300}; border-radius:5px;"
            f" font-size:11px; padding:0 10px; }}"
            f"QPushButton:hover {{ background:#FEF2F2; color:#C6262E; }}"
        )
        btn_quitar_logo.clicked.connect(self._emp_quitar_logo)
        vl_logo_btns.addWidget(btn_quitar_logo)
        hl_logo.addLayout(vl_logo_btns)
        hl_logo.addStretch()
        vl.addLayout(hl_logo)

        hl = QHBoxLayout()
        hl.addStretch()
        btn = QPushButton(tr("Guardar"))
        btn.setFixedHeight(34)
        btn.setStyleSheet(_BTN_SAVE)
        btn.clicked.connect(self._guardar_empresa)
        hl.addWidget(btn)
        vl.addLayout(hl)

        self._lbl_emp_estado = QLabel("")
        self._lbl_emp_estado.setStyleSheet(
            f"color:{GREEN}; font-size:11px; background:transparent; border:none;"
        )
        vl.addWidget(self._lbl_emp_estado)
        return card

    def _cargar_logo_preview(self):
        logo_b64 = get_config('empresa_logo_b64', '')
        if logo_b64:
            ba = QByteArray.fromBase64(logo_b64.encode('ascii'))
            pm = QPixmap()
            pm.loadFromData(ba)
            if not pm.isNull():
                self._lbl_logo_preview.setPixmap(
                    pm.scaled(60, 60, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                )
                return
        self._lbl_logo_preview.setText("Sin logo")
        self._lbl_logo_preview.setStyleSheet(
            f"background:white; border:1px solid {SILVER_300}; border-radius:6px;"
            f" color:{SLATE_300}; font-size:10px;"
        )

    def _emp_cargar_logo(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Seleccionar logo",
            os.path.expanduser("~"),
            "Imágenes (*.png *.jpg *.jpeg *.bmp)"
        )
        if not path:
            return
        with open(path, 'rb') as f:
            data = f.read()
        b64 = base64.b64encode(data).decode('ascii')
        set_config('empresa_logo_b64', b64)
        self._cargar_logo_preview()

    def _emp_quitar_logo(self):
        set_config('empresa_logo_b64', '')
        self._lbl_logo_preview.setPixmap(QPixmap())
        self._lbl_logo_preview.setText("Sin logo")
        self._lbl_logo_preview.setStyleSheet(
            f"background:white; border:1px solid {SILVER_300}; border-radius:6px;"
            f" color:{SLATE_300}; font-size:10px;"
        )

    def _guardar_empresa(self):
        set_config('empresa_nombre', self._inp_emp_nombre.text().strip())
        set_config('empresa_ruc', self._inp_emp_ruc.text().strip())
        set_config('empresa_direccion', self._inp_emp_direccion.text().strip())
        set_config('empresa_telefono', self._inp_emp_telefono.text().strip())
        # Sincronizar con formato de reportes
        from core import pdf_reports
        fmt = pdf_reports.get_formato()
        nombre = self._inp_emp_nombre.text().strip()
        if nombre:
            fmt['rep_empresa_nombre'] = nombre
        logo_b64 = get_config('empresa_logo_b64', '')
        if logo_b64:
            fmt['rep_logo_b64'] = logo_b64
        pdf_reports.set_formato(fmt)
        self._lbl_emp_estado.setText("✓  Datos de empresa guardados")

    # ── Card jornada laboral ─────────────────────────────────────────────

    def _card_jornada(self) -> QFrame:
        from utils.theme import apply_shadow
        from utils.i18n import tr
        card = QFrame()
        card.setObjectName("cfgCard")
        card.setAttribute(Qt.WA_StyledBackground, True)
        card.setStyleSheet(_CARD_SS)
        vl = QVBoxLayout(card)
        vl.setContentsMargins(24, 20, 24, 24)
        vl.setSpacing(12)

        lbl = QLabel(tr("Jornada laboral por defecto"))
        lbl.setStyleSheet(_SEC_SS)
        vl.addWidget(lbl)
        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color:{SILVER_300};")
        vl.addWidget(sep)

        nota = QLabel(
            tr("Horas de la jornada laboral para nuevos proyectos.\n"
               "Se usa en el cálculo: cantidad MO = cuadrilla / rendimiento × jornada.")
        )
        nota.setWordWrap(True)
        nota.setStyleSheet(_NOTE_SS)
        vl.addWidget(nota)

        form = QFormLayout()
        form.setSpacing(10)
        self._spin_jornada = QSpinBox()
        self._spin_jornada.setRange(1, 24)
        self._spin_jornada.setValue(int(get_config('jornada_defecto', '8')))
        self._spin_jornada.setSuffix(" horas")
        self._spin_jornada.setMinimumHeight(34)
        self._spin_jornada.setMaximumWidth(120)
        form.addRow(tr("Jornada:"), self._spin_jornada)
        vl.addLayout(form)

        hl = QHBoxLayout()
        hl.addStretch()
        btn = QPushButton(tr("Guardar"))
        btn.setFixedHeight(34)
        btn.setStyleSheet(_BTN_SAVE)
        btn.clicked.connect(self._guardar_jornada)
        hl.addWidget(btn)
        vl.addLayout(hl)

        self._lbl_jornada_estado = QLabel("")
        self._lbl_jornada_estado.setStyleSheet(
            f"color:{GREEN}; font-size:11px; background:transparent; border:none;"
        )
        vl.addWidget(self._lbl_jornada_estado)
        return card

    def _guardar_jornada(self):
        val = self._spin_jornada.value()
        set_config('jornada_defecto', str(val))
        self._lbl_jornada_estado.setText(
            f"✓  Jornada por defecto: {val} horas. Se aplica a proyectos nuevos."
        )

    # ── Card moneda ──────────────────────────────────────────────────────

    def _card_moneda(self) -> QFrame:
        from utils.theme import apply_shadow
        from utils.i18n import tr
        card = QFrame()
        card.setObjectName("cfgCard")
        card.setAttribute(Qt.WA_StyledBackground, True)
        card.setStyleSheet(_CARD_SS)
        vl = QVBoxLayout(card)
        vl.setContentsMargins(24, 20, 24, 24)
        vl.setSpacing(12)

        lbl = QLabel(tr("Moneda por defecto"))
        lbl.setStyleSheet(_SEC_SS)
        vl.addWidget(lbl)
        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color:{SILVER_300};")
        vl.addWidget(sep)

        nota = QLabel(
            tr("Moneda seleccionada automáticamente al crear un proyecto nuevo.")
        )
        nota.setWordWrap(True)
        nota.setStyleSheet(_NOTE_SS)
        vl.addWidget(nota)

        form = QFormLayout()
        form.setSpacing(10)
        self._combo_moneda = QComboBox()
        self._combo_moneda.addItems(list(MONEDAS.keys()))
        actual = get_config('moneda_defecto', 'Soles')
        idx = self._combo_moneda.findText(actual)
        if idx >= 0:
            self._combo_moneda.setCurrentIndex(idx)
        self._combo_moneda.setMinimumHeight(34)
        self._combo_moneda.setMaximumWidth(220)
        form.addRow(tr("Moneda:"), self._combo_moneda)
        vl.addLayout(form)

        hl = QHBoxLayout()
        hl.addStretch()
        btn = QPushButton(tr("Guardar"))
        btn.setFixedHeight(34)
        btn.setStyleSheet(_BTN_SAVE)
        btn.clicked.connect(self._guardar_moneda)
        hl.addWidget(btn)
        vl.addLayout(hl)

        self._lbl_moneda_estado = QLabel("")
        self._lbl_moneda_estado.setStyleSheet(
            f"color:{GREEN}; font-size:11px; background:transparent; border:none;"
        )
        vl.addWidget(self._lbl_moneda_estado)
        return card

    def _guardar_moneda(self):
        moneda = self._combo_moneda.currentText()
        set_config('moneda_defecto', moneda)
        simbolo = MONEDAS[moneda]['simbolo']
        self._lbl_moneda_estado.setText(
            f"✓  Moneda por defecto: {moneda} ({simbolo}). Se aplica a proyectos nuevos."
        )

    # ── Card backups ─────────────────────────────────────────────────────

    def _card_backups(self) -> QFrame:
        from utils.theme import apply_shadow
        from utils.i18n import tr
        from core.backup import info_backups
        card = QFrame()
        card.setObjectName("cfgCard")
        card.setAttribute(Qt.WA_StyledBackground, True)
        card.setStyleSheet(_CARD_SS)
        vl = QVBoxLayout(card)
        vl.setContentsMargins(24, 20, 24, 24)
        vl.setSpacing(12)

        lbl = QLabel(tr("Copias de seguridad"))
        lbl.setStyleSheet(_SEC_SS)
        vl.addWidget(lbl)
        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color:{SILVER_300};")
        vl.addWidget(sep)

        nota = QLabel(
            tr("Se crean automáticamente al iniciar la app (diario) y al cerrarla.\n"
               "Retención: 7 diarios + 10 al cerrar + 10 manuales.")
        )
        nota.setWordWrap(True)
        nota.setStyleSheet(_NOTE_SS)
        vl.addWidget(nota)

        info = info_backups()
        info_frame = QFrame()
        info_frame.setObjectName("cfgEjemplo")
        info_frame.setAttribute(Qt.WA_StyledBackground, True)
        info_frame.setStyleSheet(
            f"QFrame#cfgEjemplo {{ background:{SILVER_100}; border-radius:6px;"
            f" border:1px solid {SILVER_300}; }}"
        )
        info_vl = QVBoxLayout(info_frame)
        info_vl.setContentsMargins(12, 8, 12, 8)
        info_vl.setSpacing(4)

        carpeta = str(info['carpeta'])
        self._lbl_bkp_info = QLabel()
        self._lbl_bkp_info.setStyleSheet(
            f"color:{SLATE_500}; font-size:11px; background:transparent; border:none;"
        )
        self._actualizar_info_backups()
        info_vl.addWidget(self._lbl_bkp_info)

        lbl_path = QLabel(f"Carpeta: {carpeta}")
        lbl_path.setWordWrap(True)
        lbl_path.setStyleSheet(
            f"color:{SLATE_300}; font-size:10px; background:transparent; border:none;"
        )
        info_vl.addWidget(lbl_path)
        vl.addWidget(info_frame)

        hl = QHBoxLayout()
        hl.addStretch()
        btn_bkp = QPushButton(tr("Hacer backup ahora"))
        btn_bkp.setFixedHeight(34)
        btn_bkp.setCursor(Qt.PointingHandCursor)
        btn_bkp.setStyleSheet(_BTN_SAVE)
        btn_bkp.clicked.connect(self._hacer_backup)
        hl.addWidget(btn_bkp)
        vl.addLayout(hl)

        self._lbl_bkp_estado = QLabel("")
        self._lbl_bkp_estado.setStyleSheet(
            f"color:{GREEN}; font-size:11px; background:transparent; border:none;"
        )
        vl.addWidget(self._lbl_bkp_estado)
        return card

    def _actualizar_info_backups(self):
        from core.backup import info_backups
        info = info_backups()
        cantidad = info['cantidad']
        ultimo_dt = info['ultimo_mtime']
        ultimo_str = ultimo_dt.strftime('%Y-%m-%d %H:%M') if ultimo_dt else "—"
        tamano_mb = info['tamano_total'] / (1024 * 1024)
        self._lbl_bkp_info.setText(
            f"Backups: {cantidad}  |  Último: {ultimo_str}  |  "
            f"Tamaño total: {tamano_mb:.1f} MB"
        )

    def _hacer_backup(self):
        from core.backup import crear_backup
        resultado = crear_backup('manual')
        if resultado:
            self._lbl_bkp_estado.setText(f"✓  Backup creado: {resultado.name}")
            self._actualizar_info_backups()
        else:
            self._lbl_bkp_estado.setText("✗  No se pudo crear el backup")
            self._lbl_bkp_estado.setStyleSheet(
                "color:#C6262E; font-size:11px; background:transparent; border:none;"
            )

    # ── Card ruta exportación ────────────────────────────────────────────

    def _card_ruta_exportacion(self) -> QFrame:
        from utils.theme import apply_shadow
        from utils.i18n import tr
        card = QFrame()
        card.setObjectName("cfgCard")
        card.setAttribute(Qt.WA_StyledBackground, True)
        card.setStyleSheet(_CARD_SS)
        vl = QVBoxLayout(card)
        vl.setContentsMargins(24, 20, 24, 24)
        vl.setSpacing(12)

        lbl = QLabel(tr("Ruta de exportación por defecto"))
        lbl.setStyleSheet(_SEC_SS)
        vl.addWidget(lbl)
        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color:{SILVER_300};")
        vl.addWidget(sep)

        nota = QLabel(
            tr("Carpeta donde se guardan los reportes exportados (PDF, Excel, Word).\n"
               "Si está vacío se usa la carpeta de Descargas del sistema.")
        )
        nota.setWordWrap(True)
        nota.setStyleSheet(_NOTE_SS)
        vl.addWidget(nota)

        _INP = (
            f"QLineEdit {{ border:1.5px solid {SILVER_300}; border-radius:6px;"
            f" padding:0 12px; font-size:12px; color:{SLATE_700}; background:white;"
            f" min-height:34px; }}"
            f"QLineEdit:focus {{ border-color:{ORANGE}; }}"
        )

        hl_path = QHBoxLayout()
        hl_path.setSpacing(8)
        self._inp_ruta_export = QLineEdit()
        self._inp_ruta_export.setStyleSheet(_INP)
        self._inp_ruta_export.setPlaceholderText(tr("Carpeta de descargas del sistema"))
        self._inp_ruta_export.setText(get_config('ruta_exportacion', ''))
        self._inp_ruta_export.setReadOnly(True)
        hl_path.addWidget(self._inp_ruta_export, stretch=1)

        btn_browse = QPushButton(tr("Examinar"))
        btn_browse.setFixedHeight(34)
        btn_browse.setCursor(Qt.PointingHandCursor)
        btn_browse.setStyleSheet(
            f"QPushButton {{ background:white; color:{SLATE_700};"
            f" border:1px solid {SILVER_300}; border-radius:6px;"
            f" font-size:12px; padding:0 14px; }}"
            f"QPushButton:hover {{ background:#E8EAED; }}"
        )
        btn_browse.clicked.connect(self._examinar_ruta_export)
        hl_path.addWidget(btn_browse)
        vl.addLayout(hl_path)

        hl = QHBoxLayout()
        hl.addStretch()
        btn_limpiar = QPushButton(tr("Restablecer"))
        btn_limpiar.setFixedHeight(34)
        btn_limpiar.setCursor(Qt.PointingHandCursor)
        btn_limpiar.setStyleSheet(
            f"QPushButton {{ background:white; color:{SLATE_700};"
            f" border:1px solid {SILVER_300}; border-radius:6px;"
            f" font-size:12px; padding:0 14px; }}"
            f"QPushButton:hover {{ background:#E8EAED; }}"
        )
        btn_limpiar.clicked.connect(self._limpiar_ruta_export)
        hl.addWidget(btn_limpiar)
        vl.addLayout(hl)

        self._lbl_ruta_estado = QLabel("")
        self._lbl_ruta_estado.setStyleSheet(
            f"color:{GREEN}; font-size:11px; background:transparent; border:none;"
        )
        vl.addWidget(self._lbl_ruta_estado)
        return card

    def _examinar_ruta_export(self):
        actual = self._inp_ruta_export.text() or os.path.expanduser("~")
        carpeta = QFileDialog.getExistingDirectory(
            self, "Seleccionar carpeta de exportación", actual
        )
        if carpeta:
            self._inp_ruta_export.setText(carpeta)
            set_config('ruta_exportacion', carpeta)
            self._lbl_ruta_estado.setText(f"✓  Ruta guardada: {carpeta}")

    def _limpiar_ruta_export(self):
        self._inp_ruta_export.clear()
        set_config('ruta_exportacion', '')
        self._lbl_ruta_estado.setText("✓  Restablecido a carpeta de Descargas del sistema")

    # ── Card atajos de teclado ───────────────────────────────────────────

    def _card_atajos(self) -> QFrame:
        from utils.theme import apply_shadow
        from utils.i18n import tr
        card = QFrame()
        card.setObjectName("cfgCard")
        card.setAttribute(Qt.WA_StyledBackground, True)
        card.setStyleSheet(_CARD_SS)
        vl = QVBoxLayout(card)
        vl.setContentsMargins(24, 20, 24, 24)
        vl.setSpacing(12)

        lbl = QLabel(tr("Atajos de teclado"))
        lbl.setStyleSheet(_SEC_SS)
        vl.addWidget(lbl)
        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color:{SILVER_300};")
        vl.addWidget(sep)

        nota = QLabel(tr("Atajos disponibles en la vista de proyecto."))
        nota.setWordWrap(True)
        nota.setStyleSheet(_NOTE_SS)
        vl.addWidget(nota)

        _ATAJOS = [
            ("Ctrl+N", tr("Nuevo Proyecto")),
            ("Ctrl+O", tr("Abrir")),
            ("Ctrl+P", tr("Imprimir")),
            ("Ctrl+S", tr("Guardar") + " (notas/memoria)"),
            ("Ctrl+F", tr("Buscar") + " partida"),
            ("F5", tr("Recalcular")),
            ("F2", tr("Editar") + " partida"),
            ("F1", tr("Atajos de teclado")),
            ("Ins", tr("Agregar partida")),
            ("Ctrl+Ins", tr("Agregar título")),
            ("Ctrl+D", tr("Duplicar")),
            ("Del", tr("Eliminar")),
            ("Ctrl+C", tr("Copiar")),
            ("Ctrl+V", tr("Pegar")),
            ("Ctrl+X", tr("Cortar")),
            ("Alt+Up", tr("Subir")),
            ("Alt+Down", tr("Bajar")),
            ("Alt+Right", tr("Bajar nivel")),
            ("Alt+Left", tr("Subir nivel")),
            ("Ctrl+Home", "Ir a primera partida"),
            ("Ctrl+End", "Ir a última partida"),
            ("Esc", "Deseleccionar"),
        ]

        grid = QHBoxLayout()
        grid.setSpacing(24)

        col_size = 8
        for col_start in range(0, len(_ATAJOS), col_size):
            col_vl = QVBoxLayout()
            col_vl.setSpacing(4)
            for key, desc in _ATAJOS[col_start:col_start + col_size]:
                row_hl = QHBoxLayout()
                row_hl.setSpacing(8)
                lbl_key = QLabel(key)
                lbl_key.setFixedWidth(80)
                lbl_key.setStyleSheet(
                    f"color:{SLATE_700}; font-size:11px; font-weight:700;"
                    f" font-family:monospace; background:transparent; border:none;"
                )
                lbl_desc = QLabel(desc)
                lbl_desc.setStyleSheet(
                    f"color:{SLATE_500}; font-size:11px;"
                    f" background:transparent; border:none;"
                )
                row_hl.addWidget(lbl_key)
                row_hl.addWidget(lbl_desc)
                row_hl.addStretch()
                col_vl.addLayout(row_hl)
            grid.addLayout(col_vl)

        grid.addStretch()
        vl.addLayout(grid)
        return card

    # ── Card decimales ────────────────────────────────────────────────────

    def _card_decimales(self) -> QFrame:
        from utils.theme import apply_shadow
        card = QFrame()
        card.setObjectName("cfgCard")
        card.setAttribute(Qt.WA_StyledBackground, True)
        card.setStyleSheet(_CARD_SS)
        vl = QVBoxLayout(card)
        vl.setContentsMargins(24, 20, 24, 24)
        vl.setSpacing(12)

        lbl = QLabel("Precisión decimal")
        lbl.setStyleSheet(_SEC_SS)
        vl.addWidget(lbl)
        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color:{SILVER_300};")
        vl.addWidget(sep)

        nota = QLabel(
            "Define cuántos decimales se usan al calcular y mostrar cada parte "
            "del presupuesto (mismo criterio que S10 «Datos Adicionales»).\n"
            "Montos: precios unitarios, parciales y totales. Metrados: metrado "
            "de la partida y planilla. Cantidades: insumos del ACU.\n"
            "Abre de nuevo el proyecto para ver el cambio aplicado."
        )
        nota.setWordWrap(True)
        nota.setStyleSheet(_NOTE_SS)
        vl.addWidget(nota)

        form = QFormLayout()
        form.setSpacing(10)
        self.spin_dec = QSpinBox()
        self.spin_dec.setRange(0, 6)
        self.spin_dec.setValue(get_decimales_ppto())
        self.spin_dec.setMinimumHeight(34)
        self.spin_dec.setMaximumWidth(80)
        form.addRow("Decimales en montos (PU y parciales):", self.spin_dec)

        self.spin_dec_met = QSpinBox()
        self.spin_dec_met.setRange(0, 6)
        self.spin_dec_met.setValue(get_decimales_metrado())
        self.spin_dec_met.setMinimumHeight(34)
        self.spin_dec_met.setMaximumWidth(80)
        form.addRow("Decimales en metrados:", self.spin_dec_met)

        self.spin_dec_cant = QSpinBox()
        self.spin_dec_cant.setRange(0, 6)
        self.spin_dec_cant.setValue(get_decimales_cant_acu())
        self.spin_dec_cant.setMinimumHeight(34)
        self.spin_dec_cant.setMaximumWidth(80)
        form.addRow("Decimales en cantidades del ACU:", self.spin_dec_cant)
        vl.addLayout(form)

        ej = QFrame()
        ej.setObjectName("cfgEjemplo")
        ej.setAttribute(Qt.WA_StyledBackground, True)
        ej.setStyleSheet(
            f"QFrame#cfgEjemplo {{ background:{SILVER_100}; border-radius:6px; "
            f"  border:1px solid {SILVER_300}; }}"
        )
        ej_vl = QVBoxLayout(ej)
        ej_vl.setContentsMargins(12, 8, 12, 8)
        self.lbl_ej = QLabel()
        self.lbl_ej.setStyleSheet(
            f"color:{SLATE_500}; font-size:11px; "
            f"background:transparent; border:none;"
        )
        ej_vl.addWidget(self.lbl_ej)
        vl.addWidget(ej)
        self.spin_dec.valueChanged.connect(self._actualizar_ejemplo)
        self.spin_dec_met.valueChanged.connect(self._actualizar_ejemplo)
        self.spin_dec_cant.valueChanged.connect(self._actualizar_ejemplo)
        self._actualizar_ejemplo()

        hl = QHBoxLayout()
        hl.addStretch()
        btn = QPushButton("Guardar")
        btn.setFixedHeight(34)
        btn.setStyleSheet(_BTN_SAVE)
        btn.clicked.connect(self._guardar_decimales)
        hl.addWidget(btn)
        vl.addLayout(hl)

        self.lbl_dec_estado = QLabel("")
        self.lbl_dec_estado.setStyleSheet(
            f"color:{GREEN}; font-size:11px; "
            f"background:transparent; border:none;"
        )
        vl.addWidget(self.lbl_dec_estado)
        return card

    # ── Card apariencia ───────────────────────────────────────────────────

    def _card_apariencia(self) -> QFrame:
        from utils.theme import apply_shadow
        card = QFrame()
        card.setObjectName("cfgCard")
        card.setAttribute(Qt.WA_StyledBackground, True)
        card.setStyleSheet(_CARD_SS)
        vl = QVBoxLayout(card)
        vl.setContentsMargins(24, 20, 24, 24)
        vl.setSpacing(12)

        lbl = QLabel("Apariencia")
        lbl.setStyleSheet(_SEC_SS)
        vl.addWidget(lbl)
        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color:{SILVER_300};")
        vl.addWidget(sep)

        nota = QLabel(
            "Ajusta el tamaño del texto para monitores pequeños.\n"
            "El cambio se aplica de inmediato; algunos elementos se ven mejor al reiniciar."
        )
        nota.setWordWrap(True)
        nota.setStyleSheet(_NOTE_SS)
        vl.addWidget(nota)

        _PRESETS = [
            ("Normal",       1.0,  "100% — pantalla estándar"),
            ("Mediano",      1.12, "112% — laptop 14\", cambio sutil"),
            ("Grande",       1.22, "122% — fuentes notablemente mayores"),
            ("Extra grande", 1.35, "135% — máxima legibilidad"),
        ]

        escala_actual = float(get_config('ui_escala', '1.0'))
        self._bg_escala = QButtonGroup(self)
        hl_presets = QHBoxLayout()
        hl_presets.setSpacing(8)

        for nombre, factor, desc in _PRESETS:
            btn = QPushButton(nombre)
            btn.setCheckable(True)
            btn.setFixedHeight(36)
            btn.setToolTip(desc)
            btn.setStyleSheet(
                f"QPushButton {{ background:{SILVER_100}; color:{SLATE_700};"
                f" border:1px solid {SILVER_300}; border-radius:6px;"
                f" font-size:12px; padding:0 12px; }}"
                f"QPushButton:hover {{ background:#E8EAED; }}"
                f"QPushButton:checked {{ background:{ORANGE}; color:white;"
                f" border-color:{ORANGE}; font-weight:600; }}"
            )
            if abs(factor - escala_actual) < 0.05:
                btn.setChecked(True)
            btn.clicked.connect(lambda _ch, f=factor, n=nombre: self._aplicar_escala(f, n))
            self._bg_escala.addButton(btn)
            hl_presets.addWidget(btn)
        vl.addLayout(hl_presets)

        prev = QFrame()
        prev.setObjectName("cfgPrev")
        prev.setAttribute(Qt.WA_StyledBackground, True)
        prev.setStyleSheet(
            f"QFrame#cfgPrev {{ background:{SILVER_100}; border-radius:6px; "
            f"  border:1px solid {SILVER_300}; }}"
        )
        prev_vl = QVBoxLayout(prev)
        prev_vl.setContentsMargins(12, 8, 12, 8)
        self.lbl_preview_escala = QLabel(
            "Vista previa — Partida 01.01  TRABAJOS PRELIMINARES"
        )
        self.lbl_preview_escala.setStyleSheet(
            f"color:{SLATE_500}; background:transparent; border:none;"
        )
        prev_vl.addWidget(self.lbl_preview_escala)
        vl.addWidget(prev)

        self.lbl_escala_estado = QLabel("")
        self.lbl_escala_estado.setStyleSheet(
            f"color:{GREEN}; font-size:11px; "
            f"background:transparent; border:none;"
        )
        vl.addWidget(self.lbl_escala_estado)
        return card

    # ── Acciones ──────────────────────────────────────────────────────────

    def _aplicar_escala(self, factor: float, nombre: str):
        set_config('ui_escala', str(factor))
        pct = int(factor * 100)
        self.lbl_escala_estado.setText(
            f"✓  {nombre} ({pct}%) guardado. "
            "Reinicia la aplicación para aplicar el cambio en todos los paneles."
        )

    # ── Card barra de título ──────────────────────────────────────────────

    def _card_barra_titulo(self) -> QFrame:
        from utils.theme import apply_shadow
        card = QFrame()
        card.setObjectName("cfgCard")
        card.setAttribute(Qt.WA_StyledBackground, True)
        card.setStyleSheet(_CARD_SS)
        vl = QVBoxLayout(card)
        vl.setContentsMargins(24, 20, 24, 24)
        vl.setSpacing(12)

        lbl = QLabel("Barra de título")
        lbl.setStyleSheet(_SEC_SS)
        vl.addWidget(lbl)
        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color:{SILVER_300};")
        vl.addWidget(sep)

        nota = QLabel(
            "Elige cómo quieres ver la barra superior de la ventana.\n"
            "El cambio se aplica al reiniciar la aplicación."
        )
        nota.setWordWrap(True)
        nota.setStyleSheet(_NOTE_SS)
        vl.addWidget(nota)

        actual = get_config('barra_titulo_custom', '0')
        self._bg_barra = QButtonGroup(self)

        hl = QHBoxLayout()
        hl.setSpacing(8)
        for clave, nombre, desc in [
            ('0', "Del sistema (recomendada)",
             "Barra de título nativa del sistema operativo — respeta el "
             "tema de tu entorno. Apariencia más profesional y consistente "
             "con el resto de tus apps."),
            ('1', "Personalizada (oscura)",
             "Barra de título integrada con el diseño de la app — misma "
             "apariencia en Linux, Windows y macOS."),
        ]:
            btn = QPushButton(nombre)
            btn.setCheckable(True)
            btn.setFixedHeight(36)
            btn.setToolTip(desc)
            btn.setStyleSheet(
                f"QPushButton {{ background:{SILVER_100}; color:{SLATE_700};"
                f" border:1px solid {SILVER_300}; border-radius:6px;"
                f" font-size:12px; padding:0 14px; }}"
                f"QPushButton:hover {{ background:#E8EAED; }}"
                f"QPushButton:checked {{ background:{ORANGE}; color:white;"
                f" border-color:{ORANGE}; font-weight:600; }}"
            )
            if str(actual) == clave:
                btn.setChecked(True)
            btn.clicked.connect(lambda _ch, c=clave, n=nombre: self._aplicar_barra(c, n))
            self._bg_barra.addButton(btn)
            hl.addWidget(btn)
        hl.addStretch()
        vl.addLayout(hl)

        self.lbl_barra_estado = QLabel("")
        self.lbl_barra_estado.setStyleSheet(
            f"color:{GREEN}; font-size:11px; background:transparent; border:none;"
        )
        vl.addWidget(self.lbl_barra_estado)
        return card

    def _aplicar_barra(self, clave: str, nombre: str):
        set_config('barra_titulo_custom', clave)
        self.lbl_barra_estado.setText(
            f"✓  {nombre} guardado. Reinicia la aplicación para aplicar el cambio."
        )

    # ── Card asistente Tuxia ──────────────────────────────────────────────

    def _card_tuxia(self) -> QFrame:
        from utils.theme import apply_shadow
        card = QFrame()
        card.setObjectName("cfgCard")
        card.setAttribute(Qt.WA_StyledBackground, True)
        card.setStyleSheet(_CARD_SS)
        vl = QVBoxLayout(card)
        vl.setContentsMargins(24, 20, 24, 24)
        vl.setSpacing(12)

        lbl = QLabel("Asistente Tuxia")
        lbl.setStyleSheet(_SEC_SS)
        vl.addWidget(lbl)
        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color:{SILVER_300};")
        vl.addWidget(sep)

        nota = QLabel(
            "Tuxia es un pingüino flotante que da consejos contextuales, "
            "detecta incoherencias en el presupuesto y recuerda hacer "
            "backups.\n"
            "Si lo activas, aparece en la esquina inferior derecha al abrir "
            "un proyecto. El cambio se aplica al abrir el siguiente proyecto."
        )
        nota.setWordWrap(True)
        nota.setStyleSheet(_NOTE_SS)
        vl.addWidget(nota)

        actual = get_config('mostrar_tuxia', '1')
        self._bg_tuxia = QButtonGroup(self)

        hl = QHBoxLayout()
        hl.setSpacing(8)
        for clave, nombre, desc in [
            ('0', "Ocultar",
             "Interfaz limpia, sin asistente flotante. "
             "Las acciones (chat IA, validador, backups) siguen "
             "disponibles desde la barra de herramientas."),
            ('1', "Mostrar",
             "Activa el pingüino con tips contextuales, validaciones "
             "automáticas y recordatorios de backup."),
        ]:
            btn = QPushButton(nombre)
            btn.setCheckable(True)
            btn.setFixedHeight(36)
            btn.setToolTip(desc)
            btn.setStyleSheet(
                f"QPushButton {{ background:{SILVER_100}; color:{SLATE_700};"
                f" border:1px solid {SILVER_300}; border-radius:6px;"
                f" font-size:12px; padding:0 14px; }}"
                f"QPushButton:hover {{ background:#E8EAED; }}"
                f"QPushButton:checked {{ background:{ORANGE}; color:white;"
                f" border-color:{ORANGE}; font-weight:600; }}"
            )
            if str(actual) == clave:
                btn.setChecked(True)
            btn.clicked.connect(lambda _ch, c=clave, n=nombre: self._aplicar_tuxia(c, n))
            self._bg_tuxia.addButton(btn)
            hl.addWidget(btn)
        hl.addStretch()
        vl.addLayout(hl)

        self.lbl_tuxia_estado = QLabel("")
        self.lbl_tuxia_estado.setStyleSheet(
            f"color:{GREEN}; font-size:11px; background:transparent; border:none;"
        )
        vl.addWidget(self.lbl_tuxia_estado)
        return card

    def _aplicar_tuxia(self, clave: str, nombre: str):
        set_config('mostrar_tuxia', clave)
        self.lbl_tuxia_estado.setText(
            f"✓  Asistente Tuxia: {nombre.lower()}. "
            "El cambio se aplica al abrir el siguiente proyecto."
        )

    # ── Tab Usuarios (solo admin) ───────────────────────────────────────

    def _make_tab_usuarios(self) -> QWidget:
        from utils.theme import apply_shadow
        wrap = QWidget()
        wrap.setStyleSheet(f"background:{SILVER_100};")
        vl_outer = QVBoxLayout(wrap)
        vl_outer.setContentsMargins(0, 18, 0, 24)
        vl_outer.setSpacing(12)

        # Toolbar
        hl_bar = QHBoxLayout()
        hl_bar.setSpacing(8)
        lbl_sec = QLabel("Administrar usuarios")
        lbl_sec.setStyleSheet(_SEC_SS)
        hl_bar.addWidget(lbl_sec)
        hl_bar.addStretch()

        btn_nuevo = QPushButton("+ Nuevo usuario")
        btn_nuevo.setFixedHeight(34)
        btn_nuevo.setCursor(Qt.PointingHandCursor)
        btn_nuevo.setStyleSheet(BTN_PRIMARY_SS)
        btn_nuevo.clicked.connect(self._usr_nuevo)
        hl_bar.addWidget(btn_nuevo)
        vl_outer.addLayout(hl_bar)

        # Tabla
        card = QFrame()
        card.setObjectName("cfgCard")
        card.setAttribute(Qt.WA_StyledBackground, True)
        card.setStyleSheet(_CARD_SS)
        cv = QVBoxLayout(card)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)

        self._usr_table = QTableWidget()
        self._usr_table.setColumnCount(6)
        self._usr_table.setHorizontalHeaderLabels(
            ["Nombre", "Usuario", "Email", "Rol", "Estado", "Creado"]
        )
        self._usr_table.setSelectionBehavior(QTableWidget.SelectRows)
        self._usr_table.setSelectionMode(QTableWidget.SingleSelection)
        self._usr_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._usr_table.setAlternatingRowColors(True)
        self._usr_table.verticalHeader().setVisible(False)
        hh = self._usr_table.horizontalHeader()
        hh.setStretchLastSection(True)
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        for c in (1, 2, 3, 4, 5):
            hh.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self._usr_table.setStyleSheet(
            f"QTableWidget {{ border:none; background:white; gridline-color:#E8EAED;"
            f" font-size:12px; color:{SLATE_700}; }}"
            f"QTableWidget::item {{ padding:6px 10px; }}"
            f"QTableWidget::item:selected {{ background:#E3F2FD; color:{SLATE_700}; }}"
            f"QHeaderView::section {{ background:{SLATE_700}; color:white;"
            f" font-size:11px; font-weight:600; padding:6px 10px;"
            f" border:none; border-right:1px solid {SLATE_500}; }}"
        )
        cv.addWidget(self._usr_table)
        vl_outer.addWidget(card, stretch=1)

        # Botones de acción
        hl_acc = QHBoxLayout()
        hl_acc.setSpacing(8)
        hl_acc.addStretch()

        _BTN_SS = (
            f"QPushButton {{ background:white; color:{SLATE_700};"
            f" border:1px solid {SILVER_300}; border-radius:6px;"
            f" font-size:12px; padding:6px 14px; }}"
            f"QPushButton:hover {{ background:#E8EAED; }}"
            f"QPushButton:disabled {{ color:{SILVER_300}; }}"
        )
        _BTN_RED = (
            f"QPushButton {{ background:white; color:#C6262E;"
            f" border:1px solid #E8A0A4; border-radius:6px;"
            f" font-size:12px; padding:6px 14px; }}"
            f"QPushButton:hover {{ background:#FEF2F2; }}"
            f"QPushButton:disabled {{ color:{SILVER_300}; border-color:{SILVER_300}; }}"
        )

        self._btn_editar = QPushButton("Editar")
        self._btn_editar.setFixedHeight(32)
        self._btn_editar.setCursor(Qt.PointingHandCursor)
        self._btn_editar.setStyleSheet(_BTN_SS)
        self._btn_editar.clicked.connect(self._usr_editar)
        hl_acc.addWidget(self._btn_editar)

        self._btn_password = QPushButton("Cambiar contraseña")
        self._btn_password.setFixedHeight(32)
        self._btn_password.setCursor(Qt.PointingHandCursor)
        self._btn_password.setStyleSheet(_BTN_SS)
        self._btn_password.clicked.connect(self._usr_cambiar_pass)
        hl_acc.addWidget(self._btn_password)

        self._btn_toggle = QPushButton("Activar/Desactivar")
        self._btn_toggle.setFixedHeight(32)
        self._btn_toggle.setCursor(Qt.PointingHandCursor)
        self._btn_toggle.setStyleSheet(_BTN_SS)
        self._btn_toggle.clicked.connect(self._usr_toggle)
        hl_acc.addWidget(self._btn_toggle)

        self._btn_eliminar = QPushButton("Eliminar")
        self._btn_eliminar.setFixedHeight(32)
        self._btn_eliminar.setCursor(Qt.PointingHandCursor)
        self._btn_eliminar.setStyleSheet(_BTN_RED)
        self._btn_eliminar.clicked.connect(self._usr_eliminar)
        hl_acc.addWidget(self._btn_eliminar)

        vl_outer.addLayout(hl_acc)

        self._usr_msg = QLabel("")
        self._usr_msg.setStyleSheet(
            f"color:{GREEN}; font-size:11px; background:transparent; border:none;"
        )
        vl_outer.addWidget(self._usr_msg)

        self._usr_cargar_tabla()
        self._usr_table.selectionModel().selectionChanged.connect(self._usr_sel_changed)
        self._usr_sel_changed()
        return wrap

    def _usr_cargar_tabla(self):
        usuarios = listar_usuarios()
        self._usr_table.setRowCount(len(usuarios))
        for i, u in enumerate(usuarios):
            self._usr_table.setItem(i, 0, QTableWidgetItem(u.nombre))
            self._usr_table.setItem(i, 1, QTableWidgetItem(u.username))
            self._usr_table.setItem(i, 2, QTableWidgetItem(u.email))
            rol_item = QTableWidgetItem(u.rol.capitalize())
            self._usr_table.setItem(i, 3, rol_item)
            estado = "Activo" if u.activo else "Inactivo"
            est_item = QTableWidgetItem(estado)
            if not u.activo:
                est_item.setForeground(Qt.red)
            self._usr_table.setItem(i, 4, est_item)
            fecha = u.creado_en[:10] if u.creado_en else ""
            self._usr_table.setItem(i, 5, QTableWidgetItem(fecha))
            self._usr_table.item(i, 0).setData(Qt.UserRole, u.id)

    def _usr_sel_changed(self):
        tiene = bool(self._usr_table.selectedItems())
        u_actual = usuario_actual()
        uid = self._usr_id_seleccionado()
        es_self = uid == (u_actual.id if u_actual else -1)
        self._btn_editar.setEnabled(tiene)
        self._btn_password.setEnabled(tiene)
        self._btn_toggle.setEnabled(tiene and not es_self)
        self._btn_eliminar.setEnabled(tiene and not es_self)

    def _usr_id_seleccionado(self) -> int | None:
        row = self._usr_table.currentRow()
        if row < 0:
            return None
        item = self._usr_table.item(row, 0)
        return item.data(Qt.UserRole) if item else None

    def _usr_nuevo(self):
        dlg = _UsuarioDialog(self)
        if dlg.exec() == QDialog.Accepted:
            d = dlg.datos()
            ok, msg = crear_admin(
                d['nombre'], d['username'], d['password'],
                email=d['email'], rol=d['rol']
            )
            self._usr_msg.setText(f"{'✓' if ok else '✗'}  {msg}")
            self._usr_msg.setStyleSheet(
                f"color:{'#68B723' if ok else '#C6262E'}; font-size:11px;"
                f" background:transparent; border:none;"
            )
            if ok:
                self._usr_cargar_tabla()

    def _usr_editar(self):
        uid = self._usr_id_seleccionado()
        if not uid:
            return
        usuarios = listar_usuarios()
        usr = next((u for u in usuarios if u.id == uid), None)
        if not usr:
            return
        dlg = _UsuarioDialog(self, usuario=usr)
        if dlg.exec() == QDialog.Accepted:
            d = dlg.datos()
            ok, msg = actualizar_usuario(uid, d['nombre'], d['username'], d['email'], d['rol'])
            self._usr_msg.setText(f"{'✓' if ok else '✗'}  {msg}")
            self._usr_msg.setStyleSheet(
                f"color:{'#68B723' if ok else '#C6262E'}; font-size:11px;"
                f" background:transparent; border:none;"
            )
            if ok:
                self._usr_cargar_tabla()

    def _usr_cambiar_pass(self):
        uid = self._usr_id_seleccionado()
        if not uid:
            return
        dlg = _CambiarPasswordDialog(self)
        if dlg.exec() == QDialog.Accepted:
            ok, msg = cambiar_password(uid, dlg.password())
            self._usr_msg.setText(f"{'✓' if ok else '✗'}  {msg}")
            self._usr_msg.setStyleSheet(
                f"color:{'#68B723' if ok else '#C6262E'}; font-size:11px;"
                f" background:transparent; border:none;"
            )

    def _usr_toggle(self):
        uid = self._usr_id_seleccionado()
        if not uid:
            return
        ok, msg = toggle_activo(uid)
        self._usr_msg.setText(f"{'✓' if ok else '✗'}  {msg}")
        self._usr_msg.setStyleSheet(
            f"color:{'#68B723' if ok else '#C6262E'}; font-size:11px;"
            f" background:transparent; border:none;"
        )
        if ok:
            self._usr_cargar_tabla()

    def _usr_eliminar(self):
        uid = self._usr_id_seleccionado()
        if not uid:
            return
        row = self._usr_table.currentRow()
        nombre = self._usr_table.item(row, 0).text()
        resp = QMessageBox.question(
            self, "Eliminar usuario",
            f"¿Eliminar permanentemente a «{nombre}»?\nEsta acción no se puede deshacer.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if resp != QMessageBox.Yes:
            return
        ok, msg = eliminar_usuario(uid)
        self._usr_msg.setText(f"{'✓' if ok else '✗'}  {msg}")
        self._usr_msg.setStyleSheet(
            f"color:{'#68B723' if ok else '#C6262E'}; font-size:11px;"
            f" background:transparent; border:none;"
        )
        if ok:
            self._usr_cargar_tabla()

    def _actualizar_ejemplo(self, _n: int = 0):
        nm = self.spin_dec.value()
        nt = self.spin_dec_met.value()
        nc = self.spin_dec_cant.value()
        self.lbl_ej.setText(
            f"Ejemplo — monto: {1234.5678:,.{nm}f}   ·   "
            f"metrado: {125.4567:,.{nt}f}   ·   "
            f"cantidad: {0.123456:.{nc}f}"
        )

    def _guardar_decimales(self):
        n_ppto = self.spin_dec.value()
        n_met  = self.spin_dec_met.value()
        n_cant = self.spin_dec_cant.value()
        conn = get_db()
        for clave, val in (('decimales_presupuesto', n_ppto),
                           ('decimales_metrado', n_met),
                           ('decimales_cantidad_acu', n_cant)):
            conn.execute(
                "INSERT OR REPLACE INTO configuracion (clave, valor) VALUES (?, ?)",
                (clave, str(val))
            )
        conn.commit()
        conn.close()
        set_decimales_ppto(n_ppto)
        set_decimales_metrado(n_met)
        set_decimales_cant_acu(n_cant)
        self.lbl_dec_estado.setText(
            f"✓  Guardado: montos {n_ppto} · metrados {n_met} · cantidades {n_cant}. "
            "Abre un proyecto para ver el cambio aplicado."
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Diálogos auxiliares para administración de usuarios
# ═══════════════════════════════════════════════════════════════════════════════

_DLG_INP_SS = (
    f"QLineEdit {{ border:1.5px solid {SILVER_300}; border-radius:6px;"
    f" padding:0 12px; font-size:13px; color:{SLATE_700}; background:white;"
    f" min-height:36px; }}"
    f"QLineEdit:focus {{ border-color:{ORANGE}; }}"
)
_DLG_COMBO_SS = (
    f"QComboBox {{ border:1.5px solid {SILVER_300}; border-radius:6px;"
    f" padding:0 12px; font-size:13px; color:{SLATE_700}; background:white;"
    f" min-height:36px; }}"
    f"QComboBox:focus {{ border-color:{ORANGE}; }}"
    f"QComboBox::drop-down {{ border:none; width:24px; }}"
)
_DLG_LBL_SS = f"color:{SLATE_700}; font-size:12px; background:transparent; border:none;"


class _UsuarioDialog(QDialog):
    """Crear o editar un usuario."""

    def __init__(self, parent=None, usuario=None):
        super().__init__(parent)
        self._usuario = usuario
        self.setWindowTitle("Editar usuario" if usuario else "Nuevo usuario")
        self.setFixedWidth(400)
        self.setWindowModality(Qt.WindowModal)
        self._build_ui()

    def _build_ui(self):
        vl = QVBoxLayout(self)
        vl.setContentsMargins(24, 20, 24, 20)
        vl.setSpacing(10)

        lbl_n = QLabel("Nombre completo")
        lbl_n.setStyleSheet(_DLG_LBL_SS)
        vl.addWidget(lbl_n)
        self._inp_nombre = QLineEdit()
        self._inp_nombre.setStyleSheet(_DLG_INP_SS)
        self._inp_nombre.setPlaceholderText("Nombre y apellidos")
        vl.addWidget(self._inp_nombre)

        lbl_u = QLabel("Usuario")
        lbl_u.setStyleSheet(_DLG_LBL_SS)
        vl.addWidget(lbl_u)
        self._inp_username = QLineEdit()
        self._inp_username.setStyleSheet(_DLG_INP_SS)
        self._inp_username.setPlaceholderText("nombre de usuario")
        vl.addWidget(self._inp_username)

        lbl_e = QLabel("Email")
        lbl_e.setStyleSheet(_DLG_LBL_SS)
        vl.addWidget(lbl_e)
        self._inp_email = QLineEdit()
        self._inp_email.setStyleSheet(_DLG_INP_SS)
        self._inp_email.setPlaceholderText("correo@dominio.com (opcional)")
        vl.addWidget(self._inp_email)

        lbl_r = QLabel("Rol")
        lbl_r.setStyleSheet(_DLG_LBL_SS)
        vl.addWidget(lbl_r)
        self._combo_rol = QComboBox()
        self._combo_rol.setStyleSheet(_DLG_COMBO_SS)
        self._combo_rol.addItems(["admin", "usuario"])
        vl.addWidget(self._combo_rol)

        if not self._usuario:
            lbl_p = QLabel("Contraseña")
            lbl_p.setStyleSheet(_DLG_LBL_SS)
            vl.addWidget(lbl_p)
            self._inp_pass = QLineEdit()
            self._inp_pass.setStyleSheet(_DLG_INP_SS)
            self._inp_pass.setEchoMode(QLineEdit.Password)
            self._inp_pass.setPlaceholderText("mín. 6 caracteres")
            vl.addWidget(self._inp_pass)

            lbl_p2 = QLabel("Confirmar contraseña")
            lbl_p2.setStyleSheet(_DLG_LBL_SS)
            vl.addWidget(lbl_p2)
            self._inp_pass2 = QLineEdit()
            self._inp_pass2.setStyleSheet(_DLG_INP_SS)
            self._inp_pass2.setEchoMode(QLineEdit.Password)
            vl.addWidget(self._inp_pass2)

        self._lbl_err = QLabel("")
        self._lbl_err.setStyleSheet(
            "color:#C6262E; font-size:12px; background:transparent; border:none;"
        )
        self._lbl_err.setAlignment(Qt.AlignCenter)
        vl.addWidget(self._lbl_err)

        hl = QHBoxLayout()
        hl.addStretch()
        btn_cancel = QPushButton("Cancelar")
        btn_cancel.setFixedHeight(34)
        btn_cancel.setStyleSheet(
            f"QPushButton {{ background:white; color:{SLATE_700};"
            f" border:1px solid {SILVER_300}; border-radius:6px;"
            f" font-size:12px; padding:0 16px; }}"
            f"QPushButton:hover {{ background:#E8EAED; }}"
        )
        btn_cancel.clicked.connect(self.reject)
        hl.addWidget(btn_cancel)

        btn_ok = QPushButton("Guardar")
        btn_ok.setFixedHeight(34)
        btn_ok.setStyleSheet(BTN_PRIMARY_SS)
        btn_ok.clicked.connect(self._validar)
        hl.addWidget(btn_ok)
        vl.addLayout(hl)

        if self._usuario:
            self._inp_nombre.setText(self._usuario.nombre)
            self._inp_username.setText(self._usuario.username)
            self._inp_email.setText(self._usuario.email)
            idx = self._combo_rol.findText(self._usuario.rol)
            if idx >= 0:
                self._combo_rol.setCurrentIndex(idx)

    def _validar(self):
        nombre = self._inp_nombre.text().strip()
        username = self._inp_username.text().strip()
        if not nombre or not username:
            self._lbl_err.setText("Nombre y usuario son obligatorios")
            return
        if not self._usuario:
            p1 = self._inp_pass.text()
            p2 = self._inp_pass2.text()
            if not p1:
                self._lbl_err.setText("La contraseña es obligatoria")
                return
            if p1 != p2:
                self._lbl_err.setText("Las contraseñas no coinciden")
                return
            if len(p1) < 6:
                self._lbl_err.setText("Mínimo 6 caracteres")
                return
        self.accept()

    def datos(self) -> dict:
        d = {
            'nombre': self._inp_nombre.text().strip(),
            'username': self._inp_username.text().strip(),
            'email': self._inp_email.text().strip(),
            'rol': self._combo_rol.currentText(),
        }
        if not self._usuario:
            d['password'] = self._inp_pass.text()
        return d


class _CambiarPasswordDialog(QDialog):
    """Diálogo para cambiar contraseña de un usuario."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Cambiar contraseña")
        self.setFixedWidth(360)
        self.setWindowModality(Qt.WindowModal)
        self._build_ui()

    def _build_ui(self):
        vl = QVBoxLayout(self)
        vl.setContentsMargins(24, 20, 24, 20)
        vl.setSpacing(10)

        lbl = QLabel("Nueva contraseña")
        lbl.setStyleSheet(_DLG_LBL_SS)
        vl.addWidget(lbl)
        self._inp_pass = QLineEdit()
        self._inp_pass.setStyleSheet(_DLG_INP_SS)
        self._inp_pass.setEchoMode(QLineEdit.Password)
        self._inp_pass.setPlaceholderText("mín. 6 caracteres")
        vl.addWidget(self._inp_pass)

        lbl2 = QLabel("Confirmar contraseña")
        lbl2.setStyleSheet(_DLG_LBL_SS)
        vl.addWidget(lbl2)
        self._inp_pass2 = QLineEdit()
        self._inp_pass2.setStyleSheet(_DLG_INP_SS)
        self._inp_pass2.setEchoMode(QLineEdit.Password)
        vl.addWidget(self._inp_pass2)

        self._lbl_err = QLabel("")
        self._lbl_err.setStyleSheet(
            "color:#C6262E; font-size:12px; background:transparent; border:none;"
        )
        self._lbl_err.setAlignment(Qt.AlignCenter)
        vl.addWidget(self._lbl_err)

        hl = QHBoxLayout()
        hl.addStretch()
        btn_cancel = QPushButton("Cancelar")
        btn_cancel.setFixedHeight(34)
        btn_cancel.setStyleSheet(
            f"QPushButton {{ background:white; color:{SLATE_700};"
            f" border:1px solid {SILVER_300}; border-radius:6px;"
            f" font-size:12px; padding:0 16px; }}"
            f"QPushButton:hover {{ background:#E8EAED; }}"
        )
        btn_cancel.clicked.connect(self.reject)
        hl.addWidget(btn_cancel)

        btn_ok = QPushButton("Cambiar")
        btn_ok.setFixedHeight(34)
        btn_ok.setStyleSheet(BTN_PRIMARY_SS)
        btn_ok.clicked.connect(self._validar)
        hl.addWidget(btn_ok)
        vl.addLayout(hl)

    def _validar(self):
        p1 = self._inp_pass.text()
        p2 = self._inp_pass2.text()
        if not p1:
            self._lbl_err.setText("Ingresa la nueva contraseña")
            return
        if p1 != p2:
            self._lbl_err.setText("Las contraseñas no coinciden")
            return
        if len(p1) < 6:
            self._lbl_err.setText("Mínimo 6 caracteres")
            return
        self.accept()

    def password(self) -> str:
        return self._inp_pass.text()
