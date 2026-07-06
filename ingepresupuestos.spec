# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec para ingePresupuestos.

Genera:
- Linux: dist/ingepresupuestos/  (carpeta con el binario + libs)
- Windows: dist\\ingepresupuestos\\  (carpeta con ingepresupuestos.exe + DLLs)
- macOS: dist/ingepresupuestos.app  (bundle)

Build:
    venv/bin/pyinstaller ingepresupuestos.spec --noconfirm  (Linux/macOS)
    venv\\Scripts\\pyinstaller.exe ingepresupuestos.spec --noconfirm  (Windows)

El mismo .spec funciona en las 3 plataformas — PyInstaller maneja los
formatos por plataforma automáticamente. Solo `console=False` y el icon
son específicos del SO.
"""
import sys
from pathlib import Path

block_cipher = None

# Repo root (donde está el .spec). Usamos Path absoluto para que funcione
# cualquiera sea el CWD desde el que se invoque pyinstaller.
ROOT = Path(SPECPATH).resolve()

# ── Assets que se bundlean dentro del ejecutable ─────────────────────────────
# Cada tupla = (origen_relativo_al_repo, destino_relativo_al_bundle).
datas = [
    ('resources/icons/elementary/24/*.svg',  'resources/icons/elementary/24'),
    ('resources/icons/elementary/24/*.png',  'resources/icons/elementary/24'),
    ('resources/icons/elementary/24/*.ico',  'resources/icons/elementary/24'),
    # Íconos raíz referenciados por el QSS global (check.svg, arrow_down.svg,
    # radio_slate_on.svg…): sin esto los indicadores de checkbox/combo/radio
    # salían como cuadraditos negros en el binario empaquetado.
    ('resources/icons/*.svg',                'resources/icons'),
    ('resources/fonts/*.ttf',                'resources/fonts'),
    ('resources/fonts/*.woff2',              'resources/fonts'),
    ('resources/fonts/*.json',               'resources/fonts'),
    ('resources/styles/*.qss',               'resources/styles'),
    ('presupuestos_seed.db',                 '.'),
    ('ingepresupuesto-icon.svg',             '.'),
    # Clave pública para verificar firmas de licencias. La privada NUNCA
    # se incluye (vive solo en la máquina de Marco).
    ('resources/license_public.pem',         'resources'),
    # Base UBIGEO del Perú (INEI) para autocompletar la ubicación.
    ('resources/ubigeo_peru.json',           'resources'),
    # Mapa QML (QtLocation/OSM) para marcar la ubicación del proyecto.
    ('resources/map.qml',                    'resources'),
    # Repositorio de proveedores de tiles propio (calle OSM + satélite Esri,
    # sin API key). Reemplaza el servicio hospedado de Qt, ya descontinuado.
    ('resources/osm_providers/street',       'resources/osm_providers'),
    ('resources/osm_providers/satellite',    'resources/osm_providers'),
]

# ── Hidden imports ───────────────────────────────────────────────────────────
# Módulos que PyInstaller no detecta automáticamente (importados dinámicamente
# o vía strings). Si más adelante hay ModuleNotFoundError en runtime,
# agregar aquí.
hiddenimports = [
    # Módulos internos referenciados por import perezoso (dentro de funciones) —
    # PyInstaller normalmente los detecta, pero se listan por seguridad.
    'core.plantillas_estructura',
    # Proveedores IA — se importan dinámicamente según la config del usuario.
    'anthropic',
    'groq',
    'openai',
    'google.genai',
    # PySide6 submódulos que a veces no entran en el grafo de imports.
    'PySide6.QtPdf',
    'PySide6.QtPdfWidgets',
    'PySide6.QtSvg',
    'PySide6.QtSvgWidgets',
    'PySide6.QtPrintSupport',
    # Manejo de docs / spreadsheets / PDF
    'openpyxl',
    'docx',
    'pdfplumber',
    'xlrd',
    'pypdf',
    'reportlab',
    # ODF (odfpy) — submódulos usados por core/odt_reports.py + ods_reports.py
    'odf',
    'odf.opendocument',
    'odf.style',
    'odf.text',
    'odf.table',
    'odf.draw',
    'odf.office',
    # Otros
    'rapidfuzz',
    'werkzeug',
    'PIL',
    'PIL.Image',
    # Sistema de licencias premium — RSA-PSS verify.
    'cryptography',
    'cryptography.hazmat.primitives.serialization',
    'cryptography.hazmat.primitives.asymmetric.padding',
    'cryptography.hazmat.primitives.hashes',
    # ODBC — lectura de .prs (PowerCost MS Access) en Windows.
    'pyodbc',
    # Fallback para .prs con contraseña (lee MDB sin ODBC).
    'access_parser',
    # Mapa de ubicación (resources/map.qml): QtLocation y QtPositioning se
    # importan SOLO desde el QML, nunca desde Python → PyInstaller no los ve por
    # análisis estático y no los bundlearía. Forzarlos aquí dispara sus hooks
    # (add_qt6_dependencies), que traen los .dll Qt6Location/Qt6Positioning y los
    # módulos QML. Sin esto el mapa carga con error en el binario. Ver más abajo
    # el bundle explícito del plugin de geoservicios.
    'PySide6.QtLocation',
    'PySide6.QtPositioning',
    'PySide6.QtQml',
    'PySide6.QtQuick',
    # RAG Fase 2 — model2vec (embeddings estáticos, sin PyTorch) + sus deps que
    # se cargan dinámicamente. El modelo se bundlea como data (ver más abajo).
    'model2vec',
    'model2vec.model',
    'tokenizers',
    'safetensors',
    'huggingface_hub',
]

# ── Plugins/QML del mapa que PyInstaller no recolecta solo ───────────────────
# El plugin Qt de geoservicios (proveedor 'osm', qtgeoservices_osm.{dll,so}) NO
# está en el mapeo automático de PyInstaller (no se asocia al módulo QtLocation),
# así que hay que copiarlo a mano junto con los módulos QML del mapa.
#
# OJO con el layout del wheel, que difiere por plataforma:
#   • Windows: los recursos Qt cuelgan directo de PySide6/  (PySide6/plugins, PySide6/qml)
#   • Linux/macOS: cuelgan de PySide6/Qt/  (PySide6/Qt/plugins, PySide6/Qt/qml)
# El destino en el bundle debe ESPEJAR esa ruta relativa (es donde apunta el
# qt.conf generado). Antes se asumía siempre PySide6/plugins → en Linux el
# `if exists()` saltaba todo en silencio y el AppImage cargaba el mapa con error.
# Derivar el destino de la ruta real evita ese sesgo de plataforma.
import PySide6 as _pyside6
_PS6 = Path(_pyside6.__file__).resolve().parent
_QT_BASE = (_PS6 / 'Qt') if (_PS6 / 'Qt').is_dir() else _PS6   # Linux/macOS vs Windows
for _sub in (
    'plugins/geoservices',   # qtgeoservices_osm.{dll,so} (proveedor de tiles)
    'plugins/position',      # plugins de posicionamiento (por si QtPositioning los pide)
    'qml/QtLocation',
    'qml/QtPositioning',
):
    _src = _QT_BASE / _sub
    if _src.exists():
        # 'PySide6/plugins/geoservices' en Win · 'PySide6/Qt/plugins/geoservices' en Linux
        datas.append((str(_src), str(Path('PySide6') / _src.relative_to(_PS6))))

# ── Modelo de embeddings RAG Fase 2 (model2vec int8, ~147 MB) ────────────────
# Gitignored: en el build se baja de R2 a resources/models/ ANTES de PyInstaller
# (ver el step "Descargar modelo RAG" en los workflows + RELEASE_CHECKLIST). Si
# no está, el bundle sale sin él y la app degrada a fuzzy (Fase 1) — no rompe.
_modelo_rag = ROOT / 'resources' / 'models' / 'potion-multilingual-128M'
if _modelo_rag.is_dir():
    datas.append((str(_modelo_rag), 'resources/models/potion-multilingual-128M'))

# ── Exclusiones — reducen tamaño del binario ────────────────────────────────
excludes = [
    'tkinter',          # no usado, viene con Python por defecto
    'matplotlib',       # no usado
    'numpy.tests',
    'pandas',           # no usado
    'IPython',
    'jupyter',
]

a = Analysis(
    ['main.py'],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# Ícono por plataforma. PyInstaller acepta .ico (Windows), .icns (macOS),
# .png (cualquier plataforma). Usamos .svg → si falla en build, generamos
# .ico/.icns aparte. Por ahora, sin ícono específico para evitar fallos.
icon = None
if sys.platform == 'win32':
    win_ico = ROOT / 'resources' / 'icons' / 'elementary' / '24' / 'ingepresupuestos.ico'
    if win_ico.exists():
        icon = str(win_ico)
elif sys.platform == 'darwin':
    mac_icns = ROOT / 'resources' / 'icons' / 'elementary' / '24' / 'ingepresupuestos.icns'
    if mac_icns.exists():
        icon = str(mac_icns)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ingepresupuestos',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                  # UPX comprime pero a veces rompe PySide6
    console=False,              # False = sin terminal (app GUI)
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='ingepresupuestos',
)

# ── macOS .app bundle (solo si compilamos en macOS) ──────────────────────────
if sys.platform == 'darwin':
    app = BUNDLE(
        coll,
        name='ingepresupuestos.app',
        icon=icon,
        bundle_identifier='pe.tuxiasumari.ingepresupuestos',
        info_plist={
            'CFBundleDisplayName': 'ingePresupuestos',
            'CFBundleShortVersionString': '0.5.0',
            'NSHighResolutionCapable': True,
            'NSRequiresAquaSystemAppearance': False,
        },
    )
