# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""Diálogos modales de IA para el proyecto: Validador y Asistente.

- `ValidadorDialog`: pasa el proyecto entero por IA y muestra un informe
  priorizado de hallazgos (críticos / advertencias / sugerencias).
- `AsistenteDialog`: chat conversacional con contexto del proyecto completo.

Ambos usan el patrón "modal pero `Qt.WindowModal`" para no desaparecer al
mover la ventana principal en Cinnamon/GNOME.
"""
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QTextEdit, QLineEdit, QScrollArea, QWidget, QSizePolicy,
)

from core.ai_specs import validar_proyecto, chat_proyecto_asistente

SLATE_700  = "#273445"
SLATE_500  = "#485A6C"
SLATE_300  = "#667885"
SILVER_100 = "#F8F9FA"
SILVER_200 = "#EEF0F2"
SILVER_300 = "#D4D4D4"
ORANGE     = "#F37329"
ORANGE_DRK = "#C0621A"
ORANGE_SFT = "#FEF5EB"
GREEN      = "#68B723"
RED        = "#C6262E"
WHITE      = "#FFFFFF"


# ── Validador ──────────────────────────────────────────────────────────────

class _WorkerValidar(QThread):
    terminado = Signal(str, str)   # (informe_markdown, error)

    def __init__(self, proyecto_id: int, parent=None):
        super().__init__(parent)
        self.proyecto_id = proyecto_id

    def run(self):
        informe, err = validar_proyecto(self.proyecto_id)
        self.terminado.emit(informe or '', err or '')


class ValidadorDialog(QDialog):
    """Modal que ejecuta la validación y muestra el informe."""

    def __init__(self, proyecto_id: int, proyecto_nombre: str, parent=None):
        super().__init__(parent)
        self.proyecto_id = proyecto_id
        self.setWindowTitle("Revisor de proyecto con IA")
        self.setWindowModality(Qt.WindowModal)
        self.setWindowFlags(
            Qt.Window | Qt.WindowCloseButtonHint
            | Qt.WindowMinMaxButtonsHint
        )
        self.setMinimumSize(720, 600)
        self.setStyleSheet(f"QDialog {{ background:{SILVER_100}; }}")

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        # Header
        ttl = QLabel("Revisor de proyecto con IA")
        ttl.setStyleSheet(
            f"color:{SLATE_700}; font-size:16px; font-weight:700; "
            f"background:transparent;"
        )
        root.addWidget(ttl)

        sub = QLabel(
            f"Proyecto: <b>{proyecto_nombre}</b> &nbsp;·&nbsp; "
            f"La IA buscará inconsistencias, faltantes y oportunidades de mejora."
        )
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color:{SLATE_300}; font-size:12px;")
        root.addWidget(sub)

        # Card con el informe
        card = QFrame()
        card.setObjectName("validadorCard")
        card.setAttribute(Qt.WA_StyledBackground, True)
        card.setStyleSheet(
            f"QFrame#validadorCard {{ background:{WHITE}; "
            f"  border:1px solid {SILVER_300}; border-radius:10px; }}"
        )
        cv = QVBoxLayout(card)
        cv.setContentsMargins(16, 14, 16, 14)
        cv.setSpacing(8)

        self.lbl_estado = QLabel("Analizando proyecto con IA…")
        self.lbl_estado.setStyleSheet(
            f"color:{SLATE_500}; font-size:12px; background:transparent;"
        )
        cv.addWidget(self.lbl_estado)

        self.txt_informe = QTextEdit()
        self.txt_informe.setReadOnly(True)
        self.txt_informe.setStyleSheet(
            f"QTextEdit {{ border:none; background:transparent; "
            f"  color:{SLATE_700}; font-size:13px; }}"
        )
        # Permitir cierto estilo: el markdown se renderiza vía setMarkdown()
        cv.addWidget(self.txt_informe, 1)

        root.addWidget(card, 1)

        # Barra de acciones
        hl = QHBoxLayout()
        hl.setSpacing(8)
        self.btn_repetir = QPushButton("Volver a analizar")
        self.btn_repetir.setCursor(Qt.PointingHandCursor)
        self.btn_repetir.setFixedHeight(34)
        self.btn_repetir.setEnabled(False)
        self.btn_repetir.setStyleSheet(
            f"QPushButton {{ background:{WHITE}; color:{SLATE_700}; "
            f"  border:1px solid {SILVER_300}; border-radius:6px; "
            f"  padding:0 16px; font-size:12px; }}"
            f"QPushButton:hover {{ background:{ORANGE_SFT}; "
            f"  border-color:{ORANGE}; color:{ORANGE_DRK}; }}"
            f"QPushButton:disabled {{ color:#AAAAAA; }}"
        )
        self.btn_repetir.clicked.connect(self._iniciar)
        hl.addWidget(self.btn_repetir)
        hl.addStretch(1)
        btn_close = QPushButton("Cerrar")
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.setFixedHeight(34)
        from utils.theme import BTN_PRIMARY_SS
        btn_close.setStyleSheet(BTN_PRIMARY_SS)
        btn_close.clicked.connect(self.accept)
        hl.addWidget(btn_close)
        root.addLayout(hl)

        self._worker: _WorkerValidar | None = None
        self._iniciar()

    def _iniciar(self):
        self.btn_repetir.setEnabled(False)
        self.lbl_estado.setStyleSheet(
            f"color:{SLATE_500}; font-size:12px; background:transparent;"
        )
        self.lbl_estado.setText(
            "Analizando proyecto con IA — esto puede tomar 10-30 segundos…"
        )
        self.txt_informe.setMarkdown("")
        self._worker = _WorkerValidar(self.proyecto_id, parent=self)
        self._worker.terminado.connect(self._on_terminado)
        self._worker.start()

    def _on_terminado(self, informe: str, err: str):
        self.btn_repetir.setEnabled(True)
        if err:
            self.lbl_estado.setStyleSheet(
                f"color:{RED}; font-size:12px; background:transparent;"
            )
            self.lbl_estado.setText(f"✗  Error: {err}")
            return
        self.lbl_estado.setStyleSheet(
            f"color:{GREEN}; font-size:12px; background:transparent;"
        )
        self.lbl_estado.setText("✓  Informe generado.")
        self.txt_informe.setMarkdown(informe)

    def done(self, code):
        # Si el worker IA sigue corriendo cuando el usuario cierra el
        # diálogo (accept/reject/close), hay que detenerlo antes de que
        # Qt destruya al padre — de lo contrario "QThread: Destroyed
        # while thread is still running" → SIGABRT en el shutdown.
        # done() es el punto único: accept() y reject() pasan por aquí.
        # closeEvent NO se dispara con accept/reject — solo con close().
        self._detener_worker()
        super().done(code)

    def _detener_worker(self):
        w = getattr(self, '_worker', None)
        if w is not None and w.isRunning():
            try:
                w.terminado.disconnect()
            except (TypeError, RuntimeError):
                pass
            w.terminate()
            w.wait(1500)
            self._worker = None


# ── Asistente conversacional global ────────────────────────────────────────

class _WorkerChat(QThread):
    terminado = Signal(str, str)   # (respuesta, error)

    def __init__(self, proyecto_id: int, historial: list, mensaje: str, parent=None):
        super().__init__(parent)
        self.proyecto_id = proyecto_id
        self.historial = historial
        self.mensaje = mensaje

    def run(self):
        respuesta, err = chat_proyecto_asistente(
            self.proyecto_id, self.historial, self.mensaje
        )
        self.terminado.emit(respuesta or '', err or '')


class AsistenteDialog(QDialog):
    """Modal de chat con la IA usando contexto del proyecto completo."""

    def __init__(self, proyecto_id: int, proyecto_nombre: str, parent=None):
        super().__init__(parent)
        self.proyecto_id = proyecto_id
        self.setWindowTitle("Asistente IA del proyecto")
        self.setWindowModality(Qt.WindowModal)
        self.setWindowFlags(
            Qt.Window | Qt.WindowCloseButtonHint
            | Qt.WindowMinMaxButtonsHint
        )
        self.setMinimumSize(680, 600)
        self.setStyleSheet(f"QDialog {{ background:{SILVER_100}; }}")

        self._historial: list[dict] = []
        self._worker: _WorkerChat | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        # Header
        ttl = QLabel("Asistente IA del proyecto")
        ttl.setStyleSheet(
            f"color:{SLATE_700}; font-size:16px; font-weight:700; "
            f"background:transparent;"
        )
        root.addWidget(ttl)

        sub = QLabel(
            f"Proyecto: <b>{proyecto_nombre}</b> &nbsp;·&nbsp; "
            f"Pregunta lo que necesites sobre presupuesto, partidas, insumos."
        )
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color:{SLATE_300}; font-size:12px;")
        root.addWidget(sub)

        # Card con historial de chat
        card = QFrame()
        card.setObjectName("chatCard")
        card.setAttribute(Qt.WA_StyledBackground, True)
        card.setStyleSheet(
            f"QFrame#chatCard {{ background:{WHITE}; "
            f"  border:1px solid {SILVER_300}; border-radius:10px; }}"
        )
        cv = QVBoxLayout(card)
        cv.setContentsMargins(6, 6, 6, 6)
        cv.setSpacing(0)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setStyleSheet("QScrollArea { background:transparent; }")

        self.inner = QWidget()
        self.inner.setStyleSheet(f"background:{WHITE};")
        self.lay = QVBoxLayout(self.inner)
        self.lay.setContentsMargins(12, 12, 12, 12)
        self.lay.setSpacing(10)
        self.lay.addStretch(1)
        self.scroll.setWidget(self.inner)
        cv.addWidget(self.scroll)
        root.addWidget(card, 1)

        # Sugerencias rápidas
        sug = QHBoxLayout()
        sug.setSpacing(6)
        for txt in (
            "¿Cuál es la partida más cara?",
            "Resumen de insumos críticos",
            "¿Dónde puedo optimizar costos?",
        ):
            b = QPushButton(txt)
            b.setCursor(Qt.PointingHandCursor)
            b.setFixedHeight(28)
            b.setStyleSheet(
                f"QPushButton {{ background:{WHITE}; color:{SLATE_500}; "
                f"  border:1px solid {SILVER_300}; border-radius:14px; "
                f"  padding:0 12px; font-size:11px; }}"
                f"QPushButton:hover {{ background:{ORANGE_SFT}; "
                f"  border-color:{ORANGE}; color:{ORANGE_DRK}; }}"
            )
            b.clicked.connect(lambda _c=False, t=txt: self._enviar_texto(t))
            sug.addWidget(b)
        sug.addStretch(1)
        root.addLayout(sug)

        # Input + Enviar
        hl_in = QHBoxLayout()
        hl_in.setSpacing(8)
        self.inp = QLineEdit()
        self.inp.setPlaceholderText("Escribe tu pregunta y pulsa Enter…")
        self.inp.setFixedHeight(38)
        self.inp.setStyleSheet(
            f"QLineEdit {{ background:{WHITE}; "
            f"  border:1px solid {SILVER_300}; border-radius:8px; "
            f"  padding:0 12px; font-size:13px; }}"
        )
        self.inp.returnPressed.connect(self._on_enviar_clicked)
        hl_in.addWidget(self.inp, 1)

        self.btn_send = QPushButton("Enviar")
        self.btn_send.setCursor(Qt.PointingHandCursor)
        self.btn_send.setFixedHeight(38)
        from utils.theme import BTN_PRIMARY_SS
        self.btn_send.setStyleSheet(BTN_PRIMARY_SS)
        self.btn_send.clicked.connect(self._on_enviar_clicked)
        hl_in.addWidget(self.btn_send)
        root.addLayout(hl_in)

        # Mensaje de bienvenida
        self._burbuja(
            "Hola. Tengo cargado el contexto de tu proyecto. "
            "¿En qué te puedo ayudar?",
            es_usuario=False
        )

    # -- burbujas ------------------------------------------------------------

    def _burbuja(self, texto: str, es_usuario: bool):
        b = QFrame()
        b.setObjectName("bubbleU" if es_usuario else "bubbleA")
        b.setAttribute(Qt.WA_StyledBackground, True)
        if es_usuario:
            ss = (
                f"QFrame#bubbleU {{ background:{ORANGE_SFT}; "
                f"  border:1px solid {ORANGE}; border-radius:10px; }}"
            )
            txt_color = SLATE_700
        else:
            ss = (
                f"QFrame#bubbleA {{ background:{SILVER_100}; "
                f"  border:1px solid {SILVER_300}; border-radius:10px; }}"
            )
            txt_color = SLATE_700
        b.setStyleSheet(ss)
        v = QVBoxLayout(b)
        v.setContentsMargins(12, 8, 12, 10)
        v.setSpacing(2)
        rol = QLabel("Tú" if es_usuario else "Asistente")
        rol.setStyleSheet(
            f"color:{ORANGE_DRK if es_usuario else SLATE_300}; "
            f"font-size:10px; font-weight:700; "
            f"background:transparent; border:none;"
        )
        v.addWidget(rol)
        msg = QLabel(texto)
        msg.setWordWrap(True)
        msg.setTextInteractionFlags(Qt.TextSelectableByMouse)
        msg.setStyleSheet(
            f"color:{txt_color}; font-size:13px; "
            f"background:transparent; border:none;"
        )
        v.addWidget(msg)

        # Insertar antes del stretch final
        self.lay.insertWidget(self.lay.count() - 1, b)
        # Scroll automático al final
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, lambda: self.scroll.verticalScrollBar().setValue(
            self.scroll.verticalScrollBar().maximum()
        ))
        return msg

    def _on_enviar_clicked(self):
        txt = self.inp.text().strip()
        if not txt:
            return
        self._enviar_texto(txt)
        self.inp.clear()

    def _enviar_texto(self, texto: str):
        if self._worker is not None:
            return
        self._burbuja(texto, es_usuario=True)
        self._historial.append({'rol': 'usuario', 'texto': texto})
        self._lbl_pensando = self._burbuja("Pensando…", es_usuario=False)
        self.btn_send.setEnabled(False)
        self.inp.setEnabled(False)

        self._worker = _WorkerChat(
            self.proyecto_id, list(self._historial), texto, parent=self
        )
        self._worker.terminado.connect(self._on_chat_terminado)
        self._worker.start()

    def _on_chat_terminado(self, respuesta: str, err: str):
        self._worker = None
        self.btn_send.setEnabled(True)
        self.inp.setEnabled(True)
        self.inp.setFocus()

        if err:
            self._lbl_pensando.setText(f"✗  Error: {err}")
            self._lbl_pensando.setStyleSheet(
                f"color:{RED}; font-size:13px; "
                f"background:transparent; border:none;"
            )
            return

        self._lbl_pensando.setText(respuesta)
        self._historial.append({'rol': 'asistente', 'texto': respuesta})

    def done(self, code):
        # Mismo problema que ValidadorDialog. done() cubre accept/reject/close.
        w = getattr(self, '_worker', None)
        if w is not None and w.isRunning():
            try:
                w.terminado.disconnect()
            except (TypeError, RuntimeError):
                pass
            w.terminate()
            w.wait(1500)
            self._worker = None
        super().done(code)
