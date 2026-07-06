# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""Asistente local — análisis y tips sin IA.

Funciona como fallback cuando no hay conexión / API key, y como
complemento del chat IA con análisis instantáneo del proyecto.

Componentes:
  - ASCII tux frames    → animación visual del asistente
  - Banco de tips       → consejos prácticos de presupuestos peruanos
  - Banco motivacional  → frases de aliento para el trabajo
  - analizar_proyecto() → genera insights leyendo la BD
"""
from __future__ import annotations
import random
from core.database import get_db, calcular_totales


# ── ASCII Tux ─────────────────────────────────────────────────────────────────

TUX_NORMAL = r"""    /AI\
   |o_o |
   |:_/ |
  //   \ \
 (|     | )
/'\_   _/`\
\___)=(___/"""

TUX_PIENSA = r"""    /AI\    .oO( ... )
   |-_- |
   |:_/ |
  //   \ \
 (|     | )
/'\_   _/`\
\___)=(___/"""

TUX_FELIZ = r"""    /AI\
   |^_^ |  ¡listo!
   |:_/ |
  //   \ \
 (|     | )
/'\_   _/`\
\___)=(___/"""

TUX_TIP = r"""    /AI\    .oO( tip )
   |o_O |
   |:_/ |
  //   \ \
 (|     | )
/'\_   _/`\
\___)=(___/"""


def tux_frame(estado: str = 'normal') -> str:
    return {
        'normal': TUX_NORMAL,
        'piensa': TUX_PIENSA,
        'feliz':  TUX_FELIZ,
        'tip':    TUX_TIP,
    }.get(estado, TUX_NORMAL)


# ── Tips de presupuestos peruanos (offline) ───────────────────────────────────

TIPS = [
    # ── Buenas prácticas técnicas peruanas ────────────────────────────────
    "Verifica que la cuadrilla y el rendimiento sean coherentes: cantidad MO = cuadrilla / rendimiento × jornada.",
    "En sierra >3000 msnm, ajusta los rendimientos CAPECO a la baja: típicamente -15 a -20%.",
    "Para concretos, no olvides agregar el % de desperdicio en cemento, arena y piedra (5-10%).",
    "Los metrados de acero se calculan con kg/ml según diámetro (NTP 341.031 / ASTM A615).",
    "Si tu fórmula polinómica no suma 1.000, ajusta el monomio mayor para que ΣK = 1.000 exacto.",
    "Los precios INEI cambian cada mes; revisa que la fecha 'costo al' del proyecto esté actualizada.",
    "Para obras públicas, las especificaciones técnicas deben citar normas: NTP, ASTM, RNE, MTC.",
    "Insumos con unidad '%' (porcentajes) no se cuentan en el listado de insumos del proyecto.",
    "El rendimiento del peón en albañilería ronda los 8 m²/jornada en muros de soga (CAPECO).",
    "Encofrado de muros: 12-14 m²/jornada por carpintero + ayudante; ajusta si el muro es alto.",
    "Concreto premezclado: descuenta 2-3% por mermas de bombeo en proyectos verticales.",
    "Tarrajeo interior C:A 1:5 → 14 m²/jornada; tarrajeo exterior → 12 m²/jornada (más riesgo).",
    "Para vaciado en altura > 4 m considera andamios o falso piso adicional en el ACU.",
    "Las viviendas multifamiliares peruanas usan f'c 210 kg/cm² en columnas como mínimo (RNE E.060).",
    "Acero corrugado más usado en Perú: 1/2\" y 5/8\". Pesos: 0.994 y 1.552 kg/m respectivamente.",
    "Eternit/cobertura: incluye 5% de traslape (NTP 334.151) en el metrado.",
    "Pisos de cerámico: agrega 3-5% por cortes y 2% por roturas.",
    "Para gres porcelánico de 60×60, rendimiento típico: 12 m²/jornada con boquilla simple.",
    "Pintura látex 2 manos: rendimiento 30-35 m²/galón sobre tarrajeo (Vencedor/CPP).",
    "Excavación manual en terreno normal: 3-4 m³/jornada por peón; en roca suelta 1.5 m³.",
    "Excavación con maquinaria (cargador frontal): 25-40 m³/hora según volumen.",
    "Relleno compactado con material propio: 25 m³/jornada con plancha vibratoria.",
    "Para zapatas, el metrado de concreto se mide en m³ incluyendo solado de 5 cm.",
    "Las columnas se metran por altura libre + 50 cm de empalme con viga superior.",
    # ── Productividad y atajos en ingePresupuestos ───────────────────────
    "Aprovecha la biblioteca CU: importa una vez y reusa en proyectos similares.",
    "Usa Ctrl+C / Ctrl+V en el árbol para copiar partidas completas entre proyectos.",
    "El botón 'Duplicar partida' del menú contextual ahorra horas en proyectos repetitivos.",
    "Antes de cerrar un presupuesto, ejecuta 'Revisar IA' para detectar inconsistencias.",
    "Doble clic en el nombre de un sub-presupuesto para renombrarlo al vuelo.",
    "Arrastra el separador entre tabs y chat para más espacio según necesites.",
    "Click derecho sobre una pestaña de sub-presupuesto para eliminarla o renombrar.",
    "El ratio del splitter se guarda por proyecto — cada uno recuerda su layout favorito.",
    # ── Cronograma Gantt — nuevas interacciones gráficas ─────────────────
    "En el Gantt enlazas tareas como en MS Project: arrastra una barra hacia otra (arriba/abajo) — sueltas al inicio = FC, al fin = FF, en el tercio central = CC+50% (el sucesor arranca cuando la pred. lleva el 50%).",
    "Arrastra una flecha del Gantt horizontalmente para ajustar el lag en días (o el % si la vinculaste a mitad de la pred.) — una etiqueta naranja muestra el valor en vivo.",
    "Predecesoras en notación MS Project español: 5 = FC · 5FC+3 = FC con 3 días de lag · 5CC+2 = CC · 5FF-1 = FF · 5CF = CF.",
    "Clic derecho sobre una flecha del Gantt para cambiar el tipo (FC/CC/FF/CF), editar lag/% o eliminar la dependencia.",
    "Ctrl+clic agrega varias flechas a la selección; pulsa Supr y las elimina todas en bloque.",
    "Clic sobre una barra del Gantt → se resaltan en azul sus predecesoras y sucesoras, para ver de un vistazo qué depende de qué.",
    "Activa «⏳ Holgura» en la toolbar del Gantt para ver gráficamente cuántos días puede atrasarse cada tarea no crítica.",
    "El botón «⤢ Ajustar» del Gantt calcula el zoom para que tu proyecto completo entre en una sola pantalla.",
    "Cuando divides una tarea, los segmentos quedan unidos por una línea entrecortada — indica que pertenecen a la misma partida.",
    "Las descripciones largas de partidas se ven en doble fila en la tabla del Gantt sin perder la sincronización con las barras.",
    "Auto-programar → Local agrupa partidas por fase constructiva (preliminares, estructuras, instalaciones, acabados) respetando paralelismos.",
    # ── Convenciones de presupuesto peruano ──────────────────────────────
    "Costo Directo (CD) no incluye GG ni Utilidad. El total con IGV aparece en la topbar.",
    "Para adicionales/deductivos, en el pie de presupuesto suele dejarse solo CD (sin IGV).",
    "La fórmula polinómica oficial peruana se basa en 8 monomios máximo (J, M, E + áreas).",
    "GG de obras públicas típicamente entre 8-12%; Utilidad 5-10% según riesgo.",
    "IGV en Perú es 18% (16% IGV + 2% IPM) — no lo apliques al CD directamente.",
    "Los formatos OSCE F-01 y F-02 deben coincidir centavo a centavo con el presupuesto.",
    "El expediente técnico tiene que incluir Memoria, Especificaciones, Metrados, ACUs, Plano y Fórmula.",
    "En proyectos por contrata-suma alzada, el riesgo cae sobre el contratista; metrado exacto = $$.",
    "En precios unitarios, el riesgo cae sobre el Estado; ACU detallado y específico = sin discusiones.",
    # ── Curiosidades / mensajes culturales ───────────────────────────────
    "ingePresupuestos nació para reemplazar S10 con software libre y mejor UX. ¡Estás contribuyendo a esa misión!",
    "Tux, la mascota de Linux, nació en 1996 dibujado por Larry Ewing. Soy su prima — tuxia.",
    "El 'oxidado' del concreto (carbonatación) es lo que nos da trabajo a los presupuestistas. Gracias, química.",
    "El precio del cobre afecta los conductores eléctricos del ACU — revisa monomio E si dudas.",
    "Capeco publica las tablas de rendimientos cada 5 años. La última versión vigente: revisa su sitio oficial.",
    "El INEI publica índices unificados de construcción cada mes — patrón URL estable, ingePresupuestos los descarga solo.",
]


MOTIVACIONAL = [
    # ── Sobre el oficio del presupuestista ───────────────────────────
    "Cada metrado correcto que ingresas evita un problema en obra.",
    "Un buen presupuesto es 80% planificación, 20% ejecución.",
    "Tomarte el tiempo de revisar el ACU una vez ahorra mil revisiones en valorización.",
    "Tu cliente confía en cifras precisas; tu trabajo importa.",
    "El presupuesto es la columna vertebral del proyecto — y tú la estás construyendo.",
    "Los pequeños detalles del ACU se convierten en grandes ahorros.",
    "Cada partida bien especificada es una discusión menos en obra.",
    "Un descanso de 5 minutos ahora te ahorra horas de errores después.",
    "El mejor presupuesto es el que el contratista entiende sin llamar al ingeniero.",
    "Toda obra grande se construyó partida por partida. Tú estás justo donde debes.",
    "Hacer 100 ACUs ya te convierte en experto. ¿Cuántos llevas hoy?",
    "Las cifras claras son una forma de respeto al lector. Tu ingeniería se nota.",
    "Si dudas, comenta la partida — el yo del futuro te lo agradecerá.",
    "Revisar dos veces, presupuestar una. Vas bien, sigue.",
    "El expediente técnico es un acto de comunicación. Estás escribiéndolo con claridad.",
    "Equivocarse en S/ 1.00 en una partida es humano; corregirlo a tiempo es profesional.",
    "Una taza de café + un árbol bien organizado = presupuestos felices.",
    "Cada partida que termines te acerca al hito. Un paso a la vez.",
    "El trabajo bien hecho no necesita defenderse; defiéndelo igual con un buen comentario.",
    "Hoy es buen día para terminar ese ACU que dejaste a medias.",
    "Eres más rápido que la última vez. ¿Lo habías notado?",
    "Saludos desde Tux — recuerda guardar tu trabajo (Ctrl+S nunca está de más).",
    # ── Estoicas / filosóficas ──────────────────────────────────────
    "«Comienza haciendo lo necesario, luego lo posible, y de repente harás lo imposible.» — San Francisco de Asís",
    "«No es porque las cosas sean difíciles que no nos atrevemos; es porque no nos atrevemos que son difíciles.» — Séneca",
    "«La calidad nunca es un accidente; siempre es el resultado de un esfuerzo inteligente.» — John Ruskin",
    "«El obstáculo es el camino.» — Marco Aurelio",
    "«Concéntrate en el siguiente paso, no en toda la escalera.»",
    "«Lo que se hace bien una vez, se hace para siempre.»",
    "«La paciencia es amarga, pero su fruto es dulce.» — Aristóteles",
    "«Empieza donde estás, usa lo que tienes, haz lo que puedas.» — Arthur Ashe",
    # ── Productividad / hábitos ──────────────────────────────────────
    "Hecho es mejor que perfecto. Avanza y mejora después.",
    "Los grandes proyectos se acaban con muchos pequeños comienzos.",
    "Una hora de trabajo enfocado vale tres distraídas.",
    "Si te trabas, da un paso atrás y haz una taza de té. La solución suele llegar sola.",
    "Lo urgente puede esperar; lo importante no.",
    "Avanza, aunque sea solo una partida hoy. Mañana serán dos.",
    "El cansancio no es señal de hacer mal; es señal de estar haciendo.",
    "No tienes que ser bueno para empezar, pero tienes que empezar para ser bueno.",
    "El profesional que más sabe es el que más se equivocó — con atención.",
    "«Camina como si supieras adónde vas, incluso si no lo sabes.»",
    # ── Construcción / Perú ──────────────────────────────────────
    "El maestro de obra te llamará igual. Mejor que sea para felicitarte por un buen presupuesto.",
    "Las obras públicas peruanas mueven el país. Tú estás moviendo una de ellas.",
    "Toda partida bien presupuestada es un sol bien gastado del Estado.",
    "El mejor expediente técnico es el que el ingeniero residente puede ejecutar sin dudas.",
    "La buena ingeniería se nota en obra; la mala, también.",
    # ── Humanas / cálidas ──────────────────────────────────────
    "Eres más capaz de lo que crees. Sigue así.",
    "El silencio del trabajo bien hecho es el mejor aplauso.",
    "Hoy es un buen día para ser amable contigo. Vas bien.",
    "Las grandes obras se hacen con las manos que tiemblan, no con las que dudan.",
    "Si llegaste hasta aquí, es porque puedes terminarlo.",
    "Cada decimal corregido cuenta. Cada hora invertida también.",
]


# ── Pequeños chistes / observaciones técnicas (humor de oficina) ─────────

CHISTES = [
    "¿Sabes por qué los presupuestistas no juegan póker? Porque ya saben que la casa siempre gana en costos indirectos.",
    "Un metrado entra a un bar y pide '1 m³'. El barman le dice: '¿con desperdicio o sin?'",
    "RFC del presupuestista perfecto: 'redondea, factura, conmemora la cifra cerrada'.",
    "ACU es 'Análisis de Costos Unitarios', no 'A Cada Uno lo Suyo'. Aunque a veces…",
    "El error más caro del Perú: confundir 'unidad' con 'cantidad' en el metrado de carteles.",
    "El sueño del ingeniero presupuestista: que la obra cueste lo que él calculó.",
    "Los presupuestos peruanos están en S/, pero se sueñan en US$. Verdad universal.",
]


def chiste_aleatorio() -> str:
    return random.choice(CHISTES)


def tip_aleatorio() -> str:
    return random.choice(TIPS)


def mensaje_motivacional() -> str:
    return random.choice(MOTIVACIONAL)


# ── Showcase de capacidades de Tuxia ──────────────────────────────────────────
# Para los tips ambient periódicos: "¿sabías que puedo X?" — recuerda al
# usuario qué puede pedirme. Cada tip se identifica con una key estable
# para que no se repita seguido.

CAPACIDADES_TUXIA = [
    ('calc', "💡 Soy calculadora rápida. Prueba escribirme «cuánto es 5400 × 1.18» o «calcula 850/30»."),
    ('manual', "📘 Pregúntame cómo hacer cualquier cosa: «cómo añado una partida», «cómo exporto a Excel», «cómo cambio el rendimiento»."),
    ('analizar', "🔍 Escribe «analiza» o «/analizar» y te resumo el estado del proyecto: partidas sin metrado, sin ACU, sin specs, fórmula polinómica…"),
    ('top_partidas', "📊 Quieres saber dónde se concentra el costo? Escríbeme «top partidas» y te listo las más caras."),
    ('top_insumos', "📦 Y para insumos: «top insumos» te muestra los recursos que más pesan en el presupuesto."),
    ('pendientes', "✅ ¿Te falta algo? Escribe «pendientes» y te digo qué partidas necesitan metrado, ACU o specs."),
    ('formula', "🧮 Si tu fórmula polinómica no cuadra en 1.000, dime «revisa la fórmula» y la chequeo monomio por monomio."),
    ('motiv', "🌟 Cuando estés cansado, escríbeme «ánimo» o «/animo» — tengo frases para recargar pilas."),
    ('chiste', "😄 ¿Necesitas reír un rato? Pídeme «chiste» o «/chiste»."),
    ('tip', "🇵🇪 Tengo +60 tips de presupuestos peruanos (CAPECO, RNE, NTP). Escríbeme «/tip» para uno al azar."),
    ('ia', "🧠 Si configuras una API de IA en Configuración → IA, puedo razonar y generar especificaciones técnicas."),
    ('detalle', "🔢 ¿Quieres el resumen ejecutivo con CD, GG, utilidad, IGV y total? Escribe «totales»."),
]


def tip_ambient_aleatorio(excluir_keys: set[str] | None = None) -> tuple[str, str] | None:
    """Devuelve un tip ambient aleatorio (capacidad, motivacional o técnico).

    Retorna tupla (mensaje, key) o None si todo está excluido. La key se
    usa para evitar repetir el mismo tip seguido — el caller debe persistir
    qué tips ya mostró recientemente.
    """
    excluir = excluir_keys or set()
    pool: list[tuple[str, str]] = []
    # Capacidades (50% del peso): el showcase de qué puede hacer Tuxia
    for key, msg in CAPACIDADES_TUXIA:
        full_key = f'cap_{key}'
        if full_key not in excluir:
            pool.append((msg, full_key))
            pool.append((msg, full_key))  # doble peso
    # Tips técnicos peruanos (25%)
    for i, t in enumerate(TIPS):
        full_key = f'tip_{i}'
        if full_key not in excluir:
            pool.append((f"🇵🇪 <b>Tip del día:</b> {t}", full_key))
    # Motivacional (25%)
    for i, m in enumerate(MOTIVACIONAL):
        full_key = f'motiv_{i}'
        if full_key not in excluir:
            pool.append((f"🌟 {m}", full_key))
    if not pool:
        return None
    return random.choice(pool)


def lista_comandos_corta() -> str:
    """Resumen breve de comandos para mostrar en la bienvenida."""
    return (
        "Tipea uno de estos comandos:\n"
        "  /analizar  → análisis del proyecto actual\n"
        "  /tip       → un consejo de presupuestos peruanos\n"
        "  /animo     → mensaje motivacional\n"
        "  /chiste    → humor de oficina\n"
        "  /insumos   → top insumos del proyecto por costo\n"
        "  /partidas  → top partidas por costo\n"
        "  /pendientes→ partidas sin metrado / ACU / specs\n"
        "  /total     → totales del proyecto al detalle\n"
        "  /notas     → notas del proyecto (privadas)\n"
        "  /memoria   → memoria global (la IA la usa)\n"
        "  /calc      → cómo usarme de calculadora\n"
        "  /help      → lista completa\n\n"
        "También puedes preguntar libremente (si tienes IA configurada)\n"
        "o escribirme una operación: 12.5*8+450 la resuelvo al instante.\n"
        "Para anotar algo: «recuérdame que el precio del petróleo es 20 soles»."
    )


def bienvenida(proyecto_nombre: str = '') -> str:
    """Bienvenida breve con ASCII tux + identidad + frase motivadora +
    capacidades + hint /help."""
    motiv = mensaje_motivacional()
    return (
        f"{TUX_NORMAL}\n\n"
        "tuxia listo y operativo. Soy tu asistente virtual.\n\n"
        f"✦ {motiv}\n\n"
        "Puedo ayudarte con:\n"
        "  • Rendimientos, cuadrillas e insumos del ACU\n"
        "  • Precios referenciales y verificación de metrados\n"
        "  • Análisis del proyecto y pendientes\n"
        "  • Redacción de especificaciones técnicas\n"
        "  • 🧮 Calculadora: escribe 12.5*8+450 o «cuánto es 5400×1.18»\n\n"
        "Escribe /help para ver los comandos rápidos."
    )


# ── Análisis local del proyecto ───────────────────────────────────────────────

def analizar_proyecto(proyecto_id: int) -> str:
    """Genera un análisis textual del proyecto SIN llamar a IA externa.

    Recopila métricas de la BD: completitud de metrados, ACUs, specs,
    distribución de costo por tipo, top partidas, alertas de fórmula
    polinómica, etc. Devuelve un texto formateado tipo informe.
    """
    conn = get_db()

    proyecto = conn.execute(
        "SELECT nombre FROM proyectos WHERE id=?", (proyecto_id,)
    ).fetchone()
    if not proyecto:
        conn.close()
        return f"{TUX_TIP}\n\nNo encontré el proyecto."

    # Conteos básicos
    n_part = conn.execute(
        "SELECT COUNT(*) FROM partidas WHERE proyecto_id=? AND es_titulo=0",
        (proyecto_id,)
    ).fetchone()[0]
    n_tit = conn.execute(
        "SELECT COUNT(*) FROM partidas WHERE proyecto_id=? AND es_titulo=1",
        (proyecto_id,)
    ).fetchone()[0]
    n_sin_metrado = conn.execute(
        "SELECT COUNT(*) FROM partidas WHERE proyecto_id=? AND es_titulo=0 "
        "AND (metrado IS NULL OR metrado=0)",
        (proyecto_id,)
    ).fetchone()[0]
    n_sin_acu = conn.execute(
        "SELECT COUNT(*) FROM partidas p WHERE p.proyecto_id=? AND p.es_titulo=0 "
        "AND NOT EXISTS (SELECT 1 FROM acu_items WHERE partida_id=p.id)",
        (proyecto_id,)
    ).fetchone()[0]
    n_sin_spec = conn.execute(
        "SELECT COUNT(*) FROM partidas WHERE proyecto_id=? AND es_titulo=0 "
        "AND (especificaciones IS NULL OR TRIM(especificaciones)='')",
        (proyecto_id,)
    ).fetchone()[0]
    n_sub = conn.execute(
        "SELECT COUNT(*) FROM sub_presupuestos WHERE proyecto_id=?",
        (proyecto_id,)
    ).fetchone()[0]

    # Top 3 partidas por costo
    top = conn.execute(
        "SELECT item, descripcion, "
        "ROUND(COALESCE(metrado,0) * COALESCE(precio_unitario,0), 2) as parcial "
        "FROM partidas WHERE proyecto_id=? AND es_titulo=0 "
        "ORDER BY parcial DESC LIMIT 3",
        (proyecto_id,)
    ).fetchall()

    # Fórmula polinómica: ΣK debería ser 1.000
    monomios = conn.execute(
        "SELECT SUM(coeficiente) FROM formula_monomios WHERE proyecto_id=?",
        (proyecto_id,)
    ).fetchone()[0]

    conn.close()

    # Totales
    try:
        _, tot = calcular_totales(proyecto_id)
        cd = tot.get('cd', 0)
        total = tot.get('total', 0)
    except Exception:
        cd = 0
        total = 0

    # Construir informe
    lineas = [TUX_TIP, ""]
    lineas.append(f"📋 Análisis local — {proyecto['nombre'][:50]}")
    lineas.append("")

    # Indicadores clave
    lineas.append(f"┌─ Estructura")
    lineas.append(f"│  Partidas:     {n_part}")
    lineas.append(f"│  Títulos:      {n_tit}")
    if n_sub:
        lineas.append(f"│  Sub-pptos:    {n_sub}")
    lineas.append(f"├─ Montos")
    lineas.append(f"│  Costo directo: S/ {cd:>14,.2f}")
    if total != cd:
        lineas.append(f"│  Total c/IGV:   S/ {total:>14,.2f}")
    lineas.append(f"└─")
    lineas.append("")

    # Alertas
    alertas = []
    if n_sin_metrado:
        alertas.append(f"⚠ {n_sin_metrado} partida(s) sin metrado")
    if n_sin_acu:
        alertas.append(f"⚠ {n_sin_acu} partida(s) sin ACU cargado")
    if n_sin_spec:
        alertas.append(f"ℹ {n_sin_spec} partida(s) sin especificaciones")
    if monomios is not None:
        try:
            mf = float(monomios)
            if mf > 0 and abs(mf - 1.0) > 0.001:
                alertas.append(f"⚠ Fórmula polinómica: ΣK = {mf:.4f} (debería ser 1.000)")
        except Exception:
            pass
    # Detección de insumos duplicados / con precios distintos
    try:
        dup_a, dup_b = detectar_insumos_duplicados(proyecto_id)
        if dup_a:
            alertas.append(
                f"⚠ {len(dup_a)} insumo(s) con precios distintos entre partidas — "
                "escribe /duplicados"
            )
        if dup_b:
            alertas.append(
                f"⚠ {len(dup_b)} grupo(s) de insumos similares "
                "(posibles duplicados de la biblioteca) — /duplicados"
            )
    except Exception:
        pass
    if not alertas:
        alertas.append("✓ No detecté alertas evidentes.")
    lineas.extend(alertas)
    lineas.append("")

    # Top partidas
    if top:
        lineas.append("Top 3 partidas por costo:")
        for r in top:
            desc = (r['descripcion'] or '')[:38]
            lineas.append(f"  • {r['item']:6s} {desc:38s} S/ {r['parcial']:>10,.2f}")
        lineas.append("")

    # Tip + motivacional para cerrar
    lineas.append(f"💡 Tip: {tip_aleatorio()}")
    lineas.append("")
    lineas.append(f"✦ {mensaje_motivacional()}")
    return "\n".join(lineas)


def top_insumos(proyecto_id: int, n: int = 10) -> str:
    """Top N insumos del proyecto por incidencia en el costo (cant×precio)."""
    if not proyecto_id:
        return f"{TUX_TIP}\n\nAbre un proyecto primero."
    conn = get_db()
    rows = conn.execute(
        """SELECT r.tipo, r.descripcion, r.unidad,
                  COALESCE(ai.precio, r.precio, 0) AS pu,
                  SUM(ai.cantidad * p.metrado) AS cant
           FROM acu_items ai
             JOIN partidas p ON p.id=ai.partida_id
             JOIN recursos r ON r.id=ai.recurso_id
           WHERE p.proyecto_id=? AND SUBSTR(r.unidad,1,1)!='%'
           GROUP BY r.id
           ORDER BY (SUM(ai.cantidad * p.metrado) * COALESCE(ai.precio, r.precio, 0)) DESC
           LIMIT ?""",
        (proyecto_id, n)
    ).fetchall()
    conn.close()
    if not rows:
        return f"{TUX_NORMAL}\n\nNo hay insumos cargados aún."
    lineas = [TUX_TIP, "", f"Top {n} insumos por costo:", ""]
    for r in rows:
        parc = (r['cant'] or 0) * (r['pu'] or 0)
        desc = (r['descripcion'] or '')[:38]
        lineas.append(
            f"  {r['tipo']:3s} {desc:38s} {(r['unidad'] or '')[:5]:5s}"
            f" × {(r['cant'] or 0):>9,.2f} = S/ {parc:>11,.2f}"
        )
    return "\n".join(lineas)


def top_partidas(proyecto_id: int, n: int = 10) -> str:
    """Top N partidas del proyecto por costo."""
    if not proyecto_id:
        return f"{TUX_TIP}\n\nAbre un proyecto primero."
    conn = get_db()
    rows = conn.execute(
        """SELECT item, descripcion,
                  ROUND(COALESCE(metrado,0) * COALESCE(precio_unitario,0), 2) as parcial,
                  unidad, metrado, precio_unitario
           FROM partidas WHERE proyecto_id=? AND es_titulo=0
           ORDER BY parcial DESC LIMIT ?""",
        (proyecto_id, n)
    ).fetchall()
    conn.close()
    if not rows:
        return f"{TUX_NORMAL}\n\nNo hay partidas en este proyecto."
    lineas = [TUX_TIP, "", f"Top {n} partidas por costo:", ""]
    for r in rows:
        desc = (r['descripcion'] or '')[:42]
        lineas.append(
            f"  {r['item']:8s} {desc:42s} {(r['unidad'] or '')[:4]:4s}"
            f" × {(r['metrado'] or 0):>8,.2f} = S/ {(r['parcial'] or 0):>11,.2f}"
        )
    return "\n".join(lineas)


def pendientes(proyecto_id: int) -> str:
    """Lista partidas con campos vacíos críticos (metrado/ACU/specs)."""
    if not proyecto_id:
        return f"{TUX_TIP}\n\nAbre un proyecto primero."
    conn = get_db()
    sin_m = conn.execute(
        "SELECT item, descripcion FROM partidas WHERE proyecto_id=? AND es_titulo=0 "
        "AND (metrado IS NULL OR metrado=0) ORDER BY item LIMIT 30",
        (proyecto_id,)
    ).fetchall()
    sin_acu = conn.execute(
        "SELECT p.item, p.descripcion FROM partidas p WHERE p.proyecto_id=? AND p.es_titulo=0 "
        "AND NOT EXISTS (SELECT 1 FROM acu_items WHERE partida_id=p.id) "
        "ORDER BY p.item LIMIT 30",
        (proyecto_id,)
    ).fetchall()
    sin_spec = conn.execute(
        "SELECT item, descripcion FROM partidas WHERE proyecto_id=? AND es_titulo=0 "
        "AND (especificaciones IS NULL OR TRIM(especificaciones)='') "
        "ORDER BY item LIMIT 30",
        (proyecto_id,)
    ).fetchall()
    conn.close()
    lineas = [TUX_TIP, ""]
    if not (sin_m or sin_acu or sin_spec):
        lineas.append("✓ Todo en orden: metrados, ACUs y especificaciones completos.")
        return "\n".join(lineas)
    lineas.append("Pendientes detectados:")
    lineas.append("")
    if sin_m:
        lineas.append(f"⚠ Sin metrado ({len(sin_m)}):")
        for r in sin_m[:8]:
            lineas.append(f"  • {r['item']:8s} {(r['descripcion'] or '')[:50]}")
        if len(sin_m) > 8:
            lineas.append(f"  … y {len(sin_m)-8} más")
        lineas.append("")
    if sin_acu:
        lineas.append(f"⚠ Sin ACU ({len(sin_acu)}):")
        for r in sin_acu[:8]:
            lineas.append(f"  • {r['item']:8s} {(r['descripcion'] or '')[:50]}")
        if len(sin_acu) > 8:
            lineas.append(f"  … y {len(sin_acu)-8} más")
        lineas.append("")
    if sin_spec:
        lineas.append(f"ℹ Sin especificaciones ({len(sin_spec)}):")
        for r in sin_spec[:5]:
            lineas.append(f"  • {r['item']:8s} {(r['descripcion'] or '')[:50]}")
        if len(sin_spec) > 5:
            lineas.append(f"  … y {len(sin_spec)-5} más")
    return "\n".join(lineas)


def totales_detalle(proyecto_id: int) -> str:
    """Totales detallados del proyecto, respetando los `pie_rubros` activos.

    Si el proyecto tiene un pie configurado (rubros activos como Liquidación,
    Supervisión, etc.), los lista TODOS — no solo CD/GG/Utilidad/IGV. Refleja
    exactamente lo que ve el usuario en la pestaña Pie y en el Resumen.
    """
    if not proyecto_id:
        return f"{TUX_TIP}\n\nAbre un proyecto primero."
    try:
        _, tot = calcular_totales(proyecto_id)
    except Exception as e:
        return f"{TUX_TIP}\n\nNo pude calcular: {e}"

    cd = tot.get('cd', 0)
    total = tot.get('total', 0)

    # Leemos los pie_rubros activos para mostrar el desglose real.
    conn = get_db()
    rubros = conn.execute(
        "SELECT * FROM pie_rubros WHERE proyecto_id=? AND activo=1 ORDER BY orden",
        (proyecto_id,)
    ).fetchall()
    gg_items = conn.execute(
        "SELECT * FROM gastos_generales WHERE proyecto_id=? ORDER BY orden",
        (proyecto_id,)
    ).fetchall()
    conn.close()

    lineas = [TUX_TIP, "", "Totales del proyecto:", ""]
    lineas.append(f"  {'Costo Directo (CD)':28s} S/ {cd:>14,.2f}")

    if rubros:
        # Iteramos espejo a `_filas_resumen` para listar cada rubro activo.
        acum = cd
        last_sub = cd
        for rub in rubros:
            tipo = rub['tipo']
            pct = rub['pct'] or 0
            cod = rub['codigo']
            nombre = rub['nombre']
            if tipo == 'subtotal':
                last_sub = acum
                lineas.append(f"  {'─'*30}")
                lineas.append(f"  {nombre:28s} S/ {acum:>14,.2f}")
                continue
            if tipo == 'pct_sub':
                val = last_sub * pct / 100
            elif tipo == 'pct_cd':
                val = cd * pct / 100
            else:  # rubro con detalle (GG, Util, etc.)
                manual = next((i for i in gg_items
                               if i['rubro'] == cod and i['tipo'] == 'manual'),
                              None)
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
            sufijo = f" ({pct:.2f}%)" if pct and tipo in ('pct_sub', 'pct_cd') else ''
            lineas.append(f"  {nombre + sufijo:28s} S/ {val:>14,.2f}")
    else:
        # Fallback legacy (sin pie_rubros): formula simple desde proyectos.
        if tot.get('gf', 0):
            lineas.append(f"  {'Gastos Generales':28s} S/ {tot['gf']:>14,.2f}")
        if tot.get('utilidad', 0):
            lineas.append(f"  {'Utilidad':28s} S/ {tot['utilidad']:>14,.2f}")
        if tot.get('subtotal', 0) != cd:
            lineas.append(f"  {'─'*30}")
            lineas.append(f"  {'Subtotal':28s} S/ {tot['subtotal']:>14,.2f}")
        if tot.get('igv', 0):
            lineas.append(f"  {'IGV':28s} S/ {tot['igv']:>14,.2f}")

    lineas.append(f"  {'═'*30}")
    lineas.append(f"  {'PRESUPUESTO TOTAL':28s} S/ {total:>14,.2f}")
    return "\n".join(lineas)


def detectar_insumos_duplicados(proyecto_id: int,
                                 fuzzy_threshold: int = 88
                                 ) -> tuple[list[dict], list[dict]]:
    """Detecta dos clases de inconsistencia de insumos en un proyecto:

    A) **Mismo recurso, precio variable**: el mismo `recurso_id` aparece en
       varias partidas con precios efectivos distintos (override en
       `acu_items.precio`). Caso típico: arena gruesa que cargaste a 30, 45
       y 60 soles en distintas partidas.

    B) **Recursos distintos, descripción similar**: recursos con `id`
       diferente pero misma unidad y descripción fuzzy-similar (≥85% por
       defecto). Caso típico: "petróleo" vs "petróleo diesel" o "diesel
       B5" — los tres apuntan al mismo material pero como recursos
       separados.

    Devuelve `(grupo_precio_variable, grupo_descripcion_similar)`. Cada
    item es un dict con `descripcion`, `unidad`, `variantes` (lista de
    dicts con `desc`, `precio`, `partidas` y opcional `recurso_id`).
    """
    if not proyecto_id:
        return [], []

    conn = get_db()
    rows = conn.execute(
        """
        SELECT
          r.id           AS recurso_id,
          r.descripcion  AS rec_desc,
          r.unidad       AS unidad,
          r.tipo         AS tipo,
          COALESCE(ai.precio, r.precio, 0) AS precio_ef,
          p.item         AS item,
          p.descripcion  AS partida_desc
        FROM acu_items ai
        JOIN recursos  r ON r.id = ai.recurso_id
        JOIN partidas  p ON p.id = ai.partida_id
        WHERE p.proyecto_id = ? AND p.es_titulo = 0
        ORDER BY r.unidad, r.descripcion, p.item
        """,
        (proyecto_id,)
    ).fetchall()
    conn.close()

    # ── A. Mismo recurso con precios distintos ────────────────────────
    por_recurso: dict[int, list[dict]] = {}
    for r in rows:
        rid = r['recurso_id']
        por_recurso.setdefault(rid, []).append(dict(r))

    grupo_a: list[dict] = []
    for rid, items in por_recurso.items():
        precios = {round(it['precio_ef'], 2) for it in items}
        # Filtrar 0/None — sin precio cargado no es "discrepancia" útil
        precios = {p for p in precios if p > 0}
        if len(precios) < 2:
            continue
        # Variantes agrupadas por precio
        por_precio: dict[float, list[str]] = {}
        for it in items:
            p = round(it['precio_ef'], 2)
            if p <= 0:
                continue
            por_precio.setdefault(p, []).append(
                f"{it['item']} — {(it['partida_desc'] or '')[:40]}"
            )
        variantes = [
            {'desc': items[0]['rec_desc'], 'precio': p,
             'partidas': sorted(set(parts))}
            for p, parts in sorted(por_precio.items())
        ]
        grupo_a.append({
            'descripcion': items[0]['rec_desc'],
            'unidad': items[0]['unidad'],
            'tipo': items[0]['tipo'],
            'recurso_id': rid,
            'variantes': variantes,
        })

    # ── B. Recursos distintos, descripción similar (misma unidad) ────
    try:
        from rapidfuzz import fuzz
    except ImportError:
        return grupo_a, []

    import re as _re

    def _nums(desc: str) -> set[str]:
        """Tokens numéricos (capacidad, calibre, dimensión, f'c) de la
        descripción. Si dos insumos difieren en números, son distintos
        aunque la descripción base sea similar — p.ej. 'mezcladora 11 P3'
        vs 'mezcladora 7 P3', 'acero Φ1/2"' vs 'acero Φ5/8"'."""
        # Captura enteros, decimales, y fracciones tipo 1/2 3/4 5/8
        nums = _re.findall(r"\d+(?:[.,/]\d+)?", desc or '')
        # Normaliza coma decimal y elimina cero a la izquierda en fracciones
        return {n.replace(',', '.') for n in nums}

    # Agrupar por unidad normalizada y por tipo (MO/MAT/EQ/SC) — no tiene
    # sentido comparar "arena gruesa m3" (MAT) con "peón h" (MO).
    por_unidad_tipo: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        unidad = (r['unidad'] or '').lower().strip()
        # Skip overhead (%MO, %MAT) y unidades vacías → ruido
        if not unidad or unidad.startswith('%'):
            continue
        clave = (unidad, r['tipo'] or '')
        por_unidad_tipo.setdefault(clave, []).append(dict(r))

    grupo_b: list[dict] = []
    visitados: set[tuple[int, int]] = set()  # pares ya emparejados

    for (unidad, tipo), items in por_unidad_tipo.items():
        # Dedupe items por recurso_id manteniendo el dict completo
        por_rec: dict[int, list[dict]] = {}
        for it in items:
            por_rec.setdefault(it['recurso_id'], []).append(it)
        recursos_unicos = list(por_rec.items())  # [(rid, [partidas_rows])]
        if len(recursos_unicos) < 2:
            continue

        # Cluster simple: union-find por similitud
        parent: dict[int, int] = {r[0]: r[0] for r in recursos_unicos}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x, y):
            parent[find(x)] = find(y)

        descs = {rid: _normalizar(items_r[0]['rec_desc'] or '')
                 for rid, items_r in recursos_unicos}
        nums_por_rid = {rid: _nums(items_r[0]['rec_desc'] or '')
                        for rid, items_r in recursos_unicos}
        for i, (rid_a, _) in enumerate(recursos_unicos):
            for rid_b, _ in recursos_unicos[i+1:]:
                key = (min(rid_a, rid_b), max(rid_a, rid_b))
                if key in visitados:
                    continue
                visitados.add(key)
                # Filtro de números: si las descripciones contienen
                # números/calibres y difieren, son insumos legítimamente
                # distintos (mezcladora 11 P3 vs 7 P3, acero Φ1/2" vs 5/8").
                if nums_por_rid[rid_a] != nums_por_rid[rid_b]:
                    continue
                # Solo token_set_ratio — partial_ratio se infla con
                # substrings comunes ("tee cpvc 3/4" vs "unión cpvc 3/4"
                # daría 91 por partial pero son insumos distintos).
                score = fuzz.token_set_ratio(descs[rid_a], descs[rid_b])
                if score >= fuzzy_threshold:
                    union(rid_a, rid_b)

        # Reagrupar por raíz
        clusters: dict[int, list[int]] = {}
        for rid, _ in recursos_unicos:
            clusters.setdefault(find(rid), []).append(rid)

        for raiz, miembros in clusters.items():
            if len(miembros) < 2:
                continue
            variantes = []
            descs_set = set()
            for rid in miembros:
                items_r = por_rec[rid]
                desc = items_r[0]['rec_desc']
                descs_set.add(desc)
                precios = {round(it['precio_ef'], 2): None for it in items_r
                           if it['precio_ef'] > 0}
                partidas = sorted({
                    f"{it['item']} — {(it['partida_desc'] or '')[:40]}"
                    for it in items_r
                })
                precio_str = ' / '.join(
                    f"S/{p:.2f}" for p in sorted(precios.keys())
                ) or 'sin precio'
                variantes.append({
                    'desc': desc,
                    'precio': precio_str,
                    'partidas': partidas,
                    'recurso_id': rid,
                })
            if len(descs_set) < 2:
                # Misma descripción pero ids distintos → biblioteca duplicada;
                # vale la pena reportarlo igual.
                pass
            grupo_b.append({
                'descripcion': '/ '.join(sorted(descs_set)),
                'unidad': unidad,
                'tipo': tipo,
                'variantes': variantes,
            })

    return grupo_a, grupo_b


def duplicados_detalle(proyecto_id: int) -> str:
    """Reporte formateado de insumos duplicados / con precios variables.
    Usado por el comando `/duplicados` y como sección de `/analizar`."""
    if not proyecto_id:
        return f"{TUX_TIP}\n\nAbre un proyecto primero."
    try:
        grupo_a, grupo_b = detectar_insumos_duplicados(proyecto_id)
    except Exception as e:
        return f"{TUX_TIP}\n\nNo pude analizar: {e}"

    if not grupo_a and not grupo_b:
        return (f"{TUX_FELIZ}\n\n✓ No detecté duplicados ni precios "
                "variables en los insumos del proyecto.")

    lineas = [TUX_TIP, "", "🔍 Insumos posiblemente duplicados o "
              "con precios variables:"]

    if grupo_a:
        lineas.append("")
        lineas.append("━" * 50)
        lineas.append("A. Mismo insumo con precios distintos en varias partidas")
        lineas.append("━" * 50)
        for g in grupo_a:
            lineas.append("")
            lineas.append(f"  📦 {g['descripcion']} ({g['unidad']}) "
                          f"— {g['tipo']}")
            for v in g['variantes']:
                lineas.append(f"    • S/ {v['precio']:>7.2f} en:")
                for part in v['partidas']:
                    lineas.append(f"        - {part}")

    if grupo_b:
        lineas.append("")
        lineas.append("━" * 50)
        lineas.append("B. Insumos con descripción similar (posibles duplicados)")
        lineas.append("━" * 50)
        for g in grupo_b:
            lineas.append("")
            lineas.append(f"  📦 {g['descripcion']} ({g['unidad']}) "
                          f"— {g['tipo']}")
            for v in g['variantes']:
                lineas.append(f"    • «{v['desc']}» → {v['precio']}")
                for part in v['partidas']:
                    lineas.append(f"        - {part}")

    lineas.append("")
    lineas.append("💡 Tip: revisa las partidas listadas y unifica el insumo "
                  "a un solo recurso de la biblioteca para que aparezca una "
                  "sola vez en el listado de insumos del proyecto.")
    return "\n".join(lineas)


def ayuda_completa() -> str:
    """Lista completa de comandos disponibles, con descripciones."""
    return (
        f"{TUX_NORMAL}\n\n"
        "Comandos de tuxia:\n\n"
        "  Información del proyecto\n"
        "  ─────────────────────────\n"
        "  /analizar      Análisis completo (estructura + alertas + top 3)\n"
        "  /total         Totales detallados (CD, GG, Util, IGV)\n"
        "  /partidas      Top 10 partidas por costo\n"
        "  /insumos       Top 10 insumos por incidencia\n"
        "  /pendientes    Partidas sin metrado / ACU / specs\n"
        "  /duplicados    Detecta insumos similares o con precios distintos\n\n"
        "  Manual de la app\n"
        "  ─────────────────\n"
        "  /manual        Lista los temas que puedo explicarte\n"
        "  Preguntas tipo «¿cómo agrego una partida?» también funcionan\n\n"
        "  Calculadora integrada\n"
        "  ──────────────────────\n"
        "  Escribe la operación directo en el chat: 12.5*8+450\n"
        "  Acepta + - × ÷ x ^ % ( ) y coma decimal (1,5*2).\n"
        "  También «cuánto es 5400×1.18» o «calcula 850/30».\n"
        "  /calc          Ayuda y ejemplos de la calculadora\n\n"
        "  Aprendizaje y motivación\n"
        "  ─────────────────────────\n"
        "  /tip           Consejo aleatorio de presupuestos peruanos\n"
        "  /animo         Mensaje motivacional\n"
        "  /chiste        Humor de oficina\n\n"
        "  Notas y Memoria (blocs editables)\n"
        "  ─────────────────────────────────\n"
        "  /notas         Notas del proyecto (privadas, NO van al LLM)\n"
        "  /memoria       Memoria global (el LLM la usa como contexto)\n"
        "  Para anotar rápido escribe «recuérdame que el petróleo está a 20 S/».\n"
        "  Patrones que reconozco: «recuerda que…», «anota que…», «memo: …»,\n"
        "  «no olvides que…». Si menciona «este proyecto»/«la obra»/«aquí»\n"
        "  → se anota en notas del proyecto. Si no, en memoria global.\n"
        "  Botones del header: 🗒️ notas · 🧠 memoria.\n\n"
        "  Sistema\n"
        "  ─────────\n"
        "  /help          Esta ayuda\n"
        "  /clear         Limpia el chat (también botón 'clear' arriba)\n\n"
        "Sin comando: pregunta libre — usa la IA si tienes API key configurada."
    )


def ayuda_calculadora() -> str:
    """Ayuda + ejemplos de la calculadora integrada (comando /calc)."""
    return (
        f"{TUX_NORMAL}\n\n"
        "🧮 Soy calculadora — escribe la operación directo en el chat:\n\n"
        "  12.5*8+450          → 550\n"
        "  (2.40+0.15)*6.8     → con paréntesis\n"
        "  5400 × 1.18         → alias × ÷ x funcionan\n"
        "  1,5*2               → coma decimal peruana OK\n"
        "  2^3   ·   18%4      → potencia y resto\n\n"
        "También entiendo «cuánto es 5400×1.18» o «calcula 850/30».\n"
        "Respondo al instante, sin gastar tokens de IA."
    )


def listar_temas_manual() -> str:
    """Lista todos los temas del manual disponibles."""
    lineas = [TUX_TIP, "", "📘 Temas que puedo explicarte:", ""]
    for entry in MANUAL:
        lineas.append(f"  • {entry['tema'].title()}")
    lineas.append("")
    lineas.append("Pregunta libremente: «¿cómo agrego una partida?», «¿dónde "
                  "configuro la IA?», etc. Detecto la intención por keywords.")
    return "\n".join(lineas)


# ── Manual / FAQ embebido — tuxia explica cómo se usa la app ─────────────────

MANUAL = [
    # ── Navegación y proyectos ────────────────────────────────────────
    {
        'tema': 'volver al inicio',
        'keywords': ['volver inicio', 'regresar inicio', 'salir proyecto',
                     'cerrar proyecto', 'ir dashboard', 'ir inicio'],
        'respuesta':
            "Para volver al dashboard de proyectos:\n"
            "  • Click en «Inicio» (toolbar superior izquierda) o\n"
            "  • Click en el logo de la app (esquina superior izquierda)\n"
            "Las pestañas de proyectos abiertos quedan disponibles arriba."
    },
    {
        'tema': 'crear proyecto',
        'keywords': ['crear proyecto', 'nuevo proyecto', 'agregar proyecto',
                     'como creo un proyecto'],
        'respuesta':
            "En el sidebar izquierdo, click en «Nuevo proyecto».\n"
            "Llena nombre, ubicación, modalidad, moneda y estado, luego "
            "guarda. Aparecerá en el dashboard."
    },
    {
        'tema': 'abrir proyecto',
        'keywords': ['abrir proyecto', 'cargar proyecto', 'entrar al proyecto'],
        'respuesta':
            "Doble clic sobre la tarjeta o fila del proyecto en el dashboard, "
            "o usa el botón «Abrir» de la tarjeta."
    },
    # ── Partidas / árbol del presupuesto ───────────────────────────────
    {
        'tema': 'agregar partida',
        'keywords': ['agregar partida', 'nueva partida', 'crear partida',
                     'añadir partida', 'añadir item'],
        'respuesta':
            "Hay dos formas:\n"
            "  • Click derecho en el árbol del presupuesto → «Nueva partida»\n"
            "  • Botón «+ Partida» en la toolbar del proyecto\n"
            "Se inserta como hija del título seleccionado, o como raíz."
    },
    {
        'tema': 'agregar titulo',
        'keywords': ['agregar titulo', 'nuevo titulo', 'crear titulo',
                     'añadir titulo'],
        'respuesta':
            "Click derecho en el árbol → «Nuevo título», o botón «+ Título» "
            "en la toolbar. Los títulos agrupan partidas y muestran el "
            "subtotal de sus hijas."
    },
    {
        'tema': 'editar metrado',
        'keywords': ['editar metrado', 'cambiar metrado', 'modificar metrado',
                     'pone metrado'],
        'respuesta':
            "Dos formas:\n"
            "  • Doble clic en la celda «Metrado» del árbol e ingresa el valor\n"
            "  • Ve a la pestaña «Metrados» (panel derecho) y usa la planilla "
            "detallada para calcular por dimensiones (largo × ancho × alto)."
    },
    {
        'tema': 'eliminar partida',
        'keywords': ['eliminar partida', 'borrar partida', 'quitar partida',
                     'remover partida'],
        'respuesta':
            "Selecciona la partida y:\n"
            "  • Tecla Delete, o\n"
            "  • Click derecho → «Eliminar partida»\n"
            "Si seleccionas varias (Ctrl+click), las borra todas a la vez."
    },
    {
        'tema': 'copiar partidas',
        'keywords': ['copiar partida', 'copiar entre proyectos', 'pegar partida',
                     'duplicar partida en otro proyecto', 'mover partidas'],
        'respuesta':
            "Selecciona partidas en el árbol y:\n"
            "  • Ctrl+C copia (incluye títulos con todo su sub-árbol)\n"
            "  • Ctrl+V pega al final del sub-presupuesto activo\n"
            "Funciona ENTRE PROYECTOS: copia en uno, abre otro y pega.\n"
            "Trae ACU, metrados, acero y especificaciones."
    },
    {
        'tema': 'duplicar partida',
        'keywords': ['duplicar partida', 'clonar partida', 'replicar partida'],
        'respuesta':
            "Click derecho sobre la partida → «Duplicar partida». Crea una "
            "copia inmediatamente debajo con todo su ACU y metrados."
    },
    # ── ACU ────────────────────────────────────────────────────────────
    {
        'tema': 'agregar insumo al ACU',
        'keywords': ['agregar insumo', 'agregar recurso', 'añadir insumo',
                     'cargar acu', 'insumo a la partida'],
        'respuesta':
            "Selecciona una partida → tab «ACU» (panel derecho) → botón "
            "«+ Recurso». Busca el insumo en la biblioteca o crea uno nuevo. "
            "Se agrega con la cantidad/cuadrilla que indiques."
    },
    {
        'tema': 'rendimiento partida',
        'keywords': ['rendimiento', 'cambiar rendimiento', 'modificar rendimiento'],
        'respuesta':
            "En la tab «ACU» de la partida, el campo «Rendimiento» está en "
            "la parte superior. Cambia el valor y las cantidades de MO se "
            "recalculan automáticamente (cant = cuadrilla / rend × jornada)."
    },
    {
        'tema': 'precio de recurso',
        'keywords': ['cambiar precio', 'modificar precio', 'editar precio',
                     'actualizar precio'],
        'respuesta':
            "En el ACU, doble clic en la columna «Precio U.» del insumo y "
            "edita el valor. El cambio se aplica a TODAS las partidas del "
            "proyecto que usen ese mismo recurso (precio por proyecto)."
    },
    # ── Sub-presupuestos ──────────────────────────────────────────────
    {
        'tema': 'crear sub-presupuesto',
        'keywords': ['crear sub-presupuesto', 'nuevo sub presupuesto',
                     'agregar sub-presupuesto', 'crear subppto', 'subpresupuesto'],
        'respuesta':
            "En la barra inferior del panel del presupuesto, click en el "
            "botón «+» al lado de las pestañas. Aparece un diálogo para "
            "nombrarlo. Las partidas se asignan al sub-presupuesto activo."
    },
    {
        'tema': 'eliminar sub-presupuesto',
        'keywords': ['eliminar sub-presupuesto', 'borrar sub-presupuesto',
                     'quitar sub presupuesto'],
        'respuesta':
            "Click derecho sobre la pestaña del sub-presupuesto → "
            "«Eliminar». Si tiene partidas, te pregunta a dónde moverlas "
            "(Principal u otro sub) o si eliminarlas también."
    },
    # ── Importar/Exportar ─────────────────────────────────────────────
    {
        'tema': 'importar powercost',
        'keywords': ['importar powercost', 'importar prs', 'importar power cost',
                     'cargar prs'],
        'respuesta':
            "Sidebar → «Importar» → «PowerCost» → «.prs». Elige el archivo "
            "y el sub-presupuesto que quieras traer. Requiere `mdbtools` "
            "instalado en el sistema."
    },
    {
        'tema': 'importar delphin',
        'keywords': ['importar delphin', 'importar sqlite delphin'],
        'respuesta':
            "Sidebar → «Importar» → «Delphin Express» → «.sqlite». Si tu "
            "archivo es .dprj, primero haz «Archivo → Hacer Backup» en "
            "Delphin para obtener el .sqlite."
    },
    {
        'tema': 'exportar excel',
        'keywords': ['exportar excel', 'exportar xlsx', 'descargar excel'],
        'respuesta':
            "Sidebar → «Exportar» → elige el formato (Presupuesto, ACUs, "
            "Insumos, Metrados, Fórmula…) → genera el archivo .xlsx."
    },
    {
        'tema': 'generar pdf',
        'keywords': ['generar pdf', 'reporte pdf', 'imprimir pdf',
                     'crear pdf', 'descargar pdf'],
        'respuesta':
            "Toolbar del proyecto → «Reportes» → elige el tipo "
            "(Presupuesto, ACUs, Metrados, Especificaciones, Cronograma, "
            "Curva S, Insumos, etc.). Cada uno genera un PDF nativo."
    },
    # ── Pie de presupuesto / GG / IGV ─────────────────────────────────
    {
        'tema': 'pie presupuesto',
        'keywords': ['pie de presupuesto', 'gastos generales', 'utilidad',
                     'igv', 'cambiar gg', 'cambiar utilidad', 'cambiar igv'],
        'respuesta':
            "Toolbar del proyecto → «Pie de Presupuesto». Marca/desmarca "
            "los rubros activos y edita sus porcentajes. El total se "
            "recalcula al instante en la topbar."
    },
    # ── Estados ───────────────────────────────────────────────────────
    {
        'tema': 'cambiar estado',
        'keywords': ['cambiar estado', 'estado proyecto', 'aprobar proyecto',
                     'marcar ejecutado'],
        'respuesta':
            "En el dashboard, click sobre el badge de estado de la tarjeta "
            "y elige el nuevo estado. Dentro del proyecto, usa «Editar» en "
            "la toolbar para abrir el formulario y cambiarlo allí."
    },
    {
        'tema': 'no puedo editar',
        'keywords': ['no puedo editar', 'esta bloqueado', 'solo lectura',
                     'porque no edita', 'congelado'],
        'respuesta':
            "El proyecto solo es totalmente editable en estado «En "
            "elaboración». En «Revisión» / «Aprobado» / «Ejecutado» se "
            "bloquean partidas/ACU/pie según el régimen. Cambia el estado "
            "a elaboración desde «Editar» en la toolbar."
    },
    # ── Cronograma ────────────────────────────────────────────────────
    {
        'tema': 'cronograma',
        'keywords': ['cronograma', 'gantt', 'programar partidas',
                     'fechas de partidas', 'curva s'],
        'respuesta':
            "Toolbar → «Cronogramas». Tienes cuatro vistas: Gantt, "
            "Valorizado, Curva S y Adquisiciones.\n"
            "En el Gantt:\n"
            "  • Arrastra el centro de la barra → mover en el tiempo\n"
            "  • Arrastra el borde (cursor ↔) → cambiar duración\n"
            "  • Arrastra una barra hacia otra (arriba/abajo) → crea una "
            "dependencia (al inicio=FC, al fin=FF, tercio central=CC+50%)\n"
            "  • Clic en la barra → resalta sus predecesoras y "
            "sucesoras en azul\n"
            "  • Clic derecho en barra → dividir tarea, marcar como "
            "hito, cambiar color"
    },
    {
        'tema': 'dependencias graficas',
        'keywords': ['dependencia', 'dependencias', 'predecesora',
                     'predecesoras', 'flecha', 'enlazar tareas',
                     'fc cc ff cf', 'fs ss ff sf', 'crear vinculo',
                     'vincular tareas'],
        'respuesta':
            "Las dependencias se hacen gráficamente, como en MS Project:\n"
            "  1. Arrastra una barra HACIA OTRA (hacia arriba/abajo). Ya no "
            "hay puntos ni handles: agarras la barra y la llevas a su "
            "predecesora/sucesora.\n"
            "  2. El tipo se decide por DÓNDE sueltas en la barra destino:\n"
            "       al inicio         =  FC  (fin→comienzo, default)\n"
            "       al fin            =  FF  (fin→fin)\n"
            "       al tercio central =  CC+50% (el sucesor comienza cuando "
            "la pred. lleva el 50%)\n"
            "  3. Clic derecho sobre la flecha → cambiar tipo (FC/CC/FF/CF), "
            "editar lag (días) o el %.\n"
            "  4. Arrastra la flecha horizontalmente → ajusta el lag en "
            "días (o el % si la vinculaste a mitad de la pred.).\n"
            "  5. Clic + Supr → elimina la flecha. Ctrl+clic agrega varias "
            "a la selección para borrar en bloque.\n"
            "También puedes escribirlas en la columna Predecesoras: "
            "5 = FC, 5CC+2 = CC con lag, 5FF-1 = FF con lead, 5CF = CF."
    },
    {
        'tema': 'lag predecesora',
        'keywords': ['lag', 'retraso predecesora', 'dias entre tareas',
                     'esperar entre tareas', 'tiempo entre partidas'],
        'respuesta':
            "Para que B inicie X días después de que A termine (lag):\n"
            "  1. Crea la dependencia FC arrastrando la barra de B hacia "
            "A (sueltas al inicio).\n"
            "  2. Arrastra la flecha a la derecha → suma días. "
            "Una etiqueta naranja muestra el valor en vivo.\n"
            "  o clic derecho → Editar lag.\n"
            "Para lead (B antes que A termine), usa lag negativo."
    },
    {
        'tema': 'tarea al medio',
        'keywords': ['mitad de tarea', 'a la mitad', 'porcentaje pred',
                     'iniciar al 50', '50% del avance', 'cuando pred lleve',
                     'al 75'],
        'respuesta':
            "Dos modos diferentes:\n"
            "  • «Iniciar cuando pred. lleve X%» — B arranca cuando "
            "A ya tiene X% completado. La flecha sale del punto X% "
            "dentro de A. Útil para: empezar a vaciar concreto cuando "
            "el encofrado lleva 75%.\n"
            "  • «Llegar al X% del sucesor cuando pred termina» — "
            "cuando A termina, B ya está al X% completado. Útil para: "
            "cuando termine excavación, vaciado al 50%.\n"
            "Ambas se activan por clic derecho en la flecha. El PRIMER "
            "modo (CC+%, «cuando pred. lleve X%») también se crea soltando "
            "en el tercio central de la barra destino al enlazar."
    },
    {
        'tema': 'eliminar dependencia',
        'keywords': ['eliminar flecha', 'borrar dependencia',
                     'quitar predecesora', 'remover flecha',
                     'borrar enlace tareas'],
        'respuesta':
            "Tres maneras:\n"
            "  • Clic sobre la flecha → tecla Supr.\n"
            "  • Clic derecho → «✕ Eliminar dependencia».\n"
            "  • Ctrl+clic agrega varias flechas a la selección; Supr "
            "las elimina todas en un solo paso."
    },
    {
        'tema': 'tarea dividida',
        'keywords': ['dividir tarea', 'partir tarea', 'segmento gantt',
                     'pausar partida', 'tarea con pausa', 'linea entrecortada'],
        'respuesta':
            "Clic derecho sobre una barra → «✂ Dividir tarea». Aparece "
            "un nuevo segmento con un gap entre ambos.\n"
            "Los dos segmentos quedan unidos por una línea entrecortada "
            "(gris o roja si está en ruta crítica) — indica que son la "
            "misma partida.\n"
            "Para juntarlos: clic derecho → «⊞ Unir segmentos»."
    },
    {
        'tema': 'ruta critica',
        'keywords': ['ruta critica', 'critical path', 'tareas criticas',
                     'rojo gantt', 'que es critica'],
        'respuesta':
            "Las barras rojas (y la columna «Ítem» en rojo bold en la "
            "tabla) son la ruta crítica: tareas cuyo atraso retrasa el "
            "fin del proyecto. CPM las identifica automáticamente "
            "(holgura = 0).\n"
            "Las flechas que las conectan también salen en rojo."
    },
    {
        'tema': 'holgura',
        'keywords': ['holgura', 'float', 'slack', 'margen tarea',
                     'cuanto puede atrasarse'],
        'respuesta':
            "La holgura (float) es cuántos días puede atrasarse una "
            "tarea no crítica sin afectar el fin del proyecto.\n"
            "Para verla gráficamente: en la toolbar del Gantt, activa "
            "el botón «⏳ Holgura». Aparece una barra gris al final de "
            "cada tarea no crítica, terminando con un triángulo que "
            "marca el LF (Latest Finish)."
    },
    {
        'tema': 'zoom gantt',
        'keywords': ['zoom gantt', 'acercar gantt', 'alejar cronograma',
                     'ajustar zoom', 'ver completo proyecto',
                     'fit to width'],
        'respuesta':
            "En la toolbar del Gantt:\n"
            "  • Slider naranja entre [−] y [+]: zoom continuo.\n"
            "  • «⤢ Ajustar»: calcula el zoom para que el proyecto "
            "entero entre en pantalla.\n"
            "  • «100%»: vuelve al tamaño normal (16 px/día).\n"
            "  • Ctrl + rueda del mouse sobre el Gantt: también hace zoom.\n"
            "El slider se sincroniza con cualquier método de zoom."
    },
    {
        'tema': 'auto programar',
        'keywords': ['auto programar', 'programar automatico',
                     'sugerir dependencias', 'asignar dependencias ia',
                     'fases constructivas'],
        'respuesta':
            "Toolbar del Gantt → menú «Auto-programar ▾»:\n"
            "  • Modo Simple — secuencial: cada partida usa la anterior "
            "como predecesora.\n"
            "  • Modo Local (por fases) — agrupa por fase constructiva "
            "(preliminares → mov.tierras → estructuras → albañilería → "
            "instalaciones → acabados) y respeta paralelismos.\n"
            "  • Modo IA — usa LLM para analizar nombres y devolver "
            "dependencias realistas con ruta crítica coherente."
    },
    {
        'tema': 'feriados',
        'keywords': ['feriados', 'dias no laborables', 'domingos',
                     'calendario peruano', 'no trabajar fecha'],
        'respuesta':
            "Toolbar del Gantt → botón «Feriados…». Lista una fecha por "
            "línea (YYYY-MM-DD). El motor CPM las salta junto con los "
            "domingos al calcular fechas. Visualmente, los días no "
            "laborables se sombrean en naranja claro (feriados) y "
            "gris claro (domingos)."
    },
    {
        'tema': 'mover panel acu',
        'keywords': ['mover panel', 'cambiar layout proyecto',
                     'ocultar acu', 'reordenar paneles'],
        'respuesta':
            "El layout del proyecto es responsivo:\n"
            "  • Ventana < 750px → solo se muestra el árbol del "
            "presupuesto, el ACU se oculta.\n"
            "  • Ventana ≥ 750px → ambos paneles visibles, lado-a-lado "
            "o apilados según la orientación de tu pantalla.\n"
            "  • Botón «mover panel» en la toolbar fija manualmente la "
            "orientación a tu gusto."
    },
    # ── Fórmula polinómica ────────────────────────────────────────────
    {
        'tema': 'formula polinomica',
        'keywords': ['formula polinomica', 'fórmula polinómica', 'reajuste',
                     'monomios', 'inei polinomica'],
        'respuesta':
            "Toolbar → «Fórmula». Auto-deriva 3 monomios (J/M/E) desde el "
            "ACU del proyecto. Verifica que ΣK = 1.000. Para reajuste real, "
            "actualiza los índices INEI en «Índices Unificados» del menú "
            "superior derecho.\n"
            "(NO aplica en obras por Administración Directa.)"
    },
    # ── Configuración / IA ────────────────────────────────────────────
    {
        'tema': 'configurar ia',
        'keywords': ['configurar ia', 'api key', 'agregar api',
                     'cambiar proveedor ia', 'activar ia'],
        'respuesta':
            "Toolbar superior derecha → «Configuración» → tab «IA». Elige "
            "el proveedor (Anthropic, OpenAI, Groq, OpenRouter, Gemini, "
            "Ollama) y pega tu API key. Prueba conexión antes de guardar."
    },
    # ── Atajos ────────────────────────────────────────────────────────
    {
        'tema': 'atajos teclado',
        'keywords': ['atajo', 'atajos', 'shortcut', 'teclado', 'que teclas'],
        'respuesta':
            "Atajos clave:\n"
            "  • Ctrl+C / Ctrl+V — copiar / pegar partidas (árbol y ACU)\n"
            "  • Delete — eliminar partida seleccionada\n"
            "  • Escape — deseleccionar\n"
            "  • F5 — recalcular todo el proyecto\n"
            "  • Doble clic en metrado del árbol — editar inline"
    },
    # ── Asistente / chat ──────────────────────────────────────────────
    {
        'tema': 'abrir chat',
        'keywords': ['abrir chat', 'abrir asistente', 'mostrar tuxia',
                     'esconder chat'],
        'respuesta':
            "Botón «Asistente» en la toolbar del proyecto, o click sobre el "
            "icono flotante de tuxia (esquina inferior derecha)."
    },
]


# ── Calculadora local (parser AST seguro) ────────────────────────────────────

import ast
import operator as _op

_CALC_OPS = {
    ast.Add: _op.add,
    ast.Sub: _op.sub,
    ast.Mult: _op.mul,
    ast.Div: _op.truediv,
    ast.Mod: _op.mod,
    ast.Pow: _op.pow,
    ast.FloorDiv: _op.floordiv,
    ast.USub: _op.neg,
    ast.UAdd: _op.pos,
}


def _calc_eval_node(node):
    """Evalúa un nodo AST limitado a operaciones aritméticas sobre números.
    Levanta ValueError si encuentra nodos no permitidos (variables, llamadas,
    atributos, etc.) — más seguro que `eval()`."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _CALC_OPS:
        return _CALC_OPS[type(node.op)](
            _calc_eval_node(node.left), _calc_eval_node(node.right)
        )
    if isinstance(node, ast.UnaryOp) and type(node.op) in _CALC_OPS:
        return _CALC_OPS[type(node.op)](_calc_eval_node(node.operand))
    raise ValueError("nodo no permitido")


def evaluar_calculo(mensaje: str) -> str | None:
    """Si el mensaje parece una operación aritmética, la evalúa de forma
    segura (sin `eval()`) y retorna el resultado formateado. Acepta:

    - Operadores: + - * / % ** //  ·  alias: × ÷ x
    - Paréntesis: ( )
    - Separadores decimales: . o , (normalizados a punto)
    - Prefijo opcional "calcula", "cuánto es", "=" — los ignora.

    Returns None si el mensaje no es una operación válida (para que el
    flujo de respuesta continúe con el manual / IA)."""
    import re
    if not mensaje:
        return None
    m = mensaje.strip()
    # Quitar prefijos comunes de pregunta
    m = re.sub(
        r'^(calcula|calcular|cuanto es|cuánto es|cuanto da|cuánto da|=|cuanto vale|cuánto vale)\s*[:?]?\s*',
        '', m, flags=re.IGNORECASE
    )
    m = m.strip('?.! \t').strip()
    if not m:
        return None
    # Rechazar si tiene letras (excepto x como multiplicador)
    if re.search(r'[a-wyzA-WYZ]', m):
        return None
    # Normalizar
    expr = re.sub(r'\s+', '', m)
    # Coma decimal típica peruana → punto
    expr = expr.replace(',', '.')
    # Alias visuales de operadores
    expr = expr.replace('×', '*').replace('·', '*').replace('÷', '/')
    expr = expr.replace('x', '*').replace('X', '*')
    expr = expr.replace('^', '**')
    # Solo permitir chars válidos
    if not re.fullmatch(r'[\d\+\-\*\/\.\(\)\%]+', expr):
        return None
    # Debe contener al menos un operador para considerarlo cálculo
    if not re.search(r'[\+\-\*\/\%]', expr):
        return None
    try:
        tree = ast.parse(expr, mode='eval')
        result = _calc_eval_node(tree.body)
    except (ValueError, SyntaxError, ZeroDivisionError, TypeError,
            OverflowError, RecursionError):
        return None
    # Formato amigable: enteros sin decimales, floats con miles + decimales
    if isinstance(result, bool):
        return None
    if isinstance(result, int):
        out = f"{result:,}"
    elif isinstance(result, float):
        if result.is_integer():
            out = f"{int(result):,}"
        else:
            out = f"{result:,.6f}".rstrip('0').rstrip('.')
    else:
        return None
    # Devolver con prefijo claro para que se distinga del resto
    return f"🧮 {expr.replace('**','^')} = {out}"


def _normalizar(s: str) -> str:
    """Lowercase + strip + acentos básicos. Helper compartido para fuzzy."""
    s = s.lower().strip()
    for orig, repl in (('á','a'),('é','e'),('í','i'),('ó','o'),('ú','u'),('ñ','n')):
        s = s.replace(orig, repl)
    return s


# Stopwords ES — descartadas antes de comparar tokens significativos.
_STOPWORDS_ES = frozenset({
    'como','donde','cuando','que','cual','cuanto','para','desde','hasta',
    'sobre','entre','con','del','una','uno','los','las','el','la','un',
    'de','en','al','le','mi','tu','su','se','lo','y','o','a','i','es',
    'son','esta','si','este','ese','soy','va','fue','ser','sera','sea',
    'asi','aqui','alli','solo','tan','tal','mas','muy','algo',
})

# Sufijos del español (mayor a menor longitud para greedy match).
_SUFIJOS_ES = (
    'iendo','ando','aron','eron','aria','eria','aban','imos','emos','amos',
    'aste','iste','ado','ido','ar','er','ir','an','en','as','es','os','o','a','e',
)


def _stem(t: str) -> str:
    """Stemmer minimalista para español: corta sufijos verbales/plurales
    para que 'creo'='crear', 'agrego'='agregar', 'partidas'='partida'."""
    if len(t) < 4:
        return t
    for suf in _SUFIJOS_ES:
        if t.endswith(suf) and len(t) - len(suf) >= 3:
            return t[:-len(suf)]
    return t


def _signif_tokens(s: str) -> list[str]:
    """Tokens ≥4 chars que no son stopwords."""
    return [t for t in s.split() if len(t) >= 4 and t not in _STOPWORDS_ES]


def _stems_match(a: str, b: str) -> bool:
    """¿Dos tokens significativos refieren a la misma palabra raíz?"""
    sa, sb = _stem(a), _stem(b)
    if sa == sb:
        return True
    common = 0
    for x, y in zip(sa, sb):
        if x == y:
            common += 1
        else:
            break
    if common >= 4:
        return True
    try:
        from rapidfuzz import fuzz
        if len(sa) >= 3 and len(sb) >= 3 and fuzz.ratio(sa, sb) >= 80:
            return True
    except ImportError:
        pass
    return False


def buscar_manual(mensaje: str) -> str | None:
    """Busca un tema del manual que coincida con el mensaje (paráfrasis OK).

    Devuelve la respuesta del manual o None si no hay match suficiente. El
    LLM/IA solo se invoca si esto devuelve None.

    Algoritmo (dos pasadas):
      1. **Substring exacto** → win inmediato con score `200 + len(kw)`.
      2. **Fuzzy** con `rapidfuzz`:
         - `coverage` = fracción de tokens significativos de la keyword que
           aparecen en el mensaje (vía stem match → tolera 'añado'/'añadir').
         - `WRatio` = score general 0-100 (rapidfuzz combina ratio,
           partial_ratio, token_sort, token_set con pesos).
         - **score final = WRatio × coverage** → si la kw tiene un único
           token significativo y NO está en el msg, coverage=0 → score=0
           (filtra falsos positivos como 'flecha' vs 'chao').

      Threshold 60: caché de pruebas dio 23/24 sobre paráfrasis comunes
      (cómo añado/creo/elimino/borro/exporto + casos conversacionales).
    """
    if not mensaje:
        return None
    m = _normalizar(mensaje)
    if not m:
        return None

    # ── Filtro de intent: el manual responde "cómo HACER algo en la app".
    # Si el usuario pide ANÁLISIS, EVALUACIÓN o INFORMACIÓN TÉCNICA (datos
    # de construcción/CAPECO/RNE), debe ir a la IA — no al manual. Solo
    # cae al manual cuando claramente quiere instrucciones de la app.
    _ANALISIS_TRIGGERS = (
        # Análisis / opinión del estado actual
        'estan bien', 'esta bien', 'esta correcto', 'estan correcto',
        'es correcto', 'son correctos', 'es correcta', 'son correctas',
        'falta algo', 'que falta', 'faltan', 'falto',
        'que opinas', 'que piensas', 'que crees', 'tu opinion',
        'evalua', 'evaluas', 'evaluar', 'analiza', 'analizas', 'analizar',
        'revisa', 'revisas', 'revisar', 'revision',
        'dime sobre', 'dime de', 'cuentame', 'que tal',
        'esta completo', 'estan completos', 'esta lleno',
        'esta vacio', 'estan vacios',
        'como va', 'tiene sentido', 'tienen sentido',
        'me falta', 'le falta', 'les falta',
        # Consulta de INFORMACIÓN técnica (no instrucción de la app)
        'cual es', 'cual era', 'cuales son', 'cuales eran',
        'que es', 'que son', 'que era',
        'cuanto es', 'cuanto vale', 'cuanto cuesta',
        'tipico', 'tipica', 'tipicos', 'tipicas',
        'promedio', 'estandar', 'estándar', 'habitual', 'usual',
        'segun capeco', 'segun rne', 'segun ntp', 'segun norma',
        'capeco', 'rne ', 'ntp ', 'astm',
        'rango', 'ranking', 'valores tipicos', 'valor tipico',
        # Preguntas "qué + sustantivo" → consultivo (lista/info)
        'que insumo', 'que insumos', 'que material', 'que materiales',
        'que equipo', 'que equipos', 'que recurso', 'que recursos',
        'que partida', 'que partidas', 'que rubro', 'que rubros',
        'que norma', 'que normas', 'que rendimiento', 'que cuadrilla',
        'que precio', 'que precios', 'que valor', 'que cantidad',
        'que unidad', 'que diametro', 'que diámetro',
        'que riesgo', 'que riesgos', 'que tipo de',
        # Verbos consultivos / de listado
        'deberia', 'debería', 'deben tener', 'debe tener', 'debe haber',
        'recomienda', 'recomiendas', 'recomendable', 'sugiere',
        'dame ', 'muestrame', 'muéstrame', 'enséñame el', 'enséñame los',
        'sabes ', 'conoces ',
        'lista de', 'listado de', 'lista los', 'lista las', 'lista cada',
        'enumera', 'menciona', 'indica los', 'indica las', 'indica el',
        'ejemplo de', 'ejemplos de',
        'en peru', 'en lima', 'en sierra', 'en selva', 'en costa',
    )
    if any(t in m for t in _ANALISIS_TRIGGERS):
        return None

    try:
        from rapidfuzz import fuzz
        _have_fuzz = True
    except ImportError:
        _have_fuzz = False

    mejor: tuple[float, dict] | None = None
    for entry in MANUAL:
        for kw in entry['keywords']:
            kw_n = _normalizar(kw)
            if not kw_n:
                continue
            # 1) Substring exacto → score alto con bonus por longitud.
            if kw_n in m:
                score = 200.0 + len(kw_n)
            elif _have_fuzz:
                # 2) Coverage de tokens significativos via stem match.
                kw_signif = _signif_tokens(kw_n)
                m_signif = _signif_tokens(m)
                if not kw_signif or not m_signif:
                    continue
                shared = sum(
                    1 for kt in kw_signif
                    if any(_stems_match(kt, mt) for mt in m_signif)
                )
                coverage = shared / len(kw_signif)
                if coverage == 0:
                    continue
                # WRatio × coverage — WRatio para shape, coverage para
                # discriminar y romper empates.
                score = fuzz.WRatio(kw_n, m) * coverage
            else:
                continue
            if mejor is None or score > mejor[0]:
                mejor = (score, entry)

    if mejor is None or mejor[0] < 60.0:
        return None
    entry = mejor[1]
    return f"📘 {entry['tema'].title()}\n\n{entry['respuesta']}"


def detectar_conversacional(mensaje: str) -> str | None:
    """Detecta mensajes conversacionales simples (saludo, agradecimiento,
    despedida, confirmación). Devuelve respuesta local o None si no aplica.

    Esto evita gastar tokens en la IA para charla casual y da respuestas
    instantáneas con personalidad propia.
    """
    m = (mensaje or '').strip().lower()
    if not m or len(m) > 60:
        return None
    # Saludos
    if m in ('hola', 'hi', 'hey', 'buenas', 'buenos dias', 'buenos días',
             'buenas tardes', 'buenas noches', 'que tal', 'qué tal',
             'hola tuxia', 'hola tux', 'saludos'):
        opciones = [
            "¡Hola! 🐧 Soy tuxia, tu asistente de presupuestos. ¿En qué te ayudo?",
            "¡Buenas! ¿Tienes alguna duda sobre el proyecto o la partida abierta?",
            "¡Saludos! Puedes preguntarme por rendimientos, precios, metrados, o pedirme análisis. También /help para ver comandos.",
            "¡Hola! Estoy aquí para ayudarte con tu presupuesto. Pregunta libremente o usa /help para ver atajos.",
        ]
        return random.choice(opciones)
    # Agradecimientos
    if m in ('gracias', 'thx', 'thanks', 'ok gracias', 'genial', 'perfecto',
             'mil gracias', 'muchas gracias', 'super', 'súper', 'excelente',
             'muy bien', 'bien'):
        opciones = [
            "¡De nada! Aquí estoy si necesitas otra cosa.",
            "¡Con gusto! Cualquier otra duda, me dices.",
            "🐧 ¡Para eso estoy! Sigue construyendo.",
            "✦ Me alegra ayudar. ¿Algo más?",
        ]
        return random.choice(opciones)
    # Despedidas
    if m in ('chao', 'adios', 'adiós', 'bye', 'hasta luego', 'nos vemos',
             'me voy', 'eso es todo', 'eso seria todo', 'eso sería todo'):
        opciones = [
            "¡Hasta luego! Nos vemos cuando me necesites.",
            "🐧 ¡Suerte con el proyecto!",
            "Adiós. Recuerda guardar tu trabajo (Ctrl+S por si acaso).",
        ]
        return random.choice(opciones)
    # Confirmaciones cortas
    if m in ('si', 'sí', 'no', 'ok', 'okay', 'vale', 'claro', 'dale'):
        return ("Entendido. ¿Quieres que profundicemos en algo? "
                "Puedes preguntar libremente o usar /help para ver comandos.")
    # Identidad
    if m in ('quien eres', 'quién eres', 'que eres', 'qué eres',
             'como te llamas', 'cómo te llamas'):
        return (
            f"{TUX_NORMAL}\n\n"
            "Soy tuxia — la prima pingüino de Tux. Te ayudo con tu "
            "presupuesto: rendimientos, ACU, metrados, precios, fórmula "
            "polinómica y más. Usa /help para ver mis comandos."
        )
    return None


def respuesta_offline(mensaje: str, proyecto_id: int | None = None) -> str:
    """Respuesta local cuando no hay IA configurada. Reconoce keywords
    simples y devuelve un análisis o un tip relevante.
    """
    m = (mensaje or '').lower()
    if any(k in m for k in ('analiza', 'revisa', 'informe', 'resumen', 'check')):
        if proyecto_id:
            return analizar_proyecto(proyecto_id)
        return f"{TUX_TIP}\n\nAbre un proyecto para hacer el análisis."
    if any(k in m for k in ('total', 'monto', 'cuanto cuesta', 'precio total')):
        if proyecto_id:
            return totales_detalle(proyecto_id)
    if any(k in m for k in ('insumo', 'recurso', 'material')):
        if proyecto_id:
            return top_insumos(proyecto_id)
    if any(k in m for k in ('partida', 'top partid', 'caras')):
        if proyecto_id:
            return top_partidas(proyecto_id)
    if any(k in m for k in ('pendiente', 'falta', 'faltante', 'incomplet')):
        if proyecto_id:
            return pendientes(proyecto_id)
    if any(k in m for k in ('tip', 'consejo', 'recomienda', 'sugerencia')):
        return f"{TUX_TIP}\n\n💡 {tip_aleatorio()}"
    if any(k in m for k in ('chiste', 'broma', 'humor', 'gracia')):
        return f"{TUX_FELIZ}\n\n😄 {chiste_aleatorio()}"
    if any(k in m for k in ('motivame', 'anima', 'cansado', 'aburrido')):
        return f"{TUX_FELIZ}\n\n✦ {mensaje_motivacional()}"
    if any(k in m for k in ('hola', 'buenas', 'hey', 'ayuda', 'help', 'comando', 'menu')):
        return bienvenida()
    # Default: invitar a usar comandos o configurar IA
    return (
        f"{TUX_NORMAL}\n\n"
        "Estoy en modo offline (sin IA configurada).\n\n"
        f"{lista_comandos_corta()}\n\n"
        "Para conversar con la IA: Configuración → IA → agrega tu API key."
    )
