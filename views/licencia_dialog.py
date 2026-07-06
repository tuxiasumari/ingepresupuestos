# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""Diálogo de licencia — activación, estado, links de compra.

Dos modos:

* **Activación manual** (desde Acerca de → botón "Activar licencia…")
  ``mostrar_dialogo_licencia(parent)``

* **Bloqueo automático** (cuando ``require_premium`` deniega acceso)
  ``mostrar_bloqueo_premium(parent, feature, lic)``
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QUrl, QSize
from PySide6.QtGui import QDesktopServices, QFont, QPixmap, QGuiApplication
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QTextEdit, QMessageBox, QSizePolicy, QFileDialog,
)

from core import licencia as L
from utils.icons import icon


# Paleta (alineada con acerca_view.py)
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


def _color_estado(lic: L.Licencia) -> str:
    """Devuelve el color hex del badge de estado."""
    if not lic.vigente():
        return RED_500
    if lic.tipo == 'trial':
        dr = lic.dias_restantes() or 0
        if dr <= 3:
            return BANANA_500
        if dr <= 7:
            return ORANGE
        return GREEN_500
    return GREEN_500


class LicenciaDialog(QDialog):
    """Diálogo principal de licencia."""

    def __init__(self, parent=None, *, feature: str | None = None):
        super().__init__(parent)
        self._feature = feature   # para mostrar feature bloqueada en el título
        self._lic = L.cargar()
        self.setWindowTitle("Licencia de IngePresupuestos")
        self.setWindowModality(Qt.WindowModal)
        self.setMinimumSize(560, 540)
        self._build()

    def _build(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 18, 20, 16)
        v.setSpacing(12)

        # ── Header ───────────────────────────────────────────────────────
        h_top = QHBoxLayout()
        h_top.setSpacing(10)
        ico = QLabel()
        ico.setPixmap(icon("acerca").pixmap(28, 28))
        ico.setStyleSheet("background:transparent; border:none;")
        h_top.addWidget(ico)

        if self._feature:
            titulo = "Licencia requerida"
        else:
            titulo = "Licencia"
        lbl_t = QLabel(titulo)
        f = QFont(); f.setPointSize(15); f.setWeight(QFont.DemiBold)
        lbl_t.setFont(f)
        lbl_t.setStyleSheet(f"color:{SLATE_700}; background:transparent; border:none;")
        h_top.addWidget(lbl_t)
        h_top.addStretch(1)
        v.addLayout(h_top)

        # Si vinimos del gate, mostrar qué feature se bloqueó
        if self._feature:
            label = L.FEATURE_LABELS.get(self._feature, self._feature)
            warn = QLabel(
                f"«{label}» requiere una licencia activa.\n"
                f"Tu estado actual: {self._lic.estado_str()}."
            )
            warn.setWordWrap(True)
            warn.setStyleSheet(
                f"background:#FFF7E1; color:#7A5A00; border:1px solid {BANANA_500};"
                f" border-radius:6px; padding:10px 12px; font-size:12px;"
            )
            v.addWidget(warn)

        # ── Card de estado ──────────────────────────────────────────────
        v.addWidget(self._build_card_estado())

        # ── Card de activación ──────────────────────────────────────────
        v.addWidget(self._build_card_activacion(), 1)

        # ── Card de compra ──────────────────────────────────────────────
        v.addWidget(self._build_card_compra())

        # Bottom — Cerrar
        h_bot = QHBoxLayout()
        h_bot.addStretch(1)
        btn_cerrar = QPushButton("Cerrar")
        btn_cerrar.setMinimumHeight(32)
        btn_cerrar.setCursor(Qt.PointingHandCursor)
        btn_cerrar.setStyleSheet(
            f"QPushButton {{ background:{WHITE}; color:{SLATE_700};"
            f" border:1px solid {SILVER_300}; border-radius:6px;"
            f" padding:5px 22px; font-size:12px; }}"
            f"QPushButton:hover {{ background:{SILVER_100}; }}"
        )
        btn_cerrar.clicked.connect(self.accept)
        h_bot.addWidget(btn_cerrar)
        v.addLayout(h_bot)

    # ── Card de estado actual ────────────────────────────────────────────
    def _build_card_estado(self) -> QFrame:
        card = QFrame()
        card.setObjectName("cardEstado")
        card.setAttribute(Qt.WA_StyledBackground, True)
        card.setStyleSheet(
            f"QFrame#cardEstado {{ background:{WHITE};"
            f" border:1px solid {SILVER_300}; border-radius:8px; }}"
        )
        vl = QVBoxLayout(card)
        vl.setContentsMargins(14, 12, 14, 12)
        vl.setSpacing(6)

        # Línea 1: badge + texto estado
        h1 = QHBoxLayout()
        h1.setSpacing(8)
        color = _color_estado(self._lic)
        badge = QLabel(self._lic.tipo.capitalize())
        badge.setStyleSheet(
            f"background:{color}; color:white; padding:2px 10px;"
            f" border-radius:10px; font-size:11px; font-weight:700;"
        )
        h1.addWidget(badge)
        self.lbl_estado = QLabel(self._lic.estado_str())
        self.lbl_estado.setStyleSheet(
            f"color:{SLATE_700}; font-weight:600; background:transparent; border:none;"
        )
        h1.addWidget(self.lbl_estado, 1)
        vl.addLayout(h1)

        # Línea 2: machine_id de esta PC (info clave para el cliente)
        h2 = QHBoxLayout()
        h2.setSpacing(8)
        lbl_mid_lbl = QLabel("ID de esta máquina:")
        lbl_mid_lbl.setStyleSheet(
            f"color:{SLATE_500}; font-size:12px;"
            f" background:transparent; border:none;"
        )
        h2.addWidget(lbl_mid_lbl)
        lbl_mid = QLabel(L.machine_id_pretty())
        lbl_mid.setStyleSheet(
            f"color:{SLATE_700}; font-family:monospace; font-size:12px;"
            f" font-weight:700; background:transparent; border:none;"
            f" padding:1px 8px;"
        )
        lbl_mid.setTextInteractionFlags(Qt.TextSelectableByMouse)
        h2.addWidget(lbl_mid)
        btn_copiar = QPushButton("Copiar")
        btn_copiar.setCursor(Qt.PointingHandCursor)
        btn_copiar.setFixedHeight(24)
        btn_copiar.setStyleSheet(
            f"QPushButton {{ background:{WHITE}; color:{SLATE_700};"
            f" border:1px solid {SILVER_300}; border-radius:4px;"
            f" padding:0 10px; font-size:11px; }}"
            f"QPushButton:hover {{ background:{ORANGE_SOFT};"
            f" border-color:{ORANGE}; color:{ORANGE_DARK}; }}"
        )
        btn_copiar.clicked.connect(self._copiar_machine_id)
        h2.addWidget(btn_copiar)
        h2.addStretch(1)
        vl.addLayout(h2)

        # Línea 3: nombre/email si están
        if self._lic.nombre or self._lic.email:
            lbl_ne = QLabel(
                f"Titular: <b>{self._lic.nombre or '—'}</b>  ·  "
                f"{self._lic.email or '—'}"
            )
            lbl_ne.setTextFormat(Qt.RichText)
            lbl_ne.setStyleSheet(
                f"color:{SLATE_500}; font-size:12px;"
                f" background:transparent; border:none;"
            )
            vl.addWidget(lbl_ne)
        return card

    # ── Card de activación ───────────────────────────────────────────────
    def _build_card_activacion(self) -> QFrame:
        card = QFrame()
        card.setObjectName("cardActivacion")
        card.setAttribute(Qt.WA_StyledBackground, True)
        card.setStyleSheet(
            f"QFrame#cardActivacion {{ background:{WHITE};"
            f" border:1px solid {SILVER_300}; border-radius:8px; }}"
        )
        vl = QVBoxLayout(card)
        vl.setContentsMargins(14, 12, 14, 12)
        vl.setSpacing(8)

        hd = QLabel("Activar licencia")
        f = QFont(); f.setBold(True)
        hd.setFont(f)
        hd.setStyleSheet(
            f"color:{SLATE_700}; background:transparent; border:none;"
        )
        vl.addWidget(hd)

        sub = QLabel(
            "Pegá la clave que recibiste por mail/WhatsApp, o seleccioná "
            "el archivo .lic adjunto."
        )
        sub.setWordWrap(True)
        sub.setStyleSheet(
            f"color:{SLATE_500}; font-size:11px;"
            f" background:transparent; border:none;"
        )
        vl.addWidget(sub)

        self.txt_clave = QTextEdit()
        self.txt_clave.setPlaceholderText(
            "Pegá la clave aquí… (ej. eyJlbWFpbCI6...)"
        )
        self.txt_clave.setMinimumHeight(80)
        self.txt_clave.setMaximumHeight(110)
        self.txt_clave.setStyleSheet(
            "QTextEdit { background:white; border:1px solid #C5CDD3;"
            " border-radius:6px; padding:6px; font-family:monospace;"
            " font-size:11px; }"
        )
        vl.addWidget(self.txt_clave)

        # Botones — Cargar .lic / Activar
        h = QHBoxLayout()
        h.setSpacing(8)
        btn_archivo = QPushButton("📂  Cargar archivo .lic…")
        btn_archivo.setCursor(Qt.PointingHandCursor)
        btn_archivo.setMinimumHeight(32)
        btn_archivo.setStyleSheet(
            f"QPushButton {{ background:{WHITE}; color:{SLATE_700};"
            f" border:1px solid {SILVER_300}; border-radius:6px;"
            f" padding:5px 14px; font-size:12px; }}"
            f"QPushButton:hover {{ background:{ORANGE_SOFT};"
            f" border-color:{ORANGE}; color:{ORANGE_DARK}; }}"
        )
        btn_archivo.clicked.connect(self._cargar_archivo)
        h.addWidget(btn_archivo)
        h.addStretch(1)

        btn_activar = QPushButton("Activar")
        btn_activar.setCursor(Qt.PointingHandCursor)
        btn_activar.setMinimumHeight(32)
        from utils.theme import BTN_PRIMARY_SS
        btn_activar.setStyleSheet(BTN_PRIMARY_SS)
        btn_activar.clicked.connect(self._activar)
        h.addWidget(btn_activar)
        vl.addLayout(h)
        return card

    # ── Card de compra ──────────────────────────────────────────────────
    def _build_card_compra(self) -> QFrame:
        card = QFrame()
        card.setObjectName("cardCompra")
        card.setAttribute(Qt.WA_StyledBackground, True)
        card.setStyleSheet(
            f"QFrame#cardCompra {{ background:{SILVER_100};"
            f" border:1px solid {SILVER_300}; border-radius:8px; }}"
        )
        vl = QVBoxLayout(card)
        vl.setContentsMargins(14, 12, 14, 12)
        vl.setSpacing(8)

        hd = QLabel("¿No tienes licencia? Adquirí una")
        f = QFont(); f.setBold(True)
        hd.setFont(f)
        hd.setStyleSheet(
            f"color:{SLATE_700}; background:transparent; border:none;"
        )
        vl.addWidget(hd)

        nota = QLabel(
            "<b>Gratis para siempre:</b> todos los reportes en PDF, "
            "importadores de Delphin / PowerCost / S10, Tuxia con tu API key, "
            "y la app completa.<br>"
            "<b>Licencia desbloquea</b> los reportes editables — Excel, ODS, "
            "Word, ODT y MS Project (.xml)."
        )
        nota.setTextFormat(Qt.RichText)
        nota.setWordWrap(True)
        nota.setStyleSheet(
            f"color:{SLATE_500}; font-size:11px;"
            f" background:transparent; border:none;"
        )
        vl.addWidget(nota)

        # ── Pricing inline ───────────────────────────────────────────────
        h_precios = QHBoxLayout()
        h_precios.setSpacing(8)

        def _card_precio(plan: str, precio: str, sub: str) -> QFrame:
            c = QFrame()
            c.setObjectName("cardPrecio")
            c.setAttribute(Qt.WA_StyledBackground, True)
            c.setStyleSheet(
                f"QFrame#cardPrecio {{ background:{WHITE};"
                f" border:1px solid {SILVER_300}; border-radius:6px; }}"
            )
            cl = QVBoxLayout(c)
            cl.setContentsMargins(10, 8, 10, 8)
            cl.setSpacing(2)
            lbl_plan = QLabel(plan)
            lbl_plan.setStyleSheet(
                f"color:{SLATE_500}; font-size:10px; font-weight:600;"
                f" background:transparent; border:none; text-transform:uppercase;"
            )
            cl.addWidget(lbl_plan)
            lbl_precio = QLabel(precio)
            fp = QFont(); fp.setPointSize(13); fp.setBold(True)
            lbl_precio.setFont(fp)
            lbl_precio.setStyleSheet(
                f"color:{ORANGE_DARK}; background:transparent; border:none;"
            )
            cl.addWidget(lbl_precio)
            lbl_sub = QLabel(sub)
            lbl_sub.setStyleSheet(
                f"color:{SLATE_300}; font-size:10px;"
                f" background:transparent; border:none;"
            )
            cl.addWidget(lbl_sub)
            return c

        h_precios.addWidget(_card_precio(
            "Anual", "USD 30", "1 PC · 1 año de updates"
        ))
        h_precios.addWidget(_card_precio(
            "Perpetua", "USD 150", "1 PC · 2 años de updates"
        ))
        h_precios.addStretch(1)
        vl.addLayout(h_precios)

        h = QHBoxLayout()
        h.setSpacing(8)
        btn_web = QPushButton("🌐  Comprar online")
        btn_web.setCursor(Qt.PointingHandCursor)
        btn_web.setMinimumHeight(32)
        from utils.theme import BTN_PRIMARY_SS
        btn_web.setStyleSheet(BTN_PRIMARY_SS)
        btn_web.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(L.URL_COMPRA))
        )
        h.addWidget(btn_web)

        btn_wa = QPushButton("💬  WhatsApp")
        btn_wa.setCursor(Qt.PointingHandCursor)
        btn_wa.setMinimumHeight(32)
        btn_wa.setStyleSheet(
            f"QPushButton {{ background:{WHITE}; color:{SLATE_700};"
            f" border:1px solid {SILVER_300}; border-radius:6px;"
            f" padding:5px 18px; font-size:12px; }}"
            f"QPushButton:hover {{ background:#E8F5E9;"
            f" border-color:#25D366; color:#128C7E; }}"
        )
        btn_wa.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(L.URL_WHATSAPP))
        )
        h.addWidget(btn_wa)

        btn_mail = QPushButton("✉  Email")
        btn_mail.setCursor(Qt.PointingHandCursor)
        btn_mail.setMinimumHeight(32)
        btn_mail.setStyleSheet(
            f"QPushButton {{ background:{WHITE}; color:{SLATE_700};"
            f" border:1px solid {SILVER_300}; border-radius:6px;"
            f" padding:5px 18px; font-size:12px; }}"
            f"QPushButton:hover {{ background:{ORANGE_SOFT};"
            f" border-color:{ORANGE}; color:{ORANGE_DARK}; }}"
        )
        # mailto con asunto pre-rellenado e ID de máquina
        mailto = (
            f"mailto:{L.EMAIL_CONTACTO}"
            f"?subject=Compra%20de%20licencia%20IngePresupuestos"
            f"&body=Hola%2C%20quiero%20comprar%20una%20licencia.%0A%0A"
            f"Machine%20ID%3A%20{L.machine_id_pretty()}"
        )
        btn_mail.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(mailto))
        )
        h.addWidget(btn_mail)
        h.addStretch(1)
        vl.addLayout(h)
        return card

    # ── Acciones ─────────────────────────────────────────────────────────
    def _copiar_machine_id(self):
        QGuiApplication.clipboard().setText(L.machine_id_pretty())
        self.lbl_estado.setText("ID copiado al portapapeles")

    def _cargar_archivo(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Seleccionar archivo de licencia",
            "", "Archivo de licencia (*.lic);;Todos los archivos (*)"
        )
        if not path:
            return
        try:
            contenido = open(path, 'r', encoding='utf-8').read()
        except OSError as e:
            QMessageBox.warning(self, "Error",
                                  f"No se pudo leer el archivo:\n{e}")
            return
        self.txt_clave.setPlainText(contenido.strip())

    def _activar(self):
        clave = self.txt_clave.toPlainText().strip()
        if not clave:
            QMessageBox.information(
                self, "Activar licencia",
                "Pegá la clave o cargá el archivo .lic primero."
            )
            return
        ok, msg, lic = L.activar_clave(clave)
        if ok:
            QMessageBox.information(self, "Licencia activada", msg)
            self.accept()
        else:
            QMessageBox.critical(self, "No se pudo activar", msg)


# ─────────────────────────────────────────────────────────────────────────────
# API público
# ─────────────────────────────────────────────────────────────────────────────

def mostrar_dialogo_licencia(parent=None) -> int:
    """Abre el diálogo de licencia en modo "estado + activación".
    Llamado desde Acerca de → botón "Activar licencia…"."""
    dlg = LicenciaDialog(parent)
    return dlg.exec()


def mostrar_bloqueo_premium(parent, feature: str, lic: L.Licencia) -> int:
    """Abre el diálogo en modo "Licencia requerida", explicando qué
    feature se intentó usar. Llamado por ``require_premium`` cuando
    deniega acceso."""
    dlg = LicenciaDialog(parent, feature=feature)
    return dlg.exec()
