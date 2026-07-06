# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""ingePresupuestos — PySide6 entry point."""
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# Backend Qt: por defecto Qt elige (xcb en Xorg, wayland en Wayland). Si el
# usuario exporta INGEPPTO_FORCE_XCB=1, se fuerza xcb (compat con la versión
# anterior — útil si algún WM raro tiene un bug en Wayland nativo).
# Debe establecerse ANTES de importar Qt.
if os.environ.get("INGEPPTO_FORCE_XCB") == "1":
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

# Escala de interfaz y barra de título — leer ANTES de crear QApplication
import sqlite3 as _sq
def _leer_config_db(clave: str, default: str = '') -> str:
    try:
        from core.config import DB_PATH
        con = _sq.connect(str(DB_PATH))
        row = con.execute("SELECT valor FROM configuracion WHERE clave=?", (clave,)).fetchone()
        con.close()
        return str(row[0]) if row else default
    except Exception:
        return default

_escala_ui = float(_leer_config_db('ui_escala', '1.0') or '1.0')
if _escala_ui != 1.0:
    os.environ["QT_SCALE_FACTOR"] = f"{_escala_ui:.2f}"

# Solo desactivar las decoraciones cliente de Qt en Wayland cuando el usuario
# usa la barra custom (FramelessWindowHint). Si usa la nativa, dejar que Qt
# pinte las decoraciones — si las desactivamos, la ventana queda sin titlebar.
# Default = '0' (barra nativa del sistema). Más profesional para perfiles
# enterprise y respeta el tema del WM. El usuario puede activar la barra
# custom en Configuración → General → Barra de título.
_barra_custom = (_leer_config_db('barra_titulo_custom', '0') == '1')
if _barra_custom:
    os.environ.setdefault("QT_WAYLAND_DISABLE_WINDOWDECORATION", "1")

from PySide6.QtWidgets import QApplication, QDialog
from PySide6.QtGui import QIcon, QFont, QPalette, QColor, QGuiApplication
from PySide6.QtCore import QTranslator, QLocale, QLibraryInfo, Qt

from core.database import init_db
from core.config import BASE_DIR


def _aplicar_paleta_tooltip(app: QApplication):
    """Fuerza colores de tooltip + enlaces vía QPalette — anula el tema del
    sistema. El color de enlace (Link) afecta a TODOS los <a href> de la app
    (config IA, índices INEI, etc.): arándano oscuro, legible y consistente."""
    palette = app.palette()
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#273445"))
    palette.setColor(QPalette.ColorRole.Link, QColor("#0A3D91"))         # arándano oscuro
    palette.setColor(QPalette.ColorRole.LinkVisited, QColor("#06286B"))  # aún más oscuro
    app.setPalette(palette)


def _aplicar_barra_titulo_oscura(ventana) -> None:
    """En X11/XCB, sugiere al WM usar la variante oscura del tema del
    sistema para la barra de título de esta ventana (atom GTK estándar
    `_GTK_THEME_VARIANT=dark`). Soportado por Mutter (GNOME), KWin,
    Cinnamon, Xfwm4. Silencioso si falla (otro backend, xprop ausente)."""
    try:
        if os.environ.get("QT_QPA_PLATFORM", "") not in ("xcb", ""):
            return
        import shutil
        import subprocess
        if not shutil.which("xprop"):
            return
        wid = int(ventana.winId())
        if not wid:
            return
        subprocess.run(
            ["xprop", "-id", str(wid),
             "-f", "_GTK_THEME_VARIANT", "8u",
             "-set", "_GTK_THEME_VARIANT", "dark"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=2,
        )
    except Exception:
        pass


def main():
    # Bajo Flatpak, /tmp es privado del sandbox y el LibreOffice/mdbtools del
    # host (invocados vía flatpak-spawn) no lo ven. Redirigir los temporales a
    # un directorio bajo el home de la app (ruta real, visible desde el host)
    # para que la conversión ODT/ODS y la lectura de .prs funcionen.
    try:
        from core.config import es_flatpak, USER_DATA_DIR
        if es_flatpak():
            import tempfile
            _tmp = USER_DATA_DIR / "tmp"
            _tmp.mkdir(parents=True, exist_ok=True)
            os.environ["TMPDIR"] = str(_tmp)
            tempfile.tempdir = str(_tmp)
    except Exception:
        pass

    init_db()

    # Backup automático "daily" al iniciar (idempotente: si ya existe el de
    # hoy, no duplica). Luego rotación según política.
    try:
        from core.backup import crear_backup, rotar_backups
        crear_backup('daily')
        rotar_backups()
    except Exception:
        # Nunca bloquear el arranque por un problema de backup
        pass

    # Fractional scaling sin redondear (necesario para snap a mitad de pantalla
    # bajo Wayland + Mutter cuando el monitor está a 1.25x, 1.5x, 1.75x, etc.).
    # Si redondeáramos a entero, Qt reportaría una geometría distinta a la que
    # el compositor espera → snap queda chico o la ventana sale de pantalla.
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("ingePresupuestos")
    app.setApplicationVersion("2.0")
    app.setOrganizationName("Ing. Marco Sumari Tellez")

    # Traducir todos los textos Qt internos al español
    _translations_path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    _locale = QLocale(QLocale.Language.Spanish)
    for _qm in ("qtbase_es", "qt_es"):
        _t = QTranslator(app)
        if _t.load(_qm, _translations_path):
            app.installTranslator(_t)

    # Ícono del PRODUCTO (ventana + barra de tareas) — NO es Tuxia.
    # Tuxia es el asistente IA dentro de la app, ingePresupuestos es el
    # producto y tiene su propio logo (rect naranja + tabla + Σ).
    from core.config import get_product_icon_path
    icon_path = get_product_icon_path()
    if icon_path and icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    # Cargar Inter (variable font, regular + italic) ANTES de cualquier
    # widget — usada en los reportes PDF/Word/Excel y disponible como
    # fuente del sistema (cross-platform consistente: el PDF se ve
    # idéntico en Linux/Windows/macOS sin importar qué tenga el usuario
    # instalado).
    try:
        from PySide6.QtGui import QFontDatabase
        _fonts_dir = BASE_DIR / "resources" / "fonts"
        for _ttf in ("Inter.ttf", "Inter-Italic.ttf",
                     "Inter-Bold.ttf", "Inter-BoldItalic.ttf"):
            _path = _fonts_dir / _ttf
            if _path.exists():
                QFontDatabase.addApplicationFont(str(_path))
    except Exception:
        pass

    # Instalar Inter en el directorio de fuentes del usuario (idempotente)
    # para que LibreOffice/Word también la usen al abrir reportes .odt/.docx.
    try:
        from core.config import es_flatpak
        # Bajo Flatpak instalar fuentes system-wide no aplica (sandbox); la UI
        # ya carga Inter vía QFontDatabase y LibreOffice del host usa las suyas.
        if not es_flatpak():
            from core.fonts_installer import instalar_fuentes_si_falta
            instalar_fuentes_si_falta()
    except Exception:
        pass

    # Trial de 30 días al primer arranque (no-op si ya existe license.json).
    # El trial es full: el usuario tiene 30 días de todo premium sin tocar
    # nada. Tras vencer, los exports editables / cronogramas / Gantt PDF
    # quedan bloqueados; PDF queda libre siempre.
    try:
        from core.licencia import iniciar_trial_si_falta
        iniciar_trial_si_falta()
    except Exception:
        pass

    # Font global de la UI = misma que reportes (Inter). Cross-platform
    # consistente — Inter va bundleada con la app via QFontDatabase.
    app.setFont(QFont("Inter", 10))

    qss_path = BASE_DIR / "resources" / "styles" / "main.qss"
    if qss_path.exists():
        _qss = qss_path.read_text(encoding="utf-8")
        # Las url() del QSS son relativas («resources/icons/check.svg»): Qt las
        # resuelve contra el CWD, que en el binario empaquetado NO es el repo →
        # los íconos de checkbox/combo no cargaban y salían cuadraditos negros.
        # Reescribir a ruta ABSOLUTA bajo BASE_DIR para que resuelvan siempre.
        _res_abs = (BASE_DIR / "resources").as_posix()
        _qss = _qss.replace("url(resources/", f"url({_res_abs}/")
        app.setStyleSheet(_qss)

    # Forzar colores de tooltip (QPalette tiene más prioridad que el tema GTK)
    _aplicar_paleta_tooltip(app)

    # Reemplazar tooltips nativos por _TipWindow blanco a nivel global.
    # En GNOME/X11 el tema del sistema a veces pinta el tooltip nativo en
    # oscuro a pesar del QSS y QPalette; este filter intercepta el evento
    # y dibuja un QLabel propio con paleta clara.
    from utils.tooltip import (
        install_global_tooltip_filter,
        install_global_combo_popup_style,
    )
    install_global_tooltip_filter(app)
    # Garantizar que TODOS los popups de QComboBox tengan fondo blanco,
    # incluso si el call-site sobreescribió la QSS global con un
    # setStyleSheet local.
    install_global_combo_popup_style(app)

    from views.main_window import MainWindow
    from utils.auth import cargar_sesion, usuario_actual

    ventana = MainWindow(usuario=None)
    ventana.show()
    # Forzar el primer pintado de la ventana ANTES de cargar el dashboard
    # (con 400+ proyectos el dashboard tarda ~2s en construirse y, sin esto,
    # la ventana queda negra hasta que termina).
    app.processEvents()
    # Multi-monitor (Windows): asegurar que la barra de título quede visible.
    ventana.asegurar_visible()

    # Chequeo silencioso de actualizaciones (sin bloquear el arranque).
    # Se difiere 3s después del show para no competir con la carga del
    # dashboard y solo dispara si han pasado >24h del último check.
    from PySide6.QtCore import QTimer as _QTimer
    def _silent_update_check():
        try:
            from core.config import es_flatpak
            # Bajo Flatpak las actualizaciones llegan por `flatpak update`, no
            # por el instalador propio → no ofrecer el auto-update.
            if es_flatpak():
                return
            from views.update_dialog import lanzar_check
            lanzar_check(ventana, silencioso=True)
        except Exception:
            pass
    _QTimer.singleShot(3000, _silent_update_check)

    # ── Intentar recuperar sesión guardada ────────────────────────────────────
    sesion = cargar_sesion()
    if sesion:
        # Sesión válida → entrar directamente sin login
        from utils.auth import _usuario_actual as _dummy  # noqa: F401
        import utils.auth as _auth
        _auth._usuario_actual = sesion
        # Diferir set_usuario al event loop para que el placeholder
        # "Cargando proyectos…" sea visible mientras se construye el dashboard
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, lambda: ventana.set_usuario(sesion))
        app.exec()
        # Si hizo logout dentro de la app → continuar al bucle normal
        if usuario_actual() is not None:
            sys.exit(0)

    # ── Bucle de autenticación (login manual) ─────────────────────────────────
    while True:
        from views.login_dialog import LoginDialog
        dlg = LoginDialog(parent=ventana)

        dlg.adjustSize()
        geo = ventana.geometry()
        dlg.move(
            geo.x() + (geo.width()  - dlg.width())  // 2,
            geo.y() + (geo.height() - dlg.height()) // 2,
        )

        resultado = dlg.exec()
        usuario   = usuario_actual()

        if resultado != QDialog.Accepted or usuario is None:
            break

        ventana.set_usuario(usuario)
        ventana.show()
        ventana.asegurar_visible()
        app.exec()

        if usuario_actual() is not None:
            break   # cerró ventana sin logout → salir
        # logout → volver a mostrar login

    sys.exit(0)


if __name__ == "__main__":
    main()
