# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""Persistencia de estado de sesión (último proyecto abierto, etc.)."""
from PySide6.QtCore import QSettings

_S = lambda: QSettings("ingePresupuestos", "session")


def get_ultimo_proyecto() -> int | None:
    v = _S().value("last_project")
    return int(v) if v is not None else None


def set_ultimo_proyecto(pid: int):
    _S().setValue("last_project", pid)
