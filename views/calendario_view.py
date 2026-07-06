# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""calendario_view — Calendario de Proyectos (≈ calendario.html de Flask).

Vista Mes: grid 6×7 con barras horizontales por proyecto que cruzan los días
que abarcan (inicio = ``costo_al`` parseado, fin = inicio + ``plazo`` días).
Hitos del cronograma se dibujan como diamantes en su día.

Vista Año: 12 mini-meses con marcadores de actividad. Click en un mes
→ vista mes.

Click en una barra de proyecto → emite ``proyecto_clicked(int)`` que
MainWindow conecta para abrir el proyecto.
"""
from __future__ import annotations

import calendar
import re
from datetime import date, datetime, timedelta

from PySide6.QtCore import Qt, QSize, QRect, Signal, QPoint
from PySide6.QtGui import (
    QColor, QFont, QPainter, QPen, QBrush, QPolygon, QPainterPath,
    QFontMetrics, QPixmap, QIcon,
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton,
    QSizePolicy, QListWidget, QListWidgetItem, QToolTip,
)

from core.database import get_db
from utils.icons import icon


# ── Paleta ────────────────────────────────────────────────────────────────────
ORANGE       = "#F37329"
ORANGE_DARK  = "#C0621A"
ORANGE_SOFT  = "#FEF5EB"
SLATE_700    = "#273445"
SLATE_500    = "#485A6C"
SLATE_300    = "#667885"
SILVER_100   = "#F8F9FA"
SILVER_200   = "#F0F1F2"
SILVER_300   = "#D4D4D4"
WHITE        = "#FFFFFF"

# Paleta de colores por proyecto (rota por índice)
COLORES_PROY = [
    "#E8610A", "#2563EB", "#16A34A", "#9333EA", "#DC2626",
    "#0891B2", "#B45309", "#BE185D", "#65A30D", "#7C3AED",
]
# Colores de hito según tipo (1=genérico, 2=inicio, 3=fin)
COL_HITO = {1: "#9333EA", 2: "#2563EB", 3: "#16A34A"}

DIAS_SEMANA = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
MESES_LARGOS = [
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]
MESES_CORTOS = [m[:3] for m in MESES_LARGOS]

# Mapa de meses en español → número (acepta acentuados, may/min, ENE/Enero/etc.)
_MAPA_MESES: dict[str, int] = {}
for _i, _m in enumerate(MESES_LARGOS, 1):
    _MAPA_MESES[_m.lower()] = _i
    _MAPA_MESES[MESES_CORTOS[_i - 1].lower()] = _i
for _k_orig in list(_MAPA_MESES.keys()):
    _sin_acentos = (
        _k_orig.replace('á', 'a').replace('é', 'e').replace('í', 'i')
               .replace('ó', 'o').replace('ú', 'u')
    )
    _MAPA_MESES.setdefault(_sin_acentos, _MAPA_MESES[_k_orig])


def _parsear_costo_al(texto: str | None) -> date | None:
    """Convierte ``costo_al`` (campo libre) en una ``date`` de inicio.

    Acepta:
        - ``DD/MM/YYYY``, ``YYYY-MM-DD``, ``DD-MM-YYYY``
        - ``MM/YYYY``
        - ``MES YYYY``, ``MES - YYYY``, ``Mes de YYYY`` (en español)
    Si no parsea, retorna ``None``.
    """
    if not texto:
        return None
    t = str(texto).strip()
    if not t:
        return None

    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(t, fmt).date()
        except ValueError:
            pass
    try:
        return datetime.strptime(t, "%m/%Y").date().replace(day=1)
    except ValueError:
        pass

    m = re.search(
        r'([a-záéíóúñ]{3,})[\s\-]*(?:de(?:l)?\s+)?(\d{4})', t.lower()
    )
    if m:
        mes = _MAPA_MESES.get(m.group(1))
        if mes:
            try:
                return date(int(m.group(2)), mes, 1)
            except ValueError:
                return None
    return None


# ── Canvas del mes (QPainter) ────────────────────────────────────────────────
class _MesCanvas(QWidget):
    """Dibuja la grilla del mes con barras de proyecto y hitos."""

    proyecto_clicked = Signal(int)  # pid

    PADDING = 6
    HEADER_H = 22
    DAY_NUM_H = 20
    # Estilo "pílula plana" tipo Maya (elementary Calendar):
    # fondo translúcido del color del proyecto + texto sólido del mismo color,
    # sin barrita lateral ni borde — el color del fondo basta para identificar.
    BAR_H = 18
    BAR_GAP = 3
    BAR_INSET_X = 3
    BAR_RADIUS = 3
    BAR_BG_ALPHA = 70       # fondo translúcido pero visible (≈ Maya)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._year = date.today().year
        self._month = date.today().month
        self._eventos: list[dict] = []
        self._hitos: list[dict] = []
        self._bar_rects: list[tuple[QRect, int]] = []
        self._cell_dates: dict[tuple[int, int], date] = {}
        self.setMouseTracking(True)
        self.setMinimumHeight(560)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_mes(self, year: int, month: int):
        self._year = year
        self._month = month
        self.update()

    def set_eventos(self, eventos: list[dict], hitos: list[dict]):
        self._eventos = eventos
        self._hitos = hitos
        self.update()

    def _grid_geom(self) -> tuple[int, int, int, int]:
        x0 = self.PADDING
        y0 = self.PADDING + self.HEADER_H
        w = self.width() - 2 * self.PADDING
        h = self.height() - y0 - self.PADDING
        return x0, y0, w, h

    def _cell_geom(self, row: int, col: int) -> QRect:
        x0, y0, w, h = self._grid_geom()
        cw = w / 7
        rh = h / 6
        return QRect(int(x0 + col * cw), int(y0 + row * rh),
                     int(cw + 1), int(rh + 1))

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), QColor(WHITE))
        self._bar_rects.clear()
        self._draw_header_dias(p)
        self._draw_grid(p)
        self._draw_eventos(p)
        self._draw_hitos(p)
        p.end()

    def _draw_header_dias(self, p: QPainter):
        x0, _y0, w, _h = self._grid_geom()
        cw = w / 7
        rect = QRect(x0, self.PADDING, w, self.HEADER_H)
        # Header limpio: blanco con borde inferior sutil (antes era slate-700
        # oscuro, demasiado agresivo para una vista de consulta).
        p.fillRect(rect, QColor("#FBFBFC"))
        p.setPen(QPen(QColor(SILVER_300), 1))
        p.drawLine(rect.bottomLeft(), rect.bottomRight())

        f = QFont(); f.setBold(False); f.setPointSize(9)
        p.setFont(f)
        for i, nombre in enumerate(DIAS_SEMANA):
            r = QRect(int(x0 + i * cw), self.PADDING, int(cw), self.HEADER_H)
            # Header uniforme estilo Maya/elementary: todos los días con el
            # mismo gris, sin destacar fines de semana ni MAYÚSCULAS.
            p.setPen(QColor(SLATE_500))
            p.drawText(r, Qt.AlignCenter, nombre)

    def _draw_grid(self, p: QPainter):
        primero = date(self._year, self._month, 1)
        dia_sem = primero.weekday()  # Lunes = 0
        if self._month == 1:
            mes_ant = (self._year - 1, 12)
        else:
            mes_ant = (self._year, self._month - 1)
        ult_mes_ant = calendar.monthrange(*mes_ant)[1]
        dias_en_mes = calendar.monthrange(self._year, self._month)[1]

        f_num = QFont(); f_num.setPointSize(9); f_num.setWeight(QFont.DemiBold)
        p.setFont(f_num)
        hoy = date.today()
        self._cell_dates.clear()

        # Pre-resolver es-fin-de-semana para colorear sutilmente los sábados
        # y domingos (más limpio que el header oscuro anterior).
        for i in range(42):
            row, col = divmod(i, 7)
            cell = self._cell_geom(row, col)
            es_finde = col >= 5
            if i < dia_sem:
                d = date(*mes_ant, ult_mes_ant - dia_sem + i + 1)
                otro = True
            elif i < dia_sem + dias_en_mes:
                d = date(self._year, self._month, i - dia_sem + 1)
                otro = False
            else:
                if self._month == 12:
                    mes_sig = (self._year + 1, 1)
                else:
                    mes_sig = (self._year, self._month + 1)
                d = date(*mes_sig, i - dia_sem - dias_en_mes + 1)
                otro = True
            self._cell_dates[(row, col)] = d

            # Todas las celdas con fondo blanco uniforme — sin distinguir
            # "otro mes". El calendario se ve más limpio así.

            # Bordes muy sutiles entre celdas (eran SILVER_200 = #F0F1F2,
            # ahora un gris aún más tenue para reducir el grid visual).
            p.setPen(QPen(QColor("#EDEEEF"), 1))
            p.drawRect(cell)

            # Número de día — alineado a la derecha como en elementary
            num_rect = QRect(cell.right() - 28, cell.y() + 4, 24, self.DAY_NUM_H)
            if d == hoy:
                # Círculo amarillo suave para destacar HOY
                p.setBrush(QBrush(QColor("#FFF59D")))
                p.setPen(Qt.NoPen)
                p.drawEllipse(num_rect.right() - 22, num_rect.y(), 20, 20)
                p.setPen(QColor(SLATE_700))
                p.drawText(QRect(num_rect.right() - 22, num_rect.y(), 20, 20),
                           Qt.AlignCenter, str(d.day))
            else:
                # Mismo gris para todos los días (mes actual y "otro mes")
                # — calendario limpio sin jerarquía por mes.
                p.setPen(QColor(SLATE_500))
                p.drawText(num_rect, Qt.AlignRight | Qt.AlignVCenter,
                           str(d.day))

    def _draw_eventos(self, p: QPainter):
        if not self._eventos:
            return
        primer_dia_grid = self._cell_dates[(0, 0)]
        ultimo_dia_grid = self._cell_dates[(5, 6)]
        visibles = [e for e in self._eventos
                    if e['fin'] >= primer_dia_grid and e['inicio'] <= ultimo_dia_grid]
        visibles.sort(key=lambda e: e['inicio'])
        # Asignar tracks (greedy: reaprovecha pista cuando termina antes)
        tracks: list[date] = []
        for ev in visibles:
            asignado = -1
            for ti, ult in enumerate(tracks):
                if ult < ev['inicio']:
                    asignado = ti
                    break
            if asignado < 0:
                tracks.append(ev['fin'])
                asignado = len(tracks) - 1
            else:
                tracks[asignado] = ev['fin']
            ev['_track'] = asignado

        f_lbl = QFont(); f_lbl.setBold(True); f_lbl.setPointSize(8)
        p.setFont(f_lbl)
        fm = QFontMetrics(f_lbl)

        for ev in visibles:
            color_bg = QColor(ev['color'])
            color_bg.setAlpha(self.BAR_BG_ALPHA)
            # Texto sólido en el color del proyecto (oscurecido un poco para
            # garantizar contraste sobre el fondo translúcido).
            color_texto = QColor(ev['color']).darker(140)
            track = ev['_track']
            etiqueta_pintada = False
            for row in range(6):
                lunes = self._cell_dates[(row, 0)]
                domingo = self._cell_dates[(row, 6)]
                if ev['fin'] < lunes or ev['inicio'] > domingo:
                    continue
                col_inicio = max(0, (ev['inicio'] - lunes).days)
                col_fin = min(6, (ev['fin'] - lunes).days)

                cell_ini = self._cell_geom(row, col_inicio)
                cell_fin = self._cell_geom(row, col_fin)

                y = (cell_ini.y() + self.DAY_NUM_H + 8
                     + track * (self.BAR_H + self.BAR_GAP))
                if y + self.BAR_H > cell_ini.bottom() - 3:
                    continue

                x_ini = cell_ini.x() + self.BAR_INSET_X
                x_fin = cell_fin.right() - self.BAR_INSET_X
                w = max(8, x_fin - x_ini)
                bar_rect = QRect(x_ini, y, w, self.BAR_H)

                tiene_inicio = (ev['inicio'] >= lunes and
                                ev['inicio'] <= domingo)
                tiene_fin = (ev['fin'] >= lunes and ev['fin'] <= domingo)
                radius_l = self.BAR_RADIUS if tiene_inicio else 0
                radius_r = self.BAR_RADIUS if tiene_fin else 0

                # Pílula plana: solo fondo translúcido + texto sólido
                self._fill_round_rect(p, bar_rect, color_bg, radius_l, radius_r)

                if not etiqueta_pintada and w > 30:
                    p.setPen(color_texto)
                    elided = fm.elidedText(
                        ev['nombre'], Qt.ElideRight, w - 10
                    )
                    p.drawText(
                        bar_rect.adjusted(6, 0, -4, 0),
                        Qt.AlignVCenter | Qt.AlignLeft, elided
                    )
                    etiqueta_pintada = True

                self._bar_rects.append((QRect(bar_rect), ev['pid']))

    def _fill_round_rect(self, p: QPainter, rect: QRect, color: QColor,
                          r_left: int, r_right: int):
        """Pinta un rectángulo con esquinas redondeadas selectivas."""
        path = QPainterPath()
        path.moveTo(rect.x() + r_left, rect.y())
        # Borde superior
        path.lineTo(rect.right() - r_right, rect.y())
        if r_right > 0:
            path.quadTo(rect.right(), rect.y(),
                        rect.right(), rect.y() + r_right)
            path.lineTo(rect.right(), rect.bottom() - r_right)
            path.quadTo(rect.right(), rect.bottom(),
                        rect.right() - r_right, rect.bottom())
        else:
            path.lineTo(rect.right(), rect.bottom())
        # Borde inferior + esquina izquierda
        path.lineTo(rect.x() + r_left, rect.bottom())
        if r_left > 0:
            path.quadTo(rect.x(), rect.bottom(),
                        rect.x(), rect.bottom() - r_left)
            path.lineTo(rect.x(), rect.y() + r_left)
            path.quadTo(rect.x(), rect.y(),
                        rect.x() + r_left, rect.y())
        else:
            path.lineTo(rect.x(), rect.y())
        path.closeSubpath()
        p.fillPath(path, QBrush(color))

    def _draw_hitos(self, p: QPainter):
        if not self._hitos:
            return
        for h in self._hitos:
            d = h['fecha']
            if d.year != self._year or d.month != self._month:
                continue
            for (row, col), cd in self._cell_dates.items():
                if cd == d:
                    cell = self._cell_geom(row, col)
                    cx = cell.right() - 12
                    cy = cell.y() + 8
                    color = QColor(COL_HITO.get(h['tipo'], "#9333EA"))
                    poly = QPolygon([
                        QPoint(cx, cy - 4),
                        QPoint(cx + 4, cy),
                        QPoint(cx, cy + 4),
                        QPoint(cx - 4, cy),
                    ])
                    p.setBrush(QBrush(color))
                    p.setPen(QPen(QColor("white"), 1))
                    p.drawPolygon(poly)
                    break

    def mousePressEvent(self, ev):
        if ev.button() != Qt.LeftButton:
            return
        pos = ev.position().toPoint()
        for rect, pid in self._bar_rects:
            if rect.contains(pos):
                self.proyecto_clicked.emit(pid)
                return

    def mouseMoveEvent(self, ev):
        pos = ev.position().toPoint()
        for rect, pid in self._bar_rects:
            if rect.contains(pos):
                self.setCursor(Qt.PointingHandCursor)
                ev_data = next((e for e in self._eventos if e['pid'] == pid), None)
                if ev_data:
                    txt = (f"<b>{ev_data['nombre']}</b><br>"
                           f"{ev_data['cliente']}<br>"
                           f"{ev_data['inicio'].strftime('%d/%m/%Y')} → "
                           f"{ev_data['fin'].strftime('%d/%m/%Y')}")
                    QToolTip.showText(self.mapToGlobal(pos), txt, self)
                return
        self.unsetCursor()
        QToolTip.hideText()


# ── Vista Año (mini-meses) ───────────────────────────────────────────────────
class _AnioCanvas(QWidget):
    mes_clicked = Signal(int, int)  # year, month

    def __init__(self, parent=None):
        super().__init__(parent)
        self._year = date.today().year
        self._eventos: list[dict] = []
        self._month_rects: list[tuple[QRect, int]] = []
        self.setMouseTracking(True)
        self.setMinimumHeight(560)

    def set_anio(self, year: int):
        self._year = year
        self.update()

    def set_eventos(self, eventos: list[dict]):
        self._eventos = eventos
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), QColor(WHITE))
        self._month_rects.clear()
        cols, rows, pad, gap = 3, 4, 8, 8
        cell_w = (self.width() - 2 * pad - (cols - 1) * gap) / cols
        cell_h = (self.height() - 2 * pad - (rows - 1) * gap) / rows
        for i in range(12):
            r = i // cols
            c = i % cols
            x = int(pad + c * (cell_w + gap))
            y = int(pad + r * (cell_h + gap))
            rect = QRect(x, y, int(cell_w), int(cell_h))
            self._month_rects.append((QRect(rect), i + 1))
            self._dibujar_mini_mes(p, rect, i + 1)
        p.end()

    def _dibujar_mini_mes(self, p: QPainter, rect: QRect, mes: int):
        p.setBrush(QBrush(QColor(WHITE)))
        p.setPen(QPen(QColor(SILVER_300), 1))
        p.drawRoundedRect(rect, 6, 6)

        title = QRect(rect.x() + 8, rect.y() + 6, rect.width() - 16, 18)
        f = QFont(); f.setBold(True); f.setPointSize(10)
        p.setFont(f)
        p.setPen(QColor(SLATE_700))
        p.drawText(title, Qt.AlignLeft, MESES_LARGOS[mes - 1])

        hoy = date.today()
        es_mes_hoy = (hoy.year == self._year and hoy.month == mes)

        gx = rect.x() + 6
        gy = title.bottom() + 6
        gw = rect.width() - 12
        gh = rect.bottom() - gy - 6
        cw = gw / 7
        rh = gh / 7

        f_dn = QFont(); f_dn.setPointSize(7); f_dn.setBold(True)
        p.setFont(f_dn)
        for i, n in enumerate(["L", "M", "M", "J", "V", "S", "D"]):
            r = QRect(int(gx + i * cw), int(gy), int(cw), int(rh))
            p.setPen(QColor(SLATE_300 if i < 5 else ORANGE_DARK))
            p.drawText(r, Qt.AlignCenter, n)

        primero = date(self._year, mes, 1)
        dia_sem = primero.weekday()
        dias_en_mes = calendar.monthrange(self._year, mes)[1]

        # Días con eventos
        ult_dia = date(self._year, mes, dias_en_mes)
        dias_con_proy: set[int] = set()
        for ev in self._eventos:
            if ev['fin'] < primero or ev['inicio'] > ult_dia:
                continue
            d_ini = max(ev['inicio'], primero)
            d_fin = min(ev['fin'], ult_dia)
            d = d_ini
            while d <= d_fin:
                dias_con_proy.add(d.day)
                d += timedelta(days=1)

        f_d = QFont(); f_d.setPointSize(7)
        p.setFont(f_d)
        for d in range(1, dias_en_mes + 1):
            idx = dia_sem + d - 1
            row = idx // 7
            col = idx % 7
            x = int(gx + col * cw)
            y = int(gy + (row + 1) * rh)
            r_cell = QRect(x, y, int(cw), int(rh))
            es_hoy = (es_mes_hoy and d == hoy.day)
            if es_hoy:
                p.setBrush(QBrush(QColor(ORANGE)))
                p.setPen(Qt.NoPen)
                cx = int(x + cw / 2); cy = int(y + rh / 2)
                rad = max(6, int(min(cw, rh) / 2 - 1))
                p.drawEllipse(cx - rad, cy - rad, rad * 2, rad * 2)
                p.setPen(QColor("white"))
                p.drawText(r_cell, Qt.AlignCenter, str(d))
            elif d in dias_con_proy:
                p.setPen(QColor(SLATE_700))
                p.drawText(r_cell, Qt.AlignCenter, str(d))
                p.setBrush(QBrush(QColor(ORANGE)))
                p.setPen(Qt.NoPen)
                p.drawEllipse(int(x + cw / 2 - 1.5), int(y + rh - 4), 3, 3)
            else:
                p.setPen(QColor(SLATE_500))
                p.drawText(r_cell, Qt.AlignCenter, str(d))

    def mousePressEvent(self, ev):
        if ev.button() != Qt.LeftButton:
            return
        pos = ev.position().toPoint()
        for rect, mes in self._month_rects:
            if rect.contains(pos):
                self.mes_clicked.emit(self._year, mes)
                return

    def mouseMoveEvent(self, ev):
        pos = ev.position().toPoint()
        for rect, _ in self._month_rects:
            if rect.contains(pos):
                self.setCursor(Qt.PointingHandCursor)
                return
        self.unsetCursor()


# ── Vista principal ──────────────────────────────────────────────────────────
class CalendarioView(QWidget):
    """Calendario navegable con vista Mes y Año."""

    proyecto_clicked = Signal(int)
    volver = Signal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setProperty("vista_nombre", "calendario")
        self._vista = "mes"
        hoy = date.today()
        self._year = hoy.year
        self._month = hoy.month
        self._eventos: list[dict] = []
        self._hitos: list[dict] = []
        self._build()
        self.cargar()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(12)

        # Topbar
        top = QHBoxLayout()
        top.setSpacing(10)

        ico_t = QLabel()
        ico_t.setPixmap(icon("calendario").pixmap(28, 28))
        top.addWidget(ico_t)

        title = QLabel("Calendario de Proyectos")
        f = QFont(); f.setPointSize(15); f.setWeight(QFont.DemiBold)
        title.setFont(f)
        title.setStyleSheet(f"color:{SLATE_700};")
        top.addWidget(title)
        top.addStretch(1)

        # Toggle Mes / Año
        self.btn_mes = QPushButton("Mes")
        self.btn_anio = QPushButton("Año")
        for b, v in ((self.btn_mes, "mes"), (self.btn_anio, "anio")):
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setMinimumHeight(30)
            b.setStyleSheet(
                f"QPushButton {{ background:{WHITE}; color:{SLATE_700};"
                f"  border:1px solid {SILVER_300}; padding:4px 14px;"
                f"  font-weight:500; }}"
                f"QPushButton:hover {{ background:{ORANGE_SOFT};"
                f"  border-color:{ORANGE}; color:{ORANGE_DARK}; }}"
                f"QPushButton:checked {{ background:{ORANGE}; color:white;"
                f"  border-color:{ORANGE_DARK}; font-weight:600; }}"
            )
            b.clicked.connect(lambda _=False, vista=v: self._set_vista(vista))
        self.btn_mes.setChecked(True)
        top.addWidget(self.btn_mes)
        top.addWidget(self.btn_anio)
        root.addLayout(top)

        # Toolbar de navegación — limpia, sobre fondo blanco con borde sutil
        nav = QFrame()
        nav.setStyleSheet(
            f"QFrame {{ background:{WHITE};"
            f"  border:1px solid {SILVER_300};"
            f"  border-bottom:none;"
            f"  border-radius:6px 6px 0 0; }}"
        )
        nl = QHBoxLayout(nav)
        nl.setContentsMargins(12, 8, 12, 8)
        nl.setSpacing(6)

        self.btn_hoy = QPushButton("Hoy")
        self.btn_hoy.setCursor(Qt.PointingHandCursor)
        self.btn_hoy.setStyleSheet(
            f"QPushButton {{ background:{WHITE}; color:{SLATE_700};"
            f" border:1px solid {SILVER_300}; border-radius:6px;"
            f" padding:4px 14px; font-size:11px; font-weight:600; }}"
            f"QPushButton:hover {{ background:{ORANGE_SOFT};"
            f" border-color:{ORANGE}; color:{ORANGE_DARK}; }}"
        )
        self.btn_hoy.clicked.connect(self._ir_hoy)
        nl.addWidget(self.btn_hoy)

        self.btn_prev = QPushButton("‹")
        self.btn_next = QPushButton("›")
        for b in (self.btn_prev, self.btn_next):
            b.setCursor(Qt.PointingHandCursor)
            b.setFixedWidth(32)
            b.setStyleSheet(
                f"QPushButton {{ background:{WHITE}; color:{SLATE_500};"
                f" border:1px solid {SILVER_300}; border-radius:6px;"
                f" font-size:18px; padding:0; font-weight:bold; }}"
                f"QPushButton:hover {{ background:{ORANGE_SOFT};"
                f" border-color:{ORANGE}; color:{ORANGE_DARK}; }}"
            )
        self.btn_prev.clicked.connect(lambda: self._navegar(-1))
        self.btn_next.clicked.connect(lambda: self._navegar(1))
        nl.addWidget(self.btn_prev)

        self.lbl_titulo = QLabel("—")
        f2 = QFont(); f2.setPointSize(13); f2.setBold(True)
        self.lbl_titulo.setFont(f2)
        self.lbl_titulo.setStyleSheet(f"color:{SLATE_700};")
        self.lbl_titulo.setAlignment(Qt.AlignCenter)
        self.lbl_titulo.setMinimumWidth(180)
        nl.addWidget(self.lbl_titulo, 1)

        nl.addWidget(self.btn_next)
        root.addWidget(nav)

        # Body: canvas + sidebar
        body = QHBoxLayout()
        body.setSpacing(12)
        body.setContentsMargins(0, 0, 0, 0)

        canvas_frame = QFrame()
        canvas_frame.setStyleSheet(
            f"QFrame {{ background:{WHITE}; border:1px solid {SILVER_300};"
            f"  border-top:none; border-radius:0 0 6px 6px; }}"
        )
        cf_layout = QVBoxLayout(canvas_frame)
        cf_layout.setContentsMargins(0, 0, 0, 0)
        cf_layout.setSpacing(0)

        self.mes_canvas = _MesCanvas()
        self.mes_canvas.proyecto_clicked.connect(self.proyecto_clicked.emit)
        cf_layout.addWidget(self.mes_canvas)

        self.anio_canvas = _AnioCanvas()
        self.anio_canvas.mes_clicked.connect(self._on_mes_clicked)
        self.anio_canvas.setVisible(False)
        cf_layout.addWidget(self.anio_canvas)

        body.addWidget(canvas_frame, 7)

        body.addWidget(self._build_sidebar(), 3)
        root.addLayout(body, 1)

    def _build_sidebar(self) -> QWidget:
        side = QFrame()
        side.setStyleSheet(
            f"QFrame {{ background:{SILVER_100}; border:1px solid {SILVER_300};"
            f"  border-radius:6px; }}"
        )
        v = QVBoxLayout(side)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(10)

        # Tarjeta de proyectos
        card_proy = QFrame()
        card_proy.setStyleSheet(
            f"QFrame {{ background:{WHITE}; border:1px solid {SILVER_300};"
            f"  border-radius:6px; }}"
        )
        cv = QVBoxLayout(card_proy)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)
        ph = QFrame()
        ph.setStyleSheet(f"background:{SLATE_700};")
        phl = QHBoxLayout(ph); phl.setContentsMargins(10, 6, 10, 6); phl.setSpacing(6)
        ico_p = QLabel(); ico_p.setPixmap(icon("folder").pixmap(14, 14))
        ico_p.setStyleSheet("background:transparent; border:none;")
        phl.addWidget(ico_p)
        ttl_p = QLabel("Proyectos")
        ttl_p.setStyleSheet(
            "color:white; font-weight:600; font-size:12px;"
            " background:transparent; border:none;"
        )
        phl.addWidget(ttl_p)
        phl.addStretch(1)
        cv.addWidget(ph)

        self.lst_proy = QListWidget()
        self.lst_proy.setStyleSheet(
            "QListWidget { border:none; background:white; }"
            "QListWidget::item { padding:6px 8px; border-bottom:1px solid #F0F1F2; }"
            "QListWidget::item:hover { background:#FEF5EB; }"
        )
        self.lst_proy.setMinimumHeight(220)
        self.lst_proy.setMaximumHeight(320)
        self.lst_proy.itemClicked.connect(self._on_lst_proy_click)
        cv.addWidget(self.lst_proy)

        v.addWidget(card_proy)

        # Tarjeta de leyenda
        card_leg = QFrame()
        card_leg.setStyleSheet(
            f"QFrame {{ background:{WHITE}; border:1px solid {SILVER_300};"
            f"  border-radius:6px; }}"
        )
        lv = QVBoxLayout(card_leg)
        lv.setContentsMargins(10, 8, 10, 8)
        lv.setSpacing(6)
        ttl_l = QLabel("Referencias")
        f = QFont(); f.setBold(True)
        ttl_l.setFont(f)
        ttl_l.setStyleSheet(f"color:{SLATE_700};")
        lv.addWidget(ttl_l)
        for color, txt in (
            ("#3689E6", "Barra de duración del proyecto"),
            (COL_HITO[1], "Hito genérico"),
            (COL_HITO[2], "Hito de inicio"),
            (COL_HITO[3], "Hito de fin"),
        ):
            row = QHBoxLayout()
            dot = QLabel()
            dot.setFixedSize(12, 12)
            dot.setStyleSheet(f"background:{color}; border-radius:2px;")
            row.addWidget(dot)
            l = QLabel(txt)
            l.setStyleSheet(f"color:{SLATE_500}; font-size:11px;")
            row.addWidget(l, 1)
            lv.addLayout(row)
        v.addWidget(card_leg)

        tip = QLabel(
            "<b>Tip:</b> haz clic en una barra de proyecto para abrirlo.<br>"
            "Para que aparezca, el proyecto debe tener <b>Costo a</b> y "
            "<b>Plazo</b> configurados."
        )
        tip.setWordWrap(True)
        tip.setStyleSheet(f"color:{SLATE_300}; font-size:11px; padding:4px 2px;")
        tip.setTextFormat(Qt.RichText)
        v.addWidget(tip)
        v.addStretch(1)
        return side

    # ── Carga de datos ──────────────────────────────────────────────────────
    def cargar(self):
        conn = get_db()
        proys = conn.execute(
            "SELECT id, nombre, costo_al, plazo, cliente "
            "FROM proyectos ORDER BY creado_en DESC"
        ).fetchall()

        eventos: list[dict] = []
        hitos: list[dict] = []
        for i, p in enumerate(proys):
            color = COLORES_PROY[i % len(COLORES_PROY)]
            inicio = _parsear_costo_al(p['costo_al'])
            if not inicio:
                continue
            plazo = int(p['plazo'] or 60)
            fin = inicio + timedelta(days=plazo)
            eventos.append({
                'pid':     p['id'],
                'nombre':  p['nombre'] or '',
                'cliente': p['cliente'] or '',
                'inicio':  inicio,
                'fin':     fin,
                'color':   color,
            })

            try:
                hits = conn.execute(
                    "SELECT cp.inicio_dia, cp.es_hito, p.descripcion, p.item "
                    "FROM cronograma_partidas cp "
                    "JOIN partidas p ON p.id = cp.partida_id "
                    "WHERE p.proyecto_id=? AND cp.es_hito > 0 "
                    "AND cp.inicio_dia > 0",
                    (p['id'],)
                ).fetchall()
                for h in hits:
                    hitos.append({
                        'pid':    p['id'],
                        'fecha':  inicio + timedelta(days=int(h['inicio_dia']) - 1),
                        'tipo':   int(h['es_hito']),
                        'nombre': h['descripcion'] or '',
                        'item':   h['item'] or '',
                    })
            except Exception:
                pass
        conn.close()

        self._eventos = eventos
        self._hitos = hitos

        self._poblar_sidebar()
        self._refrescar_canvas()
        self._actualizar_titulo()

    def _poblar_sidebar(self):
        self.lst_proy.clear()
        if not self._eventos:
            it = QListWidgetItem("Sin proyectos con fecha")
            it.setForeground(QColor(SLATE_300))
            it.setFlags(Qt.NoItemFlags)
            self.lst_proy.addItem(it)
            return
        for ev in self._eventos:
            txt = ev['nombre'][:60]
            sub = ev['cliente'][:40] if ev['cliente'] else ''
            display = f"{txt}\n  {sub}" if sub else txt
            it = QListWidgetItem(display)
            it.setData(Qt.UserRole, ev['pid'])
            it.setData(Qt.UserRole + 1, ev['inicio'])
            it.setForeground(QColor(SLATE_700))
            it.setFont(QFont("Ubuntu Sans", 9))
            # Dot coloreado como icono
            pix = QPixmap(10, 10)
            pix.fill(Qt.transparent)
            p = QPainter(pix)
            p.setRenderHint(QPainter.Antialiasing)
            p.setBrush(QBrush(QColor(ev['color'])))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(0, 0, 10, 10, 2, 2)
            p.end()
            it.setIcon(QIcon(pix))
            self.lst_proy.addItem(it)

    def _on_lst_proy_click(self, item: QListWidgetItem):
        d = item.data(Qt.UserRole + 1)
        if isinstance(d, date):
            self._year = d.year
            self._month = d.month
            self._set_vista("mes")

    # ── Navegación ──────────────────────────────────────────────────────────
    def _navegar(self, delta: int):
        if self._vista == "mes":
            self._month += delta
            if self._month < 1:
                self._month = 12; self._year -= 1
            elif self._month > 12:
                self._month = 1; self._year += 1
        else:
            self._year += delta
        self._refrescar_canvas()
        self._actualizar_titulo()

    def _ir_hoy(self):
        hoy = date.today()
        self._year = hoy.year
        self._month = hoy.month
        self._refrescar_canvas()
        self._actualizar_titulo()

    def _set_vista(self, vista: str):
        self._vista = vista
        self.btn_mes.setChecked(vista == "mes")
        self.btn_anio.setChecked(vista == "anio")
        self.mes_canvas.setVisible(vista == "mes")
        self.anio_canvas.setVisible(vista == "anio")
        self._refrescar_canvas()
        self._actualizar_titulo()

    def _on_mes_clicked(self, year: int, mes: int):
        self._year = year
        self._month = mes
        self._set_vista("mes")

    def _refrescar_canvas(self):
        if self._vista == "mes":
            self.mes_canvas.set_mes(self._year, self._month)
            self.mes_canvas.set_eventos(self._eventos, self._hitos)
        else:
            self.anio_canvas.set_anio(self._year)
            self.anio_canvas.set_eventos(self._eventos)

    def _actualizar_titulo(self):
        if self._vista == "mes":
            self.lbl_titulo.setText(
                f"{MESES_LARGOS[self._month - 1]} {self._year}"
            )
        else:
            self.lbl_titulo.setText(str(self._year))
