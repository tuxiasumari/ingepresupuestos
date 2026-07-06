# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""
ai_specs.py — Generador de especificaciones técnicas con IA.
Proveedores soportados:
  - Groq      (clave gsk_)        — gratis, llama-3.3-70b
  - Anthropic (clave sk-ant-)     — claude-haiku-4-5
  - OpenAI    (clave sk-)         — gpt-4o-mini / gpt-4o
  - Gemini    (clave AIza)        — gemini-2.5-flash (free tier) / gemini-2.0-flash
  - Ollama    (ia_proveedor=ollama) — modelo local
"""

from core.database import get_db, get_config, set_config


# ── Detección de proveedor ─────────────────────────────────────────────────

def _detectar_proveedor(api_key: str) -> str:
    if not api_key:
        return 'groq'
    if api_key.startswith('gsk_'):
        return 'groq'
    if api_key.startswith('sk-ant-'):
        return 'anthropic'
    if api_key.startswith('AIza'):
        return 'gemini'
    if api_key.startswith('sk-or-'):
        return 'openrouter'
    if api_key.startswith('sk-'):
        return 'openai'
    return 'anthropic'


def _proveedor_activo() -> str:
    """Lee ia_proveedor de la BD; si no está, lo detecta por el prefijo de la clave."""
    ia_proveedor = get_config('ia_proveedor', '')
    if ia_proveedor in ('groq', 'anthropic', 'openai', 'gemini', 'ollama', 'openrouter'):
        return ia_proveedor
    api_key = get_config('api_key', '')
    return _detectar_proveedor(api_key)


# ── Llamada a Ollama ───────────────────────────────────────────────────────

def _llamar_ollama(prompt: str, max_tokens: int = 1500):
    """Llama al servidor Ollama local via API nativa /api/chat."""
    import json
    import urllib.request
    import urllib.error

    url     = get_config('ollama_url',    'http://localhost:11434').rstrip('/')
    modelo  = get_config('ollama_modelo', 'llama3.2')
    endpoint = f"{url}/api/chat"

    payload = json.dumps({
        "model":    modelo,
        "messages": [{"role": "user", "content": prompt}],
        "stream":   False,
        "options":  {"num_predict": max_tokens},
    }).encode()

    req = urllib.request.Request(
        endpoint,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
        texto = data.get("message", {}).get("content", "")
        if not texto:
            return None, "Ollama no devolvió respuesta. Verifica que el modelo esté descargado."
        return texto, None
    except urllib.error.URLError as e:
        return None, f"No se pudo conectar a Ollama en {url}. ¿Está corriendo? ({e.reason})"
    except Exception as e:
        return None, f"Error Ollama: {e}"


# ── Llamadas por proveedor ────────────────────────────────────────────────

def _llamar_groq(prompt: str, api_key: str, max_tokens: int):
    try:
        from groq import Groq
        client   = Groq(api_key=api_key)
        modelo   = get_config('groq_modelo', 'llama-3.3-70b-versatile')
        response = client.chat.completions.create(
            model=modelo, max_tokens=max_tokens,
            messages=[{'role': 'user', 'content': prompt}]
        )
        return response.choices[0].message.content, None
    except Exception as e:
        err = str(e)
        if 'authentication' in err.lower() or 'invalid' in err.lower():
            return None, 'Clave Groq incorrecta. Verifica en Configuración.'
        if 'rate' in err.lower():
            return None, 'Límite Groq alcanzado. Intenta en unos minutos.'
        return None, f'Error Groq: {err}'


def _llamar_anthropic(prompt: str, api_key: str, max_tokens: int):
    try:
        import anthropic
        client  = anthropic.Anthropic(api_key=api_key)
        modelo  = get_config('anthropic_modelo', 'claude-haiku-4-5-20251001')
        message = client.messages.create(
            model=modelo, max_tokens=max_tokens,
            messages=[{'role': 'user', 'content': prompt}]
        )
        return message.content[0].text, None
    except Exception as e:
        err = str(e)
        if 'authentication' in err.lower():
            return None, 'Clave Anthropic incorrecta. Verifica en Configuración.'
        if 'rate' in err.lower():
            return None, 'Límite Anthropic alcanzado. Intenta en unos minutos.'
        return None, f'Error Anthropic: {err}'


def _llamar_openai(prompt: str, api_key: str, max_tokens: int):
    try:
        from openai import OpenAI
        client   = OpenAI(api_key=api_key)
        modelo   = get_config('openai_modelo', 'gpt-4o-mini')
        response = client.chat.completions.create(
            model=modelo, max_tokens=max_tokens,
            messages=[{'role': 'user', 'content': prompt}]
        )
        return response.choices[0].message.content, None
    except Exception as e:
        err = str(e)
        if 'authentication' in err.lower() or 'incorrect' in err.lower():
            return None, 'Clave OpenAI incorrecta. Verifica en Configuración.'
        if 'rate' in err.lower() or 'quota' in err.lower():
            return None, 'Límite OpenAI alcanzado. Revisa tu cuenta.'
        return None, f'Error OpenAI: {err}'


def _llamar_openrouter(prompt: str, api_key: str, max_tokens: int):
    try:
        from openai import OpenAI
        client   = OpenAI(api_key=api_key, base_url='https://openrouter.ai/api/v1')
        modelo   = get_config('openrouter_modelo', 'meta-llama/llama-3.3-70b-instruct:free')
        response = client.chat.completions.create(
            model=modelo, max_tokens=max_tokens,
            messages=[{'role': 'user', 'content': prompt}],
            extra_headers={'X-Title': 'ingePresupuestos'},
        )
        return response.choices[0].message.content, None
    except Exception as e:
        err = str(e)
        if 'authentication' in err.lower() or 'invalid' in err.lower() or '401' in err:
            return None, 'Clave OpenRouter incorrecta. Verifica en Configuración.'
        if '404' in err or 'No endpoints found' in err:
            return None, (
                f'El modelo "{modelo}" ya no tiene endpoints activos en OpenRouter.\n'
                'Use ↺ Actualizar lista en Configuración para ver los modelos disponibles.'
            )
        if 'rate' in err.lower() or 'quota' in err.lower() or '429' in err:
            return None, f'Límite OpenRouter alcanzado. Intenta en unos minutos.\n{err}'
        return None, f'Error OpenRouter: {err}'


def _gemini_modelo_disponible(client, prefer: str = 'flash') -> str | None:
    """Pregunta a Google qué modelos hay y elige uno que soporte generación de
    contenido (prefiriendo los «flash», más baratos/rápidos). Permite que la app
    sobreviva a cambios de versión (p.ej. si Google retira el modelo configurado
    al sacar Gemini 3): se autodescubre el reemplazo. Devuelve el nombre o None."""
    try:
        candidatos = []
        for m in client.models.list():
            name = (getattr(m, 'name', '') or '').split('/')[-1]
            if not name or 'embedding' in name.lower() or 'aqa' in name.lower():
                continue
            acciones = (getattr(m, 'supported_actions', None)
                        or getattr(m, 'supported_generation_methods', None) or [])
            if acciones and 'generateContent' not in acciones:
                continue
            candidatos.append(name)
        if not candidatos:
            return None
        import re as _re
        def _ver(nl):
            m = _re.search(r'(\d+(?:\.\d+)?)', nl)
            return float(m.group(1)) if m else 0.0
        # Preferir: flash estable > flash > estable > resto; dentro de cada grupo,
        # los alias «-latest» primero y luego la versión más nueva. Así sobrevive
        # a Gemini 3, 4… eligiendo siempre lo más reciente disponible.
        def _rank(n):
            nl = n.lower()
            es_flash = prefer in nl
            estable = not any(t in nl for t in ('preview', 'exp', 'thinking'))
            grupo = 0 if (es_flash and estable) else 1 if es_flash else 2 if estable else 3
            return (grupo, 0 if 'latest' in nl else 1, -_ver(nl), n)
        candidatos.sort(key=_rank)
        return candidatos[0]
    except Exception:
        return None


def _llamar_gemini(prompt: str, api_key: str, max_tokens: int):
    try:
        from google import genai
        from google.genai import types
        modelo = get_config('gemini_modelo', 'gemini-2.5-flash') or 'gemini-2.5-flash'
        client = genai.Client(api_key=api_key)
        # Los modelos «2.5» son de razonamiento (thinking): gastan tokens
        # «pensando» antes de responder y, con un max_output_tokens acotado, se
        # quedan sin presupuesto para el texto → respuestas cortadas (2 líneas).
        # Desactivamos el thinking (budget=0) para que TODO el presupuesto vaya
        # a la respuesta, como en Groq/2.0-flash. Guard por si el SDK es viejo.
        cfg_kwargs = {'max_output_tokens': max_tokens}
        try:
            cfg_kwargs['thinking_config'] = types.ThinkingConfig(thinking_budget=0)
        except Exception:
            pass
        cfg = types.GenerateContentConfig(**cfg_kwargs)
        try:
            resp = client.models.generate_content(model=modelo, contents=prompt, config=cfg)
            return resp.text, None
        except Exception as e_mod:
            # ¿El modelo configurado ya no existe/soporta generación? (típico al
            # cambiar de versión). Autodescubrir un reemplazo, usarlo y guardarlo.
            em = str(e_mod)
            if any(s in em for s in ('NOT_FOUND', 'not found', '404',
                                     'is not supported', 'not supported for',
                                     'is not found for API version')):
                alt = _gemini_modelo_disponible(client)
                if alt and alt != modelo:
                    resp = client.models.generate_content(model=alt, contents=prompt, config=cfg)
                    try:
                        set_config('gemini_modelo', alt)
                    except Exception:
                        pass
                    return resp.text, None
            raise
    except Exception as e:
        err = str(e)
        if 'api_key' in err.lower() or 'api key' in err.lower():
            return None, f'Clave Gemini incorrecta. Verifica en Configuración.\nDetalle: {err}'
        if '429' in err and 'limit: 0' in err:
            return None, (
                f'El modelo «{modelo}» no tiene cuota gratuita para esta clave '
                '(cuota = 0).\n'
                '• Prueba el modelo «gemini-2.5-flash» (sí tiene free tier).\n'
                '• Y verifica que la clave sea de aistudio.google.com/app/apikey '
                '(las de Google Cloud Console vienen con cuota 0).'
            )
        if '429' in err or 'RESOURCE_EXHAUSTED' in err:
            return None, f'Límite Gemini alcanzado. Intenta en unos minutos.\nDetalle: {err}'
        return None, f'Error Gemini: {err}'


# ── Llamada unificada ──────────────────────────────────────────────────────

def _llamar_ia(prompt: str, api_key: str, max_tokens: int = 1500):
    """Despacha al proveedor activo configurado en la BD."""
    proveedor = _proveedor_activo()
    if proveedor == 'ollama':
        return _llamar_ollama(prompt, max_tokens)
    if proveedor == 'groq':
        return _llamar_groq(prompt, api_key, max_tokens)
    if proveedor == 'openai':
        return _llamar_openai(prompt, api_key, max_tokens)
    if proveedor == 'gemini':
        return _llamar_gemini(prompt, api_key, max_tokens)
    if proveedor == 'openrouter':
        return _llamar_openrouter(prompt, api_key, max_tokens)
    return _llamar_anthropic(prompt, api_key, max_tokens)


# ── Probar conexión ────────────────────────────────────────────────────────

def probar_conexion(api_key: str = '', ia_proveedor: str = '') -> tuple[bool, str, str]:
    """
    Prueba rápida de conexión.
    Devuelve (ok, mensaje, proveedor_nombre).
    """
    if not ia_proveedor:
        ia_proveedor = get_config('ia_proveedor', '')
    if not api_key:
        api_key = get_config('api_key', '')

    _NOMBRES = {
        'groq':        'Groq',
        'anthropic':   'Anthropic Claude',
        'openai':      'OpenAI',
        'gemini':      'Google Gemini',
        'ollama':      'Ollama',
        'openrouter':  'OpenRouter',
    }

    if ia_proveedor == 'ollama':
        texto, error = _llamar_ollama('Responde solo: OK', max_tokens=10)
        modelo = get_config('ollama_modelo', 'llama3.2')
        nombre = f'Ollama ({modelo})'
        if error:
            return False, error, nombre
        return True, f'Ollama conectado · modelo: {modelo}', nombre

    if not api_key:
        return False, 'No hay clave API configurada.', ''

    nombre = _NOMBRES.get(ia_proveedor, ia_proveedor.capitalize())

    if ia_proveedor == 'groq':
        texto, error = _llamar_groq('Responde solo: OK', api_key, max_tokens=10)
    elif ia_proveedor == 'anthropic':
        texto, error = _llamar_anthropic('Responde solo: OK', api_key, max_tokens=10)
    elif ia_proveedor == 'openai':
        texto, error = _llamar_openai('Responde solo: OK', api_key, max_tokens=10)
    elif ia_proveedor == 'gemini':
        texto, error = _llamar_gemini('Responde solo: OK', api_key, max_tokens=10)
    elif ia_proveedor == 'openrouter':
        texto, error = _llamar_openrouter('Responde solo: OK', api_key, max_tokens=10)
    else:
        texto, error = _llamar_ia('Responde solo: OK', api_key, max_tokens=10)

    if error:
        return False, error, nombre
    return True, f'Conexión exitosa con {nombre}.', nombre


# ── Generación de especificación individual ────────────────────────────────

def generar_spec_partida(partida_id: int, prompt_extra: str = None):
    """Genera especificación técnica para una partida."""
    ia_proveedor = get_config('ia_proveedor', '')
    api_key      = get_config('api_key', '')
    if not api_key and ia_proveedor != 'ollama':
        return None, 'No hay clave API configurada. Ve a Configuración y añade tu clave.'

    conn = get_db()
    partida = conn.execute('SELECT * FROM partidas WHERE id=?', (partida_id,)).fetchone()
    proyecto = conn.execute(
        'SELECT * FROM proyectos WHERE id=?', (partida['proyecto_id'],)
    ).fetchone()
    acu_items = conn.execute(
        """SELECT ai.*, r.codigo, r.descripcion as rec_desc, r.tipo,
                  r.unidad as rec_unidad, COALESCE(ai.precio, r.precio, 0) as precio
           FROM acu_items ai JOIN recursos r ON r.id=ai.recurso_id
           WHERE ai.partida_id=?""",
        (partida_id,)
    ).fetchall()
    conn.close()

    mo_lines, mat_lines, eq_lines = [], [], []
    for it in acu_items:
        cant  = it['cantidad'] or 0
        precio = it['precio']  or 0
        line  = f"  - {it['rec_desc']} ({it['rec_unidad']}): cantidad={cant:.4f}, precio=S/{precio:.2f}"
        if it['tipo'] == 'MO':
            mo_lines.append(line)
        elif it['tipo'] == 'MAT':
            mat_lines.append(line)
        else:
            eq_lines.append(line)

    acu_texto = ''
    if mo_lines:
        acu_texto += 'MANO DE OBRA:\n' + '\n'.join(mo_lines) + '\n'
    if mat_lines:
        acu_texto += 'MATERIALES:\n' + '\n'.join(mat_lines) + '\n'
    if eq_lines:
        acu_texto += 'EQUIPO:\n' + '\n'.join(eq_lines) + '\n'

    # Contexto del proyecto: modalidad, plazo y notas (altitud, clima, suelo,
    # acceso…) → especificaciones ajustadas a las condiciones reales de la obra.
    _modalidad = proyecto['modalidad'] or 'Contrata'
    try:
        _plazo = int(proyecto['plazo'] or 0)
    except (TypeError, ValueError, IndexError):
        _plazo = 0
    try:
        _notas = (proyecto['notas'] or '').strip()
    except (IndexError, KeyError):
        _notas = ''
    _linea_mod = f"MODALIDAD: {_modalidad}" + (
        f"  |  PLAZO: {_plazo} días calendario" if _plazo else "")
    _bloque_notas = ''
    if _notas:
        _bloque_notas = (
            "\nCONTEXTO DE LA OBRA (descrito por el ingeniero — altitud, clima, "
            "acceso, suelo, sismo, servicios, etc.):\n"
            f'"""\n{_notas}\n"""\n'
        )
    try:
        _slat, _slon, _salt = proyecto['latitud'], proyecto['longitud'], proyecto['altitud']
    except (IndexError, KeyError):
        _slat = _slon = _salt = None
    _geo_spec = _geo_contexto(proyecto['ubicacion'], _slat, _slon, _salt)

    prompt = f"""Eres un ingeniero civil experto en elaboración de expedientes técnicos para obras públicas en Perú.

Genera las ESPECIFICACIONES TÉCNICAS completas para la siguiente partida de obra:

PROYECTO: {proyecto['nombre']}
CLIENTE: {proyecto['cliente']}
UBICACIÓN: {proyecto['ubicacion']}
{_linea_mod}
{_geo_spec}{_bloque_notas}
PARTIDA: {partida['item']} - {partida['descripcion']}
UNIDAD DE MEDIDA: {partida['unidad']}
METRADO: {partida['metrado']:.2f} {partida['unidad']}
PRECIO UNITARIO: S/ {partida['precio_unitario']:.2f}

ANÁLISIS DE COSTOS UNITARIOS (recursos utilizados):
{acu_texto if acu_texto else 'Sin análisis de costos cargado.'}

Redacta las especificaciones técnicas completas con las siguientes secciones:
1. DESCRIPCIÓN
2. MATERIALES (con normas técnicas NTP/ASTM aplicables)
3. PROCESO CONSTRUCTIVO
4. CONTROL DE CALIDAD
5. MEDICIÓN Y FORMA DE PAGO

Si el CONTEXTO DE LA OBRA indica condiciones especiales (gran altitud, clima frío/lluvioso, suelo agresivo o de baja capacidad, zona sísmica alta, difícil acceso, falta de servicios…), refléjalas concretamente en MATERIALES, PROCESO CONSTRUCTIVO y CONTROL DE CALIDAD (p. ej. curado y protección contra heladas en altura, aditivos, tiempos de transporte, etc.).
IMPORTANTE: NO incluyas ningún título ni encabezado al inicio del texto. Comienza directamente con "1. DESCRIPCIÓN".
El texto debe ser formal, técnico y ajustado a la normativa peruana (RNE, normas ASTM/NTP).
Máximo 600 palabras. No uses markdown, usa texto plano con las secciones en MAYÚSCULAS.
{f"INSTRUCCIONES ADICIONALES DEL USUARIO: {prompt_extra}" if prompt_extra and prompt_extra.strip() else ""}"""

    texto, error = _llamar_ia(prompt, api_key, max_tokens=1500)
    if error:
        return None, error

    conn = get_db()
    conn.execute('UPDATE partidas SET especificaciones=? WHERE id=?', (texto, partida_id))
    conn.commit()
    conn.close()
    return texto, None


# ── Generación de la memoria descriptiva (nivel proyecto) ──────────────────

def _geo_contexto(ubicacion: str, lat=None, lon=None, altitud=None) -> str:
    """Bloque de DATOS GEOGRÁFICOS: altitud EXACTA del punto (marcado en el
    mapa) o la del distrito (UBIGEO), + coordenadas EXACTAS (mapa) o
    referenciales del distrito, en UTM WGS84. '' si no hay nada."""
    try:
        from core.ubigeo import coords_de_ubicacion
        g = coords_de_ubicacion(ubicacion or '')
    except Exception:
        g = None
    from core.ubigeo import latlon_a_utm
    partes = []
    if altitud is not None:
        partes.append(f"Altitud del punto del proyecto: {int(round(altitud))} msnm")
    elif g and g.get('altitud'):
        partes.append(f"Altitud aproximada del distrito: {int(round(g['altitud']))} msnm")
    if lat is not None and lon is not None:
        u = latlon_a_utm(lat, lon)
        if u:
            partes.append(f"Coordenadas UTM WGS84 EXACTAS del proyecto (marcadas "
                          f"en el mapa): {u['etiqueta']}  "
                          f"[geográficas: {float(lat):.6f}, {float(lon):.6f}]")
    elif g and g.get('latitud') is not None and g.get('longitud') is not None:
        u = latlon_a_utm(g['latitud'], g['longitud'])
        if u:
            partes.append(f"Coordenadas UTM WGS84 referenciales (capital distrital "
                          f"{g.get('capital','')}): {u['etiqueta']}")
    if not partes:
        return ''
    return ("\nDATOS GEOGRÁFICOS (son reales, ÚSALOS y NO los marques como "
            "«por confirmar»):\n- " + "\n- ".join(partes) + "\n")


def _bloque_datos_complementarios(datos: dict | None) -> str:
    """Bloque con los datos que el ingeniero proporciona en el diálogo
    (tipo de intervención, CUI, beneficiarios, antecedentes…). '' si vacío."""
    if not datos:
        return ''
    etiquetas = [
        ('tipo',          'Tipo de intervención'),
        ('cui',           'CUI (Código Único de Inversión)'),
        ('beneficiarios', 'N° de beneficiarios'),
        ('decreto',       'Decreto/normativa aplicable'),
        ('antecedentes',  'Antecedentes / datos adicionales'),
    ]
    lineas = []
    for clave, lbl in etiquetas:
        v = (datos.get(clave) or '').strip()
        if v:
            lineas.append(f"- {lbl}: {v}")
    if not lineas:
        return ''
    return ("\nDATOS COMPLEMENTARIOS (proporcionados por el ingeniero — son "
            "reales, ÚSALOS y NO los marques como «por confirmar»):\n"
            + "\n".join(lineas) + "\n")


def generar_memoria_descriptiva(proyecto_id: int, prompt_extra: str = None,
                                datos: dict | None = None):
    """Genera la MEMORIA DESCRIPTIVA del proyecto con IA, usando el contexto
    disponible: ubicación (UBIGEO), presupuesto calculado, plazo, modalidad,
    notas (antecedentes/condiciones) y los componentes (títulos de nivel 1).
    Guarda el resultado en ``proyectos.memoria_descriptiva`` y lo retorna."""
    ia_proveedor = get_config('ia_proveedor', '')
    api_key      = get_config('api_key', '')
    if not api_key and ia_proveedor != 'ollama':
        return None, 'No hay clave API configurada. Ve a Configuración y añade tu clave.'

    from core.database import calcular_totales

    conn = get_db()
    proyecto = conn.execute('SELECT * FROM proyectos WHERE id=?', (proyecto_id,)).fetchone()
    if not proyecto:
        conn.close()
        return None, 'Proyecto no encontrado.'
    titulos = conn.execute(
        "SELECT item, descripcion FROM partidas "
        "WHERE proyecto_id=? AND es_titulo=1 AND item NOT LIKE '%.%' ORDER BY item",
        (proyecto_id,)
    ).fetchall()
    n_part = conn.execute(
        "SELECT COUNT(*) FROM partidas WHERE proyecto_id=? AND es_titulo=0",
        (proyecto_id,)
    ).fetchone()[0]
    conn.close()

    try:
        _items, tot = calcular_totales(proyecto_id)
    except Exception:
        tot = {'cd': 0, 'gf': 0, 'utilidad': 0, 'subtotal': 0, 'igv': 0, 'total': 0}

    partes = [x.strip() for x in (proyecto['ubicacion'] or '').split(',') if x.strip()]
    distrito     = partes[0] if len(partes) >= 1 else '(por definir)'
    provincia    = partes[1] if len(partes) >= 2 else '(por definir)'
    departamento = partes[2] if len(partes) >= 3 else '(por definir)'

    modalidad = proyecto['modalidad'] or 'Contrata'
    try:
        plazo = int(proyecto['plazo'] or 0)
    except (TypeError, ValueError, IndexError):
        plazo = 0
    try:
        notas = (proyecto['notas'] or '').strip()
    except (IndexError, KeyError):
        notas = ''
    # Si el diálogo ya trae los antecedentes (precargados de las notas y/o
    # editados), no repetir las notas como bloque aparte.
    if datos and (datos.get('antecedentes') or '').strip():
        notas = ''

    comp_txt = ('\n'.join(f"  - {t['item']} {t['descripcion']}" for t in titulos)
                or '  (estructura aún sin títulos de nivel 1)')
    # Resumen de costos = el del PIE de presupuesto (rubros activos: GG,
    # Supervisión, Expediente Técnico, Liquidación, IGV…) + monto en letras.
    moneda = proyecto['moneda'] or 'Soles'
    try:
        from core.pdf_reports import (_build_pie_rows, _monto_en_letras,
                                       _moneda_simbolo)
        filas = _build_pie_rows(proyecto_id, tot['cd'])
        sim = _moneda_simbolo(moneda)
        total_pie = next((m for (l, m, c) in filas if c == 'gran'), tot['total'])
        pres_txt = ('\n'.join(f"  {l}: {sim} {m:,.2f}" for (l, m, c) in filas)
                    + f"\n  SON: {_monto_en_letras(total_pie, moneda)}")
    except Exception:
        pres_txt = (
            f"  Costo directo:      S/ {tot['cd']:,.2f}\n"
            f"  Gastos generales:   S/ {tot['gf']:,.2f}\n"
            f"  Utilidad:           S/ {tot['utilidad']:,.2f}\n"
            f"  Subtotal:           S/ {tot['subtotal']:,.2f}\n"
            f"  IGV:                S/ {tot['igv']:,.2f}\n"
            f"  PRESUPUESTO TOTAL:  S/ {tot['total']:,.2f}"
        )
    bloque_notas = (f'\nANTECEDENTES Y CONDICIONES (descritos por el ingeniero):\n'
                    f'"""\n{notas}\n"""\n' if notas else '')
    try:
        _plat, _plon, _palt = proyecto['latitud'], proyecto['longitud'], proyecto['altitud']
    except (IndexError, KeyError):
        _plat = _plon = _palt = None
    geo_txt = _geo_contexto(proyecto['ubicacion'], _plat, _plon, _palt)
    datos_txt = _bloque_datos_complementarios(datos)

    prompt = f"""Eres un ingeniero civil especialista en formulación de expedientes técnicos para proyectos de inversión pública y actividades de mantenimiento/emergencia en el Perú, con amplio conocimiento de la normativa peruana (Invierte.pe — DL N° 1252, Ley de Contrataciones del Estado — Ley N° 30225, SINAGERD — Ley N° 29664, Reglamento Nacional de Edificaciones).

Redacta una MEMORIA DESCRIPTIVA profesional y completa para el siguiente proyecto, usando los datos reales que se entregan. La ALTITUD y las COORDENADAS se entregan en DATOS GEOGRÁFICOS: úsalas tal cual. Solo donde falte un dato que NO se entrega (CUI, N° de beneficiarios, etc.), déjalo entre paréntesis como «(por confirmar)» — NO inventes cifras oficiales.

DATOS DEL PROYECTO:
- Nombre: {proyecto['nombre']}
- Cliente / Entidad: {proyecto['cliente'] or '(por confirmar)'}
- Ubicación: Distrito {distrito}, Provincia {provincia}, Departamento {departamento}
- Modalidad de ejecución: {modalidad}
- Plazo de ejecución: {plazo if plazo else '(por confirmar)'} días calendario
- N° de partidas: {n_part}
- Componentes (títulos principales):
{comp_txt}

PRESUPUESTO (calculado por el sistema):
{pres_txt}
{geo_txt}{datos_txt}{bloque_notas}
Estructura OBLIGATORIA (desarrolla las 10 secciones, numeradas):
1. NOMBRE DEL PROYECTO (nombre en mayúsculas, CUI si aplica, tipo de intervención)
2. ANTECEDENTES (contexto del problema, infraestructura existente, justificación de la necesidad/urgencia, marco normativo si es emergencia)
3. JUSTIFICACIÓN (3.1 Social, 3.2 Técnica con normas NTP/ASTM, 3.3 Económica con relación beneficio/costo)
4. LOCALIZACIÓN DEL PROYECTO (departamento, provincia, distrito, localidad; altitud y zona; coordenadas UTM referenciales si se conocen)
5. VÍAS DE COMUNICACIÓN (rutas desde la capital regional, distancias, tiempos, estado de las vías)
6. OBJETIVOS GENERALES Y ESPECÍFICOS (6.1 objetivo general; 6.2 entre 8 y 12 objetivos específicos numerados y medibles)
7. METAS DEL PROYECTO (7.1 metas físicas con cantidades y unidades a partir de los componentes; 7.2 metas sociales)
8. PRESUPUESTO DEL PROYECTO (reproduce el RESUMEN DE COSTOS entregado tal cual —con todos sus rubros y el PRESUPUESTO TOTAL— y escribe el monto total EN LETRAS tal como aparece en la línea «SON: …»; agrega el costo por beneficiario si hay datos)
9. PLAZO DE EJECUCIÓN (plazo total en días calendario, fases, justificación del plazo)
10. MODALIDAD DE EJECUCIÓN PRESUPUESTARIA (modalidad, marco legal aplicable, justificación, financiamiento)

CONSIDERACIONES:
- Lenguaje técnico-profesional, formal, tercera persona impersonal.
- Cita normas técnicas peruanas (NTP, RNE) y ASTM cuando corresponda. Adapta el marco normativo al TIPO DE INTERVENCIÓN indicado: para «Proyecto de inversión» o «IOARR» menciona el DL N° 1252 (Invierte.pe), el CUI y la Ley N° 30225; para «Ficha de emergencia» menciona la Ley N° 29664 (SINAGERD) y el DS de emergencia (sin CUI); para «Mantenimiento» trátalo como ACTIVIDAD de mantenimiento (sin CUI, sin Invierte.pe).
- Si los ANTECEDENTES indican condiciones especiales (altitud, clima, suelo, acceso, sismo), refléjalas en la justificación técnica y el plazo.
- Datos específicos y cuantificados; evita generalidades.
- SALIDA EN TEXTO PLANO (sin markdown, sin #, sin asteriscos). Títulos de sección en MAYÚSCULAS y numerados. NO incluyas un título «MEMORIA DESCRIPTIVA» al inicio (el reporte ya lo agrega): comienza directamente con «1. NOMBRE DEL PROYECTO».
{f"INSTRUCCIONES ADICIONALES DEL USUARIO: {prompt_extra}" if prompt_extra and prompt_extra.strip() else ""}"""

    texto, error = _llamar_ia(prompt, api_key, max_tokens=4000)
    if error:
        return None, error

    conn = get_db()
    conn.execute('UPDATE proyectos SET memoria_descriptiva=? WHERE id=?',
                 (texto, proyecto_id))
    conn.commit()
    conn.close()
    return texto, None


def ampliar_seccion_memoria(proyecto_id: int, numero: int, nombre_seccion: str,
                            contenido_actual: str, prompt_extra: str = None):
    """Reescribe UNA sección de la memoria descriptiva más extensa y detallada.
    Devuelve (texto_seccion, error) — NO guarda; el llamador la reemplaza en el
    documento completo."""
    ia_proveedor = get_config('ia_proveedor', '')
    api_key      = get_config('api_key', '')
    if not api_key and ia_proveedor != 'ollama':
        return None, 'No hay clave API configurada. Ve a Configuración y añade tu clave.'

    conn = get_db()
    proyecto = conn.execute('SELECT * FROM proyectos WHERE id=?', (proyecto_id,)).fetchone()
    conn.close()
    if not proyecto:
        return None, 'Proyecto no encontrado.'
    try:
        notas = (proyecto['notas'] or '').strip()
    except (IndexError, KeyError):
        notas = ''
    bloque_notas = f"\nCondiciones de la obra (notas del ingeniero): {notas}\n" if notas else ""
    try:
        _plat, _plon, _palt = proyecto['latitud'], proyecto['longitud'], proyecto['altitud']
    except (IndexError, KeyError):
        _plat = _plon = _palt = None
    geo_txt = _geo_contexto(proyecto['ubicacion'], _plat, _plon, _palt)

    prompt = f"""Eres un ingeniero civil especialista en expedientes técnicos de obras públicas en el Perú (Invierte.pe, Ley N° 30225, SINAGERD, RNE, normas NTP/ASTM).

Amplía y mejora ÚNICAMENTE la sección «{numero}. {nombre_seccion}» de la memoria descriptiva del proyecto:
- Proyecto: {proyecto['nombre']}
- Ubicación: {proyecto['ubicacion'] or '(por confirmar)'}
- Modalidad: {proyecto['modalidad'] or 'Contrata'}{geo_txt}{bloque_notas}

CONTENIDO ACTUAL DE LA SECCIÓN:
\"\"\"
{contenido_actual}
\"\"\"

Reescribe esta sección MÁS EXTENSA, DETALLADA y profesional, manteniendo coherencia con un expediente técnico peruano y citando la normativa aplicable cuando corresponda. La ALTITUD y las COORDENADAS de DATOS GEOGRÁFICOS son reales: úsalas y NO las marques como «por confirmar». Conserva «(por confirmar)» solo en los datos que de verdad no se entregan (no inventes cifras oficiales).
SALIDA EN TEXTO PLANO (sin markdown, sin asteriscos). Empieza con el encabezado «{numero}. {nombre_seccion}» en MAYÚSCULAS y devuelve SOLO esa sección (no repitas las demás).
{f"INSTRUCCIONES ADICIONALES DEL USUARIO: {prompt_extra}" if prompt_extra and prompt_extra.strip() else ""}"""

    return _llamar_ia(prompt, api_key, max_tokens=2200)


# ── Generación de rendimiento ──────────────────────────────────────────────

def generar_rendimiento_partida(partida_id: int):
    """Sugiere el rendimiento diario para la partida usando IA."""
    ia_proveedor = get_config('ia_proveedor', '')
    api_key      = get_config('api_key', '')
    if not api_key and ia_proveedor != 'ollama':
        return None, None, 'No hay clave API configurada. Ve a Configuración y añade tu clave.'

    conn = get_db()
    partida = conn.execute('SELECT * FROM partidas WHERE id=?', (partida_id,)).fetchone()
    if not partida:
        conn.close()
        return None, None, 'Partida no encontrada.'
    proyecto  = conn.execute('SELECT * FROM proyectos WHERE id=?', (partida['proyecto_id'],)).fetchone()
    acu_items = conn.execute(
        """SELECT ai.cuadrilla, r.descripcion as rec_desc, r.unidad as rec_unidad
           FROM acu_items ai JOIN recursos r ON r.id=ai.recurso_id
           WHERE ai.partida_id=? AND r.tipo='MO'""",
        (partida_id,)
    ).fetchall()
    conn.close()

    jornada = proyecto['jornada_laboral'] or 8
    mo_texto = ''
    for it in acu_items:
        mo_texto += f"  - {it['rec_desc']} ({it['rec_unidad']}): cuadrilla = {it['cuadrilla'] or 0} trabajadores\n"
    if not mo_texto:
        mo_texto = '  (Sin mano de obra cargada aún)'

    prompt = f"""Eres un especialista en análisis de costos unitarios (ACU) para obras públicas en Perú, con dominio del método CAPECO.

CONCEPTO CLAVE DE ACU PERUANO:
- Rendimiento = cantidad de unidades que produce la CUADRILLA COMPLETA en una jornada de {jornada} horas.
- Cantidad de MO en el ACU = cuadrilla / rendimiento  →  jornadas de MO por cada unidad ejecutada.
- Ejemplo: pintar 25 m²/día con cuadrilla=1 → cantidad MO = 1/25 = 0.0400 jn/m²

DATOS DEL PROYECTO:
- Nombre: {proyecto['nombre']}
- Ubicación: {proyecto['ubicacion']}
- Modalidad: {proyecto['modalidad'] or 'Contrata'}

PARTIDA:
- {partida['item']} - {partida['descripcion']}
- Unidad: {partida['unidad']}
- Jornada laboral: {jornada} horas/día

CUADRILLA DE MANO DE OBRA:
{mo_texto}

TAREA: Determina el rendimiento realista para esta partida considerando:
1. Tabla de rendimientos CAPECO vigente para la descripción de la partida.
2. Zona geográfica de "{proyecto['ubicacion']}" (si es sierra >3000 msnm reducir ~15-20%, selva reducir ~10%).
3. El tamaño y composición de la cuadrilla indicada.
4. Condiciones típicas de obra pública en Perú.

Responde SOLO con este JSON exacto, sin texto adicional:
{{"rendimiento": 25.00, "justificacion": "2 líneas máx: valor típico CAPECO y ajuste por zona si aplica."}}"""

    texto, error = _llamar_ia(prompt, api_key, max_tokens=220)
    if error:
        return None, None, error

    import re, json
    match = re.search(r'\{[^}]+\}', texto, re.DOTALL)
    if not match:
        return None, None, 'La IA no devolvió un formato válido. Intenta de nuevo.'
    try:
        data = json.loads(match.group())
        rend = float(data.get('rendimiento', 0))
        just = str(data.get('justificacion', ''))
        if rend <= 0:
            return None, None, 'El rendimiento sugerido no es válido.'
        return rend, just, None
    except Exception:
        return None, None, 'Error al interpretar la respuesta de la IA.'


# ── Generación de cantidades MAT/EQ ───────────────────────────────────────

def generar_cantidades_materiales(partida_id: int):
    """Sugiere cantidades por unidad de medida para recursos MAT y EQ del ACU."""
    ia_proveedor = get_config('ia_proveedor', '')
    api_key      = get_config('api_key', '')
    if not api_key and ia_proveedor != 'ollama':
        return None, 'No hay clave API configurada. Ve a Configuración y añade tu clave.'

    conn = get_db()
    partida = conn.execute('SELECT * FROM partidas WHERE id=?', (partida_id,)).fetchone()
    if not partida:
        conn.close()
        return None, 'Partida no encontrada.'
    proyecto  = conn.execute('SELECT * FROM proyectos WHERE id=?', (partida['proyecto_id'],)).fetchone()
    acu_items = conn.execute(
        """SELECT ai.id as acu_item_id, ai.cantidad, r.id as recurso_id,
                  r.descripcion, r.tipo, r.unidad as rec_unidad,
                  COALESCE(ai.precio, r.precio, 0) as precio
           FROM acu_items ai JOIN recursos r ON r.id=ai.recurso_id
           WHERE ai.partida_id=? AND r.tipo IN ('MAT','EQ')
             AND SUBSTR(r.unidad,1,1) != '%'""",
        (partida_id,)
    ).fetchall()
    conn.close()

    if not acu_items:
        return None, 'No hay materiales ni equipos cargados en el ACU de esta partida.'

    rendimiento    = partida['rendimiento'] or 1
    recursos_texto = ''
    for it in acu_items:
        recursos_texto += (
            f"  ID:{it['acu_item_id']} | {it['tipo']} | {it['descripcion']} "
            f"| unidad: {it['rec_unidad']} | cant. actual: {it['cantidad'] or 0:.4f}\n"
        )

    import json as _json
    prompt = f"""Eres un especialista en análisis de costos unitarios (ACU) al estilo CAPECO para obras públicas en Perú.

CONCEPTO CRÍTICO:
- Las cantidades de MATERIALES y EQUIPOS en el ACU se expresan por cada 1 {partida['unidad']} ejecutado.
- Se debe incluir el factor de desperdicio/merma típico (p.ej. +5% pintura, +3% cemento, +10% madera).
- NO confundir con cantidades por jornada — son cantidades por UNIDAD DE MEDIDA de la partida.

PROYECTO: {proyecto['nombre']} | Ubicación: {proyecto['ubicacion']}

PARTIDA: {partida['item']} — {partida['descripcion']}
Unidad de medida: {partida['unidad']}
Rendimiento de la cuadrilla: {rendimiento} {partida['unidad']}/día (referencia para validar coherencia)

RECURSOS A CALCULAR (cantidad por 1 {partida['unidad']}):
{recursos_texto}

REFERENCIAS DE CONSUMO TÍPICO EN PERÚ (usa como guía):
- Pintura látex/esmalte en muros: 0.04–0.06 gln/m² (con imprimante 1ra mano + 2 manos acabado)
- Thinner para pintura esmalte: 10–15% del volumen de pintura
- Lija: 0.10–0.20 pliego/m² según superficie
- Cemento en tarrajeo: 0.117–0.182 bls/m²
- Arena gruesa en tarrajeo: 0.022–0.030 m³/m²
- Agua en mezclas: 0.010–0.025 m³/m³ concreto
- Concreto premezclado: volumen real + 5% desperdicio
- Acero corrugado: kg teórico + 5% desperdicio y empalmes
- Tubería PVC: ml teórico + 3% empalmes y cortes
- Equipos: horas-máquina = 1/rendimiento cuando trabajan toda la jornada

Calcula la cantidad real incluyendo merma para CADA recurso listado.

Responde SOLO con este JSON exacto, sin texto adicional:
[
  {{"acu_item_id": 123, "cantidad": 0.0500, "nota": "consumo real con merma incluida"}},
  {{"acu_item_id": 456, "cantidad": 0.1500, "nota": "consumo real con merma incluida"}}
]"""

    texto, error = _llamar_ia(prompt, api_key, max_tokens=600)
    if error:
        return None, error

    import re
    match = re.search(r'\[.*\]', texto, re.DOTALL)
    if not match:
        return None, 'La IA no devolvió un formato válido. Intenta de nuevo.'
    try:
        sugerencias = _json.loads(match.group())
        ids_validos = {it['acu_item_id'] for it in acu_items}
        resultado   = []
        for s in sugerencias:
            aid  = int(s.get('acu_item_id', 0))
            cant = float(s.get('cantidad', 0))
            nota = str(s.get('nota', ''))
            if aid in ids_validos and cant > 0:
                it = next(x for x in acu_items if x['acu_item_id'] == aid)
                resultado.append({
                    'acu_item_id': aid,
                    'cantidad':    round(cant, 4),
                    'descripcion': it['descripcion'],
                    'unidad':      it['rec_unidad'],
                    'nota':        nota,
                })
        if not resultado:
            return None, 'La IA no generó cantidades válidas. Intenta de nuevo.'
        return resultado, None
    except Exception:
        return None, 'Error al interpretar la respuesta de la IA.'


# ── Chat asistente ACU ────────────────────────────────────────────────────

def _memoria_contexto(proyecto_id: int | None) -> str:
    """Construye el bloque de MEMORIA GLOBAL del usuario para inyectar al
    prompt del LLM.

    Solo trae la memoria GLOBAL (cross-proyecto). Las notas del proyecto
    son privadas del usuario (administrativas, decisiones, contactos) y
    NO se envían al LLM para no contaminar el contexto técnico.

    Devuelve '' si no hay memoria global.
    """
    try:
        from core.memo_manager import get_memoria
        mem_glob = get_memoria(None).strip()
    except Exception:
        return ''
    if not mem_glob:
        return ''
    return (
        "\n──────────── MEMORIA DEL USUARIO ────────────\n"
        f"{mem_glob}\n"
        "\nINSTRUCCIONES sobre la memoria:\n"
        "- Son notas globales que el usuario escribió para que las tengas "
        "presentes (precios referenciales, fórmulas habituales, reglas, "
        "datos técnicos puntuales).\n"
        "- Úsalas cuando sean RELEVANTES a la pregunta — citarlas como "
        "fuente cuando aplique.\n"
        "- NO las menciones si la pregunta actual no se relaciona con ellas.\n"
        "- Si el usuario te pregunta «qué te dije sobre X» / «recuerdas X», "
        "revisa primero la memoria antes de responder."
    )


def chat_acu_asistente(partida_id: int, historial: list, mensaje: str,
                       modo: str = 'ACU') -> tuple[str, str]:
    """
    Chat con asistente IA especializado en presupuestos peruanos.

    `modo` adapta el rol del experto y los datos de contexto adjuntos:
      - 'ACU'             → rendimientos, cuadrillas, composición del ACU
      - 'Insumos'         → precios referenciales del mercado peruano + INEI
      - 'Metrados'        → verificación de planilla de metrados, fórmulas
      - 'Especificaciones'→ redacción técnica, RNE/NTP/ASTM
      - 'Resumen'         → análisis general de la partida en el proyecto

    historial: lista de dicts {'rol': 'usuario'|'asistente', 'texto': str}
    Devuelve (respuesta, error).
    """
    ia_proveedor = get_config('ia_proveedor', '')
    api_key      = get_config('api_key', '')
    if not api_key and ia_proveedor != 'ollama':
        return None, 'No hay clave API configurada. Ve a Configuración.'

    conn = get_db()
    partida = conn.execute('SELECT * FROM partidas WHERE id=?', (partida_id,)).fetchone()
    if not partida:
        conn.close()
        return None, 'Partida no encontrada.'
    proyecto  = conn.execute('SELECT * FROM proyectos WHERE id=?', (partida['proyecto_id'],)).fetchone()
    acu_items = conn.execute(
        """SELECT ai.cuadrilla, ai.cantidad, COALESCE(ai.precio, r.precio, 0) as precio,
                  r.descripcion, r.tipo, r.unidad as rec_unidad
           FROM acu_items ai JOIN recursos r ON r.id=ai.recurso_id
           WHERE ai.partida_id=?""",
        (partida_id,)
    ).fetchall()
    conn.close()

    jornada = proyecto['jornada_laboral'] or 8

    # Contexto de la partida
    lineas_acu = []
    for it in acu_items:
        lineas_acu.append(
            f"  {it['tipo']:3s} | {it['descripcion'][:40]:40s} | {it['rec_unidad']:6s}"
            f" | cuad={it['cuadrilla'] or 0:.2f} cant={it['cantidad'] or 0:.4f}"
            f" precio=S/{it['precio']:.2f}"
        )
    acu_txt = '\n'.join(lineas_acu) if lineas_acu else '  (sin insumos cargados aún)'

    # Resumen del proyecto completo — permite que el asistente responda
    # preguntas amplias ("¿cuánto cuesta el proyecto?", "¿qué partidas
    # tengo?", etc.) sin estar anclado solo a la partida seleccionada.
    try:
        conn_r = get_db()
        resumen_proy = _resumen_proyecto(conn_r, partida['proyecto_id'])
        conn_r.close()
    except Exception:
        resumen_proy = ""

    # Memoria del usuario (bloc de notas proyecto + global)
    memoria_txt = _memoria_contexto(partida['proyecto_id'])

    contexto = f"""CONTEXTO DEL PROYECTO Y PARTIDA:
Proyecto: {proyecto['nombre']}
Ubicación: {proyecto['ubicacion']}
Modalidad: {proyecto['modalidad'] or 'Contrata'}
Jornada laboral: {jornada} h/día

Partida abierta actualmente: {partida['item']} — {partida['descripcion']}
Unidad: {partida['unidad']}
Metrado: {(partida['metrado'] or 0):.2f} {partida['unidad']}
Rendimiento actual: {(partida['rendimiento'] or 0):.4f} {partida['unidad']}/jornada

ACU actual (insumos cargados de la partida abierta):
{acu_txt}

──────────── RESUMEN DEL PROYECTO COMPLETO ────────────
{resumen_proy}
{memoria_txt}"""

    # Historial de conversación formateado
    hist_txt = ''
    for msg in historial[-10:]:   # últimos 10 mensajes para no saturar el contexto
        rol = 'Usuario' if msg['rol'] == 'usuario' else 'Asistente'
        hist_txt += f"\n{rol}: {msg['texto']}\n"

    # Sistema y reglas por modo (rol del experto que cambia con la tab activa)
    _modos = {
        'ACU': (
            "Eres un experto en análisis de costos unitarios (ACU) para obras "
            "públicas en Perú, con dominio del método CAPECO, normas RNE, "
            "NTP/ASTM y tablas de rendimientos vigentes.",
            (
                f"REGLAS ACU PERUANO:\n"
                f"- Rendimiento = unidades que produce la cuadrilla completa en 1 jornada de {jornada}h\n"
                f"- Cantidad MO = cuadrilla / rendimiento (jornadas por unidad)\n"
                f"- Cantidades MAT/EQ = cantidad por 1 {partida['unidad']} ejecutado, incluyendo merma/desperdicio\n"
                f"- Ajusta rendimiento por zona: sierra >3000msnm → -15/20%, selva → -10%\n\n"
                "Responde técnica y conciso. Si sugieres rendimiento, indica valor exacto y fuente "
                "(CAPECO, experiencia de campo). Si sugieres insumos: tipo (MO/MAT/EQ), descripción, "
                f"unidad, cantidad por {partida['unidad']} y precio referencial S/."
            )
        ),
        'Insumos': (
            "Eres un experto en costos de construcción en Perú, con conocimiento "
            "actualizado del mercado nacional, índices INEI y catálogo CAPECO.",
            (
                "LINEAMIENTOS:\n"
                "- Da precios referenciales en S/ por unidad y zona (Lima/Sierra/Selva).\n"
                "- Para insumos del ACU actual evalúa si el precio cargado es razonable.\n"
                "- Si te preguntan por un insumo, sugiere proveedores típicos en Perú.\n"
                "- Indica si un insumo está sujeto a fórmula polinómica (índice INEI)."
            )
        ),
        'Metrados': (
            "Eres un experto en metrados de obras civiles en Perú, con dominio "
            "del reglamento de metrados RNE y prácticas CAPECO.",
            (
                f"PARTIDA: {partida['item']} — {partida['descripcion']} ({partida['unidad']})\n"
                f"Metrado actual: {(partida['metrado'] or 0):.4f} {partida['unidad']}\n\n"
                "LINEAMIENTOS:\n"
                "- Verifica si la planilla de metrados es coherente con la unidad de la partida.\n"
                "- Sugiere fórmulas geométricas para volúmenes/áreas/longitudes según el caso.\n"
                "- Identifica posibles inconsistencias (dobles conteos, omisiones).\n"
                "- Para acero, recuerda los kg/ml según diámetro (ASTM A615 / NTP 341.031)."
            )
        ),
        'Especificaciones': (
            "Eres un redactor técnico de especificaciones para expedientes "
            "técnicos peruanos. Dominas RNE, NTP/ASTM, normas MTC y MINEDU.",
            (
                "LINEAMIENTOS:\n"
                "- Especificaciones cortas y claras, organizadas en: Descripción, "
                "Materiales (con normas), Procedimiento, Control, Medición, Pago.\n"
                "- Cita normas específicas (NTP 350.001, ACI, ASTM A615, etc.).\n"
                "- Usa unidades coherentes con la partida."
            )
        ),
        'Resumen': (
            "Eres un consultor experto en gestión de proyectos de construcción "
            "en Perú, con visión integral de costos, plazos y riesgos.",
            (
                "LINEAMIENTOS:\n"
                "- Da una mirada general sobre la partida en el contexto del proyecto.\n"
                "- Señala riesgos típicos de esta partida (precios volátiles, mano de obra escasa, etc.).\n"
                "- Compara con prácticas usuales en proyectos similares."
            )
        ),
        'Cronograma': (
            "Eres un planificador senior de obras de construcción en Perú, "
            "experto en CPM, programación con MS Project / Primavera y "
            "secuencias constructivas peruanas (CAPECO).",
            (
                "DEPENDENCIAS SOPORTADAS EN ESTA APP (todo gráfico, sin tipear):\n"
                "- FS (fin-inicio, default): B inicia cuando A termina. Token '5' o '5+3' con lag en días.\n"
                "- SS (inicio-inicio): B inicia cuando A inicia. Token '5SS' o '5SS+2'.\n"
                "- FF (fin-fin): B termina cuando A termina. Token '5FF' o '5FF-1'.\n"
                "- SF (inicio-fin, raro): B termina cuando A inicia. Token '5SF'.\n"
                "- pct (lado pred): B arranca cuando A lleva X% completado. Token '5+50%'.\n"
                "  Útil para: empezar a vaciar concreto cuando encofrado lleva 75%.\n"
                "- tgt_pct (lado sucesor): cuando A termina, B ya está al X%. Token '5T50%'.\n"
                "  Útil para: cuando termine excavación, vaciado al 50%.\n"
                "\n"
                "INTERACCIONES GRÁFICAS DEL GANTT:\n"
                "- Arrastrar handle azul del fin/inicio de una barra a otra barra crea una dependencia.\n"
                "- Soltar en el inicio = FS, en el fin = FF, en el tercio central = tgt_pct 50%.\n"
                "- Arrastrar la flecha horizontalmente ajusta el lag en días (o el % si aplica).\n"
                "- Clic en flecha + Supr la elimina; Ctrl+clic acumula selección.\n"
                "- Clic en barra resalta predecesoras y sucesoras en azul.\n"
                "- Botón «⏳ Holgura» muestra cuánto puede atrasarse cada tarea no crítica.\n"
                "- Auto-programar tiene modo Local (fases constructivas) y modo IA.\n"
                "- El motor CPM respeta domingos y feriados peruanos (configurables).\n"
                "\n"
                "LINEAMIENTOS:\n"
                "- Sugiere dependencias respetando el orden constructivo: preliminares → "
                "movimiento de tierras → concreto simple → acero → encofrado → concreto "
                "armado → albañilería → revoques → pisos → carpintería → pintura → "
                "instalaciones → limpieza final.\n"
                "- Obras provisionales, fletes, SST, limpieza permanente NO son ruta crítica.\n"
                "- Identifica si la ruta crítica pasa por partidas con mayor incidencia económica.\n"
                "- Sugiere usar tgt_pct cuando frentes paralelos deben sincronizarse "
                "(p.ej. excavación termina justo cuando concreto va por la mitad).\n"
                "- Si la duración de una partida no encaja con su metrado/rendimiento, indícalo: "
                "duración ≈ ceil(metrado / (rendimiento × jornada))."
            )
        ),
    }
    rol, lineamientos = _modos.get(modo, _modos['ACU'])

    prompt = f"""{rol}

{lineamientos}

{contexto}
{"HISTORIAL:" + hist_txt if hist_txt else ""}
Usuario: {mensaje}

IMPORTANTE:
- Si el mensaje es CONVERSACIONAL (saludo, agradecimiento, charla casual,
  pregunta abierta tipo "¿qué puedo hacer?"), responde de forma natural y
  amigable. NO arrojes datos técnicos no solicitados. Una o dos líneas.
- Si la pregunta es ANALÍTICA sobre la PARTIDA ABIERTA — aunque sea vaga
  («¿está bien?», «¿falta algo?», «¿qué opinas?», «¿lo que estoy
  considerando…?», «revisa esta partida»), NO devuelvas una contra-
  pregunta vaga ni pidas más información: YA TIENES los datos del ACU,
  rendimiento, cuadrilla y metrado arriba. Haz un análisis concreto:
    1. Rendimiento actual vs típico CAPECO/RNE para esa partida (di si
       es razonable, alto o bajo, con valor de referencia).
    2. Cuadrilla coherente con el rendimiento y la unidad.
    3. Insumos cargados: ¿están los necesarios para producir 1 {partida['unidad']}?
       ¿Falta algún MO/MAT/EQ típico? ¿Hay cantidades sospechosas
       (desperdicios sub-estimados, mermas faltantes)?
    4. Precios cargados: ¿están dentro del rango de mercado peruano?
    5. Cierra con 1-3 recomendaciones accionables priorizadas.
  Formato: viñetas, máximo 200 palabras, cifras concretas.
- Si la pregunta es sobre el PROYECTO en general (totales, comparativas,
  top partidas, riesgos generales), usa el RESUMEN DEL PROYECTO COMPLETO.
- Si la pregunta menciona cifras del proyecto (CD, total, partidas), cita
  los valores numéricos del resumen, no inventes.
- Si la MODALIDAD del proyecto es «Administración Directa» o similar,
  NO recomiendes nada sobre fórmula polinómica de reajuste de precios:
  ese mecanismo solo aplica en obras por contrata (Contrata, Concurso
  Oferta, Llave en mano). En administración directa la entidad ejecuta
  con sus propios recursos y no hay contrato que reajustar.

Responde en el tono del mensaje: charla casual → charla casual; técnico
→ técnico. Sé conciso y orientado a presupuestos peruanos."""

    return _llamar_ia(prompt, api_key, max_tokens=1200)


# ── Generación masiva (todo el proyecto) ──────────────────────────────────

def generar_specs_proyecto(proyecto_id: int):
    """Genera especificaciones para todas las partidas hoja de un proyecto."""
    ia_proveedor = get_config('ia_proveedor', '')
    api_key      = get_config('api_key', '')
    if not api_key and ia_proveedor != 'ollama':
        return None, 'No hay clave API configurada.'

    conn = get_db()
    partidas = conn.execute(
        'SELECT * FROM partidas WHERE proyecto_id=? AND es_titulo=0 ORDER BY item',
        (proyecto_id,)
    ).fetchall()
    proyecto = conn.execute('SELECT * FROM proyectos WHERE id=?', (proyecto_id,)).fetchone()
    conn.close()

    if not partidas:
        return None, 'No hay partidas en el proyecto.'

    partidas_texto = ''
    for p in partidas:
        conn = get_db()
        acu_items = conn.execute(
            """SELECT r.descripcion, r.tipo FROM acu_items ai
               JOIN recursos r ON r.id=ai.recurso_id WHERE ai.partida_id=?""",
            (p['id'],)
        ).fetchall()
        conn.close()
        mat = [it['descripcion'] for it in acu_items if it['tipo'] == 'MAT']
        partidas_texto += (
            f"\n---\nITEM {p['item']}: {p['descripcion']}\n"
            f"Unidad: {p['unidad']} | Metrado: {p['metrado']:.2f}\n"
        )
        if mat:
            partidas_texto += 'Materiales principales: ' + ', '.join(mat[:5]) + '\n'

    prompt = f"""Eres ingeniero civil experto en expedientes técnicos de obras públicas en Perú.

Proyecto: {proyecto['nombre']}
Cliente: {proyecto['cliente']}
Ubicación: {proyecto['ubicacion']}

Genera especificaciones técnicas para CADA UNA de las siguientes partidas.
Para cada partida incluye: DESCRIPCIÓN, MATERIALES, PROCESO CONSTRUCTIVO, MEDICIÓN Y PAGO.
NO incluyas título ni encabezado dentro de la especificación. Comienza directamente con "1. DESCRIPCIÓN".
Usa formato:
===ITEM [código]===
[especificación]

Partidas:
{partidas_texto}

Normas: RNE, NTP, ASTM. Texto formal y técnico. Máximo 300 palabras por partida."""

    texto, error = _llamar_ia(prompt, api_key, max_tokens=8000)
    if error:
        return None, error

    import re
    sections  = re.split(r'===ITEM\s+([^=]+)===', texto)
    specs_map = {}
    for i in range(1, len(sections) - 1, 2):
        specs_map[sections[i].strip()] = sections[i + 1].strip()

    conn  = get_db()
    saved = 0
    for p in partidas:
        spec = specs_map.get(p['item'], '')
        if not spec:
            for k, v in specs_map.items():
                if p['item'] in k or k in p['item']:
                    spec = v
                    break
        if spec:
            conn.execute('UPDATE partidas SET especificaciones=? WHERE id=?', (spec, p['id']))
            saved += 1
    conn.commit()
    conn.close()
    return saved, None


# ── Asistente global del proyecto ─────────────────────────────────────────

def _resumen_proyecto(conn, proyecto_id: int) -> str:
    """Genera un texto compacto con todo el estado del proyecto para alimentar la IA."""
    p = conn.execute('SELECT * FROM proyectos WHERE id=?', (proyecto_id,)).fetchone()
    if not p:
        return ''

    # Totales calculados
    from core.database import calcular_totales
    _items, tot = calcular_totales(proyecto_id)

    # Top 10 partidas por costo (parcial = pu × metrado)
    partidas = conn.execute(
        """SELECT item, descripcion, unidad, metrado, precio_unitario,
                  (COALESCE(metrado,0) * COALESCE(precio_unitario,0)) AS parcial,
                  CASE WHEN especificaciones IS NULL OR especificaciones='' THEN 0 ELSE 1 END AS tiene_spec
           FROM partidas WHERE proyecto_id=? AND es_titulo=0
           ORDER BY parcial DESC LIMIT 50""",
        (proyecto_id,)
    ).fetchall()
    n_partidas_total = conn.execute(
        'SELECT COUNT(*) FROM partidas WHERE proyecto_id=? AND es_titulo=0', (proyecto_id,)
    ).fetchone()[0]
    n_sin_spec = sum(1 for x in partidas if not x['tiene_spec'])

    # Insumos consolidados
    insumos = conn.execute(
        """SELECT r.tipo, r.descripcion, r.unidad,
                  COALESCE(ai.precio, r.precio, 0) AS precio,
                  SUM(ai.cantidad * p.metrado) AS cant_total
           FROM acu_items ai
             JOIN partidas p ON p.id=ai.partida_id
             JOIN recursos r ON r.id=ai.recurso_id
           WHERE p.proyecto_id=? AND SUBSTR(r.unidad,1,1)!='%'
           GROUP BY r.id
           ORDER BY (SUM(ai.cantidad * p.metrado) * COALESCE(ai.precio, r.precio, 0)) DESC
           LIMIT 20""",
        (proyecto_id,)
    ).fetchall()

    n_mo  = sum(1 for x in insumos if x['tipo'] == 'MO')
    n_mat = sum(1 for x in insumos if x['tipo'] == 'MAT')
    n_eq  = sum(1 for x in insumos if x['tipo'] == 'EQ')

    lineas_part = []
    for it in partidas[:10]:
        lineas_part.append(
            f"  {it['item']:8s} | {(it['descripcion'] or '')[:50]:50s} | "
            f"{it['unidad']:6s} x {(it['metrado'] or 0):.2f} = "
            f"S/{(it['parcial'] or 0):,.2f}"
        )
    part_txt = '\n'.join(lineas_part) if lineas_part else '  (sin partidas)'

    lineas_ins = []
    for it in insumos[:15]:
        parcial = (it['cant_total'] or 0) * (it['precio'] or 0)
        lineas_ins.append(
            f"  {it['tipo']:3s} | {(it['descripcion'] or '')[:40]:40s} | "
            f"{(it['unidad'] or '')[:6]:6s} x {(it['cant_total'] or 0):,.2f} = "
            f"S/{parcial:,.2f}"
        )
    ins_txt = '\n'.join(lineas_ins) if lineas_ins else '  (sin insumos)'

    # Cronograma — estadística resumida útil al asistente IA
    cron_txt = ''
    try:
        plazo = int(p['plazo'] or 0)
        n_con_dur = conn.execute(
            """SELECT COUNT(*) FROM cronograma_partidas cp
               JOIN partidas p ON p.id=cp.partida_id
               WHERE p.proyecto_id=? AND COALESCE(cp.duracion,0) > 0""",
            (proyecto_id,)
        ).fetchone()[0]
        n_con_pred = conn.execute(
            """SELECT COUNT(*) FROM cronograma_partidas cp
               JOIN partidas p ON p.id=cp.partida_id
               WHERE p.proyecto_id=? AND TRIM(COALESCE(cp.predecesoras,'')) != ''""",
            (proyecto_id,)
        ).fetchone()[0]
        n_hitos = conn.execute(
            """SELECT COUNT(*) FROM cronograma_partidas cp
               JOIN partidas p ON p.id=cp.partida_id
               WHERE p.proyecto_id=? AND COALESCE(cp.es_hito,0) = 1""",
            (proyecto_id,)
        ).fetchone()[0]
        n_marcadores_fase = conn.execute(
            """SELECT COUNT(*) FROM cronograma_partidas cp
               JOIN partidas p ON p.id=cp.partida_id
               WHERE p.proyecto_id=? AND COALESCE(cp.es_hito,0) IN (2,3)""",
            (proyecto_id,)
        ).fetchone()[0]
        n_segs = conn.execute(
            """SELECT COUNT(*) FROM cronograma_partidas cp
               JOIN partidas p ON p.id=cp.partida_id
               WHERE p.proyecto_id=? AND TRIM(COALESCE(cp.segmentos,'')) != ''""",
            (proyecto_id,)
        ).fetchone()[0]
        if plazo or n_con_dur:
            cron_txt = (
                f"\nCRONOGRAMA:\n"
                f"  Plazo declarado: {plazo} días calendario\n"
                f"  Partidas con duración: {n_con_dur}\n"
                f"  Partidas con predecesoras (dependencias): {n_con_pred}\n"
                f"  Hitos puros (sin duración): {n_hitos}\n"
                f"  Marcadores de inicio/fin de fase: {n_marcadores_fase}\n"
                f"  Partidas divididas (segmentos): {n_segs}"
            )
    except Exception:
        pass

    # Notas del proyecto (opcional, ayudan a la IA con contexto adicional)
    try:
        _notas = (p['notas'] or '').strip()
    except (IndexError, KeyError):
        _notas = ''
    _bloque_notas = ''
    if _notas:
        _bloque_notas = f"\nNOTAS DEL PROYECTO (descripción dada por el ingeniero):\n\"\"\"\n{_notas}\n\"\"\"\n"

    return f"""PROYECTO: {p['nombre']}
Cliente: {p['cliente'] or '—'}
Ubicación: {p['ubicacion'] or '—'}
Modalidad: {p['modalidad'] or 'Contrata'}
Jornada laboral: {p['jornada_laboral'] or 8} h/día
Moneda: {p['moneda'] or 'Soles'}
{_bloque_notas}
PARTIDAS: {n_partidas_total} en total · {n_sin_spec} sin especificaciones técnicas
INSUMOS (consolidado): {n_mo} MO · {n_mat} MAT · {n_eq} EQ

TOTALES:
  Costo directo (CD):  S/ {tot['cd']:>14,.2f}
  Gastos generales:    S/ {tot['gf']:>14,.2f}
  Utilidad:            S/ {tot['utilidad']:>14,.2f}
  Subtotal:            S/ {tot['subtotal']:>14,.2f}
  IGV:                 S/ {tot['igv']:>14,.2f}
  TOTAL:               S/ {tot['total']:>14,.2f}

TOP 10 PARTIDAS POR COSTO:
{part_txt}

TOP 15 INSUMOS POR INCIDENCIA EN COSTO:
{ins_txt}
{cron_txt}"""


def chat_proyecto_asistente(proyecto_id: int, historial: list, mensaje: str) -> tuple[str, str]:
    """Chat IA con contexto del proyecto completo (no solo una partida).

    historial: lista de dicts {'rol': 'usuario'|'asistente', 'texto': str}
    Devuelve (respuesta, error).
    """
    ia_proveedor = get_config('ia_proveedor', '')
    api_key      = get_config('api_key', '')
    if not api_key and ia_proveedor != 'ollama':
        return None, 'No hay clave API configurada. Ve a IA / API Key.'

    conn = get_db()
    contexto = _resumen_proyecto(conn, proyecto_id)
    conn.close()
    if not contexto:
        return None, 'Proyecto no encontrado.'
    memoria_txt = _memoria_contexto(proyecto_id)

    hist_txt = ''
    for msg in historial[-12:]:
        rol = 'Usuario' if msg['rol'] == 'usuario' else 'Asistente'
        hist_txt += f"\n{rol}: {msg['texto']}\n"

    prompt = f"""Eres un asistente experto en presupuestos de obra pública peruana (CAPECO, RNE, OSCE), \
con dominio de análisis de costos unitarios, fórmula polinómica y reajuste de obras.

Responde de forma concisa y técnica. Usa cifras del proyecto cuando aplique. \
Si el usuario pide datos numéricos, cítalos en formato Soles peruanos con separadores.

{contexto}
{memoria_txt}
{"HISTORIAL:" + hist_txt if hist_txt else ""}
Usuario: {mensaje}

Responde directamente, sin saludos ni disclaimers. Si necesitas datos que no están en el contexto, \
indícalo claramente."""

    return _llamar_ia(prompt, api_key, max_tokens=1500)


# ── Validador / Revisor de proyecto ───────────────────────────────────────

def validar_proyecto(proyecto_id: int) -> tuple[str, str]:
    """Pide a la IA que revise el proyecto buscando inconsistencias.

    Devuelve (informe_markdown, error).
    El informe es texto markdown con secciones agrupadas por severidad.
    """
    ia_proveedor = get_config('ia_proveedor', '')
    api_key      = get_config('api_key', '')
    if not api_key and ia_proveedor != 'ollama':
        return None, 'No hay clave API configurada. Ve a IA / API Key.'

    conn = get_db()
    contexto = _resumen_proyecto(conn, proyecto_id)
    if not contexto:
        conn.close()
        return None, 'Proyecto no encontrado.'

    # Hallazgos previos calculables sin IA — ayudan a focalizar a la IA
    hallazgos_locales = []

    # Partidas sin metrado o con metrado 0
    sin_metrado = conn.execute(
        """SELECT item, descripcion FROM partidas
           WHERE proyecto_id=? AND es_titulo=0
             AND (metrado IS NULL OR metrado=0)
           LIMIT 20""",
        (proyecto_id,)
    ).fetchall()
    if sin_metrado:
        hallazgos_locales.append(
            f"- {len(sin_metrado)} partidas con metrado 0 o vacío "
            f"(ej. {', '.join(x['item'] for x in sin_metrado[:5])})"
        )

    # Partidas sin ACU
    sin_acu = conn.execute(
        """SELECT p.item, p.descripcion FROM partidas p
           WHERE p.proyecto_id=? AND p.es_titulo=0
             AND NOT EXISTS (SELECT 1 FROM acu_items ai WHERE ai.partida_id=p.id)
           LIMIT 20""",
        (proyecto_id,)
    ).fetchall()
    if sin_acu:
        hallazgos_locales.append(
            f"- {len(sin_acu)} partidas SIN análisis de costos unitarios "
            f"(ej. {', '.join(x['item'] for x in sin_acu[:5])})"
        )

    # Partidas sin especificaciones
    sin_spec = conn.execute(
        """SELECT COUNT(*) FROM partidas
           WHERE proyecto_id=? AND es_titulo=0
             AND (especificaciones IS NULL OR especificaciones='')""",
        (proyecto_id,)
    ).fetchone()[0]
    if sin_spec:
        hallazgos_locales.append(
            f"- {sin_spec} partidas sin especificaciones técnicas"
        )

    # Fórmula polinómica — solo aplica para obras por contrata.
    # En administración directa no hay contrato a reajustar, así que se omite.
    proy_mod = conn.execute(
        'SELECT modalidad FROM proyectos WHERE id=?', (proyecto_id,)
    ).fetchone()
    modalidad_l = (proy_mod['modalidad'] if proy_mod else '') or ''
    modalidad_l = modalidad_l.strip().lower()
    es_admin_directa = 'administraci' in modalidad_l and 'directa' in modalidad_l

    if not es_admin_directa:
        monomios = conn.execute(
            'SELECT coeficiente FROM formula_monomios WHERE proyecto_id=?',
            (proyecto_id,)
        ).fetchall()
        if monomios:
            suma_k = sum((m['coeficiente'] or 0) for m in monomios)
            if abs(suma_k - 1.0) > 0.005:
                hallazgos_locales.append(
                    f"- Fórmula polinómica: Σk = {suma_k:.4f} (debe ser 1.0000 ± 0.005)"
                )
        else:
            hallazgos_locales.append(
                "- No hay fórmula polinómica configurada"
            )

    # ── Reglas mecánicas adicionales ─────────────────────────────────────
    # Partidas con descripción vacía
    sin_desc = conn.execute(
        """SELECT COUNT(*) FROM partidas
           WHERE proyecto_id=? AND es_titulo=0
             AND (descripcion IS NULL OR TRIM(descripcion)='')""",
        (proyecto_id,)
    ).fetchone()[0]
    if sin_desc:
        hallazgos_locales.append(
            f"- {sin_desc} partidas sin descripción"
        )

    # Partidas con precio unitario 0 (riesgo de costo total cero)
    pu_cero = conn.execute(
        """SELECT item FROM partidas
           WHERE proyecto_id=? AND es_titulo=0
             AND (precio_unitario IS NULL OR precio_unitario=0)
             AND (metrado IS NOT NULL AND metrado>0)
           LIMIT 20""",
        (proyecto_id,)
    ).fetchall()
    if pu_cero:
        hallazgos_locales.append(
            f"- {len(pu_cero)} partidas con metrado > 0 pero precio unitario 0 "
            f"(ej. {', '.join(x['item'] for x in pu_cero[:5])})"
        )

    # Recursos con precio 0 que están en uso
    rec_sin_precio = conn.execute(
        """SELECT DISTINCT r.codigo FROM recursos r
           JOIN acu_items ai ON ai.recurso_id = r.id
           JOIN partidas p ON p.id = ai.partida_id
           WHERE p.proyecto_id=?
             AND COALESCE(ai.precio, r.precio, 0) = 0
             AND SUBSTR(r.unidad, 1, 1) != '%'
           LIMIT 20""",
        (proyecto_id,)
    ).fetchall()
    if rec_sin_precio:
        hallazgos_locales.append(
            f"- {len(rec_sin_precio)} recursos con precio 0 en uso "
            f"(ej. {', '.join(x['codigo'] for x in rec_sin_precio[:5])})"
        )

    # Cuadratura del pie: total ≈ CD + suma(rubros)
    try:
        from core.database import calcular_totales
        _items, totales = calcular_totales(proyecto_id)
        # Sumar todos los rubros activos
        rubros = conn.execute(
            "SELECT * FROM pie_rubros WHERE proyecto_id=? AND activo=1 ORDER BY orden",
            (proyecto_id,)
        ).fetchall()
        cd = float(totales.get('cd', 0) or 0)
        if cd > 0:
            from core.pdf_reports import _build_pie_rows
            pie_rows = _build_pie_rows(proyecto_id, cd)
            if pie_rows:
                total_pie = pie_rows[-1][1]   # último = PRESUPUESTO TOTAL
                total_db = float(totales.get('total', 0) or 0)
                # tolerancia: 0.5% o 100 soles, lo mayor
                tol = max(100.0, abs(total_db) * 0.005)
                if abs(total_pie - total_db) > tol:
                    hallazgos_locales.append(
                        f"- Cuadratura del pie: total calculado por rubros "
                        f"({total_pie:,.2f}) difiere del total del proyecto "
                        f"({total_db:,.2f})"
                    )
    except Exception:
        pass

    # Cronograma: tareas sin duración o duración > plazo
    cron_sin_dur = conn.execute(
        """SELECT p.item FROM partidas p
           JOIN cronograma_partidas cp ON cp.partida_id = p.id
           WHERE p.proyecto_id=? AND p.es_titulo=0
             AND (cp.duracion IS NULL OR cp.duracion=0)
             AND (cp.es_hito IS NULL OR cp.es_hito=0)
           LIMIT 20""",
        (proyecto_id,)
    ).fetchall()
    if cron_sin_dur:
        hallazgos_locales.append(
            f"- {len(cron_sin_dur)} partidas en cronograma con duración 0 "
            f"(no se programarán)"
        )

    plazo = conn.execute(
        'SELECT plazo FROM proyectos WHERE id=?', (proyecto_id,)
    ).fetchone()
    if plazo and plazo['plazo']:
        plazo_v = int(plazo['plazo'] or 0)
        max_ef = conn.execute(
            """SELECT MAX(COALESCE(cp.inicio_dia,1) + COALESCE(cp.duracion,0) - 1)
               FROM cronograma_partidas cp
               JOIN partidas p ON p.id = cp.partida_id
               WHERE p.proyecto_id=?""",
            (proyecto_id,)
        ).fetchone()[0] or 0
        if max_ef > plazo_v + 1:
            hallazgos_locales.append(
                f"- Cronograma desborda el plazo: máx día programado={max_ef}, "
                f"plazo declarado={plazo_v}"
            )

    conn.close()

    hallazgos_txt = (
        '\n'.join(hallazgos_locales) if hallazgos_locales
        else '(no hay hallazgos automáticos previos)'
    )

    prompt = f"""Eres un revisor experto de presupuestos de obra pública peruana (CAPECO, OSCE, RNE). \
Tu tarea es revisar un proyecto y emitir un informe priorizado de hallazgos.

{contexto}

HALLAZGOS AUTOMÁTICOS PREVIOS (ya detectados):
{hallazgos_txt}

INSTRUCCIONES:
Revisa el proyecto y emite un informe con la siguiente estructura **markdown**:

## 🔴 Críticos
(problemas que impiden licitar o causarían rechazo)

## 🟡 Advertencias
(inconsistencias técnicas, valores fuera de rango, faltantes importantes)

## 🟢 Sugerencias
(mejoras opcionales, optimizaciones, completitud)

Para cada hallazgo:
- Sé específico — cita la partida, insumo o sección concreta (usa el ítem como referencia)
- Da una recomendación accionable
- Si es numérico (precio, rendimiento, metrado), indica el valor problemático y el rango sugerido

Concéntrate en lo IMPORTANTE: no listes 50 ítems triviales. Máximo 3-5 hallazgos por sección. \
Si una sección no tiene hallazgos, escribe "Sin hallazgos.".

REGLAS POR MODALIDAD:
- Si la MODALIDAD del proyecto es «Administración Directa» (la entidad
  ejecuta con sus propios recursos), NO marques como hallazgo nada
  relacionado con fórmula polinómica de reajuste: ese mecanismo solo
  aplica a obras por contrata."""

    return _llamar_ia(prompt, api_key, max_tokens=2000)



# ══════════════════════════════════════════════════════════════════════════════
# Sugerir partidas para proyecto vacío — modo IA + plantillas locales
# ══════════════════════════════════════════════════════════════════════════════

# Plantillas mínimas por tipo de obra peruana (estructura base que el usuario
# luego completa con metrados, ACUs, etc.). Lista corta — la IA da más detalle.
_PLANTILLAS_PARTIDAS = {
    'vivienda_unifamiliar': {
        'titulo': 'Vivienda Unifamiliar',
        'partidas': [
            ('01',          'OBRAS PROVISIONALES',                              '',     None),
            ('01.01',       'CARTEL DE IDENTIFICACION DE LA OBRA',              'und',  1),
            ('01.02',       'AGUA PARA LA CONSTRUCCION',                        'glb',  1),
            ('02',          'TRABAJOS PRELIMINARES',                            '',     None),
            ('02.01',       'LIMPIEZA MANUAL DEL TERRENO',                      'm2',   None),
            ('02.02',       'TRAZO Y REPLANTEO PRELIMINAR',                     'm2',   None),
            ('03',          'MOVIMIENTO DE TIERRAS',                            '',     None),
            ('03.01',       'EXCAVACION MANUAL EN TERRENO NORMAL',              'm3',   None),
            ('03.02',       'RELLENO COMPACTADO CON MATERIAL PROPIO',           'm3',   None),
            ('03.03',       'ELIMINACION DE MATERIAL EXCEDENTE',                'm3',   None),
            ('04',          'CONCRETO SIMPLE',                                  '',     None),
            ('04.01',       'CIMIENTOS CORRIDOS C:H 1:10 + 30% PG',             'm3',   None),
            ('04.02',       'SOBRECIMIENTOS C:H 1:8 + 25% PM',                  'm3',   None),
            ('04.03',       'FALSO PISO E=4" CONCRETO 1:8',                     'm2',   None),
            ('05',          'CONCRETO ARMADO',                                  '',     None),
            ('05.01',       'ZAPATAS — ACERO CORRUGADO Fy=4200 KG/CM2',         'kg',   None),
            ('05.02',       'ZAPATAS — CONCRETO F\'C=210 KG/CM2',               'm3',   None),
            ('05.03',       'COLUMNAS — ACERO CORRUGADO Fy=4200 KG/CM2',        'kg',   None),
            ('05.04',       'COLUMNAS — ENCOFRADO Y DESENCOFRADO',              'm2',   None),
            ('05.05',       'COLUMNAS — CONCRETO F\'C=210 KG/CM2',              'm3',   None),
            ('05.06',       'VIGAS — ACERO CORRUGADO Fy=4200 KG/CM2',           'kg',   None),
            ('05.07',       'VIGAS — ENCOFRADO Y DESENCOFRADO',                 'm2',   None),
            ('05.08',       'VIGAS — CONCRETO F\'C=210 KG/CM2',                 'm3',   None),
            ('05.09',       'LOSAS ALIGERADAS — ACERO CORRUGADO Fy=4200',       'kg',   None),
            ('05.10',       'LOSAS ALIGERADAS — ENCOFRADO Y DESENCOFRADO',      'm2',   None),
            ('05.11',       'LOSAS ALIGERADAS — CONCRETO F\'C=210 KG/CM2',      'm3',   None),
            ('06',          'ALBAÑILERIA',                                      '',     None),
            ('06.01',       'MURO DE LADRILLO KING KONG DE ARCILLA',            'm2',   None),
            ('07',          'REVOQUES Y ENLUCIDOS',                             '',     None),
            ('07.01',       'TARRAJEO PRIMARIO RAYADO C:A 1:5',                 'm2',   None),
            ('07.02',       'TARRAJEO EN INTERIORES C:A 1:5',                   'm2',   None),
            ('07.03',       'TARRAJEO EN EXTERIORES C:A 1:5',                   'm2',   None),
            ('08',          'PISOS Y PAVIMENTOS',                               '',     None),
            ('08.01',       'CONTRAPISO DE 48 MM',                              'm2',   None),
            ('08.02',       'PISO DE CERAMICO ANTIDESLIZANTE',                  'm2',   None),
            ('09',          'CARPINTERIA DE MADERA',                            '',     None),
            ('09.01',       'PUERTA DE MADERA TABLERO REBAJADO',                'm2',   None),
            ('10',          'CARPINTERIA METALICA',                             '',     None),
            ('10.01',       'VENTANA DE FIERRO CON PERFIL CUADRADO',            'm2',   None),
            ('11',          'INSTALACIONES SANITARIAS',                         '',     None),
            ('11.01',       'SALIDA DE AGUA FRIA TUBERIA PVC C-10 1/2"',        'pto',  None),
            ('11.02',       'SALIDA DE DESAGUE PVC SAL 4"',                     'pto',  None),
            ('11.03',       'INODORO TANQUE BAJO BLANCO',                       'und',  None),
            ('11.04',       'LAVATORIO DE PARED BLANCO',                        'und',  None),
            ('12',          'INSTALACIONES ELECTRICAS',                         '',     None),
            ('12.01',       'SALIDA PARA TOMACORRIENTE BIPOLAR',                'pto',  None),
            ('12.02',       'SALIDA PARA CENTRO DE LUZ',                        'pto',  None),
            ('12.03',       'TABLERO GENERAL TG-1',                             'und',  1),
            ('13',          'PINTURA',                                          '',     None),
            ('13.01',       'PINTURA LATEX EN MUROS INTERIORES (2 MANOS)',      'm2',   None),
            ('13.02',       'PINTURA LATEX EN MUROS EXTERIORES (2 MANOS)',      'm2',   None),
            ('14',          'LIMPIEZA FINAL',                                   '',     None),
            ('14.01',       'LIMPIEZA FINAL DE OBRA',                           'm2',   None),
        ],
    },
    'agua_saneamiento': {
        'titulo': 'Agua y Saneamiento',
        'partidas': [
            ('01',          'OBRAS PROVISIONALES',                              '',     None),
            ('01.01',       'CARTEL DE OBRA DE 3.60X2.40M',                     'und',  1),
            ('01.02',       'CASETA DE GUARDIANIA Y ALMACEN',                   'm2',   None),
            ('02',          'TRABAJOS PRELIMINARES',                            '',     None),
            ('02.01',       'TRAZO Y REPLANTEO DE TUBERIAS',                    'm',    None),
            ('02.02',       'LIMPIEZA Y DESBROCE DEL TERRENO',                  'm2',   None),
            ('03',          'MOVIMIENTO DE TIERRAS',                            '',     None),
            ('03.01',       'EXCAVACION DE ZANJAS PARA TUBERIA',                'm3',   None),
            ('03.02',       'REFINE Y NIVELACION DE FONDO DE ZANJA',            'm2',   None),
            ('03.03',       'CAMA DE ARENA E=10 CM',                            'm2',   None),
            ('03.04',       'RELLENO Y COMPACTACION DE ZANJA',                  'm3',   None),
            ('03.05',       'ELIMINACION DE MATERIAL EXCEDENTE',                'm3',   None),
            ('04',          'TUBERIAS Y ACCESORIOS',                            '',     None),
            ('04.01',       'TUBERIA PVC SAP C-10 DN 110MM',                    'm',    None),
            ('04.02',       'TUBERIA PVC SAP C-10 DN 75MM',                     'm',    None),
            ('04.03',       'TUBERIA PVC SAP C-10 DN 63MM',                     'm',    None),
            ('04.04',       'ACCESORIOS PVC SAP (CODOS, TEES, REDUCCIONES)',    'glb',  1),
            ('05',          'CAPTACION',                                        '',     None),
            ('05.01',       'CONCRETO ARMADO F\'C=210 EN CAPTACION',            'm3',   None),
            ('05.02',       'ENCOFRADO Y DESENCOFRADO EN CAPTACION',            'm2',   None),
            ('05.03',       'ACERO DE REFUERZO Fy=4200 EN CAPTACION',           'kg',   None),
            ('06',          'RESERVORIO',                                       '',     None),
            ('06.01',       'CONCRETO F\'C=210 EN MUROS DE RESERVORIO',         'm3',   None),
            ('06.02',       'ENCOFRADO Y DESENCOFRADO MUROS RESERVORIO',        'm2',   None),
            ('06.03',       'ACERO Fy=4200 EN MUROS DE RESERVORIO',             'kg',   None),
            ('07',          'CONEXIONES DOMICILIARIAS',                         '',     None),
            ('07.01',       'CONEXION DOMICILIARIA DE AGUA POTABLE',            'und',  None),
            ('08',          'PRUEBAS Y DESINFECCION',                           '',     None),
            ('08.01',       'PRUEBA HIDRAULICA Y DESINFECCION DE TUBERIA',      'm',    None),
            ('09',          'LIMPIEZA FINAL',                                   '',     None),
            ('09.01',       'LIMPIEZA FINAL DE OBRA',                           'glb',  1),
        ],
    },
    'pavimentacion': {
        'titulo': 'Pavimentación / Vías',
        'partidas': [
            ('01',          'OBRAS PROVISIONALES',                              '',     None),
            ('01.01',       'CARTEL DE OBRA DE 3.60X2.40M',                     'und',  1),
            ('01.02',       'MOVILIZACION Y DESMOVILIZACION DE EQUIPOS',        'glb',  1),
            ('02',          'TRABAJOS PRELIMINARES',                            '',     None),
            ('02.01',       'TRAZO Y REPLANTEO DE LA VIA',                      'km',   None),
            ('02.02',       'DEMOLICION DE PAVIMENTO EXISTENTE',                'm3',   None),
            ('03',          'MOVIMIENTO DE TIERRAS',                            '',     None),
            ('03.01',       'CORTE DE TERRENO A NIVEL DE SUBRASANTE',           'm3',   None),
            ('03.02',       'PERFILADO Y COMPACTACION DE SUBRASANTE',           'm2',   None),
            ('03.03',       'ELIMINACION DE MATERIAL EXCEDENTE',                'm3',   None),
            ('04',          'PAVIMENTO',                                        '',     None),
            ('04.01',       'BASE GRANULAR E=20 CM',                            'm3',   None),
            ('04.02',       'IMPRIMACION ASFALTICA',                            'm2',   None),
            ('04.03',       'CARPETA ASFALTICA EN CALIENTE E=2"',               'm2',   None),
            ('05',          'VEREDAS Y SARDINELES',                             '',     None),
            ('05.01',       'CONCRETO F\'C=175 EN VEREDAS E=10 CM',             'm2',   None),
            ('05.02',       'SARDINEL DE CONCRETO F\'C=175',                    'm',    None),
            ('06',          'SEÑALIZACION',                                     '',     None),
            ('06.01',       'PINTURA DE TRAFICO EN PAVIMENTO',                  'm2',   None),
            ('06.02',       'SEÑAL VERTICAL REGLAMENTARIA',                     'und',  None),
            ('07',          'LIMPIEZA FINAL',                                   '',     None),
            ('07.01',       'LIMPIEZA FINAL DE OBRA',                           'glb',  1),
        ],
    },
    'institucion_educativa': {
        'titulo': 'Institución Educativa (Colegio)',
        'partidas': [
            ('01',          'OBRAS PROVISIONALES',                              '',     None),
            ('01.01',       'CARTEL DE OBRA DE 3.60X2.40M',                     'und',  1),
            ('01.02',       'CASETA DE GUARDIANIA Y ALMACEN',                   'm2',   None),
            ('02',          'TRABAJOS PRELIMINARES',                            '',     None),
            ('02.01',       'LIMPIEZA DE TERRENO MANUAL',                       'm2',   None),
            ('02.02',       'TRAZO, NIVELES Y REPLANTEO',                       'm2',   None),
            ('03',          'MOVIMIENTO DE TIERRAS',                            '',     None),
            ('03.01',       'EXCAVACION PARA ZAPATAS Y CIMIENTOS',              'm3',   None),
            ('03.02',       'RELLENO COMPACTADO CON MATERIAL PROPIO',           'm3',   None),
            ('03.03',       'ELIMINACION DE MATERIAL EXCEDENTE',                'm3',   None),
            ('04',          'OBRAS DE CONCRETO SIMPLE',                         '',     None),
            ('04.01',       'SOLADO PARA ZAPATAS E=10 CM',                      'm2',   None),
            ('04.02',       'CIMIENTOS CORRIDOS C:H 1:10 + 30% PG',             'm3',   None),
            ('04.03',       'FALSO PISO E=4"',                                  'm2',   None),
            ('05',          'OBRAS DE CONCRETO ARMADO',                         '',     None),
            ('05.01',       'ZAPATAS — ACERO Fy=4200 KG/CM2',                   'kg',   None),
            ('05.02',       'ZAPATAS — CONCRETO F\'C=210 KG/CM2',               'm3',   None),
            ('05.03',       'COLUMNAS — ACERO Fy=4200 KG/CM2',                  'kg',   None),
            ('05.04',       'COLUMNAS — ENCOFRADO Y DESENCOFRADO',              'm2',   None),
            ('05.05',       'COLUMNAS — CONCRETO F\'C=210 KG/CM2',              'm3',   None),
            ('05.06',       'VIGAS — ACERO Fy=4200 KG/CM2',                     'kg',   None),
            ('05.07',       'VIGAS — ENCOFRADO Y DESENCOFRADO',                 'm2',   None),
            ('05.08',       'VIGAS — CONCRETO F\'C=210 KG/CM2',                 'm3',   None),
            ('05.09',       'LOSA ALIGERADA — ACERO Fy=4200 KG/CM2',            'kg',   None),
            ('05.10',       'LOSA ALIGERADA — ENCOFRADO Y DESENCOFRADO',        'm2',   None),
            ('05.11',       'LOSA ALIGERADA — CONCRETO F\'C=210 KG/CM2',        'm3',   None),
            ('06',          'ESTRUCTURA METALICA Y COBERTURA',                  '',     None),
            ('06.01',       'TIJERAL METALICO',                                 'kg',   None),
            ('06.02',       'COBERTURA CON PANEL / CALAMINA',                   'm2',   None),
            ('07',          'ALBAÑILERIA',                                      '',     None),
            ('07.01',       'MURO DE LADRILLO KING KONG DE ARCILLA',            'm2',   None),
            ('08',          'REVOQUES Y ENLUCIDOS',                             '',     None),
            ('08.01',       'TARRAJEO EN INTERIORES C:A 1:5',                   'm2',   None),
            ('08.02',       'TARRAJEO EN EXTERIORES C:A 1:5',                   'm2',   None),
            ('08.03',       'CIELO RASO CON MEZCLA',                            'm2',   None),
            ('09',          'PISOS Y ZOCALOS',                                  '',     None),
            ('09.01',       'CONTRAPISO DE 48 MM',                              'm2',   None),
            ('09.02',       'PISO DE CERAMICO ANTIDESLIZANTE',                  'm2',   None),
            ('09.03',       'ZOCALO DE CERAMICO',                               'm',    None),
            ('10',          'CARPINTERIA',                                      '',     None),
            ('10.01',       'PUERTA CONTRAPLACADA',                             'm2',   None),
            ('10.02',       'VENTANA METALICA CON REJILLA',                     'm2',   None),
            ('11',          'INSTALACIONES SANITARIAS',                         '',     None),
            ('11.01',       'SALIDA DE AGUA Y DESAGUE',                         'pto',  None),
            ('11.02',       'APARATOS Y ACCESORIOS SANITARIOS',                 'und',  None),
            ('12',          'INSTALACIONES ELECTRICAS',                         '',     None),
            ('12.01',       'SALIDA PARA CENTRO DE LUZ',                        'pto',  None),
            ('12.02',       'SALIDA PARA TOMACORRIENTE',                        'pto',  None),
            ('12.03',       'TABLERO GENERAL',                                  'und',  1),
            ('13',          'PINTURA',                                          '',     None),
            ('13.01',       'PINTURA LATEX EN MUROS (2 MANOS)',                 'm2',   None),
            ('14',          'LIMPIEZA FINAL',                                   '',     None),
            ('14.01',       'LIMPIEZA FINAL DE OBRA',                           'm2',   None),
        ],
    },
    'carretera_trocha': {
        'titulo': 'Carretera / Trocha Carrozable',
        'partidas': [
            ('01',          'OBRAS PROVISIONALES',                              '',     None),
            ('01.01',       'CARTEL DE OBRA DE 3.60X2.40M',                     'und',  1),
            ('01.02',       'MOVILIZACION Y DESMOVILIZACION DE MAQUINARIA',     'glb',  1),
            ('01.03',       'CAMPAMENTO Y PATIO DE MAQUINAS',                   'm2',   None),
            ('02',          'TRABAJOS PRELIMINARES',                            '',     None),
            ('02.01',       'TRAZO Y REPLANTEO DE LA VIA',                      'km',   None),
            ('02.02',       'ROCE Y LIMPIEZA DE TERRENO',                       'm2',   None),
            ('03',          'MOVIMIENTO DE TIERRAS',                            '',     None),
            ('03.01',       'CORTE DE MATERIAL SUELTO CON MAQUINARIA',          'm3',   None),
            ('03.02',       'CONFORMACION DE TERRAPLEN CON MATERIAL PROPIO',    'm3',   None),
            ('03.03',       'PERFILADO Y COMPACTADO DE SUBRASANTE',             'm2',   None),
            ('03.04',       'ELIMINACION DE MATERIAL EXCEDENTE',                'm3',   None),
            ('04',          'PAVIMENTO / AFIRMADO',                             '',     None),
            ('04.01',       'EXTRACCION Y ZARANDEO DE AFIRMADO',                'm3',   None),
            ('04.02',       'EXTENDIDO Y COMPACTADO DE AFIRMADO E=0.15M',       'm2',   None),
            ('05',          'OBRAS DE ARTE Y DRENAJE',                          '',     None),
            ('05.01',       'ALCANTARILLA TMC D=36"',                           'm',    None),
            ('05.02',       'CUNETA REVESTIDA DE CONCRETO',                     'm',    None),
            ('05.03',       'BADEN DE CONCRETO F\'C=210 KG/CM2',                'm2',   None),
            ('06',          'SEÑALIZACION',                                     '',     None),
            ('06.01',       'HITOS KILOMETRICOS',                               'und',  None),
            ('06.02',       'SEÑAL PREVENTIVA',                                 'und',  None),
            ('07',          'MITIGACION AMBIENTAL',                             '',     None),
            ('07.01',       'READECUACION DE CANTERA Y BOTADERO',               'glb',  1),
            ('08',          'LIMPIEZA FINAL',                                   '',     None),
            ('08.01',       'LIMPIEZA FINAL DE OBRA',                           'glb',  1),
        ],
    },
    'canal_riego': {
        'titulo': 'Canal de Riego',
        'partidas': [
            ('01',          'OBRAS PROVISIONALES',                              '',     None),
            ('01.01',       'CARTEL DE OBRA DE 3.60X2.40M',                     'und',  1),
            ('01.02',       'AGUA PARA LA CONSTRUCCION',                        'glb',  1),
            ('02',          'TRABAJOS PRELIMINARES',                            '',     None),
            ('02.01',       'TRAZO Y REPLANTEO DE CANAL',                       'm',    None),
            ('02.02',       'LIMPIEZA Y DESBROCE DE CANAL',                     'm',    None),
            ('03',          'MOVIMIENTO DE TIERRAS',                            '',     None),
            ('03.01',       'EXCAVACION DE CAJA DE CANAL',                      'm3',   None),
            ('03.02',       'REFINE Y NIVELACION DE CAJA DE CANAL',             'm2',   None),
            ('03.03',       'ELIMINACION DE MATERIAL EXCEDENTE',                'm3',   None),
            ('04',          'OBRAS DE CONCRETO',                                '',     None),
            ('04.01',       'CONCRETO F\'C=175 EN REVESTIMIENTO DE CANAL',      'm3',   None),
            ('04.02',       'ENCOFRADO Y DESENCOFRADO DE CANAL',                'm2',   None),
            ('04.03',       'JUNTA WATER STOP / ASFALTICA',                     'm',    None),
            ('05',          'OBRAS DE ARTE',                                    '',     None),
            ('05.01',       'TOMA LATERAL',                                     'und',  None),
            ('05.02',       'COMPUERTA METALICA TIPO TARJETA',                  'und',  None),
            ('05.03',       'CAIDA / RAPIDA DE CONCRETO',                       'und',  None),
            ('06',          'LIMPIEZA FINAL',                                   '',     None),
            ('06.01',       'LIMPIEZA FINAL DE OBRA',                           'glb',  1),
        ],
    },
    'losa_deportiva': {
        'titulo': 'Losa Deportiva Multiuso',
        'partidas': [
            ('01',          'OBRAS PROVISIONALES',                              '',     None),
            ('01.01',       'CARTEL DE OBRA DE 3.60X2.40M',                     'und',  1),
            ('02',          'TRABAJOS PRELIMINARES',                            '',     None),
            ('02.01',       'LIMPIEZA DE TERRENO MANUAL',                       'm2',   None),
            ('02.02',       'TRAZO Y REPLANTEO',                                'm2',   None),
            ('03',          'MOVIMIENTO DE TIERRAS',                            '',     None),
            ('03.01',       'CORTE Y NIVELACION DE TERRENO',                    'm3',   None),
            ('03.02',       'ELIMINACION DE MATERIAL EXCEDENTE',                'm3',   None),
            ('04',          'OBRAS DE CONCRETO',                                '',     None),
            ('04.01',       'BASE DE AFIRMADO E=4"',                            'm2',   None),
            ('04.02',       'LOSA DE CONCRETO F\'C=210 E=10 CM',                'm2',   None),
            ('04.03',       'ENCOFRADO Y DESENCOFRADO DE BORDES',               'm2',   None),
            ('04.04',       'JUNTAS DE DILATACION',                             'm',    None),
            ('04.05',       'BRUÑADO Y ACABADO DE LOSA',                        'm2',   None),
            ('05',          'PINTURA Y DEMARCACION',                            '',     None),
            ('05.01',       'PINTURA DE TRAFICO PARA DEMARCACION DEPORTIVA',    'm2',   None),
            ('06',          'EQUIPAMIENTO DEPORTIVO',                           '',     None),
            ('06.01',       'TABLEROS DE BASQUET',                              'und',  None),
            ('06.02',       'ARCOS DE FULBITO CON MALLA',                       'und',  None),
            ('06.03',       'PARANTES Y NET DE VOLEY',                          'und',  None),
            ('07',          'CERCO PERIMETRICO',                                '',     None),
            ('07.01',       'CERCO PERIMETRICO CON MALLA GALVANIZADA',          'm',    None),
            ('08',          'LIMPIEZA FINAL',                                   '',     None),
            ('08.01',       'LIMPIEZA FINAL DE OBRA',                           'glb',  1),
        ],
    },
    'muro_contencion': {
        'titulo': 'Muro de Contención',
        'partidas': [
            ('01',          'OBRAS PROVISIONALES',                              '',     None),
            ('01.01',       'CARTEL DE OBRA DE 3.60X2.40M',                     'und',  1),
            ('02',          'TRABAJOS PRELIMINARES',                            '',     None),
            ('02.01',       'TRAZO, NIVELES Y REPLANTEO',                       'm',    None),
            ('02.02',       'LIMPIEZA DE TERRENO',                              'm2',   None),
            ('03',          'MOVIMIENTO DE TIERRAS',                            '',     None),
            ('03.01',       'EXCAVACION PARA CIMENTACION',                      'm3',   None),
            ('03.02',       'RELLENO COMPACTADO DETRAS DEL MURO',               'm3',   None),
            ('03.03',       'ELIMINACION DE MATERIAL EXCEDENTE',                'm3',   None),
            ('04',          'OBRAS DE CONCRETO',                                '',     None),
            ('04.01',       'SOLADO E=10 CM',                                   'm2',   None),
            ('04.02',       'ACERO CORRUGADO Fy=4200 KG/CM2',                   'kg',   None),
            ('04.03',       'ENCOFRADO Y DESENCOFRADO CARAVISTA',               'm2',   None),
            ('04.04',       'CONCRETO F\'C=210 KG/CM2 EN MURO',                 'm3',   None),
            ('04.05',       'TUBERIA PVC 3" PARA LLORADEROS / DRENAJE',         'm',    None),
            ('05',          'JUNTAS Y ACABADOS',                                '',     None),
            ('05.01',       'JUNTA DE DILATACION CON TECNOPOR',                 'm',    None),
            ('06',          'LIMPIEZA FINAL',                                   '',     None),
            ('06.01',       'LIMPIEZA FINAL DE OBRA',                           'glb',  1),
        ],
    },
}


def listar_plantillas() -> list:
    """Devuelve [(clave, titulo), ...] de las plantillas disponibles."""
    return [(k, v['titulo']) for k, v in _PLANTILLAS_PARTIDAS.items()]


def sugerir_partidas_local(tipo_obra: str) -> list:
    """Devuelve la plantilla de partidas para un tipo de obra dado.
    Cada partida = dict {item, descripcion, unidad, metrado_sugerido}."""
    plantilla = _PLANTILLAS_PARTIDAS.get(tipo_obra)
    if not plantilla:
        return []
    out = []
    for item, desc, und, met in plantilla['partidas']:
        es_titulo = (und == '' or und is None) and met is None
        out.append({
            'item': item,
            'descripcion': desc,
            'unidad': und or '',
            'metrado_sugerido': met,
            'es_titulo': es_titulo,
        })
    return out


# ── RAG Fase 1 — recuperación desde la biblioteca (la semilla) ─────────────
# Palabras genéricas que NO discriminan el tipo de obra (se descartan al
# derivar los términos de búsqueda).
_STOPWORDS_OBRA = frozenset("""
de del la el los las en y a o u con para por que se su sus al un una unos unas
obra obras proyecto construccion mejoramiento ampliacion rehabilitacion
mantenimiento ejecucion creacion instalacion reposicion renovacion servicio
servicios sistema integral nuevo nueva varios distrito provincia region
departamento centro poblado localidad zona area sector etapa
""".split())

# Sub-temas de una EDIFICACIÓN (vivienda, colegio, posta, local…): la secuencia
# constructiva completa que casi siempre lleva. La semilla tiene estos ACUs
# aunque el nombre del proyecto solo diga «vivienda».
_EDIFICACION = [
    'excavacion', 'solado', 'cimiento corrido', 'sobrecimiento', 'falso piso',
    'zapata', 'viga de cimentacion', 'columna', 'viga', 'losa aligerada',
    'losa maciza', 'escalera', 'acero', 'encofrado', 'concreto',
    'muro de ladrillo', 'tabique', 'tarrajeo', 'cielo raso', 'contrapiso',
    'piso', 'zocalo', 'contrazocalo', 'cobertura', 'puerta', 'ventana',
    'pintura', 'instalacion sanitaria', 'instalacion electrica',
]

# Expansión de dominio: si el nombre/notas contiene un disparador, se agregan
# los sub-temas que un presupuesto de ese tipo casi siempre incluye (y que la
# semilla tiene como ACUs aunque el nombre no los nombre). Arranca con las
# familias de obra de la semilla; ampliable.
_EXPANSION_DOMINIO = {
    'canal':        ['revestimiento', 'concreto', 'encofrado', 'excavacion',
                     'junta water stop', 'compuerta', 'transicion', 'caja toma'],
    'riego':        ['canal', 'revestimiento', 'tuberia', 'reservorio',
                     'bocatoma', 'compuerta'],
    'carretera':    ['movimiento de tierras', 'afirmado', 'base granular',
                     'subbase', 'cuneta', 'alcantarilla', 'pavimento'],
    'trocha':       ['movimiento de tierras', 'afirmado', 'cuneta',
                     'alcantarilla', 'corte', 'relleno'],
    'pavimento':    ['base granular', 'subbase', 'imprimacion',
                     'carpeta asfaltica', 'concreto', 'sardinel'],
    'agua':         ['tuberia', 'excavacion zanja', 'relleno', 'valvula',
                     'conexion domiciliaria', 'reservorio'],
    'saneamiento':  ['tuberia', 'buzon', 'excavacion zanja', 'relleno',
                     'conexion domiciliaria', 'camara'],
    'alcantarillado': ['tuberia', 'buzon', 'excavacion zanja', 'relleno',
                       'conexion domiciliaria'],
    # Edificaciones — todas comparten la secuencia constructiva _EDIFICACION.
    'vivienda':     _EDIFICACION,
    'unifamiliar':  _EDIFICACION,
    'multifamiliar': _EDIFICACION,
    'casa':         _EDIFICACION,
    'modulo':       _EDIFICACION,
    'pabellon':     _EDIFICACION,
    'edificacion':  _EDIFICACION,
    'edificio':     _EDIFICACION,
    'local':        _EDIFICACION,
    'colegio':      _EDIFICACION + ['cobertura'],
    'educativa':    _EDIFICACION + ['cobertura'],
    'inicial':      _EDIFICACION + ['cobertura'],
    'posta':        _EDIFICACION,
    'salud':        _EDIFICACION + ['instalaciones'],
    'mercado':      _EDIFICACION + ['cobertura'],
    'muro':         ['concreto', 'encofrado', 'acero', 'excavacion',
                     'mamposteria'],
    'ribereña':     ['enrocado', 'gavion', 'excavacion', 'movimiento de tierras'],
    'puente':       ['concreto', 'encofrado', 'acero', 'estribo', 'losa',
                     'pilote'],
    'reservorio':   ['concreto', 'encofrado', 'acero', 'excavacion',
                     'geomembrana', 'tarrajeo'],
}


def _derivar_terminos_obra(nombre: str, notas: str = '') -> list:
    """Stage 1 del RAG: deriva términos de búsqueda del nombre + notas del
    proyecto. Tokeniza, descarta genéricos y expande con sub-temas de dominio."""
    base = _normalizar_desc(f"{nombre} {notas}")
    if not base:
        return []
    terms = {t for t in base.split()
             if len(t) >= 4 and t not in _STOPWORDS_OBRA}
    for disparador, extra in _EXPANSION_DOMINIO.items():
        if disparador in base:
            terms.update(extra)
    return sorted(terms)


def recuperar_partidas_biblioteca(terminos: list, k: int = 50,
                                  por_termino: int = 8, umbral: int = 75,
                                  grupo: str = None) -> list:
    """Stage 2 del RAG: recupera de biblioteca_cu las partidas más parecidas a
    los `terminos` (fuzzy con rapidfuzz). Toma las top `por_termino` de cada
    término para garantizar variedad de sub-temas, deduplica por descripción y
    corta en `k`. Retorna [{descripcion, unidad, grupo, _score}, ...] o []."""
    if not terminos:
        return []
    try:
        from rapidfuzz import fuzz, process
    except Exception:
        return []
    from core.database import pool_partidas_rag
    conn = get_db()
    pool = pool_partidas_rag(conn)          # biblioteca + proyectos propios
    conn.close()
    if not pool:
        return []
    # Indexado por posición; `_norm` ya viene precalculado y cacheado en el pool.
    choices = {i: p['_norm'] for i, p in enumerate(pool)}
    mejor   = {}  # idx -> score
    for t in terminos:
        for _desc, score, idx in process.extract(
                t, choices, scorer=fuzz.token_set_ratio, limit=por_termino):
            if score >= umbral and score > mejor.get(idx, 0):
                mejor[idx] = score
    ordenado = sorted(mejor.items(), key=lambda kv: kv[1], reverse=True)
    out, seen = [], set()
    for idx, score in ordenado:
        p = pool[idx]
        clave = choices[idx]
        if clave in seen:
            continue
        seen.add(clave)
        out.append({'descripcion': p['descripcion'], 'unidad': p['unidad'],
                    'grupo': '', '_score': score})
        if len(out) >= k:
            break
    return out


def _derivar_frases_obra(nombre: str, notas: str = '') -> list:
    """Para el lado SEMÁNTICO del RAG: arma frases de intención (multi-palabra),
    no tokens sueltos. Los embeddings estáticos rinden por frase — «revestimiento
    de canal» encuentra «ENCOFRADO DE MUROS DE CANAL»; el token «revestimiento»
    suelto se inunda de genéricos. Construye «{subtema} de {obra}» por cada
    disparador de dominio presente, más el propio nombre del proyecto."""
    base = _normalizar_desc(f"{nombre} {notas}")
    if not base:
        return []
    cabezas = [trig for trig in _EXPANSION_DOMINIO if trig in base]
    frases = set()
    frases.add(' '.join(base.split()[:12]))            # intención global del proyecto
    for h in cabezas:
        for sub in _EXPANSION_DOMINIO[h]:
            frases.add(f"{sub} de {h}")
    if not cabezas:                                     # sin dominio conocido → cae a términos
        frases.update(_derivar_terminos_obra(nombre, notas))
    return sorted(frases)


def _fusion_rrf(listas: list, k: int = 50, c: int = 60) -> list:
    """Reciprocal Rank Fusion: combina varias listas rankeadas en una sola sin
    depender de la escala de sus scores (fuzzy 0-100 vs coseno 0-1). El peso de
    un ítem = Σ 1/(c + rank) sobre las listas donde aparece. Dedup por
    descripción normalizada; preserva el primer dict visto."""
    acc, info = {}, {}
    for lista in listas:
        for rank, item in enumerate(lista or []):
            clave = _normalizar_desc(item.get('descripcion', ''))
            if not clave:
                continue
            acc[clave] = acc.get(clave, 0.0) + 1.0 / (c + rank)
            info.setdefault(clave, item)
    ordenado = sorted(acc.items(), key=lambda kv: kv[1], reverse=True)
    return [info[clave] for clave, _ in ordenado[:k]]


def recuperar_partidas_hibrido(nombre: str, notas: str = '', k: int = 50) -> list:
    """RAG: combina recuperación fuzzy (Fase 1) y semántica (Fase 2, model2vec)
    vía RRF. Si model2vec no está disponible o falla, devuelve solo el fuzzy."""
    terminos = _derivar_terminos_obra(nombre, notas)
    if not terminos:
        return []
    fuzzy = recuperar_partidas_biblioteca(terminos, k=k)
    semantico = []
    try:
        from core.biblioteca_embeddings import (disponible,
                                                recuperar_partidas_semantico)
        if disponible():
            frases = _derivar_frases_obra(nombre, notas)   # frases, no tokens
            semantico = recuperar_partidas_semantico(frases, k=k, por_termino=6)
    except Exception:
        semantico = []
    if not semantico:
        return fuzzy
    return _fusion_rrf([fuzzy, semantico], k=k)


def _proyecto_similar(nombre: str, notas: str = '', excluir_pid=None):
    """Proyecto (semilla o del usuario) más parecido por nombre — su estructura
    sirve de ESQUELETO. Retorna (pid, nombre) o None. Semántico si hay model2vec,
    si no fuzzy."""
    conn = get_db()
    rows = conn.execute(
        "SELECT pr.id, pr.nombre FROM proyectos pr WHERE EXISTS "
        "(SELECT 1 FROM partidas p WHERE p.proyecto_id=pr.id AND p.es_titulo=0)"
        + (" AND pr.id != ?" if excluir_pid else ""),
        (excluir_pid,) if excluir_pid else ()
    ).fetchall()
    conn.close()
    cand = [(r['id'], r['nombre']) for r in rows if (r['nombre'] or '').strip()]
    if not cand:
        return None
    query = _normalizar_desc(f"{nombre} {notas}")
    if not query:
        return None
    try:
        from core.biblioteca_embeddings import disponible, _modelo
        if disponible():
            import numpy as np
            m = _modelo()
            qv = np.asarray(m.encode([query]), dtype=np.float32)
            cv = np.asarray(m.encode([_normalizar_desc(c[1]) for c in cand]),
                            dtype=np.float32)
            qv = qv / (np.linalg.norm(qv, axis=1, keepdims=True) + 1e-9)
            cv = cv / (np.linalg.norm(cv, axis=1, keepdims=True) + 1e-9)
            sims = (cv @ qv.T).ravel()
            best = int(sims.argmax())
            return cand[best] if sims[best] >= 0.30 else None
    except Exception:
        pass
    try:
        from rapidfuzz import fuzz
        best, bs = None, 0
        for pid, nm in cand:
            s = fuzz.token_set_ratio(query, _normalizar_desc(nm))
            if s > bs:
                bs, best = s, (pid, nm)
        return best if bs >= 45 else None
    except Exception:
        return None


def _estructura_referencia(nombre: str, notas: str = '', excluir_pid=None,
                           max_lineas: int = 120) -> str:
    """Estructura (títulos+partidas, jerárquica y en orden) de un proyecto real
    parecido, formateada como esqueleto para el prompt. '' si no hay match."""
    sim = _proyecto_similar(nombre, notas, excluir_pid)
    if not sim:
        return ''
    pid, nm = sim
    conn = get_db()
    rows = conn.execute(
        "SELECT item, descripcion, unidad, es_titulo FROM partidas "
        "WHERE proyecto_id=? ORDER BY COALESCE(sub_presupuesto_id,0), id",
        (pid,)
    ).fetchall()
    conn.close()
    if not rows:
        return ''
    lineas = []
    for r in rows[:max_lineas]:
        sangria = '  ' * max(0, (r['item'] or '').count('.'))
        und = '' if r['es_titulo'] else f" [{r['unidad'] or ''}]"
        lineas.append(f"{sangria}{r['item']} {r['descripcion']}{und}")
    return (f"\nESTRUCTURA DE REFERENCIA — un presupuesto REAL parecido «{nm}». "
            "Tómala como ESQUELETO: respeta su orden y sus capítulos, y adáptala "
            "al proyecto (agrega, quita o renombra lo que aplique):\n"
            + "\n".join(lineas) + "\n")


def sugerir_partidas_ia(proyecto_id: int) -> tuple:
    """Pide a la IA una lista de partidas típicas según el nombre + ubicación
    + modalidad del proyecto. Retorna (lista, error)."""
    import re, json
    api_key = get_config('api_key', '')
    conn = get_db()
    proy = conn.execute(
        "SELECT * FROM proyectos WHERE id=?", (proyecto_id,)
    ).fetchone()
    conn.close()
    if not proy:
        return None, "Proyecto no encontrado."

    nombre    = proy['nombre'] or 'Sin nombre'
    ubicacion = proy['ubicacion'] or 'Perú'
    modalidad = proy['modalidad'] or 'Contrata'
    # Notas del proyecto — el usuario las llena en el form de creación
    try:
        notas = (proy['notas'] or '').strip()
    except (IndexError, KeyError):
        notas = ''
    notas_block = ''
    if notas:
        notas_block = (f"\n- Notas/descripción detallada:\n"
                       f"\"\"\"\n{notas}\n\"\"\"\n")

    # ── RAG Fase 1: recuperar partidas reales de la biblioteca (la semilla) y
    # ofrecérselas a la IA como «menú» para que las copie TAL CUAL → al importar
    # enganchan su ACU real. Si falla o no hay match, cae al modo anterior.
    menu_block = ''
    try:
        _reco = recuperar_partidas_hibrido(nombre, notas, k=50)
    except Exception:
        _reco = []
    if _reco:
        _lineas = "\n".join(f"  {r['descripcion']} [{r['unidad'] or '—'}]"
                            for r in _reco)
        menu_block = (
            "\nPARTIDAS SUGERIDAS DE TU BIBLIOTECA (candidatas por similitud; "
            "ALGUNAS PUEDEN NO APLICAR a este proyecto — es tu criterio cuáles "
            f"usar):\n{_lineas}\n")

    # Esqueleto = estructura de un presupuesto REAL parecido (orden + capítulos).
    esqueleto_block = ''
    try:
        esqueleto_block = _estructura_referencia(nombre, notas,
                                                 excluir_pid=proyecto_id)
    except Exception:
        esqueleto_block = ''

    prompt = f"""Eres ingeniero residente experto en presupuestos peruanos. \
A partir del nombre, ubicación y NOTAS del proyecto, genera una LISTA \
REALISTA de partidas típicas que debería incluir, organizadas jerárquicamente \
con numeración 01, 01.01, 01.01.01, etc.

DATOS DEL PROYECTO:
- Nombre: {nombre}
- Ubicación: {ubicacion}
- Modalidad: {modalidad}{notas_block}
{esqueleto_block}{menu_block}
INSTRUCCIONES:
1. Genera entre 30 y 80 partidas según la complejidad del proyecto.
2. Si hay «ESTRUCTURA DE REFERENCIA» arriba, BÁSATE en ella para los capítulos y \
su orden (es un presupuesto real del mismo tipo): replica su esqueleto y adáptalo \
al proyecto. Es tu mejor guía de completitud y secuencia constructiva.
3. El menú «PARTIDAS SUGERIDAS» son ítems de tu biblioteca que PODRÍAN aplicar. \
Cuando una corresponda DE VERDAD al proyecto, cópiala TAL CUAL (misma redacción \
y unidad) para enlazar su costo. PERO si el proyecto es de otro rubro (p.ej. \
mantenimiento de maquinaria, electromecánico, servicios, mobiliario) y el menú \
no encaja, IGNÓRALO y genera las partidas correctas con tu criterio técnico — \
NUNCA fuerces partidas de construcción (movimiento de tierras, concreto…) que \
no apliquen al proyecto.
4. Usa títulos (sin unidad) para los grupos: 01 OBRAS PROVISIONALES, 02 \
TRABAJOS PRELIMINARES, etc.
5. Las partidas hoja (subitems) deben tener unidad típica: m2, m3, m, kg, \
und, pto, glb, etc.
6. Respeta el orden constructivo: provisionales → preliminares → mov.tierras \
→ concreto simple → estructuras (acero/encofrado/concreto) → albañilería \
→ revoques → instalaciones → acabados → limpieza.
7. Usa terminología técnica peruana estándar (CAPECO, RNE, NTP).

FORMATO DE RESPUESTA (JSON puro, sin markdown):
{{
  "partidas": [
    {{"item": "01", "descripcion": "OBRAS PROVISIONALES", "unidad": ""}},
    {{"item": "01.01", "descripcion": "CARTEL DE OBRA DE 3.60X2.40M", "unidad": "und"}},
    ...
  ]
}}

Responde ÚNICAMENTE con el JSON, sin texto adicional ni bloques markdown."""

    text, err = _llamar_ia(prompt, api_key, max_tokens=4000)
    if err:
        return None, f"Error IA: {err}"
    if not text:
        return None, "La IA no devolvió respuesta."

    text = text.strip()
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return None, f"Respuesta IA no es JSON válido: {e}"

    parts = data.get('partidas', []) if isinstance(data, dict) else data
    if not isinstance(parts, list):
        return None, "Formato inesperado de respuesta IA."

    out = []
    for p in parts:
        if not isinstance(p, dict):
            continue
        item = (p.get('item') or '').strip()
        desc = (p.get('descripcion') or '').strip()
        und  = (p.get('unidad') or '').strip()
        if not item or not desc:
            continue
        es_titulo = not und  # sin unidad → título
        out.append({
            'item': item,
            'descripcion': desc,
            'unidad': und,
            'metrado_sugerido': None,
            'es_titulo': es_titulo,
        })
    return out, None


def importar_partidas_sugeridas(proyecto_id: int, partidas: list) -> int:
    """Crea las partidas en la BD respetando jerarquía. Retorna cuántas
    se crearon. Cada `p` debe tener: item, descripcion, unidad, es_titulo,
    metrado_sugerido."""
    if not partidas:
        return 0
    conn = get_db()
    cnt = 0
    for p in partidas:
        item = (p.get('item') or '').strip()
        if not item:
            continue
        # Calcular nivel desde el item (cuenta de puntos + 1)
        nivel = item.count('.') + 1
        try:
            conn.execute(
                """INSERT INTO partidas (proyecto_id, item, descripcion,
                                          unidad, metrado, nivel, es_titulo,
                                          precio_unitario)
                   VALUES (?,?,?,?,?,?,?,0)""",
                (proyecto_id, item, p.get('descripcion', ''),
                 p.get('unidad', ''),
                 float(p.get('metrado_sugerido') or 0),
                 nivel,
                 1 if p.get('es_titulo') else 0)
            )
            cnt += 1
        except Exception:
            # Si el item ya existe (UNIQUE), saltarlo
            pass
    conn.commit()
    conn.close()
    return cnt


def _normalizar_desc(s: str) -> str:
    """Normaliza descripción para fuzzy matching: minúsculas, sin tildes,
    sin signos, espacios colapsados."""
    if not s:
        return ''
    import unicodedata, re as _re
    nfkd = unicodedata.normalize('NFKD', s)
    sin_tilde = ''.join(c for c in nfkd if not unicodedata.combining(c))
    sin_sig = _re.sub(r'[^\w\s]', ' ', sin_tilde)
    return _re.sub(r'\s+', ' ', sin_sig).strip().lower()


def buscar_en_biblioteca(descripcion: str, unidad: str = '') -> dict | None:
    """Busca en el POOL unificado (biblioteca_cu + ACUs de proyectos propios) la
    partida cuya descripción coincida con la consultada y devuelve su ACU.
    Retorna {descripcion, unidad, rendimiento, costo_unitario, items, _origen}
    o None. Su composición (items) sirve para copiar a acu_items al importar."""
    if not descripcion:
        return None
    target = _normalizar_desc(descripcion)
    if len(target) < 4:
        return None
    palabras = set(target.split())
    if len(palabras) < 2:
        return None
    from core.database import pool_partidas_rag, acu_de_pool
    conn = get_db()
    pool = pool_partidas_rag(conn)
    mejor = None
    mejor_score = 0
    for p in pool:
        if unidad and (p['unidad'] or '') != unidad:
            continue
        d_norm = p['_norm']          # precalculado y cacheado en el pool
        if not d_norm:
            continue
        d_palabras = set(d_norm.split())
        comunes = palabras & d_palabras
        if not comunes:
            continue
        # Jaccard-like: comunes / max(palabras, d_palabras)
        score = len(comunes) / max(len(palabras), len(d_palabras))
        if score > mejor_score:
            mejor_score = score
            mejor = p
    if not mejor or mejor_score < 0.5:
        conn.close()
        return None
    acu = acu_de_pool(conn, mejor['origen'], mejor['ref_id'])
    conn.close()
    if not acu:
        return None
    return {'descripcion': mejor['descripcion'], 'unidad': mejor['unidad'],
            'rendimiento': acu['rendimiento'],
            'costo_unitario': acu['costo_unitario'],
            'items': acu['items'], '_score': mejor_score,
            '_origen': mejor['origen']}


def importar_partidas_con_biblioteca(proyecto_id: int, partidas: list,
                                      usar_biblioteca: bool = True) -> tuple[int, int]:
    """Importa partidas. Si `usar_biblioteca=True`, busca cada partida en
    biblioteca_cu y, si encuentra match suficiente, copia el ACU + rendimiento.
    Retorna (creadas, con_acu_de_biblioteca)."""
    if not partidas:
        return (0, 0)
    conn = get_db()
    creadas = 0
    con_acu = 0
    for p in partidas:
        item = (p.get('item') or '').strip()
        if not item:
            continue
        nivel = item.count('.') + 1
        es_titulo = bool(p.get('es_titulo'))
        unidad = p.get('unidad', '') or ''
        descripcion = p.get('descripcion', '')

        # Si hay match en biblioteca y NO es título, importar con ACU
        bib_match = None
        if usar_biblioteca and not es_titulo:
            try:
                bib_match = buscar_en_biblioteca(descripcion, unidad)
            except Exception:
                bib_match = None

        rendimiento = (bib_match.get('rendimiento') if bib_match else
                        p.get('rendimiento', 1) or 1)
        precio_unit = bib_match.get('costo_unitario', 0) if bib_match else 0

        try:
            cur = conn.execute(
                """INSERT INTO partidas (proyecto_id, item, descripcion,
                                          unidad, metrado, nivel, es_titulo,
                                          precio_unitario, rendimiento)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (proyecto_id, item, descripcion,
                 unidad,
                 float(p.get('metrado_sugerido') or 0),
                 nivel,
                 1 if es_titulo else 0,
                 float(precio_unit or 0),
                 float(rendimiento or 1))
            )
            new_pid = cur.lastrowid
            creadas += 1
            # Copiar items del ACU si hay match
            if bib_match and bib_match.get('items'):
                for it in bib_match['items']:
                    precio = it.get('precio')
                    conn.execute(
                        """INSERT INTO acu_items (partida_id, recurso_id,
                                                   cuadrilla, cantidad, precio)
                           VALUES (?,?,?,?,?)""",
                        (new_pid, it['recurso_id'],
                         it.get('cuadrilla') or 0,
                         it.get('cantidad') or 0,
                         precio if precio else None)
                    )
                con_acu += 1
        except Exception:
            pass
    conn.commit()
    conn.close()
    return (creadas, con_acu)
