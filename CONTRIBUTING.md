<!--
SPDX-License-Identifier: GPL-3.0-or-later
Copyright (C) 2026 Marco Sumari / Sumari SAC
-->

# Contribuir a IngePresupuestos

¡Gracias por tu interés! Toda ayuda es bienvenida, seas o no programador.

## Formas de contribuir

- 🐛 **Reportar un bug** — abre un *issue* describiendo qué pasó, qué esperabas y cómo reproducirlo (idealmente con capturas o un archivo de ejemplo).
- 💡 **Sugerir una mejora** — abre un *issue* explicando la idea y para qué serviría.
- 🌍 **Traducir** — la app está en español con cobertura parcial de inglés (`utils/i18n.py`). Ayuda a completar idiomas.
- 🧮 **Validar cálculos** — si detectas una diferencia con S10/Delphin/PowerCost/CAPECO, repórtala con el caso concreto.
- 💻 **Código** — corrige bugs o implementa mejoras (ver abajo).

## Aportar código

1. Haz un *fork* del repositorio y crea una rama descriptiva (`fix/gantt-scroll`, `feat/reporte-x`).
2. Prepara el entorno:
   ```bash
   python3 -m venv venv && source venv/bin/activate
   pip install -r requirements.txt
   ```
3. Corre los tests sin GUI antes de enviar:
   ```bash
   venv/bin/python3 tests/test_core.py
   venv/bin/python3 tests/test_reglas_negocio.py
   ```
4. Mantén el estilo del código existente (nombres en español para el dominio, comentarios claros).
5. Abre un *Pull Request* explicando **qué** cambia y **por qué**.

## Reglas de negocio (no romper)

Este software calcula presupuestos reales de obra. Cambios en `core/database.py`
(ACU, precios, redondeos, totales) deben preservar la coherencia con S10/CAPECO.
Ante la duda, abre un *issue* para discutirlo antes.

## Licencia de tus contribuciones

Al contribuir, aceptas que tu aporte se distribuya bajo la licencia del proyecto,
**GPL-3.0-or-later**.

¡Gracias por ayudar a que IngePresupuestos sea mejor! 🙌
