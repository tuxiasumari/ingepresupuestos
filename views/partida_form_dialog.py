# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""Diálogo para crear/editar una partida — equivale a partida_form.html de Flask."""
import sqlite3
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QPushButton, QCheckBox, QComboBox,
    QDoubleSpinBox, QMessageBox, QFrame, QCompleter
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QStandardItemModel, QStandardItem
import re as _re

from core.config import DB_PATH
from core.database import get_db
from models.usuario import Usuario


class PartidaFormDialog(QDialog):
    """Crear o editar una partida de presupuesto."""

    def __init__(self, proyecto_id: int, part_id: int | None,
                 usuario: Usuario, parent=None,
                 es_titulo_default: bool = False):
        super().__init__(parent)
        self.pid              = proyecto_id
        self.part_id          = part_id
        self.usuario          = usuario
        self._es_titulo_def   = es_titulo_default
        self._partida         = self._cargar_partida()
        self._grupos          = self._cargar_grupos()

        if part_id is None:
            titulo_ventana = "Agregar título / sección" if es_titulo_default else "Agregar partida"
        else:
            titulo_ventana = "Editar partida"
        self.setWindowTitle(titulo_ventana)
        self.setMinimumWidth(620)
        self.resize(680, 320)
        self.setModal(True)
        self._build_ui()
        if self._partida:
            self._poblar()
        elif es_titulo_default:
            self.chk_titulo.setChecked(True)
            self._toggle_titulo()

    def _cargar_partida(self) -> dict | None:
        if not self.part_id:
            return None
        conn = get_db()
        row = conn.execute("SELECT * FROM partidas WHERE id=?", (self.part_id,)).fetchone()
        conn.close()
        return dict(row) if row else None

    def _cargar_grupos(self) -> list[str]:
        conn = get_db()
        rows = conn.execute(
            "SELECT DISTINCT grupo FROM partidas WHERE proyecto_id=? AND grupo!='' ORDER BY grupo",
            (self.pid,)
        ).fetchall()
        conn.close()
        return [r['grupo'] for r in rows]

    def _build_ui(self):
        vl = QVBoxLayout(self)
        vl.setContentsMargins(20, 20, 20, 20)
        vl.setSpacing(12)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setSpacing(8)

        # Ítem
        self.inp_item = QLineEdit()
        self.inp_item.setPlaceholderText("Ej: 01.02.03")
        self.inp_item.setMinimumHeight(32)
        form.addRow("Ítem *:", self.inp_item)

        # Descripción + botón cambio de caso
        self.inp_desc = QLineEdit()
        self.inp_desc.setPlaceholderText("Descripción de la partida")
        self.inp_desc.setMinimumHeight(40)
        self.inp_desc.setStyleSheet(
            "QLineEdit { font-size:13px; padding:0 8px; }"
        )
        hl_desc = QHBoxLayout()
        hl_desc.setSpacing(4)
        hl_desc.addWidget(self.inp_desc)
        btn_caso = QPushButton("Aa")
        btn_caso.setFixedSize(34, 40)
        btn_caso.setToolTip("Ciclar: MAYÚSCULAS → minúsculas → Primera Mayúscula")
        btn_caso.setStyleSheet(
            "QPushButton { background:#F0F2F5; border:1px solid #D4D4D4;"
            " border-radius:6px; font-size:12px; font-weight:700; color:#485A6C; }"
            "QPushButton:hover { background:#E0E5EF; }"
        )
        self._caso_idx = 0
        _CASOS = [str.upper, str.lower, str.title]
        def _ciclar_caso():
            txt = self.inp_desc.text()
            if not txt:
                return
            self.inp_desc.setText(_CASOS[self._caso_idx % 3](txt))
            self._caso_idx += 1
        btn_caso.clicked.connect(_ciclar_caso)
        hl_desc.addWidget(btn_caso)
        form.addRow("Descripción *:", hl_desc)

        # Es título
        self.chk_titulo = QCheckBox("Es título de sección (sin metrado ni precio)")
        self.chk_titulo.stateChanged.connect(self._toggle_titulo)
        form.addRow("", self.chk_titulo)

        # Unidad con autocompletado
        self.inp_unidad = QLineEdit()
        self.inp_unidad.setPlaceholderText("m², m³, kg, glb, …")
        self.inp_unidad.setMinimumHeight(32)
        _UNIDADES = [
            "m", "m²", "m³", "ml", "km", "cm", "mm",
            "kg", "tn", "ton", "lb",
            "und", "glb", "pza", "pzas", "jgo", "cjt", "vj", "est",
            "hh", "hm", "h", "hr", "día", "mes", "sem",
            "lt", "l", "gal",
            "bls", "bol",
            "pie²", "pie³", "p2", "p3",
            "ha", "pto", "rll",
        ]
        _comp = QCompleter(sorted(set(_UNIDADES)), self.inp_unidad)
        _comp.setCaseSensitivity(Qt.CaseInsensitive)
        _comp.setFilterMode(Qt.MatchContains)
        _comp.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        _comp.popup().setStyleSheet(
            "QListView { background:white; border:1px solid #D4D4D4;"
            " border-radius:6px; font-size:12px; padding:4px; color:#273445; }"
            "QListView::item { padding:4px 10px; }"
            "QListView::item:selected { background:#FEF5EB; color:#C0621A; }"
        )
        self.inp_unidad.setCompleter(_comp)

        # Auto-convertir "m2"→"m²", "m3"→"m³" al escribir
        _SUP = {'2': '²', '3': '³'}
        def _auto_sup(text):
            m = _re.match(r'^([a-zA-Z/]+)([23])$', text)
            if m:
                nuevo = m.group(1) + _SUP[m.group(2)]
                QTimer.singleShot(0, lambda: (
                    self.inp_unidad.setText(nuevo) or
                    self.inp_unidad.setCursorPosition(len(nuevo))
                ))
        self.inp_unidad.textEdited.connect(_auto_sup)

        form.addRow("Unidad:", self.inp_unidad)

        # Grupo
        self.inp_grupo = QLineEdit()
        self.inp_grupo.setPlaceholderText("Grupo de análisis (opcional)")
        self.inp_grupo.setMinimumHeight(32)
        if self._grupos:
            self.inp_grupo.setCompleter(
                self._make_completer(self._grupos)
            )
        form.addRow("Grupo:", self.inp_grupo)

        vl.addLayout(form)

        # Error
        self.lbl_error = QLabel("")
        self.lbl_error.setStyleSheet("color:#dc3545; font-size:12px;")
        vl.addWidget(self.lbl_error)

        vl.addStretch()

        # Botones
        btns = QHBoxLayout()
        btns.addStretch()
        btn_can = QPushButton("Cancelar")
        btn_can.clicked.connect(self.reject)
        btns.addWidget(btn_can)
        btn_ok = QPushButton("Guardar")
        btn_ok.setStyleSheet(
            "background:#485a6c; color:white; border-radius:6px; padding:6px 20px;"
        )
        btn_ok.clicked.connect(self._guardar)
        btns.addWidget(btn_ok)
        vl.addLayout(btns)

    def _make_completer(self, items):
        from PySide6.QtWidgets import QCompleter
        from PySide6.QtCore import QStringListModel
        c = QCompleter(items, self)
        c.setCaseSensitivity(Qt.CaseInsensitive)
        return c

    def _poblar(self):
        p = self._partida
        self.inp_item.setText(p.get('item', ''))
        self.inp_desc.setText(p.get('descripcion', ''))
        self.chk_titulo.setChecked(bool(p.get('es_titulo', 0)))
        self.inp_unidad.setText(p.get('unidad', ''))
        self.inp_grupo.setText(p.get('grupo', '') or '')
        self._toggle_titulo()

    def _toggle_titulo(self):
        self.inp_unidad.setEnabled(not self.chk_titulo.isChecked())

    def _guardar(self):
        item = self.inp_item.text().strip()
        desc = self.inp_desc.text().strip()
        if not item or not desc:
            self.lbl_error.setText("Ítem y descripción son obligatorios")
            return

        es_titulo = 1 if self.chk_titulo.isChecked() else 0
        nivel     = len(item.split('.'))
        unidad    = self.inp_unidad.text().strip()
        grupo     = self.inp_grupo.text().strip()

        conn = get_db()
        try:
            if self.part_id is None:
                conn.execute(
                    """INSERT INTO partidas (proyecto_id, item, descripcion, unidad,
                       nivel, es_titulo, grupo)
                       VALUES (?,?,?,?,?,?,?)""",
                    (self.pid, item, desc, unidad, nivel, es_titulo, grupo)
                )
            else:
                conn.execute(
                    """UPDATE partidas SET item=?, descripcion=?, unidad=?,
                       nivel=?, es_titulo=?, grupo=? WHERE id=?""",
                    (item, desc, unidad, nivel, es_titulo, grupo, self.part_id)
                )
            conn.commit()
        except sqlite3.IntegrityError as e:
            self.lbl_error.setText(f"Error: {e}")
            conn.close()
            return
        conn.close()
        self.accept()
