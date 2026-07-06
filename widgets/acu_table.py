# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""Tabla de Análisis de Costos Unitarios — equivale al panel ACU de proyecto.html.

Columnas: Código | Descripción | Tipo | Unidad | Cuadrilla | Cantidad | Precio | Parcial
"""
import sqlite3
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QHeaderView, QAbstractItemView, QMessageBox
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor

from core.config import DB_PATH
from core.database import get_decimales_cant_acu
from utils.formatting import fmt


TIPO_COLOR = {'MO': '#ffeeba', 'MAT': '#d4edda', 'EQ': '#cce5ff'}


class AcuTable(QWidget):
    """Widget embebible que muestra y edita los ACU items de una partida."""
    precio_cambiado = Signal()   # emitir al guardar para recalcular totales

    def __init__(self, parent=None):
        super().__init__(parent)
        self.partida_id: int | None = None
        self.moneda = 'Soles'
        self._build_ui()

    def _build_ui(self):
        vl = QVBoxLayout(self)
        vl.setContentsMargins(4, 4, 4, 4)
        vl.setSpacing(6)

        # Encabezado
        hl = QHBoxLayout()
        self.lbl_titulo = QLabel("ACU")
        self.lbl_titulo.setStyleSheet("font-weight:bold; font-size:13px;")
        hl.addWidget(self.lbl_titulo)
        hl.addStretch()
        btn_add = QPushButton("+ Recurso")
        btn_add.setFixedHeight(28)
        btn_add.clicked.connect(self._agregar_recurso)
        hl.addWidget(btn_add)
        vl.addLayout(hl)

        # Tabla
        cols = ["Código", "Descripción", "Tipo", "Unidad", "Cuadrilla", "Cantidad", "Precio", "Parcial"]
        self.tabla = QTableWidget(0, len(cols))
        self.tabla.setHorizontalHeaderLabels(cols)
        self.tabla.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tabla.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabla.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.SelectedClicked)
        self.tabla.itemChanged.connect(self._on_item_changed)
        vl.addWidget(self.tabla)

        # Total
        hl2 = QHBoxLayout()
        hl2.addStretch()
        self.lbl_total = QLabel("P.U.: —")
        self.lbl_total.setStyleSheet("font-weight:bold; font-size:13px; color:#485a6c;")
        hl2.addWidget(self.lbl_total)
        vl.addLayout(hl2)

    def cargar(self, partida_id: int, moneda: str = 'Soles'):
        self.partida_id = partida_id
        self.moneda = moneda
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        # Obtener descripción y rendimiento de la partida
        p = conn.execute("SELECT descripcion, rendimiento FROM partidas WHERE id=?", (partida_id,)).fetchone()
        if p:
            self.lbl_titulo.setText(f"ACU — {p['descripcion']}")

        rows = conn.execute("""
            SELECT ai.id, r.codigo, r.descripcion, r.tipo, r.unidad,
                   ai.cuadrilla, ai.cantidad,
                   COALESCE(ai.precio, r.precio, 0) AS precio
            FROM acu_items ai
            JOIN recursos r ON ai.recurso_id = r.id
            WHERE ai.partida_id = ?
            ORDER BY CASE r.tipo WHEN 'MO' THEN 1 WHEN 'EQ' THEN 2 ELSE 3 END, r.descripcion
        """, (partida_id,)).fetchall()
        conn.close()

        self._loading = True
        self.tabla.setRowCount(0)
        self._acu_ids = []
        total = 0.0

        for row in rows:
            r = self.tabla.rowCount()
            self.tabla.insertRow(r)
            self._acu_ids.append(row['id'])

            precio = float(row['precio'] or 0)
            cant   = float(row['cantidad'] or 0)
            parcial = precio * cant

            if not str(row['unidad']).startswith('%'):
                total += parcial

            color = QColor(TIPO_COLOR.get(row['tipo'], '#ffffff'))
            vals = [
                row['codigo'] or '', row['descripcion'] or '',
                row['tipo'] or '', row['unidad'] or '',
                f"{(row['cuadrilla'] or 0):.3f}",
                f"{cant:.{get_decimales_cant_acu()}f}",
                f"{precio:.4f}",
                fmt(parcial, moneda),
            ]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(str(v))
                it.setBackground(color)
                # Solo cantidad y precio son editables
                if c not in (5, 6):
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                self.tabla.setItem(r, c, it)

        self.lbl_total.setText(f"P.U.: {fmt(total, moneda)}")
        self._loading = False

    def _on_item_changed(self, item):
        if self._loading or self.partida_id is None:
            return
        # TODO: guardar cambio en BD (cantidad/precio) y emitir precio_cambiado

    def _agregar_recurso(self):
        # TODO: diálogo de búsqueda y selección de recurso del catálogo
        pass
