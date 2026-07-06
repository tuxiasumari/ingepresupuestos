# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""Diálogo de login — diseño fiel a las capturas (sesion.png / sesion2.png).

Muestra un modal centrado con:
  - Cabecera oscura: logo + título
  - Tab "Ingresar" y "Crear cuenta" con línea naranja activa
  - Botón naranja principal
  - Opción "Entrar como invitado"
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QCheckBox, QFrame, QSizePolicy, QStackedWidget
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap, QFont, QColor, QPainter, QBrush, QPen, QPainterPath

from utils.auth import login, hay_usuarios, crear_admin, login_invitado
from core.config import BASE_DIR

# Paleta Elementary OS
NARANJA  = "#F37329"   # Blueberry — acento principal
OSCURO   = "#273445"   # Slate-700 — cabecera
GRIS_BD  = "#D4D4D4"   # Silver-300 — bordes
GRIS_PH  = "#95A3AB"   # Slate-100 — placeholder
TEXTO    = "#273445"   # Slate-700 — texto principal
ERR      = "#C6262E"   # Strawberry — error


# ── Widget de tab personalizado (sin QTabWidget para control total del estilo) ──

class _TabBar(QFrame):
    tab_changed = Signal(int)

    def __init__(self, labels: list[str], parent=None):
        super().__init__(parent)
        self.setFixedHeight(44)
        self.setStyleSheet("background:white; border:none;")
        self._idx = 0
        self._btns: list[QPushButton] = []

        hl = QHBoxLayout(self)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(0)

        for i, label in enumerate(labels):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setFixedHeight(44)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn.setStyleSheet(self._style(False))
            btn.clicked.connect(lambda _, idx=i: self._select(idx))
            hl.addWidget(btn)
            self._btns.append(btn)

        self._select(0)

    def _style(self, active: bool) -> str:
        if active:
            return (
                f"QPushButton {{ color:{NARANJA}; font-size:13px; font-weight:bold;"
                f" border:none; border-bottom:2px solid {NARANJA}; background:white; }}"
            )
        return (
            "QPushButton { color:#6b7a8d; font-size:13px; font-weight:normal;"
            " border:none; border-bottom:2px solid #e0e6ef; background:white; }"
            "QPushButton:hover { color:#333; }"
        )

    def _select(self, idx: int):
        self._idx = idx
        for i, btn in enumerate(self._btns):
            btn.setStyleSheet(self._style(i == idx))
            btn.setChecked(i == idx)
        self.tab_changed.emit(idx)

    def current(self) -> int:
        return self._idx


def _inp(placeholder: str, echo=False) -> QLineEdit:
    w = QLineEdit()
    w.setPlaceholderText(placeholder)
    w.setFixedHeight(42)
    if echo:
        w.setEchoMode(QLineEdit.Password)
    w.setStyleSheet(
        f"QLineEdit {{ border:1.5px solid {GRIS_BD}; border-radius:6px;"
        f" padding:0 12px; font-size:13px; color:{TEXTO}; background:white; }}"
        f"QLineEdit:focus {{ border-color:{NARANJA}; }}"
    )
    return w


def _label(texto: str, bold=False, color=TEXTO, size=13) -> QLabel:
    lbl = QLabel(texto)
    lbl.setStyleSheet(
        f"color:{color}; font-size:{size}px;"
        f" font-weight:{'bold' if bold else 'normal'};"
    )
    return lbl


def _btn_naranja(texto: str) -> QPushButton:
    btn = QPushButton(texto)
    btn.setFixedHeight(46)
    btn.setStyleSheet(
        f"QPushButton {{ background:{NARANJA}; color:white; border:none;"
        f" border-radius:8px; font-size:14px; font-weight:bold; }}"
        f"QPushButton:hover {{ background:#d4560a; }}"
        f"QPushButton:pressed {{ background:#c04c08; }}"
    )
    return btn


class _AdaptiveStack(QStackedWidget):
    """QStackedWidget que reporta sólo el tamaño del widget visible.
    Evita que el diálogo quede con espacio vacío al cambiar de panel."""

    def sizeHint(self):
        w = self.currentWidget()
        return w.sizeHint() if w else super().sizeHint()

    def minimumSizeHint(self):
        w = self.currentWidget()
        return w.minimumSizeHint() if w else super().minimumSizeHint()


# ═══════════════════════════════════════════════════════════════════════════════
class LoginDialog(QDialog):
# ═══════════════════════════════════════════════════════════════════════════════

    login_exitoso = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Iniciar sesión — ingePresupuestos")
        self.setFixedWidth(400)
        self.setModal(True)
        # Sin marco estándar de diálogo; bordes redondeados por stylesheet
        self.setStyleSheet("""
            QDialog {
                background: white;
                border-radius: 12px;
            }
        """)
        self._build_ui()

        # Si no hay usuarios → activar tab "Crear cuenta" automáticamente
        if not hay_usuarios():
            self._tabs._select(1)

    # ── Construcción de UI ────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._make_header())
        root.addWidget(self._make_body())

    def _make_header(self) -> QFrame:
        hdr = QFrame()
        hdr.setFixedHeight(120)
        hdr.setStyleSheet(f"background:{OSCURO}; border-radius:0px;")
        vl = QVBoxLayout(hdr)
        vl.setContentsMargins(0, 18, 0, 14)
        vl.setSpacing(4)
        vl.setAlignment(Qt.AlignCenter)

        # Logo del producto
        from core.config import get_product_icon_path
        icon_path = get_product_icon_path()
        lbl_icon = QLabel()
        lbl_icon.setAlignment(Qt.AlignCenter)
        if icon_path and icon_path.exists():
            pix = QPixmap(str(icon_path)).scaled(
                42, 42, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            lbl_icon.setPixmap(pix)
        else:
            lbl_icon.setText("📋")
            lbl_icon.setStyleSheet("font-size:32px;")
        vl.addWidget(lbl_icon)

        lbl_titulo = QLabel("ingePresupuestos")
        lbl_titulo.setAlignment(Qt.AlignCenter)
        lbl_titulo.setStyleSheet(
            "color:white; font-size:17px; font-weight:bold; background:transparent;"
        )
        vl.addWidget(lbl_titulo)

        lbl_sub = QLabel("Software de Presupuestos de Obra")
        lbl_sub.setAlignment(Qt.AlignCenter)
        lbl_sub.setStyleSheet("color:#8da0b3; font-size:11px; background:transparent;")
        vl.addWidget(lbl_sub)

        return hdr

    def _make_body(self) -> QFrame:
        body = QFrame()
        body.setStyleSheet("background:white;")
        vl = QVBoxLayout(body)
        vl.setContentsMargins(0, 0, 0, 24)
        vl.setSpacing(0)

        # Tabs
        self._tabs = _TabBar(["🔐  Ingresar", "👤  Crear cuenta"])
        self._tabs.tab_changed.connect(self._on_tab)
        vl.addWidget(self._tabs)

        # Stack adaptativo — solo reporta el alto del panel visible
        self._stack = _AdaptiveStack()
        self._stack.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        self._panel_login    = self._make_panel_login()
        self._panel_registro = self._make_panel_registro()
        self._stack.addWidget(self._panel_login)     # índice 0
        self._stack.addWidget(self._panel_registro)  # índice 1
        self._stack.setCurrentIndex(0)
        vl.addWidget(self._stack)

        return body

    # ── Panel Ingresar ────────────────────────────────────────────────────────

    def _make_panel_login(self) -> QFrame:
        p = QFrame()
        p.setStyleSheet("background:white;")
        vl = QVBoxLayout(p)
        vl.setContentsMargins(28, 20, 28, 0)
        vl.setSpacing(10)

        vl.addWidget(_label("Usuario o correo electrónico", size=12))
        self.inp_user = _inp("hombre o correo@dominio.com")
        vl.addWidget(self.inp_user)

        vl.addWidget(_label("Contraseña", size=12))
        self.inp_pass = _inp("••••••••", echo=True)
        self.inp_pass.returnPressed.connect(self._do_login)
        vl.addWidget(self.inp_pass)

        self.chk_recordar = QCheckBox("Mantener sesión iniciada")
        self.chk_recordar.setStyleSheet(f"color:#555; font-size:12px;")
        vl.addWidget(self.chk_recordar)

        self.lbl_err_login = QLabel("")
        self.lbl_err_login.setStyleSheet(f"color:{ERR}; font-size:12px;")
        self.lbl_err_login.setAlignment(Qt.AlignCenter)
        vl.addWidget(self.lbl_err_login)

        btn_ing = _btn_naranja("🔐  Ingresar")
        btn_ing.clicked.connect(self._do_login)
        vl.addWidget(btn_ing)

        # Separador "o continuar sin cuenta"
        sep = self._make_sep("o continuar sin cuenta")
        vl.addWidget(sep)

        btn_inv = QPushButton("👤  Entrar como invitado  (solo lectura)")
        btn_inv.setFixedHeight(40)
        btn_inv.setStyleSheet(
            "QPushButton { border:1.5px solid #d0d8e4; border-radius:8px;"
            " color:#4a5568; font-size:12px; background:white; }"
            "QPushButton:hover { background:#f5f7fa; }"
        )
        btn_inv.clicked.connect(self._do_invitado)
        vl.addWidget(btn_inv)

        vl.addSpacing(4)
        return p

    # ── Panel Crear cuenta ────────────────────────────────────────────────────

    def _make_panel_registro(self) -> QFrame:
        p = QFrame()
        p.setStyleSheet("background:white;")
        vl = QVBoxLayout(p)
        vl.setContentsMargins(28, 20, 28, 0)
        vl.setSpacing(8)

        vl.addWidget(_label("Nombre completo", size=12))
        self.inp_nombre = _inp("Nombre y apellidos")
        vl.addWidget(self.inp_nombre)

        hl = QHBoxLayout()
        hl.setSpacing(4)
        lbl_u = _label("Usuario", size=12)
        lbl_u2 = _label("(para iniciar sesión)", size=11, color="#9aa5b4")
        hl.addWidget(lbl_u)
        hl.addWidget(lbl_u2)
        hl.addStretch()
        vl.addLayout(hl)
        self.inp_reg_user = _inp("ej: primer nombre")
        vl.addWidget(self.inp_reg_user)

        vl.addWidget(_label("Correo electrónico", size=12))
        self.inp_email = _inp("correo@dominio.com")
        vl.addWidget(self.inp_email)

        hl2 = QHBoxLayout()
        hl2.setSpacing(4)
        lbl_p = _label("Contraseña", size=12)
        lbl_p2 = _label("(mín. 6 caracteres)", size=11, color="#9aa5b4")
        hl2.addWidget(lbl_p)
        hl2.addWidget(lbl_p2)
        hl2.addStretch()
        vl.addLayout(hl2)
        self.inp_reg_pass = _inp("••••••••", echo=True)
        vl.addWidget(self.inp_reg_pass)

        vl.addWidget(_label("Confirmar contraseña", size=12))
        self.inp_reg_pass2 = _inp("••••••••", echo=True)
        self.inp_reg_pass2.returnPressed.connect(self._do_registro)
        vl.addWidget(self.inp_reg_pass2)

        self.lbl_err_reg = QLabel("")
        self.lbl_err_reg.setStyleSheet(f"color:{ERR}; font-size:12px;")
        self.lbl_err_reg.setAlignment(Qt.AlignCenter)
        vl.addWidget(self.lbl_err_reg)

        btn_reg = _btn_naranja("👤  Crear cuenta e ingresar")
        btn_reg.clicked.connect(self._do_registro)
        vl.addWidget(btn_reg)

        vl.addSpacing(4)
        return p

    # ── Separador con texto ───────────────────────────────────────────────────

    def _make_sep(self, texto: str) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet("background:white;")
        hl = QHBoxLayout(frame)
        hl.setContentsMargins(0, 8, 0, 8)
        hl.setSpacing(8)

        for _ in range(2):
            lin = QFrame()
            lin.setFrameShape(QFrame.HLine)
            lin.setStyleSheet("color:#e0e6ef;")
            hl.addWidget(lin, stretch=1)
            if _ == 0:
                lbl = QLabel(texto)
                lbl.setStyleSheet("color:#9aa5b4; font-size:11px; background:white;")
                hl.addWidget(lbl)

        return frame

    # ── Eventos ───────────────────────────────────────────────────────────────

    def _on_tab(self, idx: int):
        self._stack.setCurrentIndex(idx)
        # Informar al layout que el sizeHint cambió y redibujar el diálogo
        self._stack.updateGeometry()
        self.adjustSize()

    def _do_login(self):
        username = self.inp_user.text().strip()
        password = self.inp_pass.text()
        if not username or not password:
            self.lbl_err_login.setText("Complete usuario y contraseña")
            return
        ok, msg = login(username, password)
        if ok:
            from utils.auth import usuario_actual, guardar_sesion, borrar_sesion
            u = usuario_actual()
            if self.chk_recordar.isChecked():
                guardar_sesion(u)
            else:
                borrar_sesion()   # Si antes tenía sesión guardada, la borra
            self.login_exitoso.emit(u)
            self.accept()
        else:
            self.lbl_err_login.setText(msg)
            self.inp_pass.clear()
            self.inp_pass.setFocus()

    def _do_invitado(self):
        from utils.auth import usuario_actual
        login_invitado()
        self.login_exitoso.emit(usuario_actual())
        self.accept()

    def _do_registro(self):
        nombre  = self.inp_nombre.text().strip()
        usuario = self.inp_reg_user.text().strip()
        email   = self.inp_email.text().strip()
        p1      = self.inp_reg_pass.text()
        p2      = self.inp_reg_pass2.text()

        if not all([nombre, usuario, p1, p2]):
            self.lbl_err_reg.setText("Complete todos los campos obligatorios")
            return
        if p1 != p2:
            self.lbl_err_reg.setText("Las contraseñas no coinciden")
            return
        if len(p1) < 6:
            self.lbl_err_reg.setText("La contraseña debe tener al menos 6 caracteres")
            return

        ok, msg = crear_admin(nombre, usuario, p1, email=email)
        if ok:
            login(usuario, p1)
            from utils.auth import usuario_actual
            self.login_exitoso.emit(usuario_actual())
            self.accept()
        else:
            self.lbl_err_reg.setText(msg)
