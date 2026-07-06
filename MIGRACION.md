# Plan de Migración Flask → PySide6

## Estado actual

| Módulo | Flask (original) | PySide6 (nuevo) | Estado |
|--------|-----------------|-----------------|--------|
| Base de datos | `database.py` | `core/database.py` (copia) | ✅ Copiado |
| Exportación | `exporter.py` | `core/exporter.py` (copia) | ✅ Copiado |
| Importación | `importer.py` | `core/importer.py` (copia) | ✅ Copiado |
| Importar PDF | `pdf_importer.py` | `core/pdf_importer.py` (copia) | ✅ Copiado |
| Importar IFC | `ifc_importer.py` | `core/ifc_importer.py` (copia) | ✅ Copiado |
| IA specs | `ai_specs.py` | `core/ai_specs.py` (copia) | ✅ Copiado |
| Configuración | constantes en `app.py` | `core/config.py` | ✅ Listo |
| Autenticación | Flask-Login | `utils/auth.py` | ✅ Listo |
| Formato moneda | JS `fmt()`/`parseFmt()` | `utils/formatting.py` | ✅ Listo |
| Login / Setup | `login.html` / `setup.html` | `views/login_dialog.py` / `views/setup_dialog.py` | ✅ Esqueleto |
| Dashboard (inicio) | `index.html` | `views/dashboard_view.py` | ✅ Funcional |
| Ventana principal | `base.html` + sidebar | `views/main_window.py` | ✅ Esqueleto |
| Vista de proyecto | `proyecto.html` | `views/proyecto_view.py` | 🔨 En progreso |
| Tabla ACU | panel JS en `proyecto.html` | `widgets/acu_table.py` | 🔨 Esqueleto |
| Insumos totales | panel JS en `proyecto.html` | `widgets/insumos_table.py` | 🔨 Esqueleto |
| Recursos/Catálogo | `recursos.html` | `views/recursos_view.py` | ⬜ Pendiente |
| Metrados | `metrados.html` | `views/metrados_view.py` | ⬜ Pendiente |
| Cronograma Gantt | `cronograma.html` | `views/cronograma_view.py` | ⬜ Pendiente |
| Fórmula polinómica | `formula_polinomica.html` | `views/formula_view.py` | ⬜ Pendiente |
| Pie de presupuesto | `pie_presupuesto.html` | `views/pie_view.py` | ⬜ Pendiente |
| Especificaciones | `especificaciones.html` | `views/especificaciones_view.py` | ⬜ Pendiente |
| Biblioteca CU | `biblioteca.html` | `views/biblioteca_view.py` | ⬜ Pendiente |
| Importar | `importar.html` | `views/importar_view.py` | ⬜ Pendiente |
| Exportar | `exportar.html` | `views/exportar_view.py` | ⬜ Pendiente |
| Configuración | `configuracion.html` | `views/configuracion_view.py` | ⬜ Pendiente |
| Usuarios | `usuarios.html` | ⬜ Pendiente |
| Calendario | `calendario.html` | `views/calendario_view.py` | ⬜ Pendiente |

## Orden de implementación recomendado

### Fase 1 — Core funcionando (hacer primero)
1. **`views/proyecto_view.py`** — árbol de partidas completo con CRUD
2. **`widgets/acu_table.py`** — edición de items ACU (cuadrilla, cantidad, precio)
3. **`views/proyecto_form_dialog.py`** — formulario nuevo/editar proyecto

### Fase 2 — Vistas de edición
4. **`views/recursos_view.py`** — catálogo de insumos con INEI dropdown
5. **`widgets/insumos_table.py`** — panel inferior insumos totales
6. **`views/metrados_view.py`** — tabla de metrados detalle

### Fase 3 — Vistas analíticas
7. **`views/cronograma_view.py`** — Gantt (usar `QGraphicsScene` o `QChartView`)
8. **`views/pie_view.py`** — pie de presupuesto con gastos generales
9. **`views/formula_view.py`** — fórmula polinómica INEI

### Fase 4 — Importación / Exportación
10. **`views/importar_view.py`** — wizard de importación (wrappear `core/importer.py`)
11. **`views/exportar_view.py`** — diálogo de exportación (wrappear `core/exporter.py`)

### Fase 5 — Administración
12. **`views/configuracion_view.py`** — clave API IA, sheet_url, etc.
13. **`views/usuarios_view.py`** — CRUD de usuarios con roles

## Notas críticas de migración

### Precios por proyecto
- `acu_items.precio` tiene prioridad sobre `recursos.precio`
- Siempre usar `COALESCE(ai.precio, r.precio, 0)` en todas las queries
- Al cambiar precio en un proyecto → actualizar TODOS los items del mismo `recurso_id`

### Cantidad MO en ACU
```python
cantidad_MO = (cuadrilla / rendimiento) * jornada_laboral
```

### Unidades overhead
- `r.unidad` que empieza con `%` → `precio = 0` siempre
- En queries de insumos: `SUBSTR(r.unidad, 1, 1) != '%'` (nunca `NOT LIKE '%%%'`)

### Cronograma
- `cronograma_partidas` tiene `UNIQUE(partida_id)` → usar `INSERT OR REPLACE`
- `(dur or 0) > 0` porque `dur` puede ser `None`

### sqlite3.Row
- No tiene `.get()` → usar `row['campo'] or valor_default`

## Dependencias nuevas a instalar

```bash
cd /home/sumaritux/ingepresupuestos-pyside6
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Ejecutar

```bash
source venv/bin/activate
python main.py
```
