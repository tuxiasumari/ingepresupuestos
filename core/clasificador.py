# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""Clasificación de insumos en categorías prácticas de obra (para Requerimientos).

En obras por administración directa los requerimientos se arman por categoría
(combustibles aparte, materiales de construcción aparte, pinturas, agregados…),
alineado con el clasificador económico de gastos. Aquí usamos un set CURADO de
categorías + una heurística por palabras clave (auto-clasificación); el usuario
puede ajustar manualmente (override por recurso, columna `recursos.categoria`).

`categoria_de(descripcion, tipo)` devuelve la categoría. EQ → «EQUIPOS»,
SC → «SERVICIOS»; los materiales (MAT) se clasifican por nombre.
"""
import unicodedata


def _norm(s: str) -> str:
    s = (s or '').lower()
    return ''.join(c for c in unicodedata.normalize('NFD', s)
                   if unicodedata.category(c) != 'Mn')


CAT_EQUIPOS = "EQUIPOS"
CAT_SERVICIOS = "SERVICIOS"
CAT_OTROS = "OTROS MATERIALES"

# (categoría, [palabras clave]) — orden: lo más específico primero.
_CATS = [
    ("COMBUSTIBLES Y LUBRICANTES",
     ["gasolina", "petroleo", "diesel", "kerosene", "aceite", "grasa",
      "lubricante", "combustible", "glp", "gas licuado"]),
    ("ACERO Y SOLDADURA",
     ["acero", "fierro", "varilla", "alambre", "clavo", "soldadura",
      "electrodo", "malla", "angulo", "platina", "varillaje", "estribo"]),
    ("CEMENTO Y AGLOMERANTES",
     ["cemento", "concreto premezclado", "mortero", "cal ", "yeso", "aditivo",
      "acelerante", "fragua", "impermeabilizante", "pegamento", "cola sintetica"]),
    ("AGREGADOS",
     ["arena", "piedra", "grava", "gravilla", "confitillo", "hormigon",
      "afirmado", "ripio", "over", "lastre", "material de prestamo"]),
    ("LADRILLOS Y ALBAÑILERIA",
     ["ladrillo", "bloque", "bloqueta", "pastelero", "teja", "adoquin",
      "caravista", "celosia"]),
    ("MADERA Y ENCOFRADO",
     ["madera", "triplay", "parante", "puntal", "encofrado", "contrachapado",
      "melamina", "tornapunta", "listones", "viga de madera"]),
    ("PINTURAS Y SOLVENTES",
     ["pintura", "barniz", "esmalte", "latex", "thinner", "imprimante",
      "sellador", "laca", "temple", "disolvente", "aguarras", "oleo"]),
    ("TUBERIAS Y SANITARIOS",
     ["tuberia", "tubo", "codo", "tee", "yee", "union", "reduccion", "valvula",
      "niple", "inodoro", "lavatorio", "urinario", "grifo", "llave", "sumidero",
      "registro", "trampa", "pvc", "sanitario", "ducha", "tanque"]),
    ("MATERIALES ELECTRICOS",
     ["cable", "conductor", "interruptor", "tomacorriente", "luminaria",
      "fluorescente", "foco", "tablero", "llave termica", "canaleta", "conduit",
      "electrico", "timbre", "octogonal", "braquete", "reflector"]),
    ("FERRETERIA",
     ["perno", "tuerca", "arandela", "tornillo", "bisagra", "candado",
      "cerradura", "chapa", "abrazadera", "grapa", "remache", "cinta", "lija"]),
    ("HERRAMIENTAS",
     ["pico", "lampa", "barreta", "carretilla", "badilejo", "comba", "cincel",
      "plomada", "wincha", "escalera", "balde", "frotacho", "plancha de batir",
      "buggie", "bugui"]),
]

# Lista para combos (orden estable).
CATEGORIAS = [c for c, _ in _CATS] + [CAT_OTROS, CAT_EQUIPOS, CAT_SERVICIOS]


def categoria_de(descripcion: str, tipo: str = None) -> str:
    """Categoría de un insumo. EQ→EQUIPOS, SC→SERVICIOS; MAT por palabras clave."""
    t = (tipo or '').upper()
    if t == 'EQ':
        return CAT_EQUIPOS
    if t == 'SC':
        return CAT_SERVICIOS
    d = _norm(descripcion)
    for cat, kws in _CATS:
        for kw in kws:
            if kw in d:
                return cat
    return CAT_OTROS


def tipo_de_categoria(categoria: str) -> str:
    """Tipo de recurso ('mat'|'eq'|'sc') asociado a una categoría."""
    if categoria == CAT_EQUIPOS:
        return 'eq'
    if categoria == CAT_SERVICIOS:
        return 'sc'
    return 'mat'
