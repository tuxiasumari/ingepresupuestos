# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""acerca_view — Acerca de + contacto (≈ acerca_de.html de Flask).

Layout:
    - Columna izquierda: logo + nombre del programa + ficha técnica
    - Columna derecha: formulario de contacto que envía mensajes vía HTTP
      POST a una URL configurable (Formspree / Google Apps Script / propia)

La URL se guarda en ``configuracion.form_url``. Si no está configurada,
el botón Enviar queda deshabilitado y se muestran las instrucciones para
crear un endpoint gratuito en Formspree.
"""
from __future__ import annotations

import json
import urllib.request
import urllib.error
from datetime import datetime

from PySide6.QtCore import Qt, QSize, QThread, Signal
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton,
    QLineEdit, QTextEdit, QComboBox, QMessageBox, QSizePolicy, QStackedWidget,
    QDialog,
)

from core.database import get_config, set_config
from core.config import BASE_DIR
from core.update_manager import CURRENT_VERSION
from utils.icons import icon


# ── Paleta ──
ORANGE       = "#F37329"
ORANGE_DARK  = "#C0621A"
ORANGE_SOFT  = "#FEF5EB"
SLATE_700    = "#273445"
SLATE_500    = "#485A6C"
SLATE_300    = "#667885"
SILVER_100   = "#F8F9FA"
SILVER_200   = "#F0F1F2"
SILVER_300   = "#D4D4D4"
WHITE        = "#FFFFFF"
RED_500      = "#C6262E"
GREEN_500    = "#68B723"
BANANA_500   = "#F9C440"


def _app_info() -> list[tuple[str, str]]:
    """Ficha técnica del programa. Función (no constante) para que la
    versión y licencia se lean siempre actualizadas."""
    return [
        ("Versión",          CURRENT_VERSION),
        ("Desarrollado por", "Ing. Marco Sumari"),
        ("Institución",      "Sumari SAC · Arquitectura + Ingeniería"),
        ("Plataforma",       "Multiplataforma (Linux · Windows · macOS)"),
        ("Backend",          "Python 3 + SQLite 3"),
        ("UI",               "PySide6 (Qt 6)"),
        ("Reportes",         "PDF · Excel · ODS · Word · ODT"),
        ("Licencia",         "Software Libre · GPL-3.0-or-later"),
    ]


# ── Worker para enviar el formulario en background ──
class _SendWorker(QThread):
    finished_ok = Signal()
    failed = Signal(str)

    def __init__(self, url: str, payload: dict, parent=None):
        super().__init__(parent)
        self.url = url
        self.payload = payload

    def run(self):
        try:
            data = json.dumps(self.payload).encode('utf-8')
            from core.update_manager import CURRENT_VERSION
            req = urllib.request.Request(
                self.url, data=data,
                headers={
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                    'User-Agent': f'IngePresupuestos/{CURRENT_VERSION}',
                },
                method='POST'
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                # Si el endpoint devuelve JSON, lo parseamos por si trae error
                ct = resp.headers.get('Content-Type', '')
                body = resp.read()
                if 'json' in ct:
                    try:
                        d = json.loads(body)
                        if isinstance(d, dict) and d.get('error'):
                            self.failed.emit(str(d['error']))
                            return
                    except Exception:
                        pass
            self.finished_ok.emit()
        except urllib.error.HTTPError as e:
            try:
                body = e.read().decode('utf-8', errors='replace')
                d = json.loads(body)
                msg = d.get('error') or f"HTTP {e.code}"
            except Exception:
                msg = f"HTTP {e.code}"
            self.failed.emit(msg)
        except Exception as e:
            self.failed.emit(f"Error de red: {e}")


# ── Diálogo "Apoyar el proyecto" (software libre) ──
class _ApoyarDialog(QDialog):
    """Diálogo de apoyo/donaciones. Muestra QR Yape + CCI + estrella GitHub,
    todo bundleado (funciona sin conexión). Los datos son constantes fáciles
    de editar."""

    YAPE_NUMERO  = "998839090"
    YAPE_TITULAR = "Marco Sum*"   # como lo enmascara Yape al pagar
    CCI          = "0093 1320 7930 5176 8084"
    GITHUB_URL   = "https://github.com/tuxiasumari/ingepresupuestos"
    WEB_APOYAR   = "https://ingepresupuestos.com/apoyar"

    _BTN_SS = (
        f"QPushButton {{ background:{WHITE}; color:{SLATE_700};"
        f" border:1px solid {SILVER_300}; border-radius:6px;"
        f" padding:7px 12px; font-size:12px; font-weight:600; }}"
        f"QPushButton:hover {{ background:{ORANGE_SOFT};"
        f" border-color:{ORANGE}; color:{ORANGE_DARK}; }}"
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Apoyar IngePresupuestos")
        self.setModal(True)
        self.setStyleSheet(f"QDialog {{ background:{WHITE}; }}")
        self._build()

    def _abrir(self, url: str):
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl(url))

    def _build(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 22, 24, 20)
        v.setSpacing(12)

        titulo = QLabel("💛  Apoyar IngePresupuestos")
        f = QFont(); f.setPointSize(14); f.setBold(True)
        titulo.setFont(f)
        titulo.setStyleSheet(
            f"color:{SLATE_700}; background:transparent; border:none;"
        )
        v.addWidget(titulo)

        sub = QLabel(
            "Es <b>software libre y gratuito</b>. Si te ayuda en tu trabajo, "
            "puedes apoyar su desarrollo:"
        )
        sub.setWordWrap(True)
        sub.setStyleSheet(
            f"color:{SLATE_500}; font-size:12px; background:transparent; border:none;"
        )
        v.addWidget(sub)

        # QR Yape + datos
        fila = QHBoxLayout(); fila.setSpacing(16)
        qr = QLabel()
        # OJO: NADA de `padding` en un QLabel con pixmap → Qt recorta la imagen
        # al content-rect (reducido por el padding) hasta que se redimensiona
        # la ventana. Fijar el tamaño del label = tamaño del pixmap evita el
        # recorte y hace que el layout reserve el espacio correcto desde el
        # primer render. El QR de Yape ya trae su propia zona de silencio.
        qr.setStyleSheet("background:white; border:none;")
        qr.setAlignment(Qt.AlignCenter)
        qr_path = BASE_DIR / "resources" / "qr_yape.png"
        if qr_path.exists():
            _pm = QPixmap(str(qr_path)).scaled(
                240, 240, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            qr.setPixmap(_pm)
            qr.setFixedSize(_pm.size())
        fila.addWidget(qr)

        datos = QLabel(
            f"<b style='font-size:13px'>Yape</b><br>"
            f"<span style='font-size:15px;color:{SLATE_700}'>{self.YAPE_NUMERO}</span><br>"
            f"<span style='color:{SLATE_500}'>{self.YAPE_TITULAR}</span>"
        )
        datos.setStyleSheet(
            f"color:{SLATE_700}; background:transparent; border:none;"
        )
        datos.setAlignment(Qt.AlignVCenter)
        fila.addWidget(datos, 1)
        v.addLayout(fila)

        cci = QLabel(
            "<b>Transferencia</b> (CCI Scotiabank — desde cualquier banco):<br>"
            f"<span style='font-family:monospace;font-size:13px'>{self.CCI}</span>"
        )
        cci.setTextInteractionFlags(Qt.TextSelectableByMouse)
        cci.setStyleSheet(
            f"color:{SLATE_700}; font-size:12px; background:transparent; border:none;"
        )
        v.addWidget(cci)

        # Enlaces
        links = QHBoxLayout(); links.setSpacing(8)
        btn_gh = QPushButton("⭐  Estrella en GitHub")
        btn_gh.setCursor(Qt.PointingHandCursor)
        btn_gh.setStyleSheet(self._BTN_SS)
        btn_gh.clicked.connect(lambda: self._abrir(self.GITHUB_URL))
        links.addWidget(btn_gh)
        btn_web = QPushButton("🌐  Donar en línea")
        btn_web.setCursor(Qt.PointingHandCursor)
        btn_web.setStyleSheet(self._BTN_SS)
        btn_web.clicked.connect(lambda: self._abrir(self.WEB_APOYAR))
        links.addWidget(btn_web)
        v.addLayout(links)

        btn_close = QPushButton("Cerrar")
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.setStyleSheet(self._BTN_SS)
        btn_close.clicked.connect(self.accept)
        v.addWidget(btn_close, alignment=Qt.AlignRight)

        # Abrir ya con el tamaño correcto (evita el primer render "apretado").
        self.adjustSize()


# ── Vista principal ──
class AcercaView(QWidget):
    """Acerca de la aplicación + formulario de contacto."""

    volver = Signal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setProperty("vista_nombre", "acerca")
        self._worker: _SendWorker | None = None
        self._build()
        self._cargar_config()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Topbar oscuro ──
        hdr = QFrame()
        hdr.setFixedHeight(44)
        hdr.setStyleSheet(f"background:{SLATE_700};")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(14, 0, 14, 0)
        hl.setSpacing(10)

        title = QLabel("Acerca de")
        title.setStyleSheet(
            "color:white; font-size:13px; font-weight:700; letter-spacing:0.5px;"
            " background:transparent; border:none;"
        )
        hl.addWidget(title)
        hl.addStretch(1)
        root.addWidget(hdr)

        # Contenido con márgenes
        _content = QWidget()
        _cv = QVBoxLayout(_content)
        _cv.setContentsMargins(20, 14, 20, 16)
        _cv.setSpacing(12)

        # Cuerpo: 2 columnas
        body = QHBoxLayout()
        body.setSpacing(12)
        body.setAlignment(Qt.AlignTop)

        body.addWidget(self._build_col_izq(), 4)
        body.addWidget(self._build_col_der(), 6)

        _cv.addLayout(body, 1)
        root.addWidget(_content, 1)

    # ── Columna izquierda: logo + ficha técnica ──
    def _build_col_izq(self) -> QWidget:
        col = QVBoxLayout()
        col.setSpacing(12)

        from utils.theme import apply_shadow

        # Card logo
        card_logo = QFrame()
        card_logo.setObjectName("cardLogo")
        card_logo.setAttribute(Qt.WA_StyledBackground, True)
        card_logo.setStyleSheet(
            f"QFrame#cardLogo {{ background:{WHITE}; "
            f"  border:1px solid {SILVER_300}; border-radius:8px; }}"
        )
        apply_shadow(card_logo, 'sm')
        cv = QVBoxLayout(card_logo)
        cv.setContentsMargins(16, 24, 16, 20)
        cv.setSpacing(8)
        cv.setAlignment(Qt.AlignCenter)

        logo = QLabel()
        logo.setAlignment(Qt.AlignCenter)
        logo.setStyleSheet("background:transparent; border:none;")
        from core.config import get_product_icon_path
        logo_path = get_product_icon_path()
        if logo_path and logo_path.exists():
            pm = QPixmap(str(logo_path)).scaled(
                96, 96, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            logo.setPixmap(pm)
        cv.addWidget(logo)

        nombre = QLabel("IngePresupuestos")
        f = QFont(); f.setPointSize(18); f.setWeight(QFont.Bold)
        nombre.setFont(f)
        nombre.setAlignment(Qt.AlignCenter)
        nombre.setStyleSheet(
            f"color:{SLATE_700}; padding-top:6px; "
            f"background:transparent; border:none;"
        )
        cv.addWidget(nombre)

        sub = QLabel("Software para la elaboración\nde Presupuestos de Obra")
        sub.setAlignment(Qt.AlignCenter)
        sub.setStyleSheet(
            f"color:{SLATE_300}; font-size:12px; "
            f"background:transparent; border:none;"
        )
        cv.addWidget(sub)

        # Card info técnica
        card_info = QFrame()
        card_info.setObjectName("cardInfo")
        card_info.setAttribute(Qt.WA_StyledBackground, True)
        card_info.setStyleSheet(
            f"QFrame#cardInfo {{ background:{WHITE}; "
            f"  border:1px solid {SILVER_300}; border-radius:8px; }}"
        )
        apply_shadow(card_info, 'sm')
        iv = QVBoxLayout(card_info)
        iv.setContentsMargins(0, 0, 0, 0)
        iv.setSpacing(0)

        # Header de la card (tipográfico, sin barra silver)
        hd = QFrame()
        hd.setObjectName("cardInfoHeader")
        hd.setAttribute(Qt.WA_StyledBackground, True)
        hd.setStyleSheet("QFrame#cardInfoHeader { background:transparent; border:none; }")
        hl = QHBoxLayout(hd); hl.setContentsMargins(16, 12, 16, 6); hl.setSpacing(6)
        ihi = QLabel(); ihi.setPixmap(icon("configuracion").pixmap(16, 16))
        ihi.setStyleSheet("background:transparent; border:none;")
        hl.addWidget(ihi)
        hht = QLabel("Información técnica")
        f = QFont(); f.setBold(True)
        hht.setFont(f)
        hht.setStyleSheet(
            f"color:{SLATE_700}; background:transparent; border:none;"
        )
        hl.addWidget(hht)
        hl.addStretch(1)
        iv.addWidget(hd)

        # Tabla de info como filas
        tbl = QFrame()
        tbl.setObjectName("cardInfoTbl")
        tbl.setAttribute(Qt.WA_StyledBackground, True)
        tbl.setStyleSheet("QFrame#cardInfoTbl { background:transparent; border:none; }")
        tv = QVBoxLayout(tbl)
        tv.setContentsMargins(0, 0, 0, 6)
        tv.setSpacing(0)
        for i, (k, v) in enumerate(_app_info()):
            row = QFrame()
            row.setObjectName(f"infoRow{i}")
            row.setAttribute(Qt.WA_StyledBackground, True)
            bg = '#FBFBFC' if i % 2 else WHITE
            row.setStyleSheet(
                f"QFrame#infoRow{i} {{ background:{bg}; border:none; }}"
            )
            rl = QHBoxLayout(row)
            rl.setContentsMargins(16, 7, 16, 7)
            lk = QLabel(k)
            lk.setStyleSheet(
                f"color:{SLATE_300}; font-size:12px; "
                f"background:transparent; border:none;"
            )
            lk.setMinimumWidth(120)
            rl.addWidget(lk)
            lv = QLabel(v)
            lv.setStyleSheet(
                f"color:{SLATE_700}; font-size:12px; font-weight:600; "
                f"background:transparent; border:none;"
            )
            lv.setWordWrap(True)
            rl.addWidget(lv, 1)
            tv.addWidget(row)
        iv.addWidget(tbl)

        col.addWidget(card_logo)
        col.addWidget(card_info)

        # Botón "Buscar actualizaciones" — chequeo manual contra version.json
        btn_update = QPushButton("🔄  Buscar actualizaciones")
        btn_update.setCursor(Qt.PointingHandCursor)
        btn_update.setFixedHeight(36)
        btn_update.setStyleSheet(
            f"QPushButton {{ background:{WHITE}; color:{SLATE_700};"
            f" border:1px solid {SILVER_300}; border-radius:6px;"
            f" padding:6px 14px; font-size:12px; font-weight:600; }}"
            f"QPushButton:hover {{ background:{ORANGE_SOFT};"
            f" border-color:{ORANGE}; color:{ORANGE_DARK}; }}"
        )
        btn_update.clicked.connect(self._buscar_actualizaciones)
        col.addWidget(btn_update)

        # Software libre — botón de apoyo (donaciones) en lugar de licencia
        btn_donar = QPushButton("💛  Apoyar el proyecto")
        btn_donar.setCursor(Qt.PointingHandCursor)
        btn_donar.setFixedHeight(36)
        btn_donar.setStyleSheet(
            f"QPushButton {{ background:{WHITE}; color:{SLATE_700};"
            f" border:1px solid {SILVER_300}; border-radius:6px;"
            f" padding:6px 14px; font-size:12px; font-weight:600; }}"
            f"QPushButton:hover {{ background:{ORANGE_SOFT};"
            f" border-color:{ORANGE}; color:{ORANGE_DARK}; }}"
        )
        btn_donar.clicked.connect(self._apoyar_proyecto)
        col.addWidget(btn_donar)

        lbl_libre = QLabel(
            "Software libre bajo licencia GPL-3.0.\n"
            "© 2026 Marco Sumari · Sumari SAC"
        )
        lbl_libre.setWordWrap(True)
        lbl_libre.setStyleSheet(
            f"color:{SLATE_300}; font-size:10px; padding:4px 4px;"
            f" background:transparent; border:none;"
        )
        col.addWidget(lbl_libre)

        col.addStretch(1)

        wrap = QWidget()
        wrap.setLayout(col)
        return wrap

    def _buscar_actualizaciones(self):
        """Chequeo manual de actualizaciones (no silencioso)."""
        from views.update_dialog import lanzar_check
        lanzar_check(self, silencioso=False)

    def _apoyar_proyecto(self):
        """Muestra el diálogo de apoyo/donaciones (Yape QR + CCI + GitHub)."""
        _ApoyarDialog(self).exec()

    # ── Columna derecha: contacto ──
    def _build_col_der(self) -> QWidget:
        from utils.theme import apply_shadow
        card = QFrame()
        card.setObjectName("cardContacto")
        card.setAttribute(Qt.WA_StyledBackground, True)
        card.setStyleSheet(
            f"QFrame#cardContacto {{ background:{WHITE}; "
            f"  border:1px solid {SILVER_300}; border-radius:8px; }}"
        )
        apply_shadow(card, 'sm')
        v = QVBoxLayout(card)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # Header (tipográfico, sin barra silver)
        hd = QFrame()
        hd.setObjectName("cardContactoHeader")
        hd.setAttribute(Qt.WA_StyledBackground, True)
        hd.setStyleSheet(
            "QFrame#cardContactoHeader { background:transparent; border:none; }"
        )
        hl = QHBoxLayout(hd); hl.setContentsMargins(16, 12, 16, 6); hl.setSpacing(6)
        i_h = QLabel(); i_h.setPixmap(icon("usuario").pixmap(16, 16))
        i_h.setStyleSheet("background:transparent; border:none;")
        hl.addWidget(i_h)
        hht = QLabel("Contacto y sugerencias")
        f = QFont(); f.setBold(True)
        hht.setFont(f)
        hht.setStyleSheet(
            f"color:{SLATE_700}; background:transparent; border:none;"
        )
        hl.addWidget(hht)
        hl.addStretch(1)
        v.addWidget(hd)

        # Body
        body = QFrame()
        bv = QVBoxLayout(body)
        bv.setContentsMargins(16, 14, 16, 14)
        bv.setSpacing(10)

        # URL oculta al usuario — siempre usa el endpoint propio
        self.banner_no_url = QLabel()
        self.banner_no_url.setVisible(False)
        bv.addWidget(self.banner_no_url)
        self.inp_url = QLineEdit()
        self.inp_url.setVisible(False)
        bv.addWidget(self.inp_url)

        # Stack: form | confirmación
        self._stack = QStackedWidget()

        # Página 0 — formulario
        form_widget = QFrame()
        fv = QVBoxLayout(form_widget)
        fv.setContentsMargins(0, 0, 0, 0)
        fv.setSpacing(8)

        lbl_n = QLabel("Nombre  <span style='color:#95A3AB;font-weight:normal'>(opcional)</span>")
        lbl_n.setTextFormat(Qt.RichText)
        lbl_n.setStyleSheet(f"color:{SLATE_700}; font-weight:600; font-size:12px;")
        fv.addWidget(lbl_n)
        self.inp_nombre = QLineEdit()
        self.inp_nombre.setPlaceholderText("Tu nombre")
        fv.addWidget(self.inp_nombre)

        lbl_t = QLabel("Tipo de mensaje")
        lbl_t.setStyleSheet(f"color:{SLATE_700}; font-weight:600; font-size:12px;")
        fv.addWidget(lbl_t)
        self.cmb_tipo = QComboBox()
        self.cmb_tipo.addItems([
            "Sugerencia de mejora",
            "Reporte de error / bug",
            "Consulta técnica",
            "Otro",
        ])
        fv.addWidget(self.cmb_tipo)

        lbl_m = QLabel("Mensaje")
        lbl_m.setStyleSheet(f"color:{SLATE_700}; font-weight:600; font-size:12px;")
        fv.addWidget(lbl_m)
        self.txt_mensaje = QTextEdit()
        self.txt_mensaje.setPlaceholderText(
            "Describe tu sugerencia, el problema encontrado o cualquier "
            "consulta que tengas…"
        )
        self.txt_mensaje.setMinimumHeight(140)
        self.txt_mensaje.setStyleSheet(
            "QTextEdit { background:white; border:1px solid #C5CDD3;"
            " border-radius:6px; padding:6px; font-size:12px; }"
        )
        fv.addWidget(self.txt_mensaje, 1)

        self.lbl_err = QLabel("")
        self.lbl_err.setStyleSheet(
            f"color:{RED_500}; font-size:11px; padding:2px 0;"
        )
        self.lbl_err.setWordWrap(True)
        self.lbl_err.setVisible(False)
        fv.addWidget(self.lbl_err)

        self.btn_enviar = QPushButton("Enviar mensaje")
        self.btn_enviar.setIcon(icon("guardar"))
        self.btn_enviar.setIconSize(QSize(18, 18))
        self.btn_enviar.setCursor(Qt.PointingHandCursor)
        self.btn_enviar.setMinimumHeight(36)
        from utils.theme import BTN_PRIMARY_SS
        self.btn_enviar.setStyleSheet(BTN_PRIMARY_SS)
        self.btn_enviar.clicked.connect(self._enviar)
        fv.addWidget(self.btn_enviar)

        self._stack.addWidget(form_widget)

        # Página 1 — confirmación
        ok_widget = QFrame()
        ok_v = QVBoxLayout(ok_widget)
        ok_v.setContentsMargins(20, 30, 20, 30)
        ok_v.setSpacing(10)
        ok_v.setAlignment(Qt.AlignCenter)
        ico_ok = QLabel()
        ico_ok.setAlignment(Qt.AlignCenter)
        # Punto verde grande
        pix = QPixmap(72, 72)
        pix.fill(Qt.transparent)
        from PySide6.QtGui import QPainter, QBrush, QColor
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QBrush(QColor(GREEN_500)))
        p.setPen(Qt.NoPen)
        p.drawEllipse(0, 0, 72, 72)
        # Tick blanco
        from PySide6.QtGui import QPen
        pen = QPen(QColor("white"), 6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        p.setPen(pen)
        p.drawLine(20, 38, 32, 50)
        p.drawLine(32, 50, 54, 26)
        p.end()
        ico_ok.setPixmap(pix)
        ok_v.addWidget(ico_ok)
        lbl_ok = QLabel("¡Mensaje enviado!")
        lbl_ok.setAlignment(Qt.AlignCenter)
        f2 = QFont(); f2.setPointSize(13); f2.setBold(True)
        lbl_ok.setFont(f2)
        lbl_ok.setStyleSheet(f"color:{SLATE_700};")
        ok_v.addWidget(lbl_ok)
        sub = QLabel("Gracias por tu mensaje. Lo revisaré lo antes posible.")
        sub.setAlignment(Qt.AlignCenter)
        sub.setStyleSheet(f"color:{SLATE_300}; font-size:12px;")
        sub.setWordWrap(True)
        ok_v.addWidget(sub)
        btn_otro = QPushButton("Enviar otro mensaje")
        btn_otro.setCursor(Qt.PointingHandCursor)
        btn_otro.setStyleSheet(
            f"QPushButton {{ background:{WHITE}; color:{SLATE_700};"
            f"  border:1px solid {SILVER_300}; border-radius:6px;"
            f"  padding:6px 18px; }}"
            f"QPushButton:hover {{ background:{ORANGE_SOFT};"
            f"  border-color:{ORANGE}; color:{ORANGE_DARK}; }}"
        )
        btn_otro.clicked.connect(self._reset_form)
        ok_v.addWidget(btn_otro, alignment=Qt.AlignCenter)
        self._stack.addWidget(ok_widget)

        bv.addWidget(self._stack, 1)

        nota_contacto = QLabel(
            "Tu mensaje será enviado al equipo de IngePresupuestos.\n"
            "Si no hay conexión a internet, se abrirá tu correo electrónico."
        )
        nota_contacto.setWordWrap(True)
        nota_contacto.setStyleSheet(
            f"color:{SLATE_300}; font-size:11px; padding:4px 0;"
            f" background:transparent; border:none;"
        )
        bv.addWidget(nota_contacto)

        v.addWidget(body, 1)
        return card

    _DEFAULT_FORM_URL = "https://ingepresupuestos.com/api/contacto"

    # ── Carga / guardado de configuración ──────────────────────────────────
    def _cargar_config(self):
        url = (get_config('form_url', '') or '').strip()
        if not url:
            url = self._DEFAULT_FORM_URL
        self.inp_url.setText(url)
        self._actualizar_estado_form(url)

    def _actualizar_estado_form(self, url: str):
        self.btn_enviar.setEnabled(self._worker is None)

    # ── Envío ──
    def _enviar(self):
        if self._worker is not None:
            return
        url = self.inp_url.text().strip() or self._DEFAULT_FORM_URL
        mensaje = self.txt_mensaje.toPlainText().strip()
        if not mensaje:
            self.lbl_err.setText("Por favor escribe un mensaje antes de enviar.")
            self.lbl_err.setVisible(True)
            self.txt_mensaje.setFocus()
            return
        self.lbl_err.setVisible(False)

        nombre = self.inp_nombre.text().strip() or "(anónimo)"
        tipo = self.cmb_tipo.currentText()
        self._last_payload = {
            "Fecha":   datetime.now().strftime("%d/%m/%Y %H:%M"),
            "Nombre":  nombre,
            "Tipo":    tipo,
            "Mensaje": mensaje,
        }
        self.btn_enviar.setEnabled(False)
        self.btn_enviar.setText("Enviando…")

        self._worker = _SendWorker(url, self._last_payload, self)
        self._worker.finished_ok.connect(self._on_ok)
        self._worker.failed.connect(self._on_fail)
        self._worker.start()

    def _on_ok(self):
        self._worker = None
        self.btn_enviar.setText("Enviar mensaje")
        self.btn_enviar.setEnabled(True)
        self._stack.setCurrentIndex(1)

    def _on_fail(self, msg: str):
        self._worker = None
        self.btn_enviar.setText("Enviar mensaje")
        self.btn_enviar.setEnabled(True)
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        import urllib.parse
        payload = getattr(self, '_last_payload', {})
        subject = f"[IngePresupuestos] {payload.get('Tipo', 'Contacto')}"
        body = (
            f"Nombre: {payload.get('Nombre', '')}\n"
            f"Tipo: {payload.get('Tipo', '')}\n"
            f"Fecha: {payload.get('Fecha', '')}\n\n"
            f"{payload.get('Mensaje', '')}"
        )
        mailto = (
            f"mailto:info@ingepresupuestos.com"
            f"?subject={urllib.parse.quote(subject)}"
            f"&body={urllib.parse.quote(body)}"
        )
        resp = QMessageBox.question(
            self, "Error de envío",
            f"No se pudo enviar el mensaje:\n{msg}\n\n"
            "¿Deseas abrir tu correo electrónico para enviarlo manualmente?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
        )
        if resp == QMessageBox.Yes:
            QDesktopServices.openUrl(QUrl(mailto))

    def _reset_form(self):
        self.inp_nombre.clear()
        self.txt_mensaje.clear()
        self.cmb_tipo.setCurrentIndex(0)
        self.lbl_err.setVisible(False)
        self._stack.setCurrentIndex(0)
