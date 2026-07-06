# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""Diálogo para crear/editar un proyecto — equivale a proyecto_form.html de Flask."""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QPushButton, QComboBox, QMessageBox,
    QTabWidget, QWidget, QSpinBox, QDoubleSpinBox
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QIntValidator

from core.config import MONEDAS, ESTADOS_PROYECTO
from core.database import get_db, _recalcular_pu
from models.usuario import Usuario
from utils.formatting import parse_num


class ProyectoFormDialog(QDialog):
    def __init__(self, usuario: Usuario, proyecto_id: int | None = None, parent=None):
        super().__init__(parent)
        self.usuario     = usuario
        self.proyecto_id = proyecto_id
        self._proy       = self._cargar_proyecto()

        self.setWindowTitle("Nuevo proyecto" if proyecto_id is None else "Editar proyecto")
        self.resize(500, 500)
        self.setModal(True)
        self._build_ui()
        if self._proy:
            self._poblar()

    def _cargar_proyecto(self) -> dict | None:
        if not self.proyecto_id:
            return None
        conn = get_db()
        row = conn.execute("SELECT * FROM proyectos WHERE id=?", (self.proyecto_id,)).fetchone()
        conn.close()
        return dict(row) if row else None

    def _build_ui(self):
        vl = QVBoxLayout(self)
        vl.setContentsMargins(20, 20, 20, 20)
        vl.setSpacing(12)

        tabs = QTabWidget()
        tabs.addTab(self._tab_general(), "General")
        tabs.addTab(self._tab_financiero(), "Financiero")
        vl.addWidget(tabs)

        self.lbl_error = QLabel("")
        self.lbl_error.setStyleSheet("color:#dc3545; font-size:12px;")
        vl.addWidget(self.lbl_error)

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

    def _tab_general(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(12, 12, 12, 12)
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignRight)

        self.inp_nombre   = QLineEdit(); self.inp_nombre.setMinimumHeight(32)
        self.inp_cliente  = QLineEdit(); self.inp_cliente.setMinimumHeight(32)
        self.inp_ubic     = QLineEdit(); self.inp_ubic.setMinimumHeight(32)
        self.inp_sub      = QLineEdit(); self.inp_sub.setMinimumHeight(32)
        self.inp_costo_al = QLineEdit(); self.inp_costo_al.setMinimumHeight(32)

        self.cmb_moneda = QComboBox()
        for m in MONEDAS:
            self.cmb_moneda.addItem(m, m)
        self.cmb_moneda.setMinimumHeight(32)

        self.cmb_estado = QComboBox()
        for e in ESTADOS_PROYECTO:
            self.cmb_estado.addItem(e.capitalize(), e)
        self.cmb_estado.setMinimumHeight(32)

        self.inp_modalidad = QLineEdit("Contrata"); self.inp_modalidad.setMinimumHeight(32)

        form.addRow("Nombre *:", self.inp_nombre)
        form.addRow("Cliente:", self.inp_cliente)
        form.addRow("Ubicación:", self.inp_ubic)
        form.addRow("Sub-presupuesto:", self.inp_sub)
        form.addRow("Costo al:", self.inp_costo_al)
        form.addRow("Moneda:", self.cmb_moneda)
        form.addRow("Estado:", self.cmb_estado)
        form.addRow("Modalidad:", self.inp_modalidad)
        return w

    def _tab_financiero(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(12, 12, 12, 12)
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignRight)

        self.inp_plazo = QSpinBox()
        self.inp_plazo.setRange(1, 9999)
        self.inp_plazo.setSuffix(" días")

        self.inp_gf = QDoubleSpinBox()
        self.inp_gf.setRange(0, 100)
        self.inp_gf.setSuffix(" %")
        self.inp_gf.setDecimals(2)

        self.inp_util = QDoubleSpinBox()
        self.inp_util.setRange(0, 100)
        self.inp_util.setSuffix(" %")
        self.inp_util.setDecimals(2)

        self.inp_igv = QDoubleSpinBox()
        self.inp_igv.setRange(0, 100)
        self.inp_igv.setSuffix(" %")
        self.inp_igv.setDecimals(2)
        self.inp_igv.setValue(18.0)

        self.inp_jorn = QComboBox()
        self.inp_jorn.setEditable(True)
        self.inp_jorn.lineEdit().setValidator(QIntValidator(1, 24))
        self.inp_jorn.lineEdit().setPlaceholderText("h/día")
        for h in range(4, 13):
            self.inp_jorn.addItem(f"{h}", h)
        self.inp_jorn.setCurrentIndex(4)  # 8 h/día por defecto

        self.inp_grupo_analisis = QLineEdit()

        for w2 in (self.inp_plazo, self.inp_gf, self.inp_util, self.inp_igv):
            w2.setMinimumHeight(32)
        self.inp_jorn.setMinimumHeight(32)

        form.addRow("Plazo:", self.inp_plazo)
        form.addRow("Gastos Generales %:", self.inp_gf)
        form.addRow("Utilidad %:", self.inp_util)
        form.addRow("IGV %:", self.inp_igv)
        form.addRow("Jornada laboral:", self.inp_jorn)
        form.addRow("Grupo de análisis:", self.inp_grupo_analisis)
        return w

    def _poblar(self):
        p = self._proy
        self.inp_nombre.setText(p.get('nombre', ''))
        self.inp_cliente.setText(p.get('cliente', '') or '')
        self.inp_ubic.setText(p.get('ubicacion', '') or '')
        self.inp_sub.setText(p.get('sub_presupuesto', '') or '')
        self.inp_costo_al.setText(p.get('costo_al', '') or '')
        idx = self.cmb_moneda.findData(p.get('moneda', 'Soles'))
        if idx >= 0:
            self.cmb_moneda.setCurrentIndex(idx)
        idx = self.cmb_estado.findData(p.get('estado', 'elaboracion'))
        if idx >= 0:
            self.cmb_estado.setCurrentIndex(idx)
        self.inp_modalidad.setText(p.get('modalidad', '') or '')
        self.inp_plazo.setValue(int(p.get('plazo', 60) or 60))
        self.inp_gf.setValue(float(p.get('gf_pct', 10) or 10))
        self.inp_util.setValue(float(p.get('utilidad_pct', 5) or 5))
        self.inp_igv.setValue(float(p.get('igv_pct', 18) or 18))
        jorn = int(p.get('jornada_laboral', 8) or 8)
        idx  = self.inp_jorn.findText(str(jorn))
        if idx >= 0:
            self.inp_jorn.setCurrentIndex(idx)
        else:
            self.inp_jorn.setCurrentText(str(jorn))
        self.inp_grupo_analisis.setText(p.get('grupo_analisis', '') or '')

    def _guardar(self):
        nombre = self.inp_nombre.text().strip()
        if not nombre:
            self.lbl_error.setText("El nombre del proyecto es obligatorio")
            return

        datos = (
            nombre,
            self.inp_cliente.text().strip(),
            self.inp_ubic.text().strip(),
            self.inp_sub.text().strip(),
            self.inp_costo_al.text().strip(),
            self.inp_plazo.value(),
            self.inp_gf.value(),
            self.inp_util.value(),
            self.inp_igv.value(),
            self.inp_grupo_analisis.text().strip(),
            int(self.inp_jorn.currentText() or 8),
            self.cmb_moneda.currentData(),
            self.inp_modalidad.text().strip(),
            self.cmb_estado.currentData(),
        )

        conn = get_db()
        # Leer jornada actual antes de modificar (para detectar cambio)
        _jornada_vieja = 8
        if self.proyecto_id is not None:
            _r = conn.execute("SELECT jornada_laboral FROM proyectos WHERE id=?",
                              (self.proyecto_id,)).fetchone()
            _jornada_vieja = int((_r['jornada_laboral'] if _r else 8) or 8)

        try:
            if self.proyecto_id is None:
                conn.execute(
                    """INSERT INTO proyectos (nombre, cliente, ubicacion, sub_presupuesto,
                       costo_al, plazo, gf_pct, utilidad_pct, igv_pct, grupo_analisis,
                       jornada_laboral, moneda, modalidad, estado, usuario_id)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    datos + (self.usuario.id,)
                )
            else:
                conn.execute(
                    """UPDATE proyectos SET nombre=?, cliente=?, ubicacion=?,
                       sub_presupuesto=?, costo_al=?, plazo=?, gf_pct=?, utilidad_pct=?,
                       igv_pct=?, grupo_analisis=?, jornada_laboral=?, moneda=?,
                       modalidad=?, estado=? WHERE id=?""",
                    datos + (self.proyecto_id,)
                )
            conn.commit()

            # Si cambió la jornada laboral, recalcular las cantidades derivadas
            # de la cuadrilla en todo el proyecto: MO y equipo por hora (hh/hm).
            # MO/EQ por día NO lleva jornada; globales y los insumos sin
            # cuadrilla (MAT, equipo-día directo) conservan su cantidad.
            if self.proyecto_id is not None:
                jornada_nueva = int(self.inp_jorn.currentText() or 8)
                if jornada_nueva != _jornada_vieja:
                    from core.database import (_rn, get_decimales_cant_acu,
                        recurso_por_hora, recurso_por_dia, partida_global)
                    partidas = conn.execute(
                        "SELECT id, rendimiento, unidad FROM partidas WHERE proyecto_id=?",
                        (self.proyecto_id,)
                    ).fetchall()
                    dec = get_decimales_cant_acu()
                    for part in partidas:
                        if partida_global(part['unidad']):
                            continue
                        rend = part['rendimiento'] or 1
                        items = conn.execute(
                            """SELECT ai.id, ai.cuadrilla, r.tipo, r.unidad FROM acu_items ai
                               JOIN recursos r ON r.id = ai.recurso_id
                               WHERE ai.partida_id = ?""",
                            (part['id'],)
                        ).fetchall()
                        for it in items:
                            cuad = it['cuadrilla'] or 0
                            if cuad <= 0:
                                continue
                            por_dia = recurso_por_dia(it['tipo'], it['unidad'])
                            if not (por_dia or recurso_por_hora(it['tipo'], it['unidad'])):
                                continue
                            factor = 1 if por_dia else jornada_nueva
                            conn.execute(
                                "UPDATE acu_items SET cantidad=? WHERE id=?",
                                (_rn(cuad / rend * factor, dec), it['id'])
                            )
                        _recalcular_pu(conn, part['id'])
                    conn.commit()

        except Exception as e:
            self.lbl_error.setText(str(e))
            conn.close()
            return
        conn.close()
        self.accept()
