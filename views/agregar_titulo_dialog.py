# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""Diálogo para agregar un título / sección al presupuesto.

2 tabs:
  1. Buscar — títulos existentes en todos los proyectos
  2. Nuevo  — ingreso manual de descripción
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QFrame, QListWidget, QListWidgetItem, QWidget,
    QStackedWidget, QSizePolicy
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QFont

from core.database import get_db

BLUE_500   = "#F37329"
BLUE_700   = "#C0621A"
SLATE_700  = "#273445"
SLATE_500  = "#485A6C"
SLATE_300  = "#667885"
SILVER_100 = "#F8F9FA"
SILVER_300 = "#D4D4D4"
RED_500    = "#C6262E"


# ── Tab bar ───────────────────────────────────────────────────────────────────

class _TabBar(QFrame):
    changed = Signal(int)

    def __init__(self, labels: list[str], parent=None):
        super().__init__(parent)
        self.setFixedHeight(42)
        self.setStyleSheet(f"background:white; border-bottom:1px solid {SILVER_300};")
        self._btns: list[QPushButton] = []
        hl = QHBoxLayout(self)
        hl.setContentsMargins(16, 0, 16, 0)
        hl.setSpacing(0)
        for i, lbl in enumerate(labels):
            btn = QPushButton(lbl)
            btn.setCheckable(True)
            btn.setFixedHeight(42)
            btn.setStyleSheet(
                "QPushButton { border:none; border-bottom:3px solid transparent;"
                f" font-size:13px; color:{SLATE_300}; padding:0 18px; background:transparent; }}"
                f"QPushButton:checked {{ color:{BLUE_700}; border-bottom:3px solid {BLUE_500};"
                " font-weight:700; }"
            )
            btn.clicked.connect(lambda _, idx=i: self.select(idx))
            self._btns.append(btn)
            hl.addWidget(btn)
        hl.addStretch()
        self.select(0)

    def select(self, idx: int):
        for i, b in enumerate(self._btns):
            b.setChecked(i == idx)
        self.changed.emit(idx)


# ── Diálogo principal ─────────────────────────────────────────────────────────

class AgregarTituloDialog(QDialog):
    partidas_agregadas = Signal()

    def __init__(self, proyecto_id: int, usuario,
                 contexto_item: str | None = None,
                 contexto_es_titulo: bool = False,
                 sub_presupuesto_id: int | None = None,
                 parent=None):
        super().__init__(parent)
        self.pid               = proyecto_id
        self.usuario           = usuario
        self._contexto_item    = contexto_item
        self._contexto_es_titulo = contexto_es_titulo
        self._sub_ppto_id      = sub_presupuesto_id

        from utils.i18n import tr
        self._tr = tr
        self.setWindowTitle(tr("Agregar título"))
        self.setMinimumSize(520, 440)
        self.resize(560, 480)
        self.setModal(True)
        self.setStyleSheet("QDialog { background: white; }")

        self._build_ui()
        self._tabs.select(0)

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._make_header())

        self._tabs = _TabBar(["🔍  Buscar", "✎  Nuevo"])
        self._tabs.changed.connect(self._on_tab)
        root.addWidget(self._tabs)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._tab_buscar())
        self._stack.addWidget(self._tab_nuevo())
        root.addWidget(self._stack, stretch=1)

    def _make_header(self) -> QFrame:
        hdr = QFrame()
        hdr.setFixedHeight(44)
        hdr.setStyleSheet(
            f"background:{SLATE_700}; border:none;"
        )
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(20, 0, 16, 0)
        lbl = QLabel(self._tr("Agregar título"))
        lbl.setStyleSheet("color:white; font-size:15px; font-weight:700; border:none;")
        hl.addWidget(lbl, stretch=1)
        btn_x = QPushButton("✕")
        btn_x.setFixedSize(28, 28)
        btn_x.setStyleSheet(
            "QPushButton { background:transparent; color:white; border:none; font-size:16px; }"
            "QPushButton:hover { color:#ffcdd2; }"
        )
        btn_x.clicked.connect(self.reject)
        hl.addWidget(btn_x)
        return hdr

    # ── Tab 1: Buscar ─────────────────────────────────────────────────────────

    def _tab_buscar(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background:white;")
        vl = QVBoxLayout(w)
        vl.setContentsMargins(20, 14, 20, 14)
        vl.setSpacing(10)

        # Buscador
        self.inp_buscar = QLineEdit()
        self.inp_buscar.setPlaceholderText(self._tr("Buscar") + "…")
        self.inp_buscar.setMinimumHeight(36)
        self.inp_buscar.setStyleSheet(
            f"border:1px solid {SILVER_300}; border-radius:8px;"
            f" padding:0 12px; font-size:13px; color:{SLATE_700};"
        )
        self.inp_buscar.textChanged.connect(self._debounce_buscar)
        vl.addWidget(self.inp_buscar)

        # Lista de resultados
        self.lst_titulos = QListWidget()
        self.lst_titulos.setStyleSheet(
            f"QListWidget {{ border:1px solid {SILVER_300}; border-radius:8px;"
            f" font-size:13px; color:{SLATE_700}; background:white; outline:none; }}"
            f"QListWidget::item {{ padding:8px 12px; border-bottom:1px solid #F0F0F0; }}"
            f"QListWidget::item:selected {{ background:#FEF5EB; color:{BLUE_700}; }}"
            f"QListWidget::item:hover {{ background:{SILVER_100}; }}"
        )
        self.lst_titulos.itemDoubleClicked.connect(self._agregar_seleccionado)
        self.lst_titulos.itemSelectionChanged.connect(self._on_seleccion_cambio)
        vl.addWidget(self.lst_titulos, stretch=1)

        # Botón agregar
        hl = QHBoxLayout()
        hl.addStretch()
        self.btn_agregar_bib = QPushButton("  " + self._tr("Agregar"))
        self.btn_agregar_bib.setFixedHeight(36)
        self.btn_agregar_bib.setEnabled(False)
        self.btn_agregar_bib.setStyleSheet(
            f"QPushButton {{ background:{BLUE_500}; color:white; border:none;"
            f" border-radius:8px; font-size:13px; font-weight:700; padding:0 20px; }}"
            f"QPushButton:disabled {{ background:{SILVER_300}; color:white; }}"
            f"QPushButton:hover:enabled {{ background:{BLUE_700}; }}"
        )
        self.btn_agregar_bib.clicked.connect(self._agregar_seleccionado)
        hl.addWidget(self.btn_agregar_bib)
        vl.addLayout(hl)

        self.lbl_b_error = QLabel("")
        self.lbl_b_error.setStyleSheet(f"color:{RED_500}; font-size:11px; border:none;")
        vl.addWidget(self.lbl_b_error)

        self._timer_buscar = QTimer(self)
        self._timer_buscar.setSingleShot(True)
        self._timer_buscar.timeout.connect(self._buscar_titulos)

        self._buscar_titulos()   # carga inicial con todos
        return w

    def _debounce_buscar(self):
        self._timer_buscar.start(250)

    def _buscar_titulos(self):
        from utils.formatting import norm_busqueda
        texto = self.inp_buscar.text().strip()
        self.lst_titulos.clear()
        try:
            conn = get_db()
            conn.create_function("_norm", 1, norm_busqueda)
            if texto:
                rows = conn.execute(
                    """SELECT DISTINCT descripcion FROM partidas
                       WHERE es_titulo=1 AND _norm(descripcion) LIKE ?
                       ORDER BY descripcion LIMIT 200""",
                    (f"%{norm_busqueda(texto)}%",)
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT DISTINCT descripcion FROM partidas
                       WHERE es_titulo=1
                       ORDER BY descripcion LIMIT 200"""
                ).fetchall()
            conn.close()
        except Exception:
            rows = []

        for r in rows:
            item = QListWidgetItem(r[0])
            self.lst_titulos.addItem(item)

        self.btn_agregar_bib.setEnabled(False)

    def _on_seleccion_cambio(self):
        self.btn_agregar_bib.setEnabled(
            len(self.lst_titulos.selectedItems()) > 0
        )

    def _agregar_seleccionado(self):
        items = self.lst_titulos.selectedItems()
        if not items:
            return
        desc = items[0].text().strip()
        self._insertar_titulo(desc)

    # ── Tab 2: Nuevo ──────────────────────────────────────────────────────────

    def _tab_nuevo(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background:white;")
        vl = QVBoxLayout(w)
        vl.setContentsMargins(20, 20, 20, 14)
        vl.setSpacing(12)

        lbl = QLabel(self._tr("Descripción") + " *")
        lbl.setStyleSheet(
            f"color:{SLATE_500}; font-size:12px; font-weight:600; border:none;"
        )
        vl.addWidget(lbl)

        self.inp_n_desc = QLineEdit()
        self.inp_n_desc.setPlaceholderText(self._tr("Descripción"))
        self.inp_n_desc.setMinimumHeight(38)
        self.inp_n_desc.setStyleSheet(
            f"border:1px solid {SILVER_300}; border-radius:8px;"
            f" padding:0 12px; font-size:13px; color:{SLATE_700};"
        )
        self.inp_n_desc.returnPressed.connect(self._agregar_nuevo)
        vl.addWidget(self.inp_n_desc)

        vl.addStretch()

        hl = QHBoxLayout()
        hl.addStretch()
        btn_ag = QPushButton("  " + self._tr("Agregar"))
        btn_ag.setFixedHeight(38)
        btn_ag.setStyleSheet(
            f"QPushButton {{ background:{BLUE_500}; color:white; border:none;"
            f" border-radius:8px; font-size:13px; font-weight:700; padding:0 20px; }}"
            f"QPushButton:hover {{ background:{BLUE_700}; }}"
        )
        btn_ag.clicked.connect(self._agregar_nuevo)
        hl.addWidget(btn_ag)
        vl.addLayout(hl)

        self.lbl_n_error = QLabel("")
        self.lbl_n_error.setStyleSheet(f"color:{RED_500}; font-size:11px; border:none;")
        vl.addWidget(self.lbl_n_error)

        return w

    def _agregar_nuevo(self):
        desc = self.inp_n_desc.text().strip()
        if not desc:
            self.lbl_n_error.setText("La descripción es obligatoria")
            return
        self._insertar_titulo(desc)

    # ── Insertar en BD ────────────────────────────────────────────────────────

    def _insertar_titulo(self, desc: str):
        try:
            conn   = get_db()
            codigo = self._siguiente_item(conn)
            nivel  = len(codigo.split('.'))
            conn.execute(
                """INSERT INTO partidas
                   (proyecto_id, item, descripcion, unidad,
                    metrado, precio_unitario, nivel, es_titulo, rendimiento,
                    sub_presupuesto_id)
                   VALUES (?,?,?,?,0,0,?,1,1,?)""",
                (self.pid, codigo, desc, '', nivel,
                 self._sub_ppto_id)
            )
            conn.commit()
            conn.close()
        except Exception as e:
            lbl = self.lbl_b_error if self._stack.currentIndex() == 0 else self.lbl_n_error
            lbl.setText(f"Error: {e}")
            return
        self.partidas_agregadas.emit()
        self.accept()

    def _siguiente_item(self, conn) -> str:
        existing = {r[0] for r in conn.execute(
            "SELECT item FROM partidas WHERE proyecto_id=?", (self.pid,)
        ).fetchall()}

        ctx      = self._contexto_item
        es_titulo = self._contexto_es_titulo

        if ctx and es_titulo:
            prefijo = ctx
            for n in range(1, 1000):
                candidate = f"{prefijo}.{n:02d}"
                if candidate not in existing:
                    return candidate

        elif ctx and not es_titulo:
            partes = ctx.split('.')
            for n in range(1, 1000):
                partes[-1] = f"{n:02d}"
                candidate  = '.'.join(partes)
                if candidate not in existing:
                    return candidate

        else:
            for n in range(1, 1000):
                candidate = f"{n:02d}"
                if candidate not in existing:
                    return candidate

        return "99"

    def _on_tab(self, idx: int):
        self._stack.setCurrentIndex(idx)
        if idx == 1:
            self.inp_n_desc.setFocus()
        else:
            self.inp_buscar.setFocus()
