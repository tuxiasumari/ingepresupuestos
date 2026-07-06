# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""Ventana principal — Elementary OS HIG style.

Sidebar:  64px, Slate-700 (#273445), ítem activo Blueberry (#F37329)
Headerbar: Slate-500 (#485A6C), botones de acción redondeados
Contenido: Silver-100 (#F8F9FA)
"""
import sys

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QStackedWidget, QFrame, QLabel, QPushButton, QSizePolicy,
    QToolButton,
)
from PySide6.QtCore import Qt, QSize, Signal, QPoint, QRect
from PySide6.QtGui import QIcon, QPixmap, QFont, QColor, QPainter, QPen, QCursor

from models.usuario import Usuario
from utils.auth import logout
from utils.icons import icon, icon_colored
from core.config import BASE_DIR

# ── Paleta Elementary OS ──────────────────────────────────────────────────────
BLUE_500     = "#F37329"   # Naranja acento principal (IngePresupuestos)
BLUE_700     = "#C0621A"   # Naranja oscuro — hover activo
BLUEBERRY    = "#3689e6"   # Blueberry Elementary — celeste primario
BLUEBERRY_DK = "#0d52bf"   # Blueberry oscuro
SLATE_700  = "#2E3C52"   # Sidebar fondo — azul pizarra medio
SLATE_500  = "#485A6C"   # Headerbar / toolbar
SLATE_300  = "#667885"   # Texto secundario sidebar
SLATE_100  = "#B8C9D6"   # Texto sidebar inactivo
SILVER_100 = "#F8F9FA"   # Fondo contenido
SILVER_300 = "#D4D4D4"   # Bordes
RED_500    = "#C6262E"   # Strawberry — peligro
GREEN_500  = "#68B723"   # Lime — éxito
ORANGE_500 = "#F37329"   # Orange — advertencia
BANANA_500 = "#F9C440"   # Banana — estrella

# Mapa edge-string → Qt.Edges para startSystemResize (Wayland + X11)
_EDGE_QT_MAP = {
    'left':         Qt.LeftEdge,
    'right':        Qt.RightEdge,
    'top':          Qt.TopEdge,
    'bottom':       Qt.BottomEdge,
    'top-left':     Qt.TopEdge    | Qt.LeftEdge,
    'top-right':    Qt.TopEdge    | Qt.RightEdge,
    'bottom-left':  Qt.BottomEdge | Qt.LeftEdge,
    'bottom-right': Qt.BottomEdge | Qt.RightEdge,
}

# ── Pill de estado de licencia ────────────────────────────────────────────────

class _LicenciaPill(QPushButton):
    """Pill compacta en el headerbar que muestra el estado de la licencia.

    Visible **solo** cuando hay algo que reportar — trial vigente, trial
    vencido o licencia anual próxima a vencer (≤30 días). Una vez activada
    una licencia perpetua o anual con vencimiento lejano, queda oculta para
    no agregar ruido visual.

    Click → abre el diálogo de licencia (`mostrar_dialogo_licencia`).
    Auto-refresh cada hora y manual tras cerrar el diálogo.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setFlat(True)
        self.setFocusPolicy(Qt.NoFocus)
        self.clicked.connect(self._abrir_dialogo)
        # Refresco automático cada hora — cubre el caso de la app abierta
        # cuando justo cambia el día y vence el trial.
        from PySide6.QtCore import QTimer
        self._timer = QTimer(self)
        self._timer.setInterval(60 * 60 * 1000)
        self._timer.timeout.connect(self.refrescar)
        self._timer.start()
        self.refrescar()

    def refrescar(self):
        """Lee el estado actual y actualiza el texto + estilo + visibilidad."""
        try:
            from core import licencia as L
        except ImportError:
            self.setVisible(False)
            return
        lic = L.cargar()
        # ¿Mostrar? Solo si trial, trial vencido o licencia anual ≤30 días.
        mostrar = False
        if lic.tipo == 'trial':
            mostrar = True
        elif not lic.vigente():
            mostrar = True
        else:
            dr = lic.dias_restantes()
            if dr is not None and dr <= 30:
                mostrar = True
        if not mostrar:
            self.setVisible(False)
            return
        self.setVisible(True)
        texto, bg, fg, border = self._estilo_para(lic)
        self.setText(texto)
        self.setToolTip(lic.estado_str() + "  ·  Clic para gestionar")
        self.setStyleSheet(
            f"QPushButton {{ background:{bg}; color:{fg};"
            f" border:1px solid {border}; border-radius:11px;"
            f" padding:2px 12px; font-size:11px; font-weight:700;"
            f" font-family:'Inter'; }}"
            f"QPushButton:hover {{ background:{border};"
            f" color:white; }}"
        )

    @staticmethod
    def _estilo_para(lic) -> tuple[str, str, str, str]:
        """Devuelve (texto, bg, fg, border) según estado de la licencia."""
        if not lic.vigente():
            return ("Licencia vencida — Activar",
                      "#FCE7E9", "#9D1A20", RED_500)
        if lic.tipo == 'trial':
            dr = lic.dias_restantes() or 0
            if dr <= 3:
                # Crítico — rojo suave
                base = "1 día" if dr == 1 else ("hoy" if dr == 0 else f"{dr} días")
                return (f"Prueba: {base}", "#FCE7E9", "#9D1A20", RED_500)
            if dr <= 7:
                # Advertencia — naranja
                return (f"Prueba: {dr} días", "#FFF0DC", "#7A4615", ORANGE_500)
            # Verde — todo bien
            return (f"Prueba: {dr} días", "#E6F5D8", "#3E6E0B", GREEN_500)
        # anual ≤30 días
        dr = lic.dias_restantes() or 0
        if dr <= 7:
            return (f"Vence en {dr} días", "#FFF0DC", "#7A4615", ORANGE_500)
        return (f"Vence en {dr} días", "#E6F5D8", "#3E6E0B", GREEN_500)

    def _abrir_dialogo(self):
        try:
            from views.licencia_dialog import mostrar_dialogo_licencia
            mostrar_dialogo_licencia(self.window())
        except ImportError:
            pass
        # Tras cerrar el diálogo, refrescar (el usuario pudo haber activado
        # una licencia).
        self.refrescar()


# ── Sidebar button ─────────────────────────────────────────────────────────────

class _NavBtn(QWidget):
    """Botón de navegación: icono SVG Elementary + label debajo."""
    clicked = Signal()

    def __init__(self, icon_name: str, label: str, inactive_color: str = None, parent=None):
        super().__init__(parent)
        self._icon_name      = icon_name
        self._label          = label
        self._active         = False
        self._inactive_color = inactive_color   # color personalizado en reposo
        # objectName permite que el QSS targetee solo este widget y no a sus
        # hijos QLabel (que antes recibían background+border-radius duplicado
        # creando esa apariencia de "doble cajita").
        self.setObjectName("navBtn")
        # Qt requiere este atributo para que las subclases directas de QWidget
        # pinten el background del stylesheet (las QFrame/QPushButton lo
        # hacen por defecto, pero QWidget puro NO).
        self.setAttribute(Qt.WA_StyledBackground, True)
        # Botón más estrecho que el sidebar (84px) → el rectángulo de
        # selección queda centrado con padding visible a ambos lados.
        self.setFixedSize(64, 72)
        self.setCursor(Qt.PointingHandCursor)

        vl = QVBoxLayout(self)
        vl.setContentsMargins(4, 8, 4, 6)
        vl.setSpacing(2)
        vl.setAlignment(Qt.AlignCenter)

        self._lbl_icon = QLabel()
        self._lbl_icon.setAlignment(Qt.AlignCenter)
        self._lbl_icon.setFixedSize(36, 36)
        # Background explícitamente transparente para que NO compita con la
        # selección del padre.
        self._lbl_icon.setStyleSheet("background:transparent; border:none;")
        vl.addWidget(self._lbl_icon, alignment=Qt.AlignCenter)

        self._lbl_text = QLabel(label)
        self._lbl_text.setAlignment(Qt.AlignCenter)
        self._lbl_text.setStyleSheet(
            f"color: {SLATE_100}; font-size: 9px; font-weight: 600;"
            " background:transparent; border:none;"
        )
        vl.addWidget(self._lbl_text, alignment=Qt.AlignCenter)

        self._load_icon(False)

    def _load_icon(self, active: bool):
        if active:
            color = "#FFFFFF"
        elif self._inactive_color:
            color = self._inactive_color
        else:
            color = SLATE_100
        ic = icon_colored(self._icon_name, color)
        if ic.isNull():
            self._lbl_icon.setText("●")
            self._lbl_icon.setStyleSheet(f"color:{color}; font-size:22px;")
        else:
            pix = ic.pixmap(QSize(28, 28))
            self._lbl_icon.setPixmap(pix)
            self._lbl_icon.setText("")

    def setChecked(self, active: bool):
        self._active = active
        if active:
            # Selector #navBtn targetea SOLO el contenedor; los hijos QLabel
            # mantienen su background:transparent inline → una sola cajita
            self.setStyleSheet(f"""
                QWidget#navBtn {{
                    background: {BLUE_500};
                    border-radius: 10px;
                }}
            """)
            self._lbl_text.setStyleSheet(
                "color: white; font-size: 10px; font-weight: 700;"
                " background:transparent; border:none;"
            )
        else:
            self.setStyleSheet("""
                QWidget#navBtn { background: transparent; border-radius: 10px; }
                QWidget#navBtn:hover { background: rgba(255,255,255,0.12); }
            """)
            self._lbl_text.setStyleSheet(
                f"color: {SLATE_100}; font-size: 10px; font-weight: 600;"
                " background:transparent; border:none;"
            )
        self._load_icon(active)

    def isChecked(self) -> bool:
        return self._active

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()


# ── Headerbar button ────────────────────────────────────────────────────────────

def _hdr_btn(icon_name: str, label: str, bg: str, handler) -> QPushButton:
    """Botón de acción en el headerbar estilo Elementary."""
    btn = QPushButton(f"  {label}")
    btn.setFixedHeight(30)
    btn.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
    btn.setStyleSheet(f"""
        QPushButton {{
            background: {bg};
            color: white;
            border: none;
            border-radius: 6px;
            font-size: 12px;
            font-weight: 600;
            padding: 0 14px 0 10px;
            text-align: left;
        }}
        QPushButton:pressed {{ padding-top: 1px; }}
    """)
    ic = icon_colored(icon_name, "white")
    if not ic.isNull():
        btn.setIcon(ic)
        btn.setIconSize(QSize(16, 16))
    btn.clicked.connect(handler)
    return btn


# ═══════════════════════════════════════════════════════════════════════════════
class _CustomTitleBar(QFrame):
    """Barra de título custom oscura (FramelessWindowHint).

    Reemplaza la decoración nativa del WM/sistema. Estilo de botones según
    plataforma para mantener convenciones:
      - macOS  → traffic lights (rojo/amarillo/verde) a la IZQUIERDA
      - Windows → rectangulares planos a la DERECHA (Win11 style)
      - Linux/GNOME → círculos pequeños a la DERECHA (Adwaita style)
    """

    def __init__(self, parent_window, parent=None):
        super().__init__(parent)
        self._win = parent_window
        self.setObjectName("customTitleBar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(34)
        self.setStyleSheet(
            f"QFrame#customTitleBar {{ background:{SLATE_700};"
            f" border-bottom:1px solid #1B2434; }}"
            f"QFrame#customTitleBar QLabel {{ color:#E8EBF0;"
            f" background:transparent; }}"
        )
        # Detectar plataforma
        import sys as _sys
        if _sys.platform == 'darwin':
            self._plataforma = 'mac'
        elif _sys.platform.startswith('win'):
            self._plataforma = 'win'
        else:
            self._plataforma = 'linux'
        # Drag state
        self._drag_pos:  QPoint | None = None
        self._press_pos: QPoint | None = None

        hl = QHBoxLayout(self)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(0)

        # Crear los botones según plataforma
        self.btn_min, self.btn_max, self.btn_cls = self._make_buttons()
        self.btn_min.clicked.connect(self._on_min)
        self.btn_max.clicked.connect(self._on_max)
        self.btn_cls.clicked.connect(self._on_close)

        # Título (sin icono — el logo de la app está en el sidebar más abajo)
        self._lbl_title = QLabel(parent_window.windowTitle() or "ingePresupuestos")
        f = QFont()
        f.setPointSize(10)
        f.setWeight(QFont.DemiBold)
        self._lbl_title.setFont(f)
        self._lbl_title.setStyleSheet("color:#E8EBF0; background:transparent;")

        # Título siempre centrado. Icono a la izquierda. Botones a la derecha
        # (excepto en macOS donde van a la izquierda — traffic lights).
        self._lbl_title.setAlignment(Qt.AlignCenter)

        if self._plataforma == 'mac':
            # Traffic lights a la izquierda
            box_btns = QHBoxLayout()
            box_btns.setContentsMargins(10, 0, 8, 0)
            box_btns.setSpacing(8)
            box_btns.addWidget(self.btn_cls)
            box_btns.addWidget(self.btn_min)
            box_btns.addWidget(self.btn_max)
            hl.addLayout(box_btns)
            # Título centrado
            hl.addWidget(self._lbl_title, 1)
            # Spacer derecho del mismo ancho que los traffic lights para centrar
            spacer = QWidget()
            spacer.setFixedWidth(72)
            hl.addWidget(spacer)
        else:
            # Windows / Linux: título (centro) + botones (der)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.setSpacing(0)
            # Spacer izquierdo equivalente al ancho de los botones,
            # para que el título quede centrado en el ancho de la ventana.
            if self._plataforma == 'linux':
                btns_w = 24 * 3 + 8 * 2 + 10   # 3 botones 24px + spacings
            else:  # Windows
                btns_w = 46 * 3                 # 3 botones 46px
            spacer_l = QWidget()
            spacer_l.setFixedWidth(btns_w)
            hl.addWidget(spacer_l)
            hl.addWidget(self._lbl_title, 1)
            if self._plataforma == 'linux':
                hl.addSpacing(4)
                hl.addWidget(self.btn_min)
                hl.addSpacing(8)
                hl.addWidget(self.btn_max)
                hl.addSpacing(8)
                hl.addWidget(self.btn_cls)
                hl.addSpacing(6)
            else:  # Windows
                hl.addWidget(self.btn_min)
                hl.addWidget(self.btn_max)
                hl.addWidget(self.btn_cls)

    def _make_buttons(self) -> tuple[QToolButton, QToolButton, QToolButton]:
        """Crea los botones según la plataforma."""
        if self._plataforma == 'mac':
            return self._buttons_mac()
        if self._plataforma == 'win':
            return self._buttons_win()
        return self._buttons_linux()

    @staticmethod
    def _circle_btn(size: int, fill: str, border: str,
                    hover_text: str = '', text_color: str = '#000') -> QToolButton:
        """Botón circular pequeño (traffic light / gnome style)."""
        b = QToolButton()
        b.setFixedSize(size, size)
        b.setCursor(Qt.PointingHandCursor)
        b.setText('')
        b.setProperty('_hover_text', hover_text)
        radius = size // 2
        b.setStyleSheet(
            f"QToolButton {{ background:{fill}; border:1px solid {border};"
            f" border-radius:{radius}px;"
            f" color:{text_color}; font-size:9px; font-weight:700;"
            f" padding:0; margin:0; }}"
            f"QToolButton:hover {{ background:{fill};"
            f" color:rgba(0,0,0,0.65); }}"
        )
        return b

    def _buttons_mac(self):
        # Traffic lights: cerrar (rojo), minimizar (amarillo), maximizar (verde)
        cls = self._circle_btn(13, "#FF5F57", "#E0443E")
        mn  = self._circle_btn(13, "#FEBC2E", "#DEA123")
        mx  = self._circle_btn(13, "#28C840", "#1AAB29")
        return mn, mx, cls

    def _buttons_linux(self):
        # GNOME / Adwaita: círculos grises pequeños con glifo
        def _gnome(symbol: str, hover_bg: str = "#3C4A5E",
                   is_close: bool = False) -> QToolButton:
            b = QToolButton()
            b.setFixedSize(24, 24)
            b.setCursor(Qt.PointingHandCursor)
            b.setText(symbol)
            if is_close:
                b.setStyleSheet(
                    "QToolButton { background:#3C4A5E; color:#E8EBF0;"
                    " border:none; border-radius:12px; font-size:11px;"
                    " font-weight:700; padding:0; margin:0; }"
                    "QToolButton:hover { background:#C6262E; color:white; }"
                )
            else:
                b.setStyleSheet(
                    "QToolButton { background:#3C4A5E; color:#E8EBF0;"
                    " border:none; border-radius:12px; font-size:11px;"
                    " font-weight:700; padding:0; margin:0; }"
                    f"QToolButton:hover {{ background:{hover_bg};"
                    " color:white; }}"
                )
            return b
        mn  = _gnome("—")
        mx  = _gnome("□")
        cls = _gnome("✕", is_close=True)
        return mn, mx, cls

    def _buttons_win(self):
        # Windows 11: rectangulares planos, hover slim
        def _win(symbol: str, hover_bg: str, is_close: bool = False) -> QToolButton:
            b = QToolButton()
            b.setCursor(Qt.PointingHandCursor)
            b.setFixedSize(46, 34)
            b.setText(symbol)
            if is_close:
                b.setStyleSheet(
                    "QToolButton { background:transparent; color:#E8EBF0;"
                    " border:none; font-size:13px; padding:0; margin:0; }"
                    f"QToolButton:hover {{ background:{hover_bg}; color:white; }}"
                )
            else:
                b.setStyleSheet(
                    "QToolButton { background:transparent; color:#E8EBF0;"
                    " border:none; font-size:13px; padding:0; margin:0; }"
                    f"QToolButton:hover {{ background:{hover_bg}; }}"
                )
            return b
        mn  = _win("—", "#3C4A5E")
        mx  = _win("□", "#3C4A5E")
        cls = _win("✕", "#C6262E", is_close=True)
        return mn, mx, cls

    def actualizar_titulo(self):
        """Sincroniza el label con `self._win.windowTitle()`."""
        self._lbl_title.setText(self._win.windowTitle())

    # ── Botones ───────────────────────────────────────────────────────

    def _on_min(self):
        self._win.showMinimized()

    def _on_max(self):
        if self._win.isMaximized():
            self._win.showNormal()
            self.btn_max.setText("□")    # □
        else:
            self._win.showMaximized()
            self.btn_max.setText("❐")    # ❐ (dos cuadrados = restaurar)

    def _on_close(self):
        self._win.close()

    # ── Drag para mover ───────────────────────────────────────────────

    def mousePressEvent(self, event):
        # Solo registramos la posición; NO llamamos startSystemMove todavía.
        # Si llamáramos aquí, el compositor agarra el grab y el doble clic
        # subsiguiente se pierde. Lo disparamos en mouseMoveEvent solo si
        # el cursor se desplaza más allá del threshold.
        if event.button() == Qt.LeftButton:
            self._press_pos = event.globalPosition().toPoint()
            self._drag_pos = None
            event.accept()

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.LeftButton):
            return

        # Modo fallback: ya estamos en drag manual (WM sin _NET_WM_MOVERESIZE)
        if self._drag_pos is not None:
            if self._win.isMaximized():
                self._on_max()
                return
            self._win.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
            return

        if self._press_pos is None:
            return

        # ¿Se movió lo suficiente para considerarlo drag?
        from PySide6.QtWidgets import QApplication
        delta = (event.globalPosition().toPoint() - self._press_pos).manhattanLength()
        if delta < QApplication.startDragDistance():
            return

        # Es drag real → pedir al compositor que tome el control
        wh = self._win.windowHandle()
        if wh is not None and wh.startSystemMove():
            self._press_pos = None
            event.accept()
            return

        # Fallback manual (WM sin soporte)
        self._press_pos = None
        if self._win.isMaximized():
            self._on_max()
            return
        self._drag_pos = event.globalPosition().toPoint() - self._win.frameGeometry().topLeft()
        event.accept()

    def mouseReleaseEvent(self, event):
        self._press_pos = None
        self._drag_pos = None

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._on_max()


class MainWindow(QMainWindow):
# ═══════════════════════════════════════════════════════════════════════════════

    # Barra de título custom — sin decoración del WM
    RESIZE_MARGIN = 6   # pixels desde el borde donde se detecta resize

    def __init__(self, usuario: Usuario | None = None):
        super().__init__()
        self.usuario = usuario
        self._proyectos_abiertos: list[dict] = []   # [{pid, nombre}]
        # Si el usuario está viendo INEI/Config como atajo desde un proyecto,
        # aquí guardamos el pid al que volver. None = no hay proyecto al que
        # regresar (estamos en flujo normal con sidebar visible).
        self._volver_a_pid: int | None = None
        # ¿Usar barra de título custom o nativa del sistema? Configurable.
        try:
            from core.database import get_config
            valor = get_config('barra_titulo_custom', '0')
            self._barra_custom = (str(valor) == '1')
        except Exception:
            self._barra_custom = True
        if self._barra_custom:
            self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
            self.setMouseTracking(True)
        # Estado de resize
        self._resize_edge: str | None = None
        self._resize_origin = None
        self._resize_geom = None
        self.setWindowTitle("IngePresupuestos")
        self.setMinimumSize(900, 600)
        # Tamaño inicial cómodo (sino el WM le da el min size). El usuario
        # puede maximizar o redimensionar; QSettings podría persistir esto
        # en una iteración futura.
        self.resize(1280, 820)
        # Ícono de la ventana — usa el ícono del producto.
        # NOTA: el path histórico era "resources/icons/icon-64.png" pero ese
        # archivo nunca existió → la ventana quedaba sin ícono. Ahora apunta
        # al ícono real del producto generado desde ingepresupuesto-icon.svg.
        for _ic_rel in (
            "resources/icons/elementary/24/ingepresupuestos.png",
            "resources/icons/elementary/24/ingepresupuestos.ico",
            "resources/icons/icon-64.png",
        ):
            icon_path = BASE_DIR / _ic_rel
            if icon_path.exists():
                self.setWindowIcon(QIcon(str(icon_path)))
                break
        self._build_ui()
        from PySide6.QtGui import QShortcut, QKeySequence
        QShortcut(QKeySequence("Ctrl+N"), self, self._nuevo_proyecto)
        # Solo construir el dashboard si ya hay usuario: en el arranque
        # normal MainWindow nace con usuario=None y set_usuario() lo
        # construye tras el login — construirlo aquí duplicaba el costo
        # completo del Inicio (2 × ~3 s con 400 proyectos) en cada arranque.
        if self.usuario is not None:
            self._ir_a_dashboard()

    def setWindowTitle(self, title: str):
        super().setWindowTitle(title)
        if hasattr(self, '_title_bar') and self._title_bar is not None:
            self._title_bar.actualizar_titulo()

    def asegurar_visible(self):
        """Garantiza que el marco de la ventana (y por tanto la barra de título)
        quede dentro del área visible del monitor donde aparece.

        En multi-monitor, Windows a veces coloca la ventana con la barra de
        título por encima del área de trabajo, dejándola inalcanzable para
        mover/redimensionar. Debe llamarse DESPUÉS de show() (el grosor del
        marco nativo solo se conoce una vez creada la ventana)."""
        from PySide6.QtWidgets import QApplication
        if self.isMaximized() or self.isFullScreen():
            return
        fg = self.frameGeometry()
        scr = (QApplication.screenAt(fg.center()) or self.screen()
               or QApplication.primaryScreen())
        if scr is None:
            return
        avail = scr.availableGeometry()
        nf = QRect(fg)
        # No exceder el área disponible (achicar si la ventana es más grande).
        nf.setWidth(min(nf.width(), avail.width()))
        nf.setHeight(min(nf.height(), avail.height()))
        # Empujar dentro del área — el TOP se ajusta al final para priorizar
        # que la barra de título siempre quede visible.
        if nf.right() > avail.right():
            nf.moveRight(avail.right())
        if nf.bottom() > avail.bottom():
            nf.moveBottom(avail.bottom())
        if nf.left() < avail.left():
            nf.moveLeft(avail.left())
        if nf.top() < avail.top():
            nf.moveTop(avail.top())
        if nf == fg:
            return
        # Traducir el rect del MARCO deseado a geometría del CLIENTE (setGeometry
        # trabaja sin marco): restar los márgenes del marco nativo.
        g = self.geometry()
        fm_l = g.left() - fg.left()
        fm_t = g.top()  - fg.top()
        fm_w = fg.width()  - g.width()
        fm_h = fg.height() - g.height()
        cw = max(self.minimumWidth(),  nf.width()  - fm_w)
        ch = max(self.minimumHeight(), nf.height() - fm_h)
        self.setGeometry(nf.left() + fm_l, nf.top() + fm_t, cw, ch)

    def set_usuario(self, usuario: Usuario):
        self.usuario = usuario
        self._proyectos_abiertos = []
        if hasattr(self, '_lbl_usuario_hdr'):
            self._lbl_usuario_hdr.setText(usuario.nombre[:22])
        self._limpiar_stack()

        # Placeholder temporal mientras se construye el dashboard
        # (evita la "ventana negra" cuando hay 100+ proyectos y la
        # construcción del DashboardView tarda).
        from PySide6.QtWidgets import QLabel
        placeholder = QLabel("Cargando proyectos…")
        placeholder.setAlignment(Qt.AlignCenter)
        placeholder.setStyleSheet(
            f"color:{SLATE_300}; font-size:14px; background:{SILVER_100};"
        )
        self.stack.addWidget(placeholder)
        self.stack.setCurrentWidget(placeholder)

        # Diferir la carga real del dashboard a la siguiente iteración del
        # event loop, así Qt puede pintar el placeholder primero.
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self._ir_a_dashboard)

    def _limpiar_stack(self):
        while self.stack.count():
            w = self.stack.widget(0)
            self.stack.removeWidget(w)
            w.deleteLater()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build_ui(self):
        self._title_bar = None
        if self._barra_custom:
            # Wrapper que contiene la barra de título custom + el contenido real
            outer = QWidget()
            outer.setMouseTracking(True)
            outer.setStyleSheet(f"background: {SLATE_700};")
            self.setCentralWidget(outer)

            outer_vl = QVBoxLayout(outer)
            outer_vl.setContentsMargins(0, 0, 0, 0)
            outer_vl.setSpacing(0)

            # 1) Barra de título custom (cross-platform, tema oscuro)
            self._title_bar = _CustomTitleBar(self, outer)
            outer_vl.addWidget(self._title_bar)

            # 2) Container del contenido real (sidebar + páginas)
            central = QWidget()
            central.setStyleSheet(f"background: {SLATE_700};")
            outer_vl.addWidget(central, 1)
        else:
            # Barra del sistema — central widget directo, sin wrap
            central = QWidget()
            central.setStyleSheet(f"background: {SLATE_700};")
            self.setCentralWidget(central)

        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._make_sidebar())

        # Lado derecho: headerbar + contenido
        right = QWidget()
        right.setStyleSheet(f"background: {SILVER_100};")
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(0)
        self._headerbar = self._make_headerbar()
        rv.addWidget(self._headerbar)

        # Banner "← Volver al proyecto X" — visible solo cuando el usuario
        # vino desde un proyecto y está usando INEI/Configuración como atajo
        self._banner_volver = self._make_banner_volver()
        rv.addWidget(self._banner_volver)

        self.stack = QStackedWidget()
        self.stack.setStyleSheet(f"background: {SILVER_100};")
        rv.addWidget(self.stack, stretch=1)

        root.addWidget(right, stretch=1)

    # ── Sidebar ───────────────────────────────────────────────────────────────

    def _make_sidebar(self) -> QFrame:
        from utils.i18n import tr
        self._sb_collapsed = False
        self._sb = QFrame()
        self._sb.setFixedWidth(84)
        self._sb.setStyleSheet(f"background: {SLATE_700}; border: none;")
        sb = self._sb

        vl = QVBoxLayout(sb)
        vl.setContentsMargins(0, 8, 0, 8)
        vl.setSpacing(2)
        vl.setAlignment(Qt.AlignHCenter)

        # Logo — clic para ocultar sidebar
        btn_logo = QPushButton()
        btn_logo.setFixedSize(60, 60)
        btn_logo.setCursor(Qt.PointingHandCursor)
        btn_logo.setStyleSheet(
            "QPushButton { background:transparent; border:none; border-radius:8px; }"
            "QPushButton:hover { background:rgba(255,255,255,0.10); }"
        )
        from core.config import get_product_icon_path
        icon_path = get_product_icon_path()
        if icon_path and icon_path.exists():
            from PySide6.QtGui import QIcon as _QIcon
            btn_logo.setIcon(_QIcon(str(icon_path)))
            btn_logo.setIconSize(QSize(44, 44))
        else:
            btn_logo.setText("📋")
            btn_logo.setStyleSheet("color:white; font-size:30px; border:none;")
        btn_logo.setToolTip(tr("Ocultar menú lateral"))
        btn_logo.clicked.connect(self._toggle_sidebar)
        vl.addWidget(btn_logo, alignment=Qt.AlignHCenter)

        # Contenido colapsable (todo excepto el logo)
        self._sb_content = QWidget()
        self._sb_content.setStyleSheet("background:transparent;")
        cv = QVBoxLayout(self._sb_content)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(2)

        # Helper: separador horizontal sutil entre grupos
        def _add_sep(alpha: float = 0.10, gap_before: int = 6,
                     gap_after: int = 4, width: int = 44):
            cv.addSpacing(gap_before)
            sep = QFrame()
            sep.setFixedHeight(1); sep.setFixedWidth(width)
            sep.setStyleSheet(
                f"background: rgba(255,255,255,{alpha:.2f}); border:none;"
            )
            cv.addWidget(sep, alignment=Qt.AlignCenter)
            cv.addSpacing(gap_after)

        # Separador inicial post-logo (más sutil)
        _add_sep(alpha=0.08, gap_before=0, gap_after=2)

        # ── Grupos lógicos de navegación ────────────────────────────────────
        # Cada grupo: (lista de items, separador después)
        from utils.i18n import tr
        self._nav_btns: list[_NavBtn] = []
        grupos_nav = [
            # Grupo 1 — Trabajo principal
            [("home",       tr("Inicio"),      self._ir_a_dashboard),
             ("nuevo",      tr("Nuevo"),       self._nuevo_proyecto)],
            # Grupo 2 — Datos / Catálogos (popover)
            [("catalogos",  "Catálogos",       self._mostrar_menu_catalogos)],
            # Grupo 3 — Transferencia entre instalaciones
            [("importar",   tr("Importar"),    self._ir_a_importar),
             ("exportar",   tr("Exportar"),    self._ir_a_exportar)],
        ]
        for g_i, grupo in enumerate(grupos_nav):
            for icon_name, label, handler in grupo:
                btn = _NavBtn(icon_name, label)
                btn.clicked.connect(lambda h=handler: h())
                cv.addWidget(btn, alignment=Qt.AlignHCenter)
                self._nav_btns.append(btn)
            # Separador entre grupos (no después del último)
            if g_i < len(grupos_nav) - 1:
                _add_sep(alpha=0.07, gap_before=4, gap_after=2, width=36)

        cv.addStretch()

        # Separador prominente antes del bloque de sistema (más visible)
        _add_sep(alpha=0.12, gap_before=4, gap_after=4)

        self._bot_btns: list[_NavBtn] = []
        bot_items = [
            # Nota: el acceso a IA/Tuxia ya vive dentro de Configuración
            # (pestaña «IA»), así que no se duplica aquí en el sidebar.
            ("configuracion", "Config",       self._ir_a_configuracion, "#E8EDF2"),
            ("acerca",        tr("Acerca de"), self._ir_a_acerca,       "#E8EDF2"),
            ("salir",         "Salir",        self._logout,             "#e74c3c"),
        ]
        for icon_name, label, handler, color in bot_items:
            btn = _NavBtn(icon_name, label, inactive_color=color)
            btn.clicked.connect(lambda h=handler: h())
            cv.addWidget(btn, alignment=Qt.AlignHCenter)
            self._bot_btns.append(btn)

        vl.addWidget(self._sb_content)
        return sb

    # ── Headerbar ─────────────────────────────────────────────────────────────

    def _make_headerbar(self) -> QFrame:
        # Barra superior de accesos rápidos ELIMINADA: sus botones (Nuevo
        # Proyecto, Importar, Biblioteca CU, Insumos, Configuración, IA) ya
        # viven en el sidebar y eran redundantes. Se conserva un frame vacío
        # de altura 0 para no romper las ~15 llamadas a
        # self._headerbar.setVisible() repartidas por la navegación.
        bar = QFrame()
        bar.setFixedHeight(0)
        bar.setStyleSheet("QFrame { background: transparent; border: none; }")
        return bar

    # ── Navegación ────────────────────────────────────────────────────────────

    def _activar_nav(self, idx: int):
        for i, btn in enumerate(self._nav_btns):
            btn.setChecked(i == idx)
        for btn in self._bot_btns:
            btn.setChecked(False)

    def _activar_bot(self, idx: int):
        for btn in self._nav_btns:
            btn.setChecked(False)
        for i, btn in enumerate(self._bot_btns):
            btn.setChecked(i == idx)

    def _cargar_vista(self, nombre: str):
        from PySide6.QtCore import QTimer
        for i in range(self.stack.count()):
            if self.stack.widget(i).property("vista_nombre") == nombre:
                self.stack.setCurrentIndex(i)
                # Recargar el dashboard DESPUÉS del cambio de vista para
                # que el cambio se sienta instantáneo y el query corra en
                # el siguiente frame.
                w = self.stack.widget(i)
                if nombre == "dashboard" and hasattr(w, "cargar_proyectos"):
                    QTimer.singleShot(0, w.cargar_proyectos)
                return
        vista = self._crear_vista(nombre)
        if vista:
            vista.setProperty("vista_nombre", nombre)
            self.stack.addWidget(vista)
            self.stack.setCurrentWidget(vista)

    def _crear_vista(self, nombre: str):
        match nombre:
            case "dashboard":
                from views.dashboard_view import DashboardView
                v = DashboardView(self.usuario)
                v.abrir_proyecto.connect(self._abrir_proyecto)
                v.nuevo_proyecto.connect(self._nuevo_proyecto)
                v.editar_proyecto_solicitado.connect(self._abrir_editar_proyecto)
                v.ir_a_importar.connect(self._ir_a_importar)
                return v
            case "recursos":
                from views.recursos_view import RecursosView
                return RecursosView()
            case "biblioteca":
                from views.biblioteca_view import BibliotecaView
                return BibliotecaView()
            case "importar":
                from views.importar_view import ImportarView
                v = ImportarView()
                v.proyecto_importado.connect(self._abrir_proyecto)
                v.volver.connect(lambda: self._cargar_vista("dashboard"))
                return v
            case "exportar":
                from views.exportar_view import ExportarView
                v = ExportarView()
                v.volver.connect(lambda: self._cargar_vista("dashboard"))
                return v
            case "indices_inei":
                from views.indices_inei_view import IndicesINEIView
                return IndicesINEIView()
            case "ia":
                from views.ia_view import IAView
                return IAView()
            case "configuracion":
                from views.configuracion_view import ConfiguracionView
                return ConfiguracionView()
            case "acerca":
                from views.acerca_view import AcercaView
                return AcercaView()
        return None

    # ── Banner "Volver al proyecto" ─────────────────────────────────────────
    def _make_banner_volver(self) -> QFrame:
        """Banner sticky para regresar al proyecto desde un atajo global."""
        bar = QFrame()
        bar.setFixedHeight(34)
        bar.setStyleSheet(
            f"QFrame {{ background:{BLUEBERRY_DK}; border-bottom:1px solid {BLUEBERRY}; }}"
        )
        hl = QHBoxLayout(bar)
        hl.setContentsMargins(14, 0, 14, 0)
        hl.setSpacing(8)
        self._btn_volver_proy = QPushButton("←  Volver al proyecto")
        self._btn_volver_proy.setCursor(Qt.PointingHandCursor)
        self._btn_volver_proy.setStyleSheet(
            "QPushButton { background:transparent; color:white; border:none;"
            " font-size:12px; font-weight:600; padding:6px 8px; text-align:left; }"
            "QPushButton:hover { color:#FFF9C4; }"
        )
        self._btn_volver_proy.clicked.connect(self._click_banner_volver)
        hl.addWidget(self._btn_volver_proy)

        self._lbl_volver_meta = QLabel("")
        self._lbl_volver_meta.setStyleSheet(
            "color:rgba(255,255,255,0.7); font-size:11px;"
        )
        hl.addWidget(self._lbl_volver_meta)
        hl.addStretch(1)

        bar.setVisible(False)   # oculto por defecto
        return bar

    def _mostrar_banner_volver(self, pid: int):
        """Muestra el banner con el nombre del proyecto al que volver."""
        from core.database import get_db
        try:
            conn = get_db()
            row = conn.execute(
                "SELECT nombre FROM proyectos WHERE id=?", (pid,)
            ).fetchone()
            conn.close()
            nombre = row['nombre'] if row else f"Proyecto {pid}"
        except Exception:
            nombre = f"Proyecto {pid}"

        nombre_corto = nombre[:50] + "…" if len(nombre) > 50 else nombre
        self._btn_volver_proy.setText(f"←  Volver al proyecto «{nombre_corto}»")
        self._lbl_volver_meta.setText("  ·  estás viendo un atajo global")
        self._volver_a_pid = pid
        self._banner_volver.setVisible(True)

    def _ocultar_banner_volver(self):
        self._volver_a_pid = None
        self._banner_volver.setVisible(False)

    def _click_banner_volver(self):
        """Click en el banner → regresa al proyecto guardado."""
        pid = self._volver_a_pid
        if pid is None:
            return
        self._ocultar_banner_volver()
        self._abrir_proyecto(pid)

    def _pid_proyecto_activo(self) -> int | None:
        """Si la vista actual es una ProyectoView, retorna su pid. Si no, None."""
        current = self.stack.currentWidget()
        if current is not None and hasattr(current, 'pid'):
            try:
                return int(current.pid)
            except Exception:
                return None
        return None

    def _abrir_proyecto(self, proyecto_id: int):
        nombre_vista = f"proyecto_{proyecto_id}"

        from core.database import get_db
        conn = get_db()
        row = conn.execute("SELECT nombre FROM proyectos WHERE id=?", (proyecto_id,)).fetchone()
        conn.close()
        nombre_proy = row['nombre'] if row else f"Proyecto {proyecto_id}"
        if sys.platform == 'win32':
            nombre_corto = nombre_proy[:120] + "…" if len(nombre_proy) > 120 else nombre_proy
            self.setWindowTitle(f"{nombre_corto}  —  IngePresupuestos")
        else:
            nombre_corto = nombre_proy[:60] + "…" if len(nombre_proy) > 60 else nombre_proy
            self.setWindowTitle(f"IngePresupuestos  -  {nombre_corto}")
        self._headerbar.setVisible(False)
        # Estamos volviendo a un proyecto — ocultar banner si estaba visible
        self._ocultar_banner_volver()

        # Añadir a la lista de proyectos abiertos si no está ya
        if not any(p['pid'] == proyecto_id for p in self._proyectos_abiertos):
            self._proyectos_abiertos.append({'pid': proyecto_id, 'nombre': nombre_proy})

        # Si ya existe la vista, solo cambiar a ella
        for i in range(self.stack.count()):
            if self.stack.widget(i).property("vista_nombre") == nombre_vista:
                self.stack.setCurrentIndex(i)
                self._notificar_tabs_proyectos()
                self._colapsar_sidebar()   # ← DESPUÉS de activar la vista
                # Sincronizar SIEMPRE el botón-logo de la vista activada: si el
                # sidebar ya estaba colapsado, _colapsar_sidebar no notifica y el
                # botón quedaría oculto al cambiar de pestaña.
                self._notificar_sidebar_estado()
                return

        # «Show first, load later»: la pestaña responde al clic AL INSTANTE
        # con una cáscara «Abriendo…», y la vista real (≈0.7 s de construcción
        # de UI, independiente del tamaño del proyecto) se arma un tick
        # después. Sin esto el clic se siente congelado.
        from PySide6.QtCore import QTimer
        ph = QWidget()
        ph.setProperty("vista_nombre", nombre_vista)
        _lay = QVBoxLayout(ph)
        _lbl = QLabel(f"Abriendo «{nombre_proy[:60]}»…")
        _lbl.setAlignment(Qt.AlignCenter)
        _lbl.setStyleSheet("color:#9aa5b4; font-size:14px; background:transparent; border:none;")
        _lay.addStretch(); _lay.addWidget(_lbl); _lay.addStretch()
        self.stack.addWidget(ph)
        self.stack.setCurrentWidget(ph)
        self._notificar_tabs_proyectos()
        self._colapsar_sidebar()

        def _construir_vista():
            if self.stack.indexOf(ph) < 0:
                return   # la pestaña se cerró antes de construirse
            self._construir_proyecto_view(proyecto_id, nombre_vista, ph)

        QTimer.singleShot(20, _construir_vista)
        return

    def _construir_proyecto_view(self, proyecto_id: int, nombre_vista: str, ph):
        from views.proyecto_view import ProyectoView
        vista = ProyectoView(proyecto_id, self.usuario)
        vista.setProperty("vista_nombre", nombre_vista)
        vista.editar_proyecto_solicitado.connect(self._abrir_editar_proyecto)
        vista.cambiar_a_proyecto.connect(self._abrir_proyecto)
        vista.cerrar_proyecto.connect(self._cerrar_proyecto_tab)
        vista.ir_a_proyectos.connect(self._ir_a_dashboard)
        vista.toggle_sidebar.connect(self._toggle_sidebar)
        # Atajos globales desde la toolbar del proyecto (sidebar oculto)
        vista.ir_a_indices_inei.connect(self._ir_a_indices_inei)
        vista.ir_a_ia.connect(self._ir_a_ia)
        vista.ir_a_configuracion.connect(self._ir_a_configuracion)
        vista.ir_a_nuevo_proyecto.connect(self._nuevo_proyecto)
        vista.ir_a_importar.connect(self._ir_a_importar)
        vista.ir_a_acerca.connect(self._ir_a_acerca)
        era_actual = (self.stack.currentWidget() is ph)
        idx = self.stack.indexOf(ph)
        self.stack.removeWidget(ph)
        ph.deleteLater()
        self.stack.insertWidget(idx, vista)
        if era_actual:
            self.stack.setCurrentWidget(vista)
        self._notificar_tabs_proyectos()
        self._colapsar_sidebar()           # ← DESPUÉS de añadir y activar la vista
        # Sincronizar SIEMPRE el botón-logo de la vista recién construida (si el
        # sidebar ya estaba colapsado, _colapsar_sidebar no la habría notificado).
        self._notificar_sidebar_estado()

    def _cerrar_proyecto_tab(self, proyecto_id: int):
        """Cierra la pestaña del proyecto y muestra otro proyecto o el dashboard."""
        # Quitar de la lista
        self._proyectos_abiertos = [p for p in self._proyectos_abiertos if p['pid'] != proyecto_id]

        # Buscar y eliminar la vista del stack
        nombre_vista = f"proyecto_{proyecto_id}"
        for i in range(self.stack.count()):
            w = self.stack.widget(i)
            if w.property("vista_nombre") == nombre_vista:
                self.stack.removeWidget(w)
                w.deleteLater()
                break

        # Cambiar a otro proyecto abierto o al dashboard
        if self._proyectos_abiertos:
            self._abrir_proyecto(self._proyectos_abiertos[-1]['pid'])
        else:
            self._ir_a_dashboard()

        self._notificar_tabs_proyectos()

    def _notificar_tabs_proyectos(self):
        """Actualiza la barra de tabs en todas las vistas de proyecto abiertas."""
        for i in range(self.stack.count()):
            w = self.stack.widget(i)
            if hasattr(w, 'set_proyectos_abiertos'):
                w.set_proyectos_abiertos(self._proyectos_abiertos)

    # ── Acciones de navegación ────────────────────────────────────────────────

    def closeEvent(self, event):
        """Antes de cerrar la ventana, garantizar un backup "on-exit" de la
        BD activa. Atómico (sqlite3 backup API) y rápido; si falla por
        cualquier motivo NO bloqueamos el cierre — la app debe poder
        cerrarse siempre."""
        # Drenar QThreads activos (update checker, etc.). Si el usuario
        # cierra antes de que termine un worker, Qt destruye el padre con
        # el thread aún corriendo → SIGABRT en el shutdown del proceso.
        try:
            from PySide6.QtCore import QThread
            for th in self.findChildren(QThread):
                if th.isRunning():
                    th.terminate()
                    th.wait(1000)
        except Exception:
            pass
        try:
            from core.backup import crear_backup, rotar_backups
            crear_backup('on-exit')
            rotar_backups()
        except Exception:
            pass
        super().closeEvent(event)

    def _toggle_sidebar(self):
        # Solo colapsar/expandir cuando hay un proyecto activo
        # En otras vistas la sidebar siempre permanece visible
        current = self.stack.currentWidget()
        es_proyecto = hasattr(current, 'set_proyectos_abiertos')
        if not es_proyecto:
            self._expandir_sidebar()
            return
        if self._sb_collapsed:
            self._sb.setVisible(True)
            self._sb_collapsed = False
        else:
            self._sb.setVisible(False)
            self._sb_collapsed = True
        self._notificar_sidebar_estado()

    def _colapsar_sidebar(self):
        if not self._sb_collapsed:
            self._sb.setVisible(False)
            self._sb_collapsed = True
            self._notificar_sidebar_estado()

    def _expandir_sidebar(self):
        if self._sb_collapsed:
            self._sb.setVisible(True)
            self._sb_collapsed = False
            self._notificar_sidebar_estado()

    def _notificar_sidebar_estado(self):
        """Notifica a todas las ProyectoView abiertas el estado del sidebar."""
        for i in range(self.stack.count()):
            w = self.stack.widget(i)
            if hasattr(w, 'actualizar_btn_sidebar'):
                w.actualizar_btn_sidebar(self._sb_collapsed)

    def _ir_a_dashboard(self):
        self._ocultar_banner_volver()
        self._expandir_sidebar()
        self._activar_nav(0)
        self._headerbar.setVisible(True)
        self._cargar_vista("dashboard")

    # ── Resize por bordes (FramelessWindowHint) ──────────────────────────────

    def _edge_at(self, pos: QPoint) -> str | None:
        """Detecta sobre qué borde/esquina está el cursor.
        Devuelve uno de: left, right, top, bottom, top-left, top-right,
        bottom-left, bottom-right, o None si está al medio."""
        if not self._barra_custom or self.isMaximized():
            return None
        m = self.RESIZE_MARGIN
        x, y = pos.x(), pos.y()
        w, h = self.width(), self.height()
        left   = x <= m
        right  = x >= w - m
        top    = y <= m
        bottom = y >= h - m
        if top and left:    return 'top-left'
        if top and right:   return 'top-right'
        if bottom and left: return 'bottom-left'
        if bottom and right:return 'bottom-right'
        if left:   return 'left'
        if right:  return 'right'
        if top:    return 'top'
        if bottom: return 'bottom'
        return None

    def _cursor_for_edge(self, edge: str | None) -> Qt.CursorShape:
        return {
            'left': Qt.SizeHorCursor, 'right': Qt.SizeHorCursor,
            'top': Qt.SizeVerCursor, 'bottom': Qt.SizeVerCursor,
            'top-left': Qt.SizeFDiagCursor, 'bottom-right': Qt.SizeFDiagCursor,
            'top-right': Qt.SizeBDiagCursor, 'bottom-left': Qt.SizeBDiagCursor,
        }.get(edge, Qt.ArrowCursor)

    def mouseMoveEvent(self, event):
        # Cursor adaptativo cuando NO hay un resize en curso
        if self._resize_edge is None:
            edge = self._edge_at(event.position().toPoint())
            self.setCursor(self._cursor_for_edge(edge))
        elif event.buttons() & Qt.LeftButton:
            self._do_resize(event.globalPosition().toPoint())
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            edge = self._edge_at(event.position().toPoint())
            if edge:
                # Wayland-friendly: pide al compositor que maneje el resize.
                # Funciona también en X11 vía _NET_WM_MOVERESIZE.
                qt_edge = _EDGE_QT_MAP.get(edge)
                wh = self.windowHandle()
                if qt_edge is not None and wh is not None and wh.startSystemResize(qt_edge):
                    event.accept()
                    return
                # Fallback manual (X11 sin _NET_WM_MOVERESIZE)
                self._resize_edge = edge
                self._resize_origin = event.globalPosition().toPoint()
                self._resize_geom = self.geometry()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self._resize_edge = None
        self.setCursor(Qt.ArrowCursor)
        super().mouseReleaseEvent(event)

    def _do_resize(self, global_pos: QPoint):
        if not self._resize_edge or self._resize_geom is None:
            return
        dx = global_pos.x() - self._resize_origin.x()
        dy = global_pos.y() - self._resize_origin.y()
        g = QRect(self._resize_geom)
        min_w, min_h = self.minimumWidth(), self.minimumHeight()
        if 'right' in self._resize_edge:
            g.setRight(max(g.left() + min_w, g.right() + dx))
        if 'bottom' in self._resize_edge:
            g.setBottom(max(g.top() + min_h, g.bottom() + dy))
        if 'left' in self._resize_edge:
            new_left = min(g.right() - min_w, g.left() + dx)
            g.setLeft(new_left)
        if 'top' in self._resize_edge:
            new_top = min(g.bottom() - min_h, g.top() + dy)
            g.setTop(new_top)
        self.setGeometry(g)
        self.setWindowTitle("IngePresupuestos")

    def _nuevo_proyecto(self):
        if not self.usuario:
            return
        self._expandir_sidebar()
        self._activar_nav(1)
        self._headerbar.setVisible(False)

        # Reutilizar la vista si ya existe, limpiarla si no
        for i in range(self.stack.count()):
            w = self.stack.widget(i)
            if w.property("vista_nombre") == "nuevo_proyecto":
                w.limpiar()
                self.stack.setCurrentIndex(i)
                if sys.platform == 'win32':
                    self.setWindowTitle("Nuevo Proyecto  —  IngePresupuestos")
                else:
                    self.setWindowTitle("IngePresupuestos  -  Nuevo Proyecto")
                return

        from views.nuevo_proyecto_view import NuevoProyectoView
        vista = NuevoProyectoView(self.usuario)
        vista.setProperty("vista_nombre", "nuevo_proyecto")

        vista.cancelado.connect(self._ir_a_dashboard)
        vista.proyecto_creado.connect(self._on_proyecto_creado)

        self.stack.addWidget(vista)
        self.stack.setCurrentWidget(vista)
        if sys.platform == 'win32':
            self.setWindowTitle("Nuevo Proyecto  —  IngePresupuestos")
        else:
            self.setWindowTitle("IngePresupuestos  -  Nuevo Proyecto")

    def _abrir_editar_proyecto(self, proyecto_id: int):
        """Abre NuevoProyectoView en modo edición para el proyecto dado."""
        nombre_vista = f"editar_proyecto_{proyecto_id}"
        for i in range(self.stack.count()):
            if self.stack.widget(i).property("vista_nombre") == nombre_vista:
                self.stack.setCurrentIndex(i)
                return

        from views.nuevo_proyecto_view import NuevoProyectoView
        vista = NuevoProyectoView(self.usuario, proyecto_id=proyecto_id)
        vista.setProperty("vista_nombre", nombre_vista)

        def _al_cancelar():
            self.stack.removeWidget(vista)
            vista.deleteLater()
            self._volver_a_proyecto(proyecto_id)

        def _al_guardar(pid):
            self.stack.removeWidget(vista)
            vista.deleteLater()
            self._volver_a_proyecto(pid)

        vista.cancelado.connect(_al_cancelar)
        vista.proyecto_editado.connect(_al_guardar)

        self._headerbar.setVisible(False)
        self.stack.addWidget(vista)
        self.stack.setCurrentWidget(vista)

    def _volver_a_proyecto(self, proyecto_id: int):
        """Vuelve a la vista del proyecto (o dashboard) y recarga datos.

        Optimización: la recarga del dashboard (cara con muchos proyectos) y
        el recargar_tras_edicion se difieren con ``QTimer.singleShot(0, …)``
        para que el cambio visual a la vista del proyecto sea inmediato y el
        usuario no perciba lag al cancelar/guardar la edición."""
        from PySide6.QtCore import QTimer

        # 1. Cambio de vista PRIMERO — instantáneo para el usuario.
        nombre_vista = f"proyecto_{proyecto_id}"
        self._headerbar.setVisible(False)
        vista_proy = None
        for i in range(self.stack.count()):
            w = self.stack.widget(i)
            if w.property("vista_nombre") == nombre_vista:
                vista_proy = w
                self.stack.setCurrentIndex(i)
                break

        # 2. Trabajo costoso DESPUÉS del repaint:
        #    - recargar dashboard (no visible ahora, sin urgencia)
        #    - refrescar la vista del proyecto con los nuevos datos editados
        def _refrescar_diferido():
            for w in [self.stack.widget(i) for i in range(self.stack.count())]:
                if (w.property("vista_nombre") == "dashboard"
                        and hasattr(w, 'cargar_proyectos')):
                    w.cargar_proyectos()
            if vista_proy is not None and hasattr(vista_proy, 'recargar_tras_edicion'):
                vista_proy.recargar_tras_edicion()

        if vista_proy is not None:
            QTimer.singleShot(0, _refrescar_diferido)
            return

        # Si no hay vista del proyecto abierta, ir al dashboard (este sí se ve,
        # así que recargamos en el camino).
        self._ir_a_dashboard()

    def _on_proyecto_creado(self, proyecto_id: int):
        """Tras crear el proyecto, abre directamente su vista."""
        # Recargar dashboard si existe
        for i in range(self.stack.count()):
            w = self.stack.widget(i)
            if w.property("vista_nombre") == "dashboard":
                if hasattr(w, 'cargar_proyectos'):
                    w.cargar_proyectos()
        # Abrir el proyecto recién creado
        self._abrir_proyecto(proyecto_id)

    # ── Popover de Catálogos ────────────────────────────────────────────────
    def _mostrar_menu_catalogos(self):
        """Muestra un menú popover al lado del botón Catálogos del sidebar
        con las 3 opciones: Insumos, Biblioteca CU, Índices INEI."""
        from PySide6.QtWidgets import QMenu
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QAction

        menu = QMenu(self)
        # Estilo coherente con el resto (heredado del QSS global de QMenu)
        a_ins = QAction(icon("insumos"), "Catálogo de Insumos", self)
        a_ins.setStatusTip("6950 recursos con precios e índices INEI")
        a_ins.triggered.connect(self._ir_a_recursos)
        menu.addAction(a_ins)

        a_bib = QAction(icon("biblioteca"), "Biblioteca de Costos Unitarios", self)
        a_bib.setStatusTip("Partidas-tipo reutilizables entre proyectos")
        a_bib.triggered.connect(self._ir_a_biblioteca)
        menu.addAction(a_bib)

        menu.addSeparator()
        a_inei = QAction(icon("rep-resumen"), "Índices Unificados INEI", self)
        a_inei.setStatusTip("Histórico mensual de los 72 índices oficiales")
        a_inei.triggered.connect(self._ir_a_indices_inei)
        menu.addAction(a_inei)

        # Posicionar al lado derecho del botón "Catálogos" (índice 2)
        if len(self._nav_btns) > 2:
            btn = self._nav_btns[2]
            pos = btn.mapToGlobal(QPoint(btn.width() - 4, 8))
        else:
            pos = self.cursor().pos()
        menu.exec(pos)

    def _ir_a_importar(self):
        self._expandir_sidebar()
        self._activar_nav(3)
        self._headerbar.setVisible(False)
        self._cargar_vista("importar")

    def _ir_a_exportar(self):
        self._expandir_sidebar()
        self._activar_nav(4)
        self._headerbar.setVisible(False)
        self._cargar_vista("exportar")

    def _ir_a_biblioteca(self):
        self._expandir_sidebar()
        self._activar_nav(2)              # botón "Catálogos"
        self._headerbar.setVisible(False)
        self._cargar_vista("biblioteca")

    def _ir_a_recursos(self):
        self._expandir_sidebar()
        self._activar_nav(2)              # botón "Catálogos"
        self._headerbar.setVisible(False)
        self._cargar_vista("recursos")

    def _ir_a_indices_inei(self):
        # Context-aware: si estamos en un proyecto (sidebar colapsado),
        # actuar como atajo modal — no expandir sidebar, mostrar banner
        # para volver al proyecto.
        if self._sb_collapsed:
            pid_actual = self._pid_proyecto_activo()
            self._cargar_vista("indices_inei")
            if pid_actual is not None:
                self._mostrar_banner_volver(pid_actual)
            return
        # Flujo normal con sidebar visible
        self._ocultar_banner_volver()
        self._expandir_sidebar()
        self._activar_nav(2)              # botón "Catálogos"
        self._headerbar.setVisible(False)
        self._cargar_vista("indices_inei")

    def _ir_a_configuracion(self):
        # Context-aware: si estamos en un proyecto, mostrar como atajo modal
        if self._sb_collapsed:
            pid_actual = self._pid_proyecto_activo()
            self._headerbar.setVisible(False)
            self._cargar_vista("configuracion")
            if pid_actual is not None:
                self._mostrar_banner_volver(pid_actual)
            return
        # Flujo normal con sidebar visible
        self._ocultar_banner_volver()
        self._expandir_sidebar()
        self._activar_bot(0)
        self._headerbar.setVisible(False)
        self._cargar_vista("configuracion")

    def _ir_a_acerca(self):
        self._expandir_sidebar()
        self._activar_bot(1)
        self._headerbar.setVisible(False)
        self._cargar_vista("acerca")

    def _ir_a_ia(self):
        """IA ahora vive como tab dentro de Configuración — redirigimos allí
        seleccionando la tab 'IA' al cargar la vista."""
        if self._sb_collapsed:
            pid_actual = self._pid_proyecto_activo()
            self._headerbar.setVisible(False)
            self._cargar_vista("configuracion")
            self._seleccionar_tab_config('ia')
            if pid_actual is not None:
                self._mostrar_banner_volver(pid_actual)
            return
        self._expandir_sidebar()
        self._headerbar.setVisible(False)
        self._cargar_vista("configuracion")
        self._seleccionar_tab_config('ia')

    def _seleccionar_tab_config(self, nombre: str):
        """Si la vista activa es ConfiguracionView, selecciona la tab pedida."""
        vista = self.stack.currentWidget()
        if vista is not None and hasattr(vista, 'set_tab'):
            vista.set_tab(nombre)

    def _logout(self):
        logout()
        self.close()
