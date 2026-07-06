# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""exportar_view — Centro de exportación (≈ exportar.html de Flask).

Tres bloques:

1. **Backup completo** — copia ``presupuestos.db`` con timestamp.
2. **Exportar proyecto individual** — selector de proyecto y 6 destinos:
       - Excel: Presupuesto / ACUs / Insumos / Reporte completo
       - PDF: Reporte completo
       - SQLite (.db) sólo del proyecto
3. **Ayuda lateral** — explica para qué sirve cada tipo de export.

La generación corre en un ``QThread`` para no congelar la UI.
"""
from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QSize, QThread, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton,
    QComboBox, QFileDialog, QMessageBox, QProgressBar, QSizePolicy,
    QGridLayout,
)

from core.database import get_db
from core.config import DB_PATH
from utils.icons import icon


# ── Paleta ──
ORANGE      = "#F37329"
ORANGE_DARK = "#C0621A"
ORANGE_SOFT = "#FEF5EB"
SLATE_700   = "#273445"
SLATE_500   = "#485A6C"
SLATE_300   = "#667885"
SLATE_100   = "#95A3AB"
SILVER_100  = "#F8F9FA"
SILVER_200  = "#F0F1F2"
SILVER_300  = "#D4D4D4"
WHITE       = "#FFFFFF"
GREEN_500   = "#68B723"


# ── Definición declarativa de los 6 tipos de export por proyecto ─────────────
TIPOS_EXPORT = [
    {
        "id":    "presupuesto",
        "icono": "xlsx",
        "titulo": "Excel — Presupuesto",
        "descripcion": "Hoja de cálculo con la tabla de partidas y pie del presupuesto.",
        "ext": "xlsx",
        "filter": "Excel (*.xlsx)",
    },
    {
        "id":    "acus",
        "icono": "xlsx",
        "titulo": "Excel — Análisis de Costos",
        "descripcion": "ACUs detallados de cada partida (mano de obra, materiales, equipo).",
        "ext": "xlsx",
        "filter": "Excel (*.xlsx)",
    },
    {
        "id":    "insumos",
        "icono": "xlsx",
        "titulo": "Excel — Insumos",
        "descripcion": "Listado consolidado de recursos del proyecto con cantidades y precios.",
        "ext": "xlsx",
        "filter": "Excel (*.xlsx)",
    },
    {
        "id":    "completo",
        "icono": "xlsx",
        "titulo": "Excel — Reporte completo",
        "descripcion": "Un solo archivo con varias hojas: Presupuesto + ACUs + Insumos.",
        "ext": "xlsx",
        "filter": "Excel (*.xlsx)",
    },
    {
        "id":    "pdf",
        "icono": "pdf",
        "titulo": "PDF — Reporte completo",
        "descripcion": "Documento PDF con portada, presupuesto, ACUs, insumos y cronograma.",
        "ext": "pdf",
        "filter": "PDF (*.pdf)",
    },
    {
        "id":    "db",
        "icono": "sqlite",
        "titulo": "SQLite — Solo este proyecto",
        "descripcion": "Archivo .db con datos del proyecto (compartir con otra instalación).",
        "ext": "db",
        "filter": "SQLite (*.db)",
    },
]


# ── Worker thread para no bloquear la UI ────────────────────────────────────
class _ExportWorker(QThread):
    progreso = Signal(str)
    finished_ok = Signal(str)   # ruta del archivo final
    failed = Signal(str)

    def __init__(self, tipo: str, proyecto_id: int, destino: str, parent=None):
        super().__init__(parent)
        self.tipo = tipo
        self.pid = proyecto_id
        self.destino = destino

    def run(self):
        try:
            if self.tipo == "backup":
                self.progreso.emit("Copiando base de datos…")
                # Backup atómico vía sqlite3 (seguro aunque haya writers
                # activos). shutil.copyfile podía capturar la BD con un
                # WAL intermedio y dejar el archivo corrupto.
                import sqlite3 as _sq
                src = _sq.connect(str(DB_PATH))
                dst = _sq.connect(str(self.destino))
                try:
                    with dst:
                        src.backup(dst)
                finally:
                    dst.close()
                    src.close()

            elif self.tipo == "db":
                self.progreso.emit("Replicando esquema y datos del proyecto…")
                from core.exporter import exportar_proyecto_db
                exportar_proyecto_db(self.pid, self.destino)

            elif self.tipo == "pdf":
                self.progreso.emit("Generando PDF (puede tomar unos segundos)…")
                from core.pdf_reports import generar_pdf_archivo
                generar_pdf_archivo("completo", self.pid, self.destino)

            else:
                from core.exporter import (
                    exportar_presupuesto, exportar_acus,
                    exportar_insumos, exportar_reporte_completo,
                )
                fn = {
                    "presupuesto": exportar_presupuesto,
                    "acus":        exportar_acus,
                    "insumos":     exportar_insumos,
                    "completo":    exportar_reporte_completo,
                }.get(self.tipo)
                if not fn:
                    raise ValueError(f"Tipo de exportación desconocido: {self.tipo}")
                self.progreso.emit("Construyendo Excel…")
                buf = fn(self.pid)
                with open(self.destino, "wb") as f:
                    f.write(buf.getvalue())

            self.finished_ok.emit(self.destino)
        except Exception as e:
            import traceback
            self.failed.emit(f"{e}\n\n{traceback.format_exc()[-600:]}")


# ── Tarjeta clickeable para un destino de export ─────────────────────────────
class _ExportCard(QPushButton):
    def __init__(self, spec: dict, parent=None):
        super().__init__(parent)
        from utils.theme import apply_shadow
        self.spec = spec
        self.setObjectName("exportCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(74)
        self.setMaximumHeight(74)
        self.setStyleSheet(
            f"QPushButton#exportCard {{ background:{WHITE};"
            f"  border:1px solid {SILVER_300}; border-radius:8px;"
            f"  padding:0; text-align:left; }}"
            f"QPushButton#exportCard:hover {{ background:{ORANGE_SOFT};"
            f"  border-color:{ORANGE}; }}"
            f"QPushButton#exportCard:disabled {{ background:{SILVER_100}; }}"
        )
        apply_shadow(self, 'sm')
        hl = QHBoxLayout(self)
        hl.setContentsMargins(12, 10, 12, 10)
        hl.setSpacing(10)

        ico = QLabel()
        ico.setFixedSize(40, 40)
        ico.setAlignment(Qt.AlignCenter)
        ico.setPixmap(icon(spec["icono"]).pixmap(26, 26))
        ico.setStyleSheet(
            f"background:{ORANGE_SOFT}; border-radius:8px;"
        )
        hl.addWidget(ico)

        col = QVBoxLayout()
        col.setSpacing(2)
        ttl = QLabel(spec["titulo"])
        ttl.setStyleSheet(
            f"color:{SLATE_700}; font-size:12px; font-weight:600; "
            f"background:transparent; border:none;"
        )
        d = QLabel(spec["descripcion"])
        d.setWordWrap(True)
        d.setStyleSheet(
            f"color:{SLATE_500}; font-size:11px; "
            f"background:transparent; border:none;"
        )
        col.addWidget(ttl)
        col.addWidget(d)
        hl.addLayout(col, 1)


# ── Vista principal ─────────────────────────────────────────────────────────
class ExportarView(QWidget):
    """Centro de exportación (backup completo + por proyecto)."""

    volver = Signal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setProperty("vista_nombre", "exportar")
        self._worker: _ExportWorker | None = None
        self._build()
        self._cargar_proyectos()

    # ── construcción UI ─────────────────────────────────────────────────────
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Topbar oscuro ──
        hdr = QFrame()
        hdr.setFixedHeight(44)
        hdr.setStyleSheet(f"background:{SLATE_700};")
        top = QHBoxLayout(hdr)
        top.setContentsMargins(14, 0, 14, 0)
        top.setSpacing(10)
        from utils.i18n import tr
        btn_back = QPushButton("← " + tr("Inicio"))
        btn_back.setCursor(Qt.PointingHandCursor)
        btn_back.setStyleSheet(
            f"QPushButton {{ background:rgba(255,255,255,0.12); color:white;"
            f"  border:1px solid rgba(255,255,255,0.25); border-radius:6px;"
            f"  font-size:11px; padding:4px 12px; }}"
            f"QPushButton:hover {{ background:rgba(255,255,255,0.22); }}"
        )
        btn_back.clicked.connect(self.volver.emit)
        top.addWidget(btn_back)

        title = QLabel(tr("Exportar"))
        title.setStyleSheet(
            "color:white; font-size:13px; font-weight:700; letter-spacing:0.5px;"
            " background:transparent; border:none;"
        )
        top.addWidget(title)
        top.addStretch(1)
        root.addWidget(hdr)

        # Contenido con márgenes
        _content = QWidget()
        _cv = QVBoxLayout(_content)
        _cv.setContentsMargins(20, 14, 20, 16)
        _cv.setSpacing(12)

        # Cuerpo: 2 columnas
        body = QHBoxLayout()
        body.setSpacing(12)

        # Lado izquierdo (60%) — bloques de export
        col_left = QVBoxLayout()
        col_left.setSpacing(12)

        col_left.addWidget(self._build_card_backup())
        col_left.addWidget(self._build_card_proyecto(), 1)

        body.addLayout(col_left, 6)

        # Lado derecho (40%) — ayuda
        body.addWidget(self._build_panel_ayuda(), 4)

        _cv.addLayout(body, 1)

        # Estado y barra de progreso
        self.lbl_estado = QLabel("")
        self.lbl_estado.setStyleSheet(f"color:{SLATE_300}; font-size:11px;")
        _cv.addWidget(self.lbl_estado)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        self.bar.setVisible(False)
        self.bar.setFixedHeight(6)
        self.bar.setTextVisible(False)
        _cv.addWidget(self.bar)
        root.addWidget(_content, 1)

    def _build_card_backup(self) -> QFrame:
        from utils.theme import apply_shadow
        fr = QFrame()
        fr.setObjectName("cardBackup")
        fr.setAttribute(Qt.WA_StyledBackground, True)
        fr.setStyleSheet(
            f"QFrame#cardBackup {{ background:{WHITE}; "
            f"  border:1px solid {SILVER_300}; border-radius:8px; }}"
        )
        apply_shadow(fr, 'sm')
        v = QVBoxLayout(fr)
        v.setContentsMargins(16, 12, 16, 12)
        v.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(8)
        ico = QLabel()
        ico.setPixmap(icon("sqlite").pixmap(22, 22))
        ico.setStyleSheet("background:transparent; border:none;")
        head.addWidget(ico)
        from utils.i18n import tr
        ttl = QLabel(tr("Backup completo"))
        f = QFont(); f.setWeight(QFont.DemiBold)
        ttl.setFont(f)
        ttl.setStyleSheet(
            f"color:{SLATE_700}; background:transparent; border:none;"
        )
        head.addWidget(ttl)
        head.addStretch(1)
        v.addLayout(head)

        d = QLabel(
            "<b>Descargar</b>: copia el archivo <code>presupuestos.db</code> con todos los "
            "proyectos. Útil para mover la instalación a otro equipo o como respaldo.<br>"
            "<b>Restaurar</b>: reemplaza tu base de datos actual con un <code>.db</code> "
            "previamente guardado (la BD actual se guarda como backup con timestamp)."
        )
        d.setWordWrap(True)
        d.setStyleSheet(
            f"color:{SLATE_500}; font-size:12px; "
            f"background:transparent; border:none;"
        )
        v.addWidget(d)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addStretch(1)

        btn_rest = QPushButton(tr("Restaurar") + "…")
        btn_rest.setIcon(icon("importar"))
        btn_rest.setIconSize(QSize(18, 18))
        btn_rest.setCursor(Qt.PointingHandCursor)
        btn_rest.setMinimumHeight(34)
        btn_rest.setStyleSheet(
            f"QPushButton {{ background:{WHITE}; color:{SLATE_700};"
            f"  border:1px solid {SILVER_300}; border-radius:6px;"
            f"  padding:6px 16px; font-weight:600; }}"
            f"QPushButton:hover {{ background:{ORANGE_SOFT};"
            f"  border-color:{ORANGE}; color:{ORANGE_DARK}; }}"
        )
        btn_rest.clicked.connect(self._restaurar_backup)
        row.addWidget(btn_rest)

        btn = QPushButton(tr("Descargar backup"))
        btn.setIcon(icon("guardar"))
        btn.setIconSize(QSize(18, 18))
        btn.setCursor(Qt.PointingHandCursor)
        btn.setMinimumHeight(34)
        btn.setStyleSheet(
            f"QPushButton {{ background:{SLATE_700}; color:white; border:none;"
            f"  border-radius:6px; padding:6px 16px; font-weight:600; }}"
            f"QPushButton:hover {{ background:{SLATE_500}; }}"
        )
        btn.clicked.connect(self._guardar_backup)
        row.addWidget(btn)
        v.addLayout(row)

        return fr

    def _build_card_proyecto(self) -> QFrame:
        from utils.theme import apply_shadow
        fr = QFrame()
        fr.setObjectName("cardProyecto")
        fr.setAttribute(Qt.WA_StyledBackground, True)
        fr.setStyleSheet(
            f"QFrame#cardProyecto {{ background:{WHITE}; "
            f"  border:1px solid {SILVER_300}; border-radius:8px; }}"
        )
        apply_shadow(fr, 'sm')
        v = QVBoxLayout(fr)
        v.setContentsMargins(16, 12, 16, 14)
        v.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(8)
        ico = QLabel()
        ico.setPixmap(icon("folder").pixmap(22, 22))
        ico.setStyleSheet("background:transparent; border:none;")
        head.addWidget(ico)
        from utils.i18n import tr
        ttl = QLabel(tr("Exportar") + " — " + tr("Proyecto"))
        f = QFont(); f.setWeight(QFont.DemiBold)
        ttl.setFont(f)
        ttl.setStyleSheet(
            f"color:{SLATE_700}; background:transparent; border:none;"
        )
        head.addWidget(ttl)
        head.addStretch(1)
        v.addLayout(head)

        # Selector
        sel_row = QHBoxLayout()
        sel_row.setSpacing(8)
        lbl = QLabel(tr("Proyecto") + ":")
        lbl.setStyleSheet(
            f"color:{SLATE_500}; background:transparent; border:none;"
        )
        sel_row.addWidget(lbl)
        self.cmb_proy = QComboBox()
        self.cmb_proy.setMinimumWidth(280)
        self.cmb_proy.setMaximumWidth(520)
        # El combo se mantiene en ancho fijo. Los textos largos se truncan al
        # agregarlos en `_cargar_proyectos` (ver _ELLIPSIS_MAX) — no podemos
        # depender de view().setMaximumWidth porque Qt estira el popup al
        # item más largo bajo Wayland.
        self.cmb_proy.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.cmb_proy.setMinimumContentsLength(28)
        self.cmb_proy.setMaxVisibleItems(10)
        self.cmb_proy.view().setTextElideMode(Qt.ElideRight)
        # `combobox-popup: 0` lo aplica el filter global de utils/tooltip.py
        # a TODOS los combos. Sólo cap manual de altura para este caso.
        self.cmb_proy.setStyleSheet(
            "QComboBox QAbstractItemView { max-height: 300px; }"
        )
        self.cmb_proy.currentIndexChanged.connect(self._on_proy_change)
        sel_row.addWidget(self.cmb_proy, 1)
        v.addLayout(sel_row)

        # Grid de tarjetas (2×3)
        self._cards: dict[str, _ExportCard] = {}
        grid = QGridLayout()
        grid.setSpacing(10)
        for i, spec in enumerate(TIPOS_EXPORT):
            card = _ExportCard(spec)
            card.clicked.connect(lambda _=False, s=spec: self._exportar_tipo(s))
            self._cards[spec["id"]] = card
            grid.addWidget(card, i // 2, i % 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        v.addLayout(grid)
        v.addStretch(1)

        return fr

    def _build_panel_ayuda(self) -> QFrame:
        fr = QFrame()
        fr.setStyleSheet(
            f"QFrame {{ background:{SILVER_100}; border:1px solid {SILVER_300};"
            f"  border-radius:8px; }}"
        )
        v = QVBoxLayout(fr)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(8)

        ttl = QLabel("¿Para qué sirve cada exportación?")
        f = QFont(); f.setWeight(QFont.DemiBold)
        ttl.setFont(f)
        ttl.setStyleSheet(f"color:{SLATE_700}; background:transparent; border:none;")
        v.addWidget(ttl)

        ayuda = QLabel(
            "<b>Excel — Presupuesto/ACUs/Insumos:</b> hojas individuales del "
            "proyecto. El más usado para enviar a clientes o supervisores.<br><br>"
            "<b>Excel — Reporte completo:</b> un único archivo con todas las "
            "hojas (Presupuesto + ACUs + Insumos) en pestañas.<br><br>"
            "<b>PDF — Reporte completo:</b> documento de presentación con "
            "portada, encabezados y pies de página configurables desde el "
            "Centro de Reportes.<br><br>"
            "<b>SQLite (.db):</b> el proyecto solo, en formato nativo. "
            "Útil para compartirlo con otra instalación de ingePresupuestos "
            "sin afectar la base de datos del destino.<br><br>"
            "<b>Backup completo:</b> toda tu base de datos. Recomendado "
            "antes de actualizaciones."
        )
        ayuda.setWordWrap(True)
        ayuda.setTextFormat(Qt.RichText)
        ayuda.setStyleSheet(f"color:{SLATE_500}; font-size:12px; background:transparent; border:none;")
        v.addWidget(ayuda)
        v.addStretch(1)

        return fr

    # ── carga de proyectos ──────────────────────────────────────────────────
    def _cargar_proyectos(self):
        conn = get_db()
        rows = conn.execute(
            "SELECT id, nombre, cliente FROM proyectos ORDER BY nombre"
        ).fetchall()
        conn.close()

        self.cmb_proy.blockSignals(True)
        self.cmb_proy.clear()
        if not rows:
            self.cmb_proy.addItem("— Sin proyectos —", None)
        else:
            # Truncar items a 48 chars con elipsis para evitar que el popup
            # del QComboBox se estire a pantalla completa con nombres largos
            # típicos de proyectos públicos peruanos. El nombre completo
            # queda accesible vía tooltip.
            _MAX = 48
            for r in rows:
                etiqueta = r['nombre']
                if r['cliente']:
                    etiqueta += f"  ·  {r['cliente']}"
                display = (etiqueta if len(etiqueta) <= _MAX
                           else etiqueta[:_MAX - 1] + "…")
                self.cmb_proy.addItem(display, r['id'])
                idx = self.cmb_proy.count() - 1
                self.cmb_proy.setItemData(idx, etiqueta, Qt.ToolTipRole)
        self.cmb_proy.blockSignals(False)
        self._on_proy_change()

    def _on_proy_change(self):
        pid = self.cmb_proy.currentData()
        habilitar = pid is not None and self._worker is None
        for c in self._cards.values():
            c.setEnabled(habilitar)

    # ── acciones ────────────────────────────────────────────────────────────
    def _guardar_backup(self):
        fecha = datetime.now().strftime("%Y%m%d_%H%M")
        sugerido = f"presupuestos_backup_{fecha}.db"
        destino, _ = QFileDialog.getSaveFileName(
            self, "Guardar backup completo", sugerido, "SQLite (*.db)"
        )
        if not destino:
            return
        if not destino.lower().endswith(".db"):
            destino += ".db"
        self._lanzar_worker("backup", -1, destino)
        # Registrar timestamp para que Tuxia sepa que el usuario hizo backup
        try:
            from PySide6.QtCore import QSettings as _QS
            _QS("ingePresupuestos", "tuxia").setValue(
                "last_backup_iso", datetime.now().isoformat(timespec='seconds')
            )
        except Exception:
            pass

    def _restaurar_backup(self):
        """Reemplaza la BD actual con un .db elegido por el usuario.
        Hace backup automático antes de sobrescribir."""
        import sqlite3, shutil
        from core.config import DB_PATH

        # 1. Elegir archivo
        origen, _ = QFileDialog.getOpenFileName(
            self, "Seleccionar backup a restaurar", "",
            "Bases SQLite ingePresupuestos (*.db *.sqlite)"
        )
        if not origen:
            return

        # 2. Validar que el archivo sea una BD válida de ingePresupuestos
        try:
            c = sqlite3.connect(origen)
            tablas = {r[0] for r in c.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
            requeridas = {'proyectos', 'partidas', 'acu_items', 'recursos'}
            faltantes = requeridas - tablas
            if faltantes:
                c.close()
                QMessageBox.critical(
                    self, "Archivo no compatible",
                    f"El archivo no parece una BD de ingePresupuestos.\n\n"
                    f"Faltan tablas: {', '.join(sorted(faltantes))}"
                )
                return
            n_proy = c.execute("SELECT COUNT(*) FROM proyectos").fetchone()[0]
            c.close()
        except sqlite3.DatabaseError as e:
            QMessageBox.critical(
                self, "Archivo inválido",
                f"No es un archivo SQLite válido:\n\n{e}"
            )
            return

        # 3. Confirmación destructiva
        msg = (
            f"<b>Esto reemplazará tu base de datos actual.</b><br><br>"
            f"Archivo a restaurar:<br>"
            f"  <code>{origen}</code><br>"
            f"  ({n_proy} proyectos)<br><br>"
            f"Se hará un backup automático de tu BD actual con timestamp en la "
            f"carpeta del programa antes de sobrescribir, así que podrás revertir "
            f"si algo sale mal.<br><br>"
            f"Después de la restauración debes <b>cerrar y volver a abrir</b> el "
            f"programa para ver los datos restaurados.<br><br>"
            f"¿Continuar?"
        )
        r = QMessageBox.question(
            self, "Restaurar backup", msg,
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if r != QMessageBox.Yes:
            return

        # 4. Backup automático + reemplazo
        try:
            fecha = datetime.now().strftime("%Y%m%d_%H%M%S")
            db_path = str(DB_PATH)
            backup_path = f"{db_path[:-3]}_backup_{fecha}.db"
            shutil.copyfile(db_path, backup_path)
            shutil.copyfile(origen, db_path)
        except Exception as e:
            QMessageBox.critical(
                self, "Error al restaurar",
                f"No se pudo restaurar el backup:\n\n{e}"
            )
            return

        QMessageBox.information(
            self, "Restauración completada",
            f"<b>Restauración exitosa.</b><br><br>"
            f"BD actual guardada como:<br>"
            f"  <code>{backup_path}</code><br><br>"
            f"BD nueva activa:<br>"
            f"  <code>{db_path}</code> ({n_proy} proyectos)<br><br>"
            f"<b>Cierra y vuelve a abrir el programa</b> para cargar los datos."
        )

    def _exportar_tipo(self, spec: dict):
        pid = self.cmb_proy.currentData()
        if pid is None:
            QMessageBox.warning(self, "Exportar", "Selecciona un proyecto primero.")
            return

        nombre_proy = self.cmb_proy.currentText().split('  ·  ')[0]
        slug = re.sub(r'[^\w\s-]', '', nombre_proy)[:40].strip()
        slug = re.sub(r'\s+', '_', slug) or "proyecto"
        fecha = datetime.now().strftime("%Y%m%d_%H%M")

        sufijo = {
            "presupuesto": "_presupuesto",
            "acus":        "_acus",
            "insumos":     "_insumos",
            "completo":    "_completo",
            "pdf":         "_reporte",
            "db":          "",
        }.get(spec["id"], "")
        sugerido = f"{slug}{sufijo}_{fecha}.{spec['ext']}"

        destino, _ = QFileDialog.getSaveFileName(
            self, f"Guardar {spec['titulo']}", sugerido, spec["filter"]
        )
        if not destino:
            return
        if not destino.lower().endswith("." + spec["ext"]):
            destino += "." + spec["ext"]

        self._lanzar_worker(spec["id"], pid, destino)

    # ── worker control ──────────────────────────────────────────────────────
    def _lanzar_worker(self, tipo: str, pid: int, destino: str):
        if self._worker is not None:
            return
        for c in self._cards.values():
            c.setEnabled(False)
        self.bar.setVisible(True)
        self.lbl_estado.setText("Iniciando…")

        self._worker = _ExportWorker(tipo, pid, destino, self)
        self._worker.progreso.connect(self.lbl_estado.setText)
        self._worker.finished_ok.connect(self._on_ok)
        self._worker.failed.connect(self._on_fail)
        self._worker.start()

    def _on_ok(self, destino: str):
        self.bar.setVisible(False)
        self.lbl_estado.setText("")
        self._worker = None
        self._on_proy_change()
        QMessageBox.information(
            self, "Exportación completa",
            f"Archivo guardado:\n{destino}"
        )

    def _on_fail(self, msg: str):
        self.bar.setVisible(False)
        self.lbl_estado.setText("")
        self._worker = None
        self._on_proy_change()
        QMessageBox.critical(self, "Error al exportar", msg)
