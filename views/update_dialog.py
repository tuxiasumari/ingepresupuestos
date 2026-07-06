# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""Diálogos y helper para el sistema de actualizaciones.

* ``UpdateDialog``   — diálogo bonito con changelog + botón "Descargar ahora".
* ``NoUpdateDialog`` — confirmación cuando ya está al día (solo manual).
* ``lanzar_check``   — helper que corre el chequeo en un QThread y muestra
                       el diálogo apropiado. Pensado para ser invocado tanto
                       desde el botón "Buscar actualizaciones" como desde el
                       startup silencioso.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal, QUrl
from PySide6.QtGui import QFont, QDesktopServices
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QFrame, QMessageBox, QWidget,
)

from core.update_manager import (
    CURRENT_VERSION, CheckResult, chequear_actualizacion,
    can_download, increment_download_count, skip_version,
    get_skipped_version, debe_chequear_silencioso,
    cached_version_info, is_newer, es_msix,
)


# ── Paleta (alineada con el resto de la app) ──────────────────────────────────
ORANGE      = "#F37329"
ORANGE_DARK = "#C0621A"
ORANGE_SOFT = "#FEF5EB"
SLATE_700   = "#273445"
SLATE_500   = "#485A6C"
SLATE_300   = "#667885"
SILVER_50   = "#FBFBFC"
SILVER_100  = "#F8F9FA"
SILVER_300  = "#D4D4D4"
WHITE       = "#FFFFFF"
GREEN_500   = "#68B723"


# ─────────────────────────────────────────────────────────────────────────────
# Diálogo: actualización disponible
# ─────────────────────────────────────────────────────────────────────────────

class UpdateDialog(QDialog):
    """Diálogo elegante para mostrar nueva versión disponible."""

    def __init__(self, result: CheckResult, parent: QWidget | None = None):
        super().__init__(parent)
        self.result = result
        self.setWindowTitle("Actualización disponible")
        self.setMinimumSize(540, 480)
        self.setStyleSheet(
            f"QDialog {{ background:{WHITE}; }}"
            f"QDialog QLabel {{ background:transparent; border:none; }}"
        )
        self._build()

    def _build(self):
        info = self.result.info
        v = QVBoxLayout(self)
        v.setContentsMargins(28, 24, 28, 20)
        v.setSpacing(14)

        # Header — sparkles + título + versión actual
        head = QHBoxLayout()
        head.setSpacing(14)
        ico = QLabel("✨")
        ico.setStyleSheet("font-size:32px;")
        ico.setFixedWidth(40)
        head.addWidget(ico)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title = QLabel(f"Versión {info.version} disponible")
        f = QFont(); f.setPointSize(16); f.setBold(True)
        title.setFont(f)
        title.setStyleSheet(f"color:{SLATE_700};")
        title_col.addWidget(title)

        sub = QLabel(
            f"Estás usando v{CURRENT_VERSION}  ·  Publicada {info.release_date}"
        )
        sub.setStyleSheet(f"color:{SLATE_500}; font-size:11px;")
        title_col.addWidget(sub)
        head.addLayout(title_col, 1)
        v.addLayout(head)

        # Separador
        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color:{SILVER_300};")
        v.addWidget(sep)

        # Changelog
        lbl = QLabel("Novedades en esta versión:")
        lbl.setStyleSheet(f"color:{SLATE_700}; font-weight:600; font-size:12px;")
        v.addWidget(lbl)

        txt = QTextEdit()
        txt.setReadOnly(True)
        txt.setPlainText(info.changelog or "(sin notas de versión)")
        txt.setStyleSheet(
            f"QTextEdit {{ background:{SILVER_50}; color:{SLATE_700};"
            f" border:1px solid {SILVER_300}; border-radius:6px;"
            f" padding:10px; font-size:12px; }}"
        )
        v.addWidget(txt, 1)

        # Warning de trial (si aplica)
        puede, razon = can_download()
        if puede and razon:
            warn = QLabel(razon)
            warn.setStyleSheet(
                f"color:{ORANGE_DARK}; font-size:11px; font-style:italic;"
                f" padding:4px 2px;"
            )
            warn.setWordWrap(True)
            v.addWidget(warn)
        elif not puede:
            warn = QLabel(razon)
            warn.setStyleSheet(
                "color:#C6262E; font-size:11px; padding:6px 10px;"
                f" background:#FFF1F1; border:1px solid #FFD7D7;"
                f" border-radius:6px;"
            )
            warn.setWordWrap(True)
            v.addWidget(warn)

        # Footer con botones
        ftr = QHBoxLayout()
        ftr.setSpacing(8)

        btn_skip = QPushButton("Omitir esta versión")
        btn_skip.setCursor(Qt.PointingHandCursor)
        btn_skip.setStyleSheet(
            f"QPushButton {{ background:transparent; color:{SLATE_500};"
            f" border:none; padding:8px 12px; font-size:11px; }}"
            f"QPushButton:hover {{ color:{SLATE_700}; text-decoration:underline; }}"
        )
        btn_skip.clicked.connect(self._omitir)
        ftr.addWidget(btn_skip)

        ftr.addStretch(1)

        btn_later = QPushButton("Recordarme luego")
        btn_later.setCursor(Qt.PointingHandCursor)
        btn_later.setStyleSheet(
            f"QPushButton {{ background:{WHITE}; color:{SLATE_500};"
            f" border:1px solid {SILVER_300}; border-radius:6px;"
            f" padding:8px 16px; font-size:11px; font-weight:600; }}"
            f"QPushButton:hover {{ border-color:{ORANGE}; color:{ORANGE_DARK}; }}"
        )
        btn_later.clicked.connect(self.reject)
        ftr.addWidget(btn_later)

        btn_dl = QPushButton("⬇  Descargar ahora")
        btn_dl.setCursor(Qt.PointingHandCursor)
        btn_dl.setEnabled(puede)
        from utils.theme import BTN_PRIMARY_SS
        btn_dl.setStyleSheet(BTN_PRIMARY_SS)
        btn_dl.setDefault(True)
        btn_dl.clicked.connect(self._descargar)
        ftr.addWidget(btn_dl)
        v.addLayout(ftr)

    def _omitir(self):
        skip_version(self.result.info.version)
        self.reject()

    def _descargar(self):
        # Doble validación por si la licencia cambió mientras estaba abierto
        puede, razon = can_download()
        if not puede:
            QMessageBox.warning(
                self, "Descarga no disponible",
                f"{razon}\n\nVisita ingepresupuestos.com para adquirir tu licencia."
            )
            return
        increment_download_count()
        QDesktopServices.openUrl(QUrl(self.result.info.download_url))
        self.accept()


# ─────────────────────────────────────────────────────────────────────────────
# Diálogo: ya estás al día
# ─────────────────────────────────────────────────────────────────────────────

class NoUpdateDialog(QDialog):
    """Confirmación visual cuando el check explícito no encuentra updates."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Sin actualizaciones")
        self.setMinimumWidth(360)
        self.setStyleSheet(
            f"QDialog {{ background:{WHITE}; }}"
            f"QDialog QLabel {{ background:transparent; border:none; }}"
        )

        v = QVBoxLayout(self)
        v.setContentsMargins(28, 24, 28, 20)
        v.setSpacing(12)

        ico = QLabel("✓")
        ico.setAlignment(Qt.AlignCenter)
        ico.setStyleSheet(
            f"color:{GREEN_500}; font-size:48px; font-weight:bold;"
        )
        v.addWidget(ico)

        lbl = QLabel(f"Estás usando la última versión\n(v{CURRENT_VERSION})")
        lbl.setAlignment(Qt.AlignCenter)
        fnt = QFont(); fnt.setPointSize(13); fnt.setBold(True)
        lbl.setFont(fnt)
        lbl.setStyleSheet(f"color:{SLATE_700};")
        v.addWidget(lbl)

        btn = QPushButton("Cerrar")
        btn.setCursor(Qt.PointingHandCursor)
        from utils.theme import BTN_PRIMARY_SS
        btn.setStyleSheet(BTN_PRIMARY_SS)
        btn.clicked.connect(self.accept)

        h = QHBoxLayout()
        h.addStretch(1); h.addWidget(btn); h.addStretch(1)
        v.addLayout(h)


# ─────────────────────────────────────────────────────────────────────────────
# Worker thread + launcher
# ─────────────────────────────────────────────────────────────────────────────

class _UpdateCheckThread(QThread):
    """Thread para chequear actualización sin bloquear la UI."""
    terminado = Signal(object)   # CheckResult

    def run(self):
        self.terminado.emit(chequear_actualizacion())


def lanzar_check(parent: QWidget | None, silencioso: bool = False) -> None:
    """Dispara un chequeo de actualización en background.

    Args:
        parent: widget padre para anclar los diálogos.
        silencioso:
            * ``False`` — botón "Buscar actualizaciones": muestra siempre
              algo (diálogo de update / "ya estás al día" / mensaje de error).
            * ``True``  — startup automático: solo muestra el diálogo si hay
              versión nueva Y no fue saltada explícitamente. Errores y "estás
              al día" se ignoran sin molestar al usuario.

    El thread se auto-elimina al terminar (``deleteLater``).
    """
    # Si la app está instalada desde la Microsoft Store (MSIX), las
    # actualizaciones las gestiona la Store: no chequear nuestro version.json.
    if es_msix():
        if not silencioso:
            QMessageBox.information(
                parent, "Actualizaciones",
                "Esta versión se instaló desde la Microsoft Store. "
                "Las actualizaciones se gestionan automáticamente desde la "
                "Store (Biblioteca → Obtener actualizaciones).")
        return

    # Si es silencioso, evitar martillar el servidor: máximo 1 re-fetch / 24 h.
    # Pero el throttle NO debe silenciar el aviso: si ya conocemos (por un check
    # previo) una versión nueva no omitida, la mostramos desde el caché sin red.
    if silencioso and not debe_chequear_silencioso():
        info = cached_version_info()
        if (info and is_newer(info.version)
                and get_skipped_version() != info.version):
            UpdateDialog(CheckResult(info=info, es_nueva=True), parent).exec()
        return

    th = _UpdateCheckThread(parent)

    def _on_resultado(result: CheckResult):
        if result.error:
            if not silencioso:
                QMessageBox.warning(parent, "Actualizaciones", result.error)
            return
        if not result.es_nueva:
            if not silencioso:
                NoUpdateDialog(parent).exec()
            return
        # Hay versión nueva
        if silencioso and get_skipped_version() == result.info.version:
            return
        UpdateDialog(result, parent).exec()

    th.terminado.connect(_on_resultado)
    th.finished.connect(th.deleteLater)
    th.start()
