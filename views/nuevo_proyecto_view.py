# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""Vista de nuevo proyecto — página completa en el stack (no diálogo).

Patrón Elementary OS: el contenido reemplaza el área principal,
con botón ← para volver y botón primario "Crear proyecto →".
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QScrollArea,
    QLabel, QLineEdit, QPushButton, QComboBox, QDoubleSpinBox,
    QSpinBox, QFrame, QSizePolicy, QTextEdit, QDialog, QMessageBox
)
from PySide6.QtCore import Qt, Signal, QDate, QSize, QThread
from PySide6.QtGui import QFont, QColor, QIntValidator

from core.config import MONEDAS, ESTADOS_PROYECTO
from core.database import get_db, get_config
from models.usuario import Usuario
from utils.icons import icon, icon_colored

# ── Paleta Elementary ─────────────────────────────────────────────────────────
BLUE_500  = "#F37329"
BLUE_700  = "#C0621A"
SLATE_700 = "#273445"
SLATE_500 = "#485A6C"
SLATE_300 = "#667885"
SLATE_100 = "#95A3AB"
SILVER_100 = "#F8F9FA"
SILVER_300 = "#D4D4D4"
RED_500   = "#C6262E"
GREEN_500 = "#68B723"
PAGE_BG   = "#EEF2F7"   # canvas slate-100 detrás de las cards (mismo patrón)


def _inp(placeholder: str = "", min_h: int = 30) -> QLineEdit:
    w = QLineEdit()
    w.setPlaceholderText(placeholder)
    w.setMinimumHeight(min_h)
    return w


# Prompt de ejemplo para las Notas del proyecto (se muestra DENTRO del cuadro
# como texto «fantasma» gris; al hacer clic para escribir se borra solo).
_EJEMPLO_NOTAS = (
    "Ejemplo:\n\n"
    "Presupuesto de un colegio de 2 pisos (6 aulas + losa deportiva) en "
    "Yanaquihua, provincia de Condesuyos, Arequipa, a 2,800 msnm. Clima frío "
    "y seco, con lluvias de diciembre a marzo. El acceso es por trocha "
    "carrozable a 4 horas de Arequipa, lo que encarece el flete y baja los "
    "rendimientos de mano de obra. El terreno es rocoso (capacidad portante "
    "1.5 kg/cm²), zona sísmica 3; sistema aporticado de concreto armado con "
    "albañilería. No hay red eléctrica (grupo electrógeno) y el agua es de "
    "pozo. La mano de obra calificada es escasa, por lo que se traslada "
    "cuadrilla desde Arequipa. Plazo 120 días, modalidad a suma alzada."
)


class _GhostTextEdit(QTextEdit):
    """QTextEdit con texto de ejemplo «fantasma» dentro del cuadro: se ve en
    gris, al enfocar para escribir se borra, y al salir vacío reaparece. No se
    guarda si el usuario no escribió nada (`texto_real()` devuelve '')."""

    def __init__(self, ghost: str, parent=None):
        super().__init__(parent)
        self._ghost = ghost
        self._is_ghost = False
        self.mostrar_ghost()

    def mostrar_ghost(self):
        self.setPlainText(self._ghost)
        self.setStyleSheet("QTextEdit { color:#94A3B8; font-style:italic; }")
        self._is_ghost = True

    def texto_real(self) -> str:
        return "" if self._is_ghost else self.toPlainText().strip()

    def set_texto(self, txt: str):
        if txt and txt.strip():
            self._is_ghost = False
            self.setStyleSheet("")
            self.setPlainText(txt)
        else:
            self.mostrar_ghost()

    def focusInEvent(self, e):
        if self._is_ghost:
            self._is_ghost = False
            self.setStyleSheet("")
            self.clear()
        super().focusInEvent(e)

    def focusOutEvent(self, e):
        if not self.toPlainText().strip():
            self.mostrar_ghost()
        super().focusOutEvent(e)


def _cmb(opciones: list[tuple[str, str]], min_h: int = 30) -> QComboBox:
    c = QComboBox()
    for label, data in opciones:
        c.addItem(label, data)
    c.setMinimumHeight(min_h)
    return c


def _label(texto: str, required: bool = False) -> QLabel:
    lbl = QLabel(f"{texto} <span style='color:{RED_500};'>*</span>" if required else texto)
    lbl.setStyleSheet(
        f"color:{SLATE_500}; font-size:12px; font-weight:600;"
        f" background:transparent; border:none;"
    )
    lbl.setTextFormat(Qt.RichText)
    return lbl


def _section_header(texto: str) -> QFrame:
    frame = QFrame()
    frame.setStyleSheet(f"background:white; border-radius:8px; border: 1px solid {SILVER_300};")
    hl = QHBoxLayout(frame)
    hl.setContentsMargins(16, 12, 16, 12)
    lbl = QLabel(texto)
    lbl.setStyleSheet(
        f"color:{SLATE_700}; font-size:13px; font-weight:700;"
        f" background:transparent; border:none;"
    )
    hl.addWidget(lbl)
    return frame


# ═══════════════════════════════════════════════════════════════════════════════
# Workers de elevación VIVOS (referencia fuerte a nivel módulo). Sin esto, al
# hacer varios clics seguidos en el mapa cada clic creaba un QThread nuevo y el
# anterior, aún corriendo su request de red, perdía su única referencia → Python
# lo recolectaba → «QThread: Destroyed while thread is still running» → la app
# abortaba. El set los mantiene vivos hasta que terminan (se autoeliminan en
# `finished`) y sobrevive aunque el diálogo se cierre.
_ELEV_WORKERS: set = set()


class _WorkerElevacion(QThread):
    """Consulta la altitud (msnm) de un punto a Open-Meteo (gratis, sin key)."""
    listo = Signal(float)   # altitud; -9999 si falla

    def __init__(self, lat, lon):
        super().__init__()
        self.lat = lat
        self.lon = lon

    def run(self):
        try:
            import urllib.request
            import json
            url = ("https://api.open-meteo.com/v1/elevation?"
                   f"latitude={self.lat:.6f}&longitude={self.lon:.6f}")
            with urllib.request.urlopen(url, timeout=12) as r:
                data = json.load(r)
            alt = (data.get('elevation') or [None])[0]
            self.listo.emit(float(alt) if alt is not None else -9999.0)
        except Exception:
            self.listo.emit(-9999.0)


class _DialogMapa(QDialog):
    """Mapa OpenStreetMap (QtLocation) para marcar la ubicación EXACTA del
    proyecto. Opcional: requiere internet para ver los tiles. Si el mapa no
    carga (sin conexión o sin el módulo), muestra un aviso y el formulario
    sigue funcionando con la ubicación por distrito."""

    def __init__(self, parent, center=None, mark=None):
        # Top-level INDEPENDIENTE, SIN padre transitorio. En X11/Wayland un
        # QDialog con padre queda como `WM_TRANSIENT_FOR` de la ventana
        # principal y el compositor acopla sus geometrías → al arrastrar el mapa
        # la ventana principal se redimensionaba/movía con él (no pasa en
        # Windows). `parent.window()` no bastó: seguía siendo transitorio del
        # top-level. Sin padre no hay transient_for; la modalidad se mantiene con
        # `exec()` + `ApplicationModal`, y centramos a mano sobre la ventana dueña.
        super().__init__(None)
        self._owner = parent.window() if parent is not None else None
        self._centrado = False
        # mark = (lat, lon) o (lat, lon, altitud)
        self._lat = mark[0] if mark else None
        self._lon = mark[1] if mark else None
        self._altitud = mark[2] if (mark and len(mark) > 2) else None
        self._elev_worker = None
        self.setWindowTitle("Ubicar el proyecto en el mapa")
        self.setWindowModality(Qt.ApplicationModal)  # bloquea la app sin acoplar geometría
        self.resize(760, 580)
        vl = QVBoxLayout(self)
        vl.setContentsMargins(12, 12, 12, 12)
        vl.setSpacing(8)

        self._root = None
        top = QHBoxLayout()
        info = QLabel("Haz clic en el mapa para marcar dónde queda la obra. "
                      "Arrastra para moverte, rueda para el zoom.")
        info.setWordWrap(True)
        info.setStyleSheet("font-size:11px; color:#667885;")
        top.addWidget(info, 1)
        self._btn_sat = QPushButton("🛰  Satélite")
        self._btn_sat.setCheckable(True)
        self._btn_sat.setFixedHeight(26)
        self._btn_sat.setCursor(Qt.PointingHandCursor)
        self._btn_sat.setToolTip("Alternar entre mapa de calles e imagen satelital")
        self._btn_sat.setStyleSheet(
            "QPushButton { background:#F0F1F2; color:#273445; border:1px solid #CBD5E1;"
            " border-radius:6px; padding:2px 12px; font-size:11px; }"
            "QPushButton:checked { background:#273445; color:white; border-color:#273445; }")
        self._btn_sat.toggled.connect(
            lambda on: self._root.setProperty("satelite", on) if self._root else None)
        top.addWidget(self._btn_sat)
        vl.addLayout(top)

        try:
            # Pre-cargar QtLocation/QtPositioning DESDE PYTHON antes de instanciar
            # el QML. Importarlos carga sus DLL (Qt6Location/Qt6Positioning) en el
            # proceso; sin esto, bajo PyInstaller/MSIX el plugin QML del mapa
            # falla con «No se puede cargar la biblioteca» en `import QtLocation`
            # (línea 2 del map.qml), porque sus dependencias no están en memoria
            # ni en la ruta de búsqueda del cargador de plugins QML.
            from PySide6 import QtPositioning, QtLocation  # noqa: F401
            # …pero eso NO basta: MapView (qrc:/.../QtLocation/MapView.qml) usa el
            # value-type QtPositioning.geoCoordinate, registrado por el plugin QML
            # positioningquickplugin.dll → que depende de Qt6PositioningQuick.dll,
            # una DLL que NINGÚN import de Python carga. Bajo MSIX el loader no la
            # resuelve sola → el plugin no carga → MapView queda «unavailable». La
            # forzamos en memoria por ruta (mismo mecanismo que el preload de
            # arriba) y registramos el dir de PySide6 para que el cargador de
            # plugins QML encuentre el resto de Qt6*.dll del bundle (geoservicios
            # incluido). Solo Windows; en Linux/macOS el loader sí las resuelve.
            import sys as _sys
            if _sys.platform == "win32":
                import os as _os, ctypes as _ctypes, PySide6 as _ps6
                _pysd = _os.path.dirname(_ps6.__file__)
                try:
                    _os.add_dll_directory(_pysd)
                except Exception:
                    pass
                try:
                    _ctypes.WinDLL(_os.path.join(_pysd, "Qt6PositioningQuick.dll"))
                except Exception:
                    pass
            from PySide6.QtQuickWidgets import QQuickWidget
            from PySide6.QtCore import QUrl
            from core.config import BASE_DIR, USER_DATA_DIR
            self._qw = QQuickWidget()
            self._qw.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
            self._qw.setMinimumHeight(430)
            # Repositorio de proveedores de tiles (bundle) y caché propio.
            # Se inyectan como context properties ANTES de setSource para que
            # el Plugin OSM del QML nazca con ellos (los PluginParameter se leen
            # una sola vez al inicializar el plugin). Sin esto, el plugin usa el
            # servicio hospedado de Qt → mosaicos "API Key Required" al hacer zoom.
            prov_url = QUrl.fromLocalFile(
                str(BASE_DIR / "resources" / "osm_providers") + "/").toString()
            cache_dir = USER_DATA_DIR / "map_cache"
            cache_dir.mkdir(parents=True, exist_ok=True)
            ctx = self._qw.rootContext()
            ctx.setContextProperty("ingepProvidersUrl", prov_url)
            ctx.setContextProperty("ingepCacheDir", str(cache_dir))
            self._qw.setSource(QUrl.fromLocalFile(str(BASE_DIR / "resources" / "map.qml")))
            if self._qw.status() == QQuickWidget.Status.Error:
                msgs = "; ".join(e.toString() for e in self._qw.errors())
                raise RuntimeError(msgs or "No se pudo cargar el mapa.")
            root = self._qw.rootObject()
            self._root = root
            cy, cx = (center or (self._lat, self._lon) or (-12.0464, -77.0428))
            if cy and cx:
                root.setProperty("centerLat", float(cy))
                root.setProperty("centerLon", float(cx))
            if self._lat is not None and self._lon is not None:
                root.setProperty("markLat", float(self._lat))
                root.setProperty("markLon", float(self._lon))
                root.setProperty("hasMark", True)
            root.picked.connect(self._on_picked)
            vl.addWidget(self._qw, 1)
        except Exception as e:
            err = QLabel("No se pudo cargar el mapa (revisa tu conexión a "
                         "internet). Puedes seguir usando solo la ubicación "
                         "por distrito.\n\n" + str(e)[:200])
            err.setWordWrap(True)
            err.setStyleSheet("color:#C6262E; font-size:11px; padding:24px;")
            vl.addWidget(err, 1)

        self._lbl_coords = QLabel(self._fmt_coords())
        self._lbl_coords.setStyleSheet("font-size:12px; color:#273445; font-weight:700;")
        vl.addWidget(self._lbl_coords)

        hl = QHBoxLayout()
        hl.addStretch()
        btn_cancel = QPushButton("Cancelar")
        btn_cancel.setMinimumHeight(32)
        btn_cancel.clicked.connect(self.reject)
        hl.addWidget(btn_cancel)
        self._btn_use = QPushButton("Usar esta ubicación")
        self._btn_use.setMinimumHeight(32)
        from utils.theme import BTN_PRIMARY_SS
        self._btn_use.setStyleSheet(BTN_PRIMARY_SS)
        self._btn_use.setEnabled(self._lat is not None)
        self._btn_use.clicked.connect(self.accept)
        hl.addWidget(self._btn_use)
        vl.addLayout(hl)

    def showEvent(self, e):
        # Sin padre el WM no centra el diálogo → lo colocamos sobre la ventana
        # dueña una sola vez (move() funciona bajo xcb/XWayland) y lo traemos al
        # frente (un top-level app-modal sin padre podría nacer detrás).
        super().showEvent(e)
        if not self._centrado:
            self._centrado = True
            if self._owner is not None:
                og = self._owner.frameGeometry()
                self.move(og.center().x() - self.width() // 2,
                          og.center().y() - self.height() // 2)
            self.raise_()
            self.activateWindow()

    def _fmt_coords(self) -> str:
        if self._lat is None:
            return "Sin marcar — haz clic en el mapa"
        if self._altitud == "...":
            alt_txt = " · Altitud: obteniendo…"
        elif isinstance(self._altitud, (int, float)):
            alt_txt = f" · Altitud: {int(round(self._altitud))} msnm"
        else:
            alt_txt = ""
        try:
            from core.ubigeo import latlon_a_utm
            u = latlon_a_utm(self._lat, self._lon)
            if u:
                return (f"📍  UTM WGS84:  {u['etiqueta']}{alt_txt}\n"
                        f"      (geográficas: {self._lat:.6f}, {self._lon:.6f})")
        except Exception:
            pass
        return f"📍  Lat {self._lat:.6f},  Lon {self._lon:.6f}{alt_txt}"

    def _on_picked(self, lat, lon):
        self._lat = float(lat)
        self._lon = float(lon)
        self._altitud = "..."          # marca «obteniendo»
        self._lbl_coords.setText(self._fmt_coords())
        self._btn_use.setEnabled(True)
        # Consultar la altitud exacta del punto (en hilo, requiere internet).
        # Token: si el usuario hace varios clics, solo el ÚLTIMO actualiza la UI
        # (los resultados de clics previos llegan tarde y se descartan).
        self._elev_token = getattr(self, '_elev_token', 0) + 1
        token = self._elev_token
        w = _WorkerElevacion(self._lat, self._lon)
        _ELEV_WORKERS.add(w)   # referencia fuerte: evita el crash por GC

        def _on_listo(alt, _tok=token):
            try:
                if _tok == self._elev_token:   # solo el clic más reciente
                    self._on_altitud(alt)
            except RuntimeError:
                pass   # el diálogo ya se cerró (objeto C++ destruido)

        def _cleanup(_w=w):
            _ELEV_WORKERS.discard(_w)
            _w.deleteLater()

        w.listo.connect(_on_listo)
        w.finished.connect(_cleanup)
        w.start()

    def _on_altitud(self, alt):
        self._altitud = alt if alt > -9000 else None
        self._lbl_coords.setText(self._fmt_coords())

    def coords(self):
        alt = self._altitud if isinstance(self._altitud, (int, float)) else None
        return (self._lat, self._lon, alt)


class NuevoProyectoView(QWidget):
# ═══════════════════════════════════════════════════════════════════════════════

    proyecto_creado  = Signal(int)   # id del proyecto creado
    proyecto_editado = Signal(int)   # id del proyecto editado
    cancelado        = Signal()      # volver atrás

    def __init__(self, usuario: Usuario, proyecto_id: int | None = None, parent=None):
        super().__init__(parent)
        self.usuario      = usuario
        self._proyecto_id = proyecto_id          # None = crear, int = editar
        self._jornada_original = 8
        self.setStyleSheet(f"background:{PAGE_BG};")
        self._build_ui()
        if proyecto_id is not None:
            self._cargar_datos(proyecto_id)

    # ── Construcción ──────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._make_topbar())

        # Área scrolleable
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(f"background:{PAGE_BG};")

        contenido = QWidget()
        contenido.setStyleSheet(f"background:{PAGE_BG};")
        # Columna central con ancho máximo: en ventana maximizada los campos
        # ya no se estiran a todo el ancho; se expanden hasta ~940px y el resto
        # del espacio queda repartido a los lados (formulario centrado).
        outer = QHBoxLayout(contenido)
        outer.setContentsMargins(32, 24, 32, 32)
        outer.setSpacing(0)

        col_w = QWidget()
        col_w.setMaximumWidth(940)
        vl = QVBoxLayout(col_w)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(12)
        vl.addWidget(self._seccion_general())
        vl.addWidget(self._seccion_financiero())
        vl.addWidget(self._seccion_descripcion())
        # Footer (botones) justo debajo de las tarjetas — sin stretch previo,
        # que los empujaba al fondo de la ventana.
        vl.addWidget(self._make_footer())
        vl.addStretch()

        outer.addStretch(1)
        outer.addWidget(col_w, stretch=8)
        outer.addStretch(1)

        scroll.setWidget(contenido)
        root.addWidget(scroll, stretch=1)

    # ── Topbar ────────────────────────────────────────────────────────────────

    def _make_topbar(self) -> QFrame:
        """Topbar oscuro slate-700 (mismo patrón que Cronograma / Hoja de
        Metrados / Fórmula Polinómica) para consistencia visual entre vistas
        ancladas al stack del proyecto."""
        bar = QFrame()
        bar.setObjectName("topbarNuevo")
        bar.setAttribute(Qt.WA_StyledBackground, True)
        bar.setFixedHeight(44)
        bar.setStyleSheet(
            f"QFrame#topbarNuevo {{ background:{SLATE_700}; border:none; }}"
        )
        hl = QHBoxLayout(bar)
        hl.setContentsMargins(12, 0, 12, 0)
        hl.setSpacing(10)

        from utils.i18n import tr
        btn_back = QPushButton("← " + tr("Inicio"))
        btn_back.setCursor(Qt.PointingHandCursor)
        btn_back.setStyleSheet(
            f"QPushButton {{ background:rgba(255,255,255,0.12); color:white;"
            f" border:1px solid rgba(255,255,255,0.25); border-radius:6px;"
            f" font-size:11px; padding:4px 12px; }}"
            f"QPushButton:hover {{ background:rgba(255,255,255,0.22); }}"
        )
        btn_back.clicked.connect(self.cancelado.emit)
        hl.addWidget(btn_back)

        titulo = tr("EDITAR PROYECTO") if self._proyecto_id else tr("NUEVO PROYECTO")
        lbl = QLabel(titulo)
        lbl.setStyleSheet(
            "color:white; font-size:13px; font-weight:700; letter-spacing:0.5px;"
            " background:transparent; border:none;"
        )
        lbl.setAlignment(Qt.AlignCenter)
        hl.addWidget(lbl, stretch=1)

        self.lbl_error = QLabel("")
        self.lbl_error.setStyleSheet(
            "color:#FFCDD2; font-size:11px; font-weight:600;"
            " background:transparent; border:none;"
        )
        hl.addWidget(self.lbl_error)

        return bar

    # ── Sección: Información general ──────────────────────────────────────────

    def _seccion_general(self) -> QWidget:
        card = QFrame()
        card.setObjectName("formCard")
        card.setAttribute(Qt.WA_StyledBackground, True)
        card.setStyleSheet(
            f"QFrame#formCard {{ background:white; border-radius:8px;"
            f" border:1px solid {SILVER_300}; }}"
        )
        vl = QVBoxLayout(card)
        vl.setContentsMargins(24, 16, 24, 18)
        vl.setSpacing(12)

        from utils.i18n import tr
        # Cabecera de sección
        lbl_sec = QLabel(tr("Información general"))
        lbl_sec.setStyleSheet(
            f"color:{SLATE_700}; font-size:13px; font-weight:700;"
            f" border:none; background:transparent;"
        )
        vl.addWidget(lbl_sec)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color:{SILVER_300};"); sep.setFixedHeight(1)
        vl.addWidget(sep)

        grid = QGridLayout()
        grid.setHorizontalSpacing(20)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)

        # Fila 0: Nombre (ancho completo)
        grid.addWidget(_label(tr("Nombre del proyecto"), required=True), 0, 0)
        self.inp_nombre = _inp(tr("Nombre del proyecto"))
        self.inp_nombre.setMinimumHeight(32)
        self.inp_nombre.setStyleSheet(
            f"QLineEdit {{ border:1.5px solid {SILVER_300}; border-radius:6px;"
            f" padding:0 10px; font-size:13px; }}"
            f"QLineEdit:focus {{ border-color:{BLUE_500}; }}"
        )
        grid.addWidget(self.inp_nombre, 0, 1, 1, 3)

        # Fila 1: Cliente | Ubicación
        grid.addWidget(_label(tr("Cliente")), 1, 0)
        self.inp_cliente = _inp(tr("Cliente"))
        grid.addWidget(self.inp_cliente, 1, 1)
        grid.addWidget(_label(tr("Ubicación")), 1, 2)
        self._latitud = None
        self._longitud = None
        self._altitud = None
        _ubic_cont = QWidget()
        _uh = QHBoxLayout(_ubic_cont)
        _uh.setContentsMargins(0, 0, 0, 0)
        _uh.setSpacing(4)
        self.inp_ubic = _inp(tr("Ubicación"))
        self.inp_ubic.setPlaceholderText(tr("Distrito… (autocompleta UBIGEO)"))
        _uh.addWidget(self.inp_ubic, 1)
        self.btn_mapa = QPushButton()
        self.btn_mapa.setIcon(icon("ubicacion"))
        self.btn_mapa.setIconSize(QSize(18, 18))
        self.btn_mapa.setFixedSize(30, 30)
        self.btn_mapa.setCursor(Qt.PointingHandCursor)
        self.btn_mapa.setToolTip(tr("Ubicar en el mapa (opcional, requiere internet)"))
        self.btn_mapa.setStyleSheet(
            "QPushButton { background:transparent; border:none; }"
            "QPushButton:hover { background:#F0F1F2; border-radius:6px; }")
        self.btn_mapa.clicked.connect(self._abrir_mapa)
        _uh.addWidget(self.btn_mapa)
        grid.addWidget(_ubic_cont, 1, 3)
        self._setup_ubigeo_completer()

        # Fila 2: Sub-presupuesto | Costo al
        grid.addWidget(_label(tr("Sub-presupuesto")), 2, 0)
        self.inp_sub = _inp(tr("Sub-presupuesto"))
        grid.addWidget(self.inp_sub, 2, 1)
        grid.addWidget(_label(tr("Costo al")), 2, 2)
        # Texto libre (escribir la fecha a mano) + botón de calendario.
        _costo_cont = QWidget()
        _costo_hl = QHBoxLayout(_costo_cont)
        _costo_hl.setContentsMargins(0, 0, 0, 0)
        _costo_hl.setSpacing(4)
        self.inp_costo_al = _inp(tr("dd/mm/aaaa"))
        self.inp_costo_al.setToolTip(
            tr("Escribe la fecha (dd/mm/aaaa) o elígela del calendario"))
        _costo_hl.addWidget(self.inp_costo_al, 1)
        self._btn_cal_costo = QPushButton()
        self._btn_cal_costo.setIcon(icon("calendario"))
        self._btn_cal_costo.setFixedSize(30, 30)
        self._btn_cal_costo.setCursor(Qt.PointingHandCursor)
        self._btn_cal_costo.setToolTip(tr("Elegir del calendario"))
        self._btn_cal_costo.setStyleSheet(
            "QPushButton { background:transparent; border:none; }"
            "QPushButton:hover { background:#F0F1F2; border-radius:6px; }")
        self._btn_cal_costo.clicked.connect(self._popup_calendario_costo)
        _costo_hl.addWidget(self._btn_cal_costo)
        grid.addWidget(_costo_cont, 2, 3)

        # Fila 3: Moneda | Estado
        grid.addWidget(_label(tr("Moneda")), 3, 0)
        self.cmb_moneda = _cmb([(m, m) for m in MONEDAS])
        _moneda_def = get_config('moneda_defecto', 'Soles')
        _idx_mon = self.cmb_moneda.findData(_moneda_def)
        if _idx_mon >= 0:
            self.cmb_moneda.setCurrentIndex(_idx_mon)
        grid.addWidget(self.cmb_moneda, 3, 1)
        grid.addWidget(_label(tr("Estado")), 3, 2)
        self.cmb_estado = _cmb([
            ("En elaboración", "elaboracion"),
            ("En revisión",    "revision"),
            ("Aprobado",       "aprobado"),
            ("En ejecución",   "ejecutado"),
        ])
        grid.addWidget(self.cmb_estado, 3, 3)

        # Fila 4: Modalidad
        grid.addWidget(_label(tr("Modalidad")), 4, 0)
        self.cmb_modalidad = _cmb([
            ("Contrata",               "Contrata"),
            ("Administración directa", "Administración directa"),
            ("Concurso oferta",        "Concurso oferta"),
            ("Llave en mano",          "Llave en mano"),
        ])
        grid.addWidget(self.cmb_modalidad, 4, 1)

        vl.addLayout(grid)
        return card

    def _popup_calendario_costo(self):
        """Abre un calendario flotante bajo el botón; al elegir un día,
        escribe la fecha (dd/mm/aaaa) en el campo de texto. El campo sigue
        siendo editable a mano."""
        from PySide6.QtWidgets import QCalendarWidget, QFrame, QVBoxLayout
        pop = QFrame(self, Qt.Popup)
        pop.setFrameShape(QFrame.StyledPanel)
        lay = QVBoxLayout(pop)
        lay.setContentsMargins(2, 2, 2, 2)
        cal = QCalendarWidget(pop)
        cal.setGridVisible(True)
        cal.setSelectedDate(self._parse_fecha_costo(self.inp_costo_al.text()))
        lay.addWidget(cal)

        def _pick(d):
            self.inp_costo_al.setText(d.toString("dd/MM/yyyy"))
            pop.close()
        cal.clicked.connect(_pick)

        btn = self._btn_cal_costo
        pop.move(btn.mapToGlobal(btn.rect().bottomLeft()))
        pop.show()

    def _parse_fecha_costo(self, texto: str) -> QDate:
        """Parsea el `costo_al` guardado (texto) a QDate. Prioriza DD/MM/YYYY
        (formato nativo) y tolera los importados (MM/DD/YY con hora). Si no
        parsea, devuelve la fecha de hoy."""
        from datetime import datetime
        s = (texto or "").strip().split(" ")[0].split("T")[0]
        if not s:
            return QDate.currentDate()
        for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
            try:
                dt = datetime.strptime(s, fmt)
                return QDate(dt.year, dt.month, dt.day)
            except ValueError:
                continue
        return QDate.currentDate()

    def _abrir_mapa(self):
        """Abre el mapa para marcar la ubicación exacta. Centra en el distrito
        elegido (UBIGEO) si se reconoce. Guarda lat/lon si el usuario marca."""
        center = None
        try:
            from core.ubigeo import coords_de_ubicacion
            g = coords_de_ubicacion(self.inp_ubic.text())
            if g and g.get('latitud') is not None and g.get('longitud') is not None:
                center = (g['latitud'], g['longitud'])
        except Exception:
            pass
        mark = ((self._latitud, self._longitud, self._altitud)
                if self._latitud is not None else None)
        dlg = _DialogMapa(self, center=center, mark=mark)
        if dlg.exec() == QDialog.Accepted:
            lat, lon, alt = dlg.coords()
            if lat is not None:
                self._latitud, self._longitud, self._altitud = lat, lon, alt
                self.btn_mapa.setIcon(icon_colored("ubicacion", "#3a9e23"))
                _alt = f", {int(round(alt))} msnm" if alt is not None else ""
                self.btn_mapa.setToolTip(
                    f"Ubicación marcada: {lat:.5f}, {lon:.5f}{_alt} — clic para cambiar")

    def _setup_ubigeo_completer(self):
        """Autocompletado UBIGEO (INEI) en el campo Ubicación: al escribir un
        distrito (sin tildes/mayúsculas) sugiere «Distrito, Provincia,
        Departamento» y al elegir rellena el campo. 1,893 distritos."""
        from PySide6.QtWidgets import QCompleter
        from PySide6.QtCore import QSortFilterProxyModel
        from PySide6.QtGui import QStandardItemModel, QStandardItem
        from core.ubigeo import cargar_ubigeo
        from utils.formatting import norm_busqueda

        datos = cargar_ubigeo()
        if not datos:
            return   # sin dataset → campo de texto libre normal

        modelo = QStandardItemModel(self)
        for d in datos:
            it = QStandardItem(d["etiqueta"])
            it.setData(d["norm"], Qt.UserRole)   # clave normalizada
            modelo.appendRow(it)

        class _NormProxy(QSortFilterProxyModel):
            def __init__(self, parent=None):
                super().__init__(parent)
                self._q = ""
            def set_query(self, texto):
                self._q = norm_busqueda(texto)
                self.invalidateFilter()
            def filterAcceptsRow(self, row, parent):
                if not self._q:
                    return False   # sin texto → sin sugerencias
                idx = self.sourceModel().index(row, 0, parent)
                norm = self.sourceModel().data(idx, Qt.UserRole) or ""
                return self._q in norm

        proxy = _NormProxy(self)
        proxy.setSourceModel(modelo)
        self._ubigeo_proxy = proxy

        comp = QCompleter(self)
        comp.setModel(proxy)
        # Unfiltered: el filtrado lo hace el proxy (sin tildes); el completer
        # solo muestra lo que el proxy deja pasar.
        comp.setCompletionMode(QCompleter.UnfilteredPopupCompletion)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        comp.setMaxVisibleItems(12)
        self.inp_ubic.setCompleter(comp)

        def _on_text(t):
            proxy.set_query(t)
            if t.strip():
                comp.complete()
        self.inp_ubic.textEdited.connect(_on_text)

    def _seccion_financiero(self) -> QWidget:
        card = QFrame()
        card.setObjectName("formCard")
        card.setAttribute(Qt.WA_StyledBackground, True)
        card.setStyleSheet(
            f"QFrame#formCard {{ background:white; border-radius:8px;"
            f" border:1px solid {SILVER_300}; }}"
        )
        vl = QVBoxLayout(card)
        vl.setContentsMargins(24, 16, 24, 18)
        vl.setSpacing(12)

        from utils.i18n import tr
        lbl_sec = QLabel(tr("Configuración del proyecto"))
        lbl_sec.setStyleSheet(
            f"color:{SLATE_700}; font-size:13px; font-weight:700;"
            f" border:none; background:transparent;"
        )
        vl.addWidget(lbl_sec)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color:{SILVER_300};"); sep.setFixedHeight(1)
        vl.addWidget(sep)

        grid = QGridLayout()
        grid.setHorizontalSpacing(20)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)

        # Fila 0: Plazo | Jornada laboral
        grid.addWidget(_label(tr("Plazo de obra")), 0, 0)
        self.inp_plazo = QSpinBox()
        self.inp_plazo.setRange(1, 9999)
        self.inp_plazo.setValue(60)
        self.inp_plazo.setSuffix(" días")
        self.inp_plazo.setMinimumHeight(30)
        grid.addWidget(self.inp_plazo, 0, 1)

        grid.addWidget(_label(tr("Jornada laboral")), 0, 2)
        self.inp_jorn = QComboBox()
        self.inp_jorn.setMinimumHeight(30)
        self.inp_jorn.setEditable(True)
        self.inp_jorn.lineEdit().setValidator(QIntValidator(1, 24))
        self.inp_jorn.lineEdit().setPlaceholderText("h/día")
        for h in range(4, 13):
            self.inp_jorn.addItem(f"{h}", h)
        _jornada_def = int(get_config('jornada_defecto', '8'))
        _idx_jorn = self.inp_jorn.findText(str(_jornada_def))
        self.inp_jorn.setCurrentIndex(_idx_jorn if _idx_jorn >= 0 else 4)
        grid.addWidget(self.inp_jorn, 0, 3)

        # Fila 1: Grupo de análisis (ancho completo)
        grid.addWidget(_label(tr("Grupo de análisis")), 1, 0)
        self.inp_grupo = _inp(tr("Grupo de análisis"))
        grid.addWidget(self.inp_grupo, 1, 1, 1, 3)

        vl.addLayout(grid)

        nota = QLabel("Los gastos generales, utilidad e IGV se configuran en Pie de presupuesto.")
        nota.setStyleSheet(
            f"color:{SLATE_100}; font-size:11px; border:none; background:transparent;"
        )
        vl.addWidget(nota)
        return card

    # ── Sección: Descripción / notas ──────────────────────────────────────────

    def _seccion_descripcion(self) -> QWidget:
        from PySide6.QtWidgets import QTextEdit
        card = QFrame()
        card.setObjectName("formCard")
        card.setAttribute(Qt.WA_StyledBackground, True)
        card.setStyleSheet(
            f"QFrame#formCard {{ background:white; border-radius:10px;"
            f" border:1px solid {SILVER_300}; }}"
        )
        vl = QVBoxLayout(card)
        vl.setContentsMargins(24, 16, 24, 18)
        vl.setSpacing(12)

        from utils.i18n import tr
        lbl_sec = QLabel(tr("Notas del proyecto") + "  (" + tr("opcional") + ")")
        lbl_sec.setStyleSheet(
            f"color:{SLATE_700}; font-size:13px; font-weight:700;"
            f" border:none; background:transparent;"
        )
        vl.addWidget(lbl_sec)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color:{SILVER_300};"); sep.setFixedHeight(1)
        vl.addWidget(sep)

        # Hint visible para el usuario sobre cómo se usan las notas
        lbl_hint = QLabel(
            "✨ <b>Mientras más describas tu proyecto, mayor será la "
            "precisión con la que la IA te apoyará</b> al sugerir partidas, "
            "validar tu presupuesto o responder en el chat de Tuxia."
        )
        lbl_hint.setWordWrap(True)
        lbl_hint.setTextFormat(Qt.RichText)
        lbl_hint.setStyleSheet(
            "color:#C0621A; font-size:11px; background:#FEF5EB;"
            " border:1px solid #F37329; border-radius:6px;"
            " padding:6px 10px;"
        )
        vl.addWidget(lbl_hint)

        # Cuadro de notas con el prompt de ejemplo DENTRO (texto fantasma gris):
        # el usuario lo lee y al hacer clic para escribir se borra solo.
        self.txt_notas = _GhostTextEdit(_EJEMPLO_NOTAS)
        self.txt_notas.setMinimumHeight(140)
        self.txt_notas.setMaximumHeight(220)
        vl.addWidget(self.txt_notas)

        return card

    # ── Footer: botones de acción ─────────────────────────────────────────────

    def _make_footer(self) -> QFrame:
        footer = QFrame()
        footer.setStyleSheet("background:transparent; border:none;")
        hl = QHBoxLayout(footer)
        hl.setContentsMargins(0, 8, 0, 0)
        hl.setSpacing(10)

        hl.addStretch()

        from utils.i18n import tr
        btn_cancelar = QPushButton(tr("Cancelar"))
        btn_cancelar.setFixedHeight(38)
        btn_cancelar.setMinimumWidth(100)
        btn_cancelar.setStyleSheet(
            f"QPushButton {{ background:white; color:{SLATE_500};"
            f" border:1px solid {SILVER_300}; border-radius:8px;"
            f" font-size:13px; font-weight:600; padding:0 20px; }}"
            f"QPushButton:hover {{ border-color:{BLUE_500}; color:{BLUE_700}; }}"
        )
        btn_cancelar.clicked.connect(self.cancelado.emit)
        hl.addWidget(btn_cancelar)

        label_btn = "  " + tr("Guardar") + "  →" if self._proyecto_id else "  " + tr("Crear") + "  →"
        self.btn_crear = QPushButton(label_btn)
        self.btn_crear.setFixedHeight(38)
        self.btn_crear.setMinimumWidth(160)
        self.btn_crear.setStyleSheet(
            f"QPushButton {{ background:{BLUE_500}; color:white; border:none;"
            f" border-radius:8px; font-size:13px; font-weight:700; padding:0 24px; }}"
            f"QPushButton:hover {{ background:{BLUE_700}; }}"
            f"QPushButton:pressed {{ background:{BLUE_700}; padding-top:1px; }}"
        )
        self.btn_crear.clicked.connect(self._crear)
        hl.addWidget(self.btn_crear)

        return footer

    # ── Lógica ────────────────────────────────────────────────────────────────

    def _cargar_datos(self, proyecto_id: int):
        """Pre-rellena el formulario con los datos del proyecto existente."""
        conn = get_db()
        p = conn.execute("SELECT * FROM proyectos WHERE id=?", (proyecto_id,)).fetchone()
        conn.close()
        if not p:
            return
        p = dict(p)
        self._jornada_original = int(p.get('jornada_laboral', 8) or 8)

        self.inp_nombre.setText(p.get('nombre', '') or '')
        self.inp_cliente.setText(p.get('cliente', '') or '')
        self.inp_ubic.setText(p.get('ubicacion', '') or '')
        self._latitud = p.get('latitud')
        self._longitud = p.get('longitud')
        self._altitud = p.get('altitud')
        if self._latitud is not None and self._longitud is not None:
            self.btn_mapa.setIcon(icon_colored("ubicacion", "#3a9e23"))
            _alt = (f", {int(round(self._altitud))} msnm"
                    if self._altitud is not None else "")
            self.btn_mapa.setToolTip(
                f"Ubicación marcada: {self._latitud:.5f}, {self._longitud:.5f}{_alt}")
        self.inp_sub.setText(p.get('sub_presupuesto', '') or '')
        _ca = (p.get('costo_al', '') or '').strip()
        # Mostrar solo la fecha (algunos proyectos importados traen «… 00:00:00»).
        self.inp_costo_al.setText(
            self._parse_fecha_costo(_ca).toString('dd/MM/yyyy') if _ca else '')
        self.inp_grupo.setText(p.get('grupo_analisis', '') or '')

        idx = self.cmb_moneda.findData(p.get('moneda', 'Soles'))
        if idx >= 0: self.cmb_moneda.setCurrentIndex(idx)

        idx = self.cmb_estado.findData(p.get('estado', 'elaboracion'))
        if idx >= 0: self.cmb_estado.setCurrentIndex(idx)

        idx = self.cmb_modalidad.findData(p.get('modalidad', ''))
        if idx >= 0: self.cmb_modalidad.setCurrentIndex(idx)
        else: self.cmb_modalidad.setCurrentText(p.get('modalidad', '') or '')

        self.inp_plazo.setValue(int(p.get('plazo', 60) or 60))

        jorn_str = str(self._jornada_original)
        idx = self.inp_jorn.findText(jorn_str)
        if idx >= 0:
            self.inp_jorn.setCurrentIndex(idx)
        else:
            self.inp_jorn.setCurrentText(jorn_str)

        # Notas — preferir el campo nuevo `notas`; fallback a la partida 00
        # legacy (proyectos antiguos guardaban las notas como una partida fake)
        notas = (p.get('notas') or '').strip()
        if not notas:
            try:
                conn2 = get_db()
                row = conn2.execute(
                    "SELECT especificaciones FROM partidas "
                    "WHERE proyecto_id=? AND item='00' LIMIT 1",
                    (proyecto_id,)
                ).fetchone()
                conn2.close()
                if row:
                    notas = (row['especificaciones'] or '').strip()
            except Exception:
                pass
        self.txt_notas.set_texto(notas)

    def limpiar(self):
        """Resetea el formulario para un nuevo proyecto."""
        self.inp_nombre.clear()
        self.inp_cliente.clear()
        self.inp_ubic.clear()
        self._latitud = None
        self._longitud = None
        self._altitud = None
        if hasattr(self, 'btn_mapa'):
            self.btn_mapa.setIcon(icon("ubicacion"))
            self.btn_mapa.setToolTip("Ubicar en el mapa (opcional, requiere internet)")
        self.inp_sub.clear()
        self.inp_costo_al.setText(QDate.currentDate().toString('dd/MM/yyyy'))
        self.inp_grupo.clear()
        self.txt_notas.mostrar_ghost()
        _moneda_def = get_config('moneda_defecto', 'Soles')
        _idx_mon = self.cmb_moneda.findData(_moneda_def)
        self.cmb_moneda.setCurrentIndex(_idx_mon if _idx_mon >= 0 else 0)
        self.cmb_estado.setCurrentIndex(0)
        self.cmb_modalidad.setCurrentIndex(0)
        self.inp_plazo.setValue(60)
        _jornada_def = int(get_config('jornada_defecto', '8'))
        _idx_jorn = self.inp_jorn.findText(str(_jornada_def))
        self.inp_jorn.setCurrentIndex(_idx_jorn if _idx_jorn >= 0 else 4)
        self.lbl_error.clear()
        self.inp_nombre.setFocus()

    def _crear(self):
        nombre = self.inp_nombre.text().strip()
        if not nombre:
            self.lbl_error.setText("El nombre del proyecto es obligatorio")
            self.inp_nombre.setFocus()
            return

        self.lbl_error.clear()
        self.btn_crear.setEnabled(False)
        jornada_nueva = int(self.inp_jorn.currentText() or 8)

        conn = get_db()
        try:
            if self._proyecto_id is None:
                # ── Modo crear ────────────────────────────────────────────────
                self.btn_crear.setText("  Creando…")
                notas = self.txt_notas.texto_real()
                cur = conn.execute(
                    """INSERT INTO proyectos
                       (nombre, cliente, ubicacion, sub_presupuesto, costo_al,
                        plazo, gf_pct, utilidad_pct, igv_pct, grupo_analisis,
                        jornada_laboral, moneda, modalidad, estado, usuario_id,
                        notas, latitud, longitud, altitud)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        nombre,
                        self.inp_cliente.text().strip(),
                        self.inp_ubic.text().strip(),
                        self.inp_sub.text().strip(),
                        self.inp_costo_al.text().strip(),
                        self.inp_plazo.value(),
                        10.0, 5.0, 18.0,
                        self.inp_grupo.text().strip(),
                        jornada_nueva,
                        self.cmb_moneda.currentData(),
                        self.cmb_modalidad.currentData(),
                        self.cmb_estado.currentData(),
                        self.usuario.id if self.usuario else None,
                        notas,
                        self._latitud, self._longitud, self._altitud,
                    )
                )
                nuevo_id = cur.lastrowid
                conn.commit()
                conn.close()
                self.btn_crear.setEnabled(True)
                self.btn_crear.setText("  Crear proyecto  →")
                self.proyecto_creado.emit(nuevo_id)

            else:
                # ── Modo editar ───────────────────────────────────────────────
                self.btn_crear.setText("  Guardando…")
                notas = self.txt_notas.texto_real()
                conn.execute(
                    """UPDATE proyectos SET nombre=?, cliente=?, ubicacion=?,
                       sub_presupuesto=?, costo_al=?, plazo=?, grupo_analisis=?,
                       jornada_laboral=?, moneda=?, modalidad=?, estado=?,
                       notas=?, latitud=?, longitud=?, altitud=?
                       WHERE id=?""",
                    (
                        nombre,
                        self.inp_cliente.text().strip(),
                        self.inp_ubic.text().strip(),
                        self.inp_sub.text().strip(),
                        self.inp_costo_al.text().strip(),
                        self.inp_plazo.value(),
                        self.inp_grupo.text().strip(),
                        jornada_nueva,
                        self.cmb_moneda.currentData(),
                        self.cmb_modalidad.currentData(),
                        self.cmb_estado.currentData(),
                        notas,
                        self._latitud, self._longitud, self._altitud,
                        self._proyecto_id,
                    )
                )
                # Si cambió la jornada, recalcular las cantidades derivadas de
                # la cuadrilla: MO y equipo por hora (hh/hm). La MO/EQ por día
                # NO lleva jornada; las globales y los insumos sin cuadrilla
                # (MAT, equipo-día directo) conservan su cantidad.
                if jornada_nueva != self._jornada_original:
                    from core.database import (_recalcular_pu, _rn,
                        get_decimales_cant_acu, recurso_por_hora,
                        recurso_por_dia, partida_global)
                    partidas = conn.execute(
                        "SELECT id, rendimiento, unidad FROM partidas WHERE proyecto_id=?",
                        (self._proyecto_id,)
                    ).fetchall()
                    dec = get_decimales_cant_acu()
                    for part in partidas:
                        if partida_global(part['unidad']):
                            continue
                        rend = part['rendimiento'] or 1
                        items = conn.execute(
                            """SELECT ai.id, ai.cuadrilla, r.tipo, r.unidad FROM acu_items ai
                               JOIN recursos r ON r.id=ai.recurso_id
                               WHERE ai.partida_id=?""",
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
                conn.close()
                self.btn_crear.setEnabled(True)
                self.btn_crear.setText("  Guardar cambios  →")
                self.proyecto_editado.emit(self._proyecto_id)

        except Exception as e:
            self.lbl_error.setText(f"Error: {e}")
            self.btn_crear.setEnabled(True)
            self.btn_crear.setText(
                "  Guardar cambios  →" if self._proyecto_id else "  Crear proyecto  →"
            )
            conn.close()
