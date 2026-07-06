# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""Tooltip personalizado — reemplaza QToolTip con un QLabel estilizado propio.

Evita el problema de Wayland/GTK que pinta el fondo del sistema en lugar
del color del QSS.

Uso explícito (legacy):
    from utils.tooltip import set_tooltip
    set_tooltip(mi_boton, "Copiar proyecto")

Uso global recomendado (una sola vez al iniciar la app):
    from utils.tooltip import install_global_tooltip_filter
    install_global_tooltip_filter(app)
    # … todas las llamadas widget.setToolTip("...") se convierten
    # automáticamente en _TipWindow blancos.
"""
from PySide6.QtWidgets import QLabel, QApplication, QWidget
from PySide6.QtCore import QObject, QEvent, QTimer, Qt, QPoint
from PySide6.QtGui import QCursor, QColor, QPalette


# ── Ventana del tooltip ───────────────────────────────────────────────────────

class _TipWindow(QLabel):
    """Ventana flotante con estilo Elementary OS (fondo blanco, texto oscuro)."""

    _inst: "_TipWindow | None" = None

    @classmethod
    def get(cls) -> "_TipWindow":
        if cls._inst is None:
            cls._inst = cls()
        return cls._inst

    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.ToolTip |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        # Translucent ON para que las esquinas REDONDEADAS no se rellenen
        # con el background opaco del sistema. El fondo blanco + borde +
        # border-radius se pintan manualmente en paintEvent — no por QSS,
        # porque con WA_TranslucentBackground el QSS background no aplica.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        # QSS solo para texto/padding/fuente; el fondo lo pinta paintEvent.
        self.setStyleSheet("""
            QLabel {
                background: transparent;
                color: #273445;
                border: none;
                padding: 6px 12px;
                font-family: "Ubuntu Sans", "Ubuntu", sans-serif;
                font-size: 11px;
            }
        """)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def paintEvent(self, ev):
        # Pinta un rectángulo blanco con esquinas redondeadas + borde slate-200.
        # Esto reemplaza al `background-color`/`border`/`border-radius` del
        # QSS, que no se aplican cuando el widget tiene WA_TranslucentBackground.
        from PySide6.QtGui import QPainter, QPainterPath, QColor, QPen
        from PySide6.QtCore import QRectF
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
            path = QPainterPath()
            path.addRoundedRect(rect, 6, 6)
            painter.fillPath(path, QColor("#FFFFFF"))
            pen = QPen(QColor("#D4D4D4"))
            pen.setWidthF(1.0)
            painter.setPen(pen)
            painter.drawPath(path)
        finally:
            painter.end()
        super().paintEvent(ev)

    def show_at(self, text: str, pos: QPoint):
        self.setText(text)
        self.adjustSize()
        # Desplazar ligeramente del cursor
        x = pos.x() + 14
        y = pos.y() + 14
        # Geometría del monitor donde está el cursor — soporta multi-monitor
        # (primaryScreen falla cuando la ventana está en una pantalla
        # secundaria).
        screen_obj = QApplication.screenAt(pos) or QApplication.primaryScreen()
        screen = screen_obj.availableGeometry()
        w, h = self.width(), self.height()
        # Si excede derecha, intentar a la izquierda del cursor
        if x + w > screen.right():
            x = pos.x() - w - 6
        # Si excede abajo, intentar arriba del cursor
        if y + h > screen.bottom():
            y = pos.y() - h - 6
        # Clamp final dentro del rectángulo visible — cubre el caso en que
        # ninguno de los dos lados alternativos quepa (cursor en esquina,
        # tooltip más alto que la mitad de la pantalla, etc.).
        x = max(screen.left(), min(x, screen.right() - w))
        y = max(screen.top(),  min(y, screen.bottom() - h))
        self.move(x, y)
        self.show()
        self.raise_()
        self._timer.stop()

    def hide_delayed(self, ms: int = 200):
        self._timer.start(ms)


# ── Filtro de eventos ─────────────────────────────────────────────────────────

class _TooltipFilter(QObject):
    """Intercepta Enter/Leave del widget para mostrar/ocultar el tooltip."""

    def __init__(self, text: str, delay: int, parent: QObject):
        super().__init__(parent)
        self._text  = text
        self._delay = delay
        self._show_timer = QTimer(self)
        self._show_timer.setSingleShot(True)
        self._show_timer.setInterval(delay)
        self._show_timer.timeout.connect(self._mostrar)

    def eventFilter(self, watched, event):
        t = event.type()
        if t == QEvent.Type.Enter:
            self._show_timer.start()
        elif t in (
            QEvent.Type.Leave,
            QEvent.Type.MouseButtonPress,
            QEvent.Type.KeyPress,
            QEvent.Type.Hide,
        ):
            self._show_timer.stop()
            _TipWindow.get().hide()
        return False

    def _mostrar(self):
        _TipWindow.get().show_at(self._text, QCursor.pos())


# ── API pública ───────────────────────────────────────────────────────────────

def set_tooltip(widget, text: str, delay: int = 600):
    """Instala un tooltip personalizado en el widget.

    Elimina el tooltip nativo (negro del sistema) y reemplaza con
    uno blanco de estilo Elementary OS.

    Args:
        widget: QWidget destino
        text:   Texto del tooltip
        delay:  Milisegundos antes de aparecer (default 600ms)
    """
    if not text:
        return
    widget.setToolTip("")   # quitar tooltip nativo
    f = _TooltipFilter(text, delay, widget)
    widget.installEventFilter(f)


# ── Filtro global ─────────────────────────────────────────────────────────────

class _GlobalTooltipFilter(QObject):
    """Filter a nivel de QApplication que intercepta QEvent.ToolTip y muestra
    el ``_TipWindow`` blanco en lugar del tooltip nativo (negro en algunos WMs).

    Se instala una sola vez con ``install_global_tooltip_filter(app)``. A partir
    de ahí, cualquier ``widget.setToolTip("texto")`` se renderiza con el estilo
    blanco propio sin tener que migrar las llamadas existentes."""

    def eventFilter(self, watched, event):
        t = event.type()
        # Mostrar tooltip cuando Qt iba a mostrar el nativo
        if t == QEvent.Type.ToolTip and isinstance(watched, QWidget):
            text = watched.toolTip()
            if text:
                _TipWindow.get().show_at(text, QCursor.pos())
                # Auto-ocultar después de unos segundos como hace Qt
                _TipWindow.get().hide_delayed(8000)
                return True   # consumir → evita el tooltip nativo
            return False
        # Ocultar cuando el mouse sale del widget o el usuario interactúa
        if t in (QEvent.Type.Leave,
                 QEvent.Type.MouseButtonPress,
                 QEvent.Type.MouseButtonRelease,
                 QEvent.Type.KeyPress,
                 QEvent.Type.Wheel,
                 QEvent.Type.FocusOut,
                 QEvent.Type.Hide):
            tip = _TipWindow.get()
            if tip.isVisible():
                tip.hide()
        return False


_global_filter: "_GlobalTooltipFilter | None" = None


def install_global_tooltip_filter(app: QApplication) -> None:
    """Instala un filtro global de tooltips para toda la app.

    Llamar una única vez justo después de crear ``QApplication``. Reemplaza
    el tooltip nativo de Qt por el ``_TipWindow`` blanco — todas las
    llamadas ``widget.setToolTip(...)`` existentes pasan a verse claras
    sin requerir cambios en sus call sites."""
    global _global_filter
    if _global_filter is not None:
        return
    _global_filter = _GlobalTooltipFilter()
    app.installEventFilter(_global_filter)


# ── Popups: garantizar fondo blanco bajo temas dark del sistema ──────────────
# QComboBox, QMenu, QCompleter, QCalendarWidget y los popups con flag
# Qt.Popup heredan el QPalette del tema del sistema (Yaru-dark, Adwaita-dark)
# y muestran franjas oscuras entre items. Hay que forzar QPalette + stylesheet
# + viewport en cada uno por separado vía un eventFilter global.

_COMBO_POPUP_QSS = """
QAbstractItemView {
    background: #FFFFFF;
    color: #273445;
    border: none;
    selection-background-color: #FEF5EB;
    selection-color: #C0621A;
    outline: none;
    padding: 4px;
    alternate-background-color: #FFFFFF;
    show-decoration-selected: 1;
}
QAbstractItemView::item {
    background: #FFFFFF;
    color: #273445;
    padding: 5px 10px;
    border: none;
    border-radius: 4px;
    min-height: 22px;
}
QAbstractItemView::item:hover,
QAbstractItemView::item:selected {
    background: #FEF5EB;
    color: #C0621A;
}
"""

_MENU_QSS = """
QMenu {
    background: #FFFFFF;
    color: #273445;
    border: 1px solid #D4D4D4;
    border-radius: 8px;
    padding: 6px;
}
QMenu::item {
    background: transparent;
    color: #273445;
    padding: 6px 18px 6px 22px;
    border-radius: 5px;
    font-size: 12px;
}
QMenu::item:selected {
    background: #FEF5EB;
    color: #C0621A;
}
QMenu::separator {
    height: 1px;
    background: #E8EBED;
    margin: 4px 8px;
}
"""

_CALENDAR_QSS = """
QCalendarWidget QWidget { background: #FFFFFF; color: #273445; }
QCalendarWidget QAbstractItemView { background: #FFFFFF; color: #273445;
    selection-background-color: #FEF5EB; selection-color: #C0621A;
    alternate-background-color: #FFFFFF; outline: none; }
QCalendarWidget QToolButton { background: #FFFFFF; color: #273445;
    border: none; padding: 4px 8px; border-radius: 4px; }
QCalendarWidget QToolButton:hover { background: #F1F3F5; }
QCalendarWidget QSpinBox { background: #FFFFFF; color: #273445;
    border: 1px solid #D4D4D4; border-radius: 4px; }
QCalendarWidget QMenu { background: #FFFFFF; color: #273445; }
"""


def _force_white_palette(widget) -> None:
    """Aplica un QPalette blanco/slate al widget para anular el palette dark
    del sistema (Yaru-dark, Adwaita-dark). NO toca el stylesheet."""
    pal = widget.palette()
    white = QColor("#FFFFFF")
    ink   = QColor("#273445")
    for role in (QPalette.Base, QPalette.Window,
                 QPalette.AlternateBase, QPalette.Button):
        pal.setColor(role, white)
    pal.setColor(QPalette.Text, ink)
    pal.setColor(QPalette.WindowText, ink)
    pal.setColor(QPalette.ButtonText, ink)
    pal.setColor(QPalette.Highlight, QColor("#FEF5EB"))
    pal.setColor(QPalette.HighlightedText, QColor("#C0621A"))
    widget.setPalette(pal)


def _fix_item_view_popup(view) -> None:
    """Aplica el palette + stylesheet + viewport blanco a un item view popup
    (usado por QComboBox.view() y por QCompleter.popup()).

    El border + border-radius van SOLO al view (que llena visualmente el
    popup window). Al popup window contenedor solo le ponemos bg blanco —
    si le pusiéramos también border:1px solid, aparecería un "marco dentro
    de marco" porque el view ya tiene el suyo."""
    from PySide6.QtWidgets import QFrame
    if view.styleSheet() != _COMBO_POPUP_QSS:
        view.setStyleSheet(_COMBO_POPUP_QSS)
    view.setAlternatingRowColors(False)
    try:
        view.setFrameShape(QFrame.NoFrame)
    except Exception:
        pass
    _force_white_palette(view)
    vp = view.viewport()
    if vp is not None:
        _force_white_palette(vp)
        vp.setAutoFillBackground(True)
        vp.setStyleSheet("background:#FFFFFF;")
    popup = view.window()
    if popup is not None and popup is not view:
        _force_white_palette(popup)
        # Border + radius van SOLO al popup window mediante objectName,
        # no a sus QWidget descendientes (incluido el view) — así evitamos
        # "marco dentro de marco". El selector `#name` no matchea hijos.
        if not popup.objectName():
            popup.setObjectName("ingePopupFrame")
        oname = popup.objectName()
        popup.setStyleSheet(
            "QWidget { background:#FFFFFF; color:#273445; }"
            f"#{oname} {{ border:1px solid #D4D4D4; border-radius:6px; }}"
        )


class _DarkThemePopupFilter(QObject):
    """Filter unificado que arregla popups bajo temas dark del sistema
    (Yaru-dark/Adwaita-dark). Cubre:

    - **QComboBox** — dropdown del combo.
    - **QMenu** — menús contextuales (click derecho) y de botón (setMenu).
    - **QCalendarWidget** — selectores de fecha con grid de cells.
    - **QListView/QListWidget/QTreeView con Qt.Popup** — popups de
      QCompleter (autocomplete) y similares.

    Para QListView/QListWidget/QTreeView/QTreeWidget *no* popup (los embebidos
    en vistas normales) NO se toca nada — esos suelen tener estilos propios
    y aplicar este filter sería invasivo."""

    def eventFilter(self, watched, event):
        if event.type() != QEvent.Type.Polish:
            return False

        from PySide6.QtWidgets import (
            QComboBox, QMenu, QCalendarWidget,
            QListView, QListWidget, QTreeView, QTreeWidget,
        )

        try:
            if isinstance(watched, QComboBox):
                # Patch preventivo: `combobox-popup: 0` hace que el popup
                # respete setMaxVisibleItems y muestre scrollbar en lugar
                # de estirarse a pantalla completa cuando hay muchos items
                # (bug Wayland conocido — ver [[feedback-qcombobox-popup-height-bug]]).
                # Sólo inyectar si el call-site no lo definió ya.
                current_ss = watched.styleSheet()
                if "combobox-popup" not in current_ss:
                    watched.setStyleSheet(
                        "QComboBox { combobox-popup: 0; }" + current_ss
                    )
                view = watched.view()
                if view is not None:
                    _fix_item_view_popup(view)

            elif isinstance(watched, QMenu):
                if watched.styleSheet() != _MENU_QSS:
                    watched.setStyleSheet(_MENU_QSS)
                _force_white_palette(watched)
                # En Linux Wayland/GNOME los QMenu anclados a un widget (sidebar
                # buttons, toolbars) renderizan con shape custom del compositor
                # que ignora el `border-radius` del QSS en el lado anclado.
                # Translucent + Frameless dejan al QSS dibujar la forma completa.
                watched.setAttribute(Qt.WA_TranslucentBackground, True)

            elif isinstance(watched, QCalendarWidget):
                if watched.styleSheet() != _CALENDAR_QSS:
                    watched.setStyleSheet(_CALENDAR_QSS)
                _force_white_palette(watched)
                # Propagar palette a los subwidgets internos (navigation bar,
                # date table, header) que tienen palette propio del sistema.
                for child in watched.findChildren(QWidget):
                    _force_white_palette(child)

            elif isinstance(watched, (QListView, QListWidget,
                                       QTreeView, QTreeWidget)):
                # Solo popups (QCompleter.popup() etc.) — los item views
                # embebidos en otras vistas conservan su estilo propio.
                if watched.windowFlags() & Qt.Popup:
                    _fix_item_view_popup(watched)
        except Exception:
            # No queremos que un fallo en el filter rompa el polish del widget.
            pass

        return False


_popup_filter: "_DarkThemePopupFilter | None" = None


def install_global_popup_styles(app: QApplication) -> None:
    """Instala el filter global que arregla todos los popups (QComboBox,
    QMenu, QCalendarWidget, QCompleter popup) bajo temas dark del sistema.

    Llamar una sola vez al iniciar la app, después de ``QApplication(...)``."""
    global _popup_filter
    if _popup_filter is not None:
        return
    _popup_filter = _DarkThemePopupFilter()
    app.installEventFilter(_popup_filter)


# Alias backward-compatible: el nombre histórico cubría solo QComboBox; ahora
# instala el filter unificado que también arregla QMenu / QCalendar / QCompleter.
def install_global_combo_popup_style(app: QApplication) -> None:
    install_global_popup_styles(app)
