<!--
SPDX-License-Identifier: GPL-3.0-or-later
Copyright (C) 2026 Marco Sumari / Sumari SAC
-->

# IngePresupuestos

**Software libre de presupuestos de obra civil** — nativo, multiplataforma (Linux · Windows · macOS), pensado para ingenieros, arquitectos y contratistas peruanos.

**Autor:** Ing. Marco Sumari · **Sumari · Arquitectura + Ingeniería**
**Licencia:** [GPL-3.0-or-later](LICENSE) — software libre ✊
**Web:** https://ingepresupuestos.com · **Manual:** https://docs.ingepresupuestos.com

---

## ¿Qué hace?

- **Presupuestos** con árbol jerárquico, sub-presupuestos, **ACU** (Análisis de Costos Unitarios) editable y precios por proyecto.
- **Cronograma** completo estilo MS Project: **Gantt** interactivo con ruta crítica (CPM), Valorizado, **Curva S** y Adquisiciones. Exporta a PDF/Excel/Word/ODT/ODS y **MS Project (MSPDI XML)**.
- **Control de Obra**: requerimientos, almacén/kárdex, cuaderno de obra, valorizaciones y curva S real (programado vs reprogramado vs real).
- **Hoja de Metrados** con soporte de **acero** (diámetros peruanos, NTP 341.031 / ASTM A615).
- **Fórmula polinómica** (D.S. 011-79-VC) e **índices INEI**.
- **13 reportes** consistentes en **PDF · Excel · ODS · Word · ODT**.
- **Importadores nativos**: S10 (`.S2K`), PowerCost (`.prs`), Delphin (`.sqlite`), Excel, IFC y `.db` nativo.
- **Asistente IA (Tuxia)** y **«Sugerir partidas»** con búsqueda semántica local (RAG).

## Instalación

Descárgalo desde **https://ingepresupuestos.com**:

- **Windows** — instalador `.exe`, versión portable, o desde la **Microsoft Store** / `winget install ingepresupuestos`.
- **Linux** — AppImage (Flatpak próximamente).
- **macOS** — próximamente.

## Ejecutar desde el código fuente

Requiere **Python 3.11+**.

```bash
git clone https://github.com/<usuario>/ingepresupuestos-pyside6.git
cd ingepresupuestos-pyside6
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
python3 main.py
```

> **Linux:** para exportar ODT/ODS se usa LibreOffice headless (`sudo apt install libreoffice`). Para importar `.prs` de PowerCost: `sudo apt install -y mdbtools`.

## Tecnología

| Capa | Tecnología |
|------|-----------|
| Interfaz | PySide6 6.11 (Qt 6) |
| Backend | Python 3 puro |
| Base de datos | SQLite 3 |
| Reportes | QTextDocument + QPdfWriter · python-docx · openpyxl · LibreOffice (ODT/ODS) |

## Contribuir

¡Las contribuciones son bienvenidas! Reporta bugs, sugiere mejoras o traduce la app.
Lee [CONTRIBUTING.md](CONTRIBUTING.md) para empezar.

## Apoyar el proyecto

IngePresupuestos es gratis y libre. Si te resulta útil, puedes **apoyarlo**:
- 💛 Yape / donación: https://ingepresupuestos.com/apoyar
- ⭐ Dale una estrella al repositorio y compártelo con colegas.

## Licencia

Distribuido bajo la **Licencia Pública General de GNU v3.0 o posterior (GPL-3.0-or-later)**.
Eres libre de usar, estudiar, modificar y compartir este software; las obras derivadas deben permanecer libres bajo la misma licencia. Ver [LICENSE](LICENSE).

© 2026 Marco Sumari · Sumari SAC
