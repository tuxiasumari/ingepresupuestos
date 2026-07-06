# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""Tabla de Insumos Totales del proyecto — equivale al panel inferior izquierdo de proyecto.html."""
import sqlite3
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QTableWidget, QTableWidgetItem, QHeaderView
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from core.config import DB_PATH
from utils.formatting import fmt

TIPO_COLOR = {'MO': '#fff3cd', 'MAT': '#d1e7dd', 'EQ': '#cfe2ff'}


class InsumosTable(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        vl = QVBoxLayout(self)
        vl.setContentsMargins(4, 4, 4, 4)
        lbl = QLabel("INSUMOS TOTALES")
        lbl.setStyleSheet("font-weight:bold; font-size:12px; background:#485a6c; color:white; padding:4px 8px;")
        vl.addWidget(lbl)

        cols = ["Descripción", "Tipo", "Unidad", "Cantidad", "Precio", "Parcial", "%"]
        self.tabla = QTableWidget(0, len(cols))
        self.tabla.setHorizontalHeaderLabels(cols)
        self.tabla.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tabla.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabla.setAlternatingRowColors(True)
        vl.addWidget(self.tabla)

    def cargar(self, proyecto_id: int, moneda: str = 'Soles'):
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        # Excluir unidades overhead ('%')
        rows = conn.execute("""
            SELECT r.descripcion, r.tipo, r.unidad,
                   SUM(ai.cantidad * p.metrado) AS cantidad,
                   COALESCE(MAX(ai.precio), r.precio, 0) AS precio,
                   SUM(ai.cantidad * p.metrado * COALESCE(ai.precio, r.precio, 0)) AS parcial
            FROM acu_items ai
            JOIN recursos r ON ai.recurso_id = r.id
            JOIN partidas p ON ai.partida_id = p.id
            WHERE p.proyecto_id = ? AND SUBSTR(r.unidad, 1, 1) != '%'
            GROUP BY r.id
            ORDER BY CASE r.tipo WHEN 'MO' THEN 1 WHEN 'EQ' THEN 2 ELSE 3 END, r.descripcion
        """, (proyecto_id,)).fetchall()
        conn.close()

        total_cd = sum(float(r['parcial'] or 0) for r in rows)
        self.tabla.setRowCount(0)
        for row in rows:
            ri = self.tabla.rowCount()
            self.tabla.insertRow(ri)
            parcial = float(row['parcial'] or 0)
            pct = f"{parcial/total_cd*100:.1f}%" if total_cd else "0%"
            color = QColor(TIPO_COLOR.get(row['tipo'], '#ffffff'))
            vals = [
                row['descripcion'] or '', row['tipo'] or '', row['unidad'] or '',
                f"{(row['cantidad'] or 0):.4f}",
                fmt(row['precio'] or 0, moneda),
                fmt(parcial, moneda), pct,
            ]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(str(v))
                it.setBackground(color)
                self.tabla.setItem(ri, c, it)
