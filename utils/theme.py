# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""utils.theme — Sistema de diseño centralizado de ingePresupuestos.

Define la **única paleta**, escala de espaciado, tipografía y radios.
Las vistas deben importar de aquí en lugar de hardcodear hex codes:

    from utils.theme import C, S, R, F

donde:
    C = colores semánticos (C.brand, C.surface, C.text_primary, ...)
    S = espaciado en px        (S.xs=4, S.sm=8, S.md=12, S.lg=16, S.xl=20, S.xxl=24)
    R = border-radius           (R.sm=4, R.md=6, R.lg=8, R.xl=10, R.pill=14)
    F = tamaños de fuente       (F.xs=10, F.sm=11, F.md=12, F.lg=13, F.xl=15, F.xxl=18)

Diseño basado en Elementary OS HIG con paleta unificada (un solo naranja
marca, una sola pila de greys slate/silver).
"""
from __future__ import annotations

from types import SimpleNamespace


# ── PALETA BASE ──────────────────────────────────────────────────────────────
# Niveles de saturación: 50 (más claro) → 900 (más oscuro). Mantener estos
# como única fuente de verdad. Las constantes semánticas más abajo los usan.

# Naranja marca — UN SOLO valor. Antes había dos (#E67E22 y #F37329); ahora F37329.
ORANGE_50  = "#FEF5EB"   # fondo hover muy sutil / pills
ORANGE_100 = "#FDE8D0"   # estados ámbar suaves
ORANGE_300 = "#F9A65C"
ORANGE_500 = "#F37329"   # marca principal
ORANGE_700 = "#C0621A"   # hover, énfasis
ORANGE_900 = "#7A3800"

# Slate (azul-gris oscuro) — para texto y barras oscuras
SLATE_900  = "#1A2535"   # más oscuro (raro)
SLATE_800  = "#1F2A38"
SLATE_700  = "#273445"   # texto primario
SLATE_500  = "#485A6C"   # texto secundario / barras header
SLATE_400  = "#5C6B7A"
SLATE_300  = "#667885"   # text muted
SLATE_100  = "#95A3AB"   # text faint

# Silver (greys neutros) — para fondos, bordes
SILVER_50  = "#FBFBFC"
SILVER_100 = "#F8F9FA"   # background general
SILVER_200 = "#F0F1F2"   # cabeceras de tabla, divisores secundarios
SILVER_300 = "#D4D4D4"   # bordes principales
SILVER_500 = "#ABACAE"   # scrollbars
SILVER_700 = "#7E8087"

# Estado (semantic colors)
RED_50   = "#FEE2E2"
RED_500  = "#C6262E"     # Strawberry (Elementary)
RED_700  = "#991B1B"

GREEN_50  = "#D1FAE5"
GREEN_500 = "#68B723"    # Lime (Elementary)
GREEN_700 = "#16A34A"
GREEN_900 = "#065F46"

BLUE_50   = "#E4EEF8"
BLUE_500  = "#2563EB"
BLUE_700  = "#0D52BF"

YELLOW_500 = "#F9C440"   # Banana (Elementary) — favoritos, "reciente"

# Tipos MO/MAT/EQ — colores y fondos canónicos para badges de insumos
TIPO_MO_BG  = "#EAF5E1"; TIPO_MO_FG  = "#2E7D32"   # Verde
TIPO_MAT_BG = "#E6EFFB"; TIPO_MAT_FG = "#0D52BF"   # Azul
TIPO_EQ_BG  = "#FFF1E0"; TIPO_EQ_FG  = "#A75900"   # Ámbar
TIPO_SC_BG  = "#EFE6FB"; TIPO_SC_FG  = "#6A36B1"   # Morado (Sub-contratos/Servicios)

# Blanco
WHITE = "#FFFFFF"


# ── TOKENS SEMÁNTICOS ────────────────────────────────────────────────────────
# Estos son los que las vistas deben usar. Cambiar un color visual = cambiar
# aquí, no en 50 archivos.
C = SimpleNamespace(
    # Marca
    brand          = ORANGE_500,
    brand_hover    = ORANGE_700,
    brand_soft     = ORANGE_50,
    brand_softer   = ORANGE_100,
    brand_dark     = ORANGE_900,

    # Superficies
    bg             = SILVER_100,        # fondo general de la app
    bg_alt         = SILVER_50,         # filas alternas, hover muy sutil
    surface        = WHITE,             # cards, modales
    surface_subtle = SILVER_200,        # divisores, headers de tabla

    # Texto
    text           = SLATE_700,         # texto primario
    text_secondary = SLATE_500,         # subtítulos, headers de cards
    text_muted     = SLATE_300,         # captions, metadata
    text_faint     = SLATE_100,         # marcas de agua
    text_inverse   = WHITE,             # texto sobre fondos oscuros

    # Estados
    success        = GREEN_700,
    success_soft   = GREEN_50,
    success_dark   = GREEN_900,
    error          = RED_500,
    error_soft     = RED_50,
    error_dark     = RED_700,
    warning        = YELLOW_500,
    info           = BLUE_700,
    info_soft      = BLUE_50,

    # Bordes
    border         = SILVER_300,
    border_subtle  = SILVER_200,

    # Sidebar (oscuro)
    sidebar_bg     = SLATE_700,
    sidebar_bg_alt = SLATE_800,
    sidebar_hover  = SLATE_500,
    sidebar_text   = "#E8EDF2",
    sidebar_text_muted = SLATE_300,

    # Topbar oscuro (cronograma, gantt, metrados)
    headerbar      = SLATE_500,
    headerbar_dark = SLATE_700,

    # Tipos MO/MAT/EQ/SC
    mo_bg  = TIPO_MO_BG,  mo_fg  = TIPO_MO_FG,
    mat_bg = TIPO_MAT_BG, mat_fg = TIPO_MAT_FG,
    eq_bg  = TIPO_EQ_BG,  eq_fg  = TIPO_EQ_FG,
    sc_bg  = TIPO_SC_BG,  sc_fg  = TIPO_SC_FG,

    # Estado de proyecto
    estado_elaboracion = "#F37329",
    estado_revision    = "#F9C440",
    estado_aprobado    = GREEN_500,
    estado_ejecutado   = SLATE_500,

    # Reciente / favorito
    favorite = YELLOW_500,
    recent_bg = "#FFF9C4",
)


# ── ESPACIADO ────────────────────────────────────────────────────────────────
# Escala con steps base 2/4 + intermedios 6/10 para rítmos compactos.
# Cualquier margen/padding en la app debe ser uno de estos valores.
#
# Cuándo usar cada uno:
#   xxs (2) — separación mínima entre íconos o palabras adyacentes
#   xs  (4) — labels apilados, ítems dentro de un row pequeño
#   sm6 (6) — rítmo compacto dentro de cards (toolbars, headers de card)
#   sm  (8) — separación entre widgets relacionados en un row
#   md10(10)— alternativa a md para headers con más respiración (no tan ancho)
#   md  (12)— separación entre cards en una columna; spacing default de bodies
#   lg  (16)— márgenes de cards bien espaciadas
#   xl  (18)— márgenes top de vista (visual: respirar al inicio)
#   xxl (20)— márgenes side de vista principal (root layout)
#   xxxl(24)— separación entre secciones grandes
#   page(32)— márgenes de páginas grandes (raro)
S = SimpleNamespace(
    xxs  = 2,
    xs   = 4,
    sm6  = 6,    # compacto (header rows en cards densas)
    sm   = 8,
    md10 = 10,   # intermedio (toolbars con respiración)
    md   = 12,
    lg   = 16,
    xl   = 18,   # ⚡ margen top de vistas standalone
    xxl  = 20,   # ⚡ margen side de vistas standalone
    xxxl = 24,
    page = 32,
)


# ── BORDER RADIUS ────────────────────────────────────────────────────────────
R = SimpleNamespace(
    sm   = 4,    # botones pequeños, badges
    md   = 6,    # botones, inputs
    lg   = 8,    # cards
    xl   = 10,   # cards grandes (reportCard)
    pill = 14,   # tags de portafolio, dropdown chips
    round = 9999,
)


# ── TAMAÑOS DE FUENTE (pt para QFont; px para stylesheets QSS) ──────────────
# Qt mezcla unidades: QFont.setPointSize() usa pt (DPI-aware), QSS font-size
# usa px (a 96 DPI los pt × 1.333 ≈ px). En la app conviven los dos sistemas:
#
#   En QSS use F_PX (las px del stylesheet)         — la mayoría del UI
#   En QFont() use F (los pt para Python directo)   — títulos, KPIs, etc.
#
# Jerarquía visual real establecida en la app:
#   title  (15pt) ─ títulos de página principal
#   kpi    (14pt) ─ valores numéricos grandes de cards KPI
#   subt   (13pt) ─ subtítulos / valores destacados
#   body   (12pt) ─ texto de body, valores en tablas
#   label  (11pt) ─ labels, badges, headers de tabla
#   meta   (10pt) ─ metadata, captions
#   tiny   ( 9pt) ─ ticks de gráficos, micro-labels
F = SimpleNamespace(
    # Escala canónica original (en pt)
    xxs = 9,
    xs  = 10,
    sm  = 11,
    md  = 12,
    lg  = 13,
    xl  = 15,    # = title
    xxl = 18,    # titulares grandes
    display = 22,  # números display

    # Aliases semánticos (mismo valor, intención más clara)
    tiny  = 9,
    meta  = 10,
    label = 11,
    body  = 12,
    subt  = 13,
    kpi   = 14,    # ⚡ valores numéricos en cards KPI (recursos/biblioteca/metrados/INEI)
    title = 15,    # ⚡ títulos de página standalone
    h1    = 18,
)


# Tamaños equivalentes en px (para usar en stylesheets QSS):
# Aproximación 1pt ≈ 1.333px @ 96 DPI, pero en QSS solemos usar valores enteros
# pequeños que NO siguen esa conversión exacta. Estos son los REALES de la app:
F_PX = SimpleNamespace(
    tiny  = 9,    # ticks de gráficos en stylesheets
    meta  = 10,   # captions, badges pequeños
    label = 11,   # labels, headers de tabla (más usado: 152 veces)
    body  = 12,   # texto general (86 veces)
    subt  = 13,   # texto destacado (45 veces)
    big   = 14,   # raro, énfasis
)


# ── PESOS DE FUENTE ──────────────────────────────────────────────────────────
W = SimpleNamespace(
    normal = 400,
    medium = 500,
    semibold = 600,
    bold   = 700,
)


# ── HELPER: stylesheets canónicos ─────────────────────────────────────────────
def btn_primary(*, height: int = 32) -> str:
    """Botón primario naranja. Uso: btn.setStyleSheet(btn_primary())."""
    return (
        f"QPushButton {{ background:{C.brand}; color:{C.text_inverse}; "
        f"border:none; border-radius:{R.md}px; padding:{S.xs+2}px {S.md+2}px; "
        f"font-weight:{W.semibold}; min-height:{height - 12}px; }}"
        f"QPushButton:hover {{ background:{C.brand_hover}; }}"
        f"QPushButton:disabled {{ background:#E5E7EA; color:{C.text_faint}; }}"
    )


# Snippet pre-formateado para el caso común "botón primario de CTA en
# formularios/diálogos". Usar en lugar de copy-pastear el CSS:
#     btn.setStyleSheet(BTN_PRIMARY_SS)
# Si necesitas otra densidad (toolbar compacto), llamá btn_primary(height=…).
BTN_PRIMARY_SS = (
    f"QPushButton {{ background:{C.brand}; color:{C.text_inverse}; "
    f"border:none; border-radius:{R.md}px; padding:6px 18px; "
    f"font-size:{F_PX.body}px; font-weight:{W.semibold}; }}"
    f"QPushButton:hover {{ background:{C.brand_hover}; }}"
    f"QPushButton:disabled {{ background:#E5E7EA; color:{C.text_faint}; }}"
)


def btn_secondary(*, height: int = 32) -> str:
    """Botón secundario con borde gris y hover naranja suave."""
    return (
        f"QPushButton {{ background:{C.surface}; color:{C.text}; "
        f"border:1px solid {C.border}; border-radius:{R.md}px; "
        f"padding:{S.xs+2}px {S.md}px; min-height:{height - 12}px; }}"
        f"QPushButton:hover {{ background:{C.brand_soft}; "
        f"border-color:{C.brand}; color:{C.brand_hover}; }}"
        f"QPushButton:disabled {{ background:{C.bg}; color:{C.text_faint}; }}"
    )


def btn_ghost() -> str:
    """Botón fantasma — sin borde, hover suave. Para acciones secundarias en
    cabeceras de cards."""
    return (
        f"QPushButton {{ background:transparent; color:{C.text_secondary}; "
        f"border:none; padding:{S.xs}px {S.sm}px; }}"
        f"QPushButton:hover {{ background:{C.brand_soft}; color:{C.brand_hover}; }}"
    )


def btn_danger(*, height: int = 32) -> str:
    """Botón destructivo (eliminar). Uso restringido a confirmaciones."""
    return (
        f"QPushButton {{ background:{C.error}; color:{C.text_inverse}; "
        f"border:none; border-radius:{R.md}px; padding:{S.xs+2}px {S.md+2}px; "
        f"font-weight:{W.semibold}; min-height:{height - 12}px; }}"
        f"QPushButton:hover {{ background:{C.error_dark}; }}"
    )


def card(*, radius: int | None = None) -> str:
    """Estilo canónico de card: fondo blanco, borde gris sutil, esquinas suaves."""
    r = radius if radius is not None else R.lg
    return (
        f"QFrame {{ background:{C.surface}; border:1px solid {C.border}; "
        f"border-radius:{r}px; }}"
    )


def card_header_orange(*, radius: int = R.lg) -> str:
    """Cabecera oscura de card con esquinas redondeadas arriba — patrón muy
    usado en formulario/biblioteca/fórmula."""
    return (
        f"QFrame {{ background:{C.headerbar}; "
        f"border-radius:{radius}px {radius}px 0 0; }}"
    )


def input_default() -> str:
    """QLineEdit base: bordes suaves, focus naranja."""
    return (
        f"QLineEdit {{ background:{C.surface}; color:{C.text}; "
        f"border:1px solid {C.border}; border-radius:{R.sm}px; "
        f"padding:{S.xs+1}px {S.sm}px; selection-background-color:{C.brand_soft}; }}"
        f"QLineEdit:focus {{ border:1.5px solid {C.brand}; }}"
        f"QLineEdit:disabled {{ background:{C.bg}; color:{C.text_faint}; }}"
    )


def kpi_card() -> str:
    """Card KPI estandarizada — fondo blanco con borde y radio uniforme."""
    return (
        f"QFrame {{ background:{C.surface}; border:1px solid {C.border}; "
        f"border-radius:{R.lg}px; }}"
    )


def tag_pill(color: str, *, active: bool = False) -> str:
    """Tag tipo píldora — usado en portafolios."""
    if active:
        return (
            f"QPushButton {{ background:{color}; color:{C.text_inverse}; "
            f"border:none; border-radius:{R.pill}px; padding:0 {S.md}px; "
            f"font-size:{F.sm}px; font-weight:{W.bold}; }}"
        )
    return (
        f"QPushButton {{ background:{C.surface}; color:{color}; "
        f"border:1px solid {color}; border-radius:{R.pill}px; "
        f"padding:0 {S.md}px; font-size:{F.sm}px; font-weight:{W.semibold}; }}"
        f"QPushButton:hover {{ background:{color}; color:{C.text_inverse}; }}"
    )


# ── Compat: re-export de las constantes legacy más usadas ────────────────────
# Para no romper código existente mientras migramos vistas.
# Estos alias permiten un import gradual.
ORANGE      = ORANGE_500
ORANGE_DARK = ORANGE_700
ORANGE_SOFT = ORANGE_50


# ── Acento de color (UI + Reportes) ──────────────────────────────────────────
# El acento ambiental es slate (sobrio). Los CTAs y focus rings siguen siendo
# naranja para indicar ACCIÓN, no marca. En el futuro se podrá reintroducir un
# sistema de temas (UI + Reportes) — por ahora el sobrio es el único modo.

def accent_color(*, on_dark: bool = False) -> str:
    """Color de acento *ambiental* — slate/blanco según fondo.

    Usar en topbars, tab indicators, separadores decorativos y otros sitios
    donde el naranja "satura" cuando se repite. NO usar en CTAs (botones
    primarios), focus rings ni hover backgrounds — esos siempre deben ser
    naranja porque indican ACCIÓN, no marca.

    Args:
        on_dark: True si el accent va sobre un fondo oscuro (toolbar,
                 headerbar, sidebar) — devuelve grey claro. False (default)
                 para fondos claros — devuelve slate-700.
    """
    return '#E8EDF2' if on_dark else SLATE_700


def accent_hover(*, on_dark: bool = False) -> str:
    """Versión "hover/dark" del color de acento ambiental."""
    return WHITE if on_dark else SLATE_800


def accent_reportes() -> tuple[str, str, str]:
    """Devuelve la terna `(color, color_dark, color_soft)` para los reportes.

    Slate-700 + slate-800 + silver muy claro, para un look casi monocromo
    apto para entregas formales al cliente.
    """
    return (SLATE_700, SLATE_800, '#F1F5F9')


# ── Sombras (drop shadow) ────────────────────────────────────────────────────
# Qt no soporta `box-shadow` CSS; usamos QGraphicsDropShadowEffect.
# Solo aplicar a widgets con fondo NO transparente (cards típicas).

SHADOW_PRESETS = {
    # (blur, offset_y, alpha)
    'xs': (6,  1,  18),   # casi imperceptible (para botones primarios)
    'sm': (10, 1,  22),   # cards en flujo normal
    'md': (16, 3,  28),   # cards destacadas / modales suaves
    'lg': (24, 6,  38),   # diálogos modales / popovers
}


def apply_shadow(widget, intensity: str = 'sm', color: str | None = None):
    """Aplica un `QGraphicsDropShadowEffect` al widget con un preset.

    Args:
        widget: QWidget al que aplicar la sombra (típicamente una card QFrame).
        intensity: 'xs' | 'sm' | 'md' | 'lg' — controla blur, offset y alpha.
        color: hex de la sombra. Default: gris-azulado del tema (consistente).

    Caveats:
        - El widget debe tener fondo NO transparente (un setStyleSheet con
          background) para que la sombra se vea.
        - Solo se puede tener UN graphicsEffect por widget. Aplicar al
          contenedor más externo de la card.
        - No abusar: 50+ widgets con sombra activa puede impactar performance
          en scroll. Para listas grandes (dashboard con N proyectos) considerar
          aplicar solo a los visibles o usar dibujado custom.
    """
    from PySide6.QtWidgets import QGraphicsDropShadowEffect
    from PySide6.QtGui import QColor

    blur, offset_y, alpha = SHADOW_PRESETS.get(intensity, SHADOW_PRESETS['sm'])
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, offset_y)
    # Color neutro tirando a slate (más natural que el típico negro puro)
    c = QColor(color) if color else QColor(15, 23, 42)
    c.setAlpha(alpha)
    effect.setColor(c)
    widget.setGraphicsEffect(effect)
    return effect


# ── Layout helpers ───────────────────────────────────────────────────────────
def root_margins(layout):
    """Aplica los márgenes canónicos de root para vistas standalone.

    Patrón: (xxl, xl, xxl, lg) = (20, 18, 20, 16). Da más respiración arriba
    que abajo (el header acapara más visual peso).

    Uso:
        from utils.theme import root_margins, S
        layout = QVBoxLayout(self)
        root_margins(layout)
        layout.setSpacing(S.md)
    """
    layout.setContentsMargins(S.xxl, S.xl, S.xxl, S.lg)
    return layout


def card_margins(layout, density: str = 'normal'):
    """Aplica los márgenes canónicos para el contenido interno de cards.

    density:
        'compact' → (md, sm, md, sm) = padding ajustado
        'normal'  → (md, sm, md, md) = default
        'roomy'   → (lg, md, lg, md) = cards principales con respiración
    """
    if density == 'compact':
        layout.setContentsMargins(S.md, S.sm, S.md, S.sm)
    elif density == 'roomy':
        layout.setContentsMargins(S.lg, S.md, S.lg, S.md)
    else:
        layout.setContentsMargins(S.md, S.sm, S.md, S.md)
    return layout
