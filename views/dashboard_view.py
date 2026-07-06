# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""Vista de inicio — diseño fiel a inicio.png.

Grid de tarjetas de proyecto con:
  - Borde izquierdo de color
  - Badge de estado
  - Nombre, total, cliente, ubicación, fecha, n° partidas
  - Botones Abrir / Editar / Eliminar
"""
import sqlite3
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QFrame, QScrollArea, QGridLayout, QSizePolicy,
    QComboBox, QMessageBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QStackedWidget, QStyledItemDelegate, QStyle,
    QLayout, QLayoutItem, QDialog, QCheckBox
)
from PySide6.QtCore import Qt, Signal, QSize, QRect, QTimer, QPoint
from PySide6.QtGui import (QFont, QColor, QCursor, QPainter, QPainterPath,
                           QBrush, QFontMetrics, QPen)

from core.config import DB_PATH, ESTADOS_PROYECTO
from core.database import get_db, calcular_totales
from models.usuario import Usuario
from utils.formatting import fmt
from utils.session import get_ultimo_proyecto, set_ultimo_proyecto

# ── Label con elipsis en múltiples líneas ────────────────────────────────────

class _NameLabel(QWidget):
    """Muestra texto en exactamente N líneas con '…' al final si no cabe."""

    def __init__(self, texto: str, max_lines: int = 3,
                 font_size: int = 13, color: str = "#273445", parent=None):
        super().__init__(parent)
        self._texto     = texto
        self._max_lines = max_lines
        self._color     = QColor(color)
        self._font      = QFont("Ubuntu Sans", font_size)
        self._font.setWeight(QFont.Normal)

        fm = QFontMetrics(self._font)
        line_h = fm.lineSpacing()
        self.setFixedHeight(line_h * max_lines + 4)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setAttribute(Qt.WA_TranslucentBackground)
        # Tooltip personalizado solo si el texto excede las líneas disponibles
        if len(texto) > 60:
            from utils.tooltip import set_tooltip
            set_tooltip(self, texto)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setFont(self._font)
        painter.setPen(self._color)

        fm = QFontMetrics(self._font)
        line_h   = fm.lineSpacing()
        w        = self.width()
        words    = self._texto.split()
        lines: list[str] = []
        current  = ""

        for word in words:
            test = (current + " " + word).strip()
            if fm.horizontalAdvance(test) <= w:
                current = test
            else:
                if current:
                    lines.append(current)
                current = word
            if len(lines) >= self._max_lines:
                break
        if current and len(lines) < self._max_lines:
            lines.append(current)

        # Si hay más texto del que cabe, agregar "…" a la última línea
        texto_usado = " ".join(lines)
        if len(texto_usado.strip()) < len(self._texto.strip()):
            last = lines[-1] if lines else ""
            while last and fm.horizontalAdvance(last + "…") > w:
                last = last[:-1].rstrip()
            if lines:
                lines[-1] = last + "…"

        # Renderiza líneas justificadas: distribuye el espacio sobrante entre
        # las palabras de cada línea, excepto la última (queda alineada a la
        # izquierda como es convencional en texto justificado).
        space_w_base = fm.horizontalAdvance(' ') or 4
        for i, line in enumerate(lines):
            is_last = (i == len(lines) - 1)
            words_line = line.split()
            if len(words_line) > 1 and not is_last:
                text_w = sum(fm.horizontalAdvance(word) for word in words_line)
                gaps = len(words_line) - 1
                extra = max(0, w - text_w - gaps * space_w_base)
                step_w = space_w_base + (extra / gaps if gaps else 0)
                x = 0.0
                y = i * line_h
                for word in words_line:
                    ww = fm.horizontalAdvance(word)
                    painter.drawText(
                        QRect(int(x), y, ww + 4, line_h + 2),
                        Qt.AlignLeft | Qt.AlignVCenter, word
                    )
                    x += ww + step_w
            else:
                painter.drawText(
                    QRect(0, i * line_h, w, line_h + 2),
                    Qt.AlignLeft | Qt.AlignVCenter, line
                )
        painter.end()


# ── Paleta — aliases de tokens centralizados (utils/theme.py) ────────────────
# Los nombres "BLUE_500" / "NARANJA" son alias históricos del naranja marca.
from utils.theme import C

BLUE_500   = C.brand
BLUE_700   = C.brand_hover
SLATE_700  = C.text
SLATE_500  = C.text_secondary
SLATE_300  = C.text_muted
SLATE_100  = C.text_faint
SILVER_100 = C.bg
SILVER_300 = C.border
RED_500    = C.error
GREEN_500  = "#68B723"
ORANGE_500 = C.brand
BANANA_500 = C.warning

# Alias retro-compatibles
NARANJA = BLUE_500
BG      = SILVER_100

CARD_BG   = C.surface
CARD_W    = 300
CARD_W_MIN = 280   # ancho mínimo de card; el real se estira al ancho disponible
GRID_GAP  = 14
GRID_MARG = 20

# Estados: bg = shade 100 oficial elementary OS, fg = slate oscuro (Slate 700).
# Solo el color de fondo distingue el estado; el texto es uniforme.
# Referencia: https://elementary.io/brand
ESTADO_COLOR = {
    "elaboracion": ("#FFC27D", "#273445", "En elaboración"),  # Orange 100
    "revision":    ("#8CD5FF", "#273445", "En revisión"),     # BlueBerry 100
    "aprobado":    ("#9BDB4D", "#273445", "Aprobado"),        # Lime 300
    "ejecutado":   ("#FF8C82", "#273445", "En ejecución"),    # Strawberry 100
}
# Colores de borde izquierdo: paleta Elementary
CARD_BORDER_COLORS = [
    "#F37329",   # Blueberry
    "#F37329",   # Orange
    "#68B723",   # Lime
    "#7A36B1",   # Grape
    "#F9C440",   # Banana
    "#C6262E",   # Strawberry
    "#C0621A",   # Blueberry dark
    "#CC3B02",   # Orange dark
]


# ── Menú contextual compartido ───────────────────────────────────────────────

def _confirmar(parent, titulo: str, mensaje: str,
               btn_ok: str = "Eliminar", btn_cancel: str = "Cancelar") -> bool:
    """Cuadro de confirmación con botones en español."""
    from PySide6.QtWidgets import QMessageBox
    msg = QMessageBox(parent)
    msg.setWindowTitle(titulo)
    msg.setText(mensaje)
    msg.setIcon(QMessageBox.Icon.Warning)
    b_ok  = msg.addButton(btn_ok,     QMessageBox.ButtonRole.AcceptRole)
    msg.addButton(btn_cancel, QMessageBox.ButtonRole.RejectRole)
    msg.setDefaultButton(b_ok)
    msg.exec()
    return msg.clickedButton() == b_ok


class _CopiarProyectoDialog(QDialog):
    """Diálogo «Copiar proyecto»: el presupuesto siempre se copia; el usuario
    elige qué más incluir (metrados, especificaciones, cronograma, fórmula,
    pie). Devuelve el set de opciones marcadas en `opciones()`."""

    def __init__(self, nombre: str, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QCheckBox,
                                        QHBoxLayout, QPushButton, QFrame)
        from utils.theme import BTN_PRIMARY_SS
        self.setWindowTitle("Copiar proyecto")
        self.setWindowModality(Qt.WindowModal)
        self.setMinimumWidth(420)
        vl = QVBoxLayout(self)
        vl.setContentsMargins(20, 18, 20, 16)
        vl.setSpacing(10)

        titulo = QLabel(f"Copiar «{nombre}»")
        titulo.setStyleSheet("font-size:13px; font-weight:700; background:transparent; border:none;")
        titulo.setWordWrap(True)
        vl.addWidget(titulo)

        sub = QLabel("Se creará una copia. Elige qué incluir:")
        sub.setStyleSheet("font-size:11px; color:#5A6775; background:transparent; border:none;")
        vl.addWidget(sub)

        # Presupuesto: siempre (casilla marcada y deshabilitada).
        chk_pres = QCheckBox("Presupuesto (partidas, ACU y subpresupuestos)")
        chk_pres.setChecked(True)
        chk_pres.setEnabled(False)
        chk_pres.setStyleSheet("font-size:12px;")
        vl.addWidget(chk_pres)

        self._checks = {}
        for clave, etiqueta in (
            ('metrados',   "Metrados (planilla y acero)"),
            ('specs',      "Especificaciones técnicas (texto e imágenes)"),
            ('cronograma', "Cronograma (duraciones y dependencias)"),
            ('formula',    "Fórmula polinómica"),
            ('pie',        "Pie de presupuesto (gastos generales)"),
        ):
            chk = QCheckBox(etiqueta)
            chk.setChecked(True)   # por defecto copia todo; el usuario destilda
            chk.setStyleSheet("font-size:12px;")
            vl.addWidget(chk)
            self._checks[clave] = chk

        vl.addSpacing(6)
        botones = QHBoxLayout()
        botones.addStretch()
        b_cancel = QPushButton("Cancelar")
        b_cancel.setCursor(Qt.PointingHandCursor)
        b_cancel.clicked.connect(self.reject)
        botones.addWidget(b_cancel)
        b_ok = QPushButton("Copiar")
        b_ok.setCursor(Qt.PointingHandCursor)
        b_ok.setStyleSheet(BTN_PRIMARY_SS)
        b_ok.setDefault(True)
        b_ok.clicked.connect(self.accept)
        botones.addWidget(b_ok)
        vl.addLayout(botones)

    def opciones(self) -> set:
        return {k for k, chk in self._checks.items() if chk.isChecked()}


def _clonar_proyecto(conn, pid: int, opts: set) -> int:
    """Copia profunda de un proyecto dentro de la BD activa. El presupuesto
    (proyecto + subpresupuestos + partidas + ACU) se copia siempre; el resto
    según `opts` ('metrados','specs','cronograma','formula','pie'). Los recursos
    NO se duplican: al ser el mismo catálogo, los ACU referencian el mismo
    recurso_id. Devuelve el id del nuevo proyecto."""
    import sqlite3

    def cols_of(t):
        return [r[1] for r in conn.execute(f"PRAGMA table_info({t})")]

    # ── 1. PROYECTO (todas las columnas; nombre «(copia)», estado elaboración,
    #        timestamps frescos por defecto) ───────────────────────────────
    pcols = [c for c in cols_of('proyectos')
             if c not in ('id', 'creado_en', 'modificado_en')]
    prow = dict(conn.execute("SELECT * FROM proyectos WHERE id=?", (pid,)).fetchone())
    pvals = []
    for c in pcols:
        if c == 'nombre':
            pvals.append(f"{prow['nombre']} (copia)")
        elif c == 'estado':
            pvals.append('elaboracion')
        else:
            pvals.append(prow.get(c))
    cur = conn.execute(
        f"INSERT INTO proyectos ({','.join(pcols)}) "
        f"VALUES ({','.join('?' * len(pcols))})", pvals)
    new_pid = cur.lastrowid
    conn.execute("UPDATE proyectos SET modificado_en=CURRENT_TIMESTAMP WHERE id=?",
                 (new_pid,))

    # ── 2. SUB-PRESUPUESTOS (map id_orig → id_dst) ────────────────────────
    map_sub = {}
    scols = [c for c in cols_of('sub_presupuestos') if c not in ('id', 'proyecto_id')]
    for r in conn.execute("SELECT * FROM sub_presupuestos WHERE proyecto_id=?",
                          (pid,)).fetchall():
        d = dict(r)
        cur = conn.execute(
            f"INSERT INTO sub_presupuestos ({','.join(scols)},proyecto_id) "
            f"VALUES ({','.join('?' * len(scols))},?)",
            [d[c] for c in scols] + [new_pid])
        map_sub[d['id']] = cur.lastrowid

    # ── 3. PARTIDAS (map id_orig → id_dst; remapea subppto; specs opcional) ─
    map_part = {}
    pcols2 = [c for c in cols_of('partidas')
              if c not in ('id', 'proyecto_id', 'sub_presupuesto_id')]
    for r in conn.execute("SELECT * FROM partidas WHERE proyecto_id=? ORDER BY id",
                          (pid,)).fetchall():
        d = dict(r)
        if 'specs' not in opts:
            d['especificaciones'] = ''
        cur = conn.execute(
            f"INSERT INTO partidas ({','.join(pcols2)},proyecto_id,sub_presupuesto_id) "
            f"VALUES ({','.join('?' * len(pcols2))},?,?)",
            [d[c] for c in pcols2] + [new_pid, map_sub.get(d.get('sub_presupuesto_id'))])
        map_part[d['id']] = cur.lastrowid

    # ── 4. ACU_ITEMS (siempre; mismo recurso_id) ──────────────────────────
    def copy_part_dep(tabla):
        cs = [c for c in cols_of(tabla) if c not in ('id', 'partida_id')]
        ph = ','.join('?' * len(cs))
        for old_part, new_part in map_part.items():
            for r in conn.execute(f"SELECT * FROM {tabla} WHERE partida_id=?",
                                  (old_part,)).fetchall():
                d = dict(r)
                try:
                    conn.execute(
                        f"INSERT INTO {tabla} ({','.join(cs)},partida_id) "
                        f"VALUES ({ph},?)", [d[c] for c in cs] + [new_part])
                except sqlite3.IntegrityError:
                    pass   # p.ej. cronograma_partidas UNIQUE(partida_id)

    def copy_proj_dep(tabla):
        cs = [c for c in cols_of(tabla) if c not in ('id', 'proyecto_id')]
        ph = ','.join('?' * len(cs))
        for r in conn.execute(f"SELECT * FROM {tabla} WHERE proyecto_id=?",
                              (pid,)).fetchall():
            d = dict(r)
            try:
                conn.execute(
                    f"INSERT INTO {tabla} ({','.join(cs)},proyecto_id) "
                    f"VALUES ({ph},?)", [d[c] for c in cs] + [new_pid])
            except sqlite3.IntegrityError:
                pass

    copy_part_dep('acu_items')

    # ── 5. TABLAS OPCIONALES ──────────────────────────────────────────────
    if 'metrados' in opts:
        copy_part_dep('metrados_detalle')
        copy_part_dep('acero_detalle')
    if 'specs' in opts:
        copy_part_dep('spec_imagenes')
    if 'cronograma' in opts:
        copy_part_dep('cronograma_partidas')
    if 'pie' in opts:
        copy_proj_dep('pie_rubros')
        copy_proj_dep('gastos_generales')
    if 'formula' in opts:
        copy_proj_dep('formula_monomios')
        copy_proj_dep('formula_periodos')

    return new_pid


# QMenu styling — cubierto por `install_global_popup_styles(app)`. No se
# necesita setStyleSheet local en cada menú.


def _mostrar_menu_proyecto(pid: int, pos, parent,
                           usuario, card_signals=None):
    """Muestra el menú contextual de proyecto y ejecuta la acción elegida.

    card_signals: objeto con señales abrir/editar/eliminar/copiar/
                  favorito_toggled/estado_cambiado (puede ser _ProjectCard o None).
    Si es None, realiza las operaciones directamente y emite mediante el parent.
    """
    from PySide6.QtWidgets import QMenu, QFileDialog, QMessageBox
    from PySide6.QtGui import QIcon
    from utils.icons import icon as load_icon, icon_colored
    from utils.i18n import tr

    # Leer estado actual del proyecto
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT nombre, favorito, estado, moneda FROM proyectos WHERE id=?",
                       (pid,)).fetchone()
    conn.close()
    if not row:
        return

    nombre  = row['nombre'] or f"Proyecto {pid}"
    es_fav  = bool(row['favorito'])
    estado  = row['estado'] or 'elaboracion'
    moneda  = row['moneda'] or 'Soles'

    menu = QMenu(parent)

    def _act(texto, icon_name=None, color=None, disabled=False):
        a = menu.addAction(texto)
        ic = icon_colored(icon_name, color) if color else load_icon(icon_name or "")
        if icon_name and not ic.isNull():
            a.setIcon(ic)
        a.setEnabled(not disabled)
        return a

    # ── Abrir ──────────────────────────────────────────────────────────────
    act_abrir = _act(tr("Abrir"), "abrir")
    menu.addSeparator()

    # ── Favorito ───────────────────────────────────────────────────────────
    lbl_fav = tr("Quitar de favoritos") if es_fav else tr("Marcar como favorito")
    act_fav = _act(lbl_fav, "favorito_on" if es_fav else "favorito_off")
    menu.addSeparator()

    # ── Estado (submenu) ───────────────────────────────────────────────────
    sub_estado = menu.addMenu("  " + tr("Cambiar estado"))
    estados_items = {
        "elaboracion": ("🔧  En elaboración", "elaboracion"),
        "revision":    ("🔍  En revisión",    "revision"),
        "aprobado":    ("✅  Aprobado",        "aprobado"),
        "ejecutado":   ("🏗  En ejecución",    "ejecutado"),
    }
    act_estados = {}
    for key, (lbl, _) in estados_items.items():
        a = sub_estado.addAction(lbl + ("  ✓" if key == estado else ""))
        a.setEnabled(key != estado)
        act_estados[a] = key
    menu.addSeparator()

    # ── Edición ────────────────────────────────────────────────────────────
    invitado = usuario and usuario.es_invitado
    act_edit  = _act(tr("Editar"),   "editar",   disabled=invitado)
    act_copy  = _act(tr("Copiar"),   "copiar",   disabled=invitado)
    menu.addSeparator()

    # ── Portafolio (submenu) ───────────────────────────────────────────────
    from core.database import listar_portafolios as _listar
    sub_pf = menu.addMenu("  " + tr("Mover a portafolio"))
    portafolios_disp = _listar()
    # Leer portafolio actual del proyecto
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    pid_row = conn.execute(
        "SELECT portafolio_id FROM proyectos WHERE id=?", (pid,)
    ).fetchone()
    conn.close()
    portafolio_actual = pid_row['portafolio_id'] if pid_row else None
    act_pf: dict = {}
    a_sin = sub_pf.addAction(
        tr("Sin clasificar") + ("  ✓" if portafolio_actual is None else "")
    )
    a_sin.setEnabled(portafolio_actual is not None and not invitado)
    act_pf[a_sin] = None
    if portafolios_disp:
        sub_pf.addSeparator()
        for pf in portafolios_disp:
            lbl = pf['nombre']
            if pf['id'] == portafolio_actual:
                lbl += "  ✓"
            a = sub_pf.addAction(lbl)
            a.setEnabled(pf['id'] != portafolio_actual and not invitado)
            act_pf[a] = pf['id']
    menu.addSeparator()

    # ── Exportar (submenu) ─────────────────────────────────────────────────
    sub_exp = menu.addMenu("  " + tr("Exportar"))
    exp_opts = [
        ("Excel — Presupuesto",      "presupuesto"),
        ("Excel — ACUs",             "acus"),
        ("Excel — Insumos",          "insumos"),
        ("Excel — Reporte completo", "completo"),
        ("PDF",                      "pdf"),
        ("Base de datos (.db)",      "db"),
    ]
    act_exp = {sub_exp.addAction(lbl): tipo for lbl, tipo in exp_opts}
    menu.addSeparator()

    # ── Eliminar ───────────────────────────────────────────────────────────
    act_del = _act(tr("Eliminar"), "eliminar",
                   color=RED_500, disabled=invitado)

    # ── Ejecutar ───────────────────────────────────────────────────────────
    chosen = menu.exec(pos)
    if not chosen:
        return

    # Abrir
    if chosen == act_abrir:
        if card_signals:
            card_signals.abrir.emit(pid)
        return

    # Favorito
    if chosen == act_fav:
        nuevo_fav = 0 if es_fav else 1
        conn = sqlite3.connect(DB_PATH)
        conn.execute("UPDATE proyectos SET favorito=? WHERE id=?", (nuevo_fav, pid))
        conn.commit()
        conn.close()
        if card_signals:
            if hasattr(card_signals, '_es_fav'):
                card_signals._es_fav = bool(nuevo_fav)
                card_signals._refrescar_fav()
            card_signals.favorito_toggled.emit(pid)
        return

    # Estado
    if chosen in act_estados:
        nuevo_estado = act_estados[chosen]
        conn = sqlite3.connect(DB_PATH)
        conn.execute("UPDATE proyectos SET estado=? WHERE id=?", (nuevo_estado, pid))
        conn.commit()
        conn.close()
        if card_signals:
            card_signals.estado_cambiado.emit(pid, nuevo_estado)
        return

    # Editar
    if chosen == act_edit:
        if card_signals:
            card_signals.editar.emit(pid)
        return

    # Copiar
    if chosen == act_copy:
        if card_signals:
            card_signals.copiar.emit(pid)
        return

    # Mover a portafolio
    if chosen in act_pf:
        from core.database import mover_proyecto_portafolio as _mover
        _mover(pid, act_pf[chosen])
        # Buscar DashboardView en la cadena de padres
        dash = parent
        while dash and not hasattr(dash, '_recargar_portafolios_bar'):
            dash = dash.parent()
        if dash:
            dash._recargar_portafolios_bar()
            dash.cargar_proyectos()
        return

    # Exportar
    if chosen in act_exp:
        _exportar_proyecto(pid, nombre, moneda, act_exp[chosen], parent)
        return

    # Eliminar
    if chosen == act_del:
        if not _confirmar(
            parent, "Eliminar proyecto",
            f"¿Eliminar «{nombre}»?\n"
            "Se eliminarán todas sus partidas y datos.\n"
            "Esta acción no se puede deshacer."
        ):
            return
        conn = sqlite3.connect(DB_PATH)
        conn.execute("DELETE FROM proyectos WHERE id=?", (pid,))
        conn.commit()
        conn.close()
        if card_signals:
            card_signals.eliminar.emit(pid)


def _exportar_proyecto(pid: int, nombre: str, moneda: str, tipo: str, parent):
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    ext   = {"pdf": "pdf", "db": "db"}.get(tipo, "xlsx")
    filtro = {"pdf": "PDF (*.pdf)",
              "db":  "Base de datos ingePresupuestos (*.db)"}.get(tipo, "Excel (*.xlsx)")
    path, _ = QFileDialog.getSaveFileName(
        parent, "Exportar proyecto", f"{nombre}_{tipo}.{ext}", filtro
    )
    if not path:
        return
    try:
        if tipo == "db":
            # El export .db escribe directo al archivo (no a un buffer).
            from core.exporter import exportar_proyecto_db
            exportar_proyecto_db(pid, path)
        else:
            from core.exporter import (
                exportar_presupuesto, exportar_acus, exportar_insumos,
                exportar_reporte_completo, exportar_pdf
            )
            funcs = {
                "presupuesto": exportar_presupuesto,
                "acus":        exportar_acus,
                "insumos":     exportar_insumos,
                "completo":    exportar_reporte_completo,
                "pdf":         exportar_pdf,
            }
            buf = funcs[tipo](pid)
            with open(path, "wb") as f:
                f.write(buf.getvalue())
        QMessageBox.information(parent, "Exportar", f"Guardado en:\n{path}")
    except Exception as e:
        QMessageBox.critical(parent, "Error al exportar", str(e))


# ── Tarjeta individual ────────────────────────────────────────────────────────

class _ProjectCard(QWidget):
    """Card de proyecto pintada a mano con QPainter: UN solo widget.

    La versión anterior (~15 widgets por card) tardaba ~2.3 s en construir
    400 cards porque cada widget se re-estila contra el QSS global. Pintada
    a mano baja a milisegundos. Mantiene la misma API: signals, set_total /
    set_ultimo / setSelected, menú de estados, favorito, doble clic y menú
    contextual. Las zonas clickeables se resuelven por hit-testing de rects
    calculados en paintEvent.
    """

    abrir            = Signal(int)
    editar           = Signal(int)
    eliminar         = Signal(int)
    copiar           = Signal(int)
    favorito_toggled = Signal(int)
    seleccionado     = Signal(int)
    estado_cambiado  = Signal(int, str)   # (pid, nuevo_estado)

    _MARGEN   = 14
    _NOM_LINEAS = 4
    _BTN      = 26          # lado de cada botón de acción
    _ICON_PX  = 14

    def __init__(self, row: dict, color: str, usuario: Usuario,
                 es_ultimo: bool = False, con_sombra: bool = True,
                 total_str: str = '…', n_part: int = 0,
                 parent=None):
        super().__init__(parent)
        self.pid        = row['id']
        self.usuario    = usuario
        self._es_fav    = bool(row.get('favorito'))
        self._es_ultimo = es_ultimo
        self._selected  = False
        self._total_str = total_str

        self._nombre    = row.get('nombre') or 'Sin nombre'
        self._estado_actual = row.get('estado') or 'elaboracion'
        self._portafolio = row.get('portafolio_nombre') or ''
        self._portafolio_color = row.get('portafolio_color') or SLATE_500
        cliente   = row.get('cliente') or ''
        ubicacion = row.get('ubicacion') or ''
        self._meta1 = '  ·  '.join(filter(None, [cliente, ubicacion]))
        fecha = (row.get('modificado_en') or row.get('creado_en') or '')[:10]
        m2 = [fecha] if fecha else []
        m2.append(f"{n_part} partida{'s' if n_part != 1 else ''}")
        self._meta2 = '  ·  '.join(m2)

        fam = self.font().family()
        self._f_chip  = QFont(fam, 8);  self._f_chip.setWeight(QFont.Bold)
        self._f_nom   = QFont(fam, 10)
        self._f_total = QFont(fam, 10); self._f_total.setWeight(QFont.DemiBold)
        self._f_meta  = QFont(fam, 8)
        self._f_star  = QFont(fam, 13)

        self._hover      = False
        self._hover_zone = None
        self._zonas: dict[str, QRect] = {}

        # Ancho FLUIDO: mínimo CARD_W_MIN y se estira para repartir el
        # ancho de la ventana entre las columnas (sin scrollbar horizontal).
        # paintEvent dibuja todo relativo a self.width(), así que el
        # contenido se adapta solo.
        self.setMinimumWidth(CARD_W_MIN)
        self.setFixedHeight(self._alto_card())
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMouseTracking(True)
        if con_sombra:
            from utils.theme import apply_shadow
            apply_shadow(self, 'sm')

    # ── API pública (idéntica a la versión por widgets) ──────────────────

    def set_total(self, total_str: str):
        self._total_str = total_str
        self.update()

    def set_ultimo(self, es_ultimo: bool):
        if es_ultimo != self._es_ultimo:
            self._es_ultimo = es_ultimo
            self.update()

    def setSelected(self, selected: bool):
        if selected != self._selected:
            self._selected = selected
            self.update()

    # ── Geometría ─────────────────────────────────────────────────────────

    def _alto_card(self) -> int:
        lh_nom  = QFontMetrics(self._f_nom).lineSpacing()
        lh_tot  = QFontMetrics(self._f_total).lineSpacing()
        lh_meta = QFontMetrics(self._f_meta).lineSpacing()
        return (4 + 10 + 20 + 8 + lh_nom * self._NOM_LINEAS + 5
                + lh_tot + 3 + lh_meta * 2 + 6 + self._BTN + 12)

    # ── Pintura ───────────────────────────────────────────────────────────

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        M = self._MARGEN
        self._zonas = {}

        # Fondo + borde (selección > hover > normal)
        if self._selected:
            bg, borde, bw = QColor('#FEF5EB'), QColor('#F37329'), 1.5
        else:
            bg = QColor('#FFF9C4' if self._es_ultimo else CARD_BG)
            borde = QColor('#B8C8E0' if self._hover else '#E0E2E6')
            bw = 1.0
        path = QPainterPath()
        path.addRoundedRect(bw / 2, bw / 2, w - bw, h - bw, 8, 8)
        p.fillPath(path, bg)

        # Barra superior con el color del estado (clip al path redondeado)
        bg_e, fg_e, lbl_e = ESTADO_COLOR.get(
            self._estado_actual, ('#F0F1F2', SLATE_300, self._estado_actual))
        p.save()
        p.setClipPath(path)
        p.fillRect(QRect(0, 0, w, 4), QColor(bg_e))
        p.restore()

        p.setPen(QPen(borde, bw))
        p.drawPath(path)

        y = 4 + 10

        # ── Chips: badge estado (clickeable) + portafolio + Reciente ──────
        fm_chip = QFontMetrics(self._f_chip)
        p.setFont(self._f_chip)
        x = M

        txt_badge = f"{lbl_e}  ▾"
        bw_badge = fm_chip.horizontalAdvance(txt_badge) + 18
        r_badge = QRect(x, y, bw_badge, 20)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(bg_e))
        p.drawRoundedRect(r_badge, 8, 8)
        if self._hover_zone == 'badge':
            p.setPen(QPen(QColor(fg_e), 1))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r_badge, 8, 8)
        p.setPen(QColor(fg_e))
        p.drawText(r_badge, Qt.AlignCenter, txt_badge)
        self._zonas['badge'] = r_badge
        x = r_badge.right() + 6

        if self._portafolio:
            cp = QColor(self._portafolio_color)
            cp_bg = QColor(cp); cp_bg.setAlphaF(0.15)
            txt_pf = fm_chip.elidedText(self._portafolio, Qt.ElideRight,
                                        w - x - M - 26 - 60)
            r_pf = QRect(x, y, fm_chip.horizontalAdvance(txt_pf) + 18, 20)
            p.setPen(Qt.NoPen); p.setBrush(cp_bg)
            p.drawRoundedRect(r_pf, 8, 8)
            p.setPen(cp)
            p.drawText(r_pf, Qt.AlignCenter, txt_pf)
            x = r_pf.right() + 6

        if self._es_ultimo:
            r_rec = QRect(x, y + 1, fm_chip.horizontalAdvance('Reciente') + 14, 17)
            p.setPen(Qt.NoPen); p.setBrush(QColor('#FFF9C4'))
            p.drawRoundedRect(r_rec, 8, 8)
            p.setPen(QColor('#854D0E'))
            p.drawText(r_rec, Qt.AlignCenter, 'Reciente')

        # Estrella favorito (derecha)
        r_fav = QRect(w - M - 20, y, 20, 20)
        p.setFont(self._f_star)
        p.setPen(QColor(BANANA_500) if self._es_fav else QColor(SILVER_300))
        p.drawText(r_fav, Qt.AlignCenter, '★' if self._es_fav else '☆')
        self._zonas['fav'] = r_fav

        y += 20 + 8

        # ── Nombre: hasta 4 líneas con elipsis ────────────────────────────
        p.setFont(self._f_nom)
        p.setPen(QColor(SLATE_700))
        fm_n = QFontMetrics(self._f_nom)
        lh = fm_n.lineSpacing()
        ancho_txt = w - 2 * M
        lines, current = [], ''
        for word in self._nombre.split():
            test = (current + ' ' + word).strip()
            if fm_n.horizontalAdvance(test) <= ancho_txt:
                current = test
            else:
                if current:
                    lines.append(current)
                current = word
            if len(lines) >= self._NOM_LINEAS:
                break
        if current and len(lines) < self._NOM_LINEAS:
            lines.append(current)
        if len(' '.join(lines).strip()) < len(self._nombre.strip()) and lines:
            last = lines[-1]
            while last and fm_n.horizontalAdvance(last + '…') > ancho_txt:
                last = last[:-1].rstrip()
            lines[-1] = last + '…'
        for i, line in enumerate(lines):
            p.drawText(M, y + i * lh + fm_n.ascent(), line)
        y += lh * self._NOM_LINEAS + 5

        # ── Total ─────────────────────────────────────────────────────────
        p.setFont(self._f_total)
        p.setPen(QColor(SLATE_500))
        fm_t = QFontMetrics(self._f_total)
        p.drawText(M, y + fm_t.ascent(), self._total_str)
        y += fm_t.lineSpacing() + 3

        # ── Metas ─────────────────────────────────────────────────────────
        p.setFont(self._f_meta)
        p.setPen(QColor(SLATE_100))
        fm_m = QFontMetrics(self._f_meta)
        p.drawText(M, y + fm_m.ascent(),
                   fm_m.elidedText(self._meta1, Qt.ElideRight, ancho_txt))
        y += fm_m.lineSpacing()
        p.drawText(M, y + fm_m.ascent(),
                   fm_m.elidedText(self._meta2, Qt.ElideRight, ancho_txt))
        y += fm_m.lineSpacing() + 6

        # ── Botones de acción (derecha → izquierda) ───────────────────────
        es_invitado = bool(self.usuario and self.usuario.es_invitado)
        botones = [('abrir', 'abrir')]
        if not es_invitado:
            botones = [('abrir', 'abrir'), ('copiar', 'copiar'),
                       ('editar', 'editar'), ('eliminar', 'eliminar')]
        bx = w - M - self._BTN
        for zona, icono in reversed(botones):
            r_btn = QRect(bx, y, self._BTN, self._BTN)
            if self._hover_zone == zona:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor('#FFF0F0' if zona == 'eliminar' else SILVER_100))
                p.drawRoundedRect(r_btn, 6, 6)
            ic = (_icon_colored_cached(icono, RED_500) if zona == 'eliminar'
                  else _icon_cached(icono))
            if not ic.isNull():
                lado = self._ICON_PX
                r_ic = QRect(r_btn.center().x() - lado // 2 + 1,
                             r_btn.center().y() - lado // 2 + 1, lado, lado)
                ic.paint(p, r_ic, Qt.AlignCenter)
            self._zonas[zona] = r_btn
            bx -= self._BTN + 2

    # ── Interacción ───────────────────────────────────────────────────────

    def _zona_at(self, pos) -> str | None:
        for z, r in self._zonas.items():
            if r.contains(pos):
                return z
        return None

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self._hover_zone = None
        self.update()
        super().leaveEvent(event)

    _TOOLTIPS = {'abrir': 'Abrir', 'copiar': 'Copiar', 'editar': 'Editar',
                 'eliminar': 'Eliminar', 'fav': 'Favorito',
                 'badge': 'Cambiar estado'}

    def mouseMoveEvent(self, event):
        z = self._zona_at(event.position().toPoint())
        if z != self._hover_zone:
            self._hover_zone = z
            self.setCursor(QCursor(Qt.PointingHandCursor) if z
                           else QCursor(Qt.ArrowCursor))
            # Tooltip por zona: actualizamos toolTip() y el filtro global de
            # tooltips (utils/tooltip._GlobalTooltipFilter) lo renderiza con
            # el estilo blanco al posarse el cursor. NO usar QToolTip.showText
            # ni un tooltip base: el filtro global lee toolTip() del widget.
            txt = self._TOOLTIPS.get(z, '')
            if not txt and len(self._nombre) > 60:
                txt = self._nombre
            self.setToolTip(txt)
            self.update()
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        z = self._zona_at(event.position().toPoint())
        if z == 'badge':
            self._cambiar_estado()
        elif z == 'fav':
            self._toggle_favorito()
        elif z == 'abrir':
            self.abrir.emit(self.pid)
        elif z == 'copiar':
            self.copiar.emit(self.pid)
        elif z == 'editar':
            self.editar.emit(self.pid)
        elif z == 'eliminar':
            self.eliminar.emit(self.pid)
        else:
            self.seleccionado.emit(self.pid)

    def mouseDoubleClickEvent(self, event):
        if self._zona_at(event.position().toPoint()) is None:
            self.abrir.emit(self.pid)

    def contextMenuEvent(self, event):
        _mostrar_menu_proyecto(
            self.pid, event.globalPos(), self,
            self.usuario, card_signals=self
        )

    # ── Estado ────────────────────────────────────────────────────────────

    def _cambiar_estado(self):
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        estados = [
            ("elaboracion", "🔧  En elaboración"),
            ("revision",    "🔍  En revisión"),
            ("aprobado",    "✅  Aprobado"),
            ("ejecutado",   "🏗  En ejecución"),
        ]
        for estado_key, label in estados:
            act = menu.addAction(label + ("  ✓" if estado_key == self._estado_actual else ""))
            act.setData(estado_key)
        r = self._zonas.get('badge', QRect(0, 0, 0, 24))
        accion = menu.exec(self.mapToGlobal(r.bottomLeft() + QPoint(0, 2)))
        if not accion:
            return
        nuevo = accion.data()
        if nuevo == self._estado_actual:
            return
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.execute("UPDATE proyectos SET estado=? WHERE id=?", (nuevo, self.pid))
            conn.commit()
            conn.close()
        except Exception:
            return
        self._estado_actual = nuevo
        self.update()
        self.estado_cambiado.emit(self.pid, nuevo)

    # ── Favorito ──────────────────────────────────────────────────────────

    def _toggle_favorito(self):
        self._es_fav = not self._es_fav
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.execute(
                "UPDATE proyectos SET favorito=? WHERE id=?",
                (1 if self._es_fav else 0, self.pid)
            )
            conn.commit()
            conn.close()
        except Exception:
            self._es_fav = not self._es_fav   # revertir si falló
            return
        self.update()
        self.favorito_toggled.emit(self.pid)


def _icon_cached(nombre: str):
    from utils.icons import icon as load_icon
    return load_icon(nombre)


def _icon_colored_cached(nombre: str, color: str):
    from utils.icons import icon_colored
    return icon_colored(nombre, color)


# ── Controles de barra mejorados ─────────────────────────────────────────────

class _PillDropdown(QPushButton):
    """Botón pill que abre un QMenu. Reemplaza QComboBox con estilo moderno."""
    option_changed = Signal()

    def __init__(self, placeholder: str, options: list, parent=None):
        super().__init__(parent)
        self._placeholder = placeholder
        self._options     = options   # [(label, data), ...]
        self._data        = None
        self._idx         = 0
        self._refresh()
        self.clicked.connect(self._show_menu)

    def _refresh(self):
        if self._data:
            label = next((l for l, d in self._options if d == self._data), self._placeholder)
            self.setText(f"  {label}  ✕  ")
            self.setStyleSheet(
                f"QPushButton {{ border:1.5px solid {BLUE_500}; color:{BLUE_700};"
                f" border-radius:14px; font-size:11px; font-weight:600;"
                f" background:#FEF5EB; padding:0 4px; }}"
                f"QPushButton:hover {{ background:#D6EDFF; }}"
            )
        else:
            self.setText(f"  {self._placeholder}  ▾  ")
            self.setStyleSheet(
                f"QPushButton {{ border:1px solid {SILVER_300}; color:{SLATE_300};"
                f" border-radius:14px; font-size:11px; background:white; padding:0 4px; }}"
                f"QPushButton:hover {{ border-color:{BLUE_500}; color:{SLATE_700}; }}"
            )

    def _show_menu(self):
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        # Opción "todos"
        act_all = menu.addAction(f"Todos ({self._placeholder})")
        act_all.setCheckable(True)
        act_all.setChecked(self._data is None)
        act_all.triggered.connect(lambda: self._select(None, 0))
        menu.addSeparator()
        for i, (label, data) in enumerate(self._options, start=1):
            act = menu.addAction(label)
            act.setCheckable(True)
            act.setChecked(self._data == data)
            act.triggered.connect(lambda _, d=data, idx=i: self._select(d, idx))
        menu.exec(self.mapToGlobal(self.rect().bottomLeft()))

    def _select(self, data, idx: int):
        self._data = data
        self._idx  = idx
        self._refresh()
        self.option_changed.emit()

    def currentData(self):
        return self._data or ""

    def currentIndex(self):
        return self._idx


class _PillOrder(QPushButton):
    """Botón pill para ordenar: cicla entre opciones con clic."""
    option_changed = Signal()

    def __init__(self, options: list[str], parent=None):
        super().__init__(parent)
        self._options = options
        self._idx     = 0
        self._refresh()
        self.clicked.connect(self._show_menu)

    def _refresh(self):
        label = self._options[self._idx]
        self.setText(f"  ↕  {label}  ▾  ")
        self.setStyleSheet(
            "QPushButton { border:1px solid #d0d8e8; color:#6b7a8d;"
            " border-radius:14px; font-size:11px; background:white; padding:0 4px; }"
            "QPushButton:hover { border-color:#aab8cc; color:#485a6c; }"
        )

    def _show_menu(self):
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        for i, label in enumerate(self._options):
            act = menu.addAction(label)
            act.setCheckable(True)
            act.setChecked(i == self._idx)
            act.triggered.connect(lambda _, idx=i: self._select(idx))
        menu.exec(self.mapToGlobal(self.rect().bottomLeft()))

    def _select(self, idx: int):
        self._idx = idx
        self._refresh()
        self.option_changed.emit()

    def currentIndex(self) -> int:
        return self._idx


class _SegmentedToggle(QFrame):
    """Control segmentado de dos opciones (Mosaico / Lista)."""
    changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(32)
        self.setStyleSheet("border:none; background:transparent;")
        hl = QHBoxLayout(self)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(0)

        from utils.i18n import tr as _tr
        self._btn_m = QPushButton("⊞  " + _tr("Mosaico"))
        self._btn_l = QPushButton("☰  " + _tr("Lista"))
        for btn in (self._btn_m, self._btn_l):
            btn.setFixedHeight(32)
            btn.setCheckable(True)
        self._btn_m.setStyleSheet(self._style(True,  "left"))
        self._btn_l.setStyleSheet(self._style(False, "right"))
        self._btn_m.setChecked(True)
        self._btn_m.clicked.connect(lambda: self._select("mosaico"))
        self._btn_l.clicked.connect(lambda: self._select("lista"))
        hl.addWidget(self._btn_m)
        hl.addWidget(self._btn_l)

    def _style(self, active: bool, side: str) -> str:
        r_left  = "8px" if side == "left"  else "0"
        r_right = "8px" if side == "right" else "0"
        if active:
            return (
                f"QPushButton {{ background:{BLUE_500}; color:white; font-size:11px;"
                f" font-weight:600; border:none; padding:0 14px;"
                f" border-radius:0; border-top-left-radius:{r_left};"
                f" border-bottom-left-radius:{r_left};"
                f" border-top-right-radius:{r_right};"
                f" border-bottom-right-radius:{r_right}; }}"
            )
        else:
            return (
                f"QPushButton {{ background:white; color:{SLATE_300}; font-size:11px;"
                f" border:1px solid {SILVER_300}; padding:0 14px;"
                f" border-radius:0; border-top-left-radius:{r_left};"
                f" border-bottom-left-radius:{r_left};"
                f" border-top-right-radius:{r_right};"
                f" border-bottom-right-radius:{r_right}; }}"
                f"QPushButton:hover {{ color:{BLUE_700}; border-color:{BLUE_500}; }}"
            )

    def _select(self, modo: str):
        activo_m = modo == "mosaico"
        self._btn_m.setChecked(activo_m)
        self._btn_l.setChecked(not activo_m)
        self._btn_m.setStyleSheet(self._style(activo_m,      "left"))
        self._btn_l.setStyleSheet(self._style(not activo_m,  "right"))
        self.changed.emit(modo)

    def modo(self) -> str:
        return "mosaico" if self._btn_m.isChecked() else "lista"


# ── FlowLayout — wrap horizontal a múltiples filas ────────────────────────────

class _FlowLayout(QLayout):
    """Layout que coloca widgets en una fila y los envuelve a la siguiente
    cuando no caben. Equivalente al QtFlowLayout de los ejemplos oficiales,
    portado a Python.
    """

    def __init__(self, parent=None, *, margin_h: int = 0, margin_v: int = 0,
                 h_spacing: int = 6, v_spacing: int = 4):
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._h_space = h_spacing
        self._v_space = v_spacing
        self.setContentsMargins(margin_h, margin_v, margin_h, margin_v)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for it in self._items:
            size = size.expandedTo(it.minimumSize())
        l, t, r, b = self.getContentsMargins()
        size += QSize(l + r, t + b)
        return size

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        l, t, r, b = self.getContentsMargins()
        effective = rect.adjusted(l, t, -r, -b)
        x = effective.x()
        y = effective.y()
        line_h = 0
        for item in self._items:
            wid = item.widget()
            if wid is None:
                continue
            # NO filtramos por wid.isVisible() — widgets recién agregados
            # vía addWidget() todavía no son "visible" cuando Qt calcula el
            # primer layout. Saltarlos los deja en (0,0) superpuestos.
            sh = item.sizeHint()
            next_x = x + sh.width() + self._h_space
            if next_x - self._h_space > effective.right() and line_h > 0:
                # Wrap a siguiente fila
                x = effective.x()
                y = y + line_h + self._v_space
                next_x = x + sh.width() + self._h_space
                line_h = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), sh))
            x = next_x
            line_h = max(line_h, sh.height())
        return y + line_h - rect.y() + b


# ── Grid responsivo ───────────────────────────────────────────────────────────

class _ResponsiveGrid(QWidget):
    """Reorganiza tarjetas de ancho fijo en N columnas según el ancho disponible."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background:{BG};")
        self._cards: list = []
        self._items_ref: list = []
        self._cols = 0

        self._layout = QGridLayout(self)
        self._layout.setContentsMargins(GRID_MARG, 16, GRID_MARG, 20)
        self._layout.setSpacing(GRID_GAP)
        self._layout.setAlignment(Qt.AlignTop)

        # Debounce resize: evita re-layout en cada píxel al arrastrar la ventana
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(35)
        self._resize_timer.timeout.connect(self._do_resize)
        self._pending_w = 0

    def set_cards(self, cards: list):
        self.setUpdatesEnabled(False)
        while self._layout.count():
            self._layout.takeAt(0)
        for c in self._cards:
            c.deleteLater()
        # Copia defensiva: si el caller comparte su lista (p.ej. la caché de
        # cards del dashboard), un extend externo duplicaría entradas aquí y
        # el siguiente _arrange dispersaría las cards dejando huecos arriba.
        self._cards     = list(cards)
        self._items_ref = self._cards
        self._cols      = 0
        self._arrange(self._calc_cols(self._ancho_visible()))
        self.setUpdatesEnabled(True)


    def _ancho_visible(self) -> int:
        """Ancho del viewport del QScrollArea (el área realmente visible).
        NO usar self.width(): si el grid quedó más ancho que el viewport
        (p.ej. al aparecer la scrollbar vertical), su propio resizeEvent ya
        no llega y las columnas quedan atascadas recortando la última."""
        vp = self.parentWidget()
        return vp.width() if vp is not None and vp.width() > 0 else self.width()

    def _calc_cols(self, w: int) -> int:
        available = w - 2 * GRID_MARG
        return max(1, (available + GRID_GAP) // (CARD_W_MIN + GRID_GAP))

    def _arrange(self, cols: int):
        if cols == self._cols and self._layout.count() == len(self._cards):
            return
        self._cols = cols
        self.setUpdatesEnabled(False)
        while self._layout.count():
            self._layout.takeAt(0)
        for i, card in enumerate(self._cards):
            self._layout.addWidget(card, i // cols, i % cols)
        # Repartir el ancho disponible en partes iguales entre las columnas
        # activas (cards Expanding) y limpiar stretches de columnas viejas.
        for c in range(max(cols, self._layout.columnCount())):
            self._layout.setColumnStretch(c, 1 if c < cols else 0)
        self.setUpdatesEnabled(True)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._pending_w = self._ancho_visible()
        self._resize_timer.start()   # debounce — re-layout solo al soltar

    def eventFilter(self, obj, event):
        # Instalado sobre el viewport del QScrollArea: cuando el viewport
        # cambia (resize de ventana O aparición de la scrollbar vertical),
        # recalcular columnas aunque el grid no reciba resizeEvent propio.
        from PySide6.QtCore import QEvent
        if event.type() == QEvent.Resize:
            self._pending_w = event.size().width()
            self._resize_timer.start()
        return False

    def _do_resize(self):
        new_cols = self._calc_cols(self._pending_w)
        if new_cols != self._cols:
            self._arrange(new_cols)

    def mousePressEvent(self, event):
        # Clic en el fondo vacío → deseleccionar
        if event.button() == Qt.LeftButton and self.childAt(event.position().toPoint()) is None:
            for card in self._items_ref:
                if hasattr(card, 'setSelected'):
                    card.setSelected(False)
        super().mousePressEvent(event)


# ── Estrella clickeable para la tabla de lista ───────────────────────────────

class _RowColorDelegate(QStyledItemDelegate):
    """Fuerza el BackgroundRole ignorando el stylesheet de la tabla."""

    _BG_PAR   = QColor("#FFFFFF")    # filas pares   — blanco
    _BG_IMPAR = QColor("#F5F6F8")    # filas impares — gris claro sutil

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        bg = index.data(Qt.BackgroundRole)
        if bg:
            option.backgroundBrush = bg if isinstance(bg, QBrush) else QBrush(bg)
        else:
            option.backgroundBrush = QBrush(
                self._BG_IMPAR if index.row() % 2 != 0 else self._BG_PAR
            )

    # Columnas con word wrap (nombre=2, cliente=3, ubicación=4)
    _WRAP_COLS = {2, 3, 4}

    def paint(self, painter, option, index):
        # Fondo
        bg = index.data(Qt.BackgroundRole)
        color = bg.color() if isinstance(bg, QBrush) else (
            bg if isinstance(bg, QColor) else (
                self._BG_IMPAR if index.row() % 2 != 0 else self._BG_PAR
            )
        )
        painter.fillRect(option.rect, color)

        # Selección
        if option.state & QStyle.State_Selected:
            painter.fillRect(option.rect, QColor("#FDDCB5"))

        # Separador sutil
        painter.save()
        painter.setPen(QColor("#EDE8E0"))
        painter.drawLine(option.rect.bottomLeft(), option.rect.bottomRight())
        painter.restore()

        # Texto con padding
        text = index.data(Qt.DisplayRole)
        if text:
            fg = index.data(Qt.ForegroundRole)
            painter.save()
            if fg:
                painter.setPen(fg.color() if isinstance(fg, QBrush) else QColor(fg))
            else:
                painter.setPen(QColor("#273445"))
            rect = option.rect.adjusted(8, 4, -8, -4)
            if index.column() in self._WRAP_COLS:
                # Máximo 2 líneas + elipsis: con la columna angosta, el wrap
                # ilimitado partía el nombre palabra por palabra y la fila
                # crecía media pantalla. El texto completo va en el tooltip.
                fm = option.fontMetrics
                texto = str(text)
                lines, current = [], ''
                for word in texto.split():
                    t = (current + ' ' + word).strip()
                    if fm.horizontalAdvance(t) <= rect.width():
                        current = t
                    else:
                        if current:
                            lines.append(current)
                        current = word
                    if len(lines) >= 2:
                        break
                if current and len(lines) < 2:
                    lines.append(current)
                if len(' '.join(lines).strip()) < len(texto.strip()) and lines:
                    lines[-1] = fm.elidedText(lines[-1] + '…', Qt.ElideRight,
                                              rect.width())
                lh = fm.lineSpacing()
                y0 = rect.top() + max(0, (rect.height() - lh * len(lines)) // 2)
                for i, line in enumerate(lines):
                    painter.drawText(rect.left(), y0 + i * lh + fm.ascent(), line)
            else:
                align = index.data(Qt.TextAlignmentRole) or (Qt.AlignLeft | Qt.AlignVCenter)
                painter.drawText(rect, align, str(text))
            painter.restore()


# ── Vista de lista ────────────────────────────────────────────────────────────

class _ListView(QWidget):
    """Vista de proyectos en tabla compacta (modo lista)."""
    abrir            = Signal(int)
    editar           = Signal(int)
    eliminar         = Signal(int)
    copiar           = Signal(int)
    favorito_toggled = Signal(int)
    seleccionado     = Signal(int)
    estado_cambiado  = Signal(int, str)   # (pid, nuevo_estado) → dashboard recarga

    # Col 0=indicador color, 1=★, 2=Nombre, 3=Cliente, 4=Ubicación,
    #     5=Estado, 6=Total, 7=Partidas, 8=Fecha, 9=Acciones
    @staticmethod
    def _cols():
        from utils.i18n import tr
        return ["", "", tr("Nombre"), tr("Cliente"), tr("Ubicación"), tr("Portafolio"),
                tr("Estado"), "Total", tr("Partidas"), tr("Fecha"), ""]
    _COLS = ["", "", "Nombre", "Cliente", "Ubicación", "Portafolio", "Estado", "Total", "Partidas", "Fecha", ""]

    _BG_ULTIMO  = QColor("#FFF9C4")
    _BG_SEL     = QColor("#FEF5EB")
    _BG_PAR   = QColor("#FFFFFF")    # filas pares   — blanco
    _BG_IMPAR = QColor("#F5F6F8")    # filas impares — gris claro sutil

    def __init__(self, usuario: Usuario, parent=None):
        super().__init__(parent)
        self.usuario             = usuario
        self._pids: list[int]   = []
        self._favs: list[bool]  = []
        self._ultimo_pid: int | None = None
        self._build_ui()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._ajustar_columnas()

    def _ajustar_columnas(self):
        """Tabla responsive: garantiza ≥240 px para el Nombre ocultando
        columnas secundarias (Ubicación → Portafolio → Cliente) cuando la
        ventana se angosta, y mostrándolas de nuevo cuando vuelve a caber."""
        if not hasattr(self, 'tbl'):
            return
        vp = self.tbl.viewport().width()
        fijas = 32 + 102 + 104 + 58 + 80   # ★ estado total partidas fecha
        restante = vp - fijas - 240                 # 240 reservado para Nombre
        # Orden de PRIORIDAD para mostrar: cliente, portafolio, ubicación
        visibles = set()
        for col, wdt in ((3, 130), (5, 110), (4, 130)):
            if restante >= wdt:
                visibles.add(col)
                restante -= wdt
        for col in (3, 4, 5):
            self.tbl.setColumnHidden(col, col not in visibles)

    def _build_ui(self):
        vl = QVBoxLayout(self)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)

        self.tbl = QTableWidget(0, len(self._COLS))
        self.tbl.setHorizontalHeaderLabels(self._cols())
        hh = self.tbl.horizontalHeader()
        hh.setSectionResizeMode(2, QHeaderView.Stretch)   # Nombre absorbe el resto
        hh.setSectionResizeMode(10, QHeaderView.Fixed)    # Acciones
        self.tbl.setColumnHidden(0, True)   # indicador de color: retirado
        self.tbl.setColumnHidden(10, True)  # «⋯»: las acciones van por clic derecho
        self.tbl.setColumnWidth(1, 32)     # estrella
        self.tbl.setColumnWidth(3, 130)    # cliente
        self.tbl.setColumnWidth(4, 130)    # ubicación
        self.tbl.setColumnWidth(5, 110)    # portafolio
        self.tbl.setColumnWidth(6, 102)    # estado badge
        self.tbl.setColumnWidth(7, 104)    # total
        self.tbl.setColumnWidth(8, 58)     # partidas
        self.tbl.setColumnWidth(9, 80)     # fecha
        # Filas de alto FIJO (2 líneas máx, el delegate elide): sin esto,
        # una columna angosta + word-wrap inflaba filas a media pantalla.
        vh = self.tbl.verticalHeader()
        vh.setSectionResizeMode(QHeaderView.Fixed)
        vh.setDefaultSectionSize(40)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl.setAlternatingRowColors(False)
        # Ordenamiento al hacer clic en los encabezados (deshabilitado durante
        # el populate para no penalizar la inserción de muchas filas).
        self.tbl.setSortingEnabled(False)
        hh.setSortIndicatorShown(True)
        hh.setSectionsClickable(True)
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setShowGrid(False)
        self.tbl.setStyleSheet("""
            QTableWidget {
                border: none;
                font-size: 11px;
                background: white;
                outline: 0;
            }
            QHeaderView::section {
                background: #F5F6F8;
                color: #667885;
                font-size: 10px;
                font-weight: 700;
                padding: 5px 8px;
                border: none;
                border-bottom: 2px solid #E0E4EA;
            }
        """)
        self.tbl.setWordWrap(True)
        self._delegate = _RowColorDelegate(self.tbl)
        self.tbl.setItemDelegate(self._delegate)
        self.tbl.doubleClicked.connect(lambda idx: self.abrir.emit(self._pids[idx.row()]))
        self.tbl.clicked.connect(self._on_click_fila)
        self.tbl.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tbl.customContextMenuRequested.connect(self._on_context_menu)
        vl.addWidget(self.tbl)

        # Recalcular altura de filas al redimensionar columnas/ventana
        # (Qt no lo hace solo; con word-wrap el alto depende del ancho).
        # Debounced con QTimer para no thrashear durante el drag.
        self._h_resize_timer = QTimer(self)
        self._h_resize_timer.setSingleShot(True)
        self._h_resize_timer.setInterval(120)
        self._h_resize_timer.timeout.connect(self.tbl.resizeRowsToContents)
        hh.sectionResized.connect(
            lambda *_: self._h_resize_timer.start()
        )

    def set_rows(self, rows: list, color_map: dict,
                 selected_pid: int | None = None,
                 ultimo_pid: int | None = None,
                 totales_por_pid: dict | None = None):
        totales_por_pid = totales_por_pid or {}
        self._items_total: dict[int, QTableWidgetItem] = {}
        self.tbl.blockSignals(True)
        # Deshabilitar sort durante el populate para que las filas se inserten
        # en orden y los cellWidgets queden alineados con sus items.
        self.tbl.setSortingEnabled(False)
        self.tbl.setRowCount(0)
        self._pids.clear()
        self._favs.clear()
        self._ultimo_pid = ultimo_pid
        self.tbl.setUpdatesEnabled(False)

        fila_seleccionada = -1

        # Precalcular conteos de partidas-hoja con UNA SOLA query agregada
        # en lugar de N COUNT(*) por proyecto. Para 400 proyectos baja de
        # ~400 conexiones SQLite a 1.
        conn = get_db()
        try:
            cnt_rows = conn.execute(
                "SELECT proyecto_id, COUNT(*) AS n FROM partidas "
                "WHERE es_titulo=0 GROUP BY proyecto_id"
            ).fetchall()
            count_por_proy = {r['proyecto_id']: r['n'] for r in cnt_rows}
        finally:
            conn.close()

        # Reservar las filas todas de una vez (mucho más rápido que insertRow
        # en bucle, mismo patrón que usamos en _AcuTable / recursos_view).
        self.tbl.setRowCount(len(rows))

        for r, row in enumerate(rows):
            pid    = row['id']
            es_fav = bool(row.get('favorito'))
            moneda = row.get('moneda', 'Soles')
            estado = row.get('estado') or 'elaboracion'
            bg_e, fg_e, lbl_e = ESTADO_COLOR.get(estado, ("#F0F1F2", SLATE_300, estado))

            # El total llega del caché del dashboard; los que faltan se
            # calculan en segundo plano y entran vía set_total(pid, …).
            total_str = totales_por_pid.get(pid, '…')
            n_part = count_por_proy.get(pid, 0)

            # 'r' viene del enumerate del for; las filas se reservaron antes
            self.tbl.setMinimumHeight(36)
            self._pids.append(pid)
            self._favs.append(es_fav)

            bg_base = self._BG_PAR if r % 2 == 0 else self._BG_IMPAR
            if pid == selected_pid:
                fila_seleccionada = r
                bg_fila = self._BG_SEL
            elif pid == ultimo_pid:
                bg_fila = self._BG_ULTIMO
            else:
                bg_fila = bg_base

            bg_str = bg_fila.name()

            # Col 1 — estrella (item; el clic se maneja en _on_click_fila)
            it_fav = QTableWidgetItem("★" if es_fav else "☆")
            f_star = QFont(self.tbl.font().family(), 12)
            it_fav.setFont(f_star)
            it_fav.setForeground(QColor('#F9C440' if es_fav else '#D4D4D4'))
            it_fav.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
            it_fav.setBackground(bg_fila)
            self.tbl.setItem(r, 1, it_fav)

            # Col 2 — Nombre. El pid se guarda en UserRole para sobrevivir
            # al re-orden por sort.
            nombre_txt = row.get('nombre') or "—"
            if pid == ultimo_pid:
                nombre_txt += "  ·  Reciente"
            it_nombre = QTableWidgetItem(nombre_txt)
            it_nombre.setToolTip(nombre_txt)
            it_nombre.setData(Qt.UserRole, pid)
            it_nombre.setForeground(QColor(SLATE_700))
            it_nombre.setBackground(bg_fila)
            self.tbl.setItem(r, 2, it_nombre)

            # Col 3 — Cliente
            it = QTableWidgetItem(row.get('cliente') or "—")
            it.setForeground(QColor(SLATE_500))
            it.setBackground(bg_fila)
            self.tbl.setItem(r, 3, it)

            # Col 4 — Ubicación
            it = QTableWidgetItem(row.get('ubicacion') or "—")
            it.setForeground(QColor(SLATE_500))
            it.setBackground(bg_fila)
            self.tbl.setItem(r, 4, it)

            # Col 5 — Portafolio (chip pastel + item "sombra" para sortar)
            portafolio_nombre = row.get('portafolio_nombre')
            pf_text_sort = portafolio_nombre or ""   # vacío al ordenar para que vaya al final
            it_pf = QTableWidgetItem(pf_text_sort)
            it_pf.setBackground(bg_fila)
            self.tbl.setItem(r, 5, it_pf)
            it_pf.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
            if portafolio_nombre:
                color_p = row.get('portafolio_color') or SLATE_500
                cp = QColor(color_p); cp_bg = QColor(cp); cp_bg.setAlphaF(0.15)
                it_pf.setForeground(cp)
                it_pf.setBackground(cp_bg)
                f_pf = QFont(self.tbl.font().family(), 8); f_pf.setBold(True)
                it_pf.setFont(f_pf)
            else:
                # mostrar "—" como texto plano cuando no hay portafolio.
                # UserRole+1='zebra': _recolor_rows puede repintar su fondo.
                it_pf.setText("—")
                it_pf.setForeground(QColor(SLATE_300))
                it_pf.setData(Qt.UserRole + 1, 'zebra')

            # Col 6 — Estado (item con colores del estado, sin widget)
            it_est = QTableWidgetItem(lbl_e)
            it_est.setForeground(QColor(fg_e))
            it_est.setBackground(QColor(bg_e))
            it_est.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
            f_est = QFont(self.tbl.font().family(), 8); f_est.setBold(True)
            it_est.setFont(f_est)
            self.tbl.setItem(r, 6, it_est)

            # Col 7 — Total
            it = QTableWidgetItem(total_str)
            it.setForeground(QColor(SLATE_700))
            it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            it.setBackground(bg_fila)
            self.tbl.setItem(r, 7, it)
            self._items_total[pid] = it   # referencia viva: sobrevive al sort

            # Col 8 — Partidas
            it = QTableWidgetItem(str(n_part))
            it.setForeground(QColor(SLATE_300))
            it.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
            it.setBackground(bg_fila)
            self.tbl.setItem(r, 8, it)

            # Col 9 — Fecha
            it = QTableWidgetItem((row.get('modificado_en') or row.get('creado_en') or "")[:10])
            it.setForeground(QColor(SLATE_300))
            it.setBackground(bg_fila)
            self.tbl.setItem(r, 9, it)


        self.tbl.blockSignals(False)
        self.tbl.setUpdatesEnabled(True)
        self._ajustar_columnas()
        # Activar sort después del populate — los items "sombra" detrás de
        # los cellWidgets permiten ordenar columnas Portafolio y Estado.
        self.tbl.setSortingEnabled(True)
        # Repintar alternancia gris después de cada ordenamiento
        hh = self.tbl.horizontalHeader()
        try:
            hh.sortIndicatorChanged.disconnect(self._recolor_rows)
        except Exception:
            pass
        hh.sortIndicatorChanged.connect(self._recolor_rows)
        if fila_seleccionada >= 0:
            self.tbl.selectRow(fila_seleccionada)
        return len(rows)

    def _recolor_rows(self, *_):
        """Reaplica colores de fila alternados según la posición visual.
        Llamado tras cada cambio de ordenamiento — Qt mueve los items con sus
        backgrounds originales y rompe la alternancia. Las celdas con color
        propio (col 0 indicador, col 6 estado, col 5 con portafolio) viajan
        bien con el sort y NO se tocan."""
        try:
            self.tbl.setUpdatesEnabled(False)
            for r in range(self.tbl.rowCount()):
                bg = self._BG_PAR if r % 2 == 0 else self._BG_IMPAR
                for c in (1, 2, 3, 4, 7, 8, 9):
                    it = self.tbl.item(r, c)
                    if it is not None:
                        it.setBackground(bg)
                it5 = self.tbl.item(r, 5)
                if it5 is not None and it5.data(Qt.UserRole + 1) == 'zebra':
                    it5.setBackground(bg)
        finally:
            self.tbl.setUpdatesEnabled(True)

    def _pid_at_row(self, r: int) -> int | None:
        """Retorna el pid de la fila r leyendo el UserRole del item de Nombre.
        Esto sobrevive al reordenamiento del sort."""
        it = self.tbl.item(r, 2)
        if it is None:
            return None
        v = it.data(Qt.UserRole)
        try:
            return int(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    def _on_click_fila(self, index):
        pid = self._pid_at_row(index.row())
        if pid is None:
            return
        col = index.column()
        if col == 1:        # estrella → favorito
            self._toggle_fav(index.row(), pid)
            return
        self.seleccionado.emit(pid)

    def _on_context_menu(self, pos):
        idx = self.tbl.indexAt(pos)
        if not idx.isValid():
            return
        r = idx.row()
        pid = self._pid_at_row(r)
        if pid is None:
            return
        self._abrir_menu_fila(pid, self.tbl.viewport().mapToGlobal(pos))

    def _abrir_menu_fila(self, pid: int, global_pos):
        """Menú de acciones de una fila (clic derecho o botón «⋯»)."""
        class _Signals:
            """Adaptador que convierte acciones del menú en señales de _ListView.
            `estado_cambiado` reusa la señal real de la lista → el dashboard la
            conecta a `_on_estado_cambiado` y recarga (igual que el mosaico)."""
            def __init__(self, lv):
                self._lv = lv
                self.abrir           = lv.abrir
                self.editar          = lv.editar
                self.eliminar        = lv.eliminar
                self.copiar          = lv.copiar
                self.favorito_toggled = lv.favorito_toggled
                self.estado_cambiado  = lv.estado_cambiado

        _mostrar_menu_proyecto(
            pid, global_pos, self, self.usuario,
            card_signals=_Signals(self)
        )

    def select_pid(self, pid: int | None):
        """Selecciona la fila del pid dado sin emitir señal."""
        if pid is None:
            self.tbl.clearSelection()
            return
        for r, p in enumerate(self._pids):
            if p == pid:
                self.tbl.selectRow(r)
                self.tbl.scrollTo(self.tbl.model().index(r, 0))
                return


    def _toggle_fav(self, row_i: int, pid: int):
        # Buscar la fila visual ACTUAL del proyecto — sobrevive al sort
        # buscando el UserRole en col 2 (Nombre).
        visible_row = -1
        for rr in range(self.tbl.rowCount()):
            it = self.tbl.item(rr, 2)
            if it and it.data(Qt.UserRole) == pid:
                visible_row = rr
                break
        # _favs[i] sigue correspondiendo a _pids[i] por construcción
        try:
            i_orig = self._pids.index(pid)
        except ValueError:
            i_orig = row_i
        es_fav = not self._favs[i_orig]
        self._favs[i_orig] = es_fav
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.execute("UPDATE proyectos SET favorito=? WHERE id=?",
                         (1 if es_fav else 0, pid))
            conn.commit()
            conn.close()
        except Exception:
            self._favs[i_orig] = not es_fav
            return
        # Actualizar el item de la estrella (col 1)
        if visible_row >= 0:
            it = self.tbl.item(visible_row, 1)
            if it is not None:
                it.setText("★" if es_fav else "☆")
                it.setForeground(QColor('#F9C440' if es_fav else '#D4D4D4'))
        self.favorito_toggled.emit(pid)


# ═══════════════════════════════════════════════════════════════════════════════
class DashboardView(QWidget):
# ═══════════════════════════════════════════════════════════════════════════════

    abrir_proyecto           = Signal(int)
    nuevo_proyecto           = Signal()
    editar_proyecto_solicitado = Signal(int)
    ir_a_importar            = Signal()   # estado vacío → vista Importar

    def __init__(self, usuario: Usuario, parent=None):
        super().__init__(parent)
        self.usuario           = usuario
        self._modo             = "mosaico"
        self._rows_cache: list = []
        self._color_cache: dict = {}
        self._cards_cache: list = []
        # Caché de totales por proyecto: pid → (modificado_en, total_str).
        # Se autoinvalida cuando cambia modificado_en (triggers de la BD).
        self._tot_cache: dict = {}
        self._tot_gen = 0
        self._selected_pid: int | None = None
        self._selected_idx: int = -1
        self.setStyleSheet(f"background:{BG};")
        self.setFocusPolicy(Qt.StrongFocus)   # recibir teclas
        self._build_ui()
        self.cargar_proyectos()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._make_barra())
        root.addWidget(self._make_portafolios_bar())

        # Stack: mosaico / lista
        self._stack = QStackedWidget()

        # — Modo mosaico —
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        # El mosaico es fluido: NUNCA debe scrollear horizontal. Sin esto,
        # durante el arrastre del resize (antes del reflow debounced) el
        # contenido excede el viewport y Qt muestra la barra un instante.
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet(f"background:{BG};")
        self._grid = _ResponsiveGrid()
        self._scroll.setWidget(self._grid)
        self._scroll.viewport().installEventFilter(self._grid)
        self._stack.addWidget(self._scroll)    # índice 0

        # — Modo lista —
        self._list_view = _ListView(self.usuario)
        self._list_view.abrir.connect(self._abrir_y_recordar)
        self._list_view.editar.connect(self._editar_proyecto)
        self._list_view.eliminar.connect(self._eliminar_proyecto)
        self._list_view.copiar.connect(self._copiar_proyecto)
        self._list_view.favorito_toggled.connect(self._on_favorito_toggled)
        self._list_view.estado_cambiado.connect(self._on_estado_cambiado)
        self._list_view.seleccionado.connect(self._seleccionar_desde_lista)
        self._stack.addWidget(self._list_view) # índice 1

        # — Estado vacío (sin proyectos) — hero de migración —
        self._empty_page = self._build_empty_state()
        self._stack.addWidget(self._empty_page)  # índice 2

        root.addWidget(self._stack, stretch=1)

        # Pie con contador
        pie = QFrame()
        pie.setFixedHeight(28)
        pie.setStyleSheet("background:#e8eaf0; border-top:1px solid #d0d8e8;")
        hl = QHBoxLayout(pie)
        hl.setContentsMargins(20, 0, 20, 0)
        self.lbl_count = QLabel("")
        self.lbl_count.setStyleSheet("color:#8899aa; font-size:11px;")
        hl.addWidget(self.lbl_count)
        hl.addStretch()

        nombre = self.usuario.nombre if self.usuario else ""
        rol    = self.usuario.rol    if self.usuario else ""
        rol_label = {"admin": "Administrador", "usuario": "Usuario",
                     "invitado": "Invitado"}.get(rol, rol)
        self.lbl_usuario_pie = QLabel(f"👤  {nombre}  ·  {rol_label}")
        self.lbl_usuario_pie.setStyleSheet(
            "color:#485a6c; font-size:11px; font-weight:600;"
        )
        hl.addWidget(self.lbl_usuario_pie)
        root.addWidget(pie)

    def _build_empty_state(self) -> QWidget:
        """Hero que ve un usuario nuevo (dashboard sin proyectos): invita a
        IMPORTAR su base de datos de PowerCost/Delphin/S10 — el principal muro
        de adopción es que ya tienen su base en otro software."""
        from utils.theme import BTN_PRIMARY_SS
        from utils.icons import icon

        w = QWidget()
        w.setStyleSheet(f"background:{BG};")
        v = QVBoxLayout(w)
        v.setContentsMargins(24, 24, 24, 24)
        v.addStretch(1)

        card = QFrame()
        card.setObjectName("emptyCard")
        card.setAttribute(Qt.WA_StyledBackground, True)
        card.setMaximumWidth(560)
        card.setStyleSheet(
            f"QFrame#emptyCard {{ background:{CARD_BG};"
            f"  border:1px solid {SILVER_300}; border-radius:16px; }}"
        )
        cv = QVBoxLayout(card)
        cv.setContentsMargins(40, 36, 40, 36)
        cv.setSpacing(12)

        ico = QLabel()
        ico.setPixmap(icon("paquete").pixmap(56, 56))
        ico.setAlignment(Qt.AlignCenter)
        ico.setStyleSheet("background:transparent; border:none;")
        cv.addWidget(ico)

        titulo = QLabel("Empieza trayendo tu base de datos")
        titulo.setAlignment(Qt.AlignCenter)
        titulo.setStyleSheet(
            f"color:{SLATE_700}; font-size:18px; font-weight:700;"
            f"  background:transparent; border:none;"
        )
        cv.addWidget(titulo)

        sub = QLabel(
            "¿Vienes de <b>PowerCost</b>, <b>Delphin Express</b> o <b>S10</b>? "
            "Importa tu base de datos y arma tu presupuesto sin partir de cero. "
            "También puedes empezar un proyecto nuevo desde aquí."
        )
        sub.setAlignment(Qt.AlignCenter)
        sub.setWordWrap(True)
        sub.setTextFormat(Qt.RichText)
        sub.setStyleSheet(
            f"color:{SLATE_500}; font-size:13px; background:transparent; border:none;"
        )
        cv.addWidget(sub)

        cv.addSpacing(6)
        btns = QHBoxLayout()
        btns.setSpacing(10)
        btns.addStretch(1)
        btn_migrar = QPushButton("  Migrar mi base de datos")
        btn_migrar.setIcon(icon("paquete"))
        btn_migrar.setIconSize(QSize(18, 18))
        btn_migrar.setMinimumHeight(40)
        btn_migrar.setCursor(Qt.PointingHandCursor)
        btn_migrar.setStyleSheet(BTN_PRIMARY_SS)
        btn_migrar.clicked.connect(self.ir_a_importar.emit)
        btns.addWidget(btn_migrar)

        btn_nuevo = QPushButton("Crear proyecto nuevo")
        btn_nuevo.setMinimumHeight(40)
        btn_nuevo.setCursor(Qt.PointingHandCursor)
        btn_nuevo.setStyleSheet(
            f"QPushButton {{ background:{CARD_BG}; color:{SLATE_700};"
            f"  border:1px solid {SILVER_300}; border-radius:8px;"
            f"  padding:8px 18px; font-size:13px; }}"
            f"QPushButton:hover {{ border-color:{ORANGE_500}; color:{ORANGE_500}; }}"
        )
        btn_nuevo.clicked.connect(self.nuevo_proyecto.emit)
        btns.addWidget(btn_nuevo)
        btns.addStretch(1)
        cv.addLayout(btns)

        fmts = QLabel(
            "Formatos: PowerCost (.prs · Excel · PDF) · Delphin (.sqlite · Excel) · "
            "S10 (.S2K · Excel) · IFC/BIM · base ingePresupuestos (.db)"
        )
        fmts.setAlignment(Qt.AlignCenter)
        fmts.setWordWrap(True)
        fmts.setStyleSheet(
            f"color:{SLATE_300}; font-size:11px; padding-top:4px;"
            f"  background:transparent; border:none;"
        )
        cv.addWidget(fmts)

        hwrap = QHBoxLayout()
        hwrap.addStretch(1)
        hwrap.addWidget(card)
        hwrap.addStretch(1)
        v.addLayout(hwrap)
        v.addStretch(1)
        return w

    def _make_barra(self) -> QFrame:
        bar = QFrame()
        bar.setFixedHeight(52)
        bar.setStyleSheet("background:white; border:none;")
        hl = QHBoxLayout(bar)
        hl.setContentsMargins(20, 0, 20, 0)
        hl.setSpacing(10)

        # Título
        lbl = QLabel("PROYECTOS")
        lbl.setStyleSheet(f"color:{SLATE_700}; font-size:13px; font-weight:700; letter-spacing:0.5px;")
        hl.addWidget(lbl)

        # Búsqueda
        self.inp_buscar = QLineEdit()
        from utils.i18n import tr as _tr
        self.inp_buscar.setPlaceholderText(_tr("Buscar") + "...")
        self.inp_buscar.setFixedWidth(200)
        self.inp_buscar.setFixedHeight(32)
        self.inp_buscar.setStyleSheet(
            "border:1px solid #d0d8e8; border-radius:14px;"
            " padding:0 12px; font-size:12px; background:white; color:#273445;"
        )
        self.inp_buscar.textChanged.connect(self.cargar_proyectos)
        hl.addWidget(self.inp_buscar)

        hl.addStretch()

        # Pill dropdown Estado
        estado_opts = [
            (ESTADO_COLOR.get(e, ("#", "#", e))[2], e)
            for e in ESTADOS_PROYECTO
        ]
        self.cmb_estado = _PillDropdown(_tr("Estado"), estado_opts)
        self.cmb_estado.setFixedHeight(32)
        self.cmb_estado.option_changed.connect(self.cargar_proyectos)
        hl.addWidget(self.cmb_estado)

        # Pill orden
        self.cmb_orden = _PillOrder([_tr("Más recientes"), _tr("Favoritos"), _tr("Nombre") + " A-Z", _tr("Cliente")])
        self.cmb_orden.setFixedHeight(32)
        self.cmb_orden.option_changed.connect(self.cargar_proyectos)
        hl.addWidget(self.cmb_orden)

        # Toggle segmentado mosaico / lista
        hl.addSpacing(6)
        self._seg = _SegmentedToggle()
        self._seg.changed.connect(self._cambiar_modo)
        hl.addWidget(self._seg)

        return bar

    def _cambiar_modo(self, modo: str):
        self._modo = modo
        # Si el dashboard está vacío (hero de migración visible), el toggle
        # mosaico/lista no debe sacarlo de esa página.
        if getattr(self, '_empty_hero', False):
            self._stack.setCurrentIndex(2)
            return
        # Cambio visual inmediato (los widgets ya viven en el QStackedWidget)
        self._stack.setCurrentIndex(0 if modo == "mosaico" else 1)
        # Re-renderiza SOLO si el modo destino no está al día con los rows
        # cacheados. Con 400 proyectos esto evita reconstruir 400 widgets
        # cada vez que alternas mosaico ↔ lista.
        rows = self._rows_cache or []
        rows_id = id(rows)
        if modo == "mosaico":
            if getattr(self, '_mosaico_rendered_for', None) != rows_id:
                self._renderizar(rows, solo_modo='mosaico')
                self._mosaico_rendered_for = rows_id
        else:
            if getattr(self, '_lista_rendered_for', None) != rows_id:
                self._renderizar(rows, solo_modo='lista')
                self._lista_rendered_for = rows_id
            if self._selected_pid is not None:
                self._list_view.select_pid(self._selected_pid)

    # ── Barra de portafolios ─────────────────────────────────────────────────
    def _make_portafolios_bar(self) -> QFrame:
        """Barra de tags-tarjetas clicables para filtrar por portafolio.

        Usa FlowLayout: cuando no caben en una fila se envuelven a la
        siguiente automáticamente. Sin scroll horizontal.

        Valores especiales del data: None=todos, 0=sin clasificar, N=id portafolio.
        """
        self._portafolio_filter = None   # None=todos
        bar = QFrame()
        bar.setStyleSheet(f"background:{SILVER_100}; border:none;")
        # Contenedor interno con FlowLayout (wrap automático)
        self._portafolios_hl = _FlowLayout(bar, margin_h=20, margin_v=4,
                                            h_spacing=6, v_spacing=4)
        self._recargar_portafolios_bar()
        return bar

    def _recargar_portafolios_bar(self):
        """Reconstruye los tags. Llamar tras crear/renombrar/eliminar portafolios."""
        # Limpiar layout: sacar del layout Y desconectar del padre visual
        # antes de programar la eliminación. Sin setParent(None), los widgets
        # viejos quedan visibles en el contenedor hasta que el event loop
        # procese deleteLater(), apareciendo entremezclados con los nuevos.
        while self._portafolios_hl.count():
            item = self._portafolios_hl.takeAt(0)
            if item is None:
                break
            w = item.widget()
            if w:
                w.hide()
                w.setParent(None)
                w.deleteLater()

        from core.database import listar_portafolios as _listar
        portafolios = _listar()

        # Tag "Todos"
        self._portafolios_hl.addWidget(self._mk_tag_portafolio(
            None, "Todos", SLATE_500,
            sum(p['n_proyectos'] for p in portafolios) +
            self._contar_sin_clasificar(portafolios),
        ))
        # Tags de portafolios
        for p in portafolios:
            self._portafolios_hl.addWidget(self._mk_tag_portafolio(
                p['id'], p['nombre'], p['color'], p['n_proyectos']
            ))
        # Tag "Sin clasificar"
        sin_clas = self._contar_sin_clasificar(portafolios)
        if sin_clas > 0 or not portafolios:
            self._portafolios_hl.addWidget(self._mk_tag_portafolio(
                0, "Sin clasificar", SLATE_300, sin_clas
            ))

        # Botón "+ Nuevo"
        from utils.icons import icon as _ico
        btn_new = QPushButton("  Nuevo portafolio")
        btn_new.setCursor(QCursor(Qt.PointingHandCursor))
        btn_new.setFixedHeight(28)
        btn_new.setIcon(_ico("add"))
        btn_new.setIconSize(QSize(13, 13))
        btn_new.setStyleSheet(
            f"QPushButton {{ background:transparent; color:{SLATE_500};"
            f" border:1px dashed {SLATE_300}; border-radius:14px;"
            f" padding:0 12px; font-size:11px; font-weight:600; }}"
            f"QPushButton:hover {{ background:white; color:{BLUE_500};"
            f" border-color:{BLUE_500}; }}"
        )
        btn_new.clicked.connect(self._crear_portafolio)
        self._portafolios_hl.addWidget(btn_new)

    def _contar_sin_clasificar(self, portafolios: list[dict]) -> int:
        try:
            conn = get_db()
            n = conn.execute(
                "SELECT COUNT(*) FROM proyectos WHERE portafolio_id IS NULL"
            ).fetchone()[0]
            conn.close()
            return n
        except Exception:
            return 0

    def _mk_tag_portafolio(self, pf_id: int | None, nombre: str,
                            color: str, n_proy: int) -> QPushButton:
        """Botón-tag clickeable. ``pf_id``: None=todos, 0=sin clasificar."""
        activo = (self._portafolio_filter == pf_id)
        btn = QPushButton(f"  {nombre}  ·  {n_proy}")
        btn.setCursor(QCursor(Qt.PointingHandCursor))
        btn.setFixedHeight(28)
        if activo:
            btn.setStyleSheet(
                f"QPushButton {{ background:{color}; color:white;"
                f" border:none; border-radius:14px; padding:0 12px;"
                f" font-size:11px; font-weight:700; }}"
            )
        else:
            btn.setStyleSheet(
                f"QPushButton {{ background:white; color:{color};"
                f" border:1px solid {color}; border-radius:14px;"
                f" padding:0 12px; font-size:11px; font-weight:600; }}"
                f"QPushButton:hover {{ background:{color}; color:white; }}"
            )
        btn.clicked.connect(lambda _=False, p=pf_id: self._set_portafolio_filter(p))
        # Context menu para portafolios reales (no para Todos/Sin clasificar)
        if pf_id is not None and pf_id > 0:
            btn.setContextMenuPolicy(Qt.CustomContextMenu)
            btn.customContextMenuRequested.connect(
                lambda pos, p=pf_id, b=btn: self._menu_portafolio(p, b.mapToGlobal(pos))
            )
        return btn

    def _set_portafolio_filter(self, pf_id: int | None):
        self._portafolio_filter = pf_id
        self._recargar_portafolios_bar()
        self.cargar_proyectos()

    def _menu_portafolio(self, pf_id: int, pos):
        from PySide6.QtWidgets import QMenu, QInputDialog, QColorDialog, QMessageBox
        from utils.icons import icon as _ico
        from core.database import (
            listar_portafolios as _listar,
            actualizar_portafolio as _upd,
            eliminar_portafolio as _del,
        )
        portafolios = _listar()
        actual = next((p for p in portafolios if p['id'] == pf_id), None)
        if not actual:
            return

        menu = QMenu(self)
        from utils.i18n import tr
        a_ren = menu.addAction(_ico("editar"), tr("Renombrar") + "…")
        a_col = menu.addAction(_ico("favorito_on"), tr("Cambiar color") + "…")
        menu.addSeparator()
        a_del = menu.addAction(_ico("eliminar"), tr("Eliminar"))
        chosen = menu.exec(pos)
        if not chosen:
            return
        if chosen == a_ren:
            nuevo, ok = QInputDialog.getText(
                self, "Renombrar portafolio",
                "Nuevo nombre:", text=actual['nombre']
            )
            if ok and nuevo.strip():
                try:
                    _upd(pf_id, nombre=nuevo.strip())
                except Exception as e:
                    QMessageBox.warning(self, "Error", str(e))
                    return
                self._recargar_portafolios_bar()
                self.cargar_proyectos()
        elif chosen == a_col:
            color = QColorDialog.getColor(
                QColor(actual['color'] or SLATE_500), self,
                f"Color de «{actual['nombre']}»"
            )
            if color.isValid():
                _upd(pf_id, color=color.name())
                self._recargar_portafolios_bar()
                self.cargar_proyectos()
        elif chosen == a_del:
            res = QMessageBox.question(
                self, "Eliminar portafolio",
                f"¿Eliminar el portafolio «{actual['nombre']}»?\n\n"
                f"Sus {actual['n_proyectos']} proyecto(s) quedarán sin "
                f"clasificar, no se eliminarán.",
                QMessageBox.Yes | QMessageBox.No
            )
            if res == QMessageBox.Yes:
                _del(pf_id)
                if self._portafolio_filter == pf_id:
                    self._portafolio_filter = None
                self._recargar_portafolios_bar()
                self.cargar_proyectos()

    def _crear_portafolio(self):
        from PySide6.QtWidgets import QInputDialog, QMessageBox
        from core.database import crear_portafolio as _crear
        nombre, ok = QInputDialog.getText(
            self, "Nuevo portafolio",
            "Nombre del portafolio:\n(p.ej. Obras 2026, Cliente X, Proyectos públicos…)"
        )
        if not ok or not nombre.strip():
            return
        # Color por defecto: rotar paleta
        from random import choice
        paleta = ["#E8610A", "#2563EB", "#16A34A", "#9333EA", "#DC2626",
                  "#0891B2", "#B45309", "#BE185D"]
        try:
            _crear(nombre.strip(), color=choice(paleta))
        except Exception as e:
            QMessageBox.warning(
                self, "Error",
                f"No se pudo crear el portafolio:\n{e}\n\n"
                f"Probablemente ya existe un portafolio con ese nombre."
            )
            return
        self._recargar_portafolios_bar()

    # ── Carga y renderizado ───────────────────────────────────────────────────

    def cargar_proyectos(self):
        from utils.formatting import norm_busqueda
        buscar = self.inp_buscar.text().strip()
        estado = self.cmb_estado.currentData()
        orden  = self.cmb_orden.currentIndex()

        q = (
            "SELECT proyectos.*, "
            "       pf.nombre AS portafolio_nombre, "
            "       pf.color AS portafolio_color "
            "FROM proyectos "
            "LEFT JOIN portafolios pf ON pf.id = proyectos.portafolio_id "
            "WHERE 1=1"
        )
        p = []

        if self.usuario and not self.usuario.es_admin:
            q += " AND (proyectos.usuario_id=? OR proyectos.usuario_id IS NULL)"
            p.append(self.usuario.id)

        if estado:
            q += " AND proyectos.estado=?"
            p.append(estado)

        # Filtro por portafolio (None=todos, 0=sin clasificar, N=id)
        pf = getattr(self, '_portafolio_filter', None)
        if pf == 0:
            q += " AND proyectos.portafolio_id IS NULL"
        elif pf is not None:
            q += " AND proyectos.portafolio_id=?"
            p.append(pf)

        _needs_norm = False
        if buscar:
            _needs_norm = True
            like = f"%{norm_busqueda(buscar)}%"
            q += (" AND (_norm(proyectos.nombre) LIKE ? OR _norm(proyectos.cliente) LIKE ?"
                  " OR _norm(proyectos.ubicacion) LIKE ?)")
            p += [like, like, like]

        order_map = {
            0: "COALESCE(proyectos.modificado_en, proyectos.creado_en) DESC",
            1: "proyectos.favorito DESC, COALESCE(proyectos.modificado_en, proyectos.creado_en) DESC",
            2: "proyectos.nombre ASC",
            3: "proyectos.cliente ASC",
        }
        q += f" ORDER BY {order_map.get(orden, 'COALESCE(proyectos.modificado_en, proyectos.creado_en) DESC')}"

        try:
            conn = get_db()
            if _needs_norm:
                conn.create_function("_norm", 1, norm_busqueda)
            rows = conn.execute(q, p).fetchall()
            # Cargar el caché PERSISTENTE de totales (sobrevive reinicios de
            # la app; se invalida solo cuando cambia modificado_en).
            try:
                for cr in conn.execute(
                        "SELECT proyecto_id, modificado_en, total FROM dashboard_tot_cache"):
                    if cr['proyecto_id'] not in self._tot_cache:
                        self._tot_cache[cr['proyecto_id']] = (cr['modificado_en'], cr['total'])
            except Exception:
                pass
            conn.close()
        except Exception:
            rows = []

        # Guardar en caché para reusar al cambiar de modo sin re-consultar
        self._rows_cache   = [dict(r) for r in rows]
        self._color_cache  = {
            r['id']: CARD_BORDER_COLORS[i % len(CARD_BORDER_COLORS)]
            for i, r in enumerate(self._rows_cache)
        }

        # Dashboard REALMENTE vacío (sin proyectos y sin filtros activos) →
        # hero de migración (índice 2). Si hay búsqueda/estado/portafolio sin
        # resultados, se mantiene el modo activo con su mensaje «Sin resultados».
        self._empty_hero = (not self._rows_cache and not buscar
                            and not estado and pf is None)
        if self._empty_hero:
            self._stack.setCurrentIndex(2)
        else:
            self._stack.setCurrentIndex(0 if self._modo == "mosaico" else 1)
            self._renderizar(self._rows_cache)
        n = len(rows)
        self.lbl_count.setText(f"{n} proyecto{'s' if n != 1 else ''}")

    def _renderizar(self, rows: list, solo_modo: str | None = None):
        """Renderiza el modo activo (o el indicado con ``solo_modo``).

        Cuando se llama sin ``solo_modo``, invalida la caché del OTRO modo
        para que se reconstruya la próxima vez que el usuario cambie.
        """
        buscar   = self.inp_buscar.text().strip() if hasattr(self, 'inp_buscar') else ""
        ultimo   = get_ultimo_proyecto()
        modo = solo_modo or self._modo
        rows_id = id(rows)

        # Huella del contenido: si nada cambió desde el último render de este
        # modo (mismos proyectos, fechas, estados, favoritos), las cards/filas
        # existentes siguen válidas — NO reconstruir los ~6.000 widgets.
        # El «último proyecto» NO entra en la huella del mosaico: abrir un
        # proyecto lo cambia siempre, y reconstruir 400 cards solo para mover
        # el resaltado amarillo congelaba el regreso a Inicio.
        fp = (modo, ultimo if modo != 'mosaico' else None, tuple(
            (r['id'], r.get('modificado_en'), r.get('favorito'),
             r.get('estado'), r.get('portafolio_id')) for r in rows))
        fp_attr = '_fp_mosaico' if modo == 'mosaico' else '_fp_lista'
        if rows and getattr(self, fp_attr, None) == fp:
            if modo == 'mosaico' and getattr(self, '_ultimo_render', None) != ultimo:
                # Solo mover el resaltado «Reciente» (2 cards tocadas)
                for card in (self._cards_cache or []):
                    if hasattr(card, 'set_ultimo'):
                        card.set_ultimo(card.pid == ultimo)
                self._ultimo_render = ultimo
            return
        setattr(self, fp_attr, fp)
        self._ultimo_render = ultimo

        # Totales desde el caché (clave de invalidación: modificado_en —
        # los triggers de la BD lo actualizan en cada cambio del proyecto).
        # Los que faltan se muestran como '…' y se calculan en segundo plano:
        # con 400 proyectos, calcular_totales por card congelaba el Inicio.
        totales, faltan = {}, []
        for row in rows:
            pid = row['id']
            mod = row.get('modificado_en') or row.get('creado_en') or ''
            cached = self._tot_cache.get(pid)
            if cached and cached[0] == mod:
                totales[pid] = fmt(cached[1], row.get('moneda', 'Soles'))
            else:
                faltan.append((pid, mod, row.get('moneda', 'Soles')))

        # Conteo de partidas-hoja: UNA query agregada para todos los modos
        try:
            conn = get_db()
            count_por_proy = {r['proyecto_id']: r['n'] for r in conn.execute(
                "SELECT proyecto_id, COUNT(*) AS n FROM partidas "
                "WHERE es_titulo=0 GROUP BY proyecto_id")}
            conn.close()
        except Exception:
            count_por_proy = {}

        if modo == "mosaico":
            if not rows:
                lbl = QLabel("No hay proyectos" if not buscar else f"Sin resultados para «{buscar}»")
                lbl.setAlignment(Qt.AlignCenter)
                lbl.setStyleSheet("color:#9aa5b4; font-size:14px; padding:40px;")
                self._grid.set_cards([lbl])
            else:
                # Con dashboards grandes (50+ proyectos) desactivamos las
                # sombras para no saturar la GPU. Con borde + barra superior
                # de estado las cards siguen siendo legibles.
                con_sombra = len(rows) <= 50

                def _mk_card(row):
                    card = _ProjectCard(
                        row, self._color_cache.get(row['id'], BLUE_500),
                        self.usuario,
                        es_ultimo=(row['id'] == ultimo), con_sombra=con_sombra,
                        total_str=totales.get(row['id'], '…'),
                        n_part=count_por_proy.get(row['id'], 0),
                    )
                    card.abrir.connect(self._abrir_y_recordar)
                    card.editar.connect(self._editar_proyecto)
                    card.eliminar.connect(self._eliminar_proyecto)
                    card.copiar.connect(self._copiar_proyecto)
                    card.favorito_toggled.connect(self._on_favorito_toggled)
                    card.seleccionado.connect(self._seleccionar_card)
                    card.estado_cambiado.connect(self._on_estado_cambiado)
                    return card

                # Construcción en UNA pasada: sin totales por card (van por
                # caché/diferido) son ~0.5 s para 400 proyectos, una sola vez
                # por sesión gracias a la huella fp. El render por lotes se
                # descartó: causaba saltos de altura y huecos en el grid.
                cards = [_mk_card(r) for r in rows]
                self._cards_cache  = cards
                self._selected_idx = -1
                self._grid.set_cards(cards)
            self._mosaico_rendered_for = rows_id
            if solo_modo is None:
                self._lista_rendered_for = None   # invalidar el otro
        else:
            self._list_view.set_rows(
                rows, self._color_cache,
                selected_pid=self._selected_pid,
                ultimo_pid=ultimo,
                totales_por_pid=totales,
            )
            self._lista_rendered_for = rows_id
            if solo_modo is None:
                self._mosaico_rendered_for = None   # invalidar el otro

        if faltan:
            self._lanzar_totales_diferidos(faltan)

    def _lanzar_totales_diferidos(self, pendientes: list):
        """Calcula totales en lotes pequeños con el event loop libre entre
        lotes: el Inicio aparece al instante y los '…' se van llenando."""
        self._tot_gen = getattr(self, '_tot_gen', 0) + 1
        gen = self._tot_gen
        cola = list(pendientes)

        def lote():
            if gen != self._tot_gen:      # el dashboard se recargó: abortar
                return
            # Si el usuario salió de Inicio (abrió un proyecto), ceder el
            # paso: un lote de proyectos grandes puede bloquear ~300 ms el
            # hilo de UI justo cuando la pestaña nueva está cargando.
            if not self.isVisible():
                QTimer.singleShot(400, lote)
                return
            hechos = []
            for _ in range(2):
                if not cola:
                    break
                pid, mod, moneda = cola.pop(0)
                try:
                    _, t = calcular_totales(pid)
                    total = float(t.get('total', 0) or 0)
                except Exception:
                    total = 0.0
                self._tot_cache[pid] = (mod, total)
                hechos.append((pid, mod, total))
                self._aplicar_total(pid, fmt(total, moneda))
            # Persistir el lote: el caché sobrevive reinicios de la app y
            # solo se recalcula un proyecto cuando su modificado_en cambia.
            if hechos:
                try:
                    conn = get_db()
                    conn.executemany(
                        "INSERT OR REPLACE INTO dashboard_tot_cache "
                        "(proyecto_id, modificado_en, total) VALUES (?,?,?)", hechos)
                    conn.commit()
                    conn.close()
                except Exception:
                    pass
            if cola:
                QTimer.singleShot(0, lote)

        QTimer.singleShot(0, lote)

    def _aplicar_total(self, pid: int, total_str: str):
        for card in (self._cards_cache or []):
            if getattr(card, 'pid', None) == pid:
                card.set_total(total_str)
                break
        it = getattr(self._list_view, '_items_total', {}).get(pid)
        if it is not None:
            try:
                it.setText(total_str)
            except RuntimeError:
                pass   # la tabla fue reconstruida; el caché ya quedó listo

    def _seleccionar_desde_lista(self, pid: int):
        """Clic en fila de lista → actualizar estado de selección global."""
        self._selected_pid = pid
        # Actualizar índice en mosaico por si vuelve
        for i, row in enumerate(self._rows_cache):
            if row['id'] == pid:
                self._selected_idx = i
                break

    def _on_estado_cambiado(self, pid: int, nuevo_estado: str):
        self._mosaico_rendered_for = None
        self._lista_rendered_for = None
        self.cargar_proyectos()

    def _seleccionar_card(self, pid: int):
        for i, card in enumerate(self._cards_cache):
            sel = card.pid == pid
            card.setSelected(sel)
            if sel:
                self._selected_idx = i
        self._selected_pid = pid
        self.setFocus()

    def _seleccionar_por_indice(self, idx: int):
        if not self._cards_cache:
            return
        idx = max(0, min(idx, len(self._cards_cache) - 1))
        card = self._cards_cache[idx]
        self._seleccionar_card(card.pid)
        # Hacer visible la tarjeta en el scroll
        self._scroll.ensureWidgetVisible(card, 20, 20)

    def keyPressEvent(self, event):
        if self._modo != "mosaico" or not self._cards_cache:
            super().keyPressEvent(event)
            return

        n    = len(self._cards_cache)
        cols = max(1, self._grid._cols)
        idx  = self._selected_idx

        key = event.key()

        if key in (Qt.Key_Right, Qt.Key_Tab):
            new_idx = 0 if idx < 0 else min(idx + 1, n - 1)
        elif key in (Qt.Key_Left, Qt.Key_Backtab):
            new_idx = 0 if idx < 0 else max(idx - 1, 0)
        elif key == Qt.Key_Down:
            new_idx = 0 if idx < 0 else min(idx + cols, n - 1)
        elif key == Qt.Key_Up:
            new_idx = 0 if idx < 0 else max(idx - cols, 0)
        elif key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            if idx >= 0:
                self._abrir_y_recordar(self._cards_cache[idx].pid)
            return
        elif key == Qt.Key_Escape:
            for card in self._cards_cache:
                card.setSelected(False)
            self._selected_idx = -1
            self._selected_pid = None
            return
        else:
            super().keyPressEvent(event)
            return

        self._seleccionar_por_indice(new_idx)
        event.accept()

    def _abrir_y_recordar(self, pid: int):
        set_ultimo_proyecto(pid)
        self.abrir_proyecto.emit(pid)

    # ── Acciones ──────────────────────────────────────────────────────────────

    def _copiar_proyecto(self, pid: int):
        conn = get_db()
        orig = conn.execute("SELECT nombre FROM proyectos WHERE id=?", (pid,)).fetchone()
        conn.close()
        if not orig:
            return
        # Diálogo: el presupuesto siempre se copia; el resto es opcional.
        dlg = _CopiarProyectoDialog(orig['nombre'], self)
        if not dlg.exec():
            return
        opts = dlg.opciones()
        conn = get_db()
        try:
            _clonar_proyecto(conn, pid, opts)
            conn.commit()
        finally:
            conn.close()
        self.cargar_proyectos()

    def _on_favorito_toggled(self, pid: int):
        self._mosaico_rendered_for = None
        self._lista_rendered_for = None
        self.cargar_proyectos()

    def _editar_proyecto(self, pid: int):
        self.editar_proyecto_solicitado.emit(pid)

    def _eliminar_proyecto(self, pid: int):
        conn = get_db()
        row = conn.execute("SELECT nombre FROM proyectos WHERE id=?", (pid,)).fetchone()
        conn.close()
        nombre = row['nombre'] if row else str(pid)

        if not _confirmar(
            self, "Eliminar proyecto",
            f"¿Eliminar el proyecto «{nombre}»?\n"
            "Se eliminarán todas sus partidas, ACUs y metrados.\n"
            "Esta acción no se puede deshacer."
        ):
            return

        conn = get_db()
        conn.execute("DELETE FROM proyectos WHERE id=?", (pid,))
        conn.commit()
        conn.close()
        self.cargar_proyectos()
