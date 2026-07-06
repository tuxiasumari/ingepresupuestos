# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""Control de Obra · Generación de REQUERIMIENTOS y TÉRMINOS DE REFERENCIA (TDR)
/ ESPECIFICACIONES TÉCNICAS (EE.TT.) con IA.

A partir de un requerimiento (lista de insumos que vienen del presupuesto) la IA
redacta el documento formal completo: encabezado, cuerpo, tabla de ítems y el TDR
o las especificaciones técnicas, según el tipo (servicio/bien). Sirve igual al
sector público (municipalidad, gobierno regional, unidad ejecutora — formato
memorando A/ATENCIÓN/DE) que al privado (empresa o consultor — membrete simple);
el formato se elige solo según los datos que reciba.

Los datos de la entidad/solicitante salen de Configuración (`empresa_*`); los del
documento (número, destinatario, plazo, forma de pago…) llegan en `datos`.
"""

from core.database import get_db, get_config
from core import requerimientos as REQ
from core.ai_specs import _llamar_ia

_PLAZO_UNIDAD = {'dias': 'días calendario', 'meses': 'meses'}
_TIPO_TXT = {'mat': 'ADQUISICIÓN DE BIENES / MATERIALES',
             'eq': 'SERVICIO DE ALQUILER / OPERATIVO (equipos)',
             'sc': 'SERVICIO (consultoría / profesional / subcontrato)'}


def _es_acero(descripcion: str) -> bool:
    """Heurística: ¿el insumo es acero/fierro corrugado (se pide en varillas)?"""
    d = (descripcion or '').upper()
    return ('CORRUGAD' in d and ('ACERO' in d or 'FIERRO' in d)) or \
           ('ACERO' in d and 'FY' in d)


def _moneda_simbolo(proyecto_id: int) -> tuple[str, str]:
    conn = get_db()
    try:
        r = conn.execute("SELECT moneda FROM proyectos WHERE id=?",
                         (proyecto_id,)).fetchone()
    finally:
        conn.close()
    m = (r['moneda'] if r else '') or 'Soles'
    return (m, 'US$' if 'olar' in m or 'USD' in m.upper() else 'S/')


def _entidad_config() -> dict:
    return {
        'nombre': (get_config('empresa_nombre', '') or '').strip(),
        'ruc': (get_config('empresa_ruc', '') or '').strip(),
        'direccion': (get_config('empresa_direccion', '') or '').strip(),
        'telefono': (get_config('empresa_telefono', '') or '').strip(),
    }


def _tabla_items(filas: list, precios: dict, simbolo: str) -> tuple[str, float]:
    """Texto de la tabla de ítems + total referencial."""
    lineas, total = [], 0.0
    for i, f in enumerate(filas, start=1):
        rid = f.get('recurso_id')
        cant = f.get('cantidad') or 0
        pu = precios.get(rid, 0) if rid is not None else 0
        parcial = round(cant * pu, 2)
        total += parcial
        lineas.append(
            f"  {i}. {f.get('descripcion','')} | {f.get('unidad','')} | "
            f"cant={cant:g} | P.U.={simbolo} {pu:,.2f} | Total={simbolo} {parcial:,.2f}")
    return ('\n'.join(lineas) if lineas else '  (sin ítems cargados)'), round(total, 2)


def generar_tdr_ia(req_id: int, datos: dict, prompt_extra: str = '') -> tuple:
    """Genera el documento (requerimiento + TDR/EE.TT.) para el requerimiento.
    `datos` trae las variables del encabezado (numero, destinatario, atencion,
    cargo_*, entidad, unidad_organica, lugar, fecha, plazo, plazo_unidad,
    forma_pago, meta, objetivo). Devuelve (texto, error)."""
    ia_proveedor = get_config('ia_proveedor', '')
    api_key = get_config('api_key', '')
    if not api_key and ia_proveedor != 'ollama':
        return None, ('No hay clave API configurada. Ve a Configuración y añade '
                      'tu clave de IA.')

    q = REQ.get_requerimiento(req_id)
    if not q:
        return None, 'Requerimiento no encontrado.'
    pid = q['proyecto_id']
    tipo = REQ.tipo_de_requerimiento(q)
    filas = REQ.get_detalle(req_id, tipo)
    if not filas:
        return None, ('El requerimiento no tiene insumos. Agrega al menos uno '
                      'antes de generar el TDR.')

    conn = get_db()
    proy = conn.execute("SELECT nombre, cliente, ubicacion, modalidad FROM "
                        "proyectos WHERE id=?", (pid,)).fetchone()
    conn.close()
    proyecto = (proy['nombre'] if proy else '') or '(proyecto)'
    ubicacion = (proy['ubicacion'] if proy else '') or ''
    modalidad = (proy['modalidad'] if proy else '') or ''

    moneda, simbolo = _moneda_simbolo(pid)
    precios = REQ.precio_por_recurso(pid)
    tabla, total = _tabla_items(filas, precios, simbolo)

    # Si el requerimiento incluye acero corrugado, pasar el desglose en VARILLAS
    # de 9 m por diámetro (leído de la planilla de acero) para que el TDR lo pida
    # así (no en kg, como viene el insumo en el ACU).
    bloque_acero = ''
    if any(_es_acero(f.get('descripcion')) for f in filas):
        desglose = REQ.acero_varillas_por_diametro(pid)
        if desglose:
            lns = [f"  - Ø {x['diametro']}: {x['kg']:,.2f} kg "
                   f"({x['kg_ml']} kg/m) → {x['varillas']} varillas de 9 m"
                   for x in desglose]
            tot_var = sum(x['varillas'] for x in desglose)
            bloque_acero = (
                "\nDESGLOSE DEL ACERO CORRUGADO (el acero se PIDE en varillas de "
                "9 m POR DIÁMETRO, no en kg):\n" + '\n'.join(lns) +
                f"\n  TOTAL: {tot_var} varillas")

    ent = _entidad_config()
    d = datos or {}
    entidad = (d.get('entidad') or '').strip()
    destinatario = (d.get('destinatario') or '').strip()
    es_publico = bool(entidad or destinatario)
    solicitante = (d.get('solicitante') or ent['nombre'] or '').strip()
    plazo = (d.get('plazo') or '').strip()
    plazo_u = _PLAZO_UNIDAD.get(d.get('plazo_unidad') or 'dias', 'días')

    lugar = (d.get('lugar') or ubicacion or '').strip()
    plazo_linea = f"{plazo} {plazo_u}" if plazo else ''

    # Solo datos que la IA necesita para REDACTAR EL CUERPO (no el encabezado
    # personal — ese lo arma la app en el PDF).
    ctx = []
    if d.get('meta'):
        ctx.append(f"META: {d.get('meta').strip()}")
    if d.get('objetivo'):
        ctx.append(f"OBJETIVO: {d.get('objetivo').strip()}")
    if plazo_linea:
        ctx.append(f"PLAZO DE EJECUCIÓN: {plazo_linea}")
    if d.get('forma_pago'):
        ctx.append(f"FORMA DE PAGO: {d.get('forma_pago').strip()}")
    if lugar:
        ctx.append(f"LUGAR DE PRESTACIÓN / ENTREGA: {lugar}")
    ctx.append(f"INCLUIR PENALIDADES: {'sí' if es_publico else 'solo si aplica'}")
    bloque_ctx = '\n'.join(ctx)

    prompt = f"""{_SYSTEM}

════════════════════════════════════════════
DATOS DEL REQUERIMIENTO
════════════════════════════════════════════
PROYECTO / ACTIVIDAD: {proyecto}
{f'UBICACIÓN: {ubicacion}' if ubicacion else ''}
{f'MODALIDAD: {modalidad}' if modalidad else ''}
CATEGORÍA DEL REQUERIMIENTO: {q.get('categoria') or '(sin categoría)'}
TIPO DE INSUMO (sistema): {_TIPO_TXT.get(tipo, tipo)}
MONEDA: {moneda} ({simbolo})

{bloque_ctx}

INSUMOS SOLICITADOS (descripción | unidad | cantidad | P.U. | total):
{tabla}
TOTAL REFERENCIAL: {simbolo} {total:,.2f}
{bloque_acero}

════════════════════════════════════════════
INSTRUCCIONES FINALES
════════════════════════════════════════════
- NO escribas el encabezado (REQUERIMIENTO N°, A, ATENCIÓN, DE, ENTIDAD, FECHA) — eso lo agrega el sistema. Genera SOLO el cuerpo.
- La PRIMERA línea de tu respuesta debe ser exactamente «ASUNTO: <asunto>» (una sola línea); luego una línea en blanco y el cuerpo (párrafo de presentación, tabla de ítems y términos de referencia / especificaciones técnicas).
- ASUNTO: en adquisiciones nombra la CATEGORÍA; en SERVICIOS nombra el/los SERVICIO(S) concreto(s) (si hay 2+, nómbralos todos unidos con «Y» o combínalos), nunca la palabra genérica «SERVICIOS».
- Texto plano (sin markdown), títulos en MAYÚSCULAS y subtítulos numerados.
- CANTIDADES ENTERAS: las unidades que se piden por pieza (bolsa, galón, unidad, varilla, plancha, saco…) van SIN decimales (redondea hacia arriba).
- ACERO: si hay desglose de acero arriba, en la TABLA y en las especificaciones pídelo en VARILLAS de 9 m POR DIÁMETRO (una fila por diámetro: Ø, n° de varillas), NO en kg. Indica fy=4200 kg/cm², grado 60, NTP 341.031 / ASTM A615.
- En ESPECIFICACIONES TÉCNICAS detalla CADA insumo en su propio sub-bloque (norma NTP/ASTM, tipo/grado, calidad, presentación), no en una sola línea.
- Usa exactamente los insumos de la tabla; no inventes ítems ni precios.
- El monto total exprésalo también EN LETRAS.
{f'- INSTRUCCIONES ADICIONALES DEL USUARIO: {prompt_extra}' if prompt_extra and prompt_extra.strip() else ''}"""

    texto, error = _llamar_ia(prompt, api_key, max_tokens=3800)
    if error:
        return None, error

    # Separar el ASUNTO (1ª línea «ASUNTO: …») del cuerpo: el ASUNTO va al
    # encabezado que arma la app en el PDF; el cuerpo es lo editable.
    import json
    cuerpo, asunto = _separar_asunto(texto)
    datos_full = dict(d)
    datos_full.update({
        'numero': (d.get('numero') or '').strip() or str(q['numero']),
        'asunto': asunto,
        'es_publico': es_publico,
        'solicitante': solicitante,
        'ruc': ent['ruc'], 'direccion': ent['direccion'],
        'telefono': ent['telefono'],
        'lugar': lugar,
    })
    REQ.guardar_tdr(req_id, cuerpo, json.dumps(datos_full, ensure_ascii=False))
    return cuerpo, None


def _separar_asunto(texto: str) -> tuple:
    """Extrae el ASUNTO de la primera línea «ASUNTO: …» y devuelve (cuerpo, asunto).
    Si no la encuentra, asunto='' y cuerpo=texto íntegro."""
    lineas = (texto or '').split('\n')
    asunto = ''
    idx = None
    for i, ln in enumerate(lineas[:4]):   # buscar cerca del inicio
        s = ln.strip()
        if not s:
            continue
        if s.upper().startswith('ASUNTO'):
            asunto = s.split(':', 1)[1].strip() if ':' in s else ''
            idx = i
        break
    if idx is None:
        return (texto or '').strip(), ''
    resto = lineas[idx + 1:]
    while resto and not resto[0].strip():   # quitar líneas en blanco iniciales
        resto.pop(0)
    return '\n'.join(resto).strip(), asunto


_SYSTEM = """Eres un asistente experto en redacción de REQUERIMIENTOS y TÉRMINOS \
DE REFERENCIA (TDR) / ESPECIFICACIONES TÉCNICAS (EE.TT.) en el marco de la \
contratación peruana, tanto para el sector público (municipalidades, gobiernos \
regionales, unidades ejecutoras) como para el sector privado (empresas, \
consultores, contratistas).

A partir del requerimiento y su lista de insumos (que provienen de un \
presupuesto de obra), genera un documento formal completo, claro y listo para \
usar. Adáptate a los datos proporcionados; si un dato no existe, omite esa línea, \
SIN inventar nombres, RUC ni cargos.

PASO 1 — TIPO DE REQUERIMIENTO. Clasifica según los insumos y la categoría:
  TIPO A — SERVICIO DE CONSULTORÍA (estudio, perfil, expediente técnico, supervisión)
  TIPO B — SERVICIO DE ALQUILER / OPERATIVO (maquinaria, vehículo, equipo con operador)
  TIPO C — ADQUISICIÓN DE BIENES / MATERIALES (materiales, herramientas, insumos)
  TIPO D — SERVICIO MIXTO (materiales + mano de obra/equipos)

PASO 2 — ASUNTO. NO escribas el encabezado memorando (REQUERIMIENTO N°, A, \
ATENCIÓN, DE, ENTIDAD, FECHA): eso lo agrega el sistema en el PDF. Solo debes \
producir el ASUNTO como PRIMERA línea «ASUNTO: …» y luego el cuerpo.
ASUNTO por tipo: A → "SERVICIO DE CONSULTORÍA PARA [proyecto]"; B → "SERVICIO DE \
ALQUILER DE [equipo o categoría]"; C → "ADQUISICIÓN DE [CATEGORÍA DEL \
REQUERIMIENTO] PARA [proyecto]"; D → "SERVICIO DE MANTENIMIENTO / MEJORAMIENTO DE \
[proyecto]".
REGLAS DEL ASUNTO:
- ADQUISICIONES (tipo C / materiales): el ASUNTO nombra la CATEGORÍA DEL \
REQUERIMIENTO. Ej.: categoría «COMBUSTIBLES Y LUBRICANTES» → "ADQUISICIÓN DE \
COMBUSTIBLES Y LUBRICANTES PARA [proyecto]"; «CEMENTO Y AGLOMERANTES» → \
"ADQUISICIÓN DE CEMENTO Y AGLOMERANTES PARA [proyecto]".
- SERVICIOS (tipo sc / A / B): normalmente es UN servicio por requerimiento, así \
que el ASUNTO debe nombrar ESE servicio CONCRETO según la descripción del insumo \
(o de la categoría si ya es específica), NO la palabra genérica «SERVICIOS». Ej.: \
insumo «PRUEBA HIDRÁULICA» → "SERVICIO DE PRUEBA HIDRÁULICA"; «ALQUILER DE \
RETROEXCAVADORA» → "SERVICIO DE ALQUILER DE RETROEXCAVADORA"; «ELABORACIÓN DE \
EXPEDIENTE TÉCNICO» → "SERVICIO DE CONSULTORÍA PARA LA ELABORACIÓN DEL EXPEDIENTE \
TÉCNICO». Si hay DOS O MÁS servicios en el requerimiento, NÓMBRALOS a todos en el \
ASUNTO unidos con «Y» / comas, o combínalos en un nombre representativo que los \
englobe. Ej.: servicios «PRUEBA HIDRÁULICA» + «DESINFECCIÓN DE TUBERÍAS» → \
"SERVICIO DE PRUEBA HIDRÁULICA Y DESINFECCIÓN DE TUBERÍAS"; «ALQUILER DE VOLQUETE» \
+ «ALQUILER DE CARGADOR FRONTAL» → "SERVICIO DE ALQUILER DE VOLQUETE Y CARGADOR \
FRONTAL". No omitas servicios ni uses la palabra genérica «SERVICIOS».

PASO 3 — CUERPO Y TABLA (empieza aquí, después de la línea «ASUNTO: …»).
- Párrafo de presentación: qué se solicita, proyecto/actividad, justificación \
breve de la necesidad y referencia a los adjuntos (Requerimiento + TDR/EE.TT.).
- Marca BIEN (tipo C) o SERVICIO (A, B, D); ambos si D.
- Tabla: ÍTEM | DESCRIPCIÓN | UNIDAD | CANTIDAD | P.U. | TOTAL (usa los insumos dados).
- TOTAL referencial en la moneda indicada + el monto EN LETRAS.

PASO 4 — TÉRMINOS DE REFERENCIA / ESPECIFICACIONES TÉCNICAS. Incluye, adaptando \
al tipo:
  1. DENOMINACIÓN
  2. OBJETIVO DE LA CONTRATACIÓN
  3. FINALIDAD (pública si es entidad; objetivo de la empresa si privado)
  4. PERFIL DEL PROVEEDOR / PROFESIONAL
     A: profesional colegiado y habilitado, experiencia en proyectos similares.
     B: RUC activo, propiedad/disponibilidad del equipo, SOAT y revisión técnica vigentes, antigüedad razonable.
     C: RUC activo (y RNP vigente si es contratación pública).
     D: ambos perfiles.
  5. ALCANCES / ESPECIFICACIONES TÉCNICAS
     A: trabajos de campo, formulación, entregables.
     B: disponibilidad, traslados, zonas de cobertura, características del equipo.
     C: dedica un SUB-BLOQUE por CADA insumo (NO una sola línea) con: denominación,
        NORMA TÉCNICA peruana (NTP) o ASTM específica, tipo/clase/grado, características
        físicas y de calidad, dimensiones/presentación/embalaje, unidad y criterios de
        aceptación/control de calidad. Nivel de detalle esperado (adáptalo al insumo real):
        · CEMENTO → tipo (I, IP, MS, HS…) según uso, NTP 334.009 / 334.082, resistencia, bolsa 42.5 kg, almacenamiento.
        · ACERO CORRUGADO → grado 60, fy = 4200 kg/cm², NTP 341.031 / ASTM A615, corrugado, longitud de barra.
        · AGREGADOS (arena/piedra) → NTP 400.037, granulometría / módulo de fineza, libre de impurezas orgánicas, tamaño máximo.
        · LADRILLO → NTP 331.017, tipo (King Kong 18 huecos…), resistencia, dimensiones.
        · TUBERÍA PVC → NTP-ISO 1452 / NTP 399.002, clase/presión, diámetro, tipo de unión.
        · COMBUSTIBLE → tipo (Diésel B5 S-50, gasolina 90/95…), especificación de calidad, presentación.
        · PINTURA → tipo (látex/esmalte), norma, rendimiento, acabado, color.
     D: descripción de los trabajos a ejecutar + especificaciones de los materiales clave.
  6. ENTREGABLES / PRESENTACIÓN (A y D)
  7. PLAZO DE EJECUCIÓN (días para A; meses para B/C/D, según lo indicado)
  8. LUGAR DE PRESTACIÓN / ENTREGA
  9. FORMA DE PAGO (único / mensual / por avance, previa conformidad)
  10. PENALIDADES (solo si se indica incluirlas):
      Penalidad diaria = (0.10 × Monto Total) / (F × Plazo en días);
      F = 0.40 si plazo ≤ 60 días, F = 0.25 si plazo > 60 días.
  11. CONFORMIDAD (otorgada por el área/solicitante)
  12. CONFIDENCIALIDAD Y PROPIEDAD INTELECTUAL (A y D)

Redacta en español formal peruano, sin relleno. No inventes datos faltantes.

FORMATO DE SALIDA: texto plano (NO uses asteriscos, almohadillas ni markdown).
Escribe los TÍTULOS de sección en MAYÚSCULAS en su propia línea y numera los
subtítulos (1., 1.1, 2., …); así se resaltan automáticamente en el documento."""
