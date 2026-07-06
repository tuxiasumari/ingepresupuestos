# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""Sistema de internacionalización simple basado en diccionarios.

Uso:
    from utils.i18n import tr
    label.setText(tr("Guardar"))

El idioma activo se lee de configuracion.idioma ('es' | 'en').
Si la clave no tiene traducción, devuelve la clave original (español).
"""

from core.database import get_config

_idioma_actual: str | None = None

# ── Diccionario de traducciones ──────────────────────────────────────────────
# Clave = texto en español (idioma base).  Valor = dict de traducciones.

_TRADUCCIONES: dict[str, dict[str, str]] = {
    # ── Botones comunes ──────────────────────────────────────────────────
    "Guardar": {"en": "Save"},
    "Cancelar": {"en": "Cancel"},
    "Eliminar": {"en": "Delete"},
    "Editar": {"en": "Edit"},
    "Cerrar": {"en": "Close"},
    "Aceptar": {"en": "OK"},
    "Examinar": {"en": "Browse"},
    "Restablecer": {"en": "Reset"},
    "Cambiar": {"en": "Change"},
    "Crear": {"en": "Create"},
    "Buscar": {"en": "Search"},
    "Exportar": {"en": "Export"},
    "Importar": {"en": "Import"},
    "Imprimir": {"en": "Print"},
    "Copiar": {"en": "Copy"},
    "Pegar": {"en": "Paste"},
    "Deshacer": {"en": "Undo"},
    "Rehacer": {"en": "Redo"},
    "Nuevo": {"en": "New"},
    "Abrir": {"en": "Open"},
    "Siguiente": {"en": "Next"},
    "Anterior": {"en": "Previous"},
    "Finalizar": {"en": "Finish"},
    "Aplicar": {"en": "Apply"},
    "Sí": {"en": "Yes"},
    "No": {"en": "No"},

    # ── Navegación / Topbar ──────���───────────────────────────────────────
    "Inicio": {"en": "Home"},
    "Configuración": {"en": "Settings"},
    "Acerca de": {"en": "About"},
    "Nuevo Proyecto": {"en": "New Project"},
    "Biblioteca CU": {"en": "Unit Cost Library"},
    "Insumos": {"en": "Resources"},

    # ── Configuración — tabs ───��─────────────────────────────────────────
    "General": {"en": "General"},
    "IA": {"en": "AI"},
    "Accesibilidad": {"en": "Accessibility"},
    "Idioma": {"en": "Language"},
    "Usuarios": {"en": "Users"},

    # ── Configuración — Card empresa ───────────────────────────��─────────
    "Datos de empresa / profesional": {"en": "Company / professional info"},
    "Estos datos aparecen en el encabezado de los reportes (PDF, Excel, Word).":
        {"en": "This info appears in report headers (PDF, Excel, Word)."},
    "Nombre:": {"en": "Name:"},
    "RUC:": {"en": "Tax ID:"},
    "Dirección:": {"en": "Address:"},
    "Teléfono:": {"en": "Phone:"},
    "Nombre de empresa o profesional": {"en": "Company or professional name"},
    "RUC / DNI": {"en": "Tax ID / National ID"},
    "Dirección": {"en": "Address"},
    "Teléfono / celular": {"en": "Phone / mobile"},
    "Cargar logo": {"en": "Upload logo"},
    "Quitar": {"en": "Remove"},
    "Sin logo": {"en": "No logo"},
    "Datos de empresa guardados": {"en": "Company info saved"},

    # ── Configuración — Card jornada ─────────────────────────────────────
    "Jornada laboral por defecto": {"en": "Default work day"},
    "Horas de la jornada laboral para nuevos proyectos.\n"
    "Se usa en el cálculo: cantidad MO = cuadrilla / rendimiento × jornada.":
        {"en": "Work day hours for new projects.\n"
               "Used in calculation: labor qty = crew / yield × work day."},
    "Jornada:": {"en": "Work day:"},

    # ── Configuración — Card moneda ──────���───────────────────────────────
    "Moneda por defecto": {"en": "Default currency"},
    "Moneda seleccionada automáticamente al crear un proyecto nuevo.":
        {"en": "Currency automatically selected when creating a new project."},
    "Moneda:": {"en": "Currency:"},

    # ── Configuración — Card backups ─────────────────────────���───────────
    "Copias de seguridad": {"en": "Backups"},
    "Se crean automáticamente al iniciar la app (diario) y al cerrarla.\n"
    "Retención: 7 diarios + 10 al cerrar + 10 manuales.":
        {"en": "Created automatically on app start (daily) and on close.\n"
               "Retention: 7 daily + 10 on close + 10 manual."},
    "Hacer backup ahora": {"en": "Backup now"},

    # ── Configuración — Card ruta exportación ────────────────────────────
    "Ruta de exportación por defecto": {"en": "Default export path"},
    "Carpeta donde se guardan los reportes exportados (PDF, Excel, Word).\n"
    "Si está vacío se usa la carpeta de Descargas del sistema.":
        {"en": "Folder where exported reports are saved (PDF, Excel, Word).\n"
               "If empty, the system Downloads folder is used."},
    "Carpeta de descargas del sistema": {"en": "System downloads folder"},

    # ── Configuración — Card decimales ───────────────────────────────────
    "Precisión decimal": {"en": "Decimal precision"},
    "Define cuántos decimales se usan al calcular y mostrar cada parte "
    "del presupuesto (mismo criterio que S10 «Datos Adicionales»).\n"
    "Montos: precios unitarios, parciales y totales. Metrados: metrado "
    "de la partida y planilla. Cantidades: insumos del ACU.\n"
    "Abre de nuevo el proyecto para ver el cambio aplicado.":
        {"en": "Defines how many decimals are used to compute and display each "
               "part of the budget (same criteria as S10 \"Additional Data\").\n"
               "Amounts: unit prices, partials and totals. Takeoff: item "
               "quantity and worksheet. Quantities: unit cost resources.\n"
               "Reopen the project to see the change applied."},
    "Decimales en montos (PU y parciales):": {"en": "Decimals for amounts (UP and partials):"},
    "Decimales en metrados:": {"en": "Decimals for quantity takeoff:"},
    "Decimales en cantidades del ACU:": {"en": "Decimals for unit cost quantities:"},

    # ── Detector PU ≠ ACU ────────────────────────────────────────────────
    "PU consistentes": {"en": "Unit prices consistent"},
    "El precio unitario de todas las partidas coincide con su análisis.":
        {"en": "Every item's unit price matches its cost analysis."},
    "PU distinto a su análisis": {"en": "Unit price differs from analysis"},
    "guardado": {"en": "stored"},
    "{n} partida(s) tienen un PU guardado que NO coincide con la suma "
    "de su análisis de costos.\n\n{detalle}\n\n"
    "⚠ Recalcular cambiaría el Costo Directo en {impacto}.\n"
    "Quitar análisis NO cambia ningún monto del presupuesto.\n\n"
    "• Si el presupuesto se elaboró en ingePresupuestos, lo correcto es "
    "RECALCULAR el PU desde el ACU.\n"
    "• Si viene de una importación antigua con análisis incompletos "
    "(insumos «---» a precio 0), el PU guardado es el del software "
    "origen: conviene QUITAR esos análisis y conservar el PU.":
        {"en": "{n} item(s) have a stored unit price that does NOT match the "
               "sum of their cost analysis.\n\n{detalle}\n\n"
               "⚠ Recalculating would change the Direct Cost by {impacto}.\n"
               "Removing analyses does NOT change any budget amount.\n\n"
               "• If the budget was built in ingePresupuestos, RECALCULATE "
               "the unit price from the analysis.\n"
               "• If it comes from an old import with incomplete analyses "
               "(\"---\" resources at price 0), the stored price is the one "
               "from the source software: REMOVE those analyses and keep it."},
    "Confirmar recálculo": {"en": "Confirm recalculation"},
    "El Costo Directo del proyecto cambiará en {impacto}.\n"
    "Esta acción reemplaza el PU guardado de {n} partida(s).\n\n"
    "¿Recalcular de todas formas?":
        {"en": "The project's Direct Cost will change by {impacto}.\n"
               "This replaces the stored unit price of {n} item(s).\n\n"
               "Recalculate anyway?"},
    "Recalcular PU desde ACU": {"en": "Recalculate UP from analysis"},
    "Quitar análisis (mantener PU)": {"en": "Remove analysis (keep UP)"},

    # ── Configuración — Card apariencia ──────────────────────────────────
    "Apariencia": {"en": "Appearance"},
    "Ajusta el tamaño del texto para monitores pequeños.\n"
    "El cambio se aplica de inmediato; algunos elementos se ven mejor al reiniciar.":
        {"en": "Adjust text size for small monitors.\n"
               "Change applies immediately; some elements look better after restart."},
    "Normal": {"en": "Normal"},
    "Mediano": {"en": "Medium"},
    "Grande": {"en": "Large"},
    "Extra grande": {"en": "Extra large"},

    # ── Configuración — Card barra título ─────���──────────────────────────
    "Barra de título": {"en": "Title bar"},
    "Elige cómo quieres ver la barra superior de la ventana.\n"
    "El cambio se aplica al reiniciar la aplicaci��n.":
        {"en": "Choose how the window title bar looks.\n"
               "Change applies after restarting the app."},
    "Del sistema (recomendada)": {"en": "System (recommended)"},
    "Personalizada (oscura)": {"en": "Custom (dark)"},

    # ── Configuración — Card Tuxia ───────────────────────────────────────
    "Asistente Tuxia": {"en": "Tuxia Assistant"},
    "Ocultar": {"en": "Hide"},
    "Mostrar": {"en": "Show"},

    # ── Configuración — Usuarios ��──────────────────────────────���─────────
    "Administrar usuarios": {"en": "Manage users"},
    "+ Nuevo usuario": {"en": "+ New user"},
    "Nombre": {"en": "Name"},
    "Usuario": {"en": "Username"},
    "Email": {"en": "Email"},
    "Rol": {"en": "Role"},
    "Estado": {"en": "Status"},
    "Creado": {"en": "Created"},
    "Activo": {"en": "Active"},
    "Inactivo": {"en": "Inactive"},
    "Cambiar contraseña": {"en": "Change password"},
    "Activar/Desactivar": {"en": "Enable/Disable"},
    "Nuevo usuario": {"en": "New user"},
    "Editar usuario": {"en": "Edit user"},
    "Nombre completo": {"en": "Full name"},
    "Nombre y apellidos": {"en": "First and last name"},
    "nombre de usuario": {"en": "username"},
    "correo@dominio.com (opcional)": {"en": "email@domain.com (optional)"},
    "mín. 6 caracteres": {"en": "min. 6 characters"},
    "Contraseña": {"en": "Password"},
    "Confirmar contraseña": {"en": "Confirm password"},
    "Nueva contraseña": {"en": "New password"},

    # ── Configuración — Idioma ─────��─────────────────────────────────────
    "Selecciona el idioma de la interfaz.": {"en": "Select the interface language."},
    "Los reportes se mantienen en el idioma del proyecto.":
        {"en": "Reports stay in the project's language."},
    "Idioma aplicado. Reinicia la aplicación para ver el cambio completo.":
        {"en": "Language applied. Restart the app to see the full change."},

    # ── Dashboard ────────────────────────────────────────────────────────
    "Proyectos": {"en": "Projects"},
    "Reciente": {"en": "Recent"},
    "Todos": {"en": "All"},
    "Favoritos": {"en": "Favorites"},
    "Sin proyectos": {"en": "No projects"},
    "Crear tu primer proyecto": {"en": "Create your first project"},
    "Más recientes": {"en": "Most recent"},
    "Cliente": {"en": "Client"},
    "Mosaico": {"en": "Grid"},
    "Lista": {"en": "List"},
    "Quitar de favoritos": {"en": "Remove from favorites"},
    "Marcar como favorito": {"en": "Add to favorites"},
    "Cambiar estado": {"en": "Change status"},
    "Mover a portafolio": {"en": "Move to portfolio"},
    "Sin clasificar": {"en": "Unclassified"},
    "Cambiar color": {"en": "Change color"},
    "Ubicación": {"en": "Location"},
    "Portafolio": {"en": "Portfolio"},
    "Partidas": {"en": "Items"},
    "Fecha": {"en": "Date"},

    # ── Proyecto — tabs principales ────��─────────────────────────────────
    "Presupuesto": {"en": "Budget"},
    "Metrados": {"en": "Quantities"},
    "Especificaciones": {"en": "Specifications"},
    "Resumen": {"en": "Summary"},
    "Fórmula Polinómica": {"en": "Polynomial Formula"},
    "Cronograma": {"en": "Schedule"},

    # ── Proyecto — topbar ─────────────────────────────────────���──────────
    "Archivo": {"en": "File"},
    "Cronogramas": {"en": "Schedules"},
    "Índices": {"en": "Indices"},

    # ── Reportes ───────��───────────────────────────��─────────────────────
    "Reportes": {"en": "Reports"},
    "Vista previa": {"en": "Preview"},
    "Descargar PDF": {"en": "Download PDF"},
    "Descargar Excel": {"en": "Download Excel"},
    "Descargar Word": {"en": "Download Word"},
    "CENTRO DE REPORTES": {"en": "REPORT CENTER"},
    "Tipos de reporte": {"en": "Report types"},
    "Período": {"en": "Period"},
    "Semanal": {"en": "Weekly"},
    "Mensual": {"en": "Monthly"},
    "Papel": {"en": "Paper"},
    "Una sola hoja": {"en": "Single sheet"},
    "Selecciona un reporte": {"en": "Select a report to preview"},
    "Configurar formato": {"en": "Format settings"},
    "Generando vista previa": {"en": "Generating preview"},

    # ── Proyecto — topbar botones ────────────────────────────────────────
    "Editar": {"en": "Edit"},
    "Archivo": {"en": "File"},
    "Fórmula Polinómica": {"en": "Polynomial Formula"},
    "Cronograma": {"en": "Schedule"},
    "Revisar proyecto con IA": {"en": "Review project with AI"},
    "Asistente del proyecto": {"en": "Project assistant"},

    # ── Context menu árbol ────────────────────────────────────────────────
    "Abrir": {"en": "Open"},
    "Duplicar": {"en": "Duplicate"},
    "Cambiar texto": {"en": "Change text"},
    "Agregar partida": {"en": "Add item"},
    "Agregar título": {"en": "Add title"},
    "Reemplazar": {"en": "Replace"},
    "Actualizar catálogo": {"en": "Update catalog"},
    "Renombrar": {"en": "Rename"},
    "Agregar recurso": {"en": "Add resource"},
    "Cortar": {"en": "Cut"},

    # ── Headers de tablas ─────────────────────────────────────────────────
    "Descripción": {"en": "Description"},
    "Cuadrilla": {"en": "Crew"},
    "Cantidad": {"en": "Quantity"},
    "Cantidades": {"en": "Quantities"},
    "Precio": {"en": "Price"},
    "Parcial": {"en": "Subtotal"},
    "Ítem": {"en": "Item"},
    "Metrado": {"en": "Quantity"},
    "Tipo": {"en": "Type"},
    "Área": {"en": "Area"},
    "Largo": {"en": "Length"},
    "Ancho": {"en": "Width"},
    "Alto": {"en": "Height"},
    "Diámetro": {"en": "Diameter"},
    "Longitud": {"en": "Length"},
    "Seleccione una partida": {"en": "Select an item"},
    "METRADO TOTAL:": {"en": "TOTAL QUANTITY:"},
    "TOTAL ACERO:": {"en": "TOTAL STEEL:"},
    "Pegar": {"en": "Paste"},

    # ── Nuevo Proyecto ─────────────────────────────────────────────────────
    "NUEVO PROYECTO": {"en": "NEW PROJECT"},
    "EDITAR PROYECTO": {"en": "EDIT PROJECT"},
    "Información general": {"en": "General information"},
    "Nombre del proyecto": {"en": "Project name"},
    "Sub-presupuesto": {"en": "Sub-budget"},
    "Costo al": {"en": "Cost as of"},
    "Modalidad": {"en": "Modality"},
    "Configuración del proyecto": {"en": "Project settings"},
    "Plazo de obra": {"en": "Duration"},
    "Jornada laboral": {"en": "Work day"},
    "Grupo de análisis": {"en": "Analysis group"},
    "Notas del proyecto": {"en": "Project notes"},
    "opcional": {"en": "optional"},

    # ── Botones toolbar presupuesto ──────────────────────────────────────
    "Partida": {"en": "Item"},
    "Título": {"en": "Title"},
    "Subir": {"en": "Move up"},
    "Bajar": {"en": "Move down"},
    "Subir nivel": {"en": "Promote"},
    "Bajar nivel": {"en": "Demote"},

    # ── Diálogos agregar partida/título ───────────────────────────────────
    "Agregar partida": {"en": "Add item"},
    "Agregar": {"en": "Add"},
    "Biblioteca": {"en": "Library"},
    "Manual": {"en": "Manual"},
    "Grupo": {"en": "Group"},

    # ── Accesibilidad ─────────────────────────────────────────────────────
    "Atajos de teclado": {"en": "Keyboard shortcuts"},
    "Atajos disponibles en la vista de proyecto.": {"en": "Shortcuts available in project view."},

    # ── Tooltips ──────────────────────────────────────────────────────────
    "Recalcular": {"en": "Recalculate"},
    "Generar especificaciones para todas las partidas del proyecto":
        {"en": "Generate specifications for all project items"},
    "Generar especificación con IA para la partida seleccionada":
        {"en": "Generate AI specification for the selected item"},
    "Arrastra para reordenar": {"en": "Drag to reorder"},
    "Activar / desactivar": {"en": "Enable / disable"},
    "Porcentaje": {"en": "Percentage"},
    "Metrado calculado desde la planilla": {"en": "Quantity calculated from spreadsheet"},
    "Doble clic para editar": {"en": "Double-click to edit"},
    "Clic para editar precio · Clic derecho → actualizar catálogo":
        {"en": "Click to edit price · Right-click → update catalog"},
    "Nuevo sub-presupuesto": {"en": "New sub-budget"},
    "Asistente Tuxia — click para abrir el chat":
        {"en": "Tuxia Assistant — click to open chat"},
    "Ocultar menú lateral": {"en": "Hide sidebar"},

    # ── Sidebar ──────────────────────────────────────────────────────────
    "Acerca de": {"en": "About"},
    "Salir": {"en": "Logout"},

    # ── Importar / Exportar ─────────────────────────────────────────────
    "Software de origen": {"en": "Source software"},
    "Formato del archivo": {"en": "File format"},
    "Instrucciones": {"en": "Instructions"},
    "Requerido": {"en": "Required"},
    "Opcional": {"en": "Optional"},
    "Sin archivo seleccionado": {"en": "No file selected"},
    "Seleccionar proyectos": {"en": "Select projects"},
    "Seleccionar todos": {"en": "Select all"},
    "Deseleccionar": {"en": "Deselect all"},
    "Backup completo": {"en": "Full database backup"},
    "Restaurar": {"en": "Restore"},
    "Descargar backup": {"en": "Download backup"},
    "Proyecto": {"en": "Project"},

    # ── Mensajes comunes ─────────────────────────────────────────────────
    "Error": {"en": "Error"},
    "Éxito": {"en": "Success"},
    "Confirmar": {"en": "Confirm"},
    "Cargando...": {"en": "Loading..."},
    "Procesando...": {"en": "Processing..."},
    "Listo": {"en": "Done"},
}


def _get_idioma() -> str:
    global _idioma_actual
    if _idioma_actual is None:
        _idioma_actual = get_config('idioma', 'es')
    return _idioma_actual


def set_idioma(codigo: str):
    """Cambia el idioma en memoria (para la sesión actual tras guardar config)."""
    global _idioma_actual
    _idioma_actual = codigo


def tr(texto: str) -> str:
    """Traduce un texto. Si no hay traducción o el idioma es 'es', devuelve el original."""
    idioma = _get_idioma()
    if idioma == 'es':
        return texto
    entry = _TRADUCCIONES.get(texto)
    if entry and idioma in entry:
        return entry[idioma]
    return texto
