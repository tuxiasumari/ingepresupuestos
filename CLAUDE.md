# IngePresupuestos

App de escritorio PySide6 (Qt 6) multiplataforma para la elaboración de **presupuestos de obra** (ingeniería y arquitectura): análisis de costos unitarios (ACU), cronograma Gantt valorizado con ruta crítica (CPM), metrados (incluido acero), fórmula polinómica e índices INEI, Control de Obra y 13 reportes profesionales.

**Autor:** Ing. Marco Sumari · **Software libre — GPL-3.0-or-later** · Versión actual: **2.8.4**

> Software libre y gratuito desde 2.8.0: todas las funciones incluidas. El sistema de licencia es **vestigial** (`core/licencia.py::puede_premium()` → `True`; queda como limpieza opcional). El changelog detallado vive en `git log`.

Repo: `github.com/ingelibre/ingepresupuestos` · Web: `ingepresupuestos.com` · Docs: `docs.ingepresupuestos.com`

---

## Entorno

```bash
# Python 3.12+ · PySide6 6.x
cd /home/sumaritux/ingepresupuestos
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python3 main.py          # o ./iniciar.sh   (Wayland: INGEPPTO_FORCE_XCB=1 fuerza xcb)
```

Tests sin GUI (usan copia temporal de `presupuestos_seed.db`, nunca la BD activa):
```bash
QT_QPA_PLATFORM=offscreen venv/bin/python3 tests/test_reglas_negocio.py   # reglas de negocio
venv/bin/python3 tests/test_core.py
# también: test_almacen.py · test_curva_s.py · test_valorizacion.py
```

---

## Arquitectura

| Capa | Tecnología | Carpeta |
|------|-----------|---------|
| UI | PySide6 6.x (Qt 6) + QtPdf/QtPdfWidgets | `views/`, `widgets/` |
| Backend | Python 3 puro | `core/`, `utils/` |
| BD | SQLite 3 (`presupuestos.db`) | — |
| Reportes PDF | QTextDocument + QPdfWriter + QPainter | `core/pdf_reports.py` |
| Reportes Word | python-docx | `core/word_reports.py` |
| Reportes ODT/ODS | LibreOffice headless (conversión) | `core/odt_reports.py`, `core/ods_reports.py`, `core/soffice.py` |
| Excel | openpyxl | `core/exporter.py` |
| Importación | openpyxl + xlrd + pdfplumber + mdbtools/pyodbc | `core/importer.py` y siblings |
| IA (opcional) | Anthropic/Groq/OpenRouter/Gemini/OpenAI/Ollama | `core/ai_specs.py` |
| Fuzzy / RAG | rapidfuzz + model2vec int8 (sin PyTorch) | `core/asistente_local.py`, `core/biblioteca_embeddings.py` |
| Empaquetado | PyInstaller 6 + GitHub Actions | `ingepresupuestos.spec`, `.github/workflows/` |

Rutas (`core/config.py`): `BASE_DIR` (read-only; bajo PyInstaller = `_internal/`), `USER_DATA_DIR` (Linux `~/.local/share/ingepresupuestos/`, Windows `%APPDATA%/ingepresupuestos/`, macOS `~/Library/Application Support/…`), `DB_PATH = USER_DATA_DIR/presupuestos.db`. `_sembrar_db_si_falta` copia el seed solo si la BD no existe.

`main.py` NO procesa `sys.argv` para abrir un archivo pasado (la asociación de `.db` es solo cosmética — ver abajo).

---

## Reglas críticas de negocio (NO romper)

```python
# Precios por proyecto — siempre COALESCE
COALESCE(ai.precio, r.precio, 0)

# Cantidad MO en ACU — y equipo por hora (unidad hh/hm): se DERIVA de la cuadrilla.
#   Helper proyecto_view._recurso_por_hora(tipo, unidad) (también en recurso_selector_dialog).
cantidad = (cuadrilla / rendimiento) * jornada_laboral
# MO/EQ por DÍA (unidad día/jor): cuadrilla habilitada pero SIN jornada →
#   cantidad = cuadrilla / rendimiento   (rendimiento ya es por día). Helper _recurso_por_dia.
# EXCEPCIÓN — partida GLOBAL (unidad glb/gbl/est/serv, como PowerCost): sin cuadrilla;
#   cantidad y precio directos en TODOS los insumos (incluida MO). Helper _partida_global(unidad);
#   flag _acu_partida_global seteado en cargar_acu.

# Decimales — 3 claves GLOBALES en tabla `configuracion` (estilo S10 «Datos Adicionales»):
#   decimales_presupuesto (montos PU/parciales, def 2) · decimales_metrado (def 2)
#   · decimales_cantidad_acu (def 4). Getters en core/database.py.
# parcial_wysiwyg redondea el metrado a decimales_metrado y el monto a decimales_presupuesto.

# Pie de presupuesto
Total = cantidad * (%part/100) * precio

# Overhead (%MO / %MAT) — parcial REAL en get_acu_items (segunda pasada).
#   DEBE aparecer en Insumos y Adquisiciones. NO filtrar con SUBSTR != '%'.

# sqlite3.Row NO tiene .get()  →  row['col'] or default

# Cronograma — UNIQUE(partida_id) → INSERT OR REPLACE; dur puede ser None: (dur or 0) > 0
# Duración tarea Gantt = ⌈metrado / rendimiento⌉  (rendimiento = producción/día del ACU)
```

**Coherencia de totales:** `calcular_totales(pid)` → `(items, {cd, gf, utilidad, subtotal, igv, total})`. **Presupuesto Total = `total`** (CD+GG+Utilidad+IGV), NO solo CD. Param `all_subs=True` para totales project-wide (Resumen/Pie).

**Funciones clave `core/database.py`:** `_r2`, `get_db()` (Row + FK ON), `calcular_totales`, `_recalcular_pu` / `_pu_desde_items`, `get_acu_items` (retorna `(items, totales_tipo)`), `get_insumos_proyecto` / `get_insumos_para_partidas` (distribución proporcional al CD), `parcial_wysiwyg`, `precios_inconsistentes` / `unificar_precio_recurso`, `partidas_pu_inconsistente` (detector PU≠ACU), `_orden_mo` (Capataz<Operario<Oficial<Peón).

---

## Sistema de diseño — `utils/theme.py`

Tokens centralizados. **NO hardcodear hex.**
- Paleta: `C.brand = '#F37329'` (naranja). Tipos recurso: MO `#F39C12` · MAT `#27AE60` · EQ `#607D8B` · SC `#7A36B1`.
- Niveles de título (`NIVEL_ESTILO`): N1 rojo `#B71C1C`, N2 arándano `#0D52BF`, N3 morado `#6A1B9A`, N4 rosa `#AD1457`.
- `accent_color(*, on_dark=False)` = acento ambiental (topbars); NO en CTAs/focus (esos siempre naranjas). `accent_reportes()` → `('#273445','#1F2A38','#F1F5F9')`.
- **Modo sobrio es el único modo** — no reintroducir toggles de tema.
- Fuente **Inter** estática (NO Variable) bundleada en `resources/fonts/`, auto-instalada system-wide (`core/fonts_installer.py`).

---

## Reportes (PDF · Excel · ODS · Word · ODT)

- **PDF:** HTML → `QTextDocument.setHtml()` → `drawContents()` → `QPdfWriter`; header/pie/portada en `QPainter`.
- **Word:** python-docx; header/footer tabla 1×3 con NUMPAGES; `_set_table_fixed_layout` obligatorio.
- **Excel:** openpyxl; pie tripartito `oddFooter`; **Excel = PDF visible, no PDF CSS**.
- **ODT/ODS:** se genera el `.docx`/`.xlsx` nativo y se convierte con **LibreOffice headless** (`core/soffice.py`). Sin LibreOffice → aviso, sin crash.

### QTextDocument — gotchas
- `<table width="100%">` como **atributo HTML** (CSS solo no basta). NO soporta SVG (generar PNG con QPainter). NO centra `<table align=center>` (dibujar con QPainter).
- Selectores Qt CSS no aceptan `_` → usar `#objectName`. `QPainter.setRenderHint`: atributo de la CLASE.
- **Sangría en celda: NO `padding-left`/`margin-left`** (los ignora) → tabla-espaciador anidada, o `Alignment(indent=N)` en Excel. Profundidad = `item.count('.') - min_dots`.
- **Divisorias verticales: NO `border-left/right`** (entrecortadas) → columna-espaciador con `background`, ancho como atributo `width`. Verificar renderizando el PDF headless.

### Centro de Reportes — `views/reportes_view.py`
Anclada al `_root_stack`. Reporte Completo = merge `pypdf` + numeración global 2-pass; secciones configurables (casillas + tarjetas reordenables por arrastre; persistencia por proyecto en QSettings). Papel default A4; **Gantt** usa pipeline propio (auto A4→A0).
- **LibreOffice en Flathub:** los botones ODT/ODS/Pack-LibreOffice se ocultan cuando `core.soffice.odf_export_ofrecible()` es False (edición Flatpak sin LibreOffice del host). En instalación nativa sin LibreOffice quedan visibles con aviso de instalación.

---

## Vista de proyecto — `views/proyecto_view.py`

Topbar (← Inicio · pestañas · Total) + toolbar + `QSplitter` H/V. Panel derecho con pestañas **ACU · Insumos · Metrados · Especificaciones · Resumen · Memoria**.
- Layout responsivo: `< 1050` oculta ACU. NUNCA dos `resizeEvent` en la misma clase.
- Panel ACU: cabeceras MO/MAT/EQ/SC con `_acu_row_ids[row]==-1` → saltar en edit/menu/delegate.
- Vistas ancladas al `_root_stack` (NO diálogos): Pie, Cronograma, Reportes, Metrados, Fórmula, Memoria Descriptiva.
- **Panel Metrados/Acero:** solo se recarga cuando su pestaña está visible. Recuerda su partida dueña en `_met_panel_pid`; los 4 caminos de guardado (acero/metrados, silencioso/explícito) escriben SIEMPRE a `_met_panel_pid`, nunca a la partida seleccionada en el árbol (si difieren, evitaba copiar la planilla a otra partida).

---

## Cronograma + Fórmula + INEI

- **CPM** forward+backward+ruta crítica; dependencias FS/FF/SS/SF con lag y pct; hitos.
- **Numeración "#" y filas virtuales (estilo MS Project)** — el "#" numera TODAS las filas posicionalmente (`core/cronograma.py`); DEBE coincidir con las predecesoras. `_partidas` se carga AGRUPADO por subpresupuesto; cambiar orden/inserción rompe la numeración (prever migración).
- **Fórmula Polinómica:** `calcular_desde_acu(pid)` auto-deriva J/M/E. NO aplica en admin. directa. Validaciones D.S. 011-79-VC.
- **INEI:** 72 códigos × 6 áreas, auto-detección por HEAD requests.
- **Export MS Project (MSPDI XML):** formato abierto (abre en ProjectLibre/GanttProject). Reglas críticas: `Manual=0` (sin esto → duración 0), NO emitir `Finish`/`ManualFinish`; tareas sin predecesora → SNET; `id` incrustado en Text29 «IngeID».

---

## Control de Obra — `views/control_obra_view.py` + `core/{valorizacion,parte_diario,almacen,curva_s,requerimientos}.py`

Vista anclada al `_root_stack`, botón «Control de Obra» en el topbar tras Cronogramas. Pestañas del flujo de obra: **Requerimientos · Almacén · Cuaderno · Valorizaciones · Curva S real** (Liquidación oculta para versión futura). Reportes generados DESDE la vista (no en el Centro de Reportes). Tests: `test_{valorizacion,almacen,curva_s}.py`.
- **Valorizaciones:** solo LEEN del presupuesto/ACU. Dato base = `metrado_periodo`; todo lo demás deriva en `valorizacion.get_valorizacion_detalle`. 2 tablas (`valorizaciones` + `valorizacion_detalle`, origen `manual`|`diario`). Cerrada = no editable.
- **Almacén:** kárdex de MATERIALES (Pedido/Ingresado/Consumido/Stock/Por llegar) + entradas con fecha + kárdex por día.
- **Curva S:** programado vs reprogramado vs real; denominador = presupuesto contractual; cortes semana/mes/mes_cal.
- **Cuaderno/parte diario:** metrado ejecutado por día; push parte→valorización (`metrado_periodo = Σ metrado_dia` en el rango); celda de valorización solo-lectura cuando `origen='diario'`.

---

## Importadores nativos peruanos — `views/importar_view.py` + `core/*_importer.py`

| Software | Formato | Soporte |
|----------|---------|---------|
| Delphin Express | `.sqlite` | ✅ proyecto + biblioteca + INEI |
| PowerCost | `.prs` | ✅ mdbtools (Linux) / pyodbc+access_parser (Windows) |
| S10 | `.S2K` / `.bak` / `.bkf` | ✅ vía IngeConverter (complemento externo gratuito) |
| PowerCost/S10/Delphin | `.xlsx` | ✅ |
| BIM | `.ifc` | ✅ |
| IngePresupuestos | `.db` | ✅ ATTACH DATABASE |

**Patrones críticos:**
- `.prs` con contraseña: fallback a `access_parser` + monkey-patch. Sub-análisis (`IdSubAnalisis≠0`) → SC con precio = CU recursivo. Numeración de ítems JERÁRQUICA por posición de hermano (NO usar `TxItem`/`IdItem`). Validado con bases reales; test `test_importador_prs_reconcilia`.
- **`.prs` bajo Flatpak:** `core/powercost_prs_importer.py` prefiere el `mdb-export` LOCAL (`shutil.which`) — embebido en `/app/bin` en la edición Flathub, o del sistema en nativo — y solo usa `flatpak-spawn --host` si no hay binario local (edición sideload). En Flathub `flatpak-spawn --host` está bloqueado, así que enrutar al host rompería la importación.
- Reúso de insumos por `(tipo, desc, unidad)` aunque cambie el código (el precio NO se comparte). Al importar, el pie se siembra TODO desactivado.

---

## Distribución + Backups + Update

**Empaquetado** (`ingepresupuestos.spec` + `.github/workflows/`): tag `vX.Y.Z` → workflows Linux+Windows → binarios (Win installer+portable, Linux AppImage+tar.gz) publicados en GitHub Releases y subidos a Cloudflare R2 (`downloads.ingepresupuestos.com/vX.Y.Z/`) + `version.json` regenerado (feed del auto-updater). `CURRENT_VERSION` en `core/update_manager.py` lo bumpea `release.sh`. Al agregar un paquete pip: `requirements.txt` + `hiddenimports` en el `.spec`.

**Canales:**
- **GitHub Releases + R2** — automático en cada tag.
- **winget** (`installer/winget/`, `MarcoSumari.IngePresupuestos`, `InstallerType: inno`) — publicado. `.github/workflows/publish-winget.yml` (winget-releaser) abre el PR a `microsoft/winget-pkgs` en cada Release; requiere el secret `WINGET_TOKEN`.
- **Microsoft Store (MSIX)** (`installer/msix/package-msix.ps1`) — el `.msix` se genera en el build Windows y queda como **artifact privado** (`ingepresupuestos-msix`, retención 90 días); NO se publica en R2 ni en Releases. Se sube A MANO a Partner Center (sin firmar; Microsoft firma). Empaquetado vía mapping file (`/f`) excluyendo `docx/templates/...` (nombres OPC reservados que rompían `makeappx` con `0x8007007b`).
- **Flathub** (`installer/flathub/`) — edición separada: base-app `io.qt.PySide.BaseApp` sobre `org.kde.Platform`, deps Python offline, mdbtools embebido, SIN escape al host → ODT/ODS deshabilitados (PDF/Word/Excel son nativos). `x-checker-data` en la fuente → el bot de Flathub propone las nuevas versiones. El manifiesto y sus archivos deben ir a la raíz de la rama del PR (contra `new-pr`).
- **Edición Flatpak sideload** (`installer/flatpak/`) — COMPLETA (usa el host para ODT/ODS vía `flatpak-spawn`). NO mezclar con la de Flathub.

**Asociación de archivos `.db`** — icono de documento branded (hoja + badge naranja, estilo Office). **Cosmético**: da personalidad al icono, no abre nada. Windows: ProgID en `installer/ingepresupuestos.iss` (`ChangesAssociations=yes`). Linux: MIME propio `application/x-ingepresupuestos-db` (`resources/mime/`) que reclama `*.db`; iconos hicolor en `resources/icons/hicolor/` (bundleados por globs en el `.spec` — una tupla de directorio NO los empaqueta) + registro en `install-linux.sh`. Fuente vectorial: `resources/icons/mimetypes/ingepresupuestos-db.svg` (render con Inkscape + Pillow; sin filtros SVG porque Inkscape headless descarta los grupos con `feDropShadow`).

**Firma de código Windows:** el `.exe` NO está firmado → SmartScreen muestra «editor desconocido» (winget y Store vienen firmados por Microsoft, sin aviso). Fix real = firmar (pendiente cert gratis de SignPath Foundation para OSS). Reportar el `.exe` a SmartScreen es por-archivo, no una cura.

**Backups:** atomic `sqlite3.Connection.backup()`. Retención daily(7) · on-exit(10) · manual(10).

**Ícono producto** (`ingepresupuestos.png/.ico`) ≠ **Tuxia** (asistente IA). NO mezclar.

---

## Gotchas críticos (no repetir)

**Delegates / tablas:** `self.parent()` en delegates = padre del constructor (pasar `self` explícito). `setModelData` que recarga tabla → `QTimer.singleShot(0, …)`. Filas-cabecera ACU (`_acu_row_ids[row]==-1`): saltar.

**Stylesheet:** `QWidget { background: X }` afecta a TODOS los descendientes → `setObjectName` + `#foo` + `Qt.WA_StyledBackground`. `QLabel` con `setStyleSheet` parcial → siempre `background:transparent; border:none;`. Botones circulares: subclasear + `paintEvent` (el QSS cascade pisa `border-radius` tras hide/show). `::indicator` con QSS propio: usar `border`+`background` sólidos (no SVG semitransparente, invisible en Linux/Win).

**Layouts:** `layout.takeAt(0)` solo desconecta → `item.widget().setParent(None); deleteLater()`.

**Wayland:** `self.move()` no funciona → `startSystemMove()` diferido a mouseMoveEvent. Fractional scaling Qt 6.11: `INGEPPTO_FORCE_XCB=1`.

**QDialog + QThread:** override `done()`, NO `closeEvent`. Workers QThread: `parent=self`.

**Metrados:** `tree.blockSignals(True)` durante el guardado silencioso. Metrado manual inline vs planilla: limpiar `tbl_met`/`tbl_acero` si muestran esa partida (el guard `_met_tiene_datos()`/`_acero_tiene_datos()` corta el re-guardado que borraría el valor manual). Acero: `orden` secuencial al guardar (saltar filas en blanco); diámetro asume pulgadas sin comilla (`_normalizar_diametro_acero`).

**Dashboard 400+ proyectos:** cards/celdas **pintadas a mano** con QPainter (1 widget c/u, no ~15 sub-widgets/card) + hit-testing; caché de totales `_tot_cache` (NUNCA `calcular_totales` por card) con cálculo diferido en lotes; sin scrollbar horizontal.

---

## Convenciones rápidas

- **Diálogos modales:** `setWindowModality(Qt.WindowModal)` (NO `setModal(True)`); mejor anclar al `_root_stack`.
- **Iconografía:** SVGs elementary OS vía `utils/icons.py::icon("alias")`. NO emojis para UI.
- **Árboles: padre por prefijo de ítem SIEMPRE con dict ítem→nodo** (O(1); iterar es O(n²)).
- **ProyectoView abre en 2 etapas:** pestaña visible con árbol → `_completar_panel_tabs` (30 ms después). NO acceder a widgets del panel tabs antes de esa cadena.
- **`QT_SCALE_FACTOR`** leído ANTES de `QApplication()`. Stylesheet global + Inter registrados en `main.py` antes de las ventanas.
- **Migraciones:** `ALTER TABLE ADD COLUMN` en try/except dentro de `init_db()`.

---

## Monedas · Auth · Estados · IA · i18n

- **Monedas/formato** (`config.py`, `utils/formatting.py`): `fmt`/`fmt_num`/`parse_num` (`.` y `,`)/`pad_codigo`/`norm_busqueda`.
- **Auth** (`utils/auth.py`): roles admin·usuario·invitado; primer usuario = admin.
- **Estados:** solo `elaboracion` es editable; `_require_editable(nivel)`.
- **IA (opcional, `core/ai_specs.py`):** 6 proveedores (clave del usuario). Specs/rendimiento por partida; validar_proyecto, memoria descriptiva. Override `done()` en diálogos IA.
- **«Sugerir partidas» (RAG):** la IA arma la estructura, la biblioteca/proyectos ponen los costos. Fase 1 fuzzy + Fase 2 semántica (`core/biblioteca_embeddings.py`, model2vec int8, sin PyTorch), fusión RRF; el modelo se baja de R2 al build (si falta, degrada a fuzzy). Corre en QThread.
- **i18n** (`utils/i18n.py`): `tr("texto español")`, importar dentro del método. Cobertura parcial.
- **Contacto** (`worker/contacto.js`): POST → Cloudflare Worker → Resend. User-Agent `IngePresupuestos/X.Y.Z` obligatorio.
