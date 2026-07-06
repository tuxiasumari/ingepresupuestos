# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""importar_view — Importar Proyecto (≈ importar.html de Flask).

Soporta 5 formatos:
    - PowerCost Excel       (Presupuesto + ACUs + Insumos + Metrados)
    - Delphin Express Excel (Presupuesto + ACUs + Insumos)
    - S10 Costos & Pptos    (Presupuesto + ACUs + Insumos)
    - IFC / BIM             (Modelo .ifc → estructura sin precios)
    - PDF de PowerCost      (Presupuesto + ACU + Insumos en PDF)

La importación corre en un QThread para no congelar la UI; al terminar emite
``proyecto_importado(int)`` que MainWindow conecta para abrir el proyecto.
"""
from __future__ import annotations

from pathlib import Path
from PySide6.QtCore import Qt, QSize, QThread, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton,
    QButtonGroup, QStackedWidget, QFileDialog, QMessageBox, QProgressBar,
    QSizePolicy, QScrollArea, QDialog, QLineEdit, QListWidget,
    QListWidgetItem, QInputDialog,
)

from utils.icons import icon


# ── Paleta (consistente con dashboard/recursos) ──────────────────────────────
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
RED_500     = "#C6262E"


# ── Definición declarativa de los 5 formatos soportados ──────────────────────
# Cada formato: nombre visible, alias para utils.icons (icono SVG), descripción
# corta, lista de archivos requeridos / opcionales y bloque de instrucciones.
# Programas (nivel 1 de selección — primera fila de botones)
PROGRAMAS = [
    {"id": "powercost",        "nombre": "PowerCost",       "icono": "spreadsheet"},
    {"id": "delphin",          "nombre": "Delphin Express", "icono": "spreadsheet"},
    {"id": "s10",              "nombre": "S10",             "icono": "spreadsheet"},
    {"id": "bim",              "nombre": "BIM / IFC",       "icono": "paquete"},
    {"id": "ingepresupuestos", "nombre": "ingePresupuestos","icono": "sqlite"},
]

FORMATOS = [
    {
        "id":     "powercost",
        "programa":  "powercost",
        "subnombre": "Excel",
        "nombre": "PowerCost",
        "icono":  "spreadsheet",
        "ext":    "Excel (*.xlsx *.xls)",
        "archivos": [
            ("presupuesto", "Presupuesto.xlsx",        True,
             "Estructura del proyecto con partidas, metrados y precios."),
            ("acus",        "Análisis de Costos.xlsx", False,
             "Recursos por partida (mano de obra, materiales, equipo)."),
            ("insumos",     "Listado de Insumos.xlsx", False,
             "Catálogo de recursos con precios actualizados."),
            ("metrados",    "Planilla de Metrados.xlsx", False,
             "Detalle de dimensiones (N° estructuras, largo, ancho, alto…)."),
        ],
        "instrucciones": [
            "Abre tu proyecto en PowerCost.",
            "Reportes → Presupuesto → Exportar Excel → Presupuesto.xlsx",
            "Reportes → Análisis de Costos → Exportar → ACUS.xlsx",
            "Reportes → Listado de Insumos → Exportar → Insumos.xlsx",
            "(Opcional) Reportes → Planilla de Metrados → Exportar.",
        ],
    },
    {
        "id":     "delphin",
        "programa":  "delphin",
        "subnombre": "Excel",
        "nombre": "Delphin Express",
        "icono":  "xlsx",
        "ext":    "Excel (*.xlsx *.xls)",
        "archivos": [
            ("presupuesto", "Presupuesto.xlsx",        True,
             "Estructura del proyecto."),
            ("acus",        "ACUs.xlsx",               False,
             "Análisis de costos unitarios por partida."),
            ("insumos",     "Insumos.xlsx",            False,
             "Catálogo de recursos."),
        ],
        "instrucciones": [
            "Abre tu proyecto en Delphin Express.",
            "Imprimir / Exportar → Presupuesto → Guardar como Excel.",
            "Si tienes ACUs: Exportar → Análisis de Costos → Excel.",
            "El importador detecta automáticamente las columnas Delphin.",
        ],
    },
    {
        "id":     "ingepresupuestos_db",
        "programa":  "ingepresupuestos",
        "subnombre": "Base (.db)",
        "nombre": "Base ingePresupuestos (.db)",
        "icono":  "sqlite",
        "ext":    "Bases ingePresupuestos (*.db *.sqlite)",
        "archivos": [
            ("db", "Archivo .db de ingePresupuestos", True,
             "Otra base de datos de ingePresupuestos desde la cual extraer "
             "proyectos individuales (sin reemplazar tu base actual)."),
        ],
        "instrucciones": [
            "Selecciona un archivo .db de ingePresupuestos (típicamente un "
            "backup tuyo o de un colega).",
            "Aparecerá un diálogo con la lista de proyectos del archivo: "
            "marca los que quieras importar (Ctrl+Click suma; "
            "Shift+Click rango; 'Seleccionar todos').",
            "Los proyectos elegidos se AÑADEN a tu base actual (no reemplaza "
            "nada). Los recursos del catálogo se reutilizan si ya existen.",
            "La biblioteca CU se enriquece automáticamente con los ACUs únicos.",
        ],
    },
    {
        "id":     "powercost_prs",
        "programa":  "powercost",
        "subnombre": "Base nativa (.prs)",
        "nombre": "PowerCost (.prs)",
        "icono":  "sqlite",
        "ext":    "Bases PowerCost (*.prs)",
        "archivos": [
            ("db", "Archivo .prs de PowerCost", True,
             "Base nativa de PowerCost (MS Access). Lee partidas, ACUs, "
             "rendimientos, insumos con precios y planilla de metrados."),
        ],
        "instrucciones": [
            "En PowerCost: ubica el archivo .prs de tu proyecto. "
            "Suele estar en la carpeta donde guardas tus presupuestos.",
            "Selecciona el .prs — se importa todo: títulos, partidas, "
            "ACUs (con rendimiento y cuadrillas), insumos (con código INEI "
            "auto-mapeado) y la planilla de metrados detallados.",
            "Si tu PowerCost guardó varios sub-presupuestos en el mismo .prs, "
            "se importa el primero (sub-presupuesto activo).",
            "⚠ En Linux requiere `mdbtools` (`sudo apt install -y mdbtools`). "
            "En Windows requiere Office o el driver gratuito Access Database Engine.",
        ],
    },
    {
        "id":     "delphin_sqlite",
        "programa":  "delphin",
        "subnombre": "Base nativa (.sqlite)",
        "nombre": "Delphin (Base de datos)",
        "icono":  "sqlite",
        "ext":    "SQLite (*.sqlite *.db)",
        "archivos": [
            ("db", "Base de datos Delphin (.sqlite)", True,
             "Archivo .sqlite generado por Delphin Express con el proyecto."),
        ],
        "instrucciones": [
            "En Delphin: Archivo → Hacer Backup. Esto genera un .sqlite con "
            "todo el proyecto (partidas, ACUs, insumos, metrados, índices INEI).",
            "Selecciona el .sqlite — se importan automáticamente: partidas, "
            "rendimientos, composiciones de ACU, recursos y metrados detallados.",
            "Si la base tiene varios sub-presupuestos (Estructura, Arquitectura, "
            "Eléctricas, Sanitarias…) se importan todos como un solo árbol.",
            "⚠ Si tu archivo es .dprj (formato propietario Delphin), Delphin "
            "no permite leerlo desde otras apps. Usa Archivo → Hacer Backup "
            "para obtener el .sqlite equivalente.",
        ],
    },
    {
        "id":     "s10",
        "programa":  "s10",
        "subnombre": "Excel",
        "nombre": "S10 Costos y Presupuestos",
        "icono":  "spreadsheet",
        "ext":    "Excel (*.xlsx *.xls)",
        "archivos": [
            ("presupuesto", "Presupuesto.xlsx", True,
             "Estructura con partidas y precios."),
            ("acus",        "ACUs.xlsx",        False,
             "Análisis de costos."),
            ("insumos",     "Insumos.xlsx",     False,
             "Catálogo de recursos."),
        ],
        "instrucciones": [
            "Exporta desde S10 los reportes a formato Excel.",
            "Sube el Presupuesto (obligatorio) y opcionalmente ACUs e Insumos.",
            "Para mejores resultados sube los 3 archivos juntos.",
        ],
    },
    {
        "id":     "s10_s2k",
        "programa":  "s10",
        "subnombre": "Base nativa (.S2K)",
        "nombre": "S10 (.S2K / .bak / .bkf)",
        "icono":  "sqlite",
        "ext":    "Backup S10 (*.S2K *.bak *.bkf)",
        "archivos": [
            ("archivo", "Backup S10 (.S2K / .bak / .bkf)", True,
             "Base nativa de S10 directamente — no necesitas exportar a Excel. "
             "Importa todos los presupuestos del archivo de una vez."),
        ],
        "instrucciones": [
            "Ubica el archivo .S2K (o .bak / .bkf) de tu proyecto en S10. "
            "Suele estar en la carpeta donde S10 guarda los backups.",
            "Selecciona el archivo — se restauran TODOS los presupuestos que "
            "contiene y se importan como proyectos separados en tu base.",
            "⚠ Requiere el complemento gratuito IngeConverter. Si no lo "
            "tienes, te aparecerá un diálogo con el link de descarga. "
            "En Linux necesita Docker instalado (programa gratuito); en "
            "Windows ya viene todo incluido en el instalador.",
            "La primera vez que conviertas un .S2K en Linux/Mac, se "
            "descargan ~2.3 GB automáticamente (el motor de base de datos "
            "de Microsoft). Solo ocurre una vez — las siguientes "
            "conversiones tardan ~20 segundos.",
            "Limitación: backups de S10 muy antiguos (anteriores a S10 "
            "2005) no se pueden restaurar. Reexporta el backup desde una "
            "versión moderna de S10.",
        ],
    },
    {
        "id":     "ifc",
        "programa":  "bim",
        "subnombre": "IFC (.ifc)",
        "nombre": "IFC / BIM",
        "icono":  "paquete",
        "ext":    "IFC (*.ifc)",
        "archivos": [
            ("ifc", "Modelo BIM (.ifc)", True,
             "Archivo IFC exportado desde Revit, ArchiCAD, Tekla u otro BIM."),
        ],
        "instrucciones": [
            "Exporta tu modelo desde Revit / ArchiCAD / Tekla en formato IFC.",
            "El importador genera la estructura sin precios.",
            "Tras importar deberás asignar precios a las partidas creadas.",
        ],
    },
    {
        "id":     "pdf_powercost",
        "programa":  "powercost",
        "subnombre": "PDF",
        "nombre": "PDF (PowerCost)",
        "icono":  "pdf",
        "ext":    "PDF (*.pdf)",
        "archivos": [
            ("presupuesto", "Presupuesto.pdf", True,
             "PDF del presupuesto generado desde PowerCost."),
            ("acus",        "ACU.pdf",         False,
             "PDF del Análisis de Costos Unitarios."),
            ("insumos",     "Insumos.pdf",     False,
             "PDF del Listado de Insumos con precios."),
        ],
        "instrucciones": [
            "Genera los reportes en PDF desde PowerCost.",
            "El extractor lee el texto del PDF (no funciona con escaneados).",
            "Si los PDFs son escaneados / imagen, exporta primero en Excel.",
        ],
    },
]


# ── Worker thread para que la importación no bloquee la UI ───────────────────
class _S10ListWorker(QThread):
    """Worker que solo restaura el .S2K y lista sus presupuestos.

    Está separado de `_ImportWorker` porque levantar Docker/LocalDB y restaurar
    tarda 10-30s (más la primera vez con `docker pull`) — no podemos bloquear
    la UI esperando. La UI muestra el diálogo de selección cuando este worker
    termina, y entonces lanza el `_ImportWorker` con los cods seleccionados.
    """
    progreso = Signal(str)
    finished_list = Signal(list)  # [{'cod': str, 'descripcion': str}, ...]
    failed = Signal(str)
    pedir_descarga = Signal(str)  # URL de la landing — IngeConverter no instalado

    def __init__(self, archivo: str, parent=None):
        super().__init__(parent)
        self.archivo = archivo

    def run(self):
        try:
            from core.ingeconverter_bridge import (
                DOWNLOAD_URL, BackupVersionTooOld, IngeConverterBridge,
                IngeConverterError, IngeConverterNotInstalled,
            )
            bridge = IngeConverterBridge()
            if not bridge.esta_instalado():
                self.pedir_descarga.emit(DOWNLOAD_URL)
                return
            self.progreso.emit("Iniciando SQL Server y restaurando backup…")
            presupuestos = bridge.listar_presupuestos(self.archivo)
            data = [{'cod': p.cod, 'descripcion': p.descripcion} for p in presupuestos]
            self.finished_list.emit(data)
        except IngeConverterNotInstalled:
            self.pedir_descarga.emit(DOWNLOAD_URL)
        except BackupVersionTooOld as e:
            self.failed.emit(str(e))
        except IngeConverterError as e:
            self.failed.emit(f"IngeConverter falló al leer el backup:\n{e}")
        except Exception as e:
            import traceback
            self.failed.emit(f"{e}\n\n{traceback.format_exc()[-600:]}")


class _ImportWorker(QThread):
    progreso = Signal(str)            # mensaje de estado
    finished_ok = Signal(int, str)    # pid, resumen
    failed = Signal(str)              # mensaje de error

    finished_multi = Signal(list, str)  # [pid1, pid2, ...], resumen

    def __init__(self, formato: str, files: dict,
                 id_ppto: int | None = None,
                 ids_ppto: list[int] | None = None,
                 cods_s10: list[str] | None = None,
                 parent=None):
        super().__init__(parent)
        self.formato = formato
        self.files = files
        self.id_ppto = id_ppto       # solo para powercost_prs (1 proyecto)
        self.ids_ppto = ids_ppto     # solo para powercost_prs (varios)
        self.cods_s10 = cods_s10     # solo para s10_s2k (cods elegidos en el diálogo)

    def run(self):
        # Caso especial: backup S10 nativo — delega al bridge de IngeConverter
        if self.formato == "s10_s2k":
            self._run_s10_s2k()
            return

        # Caso especial: multi-proyecto desde una sola base
        if self.ids_ppto:
            if self.formato == "powercost_prs":
                self._run_multi_powercost()
                return
            if self.formato == "ingepresupuestos_db":
                self._run_multi_ingepresupuestos_db()
                return
        try:
            self.progreso.emit("Procesando archivos…")
            from core import importer
            from core.pdf_importer import (
                import_powercost_presupuesto_pdf,
                import_powercost_acu_pdf,
                import_powercost_insumos_pdf,
            )
            from core.ifc_importer import parse_ifc

            f = self.files
            recursos = None
            metrados = None

            if self.formato == "ifc":
                self.progreso.emit("Parseando modelo IFC…")
                info, partidas = parse_ifc(f["ifc"])
                acus = {}

            elif self.formato == "delphin":
                self.progreso.emit("Leyendo Presupuesto Delphin…")
                info, partidas = importer.import_delphin_presupuesto(f["presupuesto"])
                acus = (importer.import_delphin_acus(f["acus"])
                        if "acus" in f else {})
                recursos = (importer.import_delphin_insumos(f["insumos"])
                            if "insumos" in f else None)

            elif self.formato == "delphin_sqlite":
                self.progreso.emit("Leyendo base de datos Delphin…")
                from core.delphin_sqlite_importer import import_delphin_sqlite
                info, partidas, acus, recursos, metrados = (
                    import_delphin_sqlite(f["db"])
                )

            elif self.formato == "ingepresupuestos_db":
                # Importación directa por SQL (preserva specs, metrados de
                # acero, cronograma, pie, GG, fórmula, sub-presupuestos).
                self.progreso.emit("Importando proyecto desde base ingePresupuestos…")
                from core.ingepresupuestos_db_importer import (
                    importar_proyecto_db_directo
                )
                pid = importar_proyecto_db_directo(f["db"], self.id_ppto)
                self.finished_ok.emit(pid, "Proyecto importado completo "
                                            "(con specs + metrados + cronograma + "
                                            "pie + fórmula).")
                return

            elif self.formato == "powercost_prs":
                self.progreso.emit("Leyendo archivo .prs de PowerCost…")
                from core.powercost_prs_importer import import_powercost_prs
                info, partidas, acus, recursos, metrados = (
                    import_powercost_prs(f["db"], id_ppto=self.id_ppto)
                )

            elif self.formato == "s10":
                self.progreso.emit("Leyendo Presupuesto S10…")
                info, partidas = importer.import_s10_presupuesto(f["presupuesto"])
                acus = (importer.import_s10_acus(f["acus"])
                        if "acus" in f else {})
                recursos = (importer.import_s10_insumos(f["insumos"])
                            if "insumos" in f else None)

            elif self.formato == "pdf_powercost":
                self.progreso.emit("Extrayendo texto del PDF…")
                info, partidas = import_powercost_presupuesto_pdf(f["presupuesto"])
                acus = (import_powercost_acu_pdf(f["acus"])
                        if "acus" in f else {})
                recursos = (import_powercost_insumos_pdf(f["insumos"])
                            if "insumos" in f else None)

            else:  # powercost (default)
                self.progreso.emit("Leyendo Presupuesto PowerCost…")
                info, partidas = importer.import_powercost_presupuesto(f["presupuesto"])
                acus = (importer.import_powercost_acus(f["acus"])
                        if "acus" in f else {})
                recursos = (importer.import_powercost_insumos(f["insumos"])
                            if "insumos" in f else None)
                if "metrados" in f:
                    try:
                        metrados = importer.import_powercost_metrados(f["metrados"])
                    except Exception:
                        metrados = None

            if not partidas:
                self.failed.emit(
                    "El archivo no contiene partidas reconocibles.\n"
                    "Verifica que el formato seleccionado sea correcto."
                )
                return

            self.progreso.emit("Guardando en base de datos…")
            pid = importer.guardar_importacion(info, partidas, acus, recursos, metrados)

            n_part = len([p for p in partidas if not p.get("es_titulo")])
            n_acus = len(acus or {})
            n_rec = len(recursos) if recursos else 0
            n_met = sum(len(v) for v in metrados.values()) if metrados else 0
            partes = [f"{n_part} partidas"]
            if n_acus: partes.append(f"{n_acus} ACUs")
            if n_rec:  partes.append(f"{n_rec} recursos")
            if n_met:  partes.append(f"{n_met} filas de metrados")
            resumen = "  ·  ".join(partes)
            self.finished_ok.emit(pid, resumen)

        except Exception as e:
            import traceback
            self.failed.emit(f"{e}\n\n{traceback.format_exc()[-600:]}")

    def _run_multi_powercost(self):
        """Importa varios proyectos secuencialmente desde un .prs PowerCost.
        Emite ``finished_multi`` con la lista de PIDs creados al terminar."""
        from core import importer
        from core.powercost_prs_importer import import_powercost_prs
        pids: list[int] = []
        errores: list[str] = []
        total = len(self.ids_ppto)
        for i, idp in enumerate(self.ids_ppto, 1):
            try:
                self.progreso.emit(
                    f"Importando proyecto {i} de {total}  (IdPpto={idp})…"
                )
                info, partidas, acus, recursos, metrados = (
                    import_powercost_prs(self.files["db"], id_ppto=idp)
                )
                if not partidas:
                    errores.append(f"#{idp}: sin partidas")
                    continue
                pid = importer.guardar_importacion(
                    info, partidas, acus, recursos, metrados
                )
                pids.append(pid)
            except Exception as e:
                errores.append(f"#{idp}: {e}")

        partes = [f"{len(pids)} proyectos importados"]
        if errores:
            partes.append(f"{len(errores)} con error")
        resumen = "  ·  ".join(partes)
        if errores:
            resumen += "\n\nErrores:\n" + "\n".join(errores[:10])
            if len(errores) > 10:
                resumen += f"\n…y {len(errores)-10} más."
        self.finished_multi.emit(pids, resumen)

    def _run_multi_ingepresupuestos_db(self):
        """Importa varios proyectos desde una BD ingePresupuestos.
        Usa SQL directo para preservar specs, metrados, cronograma, pie, etc."""
        from core.ingepresupuestos_db_importer import importar_proyecto_db_directo
        pids: list[int] = []
        errores: list[str] = []
        total = len(self.ids_ppto)
        for i, idp in enumerate(self.ids_ppto, 1):
            try:
                self.progreso.emit(
                    f"Importando proyecto {i} de {total}  (id={idp})…"
                )
                pid = importar_proyecto_db_directo(self.files["db"], idp)
                pids.append(pid)
            except Exception as e:
                errores.append(f"#{idp}: {e}")

        partes = [f"{len(pids)} proyectos importados"]
        if errores:
            partes.append(f"{len(errores)} con error")
        resumen = "  ·  ".join(partes)
        if errores:
            resumen += "\n\nErrores:\n" + "\n".join(errores[:10])
            if len(errores) > 10:
                resumen += f"\n…y {len(errores)-10} más."
        self.finished_multi.emit(pids, resumen)

    def _run_s10_s2k(self):
        """Importa un backup nativo de S10 vía el complemento IngeConverter.

        Asume que `cods_s10` ya tiene los códigos elegidos por el usuario
        (el listado y diálogo de selección ocurren en `_S10ListWorker` +
        `_iniciar_importacion`, antes de instanciar este worker). Si no
        hay selección, cae al modo "todos".
        """
        import shutil
        import tempfile
        from pathlib import Path

        from core.ingeconverter_bridge import IngeConverterBridge
        from core.ingepresupuestos_db_importer import (
            importar_proyecto_db_directo, listar_proyectos_db,
        )

        archivo = Path(self.files["archivo"])
        bridge = IngeConverterBridge()
        cods = self.cods_s10 or []
        if not cods:
            self.failed.emit("No se eligió ningún presupuesto a importar.")
            return

        # Convierte cada presupuesto elegido a un .db tmp y lo importa
        tmp_dir = Path(tempfile.mkdtemp(prefix="ingeconv_import_"))
        try:
            pids: list[int] = []
            errores: list[str] = []
            total = len(cods)
            for i, cod in enumerate(cods, 1):
                try:
                    self.progreso.emit(
                        f"Convirtiendo presupuesto {i} de {total}: {cod}…"
                    )
                    out_db = tmp_dir / f"{cod}.db"
                    bridge.convertir(
                        archivo, cod_presupuesto=cod, out=out_db,
                        on_log=lambda l: self.progreso.emit(l) if l.strip() else None,
                    )
                    self.progreso.emit(f"Importando {cod} a tu base…")
                    # IngeConverter emite un .db con UN proyecto adentro;
                    # consultamos su id_ppto real (típicamente 1, pero no
                    # asumimos) y lo pasamos al importer SQL-directo.
                    proyectos_en_db = listar_proyectos_db(str(out_db))
                    if not proyectos_en_db:
                        errores.append(f"{cod}: .db vacío tras conversión")
                        continue
                    pid = importar_proyecto_db_directo(
                        str(out_db), proyectos_en_db[0]["id_ppto"]
                    )
                    pids.append(pid)
                except Exception as e:
                    errores.append(f"{cod}: {e}")

            partes = [f"{len(pids)} proyecto(s) importado(s) desde S10"]
            if errores:
                partes.append(f"{len(errores)} con error")
            resumen = "  ·  ".join(partes)
            if errores:
                resumen += "\n\nErrores:\n" + "\n".join(errores[:10])
                if len(errores) > 10:
                    resumen += f"\n…y {len(errores)-10} más."
            self.finished_multi.emit(pids, resumen)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)


# ── Vista principal ──────────────────────────────────────────────────────────
class ImportarView(QWidget):
    """Vista de importación con sidebar de formato + form de archivos."""

    proyecto_importado = Signal(int)   # pid → MainWindow abrirá el proyecto
    volver = Signal()                  # botón ← para regresar al dashboard

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setProperty("vista_nombre", "importar")
        self._formato_id = "powercost"
        self._archivos: dict[str, str] = {}
        self._worker: _ImportWorker | None = None
        self._build()
        self._aplicar_programa("powercost")

    # ── construcción UI ──────────────────────────────────────────────────────
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

        title = QLabel(tr("Importar"))
        title.setStyleSheet(
            "color:white; font-size:13px; font-weight:700; letter-spacing:0.5px;"
            " background:transparent; border:none;"
        )
        top.addWidget(title)
        top.addStretch(1)

        root.addWidget(hdr)

        # Contenido con márgenes
        _content = QWidget()
        _content_vl = QVBoxLayout(_content)
        _content_vl.setContentsMargins(20, 14, 20, 16)
        _content_vl.setSpacing(12)

        # ── Cuerpo: 2 columnas (form izq + instrucciones der) ──
        body = QHBoxLayout()
        body.setSpacing(12)

        # Lado izquierdo (60%) — formulario
        col_left = QFrame()
        col_left.setStyleSheet(
            f"QFrame {{ background:{WHITE}; border:none;"
            f"  border-radius:8px; }}"
        )
        ll = QVBoxLayout(col_left)
        ll.setContentsMargins(16, 14, 16, 14)
        ll.setSpacing(10)

        # 1) Selector de programa de origen (nivel 1)
        lbl_fmt = QLabel(tr("Software de origen"))
        f2 = QFont(); f2.setWeight(QFont.DemiBold)
        lbl_fmt.setFont(f2)
        lbl_fmt.setStyleSheet(f"color:{SLATE_700}; background:transparent; border:none;")
        ll.addWidget(lbl_fmt)

        prog_row = QHBoxLayout()
        prog_row.setSpacing(6)
        self._prog_buttons: dict[str, QPushButton] = {}
        self._prog_group = QButtonGroup(self)
        self._prog_group.setExclusive(True)
        for spec in PROGRAMAS:
            btn = self._mk_fmt_button({
                'id': spec['id'],
                'nombre': spec['nombre'],
                'icono': spec['icono'],
            })
            self._prog_buttons[spec['id']] = btn
            self._prog_group.addButton(btn)
            btn.toggled.connect(lambda checked, pid=spec['id']:
                                self._aplicar_programa(pid) if checked else None)
            prog_row.addWidget(btn)
        prog_row.addStretch(1)
        ll.addLayout(prog_row)

        # 2) Pestañas de formato (nivel 2) — depende del programa activo
        lbl_sub = QLabel(tr("Formato del archivo"))
        lbl_sub.setStyleSheet(
            f"color:{SLATE_500}; font-size:11px; padding-top:6px;"
            f" background:transparent; border:none;"
        )
        ll.addWidget(lbl_sub)

        fmt_row = QHBoxLayout()
        fmt_row.setSpacing(6)
        self._fmt_buttons: dict[str, QPushButton] = {}
        self._fmt_group = QButtonGroup(self)
        self._fmt_group.setExclusive(True)
        # Crear todos los botones, después mostrar/ocultar según programa
        for spec in FORMATOS:
            btn = QPushButton(f"  {spec.get('subnombre') or spec['nombre']}")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setMinimumHeight(30)
            btn.setStyleSheet(
                f"QPushButton {{ background:{WHITE}; color:{SLATE_700};"
                f"  border:1px solid {SILVER_300}; border-radius:6px;"
                f"  padding:3px 12px; font-size:12px; }}"
                f"QPushButton:hover {{ background:{ORANGE_SOFT};"
                f"  border-color:{ORANGE}; color:{ORANGE_DARK}; }}"
                f"QPushButton:checked {{ background:{ORANGE}; color:white;"
                f"  border-color:{ORANGE_DARK}; font-weight:600; }}"
            )
            self._fmt_buttons[spec["id"]] = btn
            self._fmt_group.addButton(btn)
            btn.toggled.connect(lambda checked, fid=spec["id"]:
                                self._aplicar_formato(fid) if checked else None)
            fmt_row.addWidget(btn)
        fmt_row.addStretch(1)
        ll.addLayout(fmt_row)

        # 2) Stack con un panel de archivos por formato
        ll.addSpacing(6)
        self._file_stack = QStackedWidget()
        self._file_panels: dict[str, _FilePanel] = {}
        for spec in FORMATOS:
            panel = _FilePanel(spec, on_changed=self._on_archivos_change)
            self._file_panels[spec["id"]] = panel
            self._file_stack.addWidget(panel)
        ll.addWidget(self._file_stack, 1)

        # 3) Botón importar + barra de progreso
        ll.addSpacing(4)
        self.lbl_estado = QLabel("")
        self.lbl_estado.setStyleSheet(f"color:{SLATE_300}; font-size:11px;")
        ll.addWidget(self.lbl_estado)

        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        self.bar.setVisible(False)
        self.bar.setFixedHeight(6)
        self.bar.setTextVisible(False)
        ll.addWidget(self.bar)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.btn_importar = QPushButton(tr("Importar"))
        self.btn_importar.setIcon(icon("guardar"))
        self.btn_importar.setIconSize(QSize(18, 18))
        self.btn_importar.setMinimumHeight(36)
        self.btn_importar.setCursor(Qt.PointingHandCursor)
        from utils.theme import BTN_PRIMARY_SS
        self.btn_importar.setStyleSheet(BTN_PRIMARY_SS)
        self.btn_importar.clicked.connect(self._iniciar_importacion)
        actions.addWidget(self.btn_importar)
        ll.addLayout(actions)

        body.addWidget(col_left, 6)

        # Lado derecho (40%) — instrucciones según formato
        col_right = QFrame()
        col_right.setStyleSheet(
            f"QFrame {{ background:{SILVER_100}; border:1px solid {SILVER_300};"
            f"  border-radius:8px; }}"
        )
        rl = QVBoxLayout(col_right)
        rl.setContentsMargins(14, 12, 14, 12)
        rl.setSpacing(8)

        lbl_h = QLabel(tr("Instrucciones"))
        f3 = QFont(); f3.setWeight(QFont.DemiBold)
        lbl_h.setFont(f3)
        lbl_h.setStyleSheet(f"color:{SLATE_700}; background:transparent; border:none;")
        rl.addWidget(lbl_h)

        from utils.theme import accent_hover as _acc_h
        self.lbl_instr_titulo = QLabel("PowerCost")
        self.lbl_instr_titulo.setStyleSheet(
            f"color:{_acc_h()}; font-weight:600; padding-bottom:2px;"
            f" background:transparent; border:none;"
        )
        rl.addWidget(self.lbl_instr_titulo)

        self.lbl_instrucciones = QLabel("")
        self.lbl_instrucciones.setStyleSheet(f"color:{SLATE_500}; font-size:12px; background:transparent; border:none;")
        self.lbl_instrucciones.setWordWrap(True)
        self.lbl_instrucciones.setTextFormat(Qt.RichText)
        rl.addWidget(self.lbl_instrucciones)
        rl.addStretch(1)

        nota = QLabel(
            "<b>Tip:</b> al importar, la app crea automáticamente los recursos "
            "en el catálogo y normaliza los precios para que un mismo insumo "
            "tenga el mismo precio en todo el proyecto."
        )
        nota.setWordWrap(True)
        nota.setStyleSheet(f"color:{SLATE_300}; font-size:11px; padding-top:6px; background:transparent; border:none;")
        rl.addWidget(nota)

        body.addWidget(col_right, 4)

        _content_vl.addLayout(body, 1)
        root.addWidget(_content, 1)

    def _mk_fmt_button(self, spec: dict) -> QPushButton:
        b = QPushButton(spec["nombre"])
        b.setCheckable(True)
        b.setIcon(icon(spec["icono"]))
        b.setIconSize(QSize(18, 18))
        b.setCursor(Qt.PointingHandCursor)
        b.setMinimumHeight(34)
        b.setStyleSheet(
            f"QPushButton {{ background:{WHITE}; color:{SLATE_700};"
            f"  border:1px solid {SILVER_300}; border-radius:6px;"
            f"  padding:4px 12px; font-weight:500; }}"
            f"QPushButton:hover {{ background:{ORANGE_SOFT};"
            f"  border-color:{ORANGE}; color:{ORANGE_DARK}; }}"
            f"QPushButton:checked {{ background:{ORANGE}; color:white;"
            f"  border-color:{ORANGE_DARK}; font-weight:600; }}"
        )
        return b

    # ── lógica de cambio de programa/formato ────────────────────────────────
    def _aplicar_programa(self, programa_id: str):
        """Activa un programa de origen (nivel 1) y muestra solo sus
        formatos en la fila inferior. Selecciona el primer formato
        del programa por defecto."""
        self._programa_id = programa_id
        # Marcar botón de programa activo
        b = self._prog_buttons.get(programa_id)
        if b and not b.isChecked():
            b.setChecked(True)
        # Mostrar/ocultar botones de formato según el programa
        primer_fmt_id = None
        for spec in FORMATOS:
            btn = self._fmt_buttons.get(spec['id'])
            if not btn:
                continue
            visible = (spec.get('programa') == programa_id)
            btn.setVisible(visible)
            if visible and primer_fmt_id is None:
                primer_fmt_id = spec['id']
        if primer_fmt_id:
            self._aplicar_formato(primer_fmt_id)

    def _aplicar_formato(self, formato_id: str):
        self._formato_id = formato_id
        b = self._fmt_buttons.get(formato_id)
        if b and not b.isChecked():
            b.setChecked(True)

        for i, spec in enumerate(FORMATOS):
            if spec["id"] == formato_id:
                self._file_stack.setCurrentIndex(i)
                self.lbl_instr_titulo.setText(spec["nombre"])
                pasos = "<br>".join(
                    f"<b>{n}.</b>&nbsp; {paso}"
                    for n, paso in enumerate(spec["instrucciones"], 1)
                )
                self.lbl_instrucciones.setText(pasos)
                break

        # Resetear archivos seleccionados al cambiar de formato
        self._archivos = {}
        for panel in self._file_panels.values():
            panel.reset()
        self._on_archivos_change()

    def _on_archivos_change(self):
        """Refresca ``self._archivos`` con los del panel activo y habilita
        Importar si están todos los obligatorios."""
        panel = self._file_panels[self._formato_id]
        self._archivos = panel.archivos_seleccionados()
        spec = next(s for s in FORMATOS if s["id"] == self._formato_id)
        ok = all(self._archivos.get(k) for k, _, req, _ in spec["archivos"] if req)
        self.btn_importar.setEnabled(ok and self._worker is None)

    # ── disparo del worker ──────────────────────────────────────────────────
    def _iniciar_importacion(self):
        if self._worker is not None:
            return

        # Formato S10 nativo: el listado de presupuestos requiere levantar
        # SQL Server (lento), así que va en un worker propio. Cuando termina,
        # _on_s10_listado() muestra el diálogo y dispara el ImportWorker.
        if self._formato_id == "s10_s2k":
            self.btn_importar.setEnabled(False)
            self.bar.setVisible(True)
            self.lbl_estado.setText("Iniciando SQL Server…")
            self._worker = _S10ListWorker(self._archivos["archivo"], parent=self)
            self._worker.progreso.connect(self.lbl_estado.setText)
            self._worker.finished_list.connect(self._on_s10_listado)
            self._worker.failed.connect(self._on_fail)
            self._worker.pedir_descarga.connect(self._on_pedir_descarga_ingeconverter)
            self._worker.start()
            return

        # Pre-paso para formatos multi-proyecto: si la base tiene varios
        # proyectos, pedirle al usuario que elija uno o varios.
        id_ppto = None
        ids_ppto: list[int] | None = None
        if self._formato_id in ("powercost_prs", "ingepresupuestos_db"):
            try:
                if self._formato_id == "powercost_prs":
                    from core.powercost_prs_importer import listar_proyectos_powercost
                    proys = listar_proyectos_powercost(self._archivos["db"])
                else:
                    from core.ingepresupuestos_db_importer import listar_proyectos_db
                    proys = listar_proyectos_db(self._archivos["db"])
            except Exception as e:
                QMessageBox.critical(
                    self, "Error al leer la base",
                    f"No se pudo abrir el archivo:\n\n{e}"
                )
                return
            if not proys:
                QMessageBox.warning(
                    self, "Importar",
                    "La base no contiene proyectos."
                )
                return
            if len(proys) == 1:
                id_ppto = proys[0]['id_ppto']
            else:
                dlg = _SelectPptoDialog(
                    proys, self,
                    origen_texto=("PowerCost (.prs)"
                                  if self._formato_id == "powercost_prs"
                                  else "ingePresupuestos (.db)"),
                )
                if dlg.exec() != QDialog.Accepted:
                    return
                seleccion = dlg.ids_seleccionados
                if not seleccion:
                    return
                if len(seleccion) == 1:
                    id_ppto = seleccion[0]
                else:
                    ids_ppto = seleccion

        self.btn_importar.setEnabled(False)
        self.bar.setVisible(True)
        self.lbl_estado.setText("Iniciando importación…")
        self._worker = _ImportWorker(
            self._formato_id, dict(self._archivos),
            id_ppto=id_ppto, ids_ppto=ids_ppto, parent=self
        )
        self._worker.progreso.connect(self.lbl_estado.setText)
        self._worker.finished_ok.connect(self._on_ok)
        self._worker.finished_multi.connect(self._on_ok_multi)
        self._worker.failed.connect(self._on_fail)
        self._worker.start()

    def _on_pedir_descarga_ingeconverter(self, url: str):
        """IngeConverter no instalado → ofrecer abrir landing en navegador."""
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        self._worker = None
        self.bar.setVisible(False)
        self.lbl_estado.setText("")
        self.btn_importar.setEnabled(True)

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Information)
        box.setWindowTitle("IngeConverter no está instalado")
        box.setText(
            "Para importar archivos <b>.S2K / .bak / .bkf</b> de S10 "
            "directamente, instalá IngeConverter — el complemento gratuito "
            "de IngePresupuestos."
        )
        box.setInformativeText(
            "Se abrirá la descarga en tu navegador. Una vez instalado, "
            "volvé acá e intentá de nuevo."
        )
        btn_open = box.addButton("Descargar IngeConverter", QMessageBox.AcceptRole)
        box.addButton("Cancelar", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is btn_open:
            QDesktopServices.openUrl(QUrl(url))

    def _on_s10_listado(self, presupuestos: list):
        """Segunda fase del flujo S10: muestra diálogo de selección y, si el
        usuario confirma, dispara el _ImportWorker con los cods elegidos."""
        # Limpiar el list-worker para no atrancar la siguiente fase
        self._worker = None

        if not presupuestos:
            self._on_fail("El backup no contiene presupuestos reconocibles.")
            return

        # Adaptar a la forma {id_ppto, nombre, fecha, cd, localidad} que
        # consume _SelectPptoDialog. El "id" acá es el código S10 (string).
        proys_compat = [
            {'id_ppto': p['cod'], 'nombre': p['descripcion'],
             'fecha': '', 'cd': 0, 'localidad': ''}
            for p in presupuestos
        ]

        if len(proys_compat) == 1:
            cods = [proys_compat[0]['id_ppto']]
        else:
            dlg = _SelectPptoDialog(
                proys_compat, self, origen_texto="S10 (.S2K)",
            )
            if dlg.exec() != QDialog.Accepted:
                self.bar.setVisible(False)
                self.lbl_estado.setText("")
                self.btn_importar.setEnabled(True)
                return
            cods = dlg.ids_seleccionados
            if not cods:
                self.bar.setVisible(False)
                self.lbl_estado.setText("")
                self.btn_importar.setEnabled(True)
                return

        # Fase final: convertir e importar los elegidos.
        self.lbl_estado.setText("Iniciando conversión…")
        self._worker = _ImportWorker(
            "s10_s2k", dict(self._archivos), cods_s10=cods, parent=self,
        )
        self._worker.progreso.connect(self.lbl_estado.setText)
        self._worker.finished_ok.connect(self._on_ok)
        self._worker.finished_multi.connect(self._on_ok_multi)
        self._worker.failed.connect(self._on_fail)
        self._worker.start()

    def _on_ok(self, pid: int, resumen: str):
        self.bar.setVisible(False)
        self.lbl_estado.setText("")
        self._worker = None
        QMessageBox.information(
            self, "Importación completa",
            f"Proyecto importado correctamente.\n\n{resumen}"
        )
        self.proyecto_importado.emit(pid)
        self._aplicar_formato(self._formato_id)

    def _on_ok_multi(self, pids: list, resumen: str):
        """Resultado de importación multi-proyecto (.prs PowerCost)."""
        self.bar.setVisible(False)
        self.lbl_estado.setText("")
        self._worker = None
        self.btn_importar.setEnabled(True)
        if not pids:
            QMessageBox.warning(
                self, "Importación sin resultados", resumen
            )
            return
        # Preguntar si abrir el primero o quedarse en dashboard
        msg = QMessageBox(self)
        msg.setWindowTitle("Importación completa")
        msg.setIcon(QMessageBox.Information)
        msg.setText(f"{len(pids)} proyecto(s) importado(s) correctamente.")
        msg.setInformativeText(resumen)
        btn_abrir = msg.addButton("Abrir el primero", QMessageBox.AcceptRole)
        msg.addButton("Volver al inicio", QMessageBox.RejectRole)
        msg.exec()
        if msg.clickedButton() is btn_abrir:
            self.proyecto_importado.emit(pids[0])
        # Si "Volver al inicio", no emitimos nada — el usuario sigue
        # en la vista de Importar y puede navegar manualmente.
        self._aplicar_formato(self._formato_id)

    def _on_fail(self, msg: str):
        self.bar.setVisible(False)
        self.lbl_estado.setText("")
        self._worker = None
        self.btn_importar.setEnabled(True)
        QMessageBox.critical(self, "Error al importar", msg)


# ── Panel reutilizable: lista de campos de archivo según formato ─────────────
class _FilePanel(QFrame):
    """Lista de inputs de archivo correspondientes a un formato."""

    def __init__(self, spec: dict, on_changed):
        super().__init__()
        self._spec = spec
        self._on_changed = on_changed
        self._campos: dict[str, _FileSlot] = {}
        self._build()

    def _build(self):
        self.setObjectName("filePanel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            "QFrame#filePanel { background:transparent; border:none; }"
        )
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { background:transparent; border:none; }")
        inner = QWidget()
        scroll.setWidget(inner)
        iv = QVBoxLayout(inner)
        iv.setContentsMargins(0, 0, 0, 0)
        iv.setSpacing(8)

        for n, (key, etiqueta, req, ayuda) in enumerate(self._spec["archivos"], 1):
            slot = _FileSlot(
                indice=n, key=key, etiqueta=etiqueta, requerido=req,
                ayuda=ayuda, ext=self._spec["ext"], on_changed=self._on_changed,
            )
            self._campos[key] = slot
            iv.addWidget(slot)
        iv.addStretch(1)

        v.addWidget(scroll, 1)

    def reset(self):
        for s in self._campos.values():
            s.limpiar()

    def archivos_seleccionados(self) -> dict[str, str]:
        return {k: s.path for k, s in self._campos.items() if s.path}


# ── Slot individual para un archivo ──────────────────────────────────────────
class _FileSlot(QFrame):
    def __init__(self, *, indice: int, key: str, etiqueta: str, requerido: bool,
                 ayuda: str, ext: str, on_changed):
        super().__init__()
        self.key = key
        self.requerido = requerido
        self._ext = ext
        self._etiqueta = etiqueta
        self._on_changed = on_changed
        self.path: str | None = None
        self._build(indice, etiqueta, ayuda)

    def _build(self, indice: int, etiqueta: str, ayuda: str):
        from utils.theme import apply_shadow
        self.setObjectName("fileSlot")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"QFrame#fileSlot {{ background:{WHITE}; "
            f"  border:1px solid {SILVER_300}; border-radius:8px; }}"
        )
        apply_shadow(self, 'sm')
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 10, 14, 12)
        v.setSpacing(2)

        head = QHBoxLayout()
        head.setSpacing(6)
        badge = QLabel(str(indice))
        badge.setFixedSize(22, 22)
        badge.setAlignment(Qt.AlignCenter)
        if self.requerido:
            badge.setStyleSheet(
                f"background:{ORANGE}; color:white; border-radius:10px;"
                f"  font-weight:700; font-size:11px;"
            )
        else:
            badge.setStyleSheet(
                f"background:{SILVER_200}; color:{SLATE_500};"
                f"  border-radius:10px; font-weight:600; font-size:11px;"
            )
        head.addWidget(badge)

        ttl = QLabel(etiqueta)
        ttf = QFont(); ttf.setWeight(QFont.DemiBold)
        ttl.setFont(ttf)
        ttl.setStyleSheet(
            f"color:{SLATE_700}; background:transparent; border:none;"
        )
        head.addWidget(ttl)

        from utils.i18n import tr as _tr
        if self.requerido:
            tag = QLabel(_tr("Requerido"))
            tag.setStyleSheet(
                f"color:{RED_500}; font-size:10px; font-weight:600;"
                f"  padding:1px 6px; background:transparent; border:none;"
            )
        else:
            tag = QLabel(_tr("Opcional"))
            tag.setStyleSheet(
                f"color:{SLATE_300}; font-size:10px; padding:1px 6px;"
                f"  background:transparent; border:none;"
            )
        head.addWidget(tag)
        head.addStretch(1)
        v.addLayout(head)

        h = QLabel(ayuda)
        h.setWordWrap(True)
        h.setStyleSheet(
            f"color:{SLATE_300}; font-size:11px; padding-left:28px;"
            f"  background:transparent; border:none;"
        )
        v.addWidget(h)

        sel = QHBoxLayout()
        sel.setContentsMargins(28, 4, 0, 0)
        sel.setSpacing(6)
        self.lbl_path = QLabel(_tr("Sin archivo seleccionado"))
        self.lbl_path.setStyleSheet(
            f"color:{SLATE_500}; padding:5px 8px; background:{SILVER_100};"
            f"  border:1px solid {SILVER_300}; border-radius:4px;"
        )
        self.lbl_path.setMinimumWidth(200)
        self.lbl_path.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        sel.addWidget(self.lbl_path, 1)

        self.btn_pick = QPushButton(_tr("Examinar") + "…")
        self.btn_pick.setIcon(icon("folder"))
        self.btn_pick.setIconSize(QSize(16, 16))
        self.btn_pick.setCursor(Qt.PointingHandCursor)
        self.btn_pick.setStyleSheet(
            f"QPushButton {{ background:{WHITE}; color:{SLATE_700};"
            f"  border:1px solid {SILVER_300}; border-radius:4px;"
            f"  padding:4px 12px; }}"
            f"QPushButton:hover {{ background:{ORANGE_SOFT};"
            f"  border-color:{ORANGE}; color:{ORANGE_DARK}; }}"
        )
        self.btn_pick.clicked.connect(self._abrir_dialog)
        sel.addWidget(self.btn_pick)

        self.btn_quitar = QPushButton()
        self.btn_quitar.setIcon(icon("cerrar"))
        self.btn_quitar.setIconSize(QSize(14, 14))
        self.btn_quitar.setFixedWidth(28)
        self.btn_quitar.setCursor(Qt.PointingHandCursor)
        self.btn_quitar.setToolTip(_tr("Quitar"))
        self.btn_quitar.setVisible(False)
        self.btn_quitar.setStyleSheet(
            f"QPushButton {{ background:transparent; border:1px solid {SILVER_300};"
            f"  border-radius:4px; }}"
            f"QPushButton:hover {{ background:#FFEDED; border-color:{RED_500}; }}"
        )
        self.btn_quitar.clicked.connect(self.limpiar)
        sel.addWidget(self.btn_quitar)

        v.addLayout(sel)

    def _abrir_dialog(self):
        p, _ = QFileDialog.getOpenFileName(
            self, f"Seleccionar {self._etiqueta}", "", self._ext
        )
        if p:
            self.path = p
            self.lbl_path.setText(Path(p).name)
            self.lbl_path.setStyleSheet(
                f"color:{SLATE_700}; padding:5px 8px; background:#EFFAEF;"
                f"  border:1px solid {GREEN_500}; border-radius:4px;"
                f"  font-weight:500;"
            )
            self.btn_quitar.setVisible(True)
            self._on_changed()

    def limpiar(self):
        self.path = None
        from utils.i18n import tr as _tr2
        self.lbl_path.setText(_tr2("Sin archivo seleccionado"))
        self.lbl_path.setStyleSheet(
            f"color:{SLATE_500}; padding:5px 8px; background:{SILVER_100};"
            f"  border:1px solid {SILVER_300}; border-radius:4px;"
        )
        self.btn_quitar.setVisible(False)
        self._on_changed()


# ── Diálogo de selección de proyecto (PowerCost multi-proyecto) ─────────────
class _SelectPptoDialog(QDialog):
    """Diálogo modal para elegir un proyecto cuando el .prs contiene
    cientos. Incluye búsqueda incremental por nombre."""

    def __init__(self, proys: list[dict], parent=None, *,
                 origen_texto: str = "base de datos"):
        super().__init__(parent)
        self.proys = proys
        self.ids_seleccionados: list = []  # int (.prs/.db) o str (S10 cod)

        from utils.i18n import tr
        self._tr = tr
        self.setWindowTitle(tr("Seleccionar proyectos"))
        self.setWindowModality(Qt.WindowModal)
        self.setWindowFlags(
            Qt.Window | Qt.WindowCloseButtonHint | Qt.WindowMinMaxButtonsHint
        )
        self.setMinimumSize(780, 560)
        self.setStyleSheet(f"QDialog {{ background:{SILVER_100}; }}")

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)

        # Header
        ttl = QLabel(self._tr("Seleccionar proyectos"))
        ttl.setStyleSheet(
            f"color:{SLATE_700}; font-size:15px; font-weight:700; background:transparent;"
        )
        root.addWidget(ttl)
        sub = QLabel(
            f"El archivo {origen_texto} contiene <b>{len(proys)} proyectos</b>. "
            "Selecciona uno o varios (Ctrl+Click o Shift+Click), o usa "
            "<b>Seleccionar todos</b>. Doble clic importa solo ese proyecto."
        )
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color:{SLATE_300}; font-size:12px;")
        root.addWidget(sub)

        # Búsqueda + acciones rápidas
        top = QHBoxLayout()
        top.setSpacing(8)
        self.inp = QLineEdit()
        self.inp.setPlaceholderText(self._tr("Buscar") + "…")
        self.inp.setFixedHeight(34)
        self.inp.setStyleSheet(
            f"QLineEdit {{ background:white; border:1px solid {SILVER_300}; "
            f"  border-radius:6px; padding:0 12px; font-size:13px; }}"
        )
        self.inp.textChanged.connect(self._filtrar)
        top.addWidget(self.inp, 1)

        self.btn_all = QPushButton(self._tr("Seleccionar todos"))
        self.btn_all.setCursor(Qt.PointingHandCursor)
        self.btn_all.setFixedHeight(34)
        self.btn_all.setStyleSheet(
            f"QPushButton {{ background:{WHITE}; color:{SLATE_700}; "
            f"  border:1px solid {SILVER_300}; border-radius:6px; "
            f"  padding:0 14px; font-size:12px; }}"
            f"QPushButton:hover {{ background:{ORANGE_SOFT}; "
            f"  border-color:{ORANGE}; color:{ORANGE_DARK}; }}"
        )
        self.btn_all.clicked.connect(self._seleccionar_todos_visibles)
        top.addWidget(self.btn_all)

        self.btn_none = QPushButton(self._tr("Deseleccionar"))
        self.btn_none.setCursor(Qt.PointingHandCursor)
        self.btn_none.setFixedHeight(34)
        self.btn_none.setStyleSheet(self.btn_all.styleSheet())
        self.btn_none.clicked.connect(lambda: self.lst.clearSelection())
        top.addWidget(self.btn_none)
        root.addLayout(top)

        # Lista (multi-selección)
        from PySide6.QtWidgets import QAbstractItemView
        self.lst = QListWidget()
        self.lst.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.lst.setStyleSheet(
            f"QListWidget {{ background:white; border:1px solid {SILVER_300}; "
            f"  border-radius:8px; padding:4px; font-size:12px; }}"
            f"QListWidget::item {{ padding:6px 10px; border-bottom:1px solid #F0F1F2; }}"
            f"QListWidget::item:selected {{ background:{ORANGE_SOFT}; "
            f"  color:{ORANGE_DARK}; border-radius:4px; }}"
        )
        self.lst.itemDoubleClicked.connect(self._aceptar_doble_clic)
        self.lst.itemSelectionChanged.connect(self._actualizar_contador)
        root.addWidget(self.lst, 1)
        self._refrescar()

        # Footer: contador + botones
        self.lbl_count = QLabel("0 seleccionados")
        self.lbl_count.setStyleSheet(
            f"color:{SLATE_500}; font-size:12px; font-weight:600;"
        )
        hl = QHBoxLayout()
        hl.setSpacing(8)
        hl.addWidget(self.lbl_count)
        hl.addStretch(1)
        btn_cancel = QPushButton(self._tr("Cancelar"))
        btn_cancel.setCursor(Qt.PointingHandCursor)
        btn_cancel.setFixedHeight(34)
        btn_cancel.setStyleSheet(
            f"QPushButton {{ background:{WHITE}; color:{SLATE_700}; "
            f"  border:1px solid {SILVER_300}; border-radius:6px; "
            f"  padding:0 18px; font-size:12px; }}"
            f"QPushButton:hover {{ background:#F0F2F5; }}"
        )
        btn_cancel.clicked.connect(self.reject)
        hl.addWidget(btn_cancel)
        self.btn_ok = QPushButton(self._tr("Importar"))
        self.btn_ok.setCursor(Qt.PointingHandCursor)
        self.btn_ok.setFixedHeight(34)
        self.btn_ok.setEnabled(False)
        from utils.theme import BTN_PRIMARY_SS
        self.btn_ok.setStyleSheet(BTN_PRIMARY_SS)
        self.btn_ok.clicked.connect(self._aceptar)
        hl.addWidget(self.btn_ok)
        root.addLayout(hl)

    def _refrescar(self, filtro: str = ''):
        self.lst.clear()
        from utils.formatting import norm_busqueda
        f = norm_busqueda((filtro or '').strip())
        for p in self.proys:
            if f and f not in norm_busqueda(p['nombre']):
                continue
            extras = []
            if p['fecha']:
                extras.append(p['fecha'].split()[0])
            if p['cd'] > 0:
                extras.append(f"CD S/ {p['cd']:,.2f}")
            if p['localidad']:
                extras.append(p['localidad'])
            tail = "   ·   ".join(extras) if extras else ""
            text = f"#{p['id_ppto']:>4}    {p['nombre']}"
            if tail:
                text += f"\n          {tail}"
            it = QListWidgetItem(text)
            it.setData(Qt.UserRole, p['id_ppto'])
            self.lst.addItem(it)
        self._actualizar_contador()

    def _filtrar(self, texto: str):
        if len(texto) < 2 and texto != '':
            return
        self._refrescar(texto)

    def _seleccionar_todos_visibles(self):
        for i in range(self.lst.count()):
            self.lst.item(i).setSelected(True)

    def _actualizar_contador(self):
        # _refrescar() puede llamar a este método durante __init__ antes de
        # que lbl_count/btn_ok se hayan creado. Defensivo:
        if not hasattr(self, 'lbl_count'):
            return
        n = len(self.lst.selectedItems())
        self.lbl_count.setText(
            f"{n} seleccionados  ·  total visible: {self.lst.count()}"
        )
        self.btn_ok.setEnabled(n > 0)

    def _aceptar_doble_clic(self, item):
        # Doble clic: importa solo ese (selección única)
        self.ids_seleccionados = [item.data(Qt.UserRole)]
        self.accept()

    def _aceptar(self):
        items = self.lst.selectedItems()
        if not items:
            return
        self.ids_seleccionados = [it.data(Qt.UserRole) for it in items]
        self.accept()
