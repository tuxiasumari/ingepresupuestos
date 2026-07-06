# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""Diálogo de primera ejecución — equivale a setup.html de Flask."""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QMessageBox
)
from PySide6.QtCore import Qt

from utils.auth import crear_admin


class SetupDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configuración inicial")
        self.setFixedSize(380, 360)
        self.setModal(True)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 36, 36, 36)
        layout.setSpacing(12)

        lbl = QLabel("Crear cuenta de administrador")
        lbl.setStyleSheet("font-size: 16px; font-weight: bold; color: #485a6c;")
        lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(lbl)

        layout.addSpacing(8)

        self.inp_nombre   = QLineEdit(); self.inp_nombre.setPlaceholderText("Nombre completo")
        self.inp_username = QLineEdit(); self.inp_username.setPlaceholderText("Nombre de usuario")
        self.inp_pass1    = QLineEdit(); self.inp_pass1.setPlaceholderText("Contraseña"); self.inp_pass1.setEchoMode(QLineEdit.Password)
        self.inp_pass2    = QLineEdit(); self.inp_pass2.setPlaceholderText("Repetir contraseña"); self.inp_pass2.setEchoMode(QLineEdit.Password)

        for w in (self.inp_nombre, self.inp_username, self.inp_pass1, self.inp_pass2):
            w.setMinimumHeight(36)
            layout.addWidget(w)

        self.lbl_error = QLabel("")
        self.lbl_error.setStyleSheet("color:#dc3545; font-size:12px;")
        self.lbl_error.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.lbl_error)

        btn = QPushButton("Crear administrador")
        btn.setMinimumHeight(40)
        btn.setStyleSheet("background:#485a6c; color:white; border-radius:6px; font-size:13px;")
        btn.clicked.connect(self._crear)
        layout.addWidget(btn)

    def _crear(self):
        nombre   = self.inp_nombre.text().strip()
        username = self.inp_username.text().strip()
        pass1    = self.inp_pass1.text()
        pass2    = self.inp_pass2.text()

        if not all([nombre, username, pass1, pass2]):
            self.lbl_error.setText("Complete todos los campos")
            return
        if pass1 != pass2:
            self.lbl_error.setText("Las contraseñas no coinciden")
            return
        if len(pass1) < 6:
            self.lbl_error.setText("La contraseña debe tener al menos 6 caracteres")
            return

        ok, msg = crear_admin(nombre, username, pass1)
        if ok:
            QMessageBox.information(self, "Listo", "Administrador creado. Puede iniciar sesión.")
            self.accept()
        else:
            self.lbl_error.setText(msg)
