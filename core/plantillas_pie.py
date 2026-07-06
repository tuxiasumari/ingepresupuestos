# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""Plantillas precargadas (borradores) para el Pie de Presupuesto.

Estructuras típicas estilo CAPECO de Gastos Generales, Supervisión,
Expediente Técnico y Liquidación de Obra. Los precios vienen en 0 a
propósito: son BORRADORES de estructura para que el usuario ajuste montos,
tiempos y % de participación según cada proyecto.

Formato de cada ítem (espeja la tabla `gastos_generales`):
    {tipo, descripcion, unidad, n_personas, tiempo, pct_participacion, precio}
`tipo` = 'grupo' (subtítulo, sin números) | 'item' (fila de detalle).
"""
from __future__ import annotations


def _g(descripcion: str) -> dict:
    """Fila de grupo (subtítulo dentro de la planilla)."""
    return {'tipo': 'grupo', 'descripcion': descripcion}


def _i(descripcion: str, unidad: str = 'MES', n_personas: float = 1,
       tiempo: float = 1, pct: float = 100, precio: float = 0) -> dict:
    """Fila de detalle. `precio` en 0 por defecto (borrador a completar)."""
    return {'tipo': 'item', 'descripcion': descripcion, 'unidad': unidad,
            'n_personas': n_personas, 'tiempo': tiempo,
            'pct_participacion': pct, 'precio': precio}


_PLANTILLAS: list[tuple[str, str, list[dict]]] = [
    ('gg', 'Gastos Generales (estándar)', [
        _g('GASTOS GENERALES FIJOS'),
        _i('Gastos de licitación y contratación', 'GLB', 1, 1, 100, 0),
        _i('Gastos legales y notariales',          'GLB', 1, 1, 100, 0),
        _i('Gastos financieros (cartas fianza)',   'GLB', 1, 1, 100, 0),
        _i('Seguros (CAR / SCTR)',                 'GLB', 1, 1, 100, 0),
        _g('PERSONAL TÉCNICO Y ADMINISTRATIVO'),
        _i('Ingeniero Residente de Obra', 'MES', 1, 1, 100, 0),
        _i('Ingeniero Asistente',         'MES', 1, 1, 100, 0),
        _i('Maestro de Obra',             'MES', 1, 1, 100, 0),
        _i('Administrador de Obra',       'MES', 1, 1, 100, 0),
        _i('Asistente Administrativo',    'MES', 1, 1, 100, 0),
        _i('Almacenero',                  'MES', 1, 1, 100, 0),
        _i('Guardián',                    'MES', 1, 1, 100, 0),
        _g('EQUIPOS NO INCLUIDOS EN COSTOS DIRECTOS'),
        _i('Camioneta Pick Up 4x4',            'MES', 1, 1, 100, 0),
        _i('Equipos de cómputo e impresión',   'GLB', 1, 1, 100, 0),
        _i('Mobiliario de oficina de obra',    'GLB', 1, 1, 100, 0),
        _g('GASTOS VARIOS'),
        _i('Útiles de oficina y escritorio',         'GLB', 1, 1, 100, 0),
        _i('Servicios (agua, luz, internet, teléfono)', 'MES', 1, 1, 100, 0),
        _i('Ensayos de laboratorio (control de calidad)', 'GLB', 1, 1, 100, 0),
        _i('Implementos de seguridad (EPP)',         'GLB', 1, 1, 100, 0),
        _i('Cartel de obra',                         'UND', 1, 1, 100, 0),
        _i('Movilización y desmovilización',         'GLB', 1, 1, 100, 0),
    ]),
    ('supervision', 'Supervisión', [
        _g('PERSONAL DE SUPERVISIÓN'),
        _i('Ingeniero Supervisor / Inspector', 'MES', 1, 1, 100, 0),
        _i('Asistente de Supervisión',         'MES', 1, 1, 100, 0),
        _i('Especialista (según especialidad)', 'MES', 1, 1, 100, 0),
        _g('EQUIPOS Y GASTOS DE SUPERVISIÓN'),
        _i('Camioneta para supervisión',       'MES', 1, 1, 100, 0),
        _i('Equipos de medición y cómputo',    'GLB', 1, 1, 100, 0),
        _i('Ensayos de control de calidad',    'GLB', 1, 1, 100, 0),
        _i('Útiles y gastos de oficina',       'GLB', 1, 1, 100, 0),
    ]),
    ('expediente', 'Expediente Técnico', [
        _g('ELABORACIÓN DEL EXPEDIENTE TÉCNICO'),
        _i('Elaboración del expediente técnico', 'GLB', 1, 1, 100, 0),
        _i('Levantamiento topográfico',          'GLB', 1, 1, 100, 0),
        _i('Estudio de mecánica de suelos',      'GLB', 1, 1, 100, 0),
        _i('Estudio de impacto ambiental',       'GLB', 1, 1, 100, 0),
        _i('Estudios básicos complementarios',   'GLB', 1, 1, 100, 0),
    ]),
    ('liquidacion', 'Liquidación de Obra', [
        _g('LIQUIDACIÓN DE OBRA'),
        _i('Elaboración de la liquidación de obra', 'GLB', 1, 1, 100, 0),
        _i('Planos de replanteo (as-built)',        'GLB', 1, 1, 100, 0),
        _i('Memoria descriptiva valorizada',        'GLB', 1, 1, 100, 0),
    ]),
    ('gg_ad', 'Gastos Generales — detallado (obra AD)', [
        _g('1. GASTOS VARIABLES'),
        _g('GASTOS DE OPERACIÓN DE OFICINA EN OBRA'),
        _g('CONTRATACION DE PERSONAL'),
        _g('PERSONAL CON CONTRATO A PLAZO FIJO'),
        _i('Residente de Obra', 'mes', 1, 3.0, 100.0, 4500.0),
        _i('Ing. Asistente de Obra', 'mes', 1, 3.0, 100.0, 3000.0),
        _i('Ing. Mecanico-electricista', 'mes', 1, 4.0, 100.0, 3000.0),
        _i('Ing. en Informatica y Sistemas', 'mes', 1, 0.0, 100.0, 3000.0),
        _i('Ing. de Seguridad', 'mes', 1, 4.0, 100.0, 3000.0),
        _i('Asistente Administrativo', 'mes', 1, 3.0, 100.0, 2500.0),
        _i('Guardian', 'mes', 1, 0.0, 100.0, 2000.0),
        _i('Chofer', 'mes', 1, 0.0, 100.0, 2000.0),
        _i('Almacenero', 'mes', 1, 0.0, 100.0, 2500.0),
        _g('LEYES SOCIALES (30%)'),
        _i('Residente de Obra', 'mes', 1, 3.0, 100.0, 1350.0),
        _i('Ing. Asistente de Obra', 'mes', 1, 3.0, 100.0, 900.0),
        _i('Ing. Mecanico-electricista', 'mes', 1, 4.0, 100.0, 900.0),
        _i('Ing. en Informatica y Sistemas', 'mes', 1, 0.0, 100.0, 900.0),
        _i('Ing. de Seguridad', 'mes', 1, 4.0, 100.0, 900.0),
        _i('Asistente Administrativo', 'mes', 1, 3.0, 100.0, 750.0),
        _i('Guardian', 'mes', 1, 0.0, 100.0, 600.0),
        _i('Chofer', 'mes', 1, 0.0, 100.0, 600.0),
        _i('Almacenero', 'mes', 1, 0.0, 0.0, 750.0),
        _g('ADQUISICION DE BIENES Y SERVICIOS'),
        _g('ARTICULOS DE CONSUMO'),
        _i('Utiles de Oficina etc', 'mes', 1, 3.0, 100.0, 200.0),
        _i('Copias de Planos, Fotocopias y Similares', 'mes', 1, 4.0, 100.0, 100.0),
        _i('Equipos de Seguridad', 'mes', 1, 0.0, 100.0, 800.0),
        _i('Equipos de Computo y otros', 'mes', 1, 0.0, 100.0, 1000.0),
        _i('Comunicaciones', 'mes', 1, 0.0, 100.0, 500.0),
        _g('CONTROL DE CALIDAD'),
        _i('Ensayos de Laboratorio', 'mes', 1, 1.0, 100.0, 1000.0),
        _g('MOVILIDAD'),
        _i('Alquiler Camioneta 4x4', 'mes', 1, 5.0, 100.0, 3600.0),
        _g('GESTION DE SEGURIDAD Y SALUD  EN EL TRABAJO'),
        _i('Examen Medico Pre-Ocupacional(Personal Tecnico)', 'und', 1, 8.0, 100.0, 211.66),
        _i('Examen Medico Pre-Ocupacional(Personal obrero)', 'und', 1, 20.0, 100.0, 211.66),
        _i('SCTR(Personal Tecnico)', 'glb', 1, 1.0, 100.0, 67.8),
        _i('SCTR(Personal  Obrero)', 'glb', 1, 1.0, 100.0, 67.8),
        _g('MOVILIZACION DE PERSONAL TECNICO Y OBRERO'),
        _i('Movilizacion de Personal Profesional y Tecnico(Dentro de la ciudad)', 'und', 1, 0.0, 100.0, 122.4),
        _i('Movilizacion de Personal Obrero (Dentro de la Cuidad)', 'und', 1, 0.0, 100.0, 122.4),
        _g('VARIOS'),
        _i('Seguro de Obra.', 'glb', 1, 0.0, 100.0, 56643.18),
        _i('sencico', 'glb', 1, 0.0, 100.0, 323.68),
        _g('2. GASTOS FIJOS'),
        _i('Muebles y equipamiento oficinas', 'und', 1, 1.0, 100.0, 515.74),
        _i('Compra de equipo de computo', 'und', 1, 1.0, 100.0, 3500.0),
    ]),
    ('estudios', 'Estudios / Expediente Técnico — detallado', [
        _g('CONTRATACION DE SERVICIOS'),
        _g('CONTRATACION DE PERSONAL'),
        _i('COORDINADOR DE PROYECTO', 'mes', 1, 3.0, 100.0, 5000.0),
        _i('ASISTENTE EN PLANTA', 'mes', 1, 3.0, 100.0, 2600.0),
        _i('SECRETARIA', 'mes', 1, 3.0, 100.0, 2200.0),
        _i('PROYECTISTA INGENIERO CIVIL - COSTOS Y PRESUPUESTOS', 'mes', 1, 3.0, 100.0, 4000.0),
        _i('PROYECTISTA ING ELECTRICISTA', 'mes', 1, 2.0, 100.0, 4000.0),
        _i('PROYECTISTA ARQUITECTURA', 'mes', 1, 2.0, 100.0, 4000.0),
        _i('ASISTENTE ING CIVIL', 'mes', 1, 2.0, 100.0, 2600.0),
        _g('CONSULTORIA'),
        _i('ESTUDIO DE SUELOS', 'est', 1, 2.0, 100.0, 2000.0),
        _i('ELABORACION DE PLAN DE GESTION DE RIESGOS', 'est', 1, 0.0, 100.0, 2000.0),
        _i('LEVANTAMIENTO TOPOGRAFICO', 'est', 1, 0.0, 100.0, 2000.0),
        _i('ELABORACION DEL EXPEDIENTE TECNICO', 'est', 1, 1.0, 100.0, 0.0),
        _g('OTROS SERVICIOS'),
        _i('IMPRESIONES, REPARACION Y MANTEN. IMPRESORAS/PLOTTER', 'est', 1, 1.0, 100.0, 375.0),
        _i('MATERIAL DE ESCRITORIO', 'est', 1, 0.0, 100.0, 2500.0),
        _i('ALQUILER CAMIONETA', 'und', 1, 0.0, 100.0, 3500.0),
        _g('ADQUISICION DE BIENES'),
        _i('Impresora Multifuncional A-3', 'und', 1, 1.0, 0.0, 1800.0),
        _g('CONTRATACION DE SERVICIOS'),
        _g('SERVICIOS VARIOS'),
        _i('Estudio de Mecanica de Suelos', 'mes', 1, 1.0, 0.0, 2400.0),
        _i('Estudio de Topografia', 'mes', 1, 1.0, 0.0, 3500.0),
        _i('Otros', 'mes', 1, 1, 100, 0),
    ]),
    ('supervision_ad', 'Supervisión / Inspección — detallado', [
        _g('1. GASTOS VARIABLES'),
        _g('CONTRATACION DE PERSONAL'),
        _g('PERSONAL CON CONTRATO A PLAZO FIJO'),
        _i('Inspector de Obra', 'mes', 1, 4.0, 100.0, 6500.0),
        _i('Ing. Asistente Inspector', 'mes', 1, 4.0, 100.0, 2600.0),
        _i('Ing. Mecanico-electricista', 'mes', 1, 4.0, 50.0, 4000.0),
        _i('Ing. Calidad', 'mes', 1, 4.0, 100.0, 4900.0),
        _i('Esp. Arquitectura', 'mes', 1, 4.0, 50.0, 4000.0),
        _i('Asistente Administrativo', 'mes', 1, 4.0, 100.0, 2200.0),
        _i('Chofer', 'mes', 1, 4.0, 100.0, 2200.0),
        _g('LEYES SOCIALES (30%)'),
        _i('Inspector de Obra', 'mes', 1, 4.0, 100.0, 1950.0),
        _i('Ing. Asistente Supervisor', 'mes', 1, 4.0, 100.0, 780.0),
        _i('Ing. Mecanico-electricista', 'mes', 1, 4.0, 100.0, 1200.0),
        _i('Ing. Calidad', 'mes', 1, 4.0, 100.0, 1470.0),
        _i('Esp. Arquitectura', 'mes', 1, 4.0, 100.0, 1200.0),
        _i('Asistente Administrativo', 'mes', 1, 4.0, 100.0, 660.0),
        _i('Chofer', 'mes', 1, 4.0, 100.0, 660.0),
        _g('EVALUACIÓN DE EXPEDIENTE TECNICO'),
        _i('Arquitecto', 'serv', 1, 0.0, 100.0, 4000.0),
        _i('Ing. Civil - Estructuras', 'serv', 1, 0.0, 100.0, 4000.0),
        _i('Ing. Mecanico-electricista', 'serv', 1, 0.0, 100.0, 3000.0),
        _i('Ing. en Informatica y Sistemas', 'serv', 1, 0.0, 100.0, 3000.0),
        _i('Ing. Civil - Costos y Presupuestos', 'serv', 1, 0.0, 100.0, 4000.0),
        _g('ADQUISICION DE BIENES Y SERVICIOS'),
        _g('ARTICULOS DE CONSUMO'),
        _i('Utiles de Oficina etc', 'mes', 1, 4.0, 100.0, 200.0),
        _i('Copias de Planos, Fotocopias y Similares', 'mes', 1, 4.0, 100.0, 200.0),
        _i('Equipos de Seguridad', 'mes', 1, 4.0, 100.0, 800.0),
        _i('Alquiles de Camioneta', 'mes', 1, 4.0, 100.0, 4500.0),
        _g('CONTROL DE CALIDAD'),
        _i('Ensayos de Laboratorio', 'und', 1, 10.0, 100.0, 500.0),
        _g('ALQUILERES'),
        _i('Alquiler de Oficina', 'mes', 1, 4.0, 100.0, 2500.0),
        _g('2. GASTOS FIJOS'),
        _i('Equipos y Mobiliario', 'und', 1, 1.0, 100.0, 18249.0),
        _i('otros', 'und', 1, 3.0, 100.0, 6500.0),
    ]),
    ('liquidacion_ad', 'Liquidación — detallado', [
        _g('CONTRATACION DE SERVICIOS'),
        _g('CONTRATACION DE PERSONAL'),
        _i('Liquidador Tecnico', 'ser', 1, 1.0, 100.0, 4000.0),
        _i('Liquidador Financiero', 'ser', 1, 1.0, 100.0, 4000.0),
        _i('Asistente Tecnico', 'ser', 1, 1.0, 50.0, 2600.0),
        _i('Asistente Administrativo', 'ser', 1, 1.0, 50.0, 2200.0),
        _g('LEYES SOCIALES'),
        _i('Leyes Sociales del Personal (30%)', 'mes', 1, 1, 30.0, 3120.0),
        _g('OTROS SERVICIOS'),
        _i('Materiales de Escritorio', 'ser', 1, 1.0, 100.0, 17636.4),
        _i('Copias de Planos, Fotocopias y Similares', 'ser', 1, 1.0, 100.0, 8500.0),
        _i('Alquiler de camioneta', 'ser', 1, 2.0, 100.0, 4500.0),
    ]),
    ('gestion', 'Gestión de Proyecto — detallado', [
        _g('CONTRATACION DE SERVICIOS'),
        _g('CONTRATACION DE PERSONAL'),
        _i('Coordinador de Obra', 'ser', 1, 4.0, 50.0, 5000.0),
        _i('Especialista administrativo-Adquisiciones', 'ser', 1, 4.0, 50.0, 4000.0),
        _i('Especialista Invirte.pe (Registros)', 'ser', 1, 4.0, 50.0, 4000.0),
        _i('Asistente de contrataciones', 'ser', 1, 4.0, 50.0, 2600.0),
        _i('Asistente Administrativo', 'ser', 1, 4.0, 50.0, 2200.0),
        _g('LEYES SOCIALES'),
        _i('Leyes Sociales del Personal (30%)', 'mes', 1, 1, 30.0, 0.0),
        _g('OTROS SERVICIOS'),
        _i('Equipos Computo', 'ser', 1, 4.0, 100.0, 8000.0),
        _i('Materiales de Escritorio', 'ser', 1, 4.0, 100.0, 18920.5),
        _i('Copias de Planos, Fotocopias y Similares', 'ser', 1, 4.0, 100.0, 5000.0),
        _i('Servicios Notariales', 'und', 1, 4.0, 100.0, 8000.0),
        _i('Alquiler de camioneta', 'und', 1, 4.0, 100.0, 12000.0),
    ]),
]


def listar_plantillas_pie() -> list[tuple[str, str, list[dict]]]:
    """Devuelve [(key, nombre, items), ...] — borradores precargados."""
    return [(k, n, [dict(it) for it in items]) for k, n, items in _PLANTILLAS]


def obtener_plantilla_pie(key: str) -> list[dict]:
    """Ítems (copias) de la plantilla `key`, o lista vacía si no existe."""
    for k, _n, items in _PLANTILLAS:
        if k == key:
            return [dict(it) for it in items]
    return []
