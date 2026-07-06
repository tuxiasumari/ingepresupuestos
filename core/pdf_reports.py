# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""Generación nativa de reportes PDF con QTextDocument + QPdfWriter.

Diseño profesional Elementary OS:
- Portada con marca y datos del proyecto
- Encabezado con banda naranja en cada página
- Tablas con filas alternadas y bordes finos
- Pie con paginación, nombre del proyecto y fecha
- Tipografía limpia (system sans-serif)

Tipos de reporte:
- presupuesto       — listado de partidas + totales
- acus              — análisis de costos unitarios por partida
- insumos           — insumos consolidados del proyecto
- resumen_ejecutivo — 1 página: KPIs + distribución MO/MAT/EQ + top 5
- completo          — todos los anteriores en un solo PDF
"""
from __future__ import annotations

import io
import os
from datetime import datetime
from html import escape
from typing import Optional

from PySide6.QtCore import QBuffer, QIODevice, QMarginsF, QRectF, QSizeF, Qt
from PySide6.QtGui import (
    QBrush, QColor, QFont, QFontMetrics, QPageLayout, QPageSize, QPainter,
    QPdfWriter, QPen, QTextDocument,
)

from core.database import (
    calcular_totales, get_acu_items, get_config, get_db,
    get_decimales_ppto, get_decimales_metrado, get_insumos_proyecto, set_config, _orden_mo,
)
from utils.formatting import fmt as _fmt_money

# ── Configuración de formato (editable por el usuario) ───────────────────────
# Las claves se leen desde la tabla `configuracion`; los defaults aquí abajo se
# usan si no hay valor guardado.
FORMATO_CLAVES = {
    'rep_empresa_nombre':   'ingePresupuestos',
    'rep_empresa_subtitulo':'Sistema de Presupuestos de Obra Pública',
    'rep_color_marca':      '#F37329',
    'rep_color_marca_dk':   '#C0621A',
    'rep_logo_b64':         '',         # PNG en base64 (sin prefijo data:)
    'rep_pie_izquierdo':    '',         # texto opcional adicional en pie
    'rep_pie_central':      '',         # si vacío, usa fecha
    'rep_pie_derecho':      '',         # si vacío, usa "Página X de N"
}


def get_formato() -> dict:
    """Lee la configuración de formato — devuelve dict con todos los campos."""
    out = {}
    for k, default in FORMATO_CLAVES.items():
        out[k] = get_config(k, default) or default
    return out


def set_formato(formato: dict):
    """Persiste la configuración de formato."""
    for k in FORMATO_CLAVES:
        if k in formato:
            set_config(k, formato[k] or '')

# ── Paleta Elementary OS ──────────────────────────────────────────────────────
ORANGE       = "#F37329"
ORANGE_DARK  = "#C0621A"
ORANGE_SOFT  = "#FEF5EB"
SLATE_900    = "#1F2A38"
SLATE_700    = "#2E3C52"
SLATE_500    = "#485A6C"
SLATE_300    = "#94A3B8"
SLATE_100    = "#E2E8F0"
SILVER_50    = "#FAFBFC"
SILVER_100   = "#F8F9FA"
WHITE        = "#FFFFFF"

MO_COLOR  = "#F39C12"   # ámbar
MAT_COLOR = "#27AE60"   # verde
EQ_COLOR  = "#607D8B"   # gris
SC_COLOR  = "#7A36B1"   # morado (Sub-contratos / Servicios)

# ── Helpers ──────────────────────────────────────────────────────────────────

def _fmt(v, dec=2) -> str:
    """Formatea número con separador de miles, sin símbolo de moneda."""
    try:
        n = float(v or 0)
    except (TypeError, ValueError):
        return "0.00"
    return f"{n:,.{dec}f}"


def _proyecto_info(pid: int) -> dict:
    conn = get_db()
    row = conn.execute("SELECT * FROM proyectos WHERE id=?", (pid,)).fetchone()
    conn.close()
    return dict(row) if row else {}


def _moneda_simbolo(moneda: str) -> str:
    from core.config import moneda_cfg
    return moneda_cfg(moneda)['simbolo']


# ── Número a letras (español, formato peruano de obras) ──────────────────────

_UNIDADES = [
    '', 'uno', 'dos', 'tres', 'cuatro', 'cinco', 'seis', 'siete', 'ocho',
    'nueve', 'diez', 'once', 'doce', 'trece', 'catorce', 'quince',
    'dieciséis', 'diecisiete', 'dieciocho', 'diecinueve'
]
_DECENAS = ['', '', 'veinte', 'treinta', 'cuarenta', 'cincuenta',
            'sesenta', 'setenta', 'ochenta', 'noventa']
_CENTENAS = ['', 'ciento', 'doscientos', 'trescientos', 'cuatrocientos',
             'quinientos', 'seiscientos', 'setecientos', 'ochocientos',
             'novecientos']


def _hasta_999(n: int) -> str:
    if n == 0:    return ''
    if n == 100:  return 'cien'
    s = []
    c, r = divmod(n, 100)
    if c:
        s.append(_CENTENAS[c])
    if r < 20:
        if r:
            s.append(_UNIDADES[r])
    else:
        d, u = divmod(r, 10)
        if u == 0:
            s.append(_DECENAS[d])
        else:
            s.append(f'{_DECENAS[d]} y {_UNIDADES[u]}')
    return ' '.join(s).strip()


def _entero_a_letras(n: int) -> str:
    if n == 0:
        return 'cero'
    if n < 0:
        return 'menos ' + _entero_a_letras(-n)
    millones, resto = divmod(n, 1_000_000)
    miles, unidades = divmod(resto, 1_000)
    out = []
    if millones:
        if millones == 1:
            out.append('un millón')
        else:
            out.append(f'{_hasta_999(millones)} millones')
    if miles:
        if miles == 1:
            out.append('mil')
        else:
            grp = _hasta_999(miles)
            # "veintiuno mil" → "veintiún mil" (apocope)
            grp = grp.replace('veintiuno', 'veintiún').replace(' uno', ' un')
            out.append(f'{grp} mil')
    if unidades:
        grp = _hasta_999(unidades)
        out.append(grp)
    return ' '.join(out).strip()


def _monto_en_letras(monto: float, moneda: str = 'Soles') -> str:
    """Convierte un monto a letras con formato peruano:
    'CIENTO OCHENTA Y UN MIL TRESCIENTOS CON 28/100 SOLES'
    """
    try:
        m = float(monto or 0)
    except (TypeError, ValueError):
        m = 0.0
    entero = int(m)
    centavos = int(round((m - entero) * 100))
    if centavos >= 100:
        entero += 1
        centavos -= 100
    letras = _entero_a_letras(entero).upper()
    # Nombres de moneda en plural
    plural = {
        'Soles': 'SOLES',
        'Dólares': 'DÓLARES AMERICANOS',
        'Euros': 'EUROS',
        'Reales': 'REALES',
        'Pesos Argentinos': 'PESOS ARGENTINOS',
        'Guaraníes': 'GUARANÍES',
        'Pesos Uruguayos': 'PESOS URUGUAYOS',
        'Pesos Mexicanos': 'PESOS MEXICANOS',
    }.get(moneda, str(moneda).upper())
    return f"{letras} CON {centavos:02d}/100 {plural}"


def _hoy_formateado() -> str:
    return datetime.now().strftime('%d/%m/%Y')


def _clean_costo_al(val) -> str:
    """Devuelve el `costo_al` sin la parte de hora.
    Acepta: 'Enero 2026', '2026-05-12', '2026-05-12 00:00:00', '12/05/26 00:00:00'.
    Strip trailing time HH:MM(:SS) si está presente."""
    import re
    s = str(val or '').strip()
    if not s:
        return '—'
    # Quitar trailing " HH:MM" o " HH:MM:SS"
    s = re.sub(r'\s+\d{1,2}:\d{2}(?::\d{2})?\s*$', '', s)
    return s or '—'


# ══════════════════════════════════════════════════════════════════════════════
# Plantilla HTML — estilos comunes
# ══════════════════════════════════════════════════════════════════════════════

def _brand_colors() -> tuple[str, str, str]:
    """Lee el toggle 'Reportes sobrios' y devuelve (color, dark, soft).

    Wrapper local sobre `utils.theme.accent_reportes()` para no
    importar utils desde core (mantiene dependencia core→utils sin
    inverso). Cada llamador debe invocar esto al inicio del render
    en vez de usar las constantes ORANGE/ORANGE_DARK/ORANGE_SOFT del
    módulo (que quedan solo como fallback en caso de error).
    """
    try:
        from utils.theme import accent_reportes
        return accent_reportes()
    except Exception:
        return (ORANGE, ORANGE_DARK, ORANGE_SOFT)


def _base_css() -> str:
    """CSS común a todos los HTML de reportes. Función (no constante)
    para que respete el toggle 'Reportes sobrios' en tiempo real sin
    requerir reiniciar la app."""
    o, od, os_ = _brand_colors()
    return f"""
<style>
  body {{
    font-family: 'Inter', 'DejaVu Sans', 'Segoe UI', Arial, sans-serif;
    color: {SLATE_900};
    font-size: 9pt;
  }}
  h1, h2, h3 {{ margin: 0; padding: 0; }}
  h1 {{ font-size: 22pt; color: {SLATE_900}; font-weight: 700; }}
  h2 {{
    font-size: 13pt; color: {od}; font-weight: 700;
    margin-top: 14pt; margin-bottom: 6pt;
    border-bottom: 2pt solid {o};
    padding-bottom: 2pt;
  }}
  h3 {{
    font-size: 11pt; color: {SLATE_700}; font-weight: 700;
    margin-top: 10pt; margin-bottom: 4pt;
  }}
  p   {{ margin: 0 0 4pt 0; }}
  table {{
    border-collapse: collapse; width: 100%;
    font-size: 8.5pt;
  }}
  /* Cabecera de tabla — sin fondo, solo borde inferior grueso color marca */
  table.data th {{
    background: white; color: {SLATE_900};
    padding: 5pt 6pt; text-align: left;
    font-weight: 700; font-size: 8pt;
    border-top: 0.5pt solid {SLATE_300};
    border-bottom: 1.5pt solid {o};
    border-left: 0.4pt solid {SLATE_100};
    border-right: 0.4pt solid {SLATE_100};
  }}
  table.data td {{
    padding: 4pt 6pt; border: 0.4pt solid {SLATE_100};
    vertical-align: top;
  }}
  /* Alternancia muy suave (gris casi imperceptible — tinta mínima) */
  table.data tr.alt td {{ background: #FBFBFC; }}
  /* Spacer entre secciones — sin borde, solo aire */
  table.data tr.spacer td {{
    background: white; border: none; padding: 0;
  }}
  /* Columnas numéricas: más padding horizontal para que los montos de
     columnas contiguas (Metrado/Precio/Parcial) no queden pegados cuando
     ambos son números anchos. */
  table.data td.r {{
    text-align: right; font-variant-numeric: tabular-nums;
    padding-left: 12pt; padding-right: 16pt;
  }}
  table.data td.c {{ text-align: center; }}
  /* Títulos jerárquicos — sin fondo oscuro, solo bordes y peso de texto */
  /* Colores de fuente por nivel = espejo del programa (NIVEL_ESTILO en
     proyecto_view.py): N1 rojo, N2 arándano, N3 morado, N4 rosa. */
  table.data tr.titulo1 td {{
    background: white; color: #B71C1C;
    font-weight: 700; font-size: 9.5pt;
    padding-top: 10pt; padding-bottom: 5pt;
    border-top: 1.5pt solid {SLATE_700};
    border-bottom: 0.8pt solid {SLATE_700};
    text-transform: uppercase; letter-spacing: 0.5pt;
    text-decoration: underline;
  }}
  table.data tr.titulo2 td {{
    background: white; color: #0D52BF;
    font-weight: 700; font-size: 9pt;
    padding-top: 8pt; padding-bottom: 4pt;
    border-top: 0.5pt solid {SLATE_300};
  }}
  table.data tr.titulo3 td {{
    background: white; color: #6A1B9A;
    font-weight: 700; font-size: 8.8pt;
    padding-top: 7pt; padding-bottom: 4pt;
  }}
  table.data tr.titulo4 td {{
    background: white; color: #AD1457;
    font-weight: 700; font-size: 8.6pt;
    padding-top: 6pt; padding-bottom: 4pt;
  }}
  table.data tr.titulo5 td {{
    background: white; color: #92400E;
    font-weight: 700; font-size: 8.5pt; font-style: italic;
    padding-top: 6pt; padding-bottom: 4pt;
  }}
  table.totales td {{
    padding: 5pt 8pt; font-size: 9.5pt;
    border-top: 0.5pt solid {SLATE_300};
  }}
  table.totales td.lbl {{ font-weight: 600; text-align: right; color: {SLATE_700}; }}
  table.totales td.val {{ text-align: right; font-variant-numeric: tabular-nums; }}
  /* Total general — sin fondo de marca, solo bordes dobles y texto bold */
  table.totales tr.gran td {{
    background: white; color: {od};
    font-weight: 700; font-size: 12pt;
    border-top: 2pt solid {o};
    border-bottom: 2pt solid {o};
  }}
  table.totales tr.sub td {{
    background: white; color: {SLATE_900};
    font-weight: 700;
    border-top: 0.6pt solid {SLATE_500};
    border-bottom: 0.6pt solid {SLATE_300};
  }}
  /* Pills MO/MAT/EQ — outline en lugar de relleno (colores semánticos
     que NO siguen el modo sobrio — son datos, no decoración) */
  .pill {{
    display: inline-block; padding: 0pt 5pt; border-radius: 6pt;
    font-size: 7.5pt; font-weight: 700; background: white;
  }}
  .pill-mo  {{ color: {MO_COLOR};  border: 0.8pt solid {MO_COLOR}; }}
  .pill-mat {{ color: {MAT_COLOR}; border: 0.8pt solid {MAT_COLOR}; }}
  .pill-eq  {{ color: {EQ_COLOR};  border: 0.8pt solid {EQ_COLOR}; }}
  .pill-sc  {{ color: {SC_COLOR};  border: 0.8pt solid {SC_COLOR}; }}
  .meta {{
    color: {SLATE_500}; font-size: 9pt;
  }}
  .meta b {{ color: {SLATE_900}; }}
  table.meta-info td {{ padding: 2pt 6pt 2pt 0; vertical-align: top; }}
  table.meta-info td.k {{
    color: {SLATE_500}; font-style: italic;
    width: 110pt; white-space: nowrap;
  }}
  table.meta-info td.v {{ color: {SLATE_900}; font-weight: 600; }}
  .kpi-grid td {{
    padding: 8pt; border: 0.6pt solid {SLATE_100};
    vertical-align: top;
  }}
  .kpi-label {{
    color: {SLATE_500}; font-size: 8pt;
    text-transform: uppercase; letter-spacing: 0.5pt;
    margin-bottom: 2pt;
  }}
  .kpi-value {{
    color: {SLATE_900}; font-size: 14pt; font-weight: 700;
  }}
  .kpi-sub {{ color: {SLATE_500}; font-size: 8pt; margin-top: 2pt; }}
  .acu-card {{
    border-left: 3pt solid {o}; padding-left: 8pt;
    margin: 10pt 0 6pt 0;
  }}
  .acu-titulo {{ font-size: 10pt; font-weight: 700; color: {SLATE_900}; }}
  .acu-meta {{ font-size: 8.5pt; color: {SLATE_500}; }}
  /* Wrap completo de ACU — bordes en gris (el color queda solo en el texto) */
  table.acu-wrap {{ margin: 18pt 0 28pt 0; width: 100%; }}
  table.acu-wrap td.acu-head {{
    border-left:   1pt solid {SLATE_700};
    border-right:  1pt solid {SLATE_700};
    border-top:    1pt solid {SLATE_700};
    padding: 8pt 10pt;
    background: {os_};
  }}
  table.acu-wrap td.acu-body {{
    border-left:   1pt solid {SLATE_700};
    border-right:  1pt solid {SLATE_700};
    border-bottom: 1pt solid {SLATE_700};
    padding: 0 10pt 10pt 10pt;
  }}
  hr.thin {{
    border: none; border-top: 0.4pt solid {SLATE_100};
    margin: 6pt 0;
  }}
  .pagebreak {{ page-break-before: always; }}
</style>
"""


# NOTA: `_BASE_CSS` ya no existe como constante. Los call sites llaman
# directamente a `_base_css()` para que el CSS se re-genere en cada
# render y respete el toggle 'Reportes sobrios' en runtime.


# ══════════════════════════════════════════════════════════════════════════════
# Generadores HTML por tipo de reporte
# ══════════════════════════════════════════════════════════════════════════════

def _html_meta_proyecto(proy: dict) -> str:
    """Tabla de información del proyecto (cliente, ubicación, fechas, moneda)."""
    rows = [
        ("Proyecto",       proy.get('nombre') or '—'),
        ("Sub-presupuesto", proy.get('sub_presupuesto') or '—'),
        ("Cliente",        proy.get('cliente') or '—'),
        ("Ubicación",      proy.get('ubicacion') or '—'),
        ("Costo al",       proy.get('costo_al') or '—'),
        ("Plazo",          f"{proy.get('plazo') or 0} días calendario"),
        ("Modalidad",      proy.get('modalidad') or 'Contrata'),
        ("Moneda",         f"{proy.get('moneda') or 'Soles'} ({_moneda_simbolo(proy.get('moneda') or 'Soles')})"),
    ]
    body = "".join(
        f'<tr><td class="k">{escape(k)}</td><td class="v">{escape(str(v))}</td></tr>'
        for k, v in rows
    )
    return f'<table class="meta-info">{body}</table>'


def _html_presupuesto(pid: int, proy: dict, items: list, totales: dict, *,
                     incluir_meta=True, todo_costo=False) -> str:
    sym = _moneda_simbolo(proy.get('moneda') or 'Soles')
    dec = get_decimales_ppto()
    _o_hp, _od_hp, _os_hp = _brand_colors()

    # «Precio cerrado»: mayora cada PU/parcial por el factor que disuelve
    # GG + utilidad, y reemplaza el pie por su versión reducida (Sub Total +
    # IGV + Total), ocultando el desglose de costos. factor=1 en modo normal.
    factor = 1.0
    pie_override = None
    if todo_costo:
        factor, pie_override = _todo_costo_factor_pie(
            pid, totales.get('cd', 0) or 0)

    parts = []
    if incluir_meta:
        parts.append('<h2>Presupuesto</h2>')

    # Tabla de partidas
    rows = []
    # Mapa nivel → altura del spacer en pt (más respiro para niveles altos,
    # estilo PowerCost: las divisiones mayores tienen gap visible antes)
    _spacer_h = {1: 7, 2: 6, 3: 5, 4: 4, 5: 4}
    # Contador propio de filas-partida (ignora títulos) para zebra CONTINUO.
    # QTextDocument ignora `tr.alt td { background }` del CSS, por eso
    # aplicamos `style="background:..."` INLINE en cada `<td>` de partidas.
    partida_idx = 0
    # Profundidad para los tabs de la columna Descripción: relativa al ítem más
    # superficial (replica la sangría del árbol on-screen, que usa el
    # anidamiento real por puntos del ítem). El campo `nivel` está topeado en 4,
    # así que NO sirve para indentar partidas profundas → se usa el código.
    _dots = [(it['partida'].get('item') or '').count('.') for it in items]
    _min_dots = min(_dots) if _dots else 0
    # Sangría colgante por nivel en la Descripción. QTextDocument ignora
    # `padding-left`/`margin-left` de la celda (ver gotcha) y un prefijo de
    # `&nbsp;` solo sangra la 1ª línea (las partidas largas envuelven feo). La
    # técnica fiable es una TABLA-ESPACIADOR anidada: una col de ancho fijo +
    # la col del texto → todas las líneas envueltas quedan indentadas.
    _IND_PX = 16   # ancho del espaciador por nivel de profundidad

    def _ind(depth, html_inner):
        if depth <= 0:
            return html_inner
        return (
            '<table border="0" cellspacing="0" cellpadding="0" width="100%"><tr>'
            f'<td width="{depth * _IND_PX}" '
            'style="border:none;padding:0;background:transparent"></td>'
            '<td style="border:none;padding:0;background:transparent">'
            f'{html_inner}</td></tr></table>'
        )

    for i, entry in enumerate(items):
        p = entry['partida']
        total = entry['total']
        nivel = p.get('nivel', 1)
        es_titulo = p.get('es_titulo', 0)
        _depth = max(0, (p.get('item') or '').count('.') - _min_dots)

        if es_titulo:
            if nivel == 1:
                cls = "titulo1"
            elif nivel == 2:
                cls = "titulo2"
            elif nivel == 3:
                cls = "titulo3"
            elif nivel == 4:
                cls = "titulo4"
            else:
                cls = "titulo5"
            row_bg_inline = ""
        else:
            zebra = (partida_idx % 2 == 1)
            partida_idx += 1
            cls = ""
            row_bg_inline = 'background:#FBFCFD;' if zebra else ''

        if es_titulo:
            desc = escape(p.get("descripcion") or "")
            item_txt = escape(p.get("item") or "")
            if nivel == 1:
                desc = f'<u>{desc}</u>'
                item_txt = f'<u>{item_txt}</u>'
            # Fila espaciadora antes del título — solo si el anterior NO es
            # nuestro padre directo. Si soy "01.01" justo después de "01"
            # (su primer hijo), no quiero gap; pero si soy un hermano o
            # vengo después de una partida, sí.
            necesita_spacer = False
            if i > 0:
                prev = items[i - 1]['partida']
                prev_titulo = bool(prev.get('es_titulo'))
                prev_nivel = prev.get('nivel', 1)
                # No spacer solo cuando el anterior es título de nivel menor
                # (mi padre directo). En cualquier otro caso → spacer.
                if not (prev_titulo and prev_nivel < nivel):
                    necesita_spacer = True
            if necesita_spacer:
                h = _spacer_h.get(nivel, 7)
                rows.append(
                    f'<tr class="spacer"><td colspan="6" '
                    f'style="border:none;background:white;'
                    f'font-size:{h}pt;line-height:{h}pt">&nbsp;</td></tr>'
                )
            rows.append(
                f'<tr class="{cls}">'
                f'<td>{item_txt}</td>'
                f'<td colspan="4">{_ind(_depth, desc)}</td>'
                f'<td class="r">{_fmt(total * factor, dec)}</td>'
                f'</tr>'
            )
        else:
            # bg inline en cada td — QTextDocument ignora `tr.alt td { bg }`.
            sty = f' style="{row_bg_inline}"' if row_bg_inline else ''
            rows.append(
                f'<tr class="{cls}">'
                f'<td{sty}>{escape(p.get("item") or "")}</td>'
                f'<td{sty}>{_ind(_depth, escape(p.get("descripcion") or ""))}</td>'
                f'<td class="c"{sty}>{escape(p.get("unidad") or "")}</td>'
                f'<td class="r"{sty}>{_fmt(p.get("metrado"), get_decimales_metrado())}</td>'
                f'<td class="r"{sty}>{_fmt((p.get("precio_unitario") or 0) * factor, dec)}</td>'
                f'<td class="r"{sty}>{_fmt(total * factor, dec)}</td>'
                f'</tr>'
            )

    parts.append(
        # width="100%" inline OBLIGATORIO — sin esto, QTextDocument calcula el
        # ancho de la tabla en base al contenido y las descripciones largas
        # de partidas terminan clipeadas al borde derecho de la página.
        # Header con bg accent_soft (espejo del card header de ACU). Marco
        # quiere que la fila Ítem · Descripción · ... esté con el gris suave
        # para que actúe como divisor visual antes de los datos.
        '<table class="data" width="100%">'
        '<thead><tr>'
        f'<th style="width:48pt;background:{_os_hp}">Ítem</th>'
        f'<th style="background:{_os_hp}">Descripción</th>'
        f'<th style="width:40pt;text-align:center;background:{_os_hp}">Und</th>'
        f'<th style="width:70pt;text-align:right;background:{_os_hp}">Cantidad</th>'
        f'<th style="width:88pt;text-align:right;background:{_os_hp}">Precio</th>'
        f'<th style="width:94pt;text-align:right;background:{_os_hp}">Parcial</th>'
        '</tr></thead>'
        f'<tbody>{"".join(rows)}</tbody>'
        '</table>'
    )

    # Pie de presupuesto — refleja exactamente el pie configurado en la
    # pestaña «Pie» del proyecto (lee `pie_rubros` activos + `gastos_generales`).
    # En modo «precio cerrado» se usa el pie reducido (Sub Total + IGV + Total).
    if pie_override is not None:
        pie_rows = pie_override
    else:
        pie_rows = _build_pie_rows(pid, totales.get('cd', 0) or 0)
    tot_html = []
    for label, val, cls in pie_rows:
        tot_html.append(
            f'<tr class="{cls}">'
            f'<td class="lbl">{escape(label)}</td>'
            f'<td class="val" style="width:120pt">{sym} {_fmt(val, dec)}</td>'
            f'</tr>'
        )
    # Separación clara entre la tabla de partidas y el pie
    parts.append('<p style="margin-top:28pt">&nbsp;</p>')
    parts.append(
        '<table class="totales" align="right" width="55%">'
        f'{"".join(tot_html)}</table>'
    )
    # Monto total en letras — debajo del pie, alineado a la derecha
    total_letras = _monto_en_letras(totales.get('total', 0) or 0,
                                     proy.get('moneda') or 'Soles')
    parts.append('<p style="margin-top:18pt">&nbsp;</p>')
    parts.append(
        f'<p align="right" style="margin-top:0;font-style:italic;'
        f' color:{SLATE_700};font-size:9.5pt">'
        f'Son: {escape(total_letras)}.</p>'
    )
    return "\n".join(parts)


def _html_acus(pid: int, proy: dict, items: list) -> str:
    o, od, _os = _brand_colors()
    sym = _moneda_simbolo(proy.get('moneda') or 'Soles')
    dec = get_decimales_ppto()
    conn = get_db()

    parts = ['<h2>Análisis de Costos Unitarios</h2>']

    cnt = 0
    for entry in items:
        p = entry['partida']
        if p.get('es_titulo'):
            continue
        cnt += 1
        acu_items, totales_tipo = get_acu_items(conn, p['id'])
        cu = sum(totales_tipo.values())

        # Encabezado de la partida — dentro del wrap (usar <p> con margins
        # explícitos para evitar colapso de altura en QTextDocument)
        rendimiento = p.get('rendimiento') or 0
        head_html = (
            f'<p style="margin:0 0 4pt 0;font-size:10pt;font-weight:700;color:{SLATE_900}">'
            f'{escape(p.get("item") or "")} &nbsp; {escape(p.get("descripcion") or "")}</p>'
            f'<p style="margin:0;font-size:8.5pt;color:{SLATE_500}">'
            f'Unidad: <b>{escape(p.get("unidad") or "—")}</b> &nbsp;·&nbsp; '
            f'Rendimiento: <b>{_fmt(rendimiento, 2) if rendimiento else "—"} {p.get("unidad") or ""}/día</b> &nbsp;·&nbsp; '
            f'Costo Unit.: <b>{sym} {_fmt(cu, dec)}</b>'
            f'</p>'
        )

        if not acu_items:
            parts.append(
                f'<table class="acu-wrap" cellspacing="0" cellpadding="0" width="100%">'
                f'<tr><td class="acu-head">{head_html}</td></tr>'
                f'<tr><td class="acu-body">'
                f'<p style="color:{SLATE_300};font-style:italic;font-size:8.5pt;margin:6pt 0">'
                'Sin recursos definidos.</p>'
                f'</td></tr></table>'
                '<p style="margin:0;font-size:16pt">&nbsp;</p>'
            )
            continue

        rows = []
        for j, it in enumerate(acu_items):
            tipo = it.get('tipo') or 'MAT'
            pill_cls = {'MO': 'pill-mo', 'MAT': 'pill-mat',
                        'EQ': 'pill-eq', 'SC': 'pill-sc'}.get(tipo, 'pill-mat')
            cls = "alt" if (j % 2) else ""
            rows.append(
                f'<tr class="{cls}">'
                f'<td><span class="pill {pill_cls}">{escape(tipo)}</span></td>'
                f'<td>{escape(it.get("descripcion") or "")}</td>'
                f'<td class="c">{escape(it.get("unidad") or "")}</td>'
                f'<td class="r">{_fmt(it.get("cuadrilla"), 4)}</td>'
                f'<td class="r">{_fmt(it.get("cantidad"), 6)}</td>'
                f'<td class="r">{_fmt(it.get("precio"), dec)}</td>'
                f'<td class="r">{_fmt(it.get("parcial"), dec)}</td>'
                f'</tr>'
            )
        # Subtotales por tipo
        sub_rows = []
        for k, label in [('MO', 'Mano de obra'), ('MAT', 'Materiales'),
                         ('EQ', 'Equipos'), ('SC', 'Sub-contratos')]:
            v = totales_tipo.get(k, 0)
            if v:
                sub_rows.append(
                    f'<tr style="background:white;border-top:1pt solid {o}">'
                    f'<td colspan="6" class="r" style="font-weight:600;color:{SLATE_700}">'
                    f'{escape(label)}</td>'
                    f'<td class="r" style="font-weight:600">{_fmt(v, dec)}</td>'
                    f'</tr>'
                )
        sub_rows.append(
            f'<tr style="background:white;color:{od}">'
            f'<td colspan="6" class="r" style="font-weight:700;'
            f' border-top:1.5pt solid {o};border-bottom:1.5pt solid {o}">'
            f'COSTO UNITARIO TOTAL</td>'
            f'<td class="r" style="font-weight:700;'
            f' border-top:1.5pt solid {o};border-bottom:1.5pt solid {o}">'
            f'{_fmt(cu, dec)}</td>'
            f'</tr>'
        )

        # Anchos como atributo HTML width="N%" en cada <th> — QTextDocument
        # respeta el atributo HTML pero IGNORA style="table-layout:fixed" y
        # mezcla auto-layout cuando ve `style="width:Xpt"`. Con porcentajes
        # sumando 100% sobre `<table width="100%">`, el engine reparte
        # exactamente las mismas proporciones en cada partida → todas las
        # tablas ACU quedan alineadas verticalmente entre partidas.
        data_table = (
            '<table class="data" width="100%">'
            '<thead><tr>'
            '<th width="7%">Tipo</th>'
            '<th width="38%">Recurso</th>'
            '<th width="7%" align="center">Und</th>'
            '<th width="10%" align="right">Cuadrilla</th>'
            '<th width="12%" align="right">Cantidad</th>'
            '<th width="12%" align="right">Precio</th>'
            '<th width="14%" align="right">Parcial</th>'
            '</tr></thead>'
            f'<tbody>{"".join(rows)}{"".join(sub_rows)}</tbody>'
            '</table>'
        )

        parts.append(
            f'<table class="acu-wrap" cellspacing="0" cellpadding="0" width="100%">'
            f'<tr><td class="acu-head">{head_html}</td></tr>'
            f'<tr><td class="acu-body">{data_table}</td></tr>'
            f'</table>'
            '<p style="margin:0;font-size:16pt">&nbsp;</p>'
        )

    if cnt == 0:
        parts.append('<p style="color:#888;font-style:italic">No hay partidas con ACU.</p>')

    conn.close()
    return "\n".join(parts)


def _html_metrados(pid: int, proy: dict, items: list) -> str:
    o, od, _os = _brand_colors()
    """Hoja de metrados — detalle por partida con metrados_detalle / acero_detalle."""
    conn = get_db()
    parts = ['<h2>Hoja de Metrados</h2>']

    cnt = 0
    for entry in items:
        p = entry['partida']
        if p.get('es_titulo'):
            continue
        # Detalle estándar
        detalles = conn.execute(
            "SELECT * FROM metrados_detalle WHERE partida_id=? ORDER BY orden, id",
            (p['id'],)
        ).fetchall()
        # Detalle de acero (exclusión mutua)
        aceros = conn.execute(
            "SELECT * FROM acero_detalle WHERE partida_id=? ORDER BY orden, id",
            (p['id'],)
        ).fetchall()

        # Mostrar la partida si tiene planilla, acero, O metrado directo (manual)
        if not detalles and not aceros and not (p.get('metrado') or 0):
            continue
        cnt += 1

        # Usar <p> con márgenes explícitos en lugar de <div>s — QTextDocument
        # respeta mejor la altura de párrafos y evita que el header colapse
        head_html = (
            f'<p style="margin:0 0 4pt 0;font-size:10pt;font-weight:700;color:{SLATE_900}">'
            f'{escape(p.get("item") or "")} &nbsp; {escape(p.get("descripcion") or "")}</p>'
            f'<p style="margin:0;font-size:8.5pt;color:{SLATE_500}">'
            f'Unidad: <b>{escape(p.get("unidad") or "—")}</b> &nbsp;·&nbsp; '
            f'Metrado total: <b>{_fmt(p.get("metrado"), get_decimales_metrado())}</b>'
            f'</p>'
        )

        if aceros:
            # Tabla de acero
            rows = []
            total_kg = 0.0
            for j, a in enumerate(aceros):
                a = dict(a)
                cls = "alt" if (j % 2) else ""
                parcial = a.get('parcial') or 0
                total_kg += parcial
                rows.append(
                    f'<tr class="{cls}">'
                    f'<td>{escape(a.get("descripcion") or "")}</td>'
                    f'<td class="c">{escape(a.get("diametro") or "")}</td>'
                    f'<td class="r">{_fmt(a.get("n_veces"), 0)}</td>'
                    f'<td class="r">{_fmt(a.get("n_elementos"), 0)}</td>'
                    f'<td class="r">{_fmt(a.get("longitud"), 4)}</td>'
                    f'<td class="r">{_fmt(a.get("kg_ml"), 4)}</td>'
                    f'<td class="r">{_fmt(parcial, 4)}</td>'
                    f'</tr>'
                )
            rows.append(
                f'<tr style="background:white;border-top:1pt solid {SLATE_700}">'
                f'<td colspan="6" class="r" style="font-weight:700;color:{od}">Total acero (kg)</td>'
                f'<td class="r" style="font-weight:700;color:{od}">{_fmt(total_kg, 4)}</td>'
                f'</tr>'
            )
            # Anchos como atributo HTML width="N%" — único patrón que
            # QTextDocument respeta para mantener columnas alineadas
            # verticalmente cuando hay varias tablas seguidas (una por
            # partida). Ver `[[feedback_qtextdoc_table_width]]`.
            data_table = (
                '<table class="data" width="100%">'
                '<thead><tr>'
                '<th width="25%">Descripción</th>'
                '<th width="11%" align="center">Ø</th>'
                '<th width="12%" align="right">Veces</th>'
                '<th width="12%" align="right">N° elem.</th>'
                '<th width="13%" align="right">Longitud</th>'
                '<th width="12%" align="right">kg/m</th>'
                '<th width="15%" align="right">Parcial</th>'
                '</tr></thead>'
                f'<tbody>{"".join(rows)}</tbody></table>'
            )
        else:
            rows = []
            total = 0.0
            # Fallback: metrado ingresado manualmente sin planilla → fila
            # sintética con el valor en "N° elem" (mismo criterio que la vista
            # de proyecto: el árbol guarda el metrado en partidas.metrado)
            if not detalles and (p.get('metrado') or 0):
                detalles = [{
                    'descripcion': 'Metrado directo',
                    'n_estructuras': None,
                    'n_elementos': p.get('metrado') or 0,
                    'area': None, 'largo': None, 'ancho': None, 'alto': None,
                    'parcial': p.get('metrado') or 0,
                }]
            for j, d in enumerate(detalles):
                d = dict(d)
                cls = "alt" if (j % 2) else ""
                parcial = d.get('parcial') or 0
                total += parcial
                rows.append(
                    f'<tr class="{cls}">'
                    f'<td>{escape(d.get("descripcion") or "")}</td>'
                    f'<td class="r">{_fmt(d.get("n_estructuras"), 2) if d.get("n_estructuras") else ""}</td>'
                    f'<td class="r">{_fmt(d.get("n_elementos"), 2) if d.get("n_elementos") else ""}</td>'
                    f'<td class="r">{_fmt(d.get("area"), 4) if d.get("area") else ""}</td>'
                    f'<td class="r">{_fmt(d.get("largo"), 4) if d.get("largo") else ""}</td>'
                    f'<td class="r">{_fmt(d.get("ancho"), 4) if d.get("ancho") else ""}</td>'
                    f'<td class="r">{_fmt(d.get("alto"), 4) if d.get("alto") else ""}</td>'
                    f'<td class="r">{_fmt(parcial, 2)}</td>'
                    f'</tr>'
                )
            rows.append(
                f'<tr style="background:white;border-top:1pt solid {SLATE_700}">'
                f'<td colspan="7" class="r" style="font-weight:700;color:{od}">'
                f'Total &nbsp;({escape(p.get("unidad") or "")})</td>'
                f'<td class="r" style="font-weight:700;color:{od}">{_fmt(total, 2)}</td>'
                f'</tr>'
            )
            # Idem: porcentajes vía atributo HTML para alineación entre
            # partidas. 6 columnas numéricas a 11% + Descripción 22% +
            # Parcial 12% = 100%.
            data_table = (
                '<table class="data" width="100%">'
                '<thead><tr>'
                '<th width="22%">Descripción</th>'
                '<th width="11%" align="right">N° estr.</th>'
                '<th width="11%" align="right">N° elem.</th>'
                '<th width="11%" align="right">Área</th>'
                '<th width="11%" align="right">Largo</th>'
                '<th width="11%" align="right">Ancho</th>'
                '<th width="11%" align="right">Alto</th>'
                '<th width="12%" align="right">Parcial</th>'
                '</tr></thead>'
                f'<tbody>{"".join(rows)}</tbody></table>'
            )

        parts.append(
            f'<table class="acu-wrap" cellspacing="0" cellpadding="0" width="100%">'
            f'<tr><td class="acu-head">{head_html}</td></tr>'
            f'<tr><td class="acu-body">{data_table}</td></tr>'
            f'</table>'
            '<p style="margin:0;font-size:16pt">&nbsp;</p>'
        )

    if cnt == 0:
        parts.append('<p style="color:#888;font-style:italic">No hay partidas con detalle de metrados.</p>')

    conn.close()
    return "\n".join(parts)


def _procesar_cuerpo_html_spec(spec: str) -> str:
    """Procesa el cuerpo HTML (specs/memoria): justifica párrafos, convierte
    los guiones de viñeta en «•» y limita el tamaño de las imágenes. Si no es
    HTML, lo envuelve en un párrafo justificado. Mismo criterio que las
    especificaciones técnicas."""
    import re
    if '<' in spec and '>' in spec:
        body = spec

        def _strip_text_align(s):
            return re.sub(r'\btext-align\s*:\s*[a-z]+\s*;?\s*', '', s, flags=re.IGNORECASE)

        def _add_justify(match):
            tag = match.group(1)
            attrs = match.group(2) or ''
            m_align = re.search(r'\balign\s*=\s*"([^"]+)"', attrs, re.IGNORECASE)
            ya_alineado = m_align and m_align.group(1).lower() in ('center', 'right')
            if 'style="' in attrs.lower():
                def _fix_style(sm):
                    s = _strip_text_align(sm.group(1))
                    if ya_alineado:
                        return f'style="{s};line-height:1.5"'
                    return f'style="{s};text-align:justify;line-height:1.5"'
                attrs = re.sub(r'style="([^"]*)"', _fix_style, attrs, count=1, flags=re.IGNORECASE)
            else:
                extra = 'line-height:1.5' if ya_alineado else 'text-align:justify;line-height:1.5'
                attrs = f' style="{extra}"' + attrs
            if not ya_alineado and not re.search(r'\balign\s*=', attrs, re.IGNORECASE):
                attrs = ' align="justify"' + attrs
            return f'<{tag}{attrs}>'

        body = re.sub(r'<(p|div)((?:\s[^>]*)?)\s*>', _add_justify, body, flags=re.IGNORECASE)
        body = re.sub(r'(<(?:p|div|li)[^>]*>)\s*[-–]\s+', r'\1•  ', body, flags=re.IGNORECASE)

        def _limit_img(mm):
            tag = mm.group(0)
            tag = re.sub(r' width="([0-9]+)"',
                         lambda x: f' width="{min(int(x.group(1)), 380)}"',
                         tag, flags=re.IGNORECASE)
            tag = re.sub(r' height="([0-9]+)"',
                         lambda x: f' height="{min(int(x.group(1)), 280)}"',
                         tag, flags=re.IGNORECASE)
            if not re.search(r'\swidth=', tag, re.IGNORECASE):
                tag = tag.replace('<img', '<img width="380"', 1)
            return tag
        body = re.sub(r'<img[^>]+>', _limit_img, body, flags=re.IGNORECASE)
        return body
    return (f'<p align="justify" style="text-align:justify;line-height:1.5">'
            f'{escape(spec).replace(chr(10), "<br/>")}</p>')


def strip_titulo_memoria(memo: str) -> str:
    """Quita un título «MEMORIA DESCRIPTIVA» al inicio del contenido.

    La IA redacta la memoria comenzando con ese encabezado, pero el reporte
    ya pone su propio título (portada/encabezado en PDF, header + título en
    Word) → saldría dos veces. Esto lo elimina tanto en contenido HTML como
    en texto plano, sin tocar el resto.
    """
    import re
    if not memo:
        return memo
    s = memo.lstrip()
    norm = lambda t: re.sub(r'\s+', ' ', re.sub(
        r'[^a-záéíóúñ ]', '', re.sub(r'<[^>]+>', '', t), flags=re.I)
    ).strip().lower()
    # HTML: primer bloque <p>/<h1-6>/<div> cuyo texto sea «memoria descriptiva»
    m = re.match(r'\s*<(p|h[1-6]|div)\b[^>]*>(.*?)</\1>', s,
                 flags=re.I | re.S)
    if m and norm(m.group(2)) == 'memoria descriptiva':
        return s[m.end():].lstrip()
    # Texto plano: primera línea no vacía
    lineas = s.split('\n')
    for i, ln in enumerate(lineas):
        if not ln.strip():
            continue
        if norm(ln) == 'memoria descriptiva':
            return '\n'.join(lineas[i + 1:]).lstrip()
        break
    return memo


def _html_memoria_descriptiva(pid: int, proy: dict) -> str:
    """Memoria descriptiva del proyecto — un documento HTML procesado con el
    mismo estilo (viñetas/justificado) que las especificaciones técnicas."""
    memo = (proy.get('memoria_descriptiva') or '').strip()
    if not memo:
        from core.database import get_db
        conn = get_db()
        row = conn.execute(
            "SELECT memoria_descriptiva FROM proyectos WHERE id=?", (pid,)
        ).fetchone()
        conn.close()
        memo = ((row['memoria_descriptiva'] if row else '') or '').strip()
    # Título del documento — centrado y grande, espejo del de Word/ODT (la
    # portada lo lleva aparte; este encabeza el cuerpo del reporte).
    _o, od, _os = _brand_colors()
    titulo = (f'<p align="center" style="color:{od};font-size:18pt;'
              f'font-weight:bold;margin-bottom:14pt">MEMORIA DESCRIPTIVA</p>')
    if not memo:
        return (titulo + '<p style="color:#888;font-style:italic">'
                'Este proyecto aún no tiene memoria descriptiva. '
                'Genérala en la pestaña «Memoria» del proyecto.</p>')
    return titulo + _procesar_cuerpo_html_spec(strip_titulo_memoria(memo))


def _chunk_especificacion_partida(p: dict, spec: str) -> str:
    """Construye el HTML de UNA partida (encabezado + cuerpo procesado).
    Lo usa tanto el renderizado tradicional como el chunked (paginación atómica)."""
    import re
    o, od, _os = _brand_colors()
    is_titulo = bool(p.get('es_titulo'))
    nivel = p.get('nivel') or 1
    if is_titulo and nivel == 1:
        color, weight, sz, border = SLATE_900, '700', '12pt', f'2pt solid {SLATE_700}'
    elif is_titulo:
        color, weight, sz, border = SLATE_700, '700', '11pt', f'1pt solid {SLATE_500}'
    else:
        color, weight, sz, border = od, '700', '11pt', f'1.5pt solid {o}'

    head_html = (
        f'<div style="background:white;color:{color};padding:6pt 0;'
        f'border-bottom:{border};font-size:{sz};font-weight:{weight}">'
        f'{escape(p.get("item") or "")} &nbsp; '
        f'{escape(p.get("descripcion") or "")}'
        f'</div>'
        f'<p style="margin:0;font-size:10pt">&nbsp;</p>'
    )

    if '<' in spec and '>' in spec:
        body = spec

        def _strip_text_align(s):
            return re.sub(r'\btext-align\s*:\s*[a-z]+\s*;?\s*', '', s, flags=re.IGNORECASE)

        def _add_justify(match):
            tag = match.group(1)
            attrs = match.group(2) or ''
            m_align = re.search(r'\balign\s*=\s*"([^"]+)"', attrs, re.IGNORECASE)
            ya_alineado = m_align and m_align.group(1).lower() in ('center', 'right')
            if 'style="' in attrs.lower():
                def _fix_style(sm):
                    s = _strip_text_align(sm.group(1))
                    if ya_alineado:
                        return f'style="{s};line-height:1.5"'
                    return f'style="{s};text-align:justify;line-height:1.5"'
                attrs = re.sub(r'style="([^"]*)"', _fix_style, attrs, count=1, flags=re.IGNORECASE)
            else:
                extra = 'line-height:1.5' if ya_alineado else 'text-align:justify;line-height:1.5'
                attrs = f' style="{extra}"' + attrs
            if not ya_alineado and not re.search(r'\balign\s*=', attrs, re.IGNORECASE):
                attrs = ' align="justify"' + attrs
            return f'<{tag}{attrs}>'

        body = re.sub(r'<(p|div)((?:\s[^>]*)?)\s*>', _add_justify, body, flags=re.IGNORECASE)
        body = re.sub(r'(<(?:p|div|li)[^>]*>)\s*[-–]\s+', r'\1•  ', body, flags=re.IGNORECASE)

        def _limit_img(mm):
            tag = mm.group(0)
            tag = re.sub(r' width="([0-9]+)"',
                         lambda x: f' width="{min(int(x.group(1)), 380)}"',
                         tag, flags=re.IGNORECASE)
            tag = re.sub(r' height="([0-9]+)"',
                         lambda x: f' height="{min(int(x.group(1)), 280)}"',
                         tag, flags=re.IGNORECASE)
            if not re.search(r'\swidth=', tag, re.IGNORECASE):
                tag = tag.replace('<img', '<img width="380"', 1)
            return tag
        body = re.sub(r'<img[^>]+>', _limit_img, body, flags=re.IGNORECASE)
        cuerpo = body
    else:
        cuerpo = (
            f'<p align="justify" style="text-align:justify;line-height:1.5">'
            f'{escape(spec).replace(chr(10), "<br/>")}</p>'
        )

    return head_html + cuerpo


def chunks_especificaciones(pid: int, proy: dict, items: list) -> list[str]:
    """Devuelve una lista de fragmentos HTML, uno por partida con
    especificación. Cada fragmento es atómico — el renderer chunked lo
    coloca completo en una página, sin partirlo (evita los gaps de
    QTextDocument cuando una imagen no cabe en el espacio restante)."""
    chunks = []
    for entry in items:
        p = dict(entry['partida'])
        spec = (p.get('especificaciones') or '').strip()
        if not spec:
            continue
        chunks.append(_chunk_especificacion_partida(p, spec))
    return chunks


def _html_especificaciones(pid: int, proy: dict, items: list) -> str:
    """Hoja de especificaciones técnicas — bloques HTML por partida.
    Versión single-blob (usada por reporte 'completo'; el reporte
    'especificaciones' standalone usa renderizado chunked atómico)."""
    parts = ['<h2>Especificaciones Técnicas</h2>']
    cnt = 0
    primer = True
    for entry in items:
        p = dict(entry['partida'])
        spec = (p.get('especificaciones') or '').strip()
        if not spec:
            continue
        cnt += 1
        if not primer:
            parts.append('<p style="margin:0;font-size:28pt">&nbsp;</p>')
        primer = False
        parts.append(_chunk_especificacion_partida(p, spec))

    if cnt == 0:
        parts.append('<p style="color:#888;font-style:italic">'
                     'No hay especificaciones técnicas registradas en este proyecto.</p>')
    return "\n".join(parts)


def _png_curva_s_b64(periodos: list[float], acum_pct: list[float], *,
                     etiqueta_x: str = 'Semana',
                     width: int = 560, height: int = 280) -> str:
    """Renderiza una curva S (avance acumulado %) como PNG embebible."""
    import base64
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPolygonF, QBrush
    o, od, _os = _brand_colors()

    img = QImage(width * 2, height * 2, QImage.Format_ARGB32)
    img.fill(Qt.white)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.Antialiasing, True)

    # Márgenes (en coordenadas 2x)
    ml, mr, mt, mb = 80, 50, 30, 70
    plot_w = width * 2 - ml - mr
    plot_h = height * 2 - mt - mb
    plot_l = ml
    plot_t = mt
    plot_r = ml + plot_w
    plot_b = mt + plot_h

    n = max(1, len(acum_pct))

    # Fondo grilla
    painter.setPen(QPen(QColor("#E2E8F0"), 1, Qt.DashLine))
    for i in range(0, 11):
        y = plot_b - (i / 10) * plot_h
        painter.drawLine(int(plot_l), int(y), int(plot_r), int(y))
    for i in range(0, n + 1):
        x = plot_l + (i / max(1, n)) * plot_w
        painter.drawLine(int(x), int(plot_t), int(x), int(plot_b))

    # Ejes principales
    painter.setPen(QPen(QColor("#475569"), 2))
    painter.drawLine(int(plot_l), int(plot_t), int(plot_l), int(plot_b))
    painter.drawLine(int(plot_l), int(plot_b), int(plot_r), int(plot_b))

    # Etiquetas Y (porcentaje)
    f = QFont('Inter', 16)
    painter.setFont(f)
    painter.setPen(QColor("#475569"))
    for i in range(0, 11, 2):
        y = plot_b - (i / 10) * plot_h
        painter.drawText(QRectF(20, y - 12, ml - 30, 24),
                         Qt.AlignRight | Qt.AlignVCenter, f"{i*10}%")

    # Etiquetas X (períodos)
    step = max(1, n // 12)
    for i in range(0, n, step):
        x = plot_l + ((i + 1) / max(1, n)) * plot_w
        painter.drawText(QRectF(x - 30, plot_b + 10, 60, 20),
                         Qt.AlignCenter, str(i + 1))
    # Título eje X
    f_t = QFont('Inter', 16); f_t.setItalic(True)
    painter.setFont(f_t)
    painter.setPen(QColor("#94A3B8"))
    painter.drawText(QRectF(plot_l, plot_b + 36, plot_w, 24),
                     Qt.AlignCenter, etiqueta_x)

    # Trazado de la curva (relleno)
    if n > 0:
        pts = []
        for i, v in enumerate(acum_pct):
            x = plot_l + ((i + 1) / max(1, n)) * plot_w
            y = plot_b - max(0, min(100, v)) / 100 * plot_h
            pts.append(QPointF(x, y))
        # Punto inicial en (plot_l, plot_b) para área
        area = QPolygonF([QPointF(plot_l, plot_b)] + pts + [QPointF(pts[-1].x(), plot_b)])
        painter.setPen(Qt.NoPen)
        # Área translúcida bajo la curva — derivada del color de marca
        _fill = QColor(o); _fill.setAlpha(60)
        painter.setBrush(QBrush(_fill))
        painter.drawPolygon(area)
        # Línea (más oscura para mejor contraste sobre el área translúcida)
        painter.setPen(QPen(QColor(od), 4))
        painter.setBrush(Qt.NoBrush)
        for i in range(len(pts) - 1):
            painter.drawLine(pts[i], pts[i + 1])
        # Puntos (color de marca pleno)
        painter.setBrush(QBrush(QColor(o)))
        painter.setPen(QPen(QColor("white"), 2))
        for p in pts:
            painter.drawEllipse(p, 5, 5)

    painter.end()

    img = img.scaled(width, height, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    b64 = bytes(ba.toBase64()).decode('ascii')
    return f'<img src="data:image/png;base64,{b64}" width="{width}" height="{height}"/>'


def _non_working_set_for(proy: dict, n_dias: int) -> set:
    """Conjunto de días corridos (1..n_dias) no laborables — espejo de
    `CronogramaView._non_working_set`. Vacío si `salta_no_laborables=0`."""
    if int(proy.get('salta_no_laborables', 1) or 0) == 0:
        return set()
    from datetime import datetime, timedelta
    try:
        fi = proy.get('fecha_inicio', '') or proy.get('costo_al', '')
        if not fi:
            return set()
        f_ini = datetime.strptime(fi, '%Y-%m-%d')
    except Exception:
        return set()
    feriados = set()
    raw = (proy.get('feriados') or '').strip()
    for tok in raw.replace(';', ',').split(','):
        tok = tok.strip()
        if tok:
            try:
                datetime.strptime(tok, '%Y-%m-%d')
                feriados.add(tok)
            except Exception:
                pass
    out = set()
    for d in range(1, max(1, n_dias) + 1):
        fecha = f_ini + timedelta(days=d - 1)
        if fecha.weekday() == 6 or fecha.strftime('%Y-%m-%d') in feriados:
            out.add(d)
    return out


def _cargar_cronograma_data(pid: int) -> tuple[dict, dict, dict]:
    """Devuelve (cronograma_map, items_dict, ...) — helper interno."""
    conn = get_db()
    rows = conn.execute(
        "SELECT c.partida_id, c.duracion, c.inicio_dia, c.predecesoras, "
        "       c.es_hito, c.segmentos "
        "FROM cronograma_partidas c "
        "JOIN partidas p ON p.id = c.partida_id "
        "WHERE p.proyecto_id = ?",
        (pid,)
    ).fetchall()
    conn.close()
    return {r['partida_id']: dict(r) for r in rows}


def _html_cronograma_valorizado(pid: int, proy: dict, items: list, *,
                                 escala: str = 'semana',
                                 paper: str = 'A4',
                                 orient: str = 'portrait',
                                 periodos_por_pagina: int = 0,
                                 show_fechas: bool = False) -> str:
    """Cronograma valorizado — distribución del parcial por período (semana
    o mes). Paginación automática horizontal: divide los períodos en
    chunks según el ancho de papel y genera una tabla por chunk con su
    page-break. Cada chunk repite las partidas con su subconjunto de
    períodos y las 4 filas de resumen (TOTAL · % PERÍODO · ACUMULADO ·
    % ACUMULADO) calculadas globalmente."""
    from core.cronograma import distribuir_periodos, cpm
    o, od, _os = _brand_colors()
    dec = get_decimales_ppto()
    plazo = int(proy.get('plazo') or 30)
    cron = _cargar_cronograma_data(pid)

    period_days = 7 if escala == 'semana' else 30
    label = 'Semana' if escala == 'semana' else 'Mes'
    label_plural = 'semanas' if escala == 'semana' else 'meses'

    # Correr CPM como en la UI — usa las predecesoras + saltos por feriados
    # para calcular la fecha real de cada partida (no la "inicio_dia" cruda).
    partidas_list = [entry['partida'] for entry in items]
    non_working = _non_working_set_for(proy, plazo + 365)
    try:
        tasks_cpm = cpm(cron, partidas_list, plazo, non_working)
    except Exception:
        tasks_cpm = {}
    max_ef = max((t['EF'] for t in tasks_cpm.values() if t.get('EF', 0) > 0),
                  default=plazo)
    n_dias = max(max_ef, plazo, period_days)
    n_periods = max(1, (n_dias + period_days - 1) // period_days)

    # Paleta — alineada con `table.data` del resto de reportes (ver
    # `_base_css()`). Gridlines suaves silver-100, header sin fondo con
    # solo borde inferior slate-700, filas resumen con bg muy sutil.
    GRID         = "#CBD5E1"   # silver/slate sutil — un poco más visible que SLATE_100
    GRID_HDR_BOT = SLATE_700   # borde inferior acentuado del header (idem)
    BG_MONTO     = "#F1F5F9"   # silver muy claro para filas TOTAL/ACUMULADO
    BG_PCT       = "#FBFCFD"   # casi imperceptible para filas %
    HDR_BG       = "white"     # sin fondo — solo bordes (como table.data th)
    BG_TITLE1    = "white"     # títulos con borde, no con bg
    TXT_DK       = SLATE_900
    LBL_GREY     = SLATE_700

    # ── n_show: períodos por hoja ─────────────────────────────────────────
    #   -1 → todo en una sola hoja (n_show = n_periods)
    #    0 → auto (calcula según papel)
    #   N>0 → N períodos por hoja exactos
    if periodos_por_pagina == -1:
        n_show = n_periods
    elif periodos_por_pagina and periodos_por_pagina > 0:
        n_show = min(int(periodos_por_pagina), n_periods)
    else:
        w_in, h_in = _PdfRenderer.PAPER_SIZES_IN.get(paper, (8.27, 11.69))
        if orient == 'landscape':
            w_in, h_in = h_in, w_in
        usable_pts = w_in * 72 - 2 * 0.6 * 72
        # Cols fijas izquierdas: Ítem(48) + Descripción(120) + Und(28) +
        # Cantidad(50) + Precio(55) + %Total(40) = 341pt
        fixed_cols_pts = 48 + 120 + 28 + 50 + 55 + 40
        per_col_pts    = 84   # cada período = 2 sub-cols (Metrado + Valorización)
        n_show = max(3, int((usable_pts - fixed_cols_pts) / per_col_pts))
        n_show = min(n_show, n_periods)

    # ── Calcular distribuciones completas para TODAS las partidas ─────────
    partidas_data = []
    for i, entry in enumerate(items):
        p = entry['partida']
        es_titulo = bool(p.get('es_titulo'))
        if es_titulo:
            partidas_data.append({
                'titulo': True, 'p': p, 'parcial': entry['total'],
                'nivel': p.get('nivel') or 1,
            })
            continue
        c = cron.get(p['id'], {})
        dur = c.get('duracion') or 0
        segs = c.get('segmentos') or ''
        parcial = entry['total'] or 0
        # Usar el ES calculado por CPM (igual que la UI). Si CPM no devolvió
        # nada, caer al inicio_dia crudo.
        t_cpm = tasks_cpm.get(p['id'], {})
        ini = t_cpm.get('ES') or (c.get('inicio_dia') or 1)
        metrado_tot = p.get('metrado') or 0
        if dur > 0 and parcial > 0:
            distrib = distribuir_periodos(segs, ini, dur, parcial, n_periods, period_days)
            distrib_met = (distribuir_periodos(segs, ini, dur, metrado_tot,
                                                n_periods, period_days)
                           if metrado_tot else [0.0] * n_periods)
        else:
            distrib = [0.0] * n_periods
            distrib_met = [0.0] * n_periods
        partidas_data.append({
            'titulo': False, 'p': p, 'parcial': parcial,
            'distrib': distrib, 'distrib_met': distrib_met, 'idx': i,
        })

    # Totales globales por período (para los pies, mismos en todos los chunks)
    totales_periodo = [0.0] * n_periods
    for rp in partidas_data:
        if rp['titulo']:
            continue
        for k, v in enumerate(rp['distrib']):
            totales_periodo[k] += v
    total_total = sum(totales_periodo)
    # CD total de partidas no-título (para calcular "% Total" por partida)
    cd_total = sum((rp['parcial'] or 0)
                    for rp in partidas_data if not rp['titulo'])
    acumulado = []
    s = 0.0
    for v in totales_periodo:
        s += v
        acumulado.append(s)
    pct_per_all = [(v / total_total * 100.0 if total_total else 0.0)
                    for v in totales_periodo]
    pct_acum_all = [(v / total_total * 100.0 if total_total else 0.0)
                     for v in acumulado]

    # ── Generar HTML por chunks ───────────────────────────────────────────
    chunks = []
    k0 = 0
    while k0 < n_periods:
        chunks.append((k0, min(k0 + n_show, n_periods)))
        k0 += n_show

    # H2 canónico (estilado por `_base_css()` — izquierda + borde inferior
    # color de marca + margin-top 14pt) — consistente con el resto de
    # reportes. Sin inline style para que herede del CSS base.
    parts = [
        f'<h2>Cronograma Valorizado — por {label}</h2>'
    ]
    parts.append(
        f'<p style="color:{SLATE_500};font-size:9pt;margin:0 0 12pt 0">'
        f'Plazo: <b>{plazo} días</b> &nbsp;·&nbsp; '
        f'Períodos: <b>{n_periods} {label_plural}</b> &nbsp;·&nbsp; '
        f'Páginas horizontales: <b>{len(chunks)}</b>'
        f'</p>'
    )

    # Sin líneas horizontales en filas de datos — espejo del look "sin
    # bordes" del Presupuesto (que Marco validó). El PDF queda limpio:
    # solo border-bottom acentuado en el header de columnas y border-top
    # slate-700 en la fila TOTAL del pie. La diferenciación visual se
    # logra con bg zebra muy sutil y peso/color de la tipografía.
    BORDER_TD = ''

    # Fecha de inicio del proyecto (para mostrar rangos en headers)
    from datetime import datetime as _dt, timedelta as _td_obj
    f_ini_proy = None
    fi_str = (proy.get('fecha_inicio') or '').strip() or (proy.get('costo_al') or '').strip()
    if fi_str:
        try:
            f_ini_proy = _dt.strptime(fi_str, '%Y-%m-%d')
        except Exception:
            f_ini_proy = None
    MESES_ABBR = ["Ene", "Feb", "Mar", "Abr", "May", "Jun",
                   "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]

    def _periodo_label_html(k: int) -> str:
        """Devuelve el HTML interno del header para el período k (0-based)."""
        base = f"{label[0]}{k+1}"
        if not show_fechas or f_ini_proy is None:
            return base
        start_day = k * period_days + 1
        end_day   = (k + 1) * period_days
        d_ini = f_ini_proy + _td_obj(days=start_day - 1)
        d_fin = f_ini_proy + _td_obj(days=end_day - 1)
        if d_ini.month == d_fin.month and d_ini.year == d_fin.year:
            rng = f"{d_ini.day:02d}-{d_fin.day:02d} {MESES_ABBR[d_ini.month - 1]}"
        elif d_ini.year == d_fin.year:
            rng = (f"{d_ini.day:02d} {MESES_ABBR[d_ini.month - 1]} - "
                    f"{d_fin.day:02d} {MESES_ABBR[d_fin.month - 1]}")
        else:
            rng = (f"{d_ini.day:02d}/{d_ini.month:02d}/{str(d_ini.year)[-2:]} - "
                    f"{d_fin.day:02d}/{d_fin.month:02d}/{str(d_fin.year)[-2:]}")
        return f"{base}<br/><span style='font-weight:400;font-size:7pt'>{rng}</span>"

    # Modo "una sola hoja" → comprimir columnas (sin width fijo) para que
    # QTextDocument distribuya proporcionalmente y todo entre en una página.
    one_page_mode = (periodos_por_pagina == -1)
    sub_w_css = "" if one_page_mode else "width:42pt;"

    # ── Divisorias VERTICALES como COLUMNAS-ESPACADOR con fondo de color ──
    # QTextDocument NO dibuja bordes verticales por celda de forma fiable
    # (salen entrecortados y de grosor irregular fila a fila). En cambio SÍ
    # rellena fondos de celda de forma consistente (como la zebra) y respeta
    # el ANCHO solo como atributo HTML `width=N` (no en CSS). Por eso una
    # columna delgada con `background` = divisoria perfectamente continua.
    # Media (3px, slate-400) tras el bloque izq. y antes de Total; fina (1px,
    # slate-300) entre meses. NO se dibujan horizontales (la zebra separa).
    SEP_MED    = '<td width="2" style="background:#94A3B8;padding:0;font-size:1px"></td>'
    SEP_THIN   = '<td width="1" style="background:#CBD5E1;padding:0;font-size:1px"></td>'
    SEP_MED_H  = '<th rowspan="2" width="2" style="background:#94A3B8;padding:0;font-size:1px"></th>'
    SEP_THIN_H = '<th rowspan="2" width="1" style="background:#CBD5E1;padding:0;font-size:1px"></th>'

    # Colores de fuente por nivel = espejo del programa (NIVEL_ESTILO en
    # proyecto_view.py), igual que el reporte de Presupuesto: N1 rojo, N2
    # arándano, N3 morado, N4 rosa, N5 marrón.
    _NIVEL_COL = {1: '#B71C1C', 2: '#0D52BF', 3: '#6A1B9A', 4: '#AD1457'}

    # Tab de la columna Descripción (igual que Presupuesto): sangría colgante
    # por profundidad real del ítem (`item.count('.')-min_dots`, NO `nivel`).
    # QTextDocument ignora padding/margin de celda → tabla-espaciador anidada.
    _dots = [(rp['p'].get('item') or '').count('.') for rp in partidas_data]
    _min_dots = min(_dots) if _dots else 0

    def _ind(depth, inner_html):
        if depth <= 0:
            return inner_html
        return (
            '<table border="0" cellspacing="0" cellpadding="0" width="100%"><tr>'
            f'<td width="{depth * 14}" style="border:none;padding:0;'
            'background:transparent"></td><td style="border:none;padding:0;'
            f'background:transparent">{inner_html}</td></tr></table>'
        )

    def _build_chunk_table(k_start: int, k_end: int, is_first_chunk: bool) -> str:
        """Genera la tabla HTML para un rango de períodos [k_start, k_end).
        Cada período tiene DOS sub-columnas: Metrado y Valorización."""
        n_cols_per = k_end - k_start
        n_sub      = 2 * n_cols_per   # sub-columnas de período (Met. + Valor.)

        # Header sin bordes verticales — solo border-bottom acentuado.
        head_css = (f'border-bottom:1.5pt solid {o};'
                    f'background:#F1F5F9;color:{SLATE_900};'
                    f'font-weight:700;font-size:8pt;padding:5pt 6pt;')
        sub_css  = (f'border-bottom:1.5pt solid {o};'
                    f'background:#F1F5F9;color:{SLATE_700};'
                    f'font-weight:700;font-size:7pt;padding:2pt 4pt;'
                    f'text-align:right;{sub_w_css}')
        # Fila 1 del header: nombre de período abarcando 2 sub-columnas, con
        # divisoria-columna tras cada mes (media el último, antes de Total).
        encabezados = ''.join(
            f'<th colspan="2" style="{head_css}text-align:center;">'
            f'{_periodo_label_html(k)}</th>'
            + (SEP_MED_H if k == k_end - 1 else SEP_THIN_H)
            for k in range(k_start, k_end)
        )
        # Fila 2 del header: sub-cabeceras Met. / Valor. por período.
        sub_encabezados = ''.join(
            f'<th style="{sub_css}">Met.</th><th style="{sub_css}">Valor.</th>'
            for _ in range(k_start, k_end)
        )

        rows = []

        def _td(content: str, *, bg: str = 'white',
                   bold: bool = False, txt_color: str = TXT_DK,
                   align: str = 'left', colspan: int = 1) -> str:
            css = (f'{BORDER_TD}padding:5pt 6pt;color:{txt_color};'
                    f'background:{bg};text-align:{align};')
            if bold:
                css += 'font-weight:700;'
            cs = f' colspan="{colspan}"' if colspan != 1 else ''
            return f'<td{cs} style="{css}">{content}</td>'

        for rp in partidas_data:
            p = rp['p']
            if rp['titulo']:
                niv = rp['nivel']
                _depth = max(0, (p.get('item') or '').count('.') - _min_dots)
                _tcolor = _NIVEL_COL[1] if niv <= 1 else _NIVEL_COL.get(niv, "#92400E")
                if niv <= 1:
                    t_css = (f'padding:5pt 6pt;color:{_NIVEL_COL[1]};'
                              f'background:white;font-weight:700;'
                              f'font-size:9.5pt;text-transform:uppercase;'
                              f'letter-spacing:0.5pt;')
                    _u0, _u1 = '<u>', '</u>'
                else:
                    t_css = (f'padding:5pt 6pt;color:{_NIVEL_COL.get(niv, "#92400E")};'
                              f'background:white;font-weight:700;'
                              f'font-size:9pt;')
                    _u0, _u1 = '', ''
                # El monto de la columna Total va al MISMO tamaño que las demás
                # columnas (8.5pt), conservando color de nivel + negrita; sin el
                # uppercase/letter-spacing del título (no aplican a un número).
                t_total_css = (f'padding:5pt 6pt;color:{_tcolor};background:white;'
                               f'font-weight:700;font-size:8.5pt;text-align:right;')
                # Item + Descripción(colspan 5 = Desc..%Total) + sep + celdas
                # de período vacías (con sus divisorias) + Total.
                celdas_per_titulo = ''.join(
                    f'<td style="{t_css}"></td><td style="{t_css}"></td>'
                    + (SEP_MED if k == k_end - 1 else SEP_THIN)
                    for k in range(k_start, k_end)
                )
                _desc_t = escape(p.get("descripcion") or "")
                _desc_html = f'{_u0}{_desc_t}{_u1}'
                rows.append(
                    f'<tr>'
                    f'<td style="{t_css}">{_u0}{escape(p.get("item") or "")}{_u1}</td>'
                    f'<td colspan="5" style="{t_css}">{_ind(_depth, _desc_html)}</td>'
                    f'{SEP_MED}'
                    f'{celdas_per_titulo}'
                    f'<td style="{t_total_css}"></td>'
                    f'</tr>'
                )
                continue

            row_bg = "#FBFCFD" if (rp['idx'] % 2) else "white"
            cells_p = ''.join(
                _td(f"{rp['distrib_met'][k]:,.2f}" if rp['distrib_met'][k] > 0 else "",
                     bg=row_bg, align='right')
                + _td(_fmt(rp['distrib'][k], dec) if rp['distrib'][k] > 0 else "",
                       bg=row_bg, align='right')
                + (SEP_MED if k == k_end - 1 else SEP_THIN)
                for k in range(k_start, k_end)
            )
            metrado_v = p.get('metrado') or 0
            pu_v      = p.get('precio_unitario') or 0
            und_v     = p.get('unidad') or p.get('und') or ''
            # Precio Total de la partida = precio unitario × metrado (= parcial).
            precio_total = rp['parcial'] or 0
            cant_txt  = (f"{metrado_v:,.2f}") if metrado_v else ''
            pu_txt    = _fmt(pu_v, dec) if pu_v else ''
            total_fila = sum(rp['distrib'][k] for k in range(k_start, k_end))
            _depth = max(0, (p.get('item') or '').count('.') - _min_dots)
            rows.append(
                f'<tr>'
                f'{_td(escape(p.get("item") or ""), bg=row_bg)}'
                f'{_td(_ind(_depth, escape(p.get("descripcion") or "")), bg=row_bg)}'
                f'{_td(escape(str(und_v)), bg=row_bg, align="center")}'
                f'{_td(cant_txt, bg=row_bg, align="right")}'
                f'{_td(pu_txt, bg=row_bg, align="right")}'
                f'{_td(_fmt(precio_total, dec) if precio_total else "", bg=row_bg, align="right")}'
                f'{SEP_MED}'
                f'{cells_p}'
                f'{_td(_fmt(total_fila, dec), bg=row_bg, align="right")}'
                f'</tr>'
            )

        def _row_resumen(lbl, vals, total_val, bg, pct=False, top_thick=False):
            # En las filas resumen la sub-columna Metrado va vacía (sumar
            # metrados de distintas unidades no tiene sentido); solo la
            # sub-columna Valorización lleva el monto/porcentaje.
            tcss = (f'border-top:2pt solid {SLATE_900};'
                     if top_thick
                     else f'border-top:0.4pt solid {SLATE_300};')
            css_lbl = (f'{tcss}padding:5pt 8pt;background:{bg};color:{LBL_GREY};'
                        f'font-weight:700;text-align:right;')
            css_val = (f'{tcss}padding:5pt 6pt;background:{bg};color:{TXT_DK};'
                        f'font-weight:700;text-align:right;')
            css_met = (f'{tcss}padding:5pt 6pt;background:{bg};')
            # Divisorias-columna que conservan el borde-top de la fila para no
            # interrumpir la línea (sobre todo el 2pt slate del TOTAL).
            sep_med  = (f'<td width="2" style="{tcss}background:#94A3B8;'
                        f'padding:0;font-size:1px"></td>')
            sep_thin = (f'<td width="1" style="{tcss}background:#CBD5E1;'
                        f'padding:0;font-size:1px"></td>')

            def _sp(k):
                return sep_med if k == k_end - 1 else sep_thin
            if pct:
                cells = ''.join(
                    f'<td style="{css_met}"></td>'
                    f'<td style="{css_val}">{vals[k]:.1f}%</td>'
                    f'{_sp(k)}'
                    for k in range(k_start, k_end)
                )
                tot_txt = f"{total_val:.1f}%"
            else:
                cells = ''.join(
                    f'<td style="{css_met}"></td>'
                    f'<td style="{css_val}">'
                    f'{_fmt(vals[k], dec) if vals[k] > 0 else "—"}</td>'
                    f'{_sp(k)}'
                    for k in range(k_start, k_end)
                )
                tot_txt = _fmt(total_val, dec)
            return (
                f'<tr>'
                f'<td colspan="6" style="{css_lbl}">{lbl}</td>'
                f'{sep_med}'
                f'{cells}'
                f'<td style="{css_val}">{tot_txt}</td>'
                f'</tr>'
            )

        rows.append(_row_resumen("TOTAL", totales_periodo, total_total,
                                    BG_MONTO, top_thick=True))
        rows.append(_row_resumen("% PERÍODO", pct_per_all,
                                    100.0 if total_total else 0.0,
                                    BG_PCT, pct=True))
        rows.append(_row_resumen("ACUMULADO", acumulado, total_total, BG_MONTO))
        rows.append(_row_resumen("% ACUMULADO", pct_acum_all,
                                    100.0 if total_total else 0.0,
                                    BG_PCT, pct=True))

        return (
            f'<table cellspacing="0" cellpadding="0" width="100%" '
            f'style="border-collapse:collapse;width:100%;font-size:8.5pt;">'
            f'<thead>'
            f'<tr>'
            f'<th rowspan="2" style="{head_css}width:48pt;text-align:left">Ítem</th>'
            f'<th rowspan="2" style="{head_css}text-align:left">Descripción</th>'
            f'<th rowspan="2" style="{head_css}width:30pt;text-align:center">Und</th>'
            f'<th rowspan="2" style="{head_css}width:52pt;text-align:right">Cantidad</th>'
            f'<th rowspan="2" style="{head_css}width:58pt;text-align:right">Precio</th>'
            f'<th rowspan="2" style="{head_css}width:62pt;text-align:right">Total</th>'
            f'{SEP_MED_H}'
            f'{encabezados}'
            f'<th rowspan="2" style="{head_css}width:70pt;text-align:right">Total</th>'
            f'</tr>'
            f'<tr>{sub_encabezados}</tr>'
            f'</thead>'
            f'<tbody>{"".join(rows)}</tbody></table>'
        )

    for ci, (k0, k1) in enumerate(chunks):
        if ci > 0:
            parts.append('<div style="page-break-before:always"></div>')
            parts.append(
                f'<h3 style="color:{TXT_DK};margin:0 0 6pt 0;font-weight:700">'
                f'Cronograma Valorizado — {label_plural.capitalize()} {k0 + 1} a {k1}'
                f' (página {ci + 1} de {len(chunks)})</h3>'
            )
        parts.append(_build_chunk_table(k0, k1, ci == 0))

    return "\n".join(parts)


def _html_cronograma_curva_s(pid: int, proy: dict, items: list, *,
                              escala: str = 'semana') -> str:
    """Curva S — avance acumulado en % a lo largo del tiempo."""
    from core.cronograma import distribuir_periodos
    sym = _moneda_simbolo(proy.get('moneda') or 'Soles')
    dec = get_decimales_ppto()
    plazo = int(proy.get('plazo') or 30)
    cron = _cargar_cronograma_data(pid)

    period_days = 7 if escala == 'semana' else 30
    label = 'Semana' if escala == 'semana' else 'Mes'
    n_periods = max(1, (plazo + period_days - 1) // period_days)

    totales_periodo = [0.0] * n_periods
    cd_total = 0.0
    for entry in items:
        p = entry['partida']
        if p.get('es_titulo'):
            continue
        parcial = entry['total'] or 0
        cd_total += parcial
        c = cron.get(p['id'], {})
        dur = c.get('duracion') or 0
        ini = c.get('inicio_dia') or 1
        segs = c.get('segmentos') or ''
        if dur > 0 and parcial > 0:
            distrib = distribuir_periodos(segs, ini, dur, parcial, n_periods, period_days)
            for k, v in enumerate(distrib):
                totales_periodo[k] += v

    acum = 0.0
    acum_pct = []
    serie = []
    for v in totales_periodo:
        acum += v
        pct = (acum / cd_total * 100) if cd_total else 0
        acum_pct.append(pct)
        serie.append(v)

    # Gráfico
    chart = _png_curva_s_b64(serie, acum_pct, etiqueta_x=label,
                              width=560, height=280)

    # Tabla resumen
    rows_t = []
    acum2 = 0.0
    for i, (v, pct) in enumerate(zip(serie, acum_pct)):
        acum2 += v
        cls = "alt" if (i % 2) else ""
        rows_t.append(
            f'<tr class="{cls}">'
            f'<td class="c">{label[0]}{i+1}</td>'
            f'<td class="r">{_fmt(v, dec)}</td>'
            f'<td class="r">{_fmt(acum2, dec)}</td>'
            f'<td class="r">{pct:.2f}%</td>'
            f'</tr>'
        )

    parts = [
        f'<h2>Curva S de Avance Físico</h2>',
        f'<p style="color:{SLATE_500};font-size:9pt;margin-top:0;margin-bottom:8pt">'
        f'Avance acumulado en porcentaje del costo directo a lo largo del tiempo. '
        f'Plazo: <b>{plazo} días</b>, distribución por <b>{label.lower()}</b>.</p>',
        f'<div align="center" style="margin:10pt 0">{chart}</div>',
        f'<h3>Detalle por {label.lower()}</h3>',
        '<table class="data" style="width:80%">'
        '<thead><tr>'
        f'<th style="width:50pt;text-align:center">{label}</th>'
        '<th style="width:120pt;text-align:right">Avance del período</th>'
        '<th style="width:120pt;text-align:right">Acumulado</th>'
        '<th style="width:80pt;text-align:right">% Avance</th>'
        '</tr></thead>'
        f'<tbody>{"".join(rows_t)}</tbody></table>',
    ]
    return "\n".join(parts)


def _html_cronograma_adquisiciones(pid: int, proy: dict, items: list, *,
                                    escala: str = 'semana',
                                    paper: str = 'A4',
                                    orient: str = 'portrait',
                                    periodos_por_pagina: int = 0,
                                    show_fechas: bool = False) -> str:
    """Cronograma de adquisición de insumos — espejo visual del Valorizado.
    Columnas: Tipo · Código · Descripción · Und · Precio · % Total · [períodos] · Total.
    4 filas de resumen al pie. Paginación horizontal y CPM como en UI."""
    return _html_cronograma_adquisiciones_v2(
        pid, proy, items, escala=escala, paper=paper, orient=orient,
        periodos_por_pagina=periodos_por_pagina, show_fechas=show_fechas)


def _html_cronograma_adquisiciones_v2(pid: int, proy: dict, items: list, *,
                                       escala: str = 'semana',
                                       paper: str = 'A4',
                                       orient: str = 'portrait',
                                       periodos_por_pagina: int = 0,
                                       show_fechas: bool = False) -> str:
    """Versión nueva del reporte de adquisiciones — sigue el mismo patrón
    visual que `_html_cronograma_valorizado` pero usando insumos como
    "filas" en lugar de partidas."""
    from core.cronograma import distribuir_periodos, cpm
    from datetime import datetime as _dt, timedelta as _td_obj

    o, od, _os = _brand_colors()
    dec = get_decimales_ppto()
    plazo = int(proy.get('plazo') or 30)
    cron = _cargar_cronograma_data(pid)

    period_days = 7 if escala == 'semana' else 30
    label = 'Semana' if escala == 'semana' else 'Mes'
    label_plural = 'semanas' if escala == 'semana' else 'meses'

    # CPM (mismo cálculo que la UI)
    partidas_list = [entry['partida'] for entry in items]
    non_working = _non_working_set_for(proy, plazo + 365)
    try:
        tasks_cpm = cpm(cron, partidas_list, plazo, non_working)
    except Exception:
        tasks_cpm = {}
    max_ef = max((t['EF'] for t in tasks_cpm.values() if t.get('EF', 0) > 0),
                  default=plazo)
    n_dias = max(max_ef, plazo, period_days)
    n_periods = max(1, (n_dias + period_days - 1) // period_days)

    # Paleta — espejo del valorizado, alineada con `table.data`.
    GRID         = "#CBD5E1"   # idem valorizado
    GRID_HDR_BOT = SLATE_700
    BG_MONTO     = "#F1F5F9"
    BG_PCT       = "#FBFCFD"
    HDR_BG       = "white"
    TXT_DK       = SLATE_900
    LBL_GREY     = SLATE_700

    # Períodos por hoja
    if periodos_por_pagina == -1:
        n_show = n_periods
    elif periodos_por_pagina and periodos_por_pagina > 0:
        n_show = min(int(periodos_por_pagina), n_periods)
    else:
        w_in, h_in = _PdfRenderer.PAPER_SIZES_IN.get(paper, (8.27, 11.69))
        if orient == 'landscape':
            w_in, h_in = h_in, w_in
        usable_pts = w_in * 72 - 2 * 0.6 * 72
        fixed_cols_pts = 28 + 60 + 130 + 28 + 52 + 58
        per_col_pts = 84   # cada período = 2 sub-cols (Cantidad + Valorización)
        n_show = max(3, int((usable_pts - fixed_cols_pts) / per_col_pts))
        n_show = min(n_show, n_periods)

    # Cargar insumos y distribuirlos por período usando CPM ES.
    # INCLUYE items con unidad `%MO`/`%MAT` (overhead) — su parcial real lo
    # calcula `get_acu_items` (cantidad/100 × subtotal_base × metrado). Sin
    # esto, items como "HERRAMIENTAS MANUALES 2 %MO" desaparecen del
    # cronograma aunque su monto distribuido sea ≠ 0.
    # Distribución proporcional al `parcial_wysiwyg` de cada partida (=
    # contribución al CD) → garantiza que `sum(montos)` = CD exactamente.
    from core.database import parcial_wysiwyg as _pw
    conn = get_db()
    partidas_db = conn.execute(
        "SELECT id, metrado, precio_unitario FROM partidas "
        "WHERE proyecto_id=? AND es_titulo=0",
        (pid,)
    ).fetchall()

    insumos = {}
    for p_row in partidas_db:
        partida_id = p_row['id']
        metrado    = float(p_row['metrado'] or 0)
        pu         = float(p_row['precio_unitario'] or 0)
        items, _ = get_acu_items(conn, partida_id)
        partida_total = _pw(metrado, pu) if (metrado and pu) else 0.0
        sum_p = sum((it.get('parcial') or 0) for it in items)
        c = cron.get(partida_id, {})
        dur  = c.get('duracion') or 0
        segs = c.get('segmentos') or ''
        t_cpm = tasks_cpm.get(partida_id, {})
        ini   = t_cpm.get('ES') or (c.get('inicio_dia') or 1)
        for it in items:
            rid = it['recurso_id']
            # Reparto proporcional del partida_total entre items.
            if sum_p > 0:
                ratio = (it.get('parcial') or 0) / sum_p
                monto_total = partida_total * ratio
            else:
                monto_total = 0.0
            und_i = it.get('unidad') or ''
            qty_total = (it.get('cantidad') or 0) * metrado
            if dur > 0 and monto_total > 0:
                distrib = distribuir_periodos(segs, ini, dur, monto_total,
                                                 n_periods, period_days)
            else:
                distrib = [0.0] * n_periods
            if dur > 0 and qty_total > 0 and not und_i.startswith('%'):
                distrib_qty = distribuir_periodos(segs, ini, dur, qty_total,
                                                    n_periods, period_days)
            else:
                distrib_qty = [0.0] * n_periods
            if rid not in insumos:
                insumos[rid] = {
                    'codigo':      it.get('codigo')      or '',
                    'descripcion': it.get('descripcion') or '',
                    'tipo':        it.get('tipo')        or 'MAT',
                    'unidad':      it.get('unidad')      or '',
                    'precio':      it.get('precio')      or 0,
                    'monto_total': 0.0,
                    'periodos':    [0.0] * n_periods,
                    'periodos_qty': [0.0] * n_periods,
                }
            d = insumos[rid]
            d['monto_total'] += monto_total
            precio_i = it.get('precio') or 0
            if precio_i > d['precio']:
                d['precio'] = precio_i
            for k in range(n_periods):
                d['periodos'][k] += distrib[k]
                d['periodos_qty'][k] += distrib_qty[k]
    conn.close()

    orden_tipo = {'MO': 0, 'MAT': 1, 'EQ': 2, 'SC': 3}
    insumos_sorted = sorted(
        insumos.values(),
        key=lambda d: (orden_tipo.get(d['tipo'], 9),
                       _orden_mo(d['descripcion']) if d['tipo'] == 'MO' else 0,
                       d['descripcion'])
    )

    # Totales globales
    totales_periodo = [0.0] * n_periods
    for d in insumos_sorted:
        for k, v in enumerate(d['periodos']):
            totales_periodo[k] += v
    total_total = sum(totales_periodo)
    acumulado = []
    s = 0.0
    for v in totales_periodo:
        s += v
        acumulado.append(s)
    pct_per_all = [(v / total_total * 100.0 if total_total else 0.0)
                    for v in totales_periodo]
    pct_acum_all = [(v / total_total * 100.0 if total_total else 0.0)
                     for v in acumulado]

    # Chunks
    chunks = []
    k0 = 0
    while k0 < n_periods:
        chunks.append((k0, min(k0 + n_show, n_periods)))
        k0 += n_show

    parts = [
        f'<h2>Cronograma de Adquisición de Insumos — por {label}</h2>'
    ]
    parts.append(
        f'<p style="color:{SLATE_500};font-size:9pt;margin:0 0 12pt 0">'
        f'Plazo: <b>{plazo} días</b> &nbsp;·&nbsp; '
        f'Períodos: <b>{n_periods} {label_plural}</b> &nbsp;·&nbsp; '
        f'Insumos: <b>{len(insumos_sorted)}</b> &nbsp;·&nbsp; '
        f'Páginas horizontales: <b>{len(chunks)}</b>'
        f'</p>'
    )

    # Sin bordes inline — look limpio espejo del Presupuesto/Valorizado.
    # Solo persisten: border-bottom acentuado del header de columnas
    # (eliminado tras feedback) y border-top slate-700 de la fila TOTAL.
    BORDER_TD = ''
    one_page_mode = (periodos_por_pagina == -1)
    sub_w_css = "" if one_page_mode else "width:42pt;"

    # Divisorias VERTICALES como columnas-espacador con fondo (ver explicación
    # en _html_cronograma_valorizado): QTextDocument no dibuja bordes
    # verticales fiables, pero sí rellena fondos y respeta width=N como
    # atributo HTML → columna delgada coloreada = divisoria continua.
    SEP_MED    = '<td width="2" style="background:#94A3B8;padding:0;font-size:1px"></td>'
    SEP_THIN   = '<td width="1" style="background:#CBD5E1;padding:0;font-size:1px"></td>'
    SEP_MED_H  = '<th rowspan="2" width="2" style="background:#94A3B8;padding:0;font-size:1px"></th>'
    SEP_THIN_H = '<th rowspan="2" width="1" style="background:#CBD5E1;padding:0;font-size:1px"></th>'

    f_ini_proy = None
    fi_str = (proy.get('fecha_inicio') or '').strip() or (proy.get('costo_al') or '').strip()
    if fi_str:
        try:
            f_ini_proy = _dt.strptime(fi_str, '%Y-%m-%d')
        except Exception:
            f_ini_proy = None
    MESES_ABBR = ["Ene", "Feb", "Mar", "Abr", "May", "Jun",
                   "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]

    def _periodo_label_html(k: int) -> str:
        base = f"{label[0]}{k+1}"
        if not show_fechas or f_ini_proy is None:
            return base
        s_day = k * period_days + 1
        e_day = (k + 1) * period_days
        d_i = f_ini_proy + _td_obj(days=s_day - 1)
        d_f = f_ini_proy + _td_obj(days=e_day - 1)
        if d_i.month == d_f.month and d_i.year == d_f.year:
            rng = f"{d_i.day:02d}-{d_f.day:02d} {MESES_ABBR[d_i.month - 1]}"
        elif d_i.year == d_f.year:
            rng = (f"{d_i.day:02d} {MESES_ABBR[d_i.month - 1]} - "
                    f"{d_f.day:02d} {MESES_ABBR[d_f.month - 1]}")
        else:
            rng = (f"{d_i.day:02d}/{d_i.month:02d}/{str(d_i.year)[-2:]} - "
                    f"{d_f.day:02d}/{d_f.month:02d}/{str(d_f.year)[-2:]}")
        return f"{base}<br/><span style='font-weight:400;font-size:7pt'>{rng}</span>"

    def _build_chunk_table(k_start: int, k_end: int) -> str:
        n_cols_per = k_end - k_start
        n_sub      = 2 * n_cols_per   # sub-columnas (Cantidad + Valorización)

        head_css = (f'border-bottom:1.5pt solid {o};'
                    f'background:#F1F5F9;color:{SLATE_900};'
                    f'font-weight:700;font-size:8pt;padding:5pt 6pt;')
        sub_css  = (f'border-bottom:1.5pt solid {o};'
                    f'background:#F1F5F9;color:{SLATE_700};'
                    f'font-weight:700;font-size:7pt;padding:2pt 4pt;'
                    f'text-align:right;{sub_w_css}')
        encabezados = ''.join(
            f'<th colspan="2" style="{head_css}text-align:center;">'
            f'{_periodo_label_html(k)}</th>'
            + (SEP_MED_H if k == k_end - 1 else SEP_THIN_H)
            for k in range(k_start, k_end)
        )
        sub_encabezados = ''.join(
            f'<th style="{sub_css}">Cant.</th><th style="{sub_css}">Valor.</th>'
            for _ in range(k_start, k_end)
        )

        rows = []

        def _td(content, *, bg='white', bold=False, txt_color=TXT_DK,
                  align='left', colspan=1):
            css = (f'{BORDER_TD}padding:5pt 6pt;color:{txt_color};'
                    f'background:{bg};text-align:{align};')
            if bold:
                css += 'font-weight:700;'
            cs = f' colspan="{colspan}"' if colspan != 1 else ''
            return f'<td{cs} style="{css}">{content}</td>'

        TIPO_LABEL = {
            'MO':  'MANO DE OBRA',
            'MAT': 'MATERIALES',
            'EQ':  'EQUIPOS Y HERRAMIENTAS',
            'SC':  'SUB-CONTRATOS / SERVICIOS',
        }
        # 6 (izq) + n_sub períodos + 1 (Total)
        n_cols_full = n_sub + 7
        # Título de grupo = banda con tinte suave del tipo + texto del color
        # del tipo (igual que el reporte de Insumos). MO naranja/ámbar, MAT
        # verde, EQ gris-acero, SC morado.
        _TIPO_COL  = {'MO': '#F39C12', 'MAT': '#27AE60',
                      'EQ': '#607D8B', 'SC': '#7A36B1'}
        _TIPO_SOFT = {'MO': '#FEF3DD', 'MAT': '#E3F4EA',
                      'EQ': '#ECEEF1', 'SC': '#F1E7F9'}
        def _title_css(tipo):
            return (f'padding:5pt 8pt;background:{_TIPO_SOFT.get(tipo, "white")};'
                    f'color:{_TIPO_COL.get(tipo, SLATE_900)};font-weight:700;'
                    f'font-size:9.5pt;letter-spacing:0.5pt;text-align:left;'
                    f'text-transform:uppercase;')

        last_tipo = None
        for ri, d in enumerate(insumos_sorted):
            if d['tipo'] != last_tipo:
                # Banner del tipo: colspan 6 (bloque izq.) + sep + celdas de
                # período vacías (con divisorias) + Total vacío.
                tcss = _title_css(d['tipo'])
                celdas_per_tipo = ''.join(
                    f'<td style="{tcss}"></td><td style="{tcss}"></td>'
                    + (SEP_MED if k == k_end - 1 else SEP_THIN)
                    for k in range(k_start, k_end)
                )
                rows.append(
                    f'<tr>'
                    f'<td colspan="6" style="{tcss}">'
                    f'{TIPO_LABEL.get(d["tipo"], d["tipo"])}</td>'
                    f'{SEP_MED}'
                    f'{celdas_per_tipo}'
                    f'<td style="{tcss}"></td>'
                    f'</tr>'
                )
                last_tipo = d['tipo']

            row_bg = "#FBFCFD" if (ri % 2) else "white"
            dq = d.get('periodos_qty', [0.0] * n_periods)
            cells_p = ''.join(
                _td(f"{dq[k]:,.2f}" if dq[k] > 0 else "", bg=row_bg, align='right')
                + _td(_fmt(d['periodos'][k], dec) if d['periodos'][k] > 0 else "",
                       bg=row_bg, align='right')
                + (SEP_MED if k == k_end - 1 else SEP_THIN)
                for k in range(k_start, k_end)
            )
            total_fila = sum(d['periodos'][k] for k in range(k_start, k_end))
            # Cantidad y Precio = TOTALES del insumo en el proyecto.
            qty_proj = sum(d.get('periodos_qty', []))
            cant_txt = f"{qty_proj:,.2f}" if qty_proj > 0 else ""
            rows.append(
                f'<tr>'
                f'{_td(escape(d["tipo"]), bg=row_bg, align="center")}'
                f'{_td(escape(d["codigo"]), bg=row_bg)}'
                f'{_td(escape(d["descripcion"]), bg=row_bg)}'
                f'{_td(escape(d["unidad"]), bg=row_bg, align="center")}'
                f'{_td(cant_txt, bg=row_bg, align="right")}'
                f'{_td(_fmt(d["monto_total"], dec) if d["monto_total"] else "", bg=row_bg, align="right")}'
                f'{SEP_MED}'
                f'{cells_p}'
                f'{_td(_fmt(total_fila, dec), bg=row_bg, align="right")}'
                f'</tr>'
            )

        def _row_resumen(lbl, vals, total_val, bg, pct=False, top_thick=False):
            tcss = (f'border-top:2pt solid {SLATE_900};'
                     if top_thick
                     else f'border-top:0.4pt solid {SLATE_300};')
            css_lbl = (f'{tcss}padding:5pt 8pt;background:{bg};color:{LBL_GREY};'
                        f'font-weight:700;text-align:right;')
            css_val = (f'{tcss}padding:5pt 6pt;background:{bg};color:{TXT_DK};'
                        f'font-weight:700;text-align:right;')
            css_qty = (f'{tcss}padding:5pt 6pt;background:{bg};')
            # Divisorias-columna que conservan el borde-top de la fila.
            sep_med  = (f'<td width="2" style="{tcss}background:#94A3B8;'
                        f'padding:0;font-size:1px"></td>')
            sep_thin = (f'<td width="1" style="{tcss}background:#CBD5E1;'
                        f'padding:0;font-size:1px"></td>')

            def _sp(k):
                return sep_med if k == k_end - 1 else sep_thin
            # En las filas resumen la sub-columna Cantidad va vacía.
            if pct:
                cells = ''.join(
                    f'<td style="{css_qty}"></td>'
                    f'<td style="{css_val}">{vals[k]:.1f}%</td>'
                    f'{_sp(k)}'
                    for k in range(k_start, k_end)
                )
                tot_txt = f"{total_val:.1f}%"
            else:
                cells = ''.join(
                    f'<td style="{css_qty}"></td>'
                    f'<td style="{css_val}">'
                    f'{_fmt(vals[k], dec) if vals[k] > 0 else "—"}</td>'
                    f'{_sp(k)}'
                    for k in range(k_start, k_end)
                )
                tot_txt = _fmt(total_val, dec)
            return (
                f'<tr>'
                f'<td colspan="6" style="{css_lbl}">{lbl}</td>'
                f'{sep_med}'
                f'{cells}'
                f'<td style="{css_val}">{tot_txt}</td>'
                f'</tr>'
            )

        rows.append(_row_resumen("TOTAL", totales_periodo, total_total,
                                    BG_MONTO, top_thick=True))
        rows.append(_row_resumen("% PERÍODO", pct_per_all,
                                    100.0 if total_total else 0.0,
                                    BG_PCT, pct=True))
        rows.append(_row_resumen("ACUMULADO", acumulado, total_total, BG_MONTO))
        rows.append(_row_resumen("% ACUMULADO", pct_acum_all,
                                    100.0 if total_total else 0.0,
                                    BG_PCT, pct=True))

        return (
            f'<table cellspacing="0" cellpadding="0" width="100%" '
            f'style="border-collapse:collapse;width:100%;font-size:8.5pt;">'
            f'<thead>'
            f'<tr>'
            f'<th rowspan="2" style="{head_css}width:28pt;text-align:center">Tipo</th>'
            f'<th rowspan="2" style="{head_css}width:60pt;text-align:left">Código</th>'
            f'<th rowspan="2" style="{head_css}text-align:left">Descripción</th>'
            f'<th rowspan="2" style="{head_css}width:28pt;text-align:center">Und</th>'
            f'<th rowspan="2" style="{head_css}width:52pt;text-align:right">Cantidad</th>'
            f'<th rowspan="2" style="{head_css}width:58pt;text-align:right">Precio</th>'
            f'{SEP_MED_H}'
            f'{encabezados}'
            f'<th rowspan="2" style="{head_css}width:70pt;text-align:right">Total</th>'
            f'</tr>'
            f'<tr>{sub_encabezados}</tr>'
            f'</thead>'
            f'<tbody>{"".join(rows)}</tbody></table>'
        )

    for ci, (k0, k1) in enumerate(chunks):
        if ci > 0:
            parts.append('<div style="page-break-before:always"></div>')
            parts.append(
                f'<h3 style="color:{TXT_DK};margin:0 0 6pt 0;font-weight:700">'
                f'Adquisiciones — {label_plural.capitalize()} {k0 + 1} a {k1}'
                f' (página {ci + 1} de {len(chunks)})</h3>'
            )
        parts.append(_build_chunk_table(k0, k1))

    return "\n".join(parts)


def _html_cronograma_adquisiciones_legacy(pid: int, proy: dict, items: list, *,
                                          escala: str = 'semana') -> str:
    """Versión anterior (preservada por si rompe algo). NO usar — espejada
    al nuevo formato mediante _html_cronograma_adquisiciones."""
    o, od, _os = _brand_colors()
    from core.cronograma import distribuir_periodos
    sym = _moneda_simbolo(proy.get('moneda') or 'Soles')
    dec = get_decimales_ppto()
    plazo = int(proy.get('plazo') or 30)
    cron = _cargar_cronograma_data(pid)

    period_days = 7 if escala == 'semana' else 30
    label = 'Semana' if escala == 'semana' else 'Mes'
    n_periods = max(1, (plazo + period_days - 1) // period_days)

    # Por cada partida hoja, distribuir cada insumo según el cronograma
    conn = get_db()
    rows_ins = conn.execute(
        """SELECT ai.partida_id, r.id as recurso_id, r.codigo, r.descripcion,
                  r.tipo, r.unidad, COALESCE(ai.precio, r.precio, 0) as precio,
                  ai.cantidad as cant_unit, p.metrado
           FROM acu_items ai
           JOIN recursos r ON r.id = ai.recurso_id
           JOIN partidas p ON p.id = ai.partida_id
           WHERE p.proyecto_id = ? AND SUBSTR(r.unidad, 1, 1) != '%'
           ORDER BY r.tipo,
                    CASE WHEN r.tipo='MO' THEN mo_rank(r.descripcion) ELSE 0 END,
                    r.descripcion""",
        (pid,)
    ).fetchall()
    conn.close()

    # Acumular: por (recurso_id, periodo) → cantidad y monto
    n_show = min(n_periods, 10)
    insumos_data = {}   # rid → {codigo, descripcion, tipo, unidad, precio, cantidad_total, monto_total, periodos}
    totales_periodo_monto = [0.0] * n_periods
    totales_periodo_cant  = {}   # tipo → [cant_periodo]

    for r in rows_ins:
        r = dict(r)
        rid = r['recurso_id']
        cant_total = (r['cant_unit'] or 0) * (r['metrado'] or 0)
        monto_total = cant_total * (r['precio'] or 0)
        c = cron.get(r['partida_id'], {})
        dur = c.get('duracion') or 0
        ini = c.get('inicio_dia') or 1
        segs = c.get('segmentos') or ''
        if dur > 0 and cant_total > 0:
            distrib_cant  = distribuir_periodos(segs, ini, dur, cant_total,  n_periods, period_days)
            distrib_monto = distribuir_periodos(segs, ini, dur, monto_total, n_periods, period_days)
        else:
            distrib_cant  = [0.0] * n_periods
            distrib_monto = [0.0] * n_periods

        if rid not in insumos_data:
            insumos_data[rid] = {
                'codigo': r['codigo'], 'descripcion': r['descripcion'],
                'tipo': r['tipo'], 'unidad': r['unidad'], 'precio': r['precio'],
                'cantidad_total': 0.0, 'monto_total': 0.0,
                'periodos_cant':  [0.0] * n_periods,
                'periodos_monto': [0.0] * n_periods,
            }
        d = insumos_data[rid]
        d['cantidad_total'] += cant_total
        d['monto_total']    += monto_total
        for k in range(n_periods):
            d['periodos_cant'][k]  += distrib_cant[k]
            d['periodos_monto'][k] += distrib_monto[k]
            totales_periodo_monto[k] += distrib_monto[k]

    # Render: agrupar por tipo
    parts = [f'<h2>Cronograma de Adquisiciones — por {label}</h2>']
    parts.append(
        f'<p style="color:{SLATE_500};font-size:9pt;margin-top:0;margin-bottom:8pt">'
        f'Distribución de insumos a lo largo del plazo de obra. '
        f'Plazo: <b>{plazo} días</b> &nbsp;·&nbsp; Períodos: <b>{n_periods} {label.lower()}s</b>'
        f'</p>'
    )

    encabezados = ''.join(
        f'<th style="text-align:right;width:48pt">{label[0]}{i+1}</th>'
        for i in range(n_show)
    )

    for tipo, label_tipo in [('MO', 'Mano de Obra'),
                              ('MAT', 'Materiales'),
                              ('EQ',  'Equipos y Herramientas'),
                              ('SC',  'Sub-contratos / Servicios')]:
        recursos_t = [d for d in insumos_data.values() if d['tipo'] == tipo]
        if not recursos_t:
            continue
        recursos_t.sort(key=lambda d: d['monto_total'], reverse=True)
        parts.append(f'<h3>{escape(label_tipo)}</h3>')

        rows = []
        for j, d in enumerate(recursos_t):
            cls = "alt" if (j % 2) else ""
            cells = ''.join(
                f'<td class="r">{_fmt(d["periodos_cant"][k], 2) if d["periodos_cant"][k] > 0 else ""}</td>'
                for k in range(n_show)
            )
            rows.append(
                f'<tr class="{cls}">'
                f'<td>{escape(d["codigo"] or "")}</td>'
                f'<td>{escape(d["descripcion"] or "")}</td>'
                f'<td class="c">{escape(d["unidad"] or "")}</td>'
                f'<td class="r">{_fmt(d["cantidad_total"], 2)}</td>'
                f'{cells}'
                f'</tr>'
            )
        parts.append(
            '<table class="data" width="100%">'
            '<thead><tr>'
            '<th style="width:55pt">Código</th>'
            '<th>Descripción</th>'
            '<th style="width:30pt;text-align:center">Und</th>'
            '<th style="width:60pt;text-align:right">Cant. total</th>'
            f'{encabezados}'
            '</tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table>'
        )

    # Resumen monto por período
    if any(totales_periodo_monto):
        cells_t = ''.join(
            f'<td class="r">{_fmt(totales_periodo_monto[k], 0)}</td>'
            for k in range(n_show)
        )
        acum = 0.0
        cells_a = []
        for k in range(n_show):
            acum += totales_periodo_monto[k]
            cells_a.append(f'<td class="r">{_fmt(acum, 0)}</td>')
        parts.append(
            '<h3>Monto total a adquirir por período</h3>'
            '<table class="data" width="100%">'
            '<thead><tr>'
            f'<th style="width:140pt">Concepto ({sym})</th>'
            f'{encabezados}'
            '</tr></thead>'
            '<tbody>'
            f'<tr style="background:white;color:{od};font-weight:700;'
        f' border-top:1.5pt solid {o};border-bottom:1.5pt solid {o}">'
            f'<td>Adquisición del período</td>{cells_t}</tr>'
            f'<tr style="background:white;color:{od};font-weight:600;'
        f' border-bottom:0.6pt solid {od}">'
            f'<td>Acumulado</td>{"".join(cells_a)}</tr>'
            '</tbody></table>'
        )

    if n_periods > n_show:
        parts.append(
            f'<p style="color:{SLATE_500};font-size:8.5pt;font-style:italic;margin-top:6pt">'
            f'Mostrando los primeros {n_show} {label.lower()}s.</p>'
        )

    return "\n".join(parts)


def _html_cronograma(pid: int, proy: dict, items: list) -> str:
    """Cronograma de obra — tabla con duración/inicio/fin/predecesoras + Gantt simple."""
    o, od, _os = _brand_colors()
    conn = get_db()
    plazo = int(proy.get('plazo') or 30)

    # Cargar datos del cronograma (solo este proyecto)
    rows_cron = conn.execute(
        "SELECT c.partida_id, c.duracion, c.inicio_dia, c.predecesoras, "
        "       c.es_hito, c.segmentos "
        "FROM cronograma_partidas c "
        "JOIN partidas p ON p.id = c.partida_id "
        "WHERE p.proyecto_id = ?",
        (pid,)
    ).fetchall()
    conn.close()
    cron = {r['partida_id']: dict(r) for r in rows_cron}

    parts = ['<h2>Cronograma de Obra</h2>']

    # Resumen del plazo
    parts.append(
        f'<table border="0" cellpadding="0" cellspacing="6" width="100%" style="margin-bottom:8pt">'
        f'<tr>'
        f'<td bgcolor="white" width="33%" valign="top"'
        f' style="border:0.6pt solid {SLATE_300};border-top:2.5pt solid {o};padding:8pt">'
        f'<p style="color:{SLATE_500};font-size:8pt;margin:0 0 4pt 0;letter-spacing:1pt">PLAZO TOTAL</p>'
        f'<p style="color:{SLATE_900};font-size:14pt;font-weight:700;margin:0">{plazo} días</p>'
        f'</td>'
        f'<td bgcolor="white" width="33%" valign="top"'
        f' style="border:0.6pt solid {SLATE_300};border-top:2.5pt solid {o};padding:8pt">'
        f'<p style="color:{SLATE_500};font-size:8pt;margin:0 0 4pt 0;letter-spacing:1pt">PARTIDAS PROGRAMADAS</p>'
        f'<p style="color:{SLATE_900};font-size:14pt;font-weight:700;margin:0">{len(cron)}</p>'
        f'</td>'
        f'<td bgcolor="white" width="33%" valign="top"'
        f' style="border:0.6pt solid {SLATE_300};border-top:2.5pt solid {o};padding:8pt">'
        f'<p style="color:{SLATE_500};font-size:8pt;margin:0 0 4pt 0;letter-spacing:1pt">MODALIDAD</p>'
        f'<p style="color:{SLATE_900};font-size:14pt;font-weight:700;margin:0">'
        f'{escape(proy.get("modalidad") or "Contrata")}</p>'
        f'</td>'
        f'</tr></table>'
    )

    # Tabla de cronograma con barra Gantt embebida
    if not items:
        parts.append('<p style="color:#888;font-style:italic">Sin partidas programadas.</p>')
        return "\n".join(parts)

    # Calcular max_dia para escalar barras
    max_dia = plazo
    for entry in items:
        p = entry['partida']
        c = cron.get(p['id'])
        if c:
            fin = (c.get('inicio_dia') or 1) + (c.get('duracion') or 0) - 1
            if fin > max_dia:
                max_dia = fin
    max_dia = max(max_dia, 1)

    # Cabecera de la tabla
    rows = []
    for i, entry in enumerate(items):
        p = entry['partida']
        c = cron.get(p['id'], {})
        dur = c.get('duracion') or 0
        ini = c.get('inicio_dia') or 1
        fin = ini + dur - 1 if dur else ini
        pred = c.get('predecesoras') or ''
        es_hito = c.get('es_hito') or 0
        es_titulo = bool(p.get('es_titulo'))

        # Estilo de fila por jerarquía
        if es_titulo and (p.get('nivel') == 1):
            cls = "titulo1"
        elif es_titulo:
            cls = "titulo2"
        else:
            cls = "alt" if (i % 2) else ""

        # Barra Gantt: tabla de 100 columnas conceptuales con offset/width
        if (dur > 0 or es_hito == 1) and not es_titulo:
            # Hito puro (es_hito==1, dur=0) → barrita morada de 1% en ini
            if es_hito == 1:
                offset_pct = max(0, (ini - 1) / max_dia * 100)
                width_pct = max(0.8, 100 / max_dia)   # ~1 día visual
            else:
                offset_pct = max(0, (ini - 1) / max_dia * 100)
                width_pct  = max(1, dur / max_dia * 100)
            # Truncar para que no exceda
            if offset_pct + width_pct > 100:
                width_pct = 100 - offset_pct

            # Construir las celdas según el tipo:
            #  • es_hito==1 → barra morada puramente (hito)
            #  • es_hito==2 → naranja con marcador azul al INICIO
            #  • es_hito==3 → naranja con marcador verde al FIN
            #  • normal     → naranja
            cells = []
            if offset_pct > 0:
                cells.append(
                    f'<td bgcolor="{SLATE_100}" width="{offset_pct:.1f}%">&nbsp;</td>'
                )
            if es_hito == 1:
                cells.append(
                    f'<td bgcolor="#7A36B1" width="{width_pct:.1f}%">&nbsp;</td>'
                )
            elif es_hito in (2, 3):
                # Marker pct: máximo 40% del ancho de la barra, mínimo 0.5%
                # del total — así se ve incluso en tareas cortas en proyectos
                # largos. Si la barra es muy chica, se hace toda del color
                # marcador para que sea visible.
                marker_pct = max(0.5, min(width_pct * 0.4, width_pct - 0.3))
                if marker_pct >= width_pct - 0.1:
                    rest_pct = 0
                    marker_pct = width_pct
                else:
                    rest_pct = width_pct - marker_pct
                marker_color = "#3689E6" if es_hito == 2 else "#3A9104"
                if es_hito == 2:
                    cells.append(
                        f'<td bgcolor="{marker_color}" width="{marker_pct:.2f}%">&nbsp;</td>'
                    )
                    if rest_pct > 0:
                        cells.append(
                            f'<td bgcolor="{o}" width="{rest_pct:.2f}%">&nbsp;</td>'
                        )
                else:
                    if rest_pct > 0:
                        cells.append(
                            f'<td bgcolor="{o}" width="{rest_pct:.2f}%">&nbsp;</td>'
                        )
                    cells.append(
                        f'<td bgcolor="{marker_color}" width="{marker_pct:.2f}%">&nbsp;</td>'
                    )
            else:
                cells.append(
                    f'<td bgcolor="{o}" width="{width_pct:.1f}%">&nbsp;</td>'
                )
            if (offset_pct + width_pct) < 100:
                cells.append(f'<td bgcolor="{SLATE_100}">&nbsp;</td>')

            bar_html = (
                f'<table border="0" cellpadding="0" cellspacing="0" width="100%"'
                f' bgcolor="{SLATE_100}" height="12">'
                f'<tr>{"".join(cells)}</tr></table>'
            )
            dur_text = f"{dur} d" if dur > 0 else '0 d'
            ini_text = str(ini)
            fin_text = str(fin)
        elif es_titulo:
            bar_html = ''
            dur_text = ''
            ini_text = ''
            fin_text = ''
        else:
            bar_html = (
                f'<table border="0" cellpadding="0" cellspacing="0" width="100%"'
                f' bgcolor="{SLATE_100}" height="12"><tr><td>&nbsp;</td></tr></table>'
            )
            dur_text = '—'
            ini_text = '—'
            fin_text = '—'

        rows.append(
            f'<tr class="{cls}">'
            f'<td>{escape(p.get("item") or "")}</td>'
            f'<td>{escape(p.get("descripcion") or "")}</td>'
            f'<td class="r">{dur_text}</td>'
            f'<td class="r">{ini_text}</td>'
            f'<td class="r">{fin_text}</td>'
            f'<td class="c">{escape(pred)}</td>'
            f'<td>{bar_html}</td>'
            f'</tr>'
        )

    parts.append(
        '<table class="data" width="100%">'
        '<thead><tr>'
        '<th style="width:50pt">Ítem</th>'
        '<th>Descripción</th>'
        '<th style="width:42pt;text-align:right">Dur.&nbsp;(d)</th>'
        '<th style="width:42pt;text-align:right">Inicio</th>'
        '<th style="width:36pt;text-align:right">Fin</th>'
        '<th style="width:55pt;text-align:center">Pred.</th>'
        '<th style="width:210pt">Diagrama Gantt</th>'
        '</tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table>'
    )

    parts.append(
        f'<p style="font-size:8.5pt;color:{SLATE_500};font-style:italic;margin-top:6pt">'
        f'Escala: barras proporcionales a {max_dia} días. '
        f'<font color="{o}"><b>■</b></font> Tarea regular &nbsp;'
        f'<font color="#7A36B1"><b>■</b></font> Hito &nbsp;'
        f'<font color="#3689E6"><b>■</b></font> Inicio de fase &nbsp;'
        f'<font color="#3A9104"><b>■</b></font> Fin de fase'
        f'</p>'
    )

    return "\n".join(parts)


def _html_insumos(pid: int, proy: dict) -> str:
    o, od, _os = _brand_colors()
    sym = _moneda_simbolo(proy.get('moneda') or 'Soles')
    dec = get_decimales_ppto()
    conn = get_db()
    insumos = get_insumos_proyecto(conn, pid)
    conn.close()

    parts = ['<h2>Relación de Insumos</h2>']

    if not insumos:
        parts.append('<p style="color:#888;font-style:italic">Sin insumos.</p>')
        return "\n".join(parts)

    # Agrupar por tipo
    por_tipo = {'MO': [], 'MAT': [], 'EQ': [], 'SC': []}
    for r in insumos:
        t = r.get('tipo') if r.get('tipo') in por_tipo else 'MAT'
        por_tipo[t].append(r)

    # Subtotales
    subtotal_tipo = {}
    for t, lst in por_tipo.items():
        subtotal_tipo[t] = sum((x.get('parcial_total') or 0) for x in lst)
    total_general = sum(subtotal_tipo.values())

    # ── Detalle: UNA tabla única con barras suaves por tipo
    #    (mismas columnas alineadas entre MO/MAT/EQ/SC + diferenciación sutil
    #    como el header de las cards de ACU/Metrados)
    TIPO_COLOR = {'MO': MO_COLOR, 'MAT': MAT_COLOR, 'EQ': EQ_COLOR, 'SC': SC_COLOR}
    TIPO_SOFT  = {'MO': '#FEF3DD',   # ámbar suave
                  'MAT': '#E3F4EA',  # verde suave
                  'EQ': '#ECEEF1',   # slate suave
                  'SC': '#F1E7F9'}   # morado suave
    all_rows = []
    primer_tipo = True
    for t, label in [('MO', 'Mano de Obra'), ('MAT', 'Materiales'),
                     ('EQ', 'Equipos y Herramientas'),
                     ('SC', 'Sub-contratos / Servicios')]:
        lst = por_tipo.get(t, [])
        if not lst:
            continue

        # Espaciador antes de cada sección (excepto la primera)
        if not primer_tipo:
            all_rows.append(
                '<tr><td colspan="6" style="border:none;padding:0;font-size:10pt">&nbsp;</td></tr>'
            )
        primer_tipo = False

        # Barra de sección — fondo suave del tipo, texto del color del tipo
        bar_color = TIPO_COLOR[t]
        bar_soft  = TIPO_SOFT[t]
        all_rows.append(
            f'<tr><td colspan="6" style="'
            f'background:{bar_soft};color:{bar_color};'
            f'padding:8pt 12pt;'
            f'font-size:11pt;font-weight:700;letter-spacing:0.6pt;'
            f'border:none;">'
            f'{t.upper()} &nbsp;&nbsp; {escape(label.upper())}'
            f'</td></tr>'
        )

        for j, r in enumerate(lst):
            cls = "alt" if (j % 2) else ""
            all_rows.append(
                f'<tr class="{cls}">'
                f'<td>{escape(r.get("codigo") or "")}</td>'
                f'<td>{escape(r.get("descripcion") or "")}</td>'
                f'<td class="c">{escape(r.get("unidad") or "")}</td>'
                f'<td class="r">{_fmt(r.get("cantidad_total"), 4)}</td>'
                f'<td class="r">{_fmt(r.get("precio"), dec)}</td>'
                f'<td class="r">{_fmt(r.get("parcial_total"), dec)}</td>'
                f'</tr>'
            )
        # Subtotal del tipo — color del tipo en texto + borde slate sutil
        all_rows.append(
            f'<tr style="background:white;border-top:1pt solid {SLATE_700}">'
            f'<td colspan="5" class="r" style="font-weight:700;color:{bar_color}">'
            f'Subtotal {escape(label)}</td>'
            f'<td class="r" style="font-weight:700;color:{bar_color}">'
            f'{_fmt(subtotal_tipo.get(t, 0), dec)}</td>'
            f'</tr>'
        )

    # Header con bg accent_soft (espejo del Presupuesto): la fila de
    # cabecera (Código · Descripción · ...) actúa como divisor visual.
    parts.append(
        '<table class="data" width="100%">'
        '<thead><tr>'
        f'<th style="width:60pt;background:{_os}">Código</th>'
        f'<th style="background:{_os}">Descripción</th>'
        f'<th style="width:35pt;text-align:center;background:{_os}">Und</th>'
        f'<th style="width:65pt;text-align:right;background:{_os}">Cantidad</th>'
        f'<th style="width:60pt;text-align:right;background:{_os}">Precio</th>'
        f'<th style="width:75pt;text-align:right;background:{_os}">Parcial</th>'
        '</tr></thead>'
        f'<tbody>{"".join(all_rows)}</tbody></table>'
    )

    # ── Resumen final (al pie del reporte): subtotales por tipo + CD
    parts.append('<p style="margin-top:28pt">&nbsp;</p>')
    parts.append(f'<h3>Resumen por Tipo de Insumo</h3>')
    resumen_rows = []
    for t, label in [('MO', 'Mano de Obra'), ('MAT', 'Materiales'),
                     ('EQ', 'Equipos / Herramientas'),
                     ('SC', 'Sub-contratos / Servicios')]:
        v = subtotal_tipo.get(t, 0)
        pct = (v / total_general * 100) if total_general else 0
        pill_cls = {'MO': 'pill-mo', 'MAT': 'pill-mat',
                    'EQ': 'pill-eq', 'SC': 'pill-sc'}[t]
        resumen_rows.append(
            f'<tr>'
            f'<td><span class="pill {pill_cls}">{t}</span> &nbsp;{escape(label)}</td>'
            f'<td class="r" style="font-weight:600">{sym} {_fmt(v, dec)}</td>'
            f'<td class="r">{pct:.1f}%</td>'
            f'</tr>'
        )
    parts.append(
        '<table class="data" width="100%">'
        '<thead><tr>'
        f'<th width="70%" style="background:{_os}">Tipo</th>'
        f'<th width="20%" style="text-align:right;background:{_os}">Subtotal</th>'
        f'<th width="10%" style="text-align:right;background:{_os}">% del CD</th>'
        '</tr></thead>'
        f'<tbody>{"".join(resumen_rows)}'
        f'<tr style="background:white;color:{od}">'
        f'<td style="font-weight:700;'
        f' border-top:1.5pt solid {SLATE_700};border-bottom:1.5pt solid {SLATE_700}">'
        f'TOTAL COSTO DIRECTO</td>'
        f'<td class="r" style="font-weight:700;'
        f' border-top:1.5pt solid {SLATE_700};border-bottom:1.5pt solid {SLATE_700}">'
        f'{sym} {_fmt(total_general, dec)}</td>'
        f'<td class="r" style="font-weight:700;'
        f' border-top:1.5pt solid {SLATE_700};border-bottom:1.5pt solid {SLATE_700}">'
        f'100.0%</td></tr>'
        '</tbody></table>'
    )
    return "\n".join(parts)


def _png_donut_bytes(mo: float, mat: float, eq: float,
                     sc: float = 0.0, size: int = 220) -> bytes:
    """Devuelve los bytes PNG del donut (reusable para Word/HTML/etc.)."""
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QImage, QPainter, QPen
    total = (mo or 0) + (mat or 0) + (eq or 0) + (sc or 0)
    img = QImage(size * 2, size * 2, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.Antialiasing, True)
    rect_outer = QRectF(8, 8, size * 2 - 16, size * 2 - 16)
    cx = cy = size
    r_inner = (size - 8) * 0.55
    if total <= 0:
        painter.setPen(QPen(QColor("#94A3B8"), 4))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(rect_outer)
    else:
        start_angle_deg = 90.0
        for value, color in [(mo, MO_COLOR), (mat, MAT_COLOR),
                              (eq, EQ_COLOR), (sc, SC_COLOR)]:
            if value <= 0:
                continue
            span_deg = -(value / total) * 360.0
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(color))
            painter.drawPie(rect_outer,
                            int(start_angle_deg * 16),
                            int(span_deg * 16))
            start_angle_deg += span_deg
        painter.setPen(Qt.NoPen)
        painter.setBrush(Qt.white)
        painter.drawEllipse(QPointF(cx, cy), r_inner, r_inner)
    painter.end()
    img = img.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(ba)


def _png_donut_b64(mo: float, mat: float, eq: float,
                    sc: float = 0.0, size: int = 220) -> str:
    """Genera un donut como PNG en base64 (QPainter), embebible en HTML <img>."""
    import base64
    import math
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QImage, QPainter, QPen

    total = (mo or 0) + (mat or 0) + (eq or 0) + (sc or 0)
    img = QImage(size * 2, size * 2, QImage.Format_ARGB32)  # 2x para nitidez
    img.fill(Qt.transparent)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.Antialiasing, True)

    rect_outer = QRectF(8, 8, size * 2 - 16, size * 2 - 16)
    cx = cy = size  # centro
    r_inner = (size - 8) * 0.55

    if total <= 0:
        painter.setPen(QPen(QColor("#94A3B8"), 4))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(rect_outer)
    else:
        start_angle_deg = 90.0   # 12 en punto
        for value, color in [(mo, MO_COLOR), (mat, MAT_COLOR),
                              (eq, EQ_COLOR), (sc, SC_COLOR)]:
            if value <= 0:
                continue
            span_deg = -(value / total) * 360.0   # sentido horario
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(color))
            # Qt drawPie usa ángulos en 1/16 de grado
            painter.drawPie(
                rect_outer,
                int(start_angle_deg * 16),
                int(span_deg * 16),
            )
            start_angle_deg += span_deg

        # Hueco central (donut)
        painter.setPen(Qt.NoPen)
        painter.setBrush(Qt.white)
        painter.drawEllipse(QPointF(cx, cy), r_inner, r_inner)

    painter.end()

    # Reducir a tamaño deseado
    img = img.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)

    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    b64 = bytes(ba.toBase64()).decode('ascii')
    return f'<img src="data:image/png;base64,{b64}" width="{size}" height="{size}"/>'


def _build_pie_rows(pid: int, cd: float) -> list:
    """Construye las filas del pie de presupuesto para el reporte,
    espejando exactamente `_filas_resumen` de ProyectoView.

    Devuelve lista de tuplas (label, monto, cls) donde cls es:
      'sub'  → subtotal (CD, Sub Total)
      ''     → rubro normal (GG, Util, IGV, supervisión…)
      'gran' → PRESUPUESTO TOTAL (último)
    """
    conn = get_db()
    rubros = conn.execute(
        "SELECT * FROM pie_rubros WHERE proyecto_id=? AND activo=1 ORDER BY orden",
        (pid,)
    ).fetchall()
    gg_items = conn.execute(
        "SELECT * FROM gastos_generales WHERE proyecto_id=? ORDER BY orden",
        (pid,)
    ).fetchall()
    conn.close()

    def _col(row, name, default=None):
        """Lee una columna de sqlite3.Row sin .get(). Devuelve default si la
        columna no existe en el esquema (migraciones tolerantes)."""
        try:
            v = row[name]
            return v if v is not None else default
        except (IndexError, KeyError):
            return default

    filas = [('Costo Directo', cd, 'sub')]
    acum = cd
    last_sub = cd
    for rub in rubros:
        tipo = rub['tipo']
        pct = rub['pct'] or 0
        cod = rub['codigo']
        nombre = rub['nombre']
        mostrar_pct = bool(_col(rub, 'mostrar_pct', 1))
        if tipo == 'subtotal':
            last_sub = acum
            filas.append((nombre, acum, 'sub'))
        elif tipo == 'pct_sub':
            val = last_sub * pct / 100
            acum += val
            etiqueta = f"{nombre} ({pct:g}%)" if mostrar_pct else nombre
            filas.append((etiqueta, val, ''))
        elif tipo == 'pct_cd':
            val = cd * pct / 100
            acum += val
            etiqueta = f"{nombre} ({pct:g}%)" if mostrar_pct else nombre
            filas.append((etiqueta, val, ''))
        else:  # rubro con detalle (GG, Supervisión, etc.)
            manual = next((i for i in gg_items
                           if i['rubro'] == cod and i['tipo'] == 'manual'), None)
            if manual:
                val = manual['precio'] or 0
            else:
                items_r = [i for i in gg_items
                           if i['rubro'] == cod and i['tipo'] == 'item']
                if items_r:
                    val = sum(
                        (i['cantidad'] or 0)
                        * ((i['pct_participacion'] or 100) / 100)
                        * (i['precio'] or 0)
                        for i in items_r
                    )
                else:
                    val = cd * pct / 100
            acum += val
            # El monto de GG/Supervisión sale del detalle (o valor manual),
            # así que el `pct` guardado del rubro puede no corresponder. El
            # porcentaje mostrado se deriva del monto real sobre el CD para
            # que siempre sea coherente con la cifra de la derecha.
            eff_pct = (val / cd * 100) if cd else 0
            etiqueta = f"{nombre} ({eff_pct:g}%)" if (mostrar_pct and eff_pct) else nombre
            filas.append((etiqueta, val, ''))
    filas.append(('PRESUPUESTO TOTAL', acum, 'gran'))
    return filas


def _todo_costo_factor_pie(pid: int, cd: float):
    """Para el «Presupuesto para Cliente»: calcula el factor de mayoración que
    disuelve gastos generales + utilidad (y cualquier otro rubro que NO sea
    impuesto) dentro del precio unitario de cada partida, dejando el IGV/IVA
    SIEMPRE abajo, separado — porque es un impuesto de ley que el cliente debe
    ver. Así se oculta el margen del usuario pero el impuesto queda transparente.

    Devuelve `(factor, pie_rows)`:
      - `factor`   = (total − impuestos) / cd   (1.0 si cd == 0)
      - `pie_rows` = tuplas `(label, monto, cls)` a mostrar bajo la tabla:
        Sub Total (= CD + GG + utilidad, ya disueltos en los PU) + IGV/IVA +
        PRESUPUESTO TOTAL. Si no hay impuesto, solo el total final.
    """
    import re
    pie = _build_pie_rows(pid, cd)
    if not pie:
        return (1.0, [('PRESUPUESTO TOTAL', cd, 'gran')])
    total = pie[-1][1] or 0
    # Filas de impuesto (IGV/IVA) — se mantienen abajo, separadas del PU.
    # `\b` evita falsos positivos (p.ej. «IVA» dentro de otra palabra).
    es_tax = lambda lbl: bool(re.search(r'\b(IGV|IVA)\b', (lbl or '').upper()))
    tax_rows = [(lbl, val, cls) for (lbl, val, cls) in pie
                if cls not in ('sub', 'gran') and es_tax(lbl)]
    tax_total = sum(v for (_l, v, _c) in tax_rows)
    # Base = todo lo que NO es impuesto (CD + GG + utilidad + …) → va al PU.
    base = total - tax_total
    factor = (base / cd) if cd else 1.0
    if tax_rows:
        pie_rows = ([('Sub Total', base, 'sub')] + tax_rows
                    + [('PRESUPUESTO TOTAL', total, 'gran')])
    else:
        pie_rows = [('PRESUPUESTO TOTAL', total, 'gran')]
    return (factor, pie_rows)


def _html_gastos_generales(pid: int, proy: dict, totales: dict) -> str:
    """Desagregado de Gastos Generales — espeja la hoja Excel
    `_hoja_gastos_generales`: planilla por rubro con su detalle
    (N° personas × tiempo × %participación × precio) y los subtotales que
    componen el pie del presupuesto."""
    o, od, _os = _brand_colors()
    from core.exporter import _calcular_rubros_pie
    sym = _moneda_simbolo(proy.get('moneda') or 'Soles')
    dec = get_decimales_ppto()
    cd  = totales.get('cd', 0) or 0

    conn = get_db()
    rubros_pie, total_final = _calcular_rubros_pie(conn, pid, cd)

    parts = ['<h2>Desagregado del Pie de Presupuesto</h2>']

    def _fila_resumen(label, monto, bold=False, top=False):
        peso = '700' if bold else '400'
        bt = f'border-top:1pt solid {SLATE_700};' if top else ''
        return (
            f'<table width="100%" style="margin:2pt 0"><tr>'
            f'<td style="padding:4pt 8pt;font-weight:{peso};color:{SLATE_900};{bt}">'
            f'{escape(label)}</td>'
            f'<td align="right" width="170" style="padding:4pt 8pt;'
            f'font-weight:{peso};color:{SLATE_900};{bt}">{sym} {_fmt(monto, dec)}</td>'
            f'</tr></table>'
        )

    # Costo Directo — base del desagregado
    parts.append(_fila_resumen('COSTO DIRECTO', cd, bold=True))

    # Sin pie configurado → fallback: GG como % plano del CD
    if not rubros_pie:
        gf  = totales.get('gf', 0) or 0
        pct = (gf / cd * 100) if cd else 0
        parts.append(_fila_resumen(
            f'GASTOS GENERALES ({pct:g}%)' if pct else 'GASTOS GENERALES',
            gf, bold=True))
        conn.close()
        return ''.join(parts)

    for rub in rubros_pie:
        tipo = rub['tipo']

        # Rubros con detalle (personal/insumos): tipo 'rubro' con ítems.
        if tipo == 'rubro' and rub.get('has_items'):
            # Título de rubro en rojo (#B71C1C) para diferenciarlo de los grupos
            # y los items. Mismo rojo del título N1 de Presupuesto.
            parts.append(
                f'<p style="margin:12pt 0 4pt 0;font-size:10pt;font-weight:700;'
                f'color:#B71C1C">{escape(rub["nombre"].upper())}</p>'
            )
            gg_items = conn.execute(
                "SELECT * FROM gastos_generales WHERE proyecto_id=? AND rubro=? "
                "ORDER BY orden, id",
                (pid, rub['codigo'])
            ).fetchall()
            rows = []
            z = 0
            grupo_activo = False
            # Sangría colgante para los items (tab). QTextDocument ignora
            # `padding-left`/`margin-left` de celda → tabla-espaciador anidada
            # (ver gotcha). Items bajo un grupo se indentan un nivel.
            def _ind(depth, inner):
                if depth <= 0:
                    return inner
                return (
                    '<table border="0" cellspacing="0" cellpadding="0"'
                    ' width="100%"><tr>'
                    f'<td width="{depth * 16}" style="border:none;padding:0;'
                    'background:transparent"></td><td style="border:none;'
                    f'padding:0;background:transparent">{inner}</td></tr></table>'
                )
            for item in gg_items:
                it = dict(item)
                if it.get('tipo') == 'grupo':
                    grupo_activo = True
                    rows.append(
                        f'<tr style="background:white">'
                        f'<td colspan="6" style="font-weight:700;color:{od};'
                        f'padding-top:3pt;text-decoration:underline">'
                        f'{escape(it.get("descripcion") or "")}</td>'
                        f'</tr>'
                    )
                    continue
                if it.get('tipo') != 'item':
                    continue
                pctp = it.get('pct_participacion') or 100
                cant = it.get('cantidad') or 0
                pr_  = it.get('precio') or 0
                parcial = cant * (pctp / 100) * pr_
                cls = 'alt' if (z % 2) else ''
                _d = 1 if grupo_activo else 0
                rows.append(
                    f'<tr class="{cls}">'
                    f'<td>{_ind(_d, escape(it.get("descripcion") or ""))}</td>'
                    f'<td class="c">{escape(it.get("unidad") or "")}</td>'
                    f'<td class="r">{_fmt(pctp, 2)}</td>'
                    f'<td class="r">{_fmt(cant, 2) if cant else ""}</td>'
                    f'<td class="r">{_fmt(pr_, dec)}</td>'
                    f'<td class="r">{_fmt(parcial, dec)}</td>'
                    f'</tr>'
                )
                z += 1
            # Subtotal del rubro
            rows.append(
                f'<tr style="background:white;border-top:1pt solid {SLATE_700}">'
                f'<td colspan="5" class="r" style="font-weight:700;color:{od}">'
                f'{escape(rub["nombre"].upper())}</td>'
                f'<td class="r" style="font-weight:700;color:{od}">'
                f'{sym} {_fmt(rub["valor"], dec)}</td>'
                f'</tr>'
            )
            parts.append(
                '<table class="data" width="100%">'
                '<thead><tr>'
                f'<th width="34%" style="background:{_os}">Descripción</th>'
                f'<th width="10%" align="center" style="background:{_os}">Unidad</th>'
                f'<th width="14%" align="right" style="background:{_os}">% Particip.</th>'
                f'<th width="12%" align="right" style="background:{_os}">Cantidad</th>'
                f'<th width="14%" align="right" style="background:{_os}">Precio</th>'
                f'<th width="16%" align="right" style="background:{_os}">Total</th>'
                '</tr></thead>'
                f'<tbody>{"".join(rows)}</tbody></table>'
            )
            continue

        # Líneas de resumen (subtotales y porcentajes planos).
        mp  = rub.get('mostrar_pct', 1)
        if tipo in ('pct_cd', 'pct_sub'):
            pct = rub.get('pct') or 0
            label = f'{rub["nombre"].upper()} ({pct:g}%)' if (mp and pct) else rub['nombre'].upper()
            parts.append(_fila_resumen(label, rub['valor']))
        elif tipo == 'rubro':            # rubro sin ítems → % real sobre CD
            pct = rub.get('pct_real') or 0
            label = f'{rub["nombre"].upper()} ({pct:g}%)' if (mp and pct) else rub['nombre'].upper()
            parts.append(_fila_resumen(label, rub['valor'], bold=True))
        else:                            # subtotal
            parts.append(_fila_resumen(rub['nombre'].upper(), rub['valor'], bold=True))

    conn.close()
    parts.append(_fila_resumen('COSTO TOTAL DE OBRA', total_final, bold=True, top=True))
    return ''.join(parts)


def _html_resumen_ejecutivo(pid: int, proy: dict, items: list, totales: dict) -> str:
    o, od, _os = _brand_colors()
    sym = _moneda_simbolo(proy.get('moneda') or 'Soles')
    dec = get_decimales_ppto()
    conn = get_db()
    insumos = get_insumos_proyecto(conn, pid)
    conn.close()

    # Totales por tipo
    tipo_total = {'MO': 0.0, 'MAT': 0.0, 'EQ': 0.0, 'SC': 0.0}
    for r in insumos:
        t = r.get('tipo') if r.get('tipo') in tipo_total else 'MAT'
        tipo_total[t] += float(r.get('parcial_total') or 0)

    # Top partidas (no títulos, top 5 por monto)
    hojas = [e for e in items if not e['partida'].get('es_titulo')]
    hojas.sort(key=lambda e: e['total'] or 0, reverse=True)
    top5 = hojas[:5]
    cd = totales['cd'] or 1

    n_partidas = len(hojas)
    n_titulos  = len(items) - n_partidas

    parts = []
    parts.append('<h2>Resumen Ejecutivo</h2>')

    # KPIs en grilla 4 columnas — usando atributos HTML que QTextDocument respeta
    kpis = [
        ('Presupuesto Total', f'{sym} {_fmt(totales["total"], dec)}', 'Todos los conceptos'),
        ('Costo Directo',     f'{sym} {_fmt(totales["cd"], dec)}',
         f'{(totales["cd"]/totales["total"]*100 if totales["total"] else 0):.1f}% del total'),
        ('Partidas',          f'{n_partidas}',  f'{n_titulos} títulos'),
        ('Plazo de Obra',     f'{proy.get("plazo") or 0} d',  proy.get('modalidad') or 'Contrata'),
    ]
    kpi_cells = []
    for label, value, sub in kpis:
        kpi_cells.append(
            # Sin marco, sin barra — puramente tipográficas. Cero ruido
            # visual; la jerarquía la define el peso y tamaño de la fuente.
            f'<td bgcolor="white" width="25%" valign="top"'
            f' style="padding:8pt">'
            f'<p style="color:{SLATE_500};font-size:8pt;margin:0 0 4pt 0;'
            f' letter-spacing:1pt">{escape(label.upper())}</p>'
            f'<p style="color:{SLATE_900};font-size:14pt;font-weight:700;margin:0">{value}</p>'
            f'<p style="color:{SLATE_500};font-size:8pt;margin:4pt 0 0 0;font-style:italic">{escape(sub)}</p>'
            f'</td>'
        )
    parts.append(
        '<table border="0" cellpadding="0" cellspacing="6" width="100%" style="margin-top:18pt">'
        f'<tr>{"".join(kpi_cells)}</tr>'
        '</table>'
    )

    # ── Estructura del presupuesto: títulos de nivel 1 y 2 con sus montos ──
    # Eco-mode: sin fondos sólidos, jerarquía con peso de fuente y bordes.
    estructura_rows = []
    for e in items:
        p = e['partida']
        if not p.get('es_titulo'):
            continue
        niv = int(p.get('nivel') or 1)
        if niv > 2:
            continue   # solo macroestructura
        monto = e['total'] or 0
        # Tabs por nivel en la columna DESCRIPCIÓN. QTextDocument NO respeta
        # `padding-left` por celda como indentación (igual que los bordes
        # verticales) → se usa un prefijo de espacios duros, igual que el Word.
        tab = '&nbsp;' * (8 * (niv - 1))
        if niv == 1:
            peso = 700; color = SLATE_900
        else:
            peso = 400; color = SLATE_500
        estructura_rows.append(
            f'<tr>'
            f'<td width="55" style="padding:4pt 6pt;'
            f' font-weight:{peso};color:{color};'
            f' border-bottom:1px solid {SLATE_100}">'
            f'{escape(p.get("item") or "")}</td>'
            f'<td style="padding:4pt 6pt;'
            f' font-weight:{peso};color:{color};'
            f' border-bottom:1px solid {SLATE_100}">'
            f'{tab}{escape(p.get("descripcion") or "")}</td>'
            f'<td align="right" width="120" style="padding:4pt 8pt;'
            f' font-weight:{peso};color:{color};'
            f' border-bottom:1px solid {SLATE_100}">'
            f'{sym} {_fmt(monto, dec)}</td>'
            f'</tr>'
        )
    if estructura_rows:
        parts.append('<p style="margin-top:36pt">&nbsp;</p>')
        parts.append('<h3>Estructura del Presupuesto</h3>')
        parts.append(
            '<table border="0" cellpadding="0" cellspacing="0" width="100%"'
            ' style="margin-top:14pt">'
            f'{"".join(estructura_rows)}</table>'
        )

    # ── Pie de presupuesto — refleja exactamente lo configurado en la
    # pestaña «Pie» del proyecto (lee `pie_rubros` activos + `gastos_generales`).
    pie_rows = _build_pie_rows(pid, totales.get('cd', 0))
    pie_html = []
    # Eco-mode: bordes para jerarquía, sin fondos sólidos.
    # Total: solo borde superior grueso + texto bold.
    for label, val, cls in pie_rows:
        if cls == 'gran':
            color = SLATE_900; peso = 700; sz = "11pt"
            border = f"border-top:2pt solid {SLATE_700};" \
                     f" border-bottom:2pt solid {SLATE_700}"
        elif cls == 'sub':
            color = SLATE_900; peso = 600; sz = "10pt"
            border = f"border-top:1px solid {SLATE_300};" \
                     f" border-bottom:1px solid {SLATE_300}"
        else:
            color = SLATE_700; peso = 400; sz = "10pt"
            border = f"border-bottom:1px solid {SLATE_100}"
        pie_html.append(
            f'<tr>'
            f'<td style="padding:4pt 8pt;font-size:{sz};font-weight:{peso};'
            f' color:{color};{border}">{escape(label)}</td>'
            f'<td align="right" style="padding:4pt 8pt;font-size:{sz};'
            f' font-weight:{peso};color:{color};width:120pt;{border}">'
            f'{sym} {_fmt(val, dec)}</td>'
            f'</tr>'
        )
    # El pie sin título (los nombres de los rubros ya son auto-explicativos)
    parts.append('<p style="margin-top:36pt">&nbsp;</p>')
    parts.append(
        '<table border="0" cellpadding="0" cellspacing="0" width="100%">'
        f'{"".join(pie_html)}</table>'
    )
    # Monto total escrito en letras (formato peruano de obras)
    total_letras = _monto_en_letras(totales.get('total', 0),
                                     proy.get('moneda') or 'Soles')
    parts.append(
        f'<p style="margin-top:6pt;font-style:italic;color:{SLATE_700};'
        f' font-size:9pt">Son: {escape(total_letras)}.</p>'
    )

    # Distribución MO / MAT / EQ / SC con donut + tabla
    donut = _png_donut_b64(
        tipo_total['MO'], tipo_total['MAT'], tipo_total['EQ'],
        sc=tipo_total['SC'], size=180,
    )
    leyenda_rows = []
    total_cd = sum(tipo_total.values()) or 1
    leyenda_tipos = [
        ('MO',  'Mano de Obra',   MO_COLOR),
        ('MAT', 'Materiales',     MAT_COLOR),
        ('EQ',  'Equipos',        EQ_COLOR),
    ]
    if tipo_total['SC'] > 0:
        leyenda_tipos.append(('SC', 'Sub-contratos', SC_COLOR))
    for k, label, color in leyenda_tipos:
        v = tipo_total[k]
        pct = v / total_cd * 100
        bar_w = max(0, min(100, pct))
        leyenda_rows.append(
            f'<tr>'
            f'<td valign="middle" width="100" style="padding:5pt 4pt">'
            f'<font color="{color}"><b>■</b></font> &nbsp;<b>{escape(label)}</b>'
            f'</td>'
            f'<td valign="middle" width="180" style="padding:5pt 4pt">'
            f'<table border="0" cellpadding="0" cellspacing="0" width="160"'
            f' bgcolor="{SLATE_100}" height="10">'
            f'<tr><td bgcolor="{color}" width="{bar_w:.1f}%">&nbsp;</td>'
            f'<td bgcolor="{SLATE_100}">&nbsp;</td></tr></table>'
            f'</td>'
            f'<td align="right" valign="middle" style="padding:5pt 4pt;font-variant-numeric:tabular-nums"><b>{sym} {_fmt(v, dec)}</b></td>'
            f'<td align="right" valign="middle" width="60" style="padding:5pt 4pt">{pct:.1f}%</td>'
            f'</tr>'
        )
    parts.append(
        '<div class="pagebreak"></div>'
        '<h3>Distribución del Costo Directo</h3>'
        '<p style="margin-top:8pt">&nbsp;</p>'
        f'<p align="center">{donut}</p>'
        '<p style="margin-top:8pt">&nbsp;</p>'
        '<table border="0" cellpadding="0" cellspacing="0" width="100%">'
        f'{"".join(leyenda_rows)}'
        '</table>'
    )

    # Top 5 partidas — con separador visual.
    # Mismo styling que la tabla del Presupuesto (class="data" + width="100%"
    # inline para forzar que QTextDocument respete el ancho del 100%).
    parts.append('<p style="margin-top:36pt">&nbsp;</p>')
    parts.append('<h3>Top 5 Partidas por Monto</h3>')
    parts.append('<p style="margin-top:8pt">&nbsp;</p>')
    if not top5:
        parts.append('<p style="color:#888;font-style:italic">Sin partidas valorizadas.</p>')
    else:
        rows = []
        for i, e in enumerate(top5):
            p = e['partida']
            pct = (e['total'] or 0) / cd * 100 if cd else 0
            cls = "alt" if (i % 2) else ""
            rows.append(
                f'<tr class="{cls}">'
                f'<td class="c" style="font-weight:600;color:{od}">#{i+1}</td>'
                f'<td>{escape(p.get("item") or "")}</td>'
                f'<td>{escape(p.get("descripcion") or "")}</td>'
                f'<td class="r">{sym} {_fmt(e["total"], dec)}</td>'
                f'<td class="r">{pct:.1f}%</td>'
                f'</tr>'
            )
        parts.append(
            '<table class="data" width="100%">'
            '<thead><tr>'
            '<th style="width:30pt;text-align:center">#</th>'
            '<th style="width:60pt">Ítem</th>'
            '<th>Descripción</th>'
            '<th style="width:90pt;text-align:right">Parcial</th>'
            '<th style="width:55pt;text-align:right">% CD</th>'
            '</tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table>'
        )
    return "\n".join(parts)


# ══════════════════════════════════════════════════════════════════════════════
# Renderizador a PDF — encabezado + contenido + pie con paginación
# ══════════════════════════════════════════════════════════════════════════════

class _PdfRenderer:
    """Renderiza HTML a PDF con encabezado y pie de página dibujados con QPainter."""

    # Mapa de tamaños de papel (pulgadas, ancho × alto en retrato)
    PAPER_SIZES_IN = {
        'A4':      (8.27, 11.69),
        'A3':      (11.69, 16.54),
        'A2':      (16.54, 23.39),
        'A1':      (23.39, 33.11),
        'A0':      (33.11, 46.81),
        'Letter':  (8.5,  11.0),
        'Tabloid': (11.0, 17.0),
    }

    def __init__(self, proyecto: dict, titulo_reporte: str, *, with_cover: bool = True,
                  paper: str = 'A4', orient: str = 'portrait',
                  pie_offset: int = 0, pie_total: int | None = None):
        self.proyecto = proyecto
        self.titulo = titulo_reporte
        self.with_cover = with_cover
        self.formato = get_formato()
        self.paper = paper if paper in self.PAPER_SIZES_IN else 'A4'
        self.orient = 'landscape' if str(orient).lower() == 'landscape' else 'portrait'
        # Numeración continua: si `pie_total` se especifica, el footer usa
        # `page_index + pie_offset + 1` de `pie_total`. Útil para el Reporte
        # Completo que mergea varios PDFs y quiere paginación global.
        self.pie_offset = int(pie_offset or 0)
        self.pie_total  = int(pie_total) if pie_total else None
        # Título alternativo SOLO para la portada (eyebrow). Permite que el
        # Reporte Completo muestre el nombre de la sección en el encabezado
        # de cada página y otro título general en la carátula.
        self.titulo_cover: str | None = None

        # Geometría — escalada al papel y orientación elegidos.
        w_in, h_in = self.PAPER_SIZES_IN[self.paper]
        if self.orient == 'landscape':
            w_in, h_in = h_in, w_in
        self.dpi = 96
        self.page_w = int(w_in * self.dpi)
        self.page_h = int(h_in * self.dpi)
        self.margin_x = int(0.6 * self.dpi)
        self.margin_top_body = int(1.05 * self.dpi)
        self.margin_bot_body = int(0.7 * self.dpi)
        self.header_h = int(0.85 * self.dpi)
        self.footer_h = int(0.5 * self.dpi)

    # --- HTML helpers --------------------------------------------------------

    def _wrap_html(self, body_html: str) -> str:
        return f"<html><head>{_base_css()}</head><body>{body_html}</body></html>"

    def _draw_cover(self, painter: QPainter):
        """Dibuja la portada completa con QPainter — control preciso de centrado."""
        proy = self.proyecto
        cx = self.page_w / 2
        # Si el usuario configuró un color custom (rep_color_marca) lo respetamos;
        # si no, fallback al color de marca actual (naranja o slate sobrio).
        _o, _od, _os = _brand_colors()
        color_marca = QColor(self.formato.get('rep_color_marca') or _o)
        empresa     = self.formato.get('rep_empresa_nombre') or 'ingePresupuestos'

        # Línea superior delgada color marca (en vez de banda llena de 60px)
        painter.fillRect(0, 0, self.page_w, 4, color_marca)

        # Logo opcional a la izquierda en lugar del texto
        logo_drawn = False
        logo_b64 = self.formato.get('rep_logo_b64') or ''
        if logo_b64:
            try:
                from PySide6.QtCore import QByteArray
                from PySide6.QtGui import QImage
                ba = QByteArray.fromBase64(logo_b64.encode('ascii'))
                img = QImage()
                if img.loadFromData(ba):
                    h = 36
                    w = int(img.width() * h / max(1, img.height()))
                    w = min(w, 240)
                    painter.drawImage(QRectF(self.margin_x, 18, w, h), img)
                    logo_drawn = True
            except Exception:
                pass

        if not logo_drawn:
            _o2, _od2, _os2 = _brand_colors()
            f = QFont('Inter', 14); f.setBold(True)
            painter.setFont(f); painter.setPen(color_marca_dk := QColor(self.formato.get('rep_color_marca_dk') or _od2))
            painter.drawText(QRectF(self.margin_x, 18, 300, 30),
                             Qt.AlignVCenter | Qt.AlignLeft, empresa)

        f2 = QFont('Inter', 9)
        painter.setFont(f2); painter.setPen(QColor(SLATE_300))
        painter.drawText(QRectF(0, 18, self.page_w - self.margin_x, 30),
                         Qt.AlignVCenter | Qt.AlignRight, _hoy_formateado())

        # Tipo de reporte (eyebrow)
        y = 160
        f3 = QFont('Inter', 11); f3.setLetterSpacing(QFont.AbsoluteSpacing, 2.0)
        painter.setFont(f3); painter.setPen(QColor(SLATE_500))
        painter.drawText(QRectF(0, y, self.page_w, 20),
                         Qt.AlignCenter, (self.titulo_cover or self.titulo).upper())

        # Línea decorativa color marca
        y += 32
        line_w = 80
        painter.fillRect(int(cx - line_w/2), int(y), line_w, 2, color_marca)

        # Nombre del proyecto (título grande, multi-línea centrado)
        y += 30
        nombre = proy.get('nombre') or '—'
        f4 = QFont('Inter', 22); f4.setBold(True)
        painter.setFont(f4); painter.setPen(QColor(SLATE_900))
        rect_nombre = QRectF(self.margin_x + 20, y,
                             self.page_w - 2 * self.margin_x - 40, 200)
        flags = Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap
        # Calcular alto necesario
        bound = painter.boundingRect(rect_nombre, flags, nombre)
        painter.drawText(rect_nombre, flags, nombre)
        y_after_title = y + max(60, int(bound.height()))

        # Sub-presupuesto opcional
        sub = proy.get('sub_presupuesto') or ''
        if sub:
            y_after_title += 8
            f5 = QFont('Inter', 11); f5.setItalic(True)
            painter.setFont(f5); painter.setPen(QColor(SLATE_500))
            painter.drawText(QRectF(self.margin_x, y_after_title,
                                     self.page_w - 2 * self.margin_x, 22),
                              Qt.AlignCenter, sub)
            y_after_title += 22

        # Tabla de datos del proyecto centrada.
        # En lugar de "Moneda", mostrar el Monto Total del proyecto
        # (la moneda ya queda implícita en el símbolo del monto).
        y = y_after_title + 60
        sym = _moneda_simbolo(proy.get('moneda') or 'Soles')
        dec = get_decimales_ppto()
        monto_total_txt = "—"
        try:
            from core.database import calcular_totales
            pid = proy.get('id')
            if pid is not None:
                _, tot = calcular_totales(int(pid))
                monto_total_txt = f"{sym} {_fmt(tot.get('total', 0), dec)}"
        except Exception:
            pass
        rows = [
            ("Cliente",        proy.get('cliente') or '—'),
            ("Ubicación",      proy.get('ubicacion') or '—'),
            ("Costo al",       proy.get('costo_al') or '—'),
            ("Plazo",          f"{proy.get('plazo') or 0} días calendario"),
            ("Modalidad",      proy.get('modalidad') or 'Contrata'),
            ("Monto Total",    monto_total_txt),
        ]

        f_k = QFont('Inter', 10); f_k.setItalic(True)
        f_v = QFont('Inter', 11); f_v.setBold(True)
        fm_k = QFontMetrics(f_k); fm_v = QFontMetrics(f_v)

        # Anchos de columnas y de bloque. Fijamos un ancho de valor amplio
        # (no truncado) — preferimos WRAP a múltiples líneas para campos
        # largos como "Ubicación" en proyectos públicos peruanos.
        max_k = max(fm_k.horizontalAdvance(k) for k, _ in rows)
        gap = 18
        avail = self.page_w - 2 * self.margin_x - 40
        max_v = avail - max_k - gap
        block_w = max_k + gap + max_v
        block_x = (self.page_w - block_w) / 2
        row_h_min = 22
        line_v = fm_v.lineSpacing()

        # Pre-medir alturas de cada fila con wrap (max 3 líneas por valor)
        row_heights = []
        wrapped_values = []
        max_lines = 3
        for k, v in rows:
            v_text = str(v)
            r_rect = fm_v.boundingRect(
                QRectF(0, 0, max_v, line_v * max_lines).toRect(),
                Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap,
                v_text,
            )
            n_lines = max(1, min(max_lines,
                                  -(-r_rect.height() // line_v)))
            if n_lines > max_lines:
                # Truncar el texto a max_lines × max_v aprox.
                v_text = fm_v.elidedText(v_text, Qt.ElideRight,
                                              int(max_v * max_lines))
                n_lines = max_lines
            wrapped_values.append(v_text)
            row_heights.append(max(row_h_min, n_lines * line_v + 4))

        block_h = sum(row_heights) + 20

        # Marco sutil sin relleno (solo línea fina)
        pen = QPen(QColor(SLATE_300)); pen.setWidth(1)
        painter.setPen(pen); painter.setBrush(Qt.NoBrush)
        painter.drawRect(QRectF(block_x - 18, y - 10,
                                 block_w + 36, block_h))

        ry = y
        for i, ((k, _v), v_text, rh) in enumerate(zip(rows, wrapped_values, row_heights)):
            painter.setFont(f_k); painter.setPen(QColor(SLATE_500))
            painter.drawText(QRectF(block_x, ry, max_k, rh),
                             Qt.AlignLeft | Qt.AlignTop, k)
            painter.setFont(f_v); painter.setPen(QColor(SLATE_900))
            painter.drawText(QRectF(block_x + max_k + gap, ry, max_v, rh),
                              Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap,
                              v_text)
            ry += rh

        # Footer del proyecto
        f_foot = QFont('Inter', 9)
        painter.setFont(f_foot); painter.setPen(QColor(SLATE_300))
        painter.drawText(QRectF(0, self.page_h - 80, self.page_w, 14),
                         Qt.AlignCenter,
                         f"Documento generado el {_hoy_formateado()}")
        f_foot2 = QFont('Inter', 8); f_foot2.setItalic(True)
        painter.setFont(f_foot2)
        sub = self.formato.get('rep_empresa_subtitulo') or 'Sistema de Presupuestos de Obra Pública'
        painter.drawText(QRectF(0, self.page_h - 60, self.page_w, 14),
                         Qt.AlignCenter,
                         f"{empresa} · {sub}")

        # Línea inferior delgada color marca
        painter.fillRect(0, self.page_h - 4, self.page_w, 4, color_marca)

    # --- Pintado de encabezado / pie ----------------------------------------

    def _draw_header(self, painter: QPainter, page_index: int):
        if page_index == 0 and self.with_cover:
            return  # sin encabezado en portada

        _o, _od, _os = _brand_colors()
        color_marca    = QColor(self.formato.get('rep_color_marca') or _o)
        color_marca_dk = QColor(self.formato.get('rep_color_marca_dk') or _od)
        empresa        = self.formato.get('rep_empresa_nombre') or 'ingePresupuestos'
        sub_emp        = self.formato.get('rep_empresa_subtitulo') or 'Presupuestos de Obra Pública'

        # (sin banda naranja superior — ahorra tinta y se ve más limpio)

        # Tres bloques: izq (logo), centro (título reporte), der (costo al)
        y = 14
        left_w  = 175
        right_w = 165

        # Logo opcional o nombre de empresa a la izquierda
        logo_b64 = self.formato.get('rep_logo_b64') or ''
        logo_drawn = False
        if logo_b64:
            try:
                from PySide6.QtCore import QByteArray
                from PySide6.QtGui import QImage
                ba = QByteArray.fromBase64(logo_b64.encode('ascii'))
                img = QImage()
                if img.loadFromData(ba):
                    h = 30
                    w = int(img.width() * h / max(1, img.height()))
                    w = min(w, left_w)
                    painter.drawImage(QRectF(self.margin_x, y, w, h), img)
                    logo_drawn = True
            except Exception:
                pass

        if not logo_drawn:
            painter.setPen(color_marca_dk)
            f = QFont('Inter', 11)
            f.setBold(True)
            painter.setFont(f)
            painter.drawText(QRectF(self.margin_x, y, left_w, 18),
                             Qt.AlignLeft | Qt.AlignVCenter, empresa)

            f2 = QFont('Inter', 7)
            painter.setFont(f2)
            painter.setPen(QColor(SLATE_300))
            painter.drawText(QRectF(self.margin_x, y + 18, left_w, 14),
                             Qt.AlignLeft | Qt.AlignVCenter, sub_emp)

        # Centro: título reporte (en banda visual)
        center_x = self.margin_x + left_w + 12
        center_w = self.page_w - 2 * self.margin_x - left_w - right_w - 24
        f3 = QFont('Inter', 10)
        f3.setBold(True)
        painter.setFont(f3)
        painter.setPen(QColor(SLATE_900))
        rect_titulo = QRectF(center_x, y, center_w, 18)
        painter.drawText(rect_titulo, Qt.AlignCenter | Qt.AlignVCenter, self.titulo)

        # Centro: nombre proyecto (hasta 3 líneas con elide en la última si no cabe)
        MAX_LINES = 3
        f4 = QFont('Inter', 7)
        f4.setItalic(True)
        painter.setFont(f4)
        painter.setPen(QColor(SLATE_500))
        fm = QFontMetrics(f4)
        nombre = (self.proyecto.get('nombre') or '').strip()
        line_h = fm.lineSpacing()
        # Wrap greedy a MAX_LINES líneas; la última se elide si no entra todo
        words = nombre.split()
        lines: list[list[str]] = [[]]
        for w in words:
            test = ' '.join(lines[-1] + [w])
            if fm.horizontalAdvance(test) <= int(center_w):
                lines[-1].append(w)
            else:
                if len(lines) < MAX_LINES:
                    lines.append([w])
                else:
                    # Sobra texto en la última línea — elide al final
                    last = ' '.join(lines[-1] + [w])
                    lines[-1] = [fm.elidedText(last, Qt.ElideRight, int(center_w))]
                    break
        texto_lineas = '\n'.join(' '.join(ws) for ws in lines if ws)
        rect_proy = QRectF(center_x, y + 18, center_w, line_h * MAX_LINES)
        painter.drawText(rect_proy,
                         Qt.AlignHCenter | Qt.AlignTop,
                         texto_lineas)

        # Derecha: solo costo al (cliente lo movemos al pie)
        right_x = self.page_w - self.margin_x - right_w
        f5 = QFont('Inter', 8)
        f5.setBold(True)
        painter.setFont(f5)
        painter.setPen(QColor(SLATE_700))
        painter.drawText(QRectF(right_x, y, right_w, 16),
                         Qt.AlignRight | Qt.AlignVCenter,
                         f"Costo al: {_clean_costo_al(self.proyecto.get('costo_al'))}")
        f6 = QFont('Inter', 7)
        f6.setItalic(True)
        painter.setFont(f6)
        painter.setPen(QColor(SLATE_300))
        modalidad = self.proyecto.get('modalidad') or ''
        painter.drawText(QRectF(right_x, y + 18, right_w, 14),
                         Qt.AlignRight | Qt.AlignVCenter,
                         modalidad)

        # Línea separadora
        pen = QPen(QColor(SLATE_100))
        pen.setWidth(1)
        painter.setPen(pen)
        painter.drawLine(self.margin_x, self.header_h - 8,
                         self.page_w - self.margin_x, self.header_h - 8)

    def _draw_footer(self, painter: QPainter, page_index: int, page_count: int):
        if page_index == 0 and self.with_cover:
            return  # sin pie en portada

        y = self.page_h - self.footer_h + 6
        # Línea separadora
        pen = QPen(QColor(SLATE_100))
        pen.setWidth(1)
        painter.setPen(pen)
        painter.drawLine(self.margin_x, y,
                         self.page_w - self.margin_x, y)

        f = QFont('Inter', 7)
        painter.setFont(f)
        painter.setPen(QColor(SLATE_300))

        # Izquierda: pie izquierdo custom o cliente del proyecto
        pie_izq = self.formato.get('rep_pie_izquierdo') or ''
        if not pie_izq:
            cliente = self.proyecto.get('cliente') or ''
            pie_izq = f"Cliente: {cliente}" if cliente else ''
        if pie_izq:
            fm = QFontMetrics(f)
            elided = fm.elidedText(pie_izq, Qt.ElideRight, 320)
            rect_l = QRectF(self.margin_x, y + 6, 320, 14)
            painter.drawText(rect_l, Qt.AlignLeft | Qt.AlignVCenter, elided)

        # Centro: pie central custom o fecha
        pie_cen = self.formato.get('rep_pie_central') or _hoy_formateado()
        rect_c = QRectF(0, y + 6, self.page_w, 14)
        painter.drawText(rect_c, Qt.AlignCenter, pie_cen)

        # Derecha: pie derecho custom o paginación.
        # Si hay numeración global (pie_total seteado por el Reporte Completo),
        # usamos `index + offset + 1 / pie_total` en vez del local.
        if self.pie_total:
            pie_der = (f"Página {page_index + 1 + self.pie_offset} "
                       f"de {self.pie_total}")
        else:
            pie_der = self.formato.get('rep_pie_derecho') or \
                      f"Página {page_index + 1} de {page_count}"
        rect_r = QRectF(self.page_w - self.margin_x - 160, y + 6, 160, 14)
        painter.drawText(rect_r, Qt.AlignRight | Qt.AlignVCenter, pie_der)

    # --- Render principal ----------------------------------------------------

    def render_to_buffer(self, body_html: str) -> io.BytesIO:
        """Renderiza body_html (HTML del cuerpo del reporte) a un BytesIO con PDF."""
        buf = io.BytesIO()
        # QPdfWriter necesita un QIODevice o ruta. Usamos archivo temporal.
        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
            tmp_path = tmp.name
        try:
            self._render_to_path(body_html, tmp_path)
            with open(tmp_path, 'rb') as f:
                buf.write(f.read())
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        buf.seek(0)
        return buf

    def render_to_file(self, body_html: str, out_path: str):
        self._render_to_path(body_html, out_path)

    def _render_to_path(self, body_html: str, out_path: str):
        writer = QPdfWriter(out_path)
        _qps_map = {
            'A4': QPageSize.A4, 'A3': QPageSize.A3, 'A2': QPageSize.A2,
            'A1': QPageSize.A1, 'A0': QPageSize.A0,
            'Letter': QPageSize.Letter, 'Tabloid': QPageSize.Tabloid,
        }
        _layout = QPageLayout(
            QPageSize(_qps_map.get(self.paper, QPageSize.A4)),
            QPageLayout.Landscape if self.orient == 'landscape' else QPageLayout.Portrait,
            QMarginsF(0, 0, 0, 0)
        )
        writer.setPageLayout(_layout)
        writer.setResolution(self.dpi)
        writer.setPageMargins(QMarginsF(0, 0, 0, 0))
        writer.setTitle(f"{self.titulo} — {self.proyecto.get('nombre','')}")
        writer.setCreator('ingePresupuestos')

        painter = QPainter()
        if not painter.begin(writer):
            raise RuntimeError("No se pudo iniciar QPdfWriter")

        try:
            # ── Pre-render: paginar el cuerpo para saber total de páginas
            doc = QTextDocument()
            doc.setDefaultStyleSheet(_base_css().replace('<style>', '').replace('</style>', ''))
            doc.setHtml(self._wrap_html(body_html))

            body_w = self.page_w - 2 * self.margin_x
            body_h = self.page_h - self.margin_top_body - self.margin_bot_body
            doc.setPageSize(QSizeF(body_w, body_h))
            doc.setDocumentMargin(0)

            n_body_pages = max(1, doc.pageCount())
            total_pages = n_body_pages + (1 if self.with_cover else 0)

            page_idx = 0

            # ── Página 1: portada (si aplica)
            if self.with_cover:
                self._draw_cover(painter)
                page_idx += 1

            # ── Páginas del cuerpo
            for i in range(n_body_pages):
                if page_idx > 0:
                    writer.newPage()

                self._draw_header(painter, page_idx)

                # Dibujar fragmento de página i del documento de cuerpo
                painter.save()
                painter.translate(self.margin_x, self.margin_top_body)
                clip = QRectF(0, 0, body_w, body_h)
                painter.setClipRect(clip)
                # Mover el cuerpo para que muestre la página i
                painter.translate(0, -i * body_h)
                doc.drawContents(painter, QRectF(0, i * body_h, body_w, body_h))
                painter.restore()

                self._draw_footer(painter, page_idx, total_pages)
                page_idx += 1
        finally:
            painter.end()

    # ─── Paginación atómica por chunks ───────────────────────────────────────
    # Para reportes donde cada bloque debe quedar íntegro en una página
    # (especificaciones técnicas: evita gaps cuando una imagen no cabe en el
    # espacio restante y QTextDocument empuja el bloque entero a la sgte página).

    def render_chunks_to_buffer(self, title_html: str, chunks: list) -> io.BytesIO:
        buf = io.BytesIO()
        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
            tmp_path = tmp.name
        try:
            self._render_chunks_to_path(title_html, chunks, tmp_path)
            with open(tmp_path, 'rb') as f:
                buf.write(f.read())
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        buf.seek(0)
        return buf

    def render_chunks_to_file(self, title_html: str, chunks: list, out_path: str):
        self._render_chunks_to_path(title_html, chunks, out_path)

    def _measure_html(self, html: str, body_w: float):
        """Crea un QTextDocument para html y devuelve (doc, altura)."""
        doc = QTextDocument()
        doc.setDefaultStyleSheet(_base_css().replace('<style>', '').replace('</style>', ''))
        doc.setHtml(self._wrap_html(html))
        # Setear ancho fijo; alto "infinito" para medir el contenido completo
        doc.setPageSize(QSizeF(body_w, 1_000_000))
        doc.setDocumentMargin(0)
        h = doc.documentLayout().documentSize().height()
        return doc, h

    def _find_block_break_points(self, doc, body_h: float) -> list:
        """Devuelve [(src_y, h_visible), ...] — uno por página del chunk.
        Cada par indica qué porción del documento natural (sin paginar) se
        renderiza en cada página. Los cortes caen entre bloques y la
        siguiente página arranca en el SIGUIENTE bloque (saltando los gaps
        internos que QTextDocument introduce — p.ej. alrededor de imágenes
        centradas, donde el `<p>` ocupa más alto que la imagen visible)."""
        layout = doc.documentLayout()
        total_h = layout.documentSize().height()
        blocks = []
        block = doc.begin()
        while block.isValid():
            rect = layout.blockBoundingRect(block)
            if rect.height() > 0.1:
                blocks.append((rect.top(), rect.bottom()))
            block = block.next()
        if not blocks:
            return [(0.0, total_h)]

        pages = []
        cur_top = 0.0
        idx = 0
        while idx < len(blocks):
            target = cur_top + body_h
            last_fit_bot = cur_top
            j = idx
            while j < len(blocks):
                top, bot = blocks[j]
                if bot <= target:
                    last_fit_bot = bot
                    j += 1
                else:
                    break
            if j == len(blocks):
                # Todo lo que queda cabe → última página
                pages.append((cur_top, last_fit_bot - cur_top))
                break
            if j == idx:
                # El primer bloque no cabe → forzar corte (caso raro)
                pages.append((cur_top, body_h))
                # Saltar al siguiente bloque para no entrar en bucle infinito
                idx += 1
                if idx < len(blocks):
                    cur_top = blocks[idx][0]
                continue
            # Página: cur_top → last_fit_bot. Próxima arranca en blocks[j].top
            pages.append((cur_top, last_fit_bot - cur_top))
            idx = j
            cur_top = blocks[idx][0]
        if not pages:
            pages.append((0.0, total_h))
        return pages

    def _render_chunks_to_path(self, title_html: str, chunks: list, out_path: str):
        writer = QPdfWriter(out_path)
        _qps_map = {
            'A4': QPageSize.A4, 'A3': QPageSize.A3, 'A2': QPageSize.A2,
            'A1': QPageSize.A1, 'A0': QPageSize.A0,
            'Letter': QPageSize.Letter, 'Tabloid': QPageSize.Tabloid,
        }
        _layout = QPageLayout(
            QPageSize(_qps_map.get(self.paper, QPageSize.A4)),
            QPageLayout.Landscape if self.orient == 'landscape' else QPageLayout.Portrait,
            QMarginsF(0, 0, 0, 0)
        )
        writer.setPageLayout(_layout)
        writer.setResolution(self.dpi)
        writer.setPageMargins(QMarginsF(0, 0, 0, 0))
        writer.setTitle(f"{self.titulo} — {self.proyecto.get('nombre','')}")
        writer.setCreator('ingePresupuestos')

        painter = QPainter()
        if not painter.begin(writer):
            raise RuntimeError("No se pudo iniciar QPdfWriter")

        try:
            body_w = self.page_w - 2 * self.margin_x
            body_h = self.page_h - self.margin_top_body - self.margin_bot_body

            # Separador vertical entre chunks consecutivos en la misma página
            sep_h = 18.0

            # Plan: lista de páginas, cada una con bloques (doc, y_off, src_y, h_visible)
            pages = []
            cur_page = []
            cur_y = 0.0

            for chunk_html in chunks:
                # Medición natural (alto sin paginar)
                nat_doc, nat_h = self._measure_html(chunk_html, body_w)

                if cur_y + nat_h <= body_h:
                    # Cabe entero en el espacio restante
                    cur_page.append((nat_doc, cur_y, 0.0, nat_h))
                    cur_y += nat_h + sep_h
                elif nat_h <= body_h:
                    # No cabe ahora pero sí en una página completa → nueva página
                    if cur_page:
                        pages.append(cur_page)
                    cur_page = [(nat_doc, 0.0, 0.0, nat_h)]
                    cur_y = nat_h + sep_h
                else:
                    # Chunk más alto que una página → slicear el doc natural
                    # por bloques (saltando gaps internos como los que
                    # introducen las imágenes centradas)
                    page_slices = self._find_block_break_points(nat_doc, body_h)
                    # page_slices = [(src_y, visible_h), ...]

                    if cur_page:
                        pages.append(cur_page)
                        cur_page = []
                        cur_y = 0.0

                    for i, (src_y, visible_h) in enumerate(page_slices):
                        cur_page = [(nat_doc, 0.0, src_y, visible_h)]
                        if i < len(page_slices) - 1:
                            pages.append(cur_page)
                            cur_page = []
                    # cur_y queda en la altura ocupada por la última porción
                    cur_y = page_slices[-1][1] + sep_h

            if cur_page:
                pages.append(cur_page)

            if not pages:
                # Sin chunks — al menos una página vacía con header
                pages = [[]]

            total_pages = len(pages) + (1 if self.with_cover else 0)
            page_idx = 0

            # Portada
            if self.with_cover:
                self._draw_cover(painter)
                page_idx += 1

            # Páginas del cuerpo
            for blocks in pages:
                if page_idx > 0:
                    writer.newPage()
                self._draw_header(painter, page_idx)

                for doc, y_off, src_y, h_visible in blocks:
                    painter.save()
                    painter.translate(self.margin_x, self.margin_top_body + y_off)
                    # Clip vertical exacto a la porción visible
                    painter.setClipRect(QRectF(0, 0, body_w, h_visible + 5))
                    # Si es porción de un chunk multi-página, desplazar el origen
                    painter.translate(0, -src_y)
                    doc.drawContents(painter, QRectF(0, src_y, body_w, h_visible))
                    painter.restore()

                self._draw_footer(painter, page_idx, total_pages)
                page_idx += 1
        finally:
            painter.end()


# ══════════════════════════════════════════════════════════════════════════════
# API pública — funciones de generación
# ══════════════════════════════════════════════════════════════════════════════

REPORT_TYPES = [
    ('memoria_descriptiva',     'Memoria Descriptiva',        'Documento descriptivo del proyecto (antecedentes, justificación, localización, metas, presupuesto, plazo).'),
    ('resumen',                 'Resumen Ejecutivo',          'Una página con KPIs, distribución MO/MAT/EQ y top 5 partidas.'),
    ('presupuesto',             'Presupuesto',                'Listado completo de partidas con metrados, precios y totales.'),
    ('gastos_generales',        'Desagregado del Pie de Presupuesto', 'Desglose del pie por rubro (GG, Supervisión, Expediente, Liquidación) con su detalle y subtotales.'),
    ('insumos',                 'Insumos',                    'Recursos consolidados por categoría y montos.'),
    ('acus',                    'Análisis de Costos',         'ACU detallado de cada partida con sus recursos.'),
    ('metrados',                'Hoja de Metrados',           'Detalle por partida con dimensiones y parciales.'),
    ('especificaciones',        'Especificaciones Técnicas',  'Texto técnico de cada partida con especificaciones.'),
    ('cronograma',              'Cronograma — Diagrama Gantt','Tabla y barras Gantt con duración, inicio, fin y predecesoras.'),
    ('cronograma_valorizado',   'Cronograma — Valorizado',    'Distribución del costo por semana o mes a lo largo del plazo.'),
    ('cronograma_adquisiciones','Cronograma — Adquisiciones', 'Insumos a comprar por período, agrupados por categoría.'),
    ('cronograma_curva_s',      'Cronograma — Curva S',       'Avance acumulado del proyecto en porcentaje, gráfico y tabla.'),
    ('presupuesto_cerrado',     'Presupuesto para Cliente',   'Precios unitarios «a todo costo» (incluyen gastos generales y utilidad disueltos en el PU), SIN desglose de costos. Ideal para entregar a clientes.'),
    ('completo',                'Reporte Completo',           'Todos los reportes anteriores en un solo documento.'),
]


# Pasar paper/orient + escala + paginación a _html_cronograma_valorizado
# sin romper firmas preexistentes.
_BUILD_HTML_PAPER: dict = {
    'paper': 'A4', 'orient': 'portrait',
    'escala': 'semana',          # 'semana' | 'mes'
    'periodos_por_pagina': 0,    # -1 = todo en una hoja, 0 = auto, N = N períodos/hoja
    'show_fechas': False,        # True → muestra rango DD-DD mes bajo el label
}


def _section_divider(n: int, nombre: str, descripcion: str = '',
                        first: bool = False) -> str:
    """Mini-portada que separa secciones dentro del Reporte Completo.
    Centra título grande + número de sección + descripción corta en una
    página propia.

    `first=True` para el primer divisor del documento — omite el page-break
    inicial porque el body ya arranca en una página nueva tras la portada.
    Sin eso, se generaría una página en blanco con solo header/footer.
    """
    o, od, _os = _brand_colors()
    desc_html = (
        f'<p align="center" style="color:{SLATE_500}; font-size:11pt;'
        f' font-style:italic;">{descripcion}</p>' if descripcion else ''
    )
    # ~8 párrafos en blanco ≈ 3cm de empuje vertical en A4
    spacer = '<p>&nbsp;</p>' * 8
    leading_break = '' if first else '<div class="pagebreak"></div>'
    return (
        f'{leading_break}'
        f'{spacer}'
        f'<p align="center" style="color:{o}; font-size:12pt;'
        f' font-weight:700;">— SECCIÓN {n} —</p>'
        f'<p>&nbsp;</p>'
        f'<p align="center" style="color:{SLATE_900}; font-size:24pt;'
        f' font-weight:700;">{nombre}</p>'
        f'<p align="center" style="color:{o}; font-size:14pt;">'
        f'━━━━━━━━━━━━━━━</p>'
        f'<p>&nbsp;</p>'
        f'{desc_html}'
        f'<div class="pagebreak"></div>'
    )


def _html_formula_polinomica(pid: int, proy: dict) -> str:
    """Fórmula polinómica: expresión K + tabla de monomios (símbolo,
    descripción, índice INEI, coeficiente, % participación) + total.
    Espejo del export Excel (`exporter.exportar_formula_polinomica`)."""
    conn = get_db()
    try:
        monomios = conn.execute(
            "SELECT * FROM formula_monomios WHERE proyecto_id=? ORDER BY orden",
            (pid,)).fetchall()
    finally:
        conn.close()

    if monomios:
        partes = []
        for mo in monomios:
            k = float(mo['coeficiente'] or 0)
            sim = (mo['simbolo'] or '?')
            partes.append(f"{k:.4f}·({sim}r/{sim}o)")
        expresion = "K = " + " + ".join(partes)
    else:
        expresion = "K = (sin monomios)"

    filas = ''
    suma_k = 0.0
    for i, mo in enumerate(monomios):
        k = float(mo['coeficiente'] or 0)
        suma_k += k
        alt = ' class="alt"' if i % 2 else ''
        filas += (
            f'<tr{alt}>'
            f'<td class="c" style="font-weight:700">{escape(mo["simbolo"] or "")}</td>'
            f'<td>{escape(mo["descripcion"] or "")}</td>'
            f'<td class="c">{escape(mo["indice_inei"] or "—")}</td>'
            f'<td class="r">{k:.4f}</td>'
            f'<td class="r">{k * 100:.2f}%</td>'
            f'</tr>'
        )
    _tot = f'font-weight:700;border-top:1.5pt solid {SLATE_900}'
    filas += (
        f'<tr>'
        f'<td colspan="3" class="r" style="{_tot}">TOTAL</td>'
        f'<td class="r" style="{_tot}">{suma_k:.4f}</td>'
        f'<td class="r" style="{_tot}">{suma_k * 100:.2f}%</td>'
        f'</tr>'
    )

    return (
        f'<p style="font-family:monospace;font-size:11pt;font-weight:700;'
        f'color:{SLATE_900};padding:6pt 0 8pt 0">{escape(expresion)}</p>'
        f'<table class="data" width="100%">'
        f'<tr>'
        f'<th style="text-align:center">Símbolo</th>'
        f'<th>Descripción</th>'
        f'<th style="text-align:center">Índice INEI</th>'
        f'<th style="text-align:right">Coeficiente k</th>'
        f'<th style="text-align:right">% Participación</th>'
        f'</tr>'
        f'{filas}'
        f'</table>'
    )


def _build_html_for(tipo: str, pid: int) -> tuple[str, str, dict]:
    """Devuelve (titulo, body_html, proy) para el tipo de reporte solicitado."""
    proy = _proyecto_info(pid)
    items, totales = calcular_totales(pid)

    if tipo == 'memoria_descriptiva':
        return ('Memoria Descriptiva',
                _html_memoria_descriptiva(pid, proy),
                proy)
    if tipo == 'resumen':
        return ('Resumen Ejecutivo',
                _html_resumen_ejecutivo(pid, proy, items, totales),
                proy)
    if tipo == 'presupuesto':
        return ('Presupuesto',
                _html_presupuesto(pid, proy, items, totales),
                proy)
    if tipo == 'presupuesto_cerrado':
        # Título neutro «Presupuesto» a propósito: el documento que el usuario
        # entrega a su cliente NO debe delatar que es un precio mayorado.
        return ('Presupuesto',
                _html_presupuesto(pid, proy, items, totales, todo_costo=True),
                proy)
    if tipo == 'acus':
        return ('Análisis de Costos Unitarios',
                _html_acus(pid, proy, items),
                proy)
    if tipo == 'metrados':
        return ('Hoja de Metrados',
                _html_metrados(pid, proy, items),
                proy)
    if tipo == 'insumos':
        return ('Relación de Insumos',
                _html_insumos(pid, proy),
                proy)
    if tipo == 'especificaciones':
        return ('Especificaciones Técnicas',
                _html_especificaciones(pid, proy, items),
                proy)
    if tipo == 'gastos_generales':
        return ('Desagregado del Pie de Presupuesto',
                _html_gastos_generales(pid, proy, totales),
                proy)
    if tipo == 'formula_polinomica':
        return ('Fórmula Polinómica',
                _html_formula_polinomica(pid, proy),
                proy)
    if tipo == 'cronograma':
        return ('Cronograma — Diagrama Gantt',
                _html_cronograma(pid, proy, items),
                proy)
    if tipo == 'cronograma_valorizado':
        return ('Cronograma Valorizado',
                _html_cronograma_valorizado(
                    pid, proy, items,
                    escala=_BUILD_HTML_PAPER.get('escala', 'semana'),
                    paper=_BUILD_HTML_PAPER.get('paper', 'A4'),
                    orient=_BUILD_HTML_PAPER.get('orient', 'portrait'),
                    periodos_por_pagina=_BUILD_HTML_PAPER.get('periodos_por_pagina', 0),
                    show_fechas=_BUILD_HTML_PAPER.get('show_fechas', False),
                ),
                proy)
    if tipo == 'cronograma_curva_s':
        return ('Curva S de Avance Físico',
                _html_cronograma_curva_s(pid, proy, items),
                proy)
    if tipo == 'cronograma_adquisiciones':
        return ('Cronograma de Adquisiciones',
                _html_cronograma_adquisiciones(
                    pid, proy, items,
                    escala=_BUILD_HTML_PAPER.get('escala', 'semana'),
                    paper=_BUILD_HTML_PAPER.get('paper', 'A4'),
                    orient=_BUILD_HTML_PAPER.get('orient', 'portrait'),
                    periodos_por_pagina=_BUILD_HTML_PAPER.get('periodos_por_pagina', 0),
                    show_fechas=_BUILD_HTML_PAPER.get('show_fechas', False),
                ),
                proy)
    if tipo == 'completo_nucleo':
        # Núcleo del reporte completo: solo secciones no-cronograma.
        # Los cronogramas (Gantt, Valorizado, Adquisiciones, Curva S) se
        # generan aparte con sus renderizadores ricos y se mergean con pypdf
        # desde reportes_view.
        body = (
            _section_divider(1, 'Memoria Descriptiva',
                              'Documento descriptivo del proyecto: antecedentes, justificación, localización, metas, presupuesto y plazo.',
                              first=True) +
            _html_memoria_descriptiva(pid, proy) +
            _section_divider(2, 'Resumen Ejecutivo',
                              'Una página con KPIs, distribución MO/MAT/EQ y top 5 partidas.') +
            _html_resumen_ejecutivo(pid, proy, items, totales) +
            _section_divider(3, 'Presupuesto',
                              'Listado completo de partidas con metrados, precios y totales.') +
            _html_presupuesto(pid, proy, items, totales) +
            _section_divider(4, 'Desagregado del Pie de Presupuesto',
                              'Desglose del pie por rubro (GG, Supervisión, Expediente, Liquidación) con su detalle y subtotales.') +
            _html_gastos_generales(pid, proy, totales) +
            _section_divider(5, 'Relación de Insumos',
                              'Recursos consolidados por categoría y montos.') +
            _html_insumos(pid, proy) +
            _section_divider(6, 'Análisis de Costos Unitarios',
                              'ACU detallado de cada partida con sus recursos.') +
            _html_acus(pid, proy, items) +
            _section_divider(7, 'Hoja de Metrados',
                              'Detalle por partida con dimensiones y parciales.') +
            _html_metrados(pid, proy, items) +
            _section_divider(12, 'Especificaciones Técnicas',
                              'Texto técnico de cada partida con especificaciones.') +
            _html_especificaciones(pid, proy, items)
        )
        return ('Expediente Técnico — Reporte Completo', body, proy)

    if tipo == 'completo':
        body = (
            _section_divider(1, 'Memoria Descriptiva',
                              'Documento descriptivo del proyecto: antecedentes, justificación, localización, metas, presupuesto y plazo.',
                              first=True) +
            _html_memoria_descriptiva(pid, proy) +
            _section_divider(2, 'Resumen Ejecutivo',
                              'Una página con KPIs, distribución MO/MAT/EQ y top 5 partidas.') +
            _html_resumen_ejecutivo(pid, proy, items, totales) +
            _section_divider(3, 'Presupuesto',
                              'Listado completo de partidas con metrados, precios y totales.') +
            _html_presupuesto(pid, proy, items, totales) +
            _section_divider(4, 'Desagregado del Pie de Presupuesto',
                              'Desglose del pie por rubro (GG, Supervisión, Expediente, Liquidación) con su detalle y subtotales.') +
            _html_gastos_generales(pid, proy, totales) +
            _section_divider(5, 'Relación de Insumos',
                              'Recursos consolidados por categoría y montos.') +
            _html_insumos(pid, proy) +
            _section_divider(6, 'Análisis de Costos Unitarios',
                              'ACU detallado de cada partida con sus recursos.') +
            _html_acus(pid, proy, items) +
            _section_divider(7, 'Hoja de Metrados',
                              'Detalle por partida con dimensiones y parciales.') +
            _html_metrados(pid, proy, items) +
            _section_divider(8, 'Cronograma — Diagrama Gantt',
                              'Tabla y barras Gantt con duración, inicio, fin y predecesoras.') +
            _html_cronograma(pid, proy, items) +
            _section_divider(9, 'Cronograma — Valorizado',
                              'Distribución del costo por semana o mes a lo largo del plazo.') +
            _html_cronograma_valorizado(pid, proy, items) +
            _section_divider(10, 'Cronograma — Adquisiciones',
                              'Insumos a comprar por período, agrupados por categoría.') +
            _html_cronograma_adquisiciones(pid, proy, items) +
            _section_divider(11, 'Cronograma — Curva S',
                              'Avance acumulado del proyecto en porcentaje, gráfico y tabla.') +
            _html_cronograma_curva_s(pid, proy, items) +
            _section_divider(12, 'Especificaciones Técnicas',
                              'Texto técnico de cada partida con especificaciones.') +
            _html_especificaciones(pid, proy, items)
        )
        return ('Expediente Técnico — Reporte Completo', body, proy)

    raise ValueError(f"Tipo de reporte desconocido: {tipo}")


def _especificaciones_chunked(pid: int, with_cover: bool,
                                  paper: str = 'A4', orient: str = 'portrait'):
    """Helper común para especificaciones: prepara proy + chunks + renderer."""
    proy = _proyecto_info(pid)
    items, _ = calcular_totales(pid)
    chunks = chunks_especificaciones(pid, proy, items)
    if not chunks:
        # Fallback al render normal para mostrar el mensaje "sin specs"
        return None
    renderer = _PdfRenderer(proy, 'Especificaciones Técnicas',
                              with_cover=with_cover, paper=paper, orient=orient)
    # El título "Especificaciones Técnicas" ya aparece en el header de cada
    # página — no lo duplicamos en el cuerpo (ahorra una página casi vacía).
    title_html = ''
    return renderer, title_html, chunks


def generar_pdf(tipo: str, pid: int, *, with_cover: bool = True,
                  paper: str = 'A4', orient: str = 'portrait') -> io.BytesIO:
    """Genera un PDF en memoria para el tipo y proyecto dado."""
    _BUILD_HTML_PAPER['paper'] = paper
    _BUILD_HTML_PAPER['orient'] = orient
    if tipo == 'especificaciones':
        prep = _especificaciones_chunked(pid, with_cover, paper=paper, orient=orient)
        if prep is not None:
            renderer, title_html, chunks = prep
            return renderer.render_chunks_to_buffer(title_html, chunks)
    titulo, body, proy = _build_html_for(tipo, pid)
    renderer = _PdfRenderer(proy, titulo, with_cover=with_cover,
                              paper=paper, orient=orient)
    return renderer.render_to_buffer(body)


def generar_pdf_archivo(tipo: str, pid: int, out_path: str, *,
                          with_cover: bool = True,
                          paper: str = 'A4', orient: str = 'portrait',
                          pie_offset: int = 0, pie_total: int | None = None):
    """Genera un PDF y lo guarda en disco.

    `pie_offset` / `pie_total` permiten numeración continua cuando este PDF
    forma parte de un compuesto (Reporte Completo merged): el footer mostrará
    `Página {index+offset+1} de {pie_total}`.
    """
    _BUILD_HTML_PAPER['paper'] = paper
    _BUILD_HTML_PAPER['orient'] = orient
    if tipo == 'especificaciones':
        prep = _especificaciones_chunked(pid, with_cover, paper=paper, orient=orient)
        if prep is not None:
            renderer, title_html, chunks = prep
            renderer.pie_offset = int(pie_offset or 0)
            renderer.pie_total  = int(pie_total) if pie_total else None
            renderer.render_chunks_to_file(title_html, chunks, out_path)
            return
    titulo, body, proy = _build_html_for(tipo, pid)
    renderer = _PdfRenderer(proy, titulo, with_cover=with_cover,
                              paper=paper, orient=orient,
                              pie_offset=pie_offset, pie_total=pie_total)
    renderer.render_to_file(body, out_path)


# ── Control de Obra · reporte de Valorización (generado DESDE la vista, no en
#    el Centro de Reportes — es por período, no del expediente) ───────────────

def _html_valorizacion(val: dict, proy: dict, filas: list, resumen: dict) -> str:
    """Cuerpo HTML de la valorización: tabla Base · Anterior · Actual ·
    Acumulado · Saldo por partida, con subtotales de título y fila TOTAL.
    Reusa las clases CSS de `table.data` (mismo look que el resto de reportes).
    """
    sym = _moneda_simbolo(proy.get('moneda') or 'Soles')
    dm = get_decimales_metrado()
    dp = get_decimales_ppto()
    _o, _od, _os = _brand_colors()

    def m(v):
        return _fmt(v, dm) if v is not None else ""

    def d(v):
        return _fmt(v, dp) if v is not None else ""

    def _fch(iso):
        """yyyy-MM-dd → dd/MM/yyyy para mostrar."""
        if not iso:
            return ""
        p = str(iso).split('-')
        return (f"{p[2]}/{p[1]}/{p[0]}"
                if (len(p) == 3 and len(p[0]) == 4) else str(iso))

    # ── Paleta (espejo del reporte valorizado del cronograma) ───────────────
    BANANA = "#FFF9CC"           # grupo «Actual» (período en curso)
    GHBG = "#F1F5F9"             # fondo de cabeceras de grupo
    GRID = "#CBD5E1"             # gridline sutil
    _NIVEL = {1: '#B71C1C', 2: '#0D52BF', 3: '#6A1B9A', 4: '#AD1457', 5: '#92400E'}
    BORDER_TD = f'border-bottom:0.4pt solid {GRID};'

    parts = []
    parts.append(f'<h2 align="center" style="text-align:center">'
                 f'Valorización N° {val["numero"]}</h2>')
    sub = []
    if val.get('periodo_desde') or val.get('periodo_hasta'):
        sub.append(f'Período: {escape(_fch(val["periodo_desde"]))} '
                   f'al {escape(_fch(val["periodo_hasta"]))}')
    sub.append(f'Avance físico acumulado: <b>{resumen.get("pct_fisico", 0):.2f}%</b>')
    parts.append(f'<p align="center" style="text-align:center;color:{SLATE_700};'
                 f'font-size:10pt">{" &nbsp;·&nbsp; ".join(sub)}</p>')

    # ── Estructura de columnas de valor (con separadores entre grupos) ──────
    SEP = object()
    layout = [('base', 'metr'), ('base', 'pu'), ('base', 'parc'), SEP,
              ('ant', 'metr'), ('ant', 'val'), ('ant', 'pct'), SEP,
              ('act', 'metr'), ('act', 'val'), ('act', 'pct'), SEP,
              ('acu', 'metr'), ('acu', 'val'), ('acu', 'pct'), SEP,
              ('sal', 'metr'), ('sal', 'val'), ('sal', 'pct')]
    groups = [('Contractual (Base)', 3, False), ('Anterior', 3, False),
              ('Actual', 3, True), ('Acumulado', 3, False), ('Saldo', 3, False)]
    _SUB = {'metr': 'Metr.', 'pu': 'P.U.', 'parc': 'Parcial',
            'val': 'Valor.', 'pct': '%'}
    # Ancho fijo por sub-columna (px) — QTextDocument lo respeta mejor que el
    # padding y evita que los números adyacentes se peguen.
    _W = {'metr': 40, 'pu': 46, 'parc': 52, 'val': 52, 'pct': 46}
    SEP_H = ('<th rowspan="2" width="2" style="background:#94A3B8;padding:0;'
             'font-size:1px"></th>')
    SEP_TD = '<td width="2" style="background:#94A3B8;padding:0;font-size:1px"></td>'

    def _valor(f, grp, fld, es_tit):
        if es_tit and fld in ('metr', 'pu'):
            return ''
        base = f.get('base_val') or 0

        def _pct(v):   # % del valor sobre la base contractual (como la pantalla)
            return f'{(v or 0) / base * 100 if base else 0:.2f}%'

        if grp == 'base':
            return {'metr': m(f['base_metr']), 'pu': d(f['precio_unitario']),
                    'parc': d(f['base_val'])}[fld]
        if grp == 'ant':
            return {'metr': m(f['ant_metr']), 'val': d(f['ant_val']),
                    'pct': _pct(f['ant_val'])}[fld]
        if grp == 'act':
            return {'metr': m(f['act_metr']), 'val': d(f['act_val']),
                    'pct': _pct(f['act_val'])}[fld]
        if grp == 'acu':
            return {'metr': m(f['acu_metr']), 'val': d(f['acu_val']),
                    'pct': f'{f["pct"]:.2f}%'}[fld]
        return {'metr': m(f['sal_metr']), 'val': d(f['sal_val']),
                'pct': _pct(f['sal_val'])}[fld]

    # ── Cabecera de 2 niveles ───────────────────────────────────────────────
    fix_css = (f'background:{GHBG};color:{SLATE_900};font-weight:700;'
               f'font-size:7.5pt;padding:5pt 6pt;border-bottom:1.5pt solid {_o};')
    gh = [f'<th rowspan="2" style="{fix_css}text-align:left">Ítem</th>',
          f'<th rowspan="2" style="{fix_css}text-align:left">Descripción</th>',
          f'<th rowspan="2" style="{fix_css}text-align:center">Und</th>']
    for gi, (glbl, gspan, ban) in enumerate(groups):
        bg = BANANA if ban else GHBG
        gh.append(f'<th colspan="{gspan}" style="background:{bg};color:{SLATE_900};'
                  f'font-weight:700;font-size:7.5pt;padding:4pt 6pt;'
                  f'border-bottom:1.5pt solid {_o};text-align:center">{glbl}</th>')
        if gi < len(groups) - 1:
            gh.append(SEP_H)
    sh = []
    for col in layout:
        if col is SEP:
            continue   # cubierto por SEP_H (rowspan 2)
        grp, fld = col
        bg = BANANA if grp == 'act' else GHBG
        sh.append(f'<th width="{_W[fld]}" style="background:{bg};color:{SLATE_700};'
                  f'font-weight:700;font-size:6.5pt;padding:2pt 4pt;'
                  f'border-bottom:1.5pt solid {_o};text-align:right">{_SUB[fld]}</th>')

    # ── Filas ────────────────────────────────────────────────────────────────
    rows = []
    _dots = [(f.get('item') or '').count('.') for f in filas if not f['es_titulo']]
    _min_dots = min(_dots) if _dots else 0
    partida_idx = 0

    def _fila(f, *, total=False):
        es_tit = bool(f['es_titulo']) or total
        if total:
            niv, cel_desc = 1, 'TOTAL'
            item = ''
        else:
            niv = f.get('nivel', 1) if es_tit else 1
            item = escape(f['item'] or '')
            cel_desc = escape(f['descripcion'] or '')
        if es_tit:
            col = _NIVEL.get(min(max(niv, 1), 5), '#92400E')
            deco = 'text-transform:uppercase;letter-spacing:0.4pt;' if niv <= 1 else ''
            btop = f'border-top:1.2pt solid {SLATE_700};' if (niv <= 1 or total) else ''
            base_css = (f'{BORDER_TD}{btop}padding:5pt 6pt;color:{col};'
                        f'font-weight:700;font-size:8pt;{deco}')
            it_css = base_css; ds_css = base_css
            # En títulos, los VALORES van en negro (no el color de nivel); el
            # color de nivel queda solo en Ítem/Descripción.
            def cell_css(grp):
                bg = BANANA if grp == 'act' else 'white'
                return (f'{BORDER_TD}{btop}padding:5pt 3pt 5pt 8pt;color:{SLATE_900};'
                        f'font-weight:700;font-size:7pt;background:{bg};'
                        f'text-align:right;white-space:nowrap;')
            row_bg = 'white'
        else:
            partidas_bg = '#FBFCFD' if (partida_idx % 2) else 'white'
            row_bg = partidas_bg
            it_css = f'{BORDER_TD}padding:4pt 6pt;color:{SLATE_900};font-size:7.5pt;background:{row_bg};'
            depth = max(0, (f.get('item') or '').count('.') - _min_dots)
            ds_inner = escape(f['descripcion'] or '')
            ds_css = it_css
            def cell_css(grp):
                bg = BANANA if grp == 'act' else row_bg
                return (f'{BORDER_TD}padding:4pt 3pt 4pt 8pt;color:{SLATE_900};'
                        f'font-size:6.8pt;background:{bg};text-align:right;'
                        f'white-space:nowrap;')
        # Ítem, Descripción, Und
        r = [f'<td style="{it_css}">{item}</td>',
             f'<td style="{ds_css}">{cel_desc}</td>',
             f'<td style="{it_css}text-align:center">'
             f'{"" if es_tit else escape(f.get("unidad") or "")}</td>']
        for col in layout:
            if col is SEP:
                r.append(SEP_TD); continue
            grp, fld = col
            r.append(f'<td width="{_W[fld]}" style="{cell_css(grp)}">'
                     f'{_valor(f, grp, fld, es_tit)}</td>')
        return '<tr>' + ''.join(r) + '</tr>'

    for f in filas:
        if not f['es_titulo']:
            partida_idx += 1
        rows.append(_fila(f))
    # Fila TOTAL (usa el resumen; se arma como un "fila título" con sus valores).
    tot = {'es_titulo': True, 'nivel': 1, 'item': '', 'descripcion': 'TOTAL',
           'unidad': '', 'base_metr': None, 'precio_unitario': None,
           'base_val': resumen.get('base_val'), 'ant_metr': None,
           'ant_val': resumen.get('ant_val'), 'act_metr': None,
           'act_val': resumen.get('act_val'), 'acu_metr': None,
           'acu_val': resumen.get('acu_val'), 'pct': resumen.get('pct_fisico', 0),
           'sal_metr': None, 'sal_val': resumen.get('sal_val')}
    rows.append(_fila(tot, total=True))

    parts.append(
        '<table border="0" cellspacing="0" cellpadding="0" width="100%">'
        f'<thead><tr>{"".join(gh)}</tr><tr>{"".join(sh)}</tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table>')
    return "\n".join(parts)


def _html_kardex_material(pid: int, f: dict, dm: int, colors) -> str:
    """Una hoja de KÁRDEX DE ALMACÉN para un material: cabecera Material/Unidad +
    tabla Fecha · Entradas · Salidas · Saldos · Observaciones (saldo corrido)."""
    import core.almacen as _alm
    _o, _od, _os = colors

    def m(v):
        return _fmt(v, dm) if v not in (None, 0, 0.0) else ""

    def _dmy(iso):
        p = str(iso or '').split('-')
        return f"{p[2]}/{p[1]}/{p[0]}" if len(p) == 3 else str(iso or '')

    movs = _alm.kardex(pid, f['recurso_id'])
    filas_html = []
    for mv in movs:
        filas_html.append(
            '<tr>'
            f'<td class="c">{escape(_dmy(mv["fecha"]))}</td>'
            f'<td class="r">{m(mv["entrada"])}</td>'
            f'<td class="r">{m(mv["salida"])}</td>'
            f'<td class="r">{_fmt(mv["saldo"], dm)}</td>'
            f'<td>{escape(mv["observacion"] or "")}</td>'
            '</tr>')
    # Filas en blanco para poder anotar a mano (como el formato físico).
    for _ in range(max(0, 6 - len(movs))):
        filas_html.append('<tr><td>&nbsp;</td><td></td><td></td><td></td><td></td></tr>')
    cab = (f'<p style="margin:2pt 0"><b>MATERIAL:</b> '
           f'{escape(f["descripcion"] or "")} &nbsp;&nbsp;&nbsp;'
           f'<b>UNIDAD:</b> {escape(f["unidad"] or "")}</p>')
    tabla = (
        '<table class="data" width="100%"><thead>'
        f'<tr><th style="background:{_os};text-align:center;width:18%">FECHA</th>'
        f'<th style="background:{_os};text-align:center;width:14%">ENTRADAS</th>'
        f'<th style="background:{_os};text-align:center;width:14%">SALIDAS</th>'
        f'<th style="background:{_os};text-align:center;width:14%">SALDOS</th>'
        f'<th style="background:{_os};text-align:center">OBSERVACIONES</th></tr></thead>'
        f'<tbody>{"".join(filas_html)}</tbody></table>')
    return cab + tabla


def _html_firmas_almacen(colors) -> str:
    """Bloque de firmas del kárdex: Residente · Supervisor · Almacenero de obra."""
    _o, _od, _os = colors
    cel = ('<td align="center" style="padding-top:34pt;font-size:9pt;'
           'color:#555">______________________<br/>{}</td>')
    return ('<table width="100%" style="margin-top:24pt"><tr>'
            + cel.format('RESIDENTE') + cel.format('SUPERVISOR')
            + cel.format('ALMACENERO DE OBRA') + '</tr></table>')


def _html_almacen(proy: dict, filas: list, pid: int = None) -> str:
    """Cuerpo HTML del kárdex de materiales: RESUMEN (por insumo, Pedido ·
    Ingresado · Consumido · Stock · Por llegar) + una hoja de KÁRDEX por material
    con movimiento (Fecha · Entradas · Salidas · Saldos · Observaciones)."""
    dm = get_decimales_metrado()
    _o, _od, _os = _brand_colors()

    def m(v):
        return _fmt(v, dm) if v is not None else ""

    def _tabla_resumen(grupo):
        rows = []
        for i, f in enumerate(grupo):
            zebra = ' class="alt"' if (i % 2) else ''
            stock_neg = f['stock'] < -1e-6
            st = (f'<b style="color:#B71C1C">{m(f["stock"])}</b>' if stock_neg
                  else m(f['stock']))
            rows.append(
                f'<tr{zebra}>'
                f'<td>{escape(f["descripcion"] or "")}</td>'
                f'<td class="c">{escape(f["unidad"] or "")}</td>'
                f'<td class="r">{m(f["pedido"])}</td>'
                f'<td class="r">{m(f["ingresado"])}</td>'
                f'<td class="r">{m(f["consumido"])}</td>'
                f'<td class="r">{st}</td>'
                f'<td class="r">{m(f["por_llegar"])}</td>'
                f'</tr>')
        return (
            '<table class="data" width="100%"><thead>'
            f'<tr><th style="background:{_os}">Insumo</th>'
            f'<th style="background:{_os}">Und</th>'
            f'<th style="background:{_os};text-align:right">Pedido</th>'
            f'<th style="background:{_os};text-align:right">Ingresado</th>'
            f'<th style="background:{_os};text-align:right">Consumido</th>'
            f'<th style="background:{_os};text-align:right">Stock</th>'
            f'<th style="background:{_os};text-align:right">Por llegar</th>'
            '</tr></thead>'
            f'<tbody>{"".join(rows) or "<tr><td>—</td></tr>"}</tbody></table>')

    con_req = [f for f in filas if (f.get('pedido') or 0) > 1e-6]
    sin_req = [f for f in filas if (f.get('pedido') or 0) <= 1e-6]

    def _subtit(txt):
        return (f'<p style="color:{_od};font-size:11pt;font-weight:700;'
                f'margin:10pt 0 3pt 0">{txt}</p>')

    parts = ['<h2>Control de materiales — Kárdex de obra</h2>']
    if con_req:
        parts.append(_subtit("Pedidos en requerimientos"))
        parts.append(_tabla_resumen(con_req))
    if sin_req:
        parts.append(_subtit("Otros — sin requerimiento"))
        parts.append(_tabla_resumen(sin_req))
    if not con_req and not sin_req:
        parts.append(_tabla_resumen([]))

    # ── Kárdex por material (solo los que tuvieron movimiento) ───────────────
    if pid is not None:
        con_mov = [f for f in filas
                   if (f.get('ingresado') or 0) > 1e-6 or (f.get('consumido') or 0) > 1e-6]
        if con_mov:
            parts.append('<p class="pagebreak">&nbsp;</p>')
            parts.append('<h2>Kárdex de almacén por material</h2>')
            for i, f in enumerate(con_mov):
                if i:
                    parts.append('<p style="font-size:12pt;margin:0">&nbsp;</p>')
                parts.append(_html_kardex_material(pid, f, dm, (_o, _od, _os)))
            parts.append(_html_firmas_almacen((_o, _od, _os)))
    return "\n".join(parts)


def generar_almacen_pdf(pid: int, out_path: str, *, paper: str = 'A4'):
    """PDF del kárdex de materiales (control de almacén) del proyecto."""
    import core.requerimientos as _req
    proy = _proyecto_info(pid)
    filas = _req.control_almacen(pid)
    body = _html_almacen(proy, filas, pid)
    renderer = _PdfRenderer(proy, "Control de materiales", with_cover=False,
                            paper=paper, orient='portrait')
    renderer.render_to_file(body, out_path)


_MESES_ES = ['ENERO', 'FEBRERO', 'MARZO', 'ABRIL', 'MAYO', 'JUNIO', 'JULIO',
             'AGOSTO', 'SEPTIEMBRE', 'OCTUBRE', 'NOVIEMBRE', 'DICIEMBRE']
_DIAS_ES = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado',
            'domingo']


def _fecha_larga_es(iso: str) -> str:
    """«yyyy-MM-dd» → «Lunes 24 de junio de 2026»."""
    from datetime import date
    p = str(iso or '').split('-')
    if len(p) == 3 and len(p[0]) == 4:
        try:
            d = date(int(p[0]), int(p[1]), int(p[2]))
            return (f"{_DIAS_ES[d.weekday()].capitalize()} {int(p[2])} de "
                    f"{_MESES_ES[int(p[1]) - 1].lower()} de {p[0]}")
        except ValueError:
            pass
    return str(iso or '')


def _html_cuaderno(proy: dict, pid: int, parte_ids: list) -> str:
    """Cuerpo HTML del cuaderno de obra: un asiento por día (mano de obra,
    actividades, materiales/equipos/servicios, observaciones)."""
    import core.parte_diario as _pd
    dm = get_decimales_metrado()
    _o, _od, _os = _brand_colors()
    SZ = "10pt"   # tamaño único para todo el cuerpo del asiento
    # Título centrado.
    parts = ['<h2 align="center" style="text-align:center">Cuaderno de obra</h2>']
    primero = True

    def _rotulo(txt):
        """Rótulo de sección con viñeta (bloque propio)."""
        return (f'<p style="font-size:{SZ};margin:6pt 0 2pt 0">'
                f'<b>•&nbsp;&nbsp;{escape(txt)}</b></p>')

    for pidx in parte_ids:
        parte = _pd.get_parte(pidx)
        if not parte:
            continue
        mo = _pd.get_recursos_dia(pidx, 'mo')
        acts = _pd.get_actividades_dia(pidx)
        recursos = {c: _pd.get_recursos_dia(pidx, c) for c in ('mat', 'eq', 'sc')}
        obs = (parte.get('observaciones') or '').strip()
        # Omitir días SIN nada registrado (no ensuciar el reporte con asientos
        # vacíos: ni mano de obra, ni actividades, ni insumos, ni incidencias).
        if not (mo or acts or any(recursos.values()) or obs):
            continue
        if not primero:   # espacio entre un día y el siguiente
            parts.append('<p style="font-size:14pt; margin:0">&nbsp;</p>')
        primero = False
        parts.append(f'<h3 style="color:{_od};margin-top:14pt;'
                     f'border-bottom:1pt solid {_os};padding-bottom:2pt">'
                     f'Asiento del día — {escape(_fecha_larga_es(parte["fecha"]))}'
                     f'</h3>')
        if mo:
            txt = " · ".join(
                escape(f"{_cant(x['cantidad'])} {x['descripcion']}".strip())
                for x in mo)
            parts.append(f'<p style="font-size:{SZ};margin:6pt 0 2pt 0">'
                         f'<b>•&nbsp;&nbsp;Mano de obra:</b> {txt}</p>')
        if acts:
            parts.append(_rotulo("Actividades realizadas:"))
            rows = "".join(
                f'<tr><td width="64" style="font-size:{SZ}">{escape(a["item"] or "")}</td>'
                f'<td style="font-size:{SZ}">{escape(a["descripcion"] or "")}</td>'
                f'<td width="80" class="r" style="font-size:{SZ}">{_fmt(a["metrado_dia"], dm)}</td>'
                f'<td width="54" class="c" style="font-size:{SZ}">{escape(a["unidad"] or "")}</td></tr>'
                for a in acts)
            parts.append(
                '<table class="data" width="100%"><thead>'
                f'<tr><th width="64" style="background:{_os};font-size:{SZ}">Ítem</th>'
                f'<th style="background:{_os};font-size:{SZ}">Actividad realizada</th>'
                f'<th width="80" style="background:{_os};text-align:right;font-size:{SZ}">Metrado</th>'
                f'<th width="54" style="background:{_os};text-align:center;font-size:{SZ}">Und</th>'
                '</tr></thead>'
                f'<tbody>{rows}</tbody></table>')
        for clase, tit in (('mat', 'Materiales'), ('eq', 'Equipos'),
                           ('sc', 'Servicios')):
            rs = recursos.get(clase)
            if rs:
                txt = " · ".join(
                    escape(" ".join(s for s in (
                        x['descripcion'], _fmt(x['cantidad'], dm), x['unidad'])
                        if s).strip()) for x in rs)
                parts.append(f'<p style="font-size:{SZ};margin:6pt 0 2pt 0">'
                             f'<b>•&nbsp;&nbsp;{tit}:</b> {txt}</p>')
        if obs:
            parts.append(_rotulo("Observaciones:"))
            parts.append(f'<p style="font-size:{SZ};margin:0 0 0 14pt;'
                         f'white-space:pre-wrap">{escape(obs)}</p>')
    if len(parts) == 1:
        parts.append('<p>No hay partes para los días seleccionados.</p>')
    return "\n".join(parts)


def _cant(v):
    """Cantidad entera si es redonda, si no con 2 decimales."""
    try:
        v = float(v or 0)
    except (TypeError, ValueError):
        return "0"
    return str(int(round(v))) if abs(v - round(v)) < 1e-9 else _fmt(v, 2)


def generar_cuaderno_pdf(pid: int, parte_ids: list, out_path: str, *,
                         paper: str = 'A4'):
    """PDF del cuaderno de obra para los días (partes) indicados."""
    proy = _proyecto_info(pid)
    body = _html_cuaderno(proy, pid, parte_ids)
    renderer = _PdfRenderer(proy, "Cuaderno de obra", with_cover=False,
                            paper=paper, orient='portrait')
    renderer.render_to_file(body, out_path)


def _png_curva_s_real_b64(d: dict, *, width: int = 720, height: int = 300,
                          vis: dict = None) -> str:
    """Renderiza la curva S programado/reprogramado/real (3 series) como PNG b64.
    `vis` = {'prog','reprog','real','pct'} controla qué series y las etiquetas de
    % se dibujan (espejo de los toggles del panel)."""
    if vis is None:
        vis = {'prog': True, 'reprog': True, 'real': True, 'pct': True}
    import base64
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPolygonF
    img = QImage(width * 2, height * 2, QImage.Format_ARGB32)
    img.fill(Qt.white)
    p = QPainter(img); p.setRenderHint(QPainter.Antialiasing, True)
    ml, mr, mt, mb = 74, 30, 30, 64
    pl, pt = ml, mt
    pr, pb = width * 2 - mr, height * 2 - mb
    n = max(1, d.get('n_periods', 1))

    def px(x):
        return pl + (x / n) * (pr - pl)

    def py(v):
        return pb - (v / 100.0) * (pb - pt)

    p.setPen(QPen(QColor("#E2E8F0"), 1, Qt.DashLine))
    f = QFont('Inter', 15); p.setFont(f)
    for g in (0, 25, 50, 75, 100):
        y = py(g)
        p.setPen(QPen(QColor("#E2E8F0"), 1, Qt.DashLine))
        p.drawLine(int(pl), int(y), int(pr), int(y))
        p.setPen(QColor("#475569"))
        p.drawText(QRectF(10, y - 14, ml - 18, 28), Qt.AlignRight | Qt.AlignVCenter,
                   f"{g}%")
    p.setPen(QPen(QColor("#475569"), 2))
    p.drawLine(int(pl), int(pb), int(pr), int(pb))
    labels = d.get('labels', [])
    for i in range(1, n + 1):
        x = px(i)
        p.setPen(QColor("#94A3B8"))
        lab = labels[i - 1] if i <= len(labels) else str(i)
        p.drawText(QRectF(x - 55, pb + 8, 110, 26), Qt.AlignCenter, lab)

    series = [('prog_pts', 'prog', "#3689E6", Qt.SolidLine, 'Programado', -42),
              ('reprog_pts', 'reprog', "#8E44AD", Qt.DashLine, 'Reprogramado', -42),
              ('real_pts', 'real', "#F37329", Qt.SolidLine, 'Real', 12)]
    leyenda = []
    for key, vkey, col, estilo, lbl, dy in series:
        if not vis.get(vkey, True):
            continue   # serie oculta por el toggle del panel
        pts = d.get(key, [])
        if len(pts) <= 1:
            continue
        leyenda.append((col, estilo, lbl))
        poly = QPolygonF([QPointF(px(x), py(v)) for x, v in pts])
        p.setPen(QPen(QColor(col), 4, estilo)); p.setBrush(Qt.NoBrush)
        p.drawPolyline(poly)
        p.setBrush(QColor(col)); p.setPen(QColor(col))
        for x, v in pts[1:]:
            p.drawEllipse(QPointF(px(x), py(v)), 5, 5)
        # Etiquetas de % por punto (chip blanco, borde del color), si el toggle
        # «Mostrar %» está activo.
        if vis.get('pct', True):
            fl = QFont('Inter', 13); fl.setBold(True); p.setFont(fl)
            for x, v in pts[1:]:
                txt = f"{v:.0f}%"
                w = 20 + 11 * len(txt)
                cx, cy = px(x), py(v)
                cy_l = cy + dy
                if cy_l < 2:            # se saldría por arriba → ponla debajo
                    cy_l = cy + 14
                chip = QRectF(cx - w / 2, cy_l, w, 26)
                p.setPen(QPen(QColor(col), 1)); p.setBrush(QColor("white"))
                p.drawRoundedRect(chip, 5, 5)
                p.setPen(QColor("black")); p.drawText(chip, Qt.AlignCenter, txt)
    # Leyenda (caja arriba-izquierda).
    if leyenda:
        bx, by, rh = pl + 16, pt + 10, 30
        p.setPen(QPen(QColor("#CBD5E1"), 1)); p.setBrush(QColor(255, 255, 255, 235))
        p.drawRoundedRect(QRectF(bx, by, 250, 12 + rh * len(leyenda)), 8, 8)
        for i, (col, estilo, lbl) in enumerate(leyenda):
            cy = by + 6 + i * rh + rh / 2
            p.setPen(QPen(QColor(col), 4, estilo))
            p.drawLine(int(bx + 12), int(cy), int(bx + 52), int(cy))
            p.setPen(QColor("#273445"))
            p.drawText(QRectF(bx + 62, cy - 14, 180, 28),
                       Qt.AlignLeft | Qt.AlignVCenter, lbl)
    p.end()
    ba = QByteArray(); buf = QBuffer(ba); buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG"); buf.close()
    return base64.b64encode(ba.data()).decode('ascii')


def _html_curva_s(proy: dict, d: dict, *, vis: dict = None) -> str:
    """Cuerpo HTML de la Curva S real: gráfico (PNG) + tabla por período con
    Programado · Reprogramado · Real (Monto·%Ejec·%Acum) y Desviación.
    `vis` = {'prog','reprog','real','pct'} muestra/oculta series y columnas
    (espejo de los toggles del panel)."""
    if vis is None:
        vis = {'prog': True, 'reprog': True, 'real': True, 'pct': True}
    dp = get_decimales_ppto()
    _o, _od, _os = _brand_colors()

    def mo(v):
        return _fmt(v, dp) if v is not None else ""

    def pc(v):
        return f"{v:.1f}%" if v is not None else ""

    img_b64 = _png_curva_s_real_b64(d, vis=vis)
    parts = ['<h2 align="center" style="text-align:center">'
             'Curva S — programado vs reprogramado vs real</h2>',
             f'<p style="text-align:center"><img src="data:image/png;base64,'
             f'{img_b64}" width="760"/></p>']
    # ── Paleta + separadores (mismo estilo que el reporte de Valorización) ──
    GHBG = "#F1F5F9"; GRID = "#CBD5E1"
    SEP_H = ('<th rowspan="2" width="2" style="background:#94A3B8;padding:0;'
             'font-size:1px"></th>')
    SEP_TD = '<td width="2" style="background:#94A3B8;padding:0;font-size:1px"></td>'
    _SUBS = ['Monto', '% Ejecutado', '% Acumulado']

    # Grupos activos según los toggles; «Desv.» acompaña a «Real».
    GROUPS = [('prog', 'Programado'), ('reprog', 'Reprogramado'), ('real', 'Real')]
    active = [(k, lbl) for k, lbl in GROUPS if vis.get(k, True)]
    show_desv = vis.get('real', True)

    # Cabecera de 2 niveles.
    fix_css = (f'background:{GHBG};color:{SLATE_900};font-weight:700;'
               f'font-size:8pt;padding:5pt 6pt;border-bottom:1.5pt solid {_o};')
    gh = [f'<th rowspan="2" style="{fix_css}text-align:left">Período</th>']
    for _k, glbl in active:
        gh.append(SEP_H)
        gh.append(f'<th colspan="3" style="{fix_css}text-align:center">{glbl}</th>')
    if show_desv:
        gh.append(SEP_H)
        gh.append(f'<th rowspan="2" style="{fix_css}text-align:right">Desv.</th>')
    sub_css = (f'background:{GHBG};color:{SLATE_700};font-weight:700;'
               f'font-size:7pt;padding:2pt 5pt;border-bottom:1.5pt solid {_o};'
               f'text-align:right;')
    sh = ''.join(f'<th style="{sub_css}">{s}</th>' for _k, _l in active for s in _SUBS)

    rows = []
    tp = {'p_mon': 0.0, 'r_mon': 0.0, 'x_mon': 0.0}
    ult = {'p_acu': None, 'r_acu': None, 'x_acu': None}

    def _row(label, gvals, desv, *, bg='', extra=''):
        """gvals = {grupo: [Monto, %Ej, %Ac]}. Emite solo los grupos activos."""
        base = (f'border-bottom:0.4pt solid {GRID};{extra}padding:4pt 6pt;'
                f'color:{SLATE_900};font-size:8pt;{bg}')
        r = [f'<td style="{base}text-align:left">{label}</td>']
        for k, _l in active:
            r.append(SEP_TD)
            for v in gvals[k]:
                r.append(f'<td style="{base}text-align:right">{v}</td>')
        if show_desv:
            r.append(SEP_TD)
            r.append(f'<td style="{base}text-align:right">{desv}</td>')
        return '<tr>' + ''.join(r) + '</tr>'

    for i, f in enumerate(d.get('filas', [])):
        bg = 'background:#FBFCFD;' if (i % 2) else ''
        dv = f.get('desviacion')
        dvs = ""
        if dv is not None:
            col = "#B71C1C" if dv < -1e-6 else "#16A34A"
            dvs = f'<b style="color:{col}">{dv:+.1f}%</b>'
        for k in tp:
            if f.get(k) is not None:
                tp[k] += f[k]
        for k in ult:
            if f.get(k) is not None:
                ult[k] = f[k]
        gvals = {'prog': [mo(f["p_mon"]), pc(f["p_eje"]), pc(f["p_acu"])],
                 'reprog': [mo(f["r_mon"]), pc(f["r_eje"]), pc(f["r_acu"])],
                 'real': [mo(f["x_mon"]), pc(f["x_eje"]), pc(f["x_acu"])]}
        rows.append(_row(escape(f["label"]), gvals, dvs, bg=bg))
    # Fila TOTAL: negrita en NEGRO con borde superior (sin rojo ni subrayado).
    gtot = {'prog': [mo(tp["p_mon"]), "", pc(ult["p_acu"])],
            'reprog': [mo(tp["r_mon"]), "", pc(ult["r_acu"])],
            'real': [mo(tp["x_mon"]), "", pc(ult["x_acu"])]}
    rows.append(_row("TOTAL", gtot, "",
                     extra=f'font-weight:700;border-top:1.2pt solid {SLATE_700};'))

    parts.append(
        '<table border="0" cellspacing="0" cellpadding="0" width="100%">'
        f'<thead><tr>{"".join(gh)}</tr><tr>{sh}</tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table>')
    return "\n".join(parts)


def generar_curva_s_pdf(pid: int, out_path: str, *, base: str = 'mes_cal',
                        paper: str = 'A4', vis: dict = None):
    """PDF de la Curva S real (gráfico + tabla comparativa) del proyecto."""
    import core.curva_s as _cs
    proy = _proyecto_info(pid)
    d = _cs.curva_s_comparada(pid, base)
    body = _html_curva_s(proy, d, vis=vis)
    renderer = _PdfRenderer(proy, "Curva S — avance real", with_cover=False,
                            paper=paper, orient='landscape')
    renderer.render_to_file(body, out_path)


def generar_valorizacion_pdf(val_id: int, out_path: str, *, paper: str = 'A4'):
    """Genera el PDF de una valorización (landscape) y lo guarda en disco."""
    import core.valorizacion as _val
    val = _val.get_valorizacion(val_id)
    if not val:
        raise ValueError("Valorización no encontrada")
    proy = _proyecto_info(val['proyecto_id'])
    filas, resumen = _val.get_valorizacion_detalle(val_id)
    body = _html_valorizacion(val, proy, filas, resumen)
    renderer = _PdfRenderer(proy, f"Valorización N° {val['numero']}",
                            with_cover=False, paper=paper, orient='landscape')
    renderer.render_to_file(body, out_path)


_TDR_NUM_CELL = None


def _es_celda_numerica(s: str) -> bool:
    """True si la celda parece un número/monto (para alinear a la derecha)."""
    import re
    global _TDR_NUM_CELL
    if _TDR_NUM_CELL is None:
        _TDR_NUM_CELL = re.compile(
            r'^[\s]*(S/|US\$|\$)?[\s]*[\d][\d.,\s]*%?[\s]*$')
    t = (s or '').strip()
    return bool(t) and bool(_TDR_NUM_CELL.match(t))


import re as _re_tdr
# Fila separadora estilo markdown («----|----|----») que la IA a veces intercala
# tras la cabecera: se descarta para que no salga como una fila de guiones.
_MD_SEP = _re_tdr.compile(r'^[\s|:+_-]*[-_]{3,}[\s|:+_-]*$')


def _tdr_split_fila(ln: str) -> list:
    """Divide una fila de tabla en celdas. Soporta los dos formatos que produce
    la IA: separada por «|» o alineada con 2+ espacios."""
    if '|' in ln:
        s = ln.strip()
        if s.startswith('|'):
            s = s[1:]
        if s.endswith('|'):
            s = s[:-1]
        return [c.strip() for c in s.split('|')]
    return [c.strip() for c in _re_tdr.split(r'\s{2,}', ln.strip())]


def _tdr_filas(block: list) -> list:
    """Convierte un bloque de líneas de tabla (con «|» o alineadas con espacios)
    en una lista de filas (cada fila = lista de celdas). Descarta separadores
    markdown y filas vacías. La primera fila es la cabecera."""
    filas = []
    for ln in block:
        if _MD_SEP.match(ln.strip()):
            continue   # separador markdown, no es una fila real
        cells = _tdr_split_fila(ln)
        if any(c for c in cells):
            filas.append(cells)
    return filas


def _tdr_tabla_html(block: list) -> str:
    """Convierte un bloque de filas (separadas por «|» o alineadas con espacios)
    en una TABLA con cuadros visibles (atributo `border` + `cellpadding`, lo más
    fiable en QTextDocument). La primera fila es la cabecera."""
    filas = _tdr_filas(block)
    if not filas:
        return ''
    return _tdr_tabla_html_filas(filas)


def _tdr_tabla_html_filas(filas: list) -> str:
    """Render HTML de una tabla ya dividida en filas/celdas."""
    if not filas:
        return ''
    ncols = max(len(f) for f in filas)
    # `border`/`cellpadding`/`cellspacing` como ATRIBUTOS → rejilla limpia (las
    # líneas verticales por CSS salen entrecortadas en QTextDocument).
    html = ['<table width="100%" border="1" cellspacing="0" cellpadding="7" '
            'style="margin:6px 0 8px 0; border-color:#9AA4AE;">']
    for ri, cells in enumerate(filas):
        cells = cells + [''] * (ncols - len(cells))
        if ri == 0:   # cabecera
            html.append('<tr>' + ''.join(
                '<td align="center" style="background:#E8EDF2; font-weight:bold; '
                f'font-size:8.5pt;">{escape(c)}</td>' for c in cells) + '</tr>')
            continue
        bg = '#FFFFFF' if ri % 2 else '#F6F8FA'
        tds = []
        for c in cells:
            al = 'right' if _es_celda_numerica(c) else 'left'
            tds.append(f'<td align="{al}" style="background:{bg}; font-size:8.5pt;">'
                       f'{escape(c)}</td>')
        html.append('<tr>' + ''.join(tds) + '</tr>')
    html.append('</table>')
    return ''.join(html)


_TDR_NUM = _re_tdr.compile(r'^(\d+(\.\d+)*|[IVXLA-Z])[\.\)]\s+\S')  # «1.»,«1.1»,«A)»
_TDR_LABEL = _re_tdr.compile(r'^([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ0-9 /.\-]{1,38}):\s+(\S.*)$')
_TDR_BULLET = _re_tdr.compile(r'^\s*[-–•*]\s+(.*)$')   # viñeta «- …» / «• …»
# Cabecera de la tabla de ítems alineada con espacios (sin «|»): «ÍTEM …
# DESCRIPCIÓN …». La IA a veces emite la tabla así en vez de con pipes.
_TDR_THEAD = _re_tdr.compile(r'^\s*[ÍI]TEM\b.*\bDESCRIP', _re_tdr.IGNORECASE)


def parse_tdr_bloques(texto: str) -> list:
    """Analiza el texto del TDR (generado/editado) en una lista de bloques
    tipados — fuente única de verdad para el render en PDF y en Word/ODT.

    Cada bloque es una tupla:
      ('blank',)                     línea en blanco (espaciador)
      ('table', filas)               filas = lista de listas de celdas
      ('bullet', texto)              viñeta «- …» / «• …»
      ('heading_num', texto, depth)  subsección numerada «1.», «5.1.»
      ('heading_major', texto)       título MAYÚSCULAS sin número («ESPECIF…»)
      ('sublabel', texto)            rótulo MAYÚSCULAS con «:» al final
      ('label', etiqueta, valor)     «ASUNTO: …» / «FECHA: …»
      ('para', texto)                párrafo de cuerpo
    """
    lineas = (texto or '').split('\n')
    blocks = []
    i, n = 0, len(lineas)
    while i < n:
        raw = lineas[i]
        # Bloque de tabla: líneas consecutivas con 2+ «|».
        if raw.count('|') >= 2:
            block = []
            while i < n and lineas[i].count('|') >= 2:
                block.append(lineas[i]); i += 1
            filas = _tdr_filas(block)
            if filas:
                blocks.append(('table', filas))
            continue
        # Bloque de tabla alineado con espacios: cabecera «ÍTEM … DESCRIPCIÓN …»
        # seguida de filas (2+ celdas al partir por 2+ espacios) hasta un blanco.
        if _TDR_THEAD.match(raw) and len(_re_tdr.split(r'\s{2,}', raw.strip())) >= 3:
            block = [raw]; i += 1
            while i < n and lineas[i].strip() and lineas[i].count('|') < 2 \
                    and len(_re_tdr.split(r'\s{2,}', lineas[i].strip())) >= 2:
                block.append(lineas[i]); i += 1
            filas = _tdr_filas(block)
            if filas:
                blocks.append(('table', filas))
            continue
        stripped = raw.strip()
        if not stripped:
            blocks.append(('blank',)); i += 1
            continue
        mb = _TDR_BULLET.match(raw)
        if mb:
            blocks.append(('bullet', mb.group(1))); i += 1
            continue
        letras = [c for c in stripped if c.isalpha()]
        es_may = bool(letras) and stripped == stripped.upper() and len(stripped) <= 80
        mnum = _TDR_NUM.match(stripped)
        mlab = _TDR_LABEL.match(stripped)
        # Numerado ANTES que mayúsculas: casi todos van en mayúscula pero NO
        # deben llevar filete (quedaría un documento sobrecargado de rayas).
        if mnum:
            blocks.append(('heading_num', stripped, mnum.group(1).count('.')))
        elif es_may:
            if stripped.endswith(':'):
                blocks.append(('sublabel', stripped))
            else:
                blocks.append(('heading_major', stripped))
        elif mlab:
            blocks.append(('label', mlab.group(1), mlab.group(2)))
        else:
            blocks.append(('para', stripped))
        i += 1
    return blocks


def _html_tdr(texto: str) -> str:
    """Convierte el texto del TDR en HTML con la MISMA tipografía y formato que
    las Especificaciones Técnicas: fuente proporcional (Inter, heredada del
    `_base_css`), párrafos justificados con interlineado 1.5, viñetas «•» y
    encabezados de sección. Renderiza desde `parse_tdr_bloques`."""
    o, od, _os = _brand_colors()
    out = ['<div class="tdr" style="line-height:1.5;">']
    prev = None   # 'blank' | 'head' | 'text' | 'bullet' | 'table' | None

    def _aire(pt):
        out.append(f'<div style="font-size:{pt}pt;">&nbsp;</div>')

    for blk in parse_tdr_bloques(texto):
        kind = blk[0]
        if kind == 'blank':
            _aire(4); prev = 'blank'
        elif kind == 'table':
            out.append(_tdr_tabla_html_filas(blk[1])); prev = 'table'
        elif kind == 'bullet':
            out.append('<p align="justify" style="margin:0 0 3pt 16pt;'
                       'text-indent:-12pt;text-align:justify;">'
                       f'•&nbsp;&nbsp;{escape(blk[1])}</p>')
            prev = 'bullet'
        elif kind == 'heading_num':
            # Más aire ANTES de cada subsección numerada (1. / 2. / 3.…).
            if prev not in (None, 'blank'):
                _aire(12 if blk[2] == 0 else 6)
            if blk[2] == 0:
                sz, col = '10.5pt', od
            else:
                sz, col = '9.5pt', SLATE_700
            out.append(f'<p style="margin:5pt 0 3pt 0;color:{col};'
                       f'font-weight:700;font-size:{sz};">{escape(blk[1])}</p>')
            prev = 'head'
        elif kind == 'heading_major':
            # Título de sección (p. ej. «ESPECIFICACIONES TÉCNICAS»): espacio
            # grande antes + CENTRADO con filete de marca.
            if prev not in (None, 'blank'):
                _aire(24)
            out.append(f'<p align="center" style="margin:6pt 0 6pt 0;color:{od};'
                       f'font-weight:700;font-size:13pt;text-align:center;'
                       f'text-transform:uppercase;letter-spacing:0.5pt;'
                       f'border-bottom:1.2pt solid {o};padding-bottom:3pt;">'
                       f'{escape(blk[1])}</p>')
            prev = 'head'
        elif kind == 'sublabel':
            if prev not in (None, 'blank'):
                _aire(6)
            out.append(f'<p style="margin:2pt 0 3pt 0;color:{SLATE_700};'
                       f'font-weight:700;font-size:9.5pt;">{escape(blk[1])}</p>')
            prev = 'head'
        elif kind == 'label':
            out.append('<p style="margin:0 0 3pt 0;text-align:justify;">'
                       f'<b>{escape(blk[1])}:</b> {escape(blk[2])}</p>')
            prev = 'text'
        else:   # 'para'
            out.append('<p align="justify" style="margin:0 0 4pt 0;'
                       f'text-align:justify;">{escape(blk[1])}</p>')
            prev = 'text'

    out.append('</div>')
    return ''.join(out)


def _html_tdr_encabezado(datos: dict) -> str:
    """Encabezado del documento (memorando público o membrete privado) compuesto
    por la app con los datos del diálogo — aparece SOLO en el PDF. Misma
    tipografía proporcional que el resto del reporte; las etiquetas se alinean
    con una tabla borderless (etiqueta | valor)."""
    if not datos:
        return ''
    def g(k):
        v = datos.get(k)
        return v.strip() if isinstance(v, str) else (v or '')
    o, od, _os = _brand_colors()
    numero = g('numero'); asunto = g('asunto'); fecha = g('fecha'); lugar = g('lugar')
    fl = f"{lugar}, {fecha}".strip(', ') if (lugar or fecha) else ''
    out = []
    filas = []   # (label, value) alineadas en una tabla

    def fila(label, value):
        if value:
            filas.append((label, value))

    def _flush_filas():
        if not filas:
            return
        out.append('<table style="border-collapse:collapse;margin:2pt 0 0 0;'
                   'font-size:9.5pt;">')
        for lb, val in filas:
            out.append(
                f'<tr><td style="padding:1pt 10pt 1pt 0;vertical-align:top;'
                f'white-space:nowrap;color:{SLATE_700};font-weight:700;">'
                f'{escape(lb)}:</td>'
                f'<td style="padding:1pt 0;vertical-align:top;color:{SLATE_900};">'
                f'{escape(val)}</td></tr>')
        out.append('</table>')
        filas.clear()

    _titulo = (f'<p align="center" style="margin:0 0 4pt 0;color:{od};'
               f'font-weight:700;font-size:15pt;letter-spacing:0.4pt;'
               f'text-align:center;">REQUERIMIENTO N° {escape(numero)}</p>')

    if g('es_publico'):
        out.append(_titulo)
        dest = g('destinatario') + (f" — {g('cargo_destinatario')}"
                                    if g('cargo_destinatario') else '')
        deq = g('solicitante') + (f" — {g('cargo_solicitante')}"
                                  if g('cargo_solicitante') else '')
        ent = g('entidad') + (f" / {g('unidad_organica')}"
                              if g('unidad_organica') else '')
        fila('A', dest)
        fila('ATENCIÓN', g('atencion'))
        fila('DE', deq)
        fila('ENTIDAD', ent)
        fila('ASUNTO', asunto)
        fila('FECHA', fl)
        _flush_filas()
    else:
        if g('solicitante'):
            out.append(f'<p style="margin:0;color:{SLATE_900};font-weight:700;'
                       f'font-size:12pt;">{escape(g("solicitante"))}</p>')
        sub = '  ·  '.join(x for x in (g('ruc') and f"RUC: {g('ruc')}",
                                       g('direccion'), g('telefono')) if x)
        if sub:
            out.append(f'<p style="margin:0 0 3pt 0;color:{SLATE_500};'
                       f'font-size:9pt;">{escape(sub)}</p>')
        out.append(_titulo)
        fila('ASUNTO', asunto)
        fila('FECHA', fl)
        _flush_filas()

    # Divisor + aire antes del cuerpo.
    out.append('<div style="font-size:4pt;">&nbsp;</div>')
    out.append(f'<hr color="{o}" size="1" width="100%">')
    out.append('<div style="font-size:6pt;">&nbsp;</div>')
    return ''.join(out)


def generar_tdr_pdf(out_path: str, req_id: int):
    """PDF del Requerimiento + TDR / EE.TT.: encabezado armado por la app (con los
    datos guardados del diálogo) + el cuerpo generado por la IA/editado, con el
    membrete del proyecto y pie."""
    import json
    import core.requerimientos as _req
    q = _req.get_requerimiento(req_id)
    if not q:
        raise ValueError("Requerimiento no encontrado")
    proy = _proyecto_info(q['proyecto_id'])
    # Encabezado de página: solo «Requerimiento» (sin número — el número va en
    # el título del cuerpo).
    titulo = "Requerimiento"
    try:
        datos = json.loads(q.get('tdr_datos') or '{}')
    except (ValueError, TypeError):
        datos = {}
    # El número del título del cuerpo SIEMPRE es el real del requerimiento
    # (q['numero']), no el que quedó guardado en tdr_datos (podía estar viejo).
    datos['numero'] = str(q['numero'])
    body = _html_tdr_encabezado(datos) + _html_tdr(q.get('tdr') or '')
    renderer = _PdfRenderer(proy, titulo, with_cover=False,
                            paper='A4', orient='portrait')
    renderer.render_to_file(body, out_path)


def generar_pdf_seccion_archivo(seccion: str, num: int, pid: int,
                                  out_path: str, *,
                                  with_cover: bool = False,
                                  titulo_cover: str | None = None,
                                  pie_offset: int = 0,
                                  pie_total: int | None = None,
                                  con_divisor: bool = True):
    """Una sección del Reporte Completo como PDF propio: divisor «SECCIÓN num»
    + contenido. El encabezado de cada página muestra el TÍTULO DE LA SECCIÓN
    (Presupuesto, ACU, Insumos…) en lugar de «Expediente Técnico», para
    distinguir las hojas en documentos gruesos. `with_cover=True` solo en la
    primera sección del merge; `titulo_cover` es el título de la carátula.
    `con_divisor=False` omite la mini-portada «— SECCIÓN n —» (modo compacto
    «Sin separadores»); la sección sigue identificándose por el encabezado."""
    _BUILD_HTML_PAPER['paper'] = 'A4'
    _BUILD_HTML_PAPER['orient'] = 'portrait'
    titulo, cuerpo, proy = _build_html_for(seccion, pid)
    desc = next((d for c, _t, d in REPORT_TYPES if c == seccion), '')
    body = (_section_divider(num, titulo, desc, first=True) + cuerpo
            if con_divisor else cuerpo)
    renderer = _PdfRenderer(proy, titulo, with_cover=with_cover,
                              paper='A4', orient='portrait',
                              pie_offset=pie_offset, pie_total=pie_total)
    renderer.titulo_cover = titulo_cover
    renderer.render_to_file(body, out_path)
