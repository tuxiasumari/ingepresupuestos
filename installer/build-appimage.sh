#!/usr/bin/env bash
# Construye el AppImage de IngePresupuestos a partir del output de
# PyInstaller (dist/ingepresupuestos/).
#
# Prerequisito: PyInstaller ya corrió y dist/ingepresupuestos/ existe.
#
# Uso:
#   ./installer/build-appimage.sh <VERSION>
#
# Genera:
#   dist/IngePresupuestos-<VERSION>-x86_64.AppImage
#
# En GitHub Actions: ver .github/workflows/build-linux.yml

set -euo pipefail

# ── Parámetros ─────────────────────────────────────────────────────────────
VERSION="${1:-0.0.0-dev}"

# Paths relativos al repo root (asumido como CWD desde el workflow)
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
REPO_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"
DIST_DIR="$REPO_ROOT/dist"
PYINSTALLER_OUT="$DIST_DIR/ingepresupuestos"
APPDIR="$DIST_DIR/IngePresupuestos.AppDir"
ICON_SRC="$REPO_ROOT/resources/icons/elementary/24/ingepresupuestos.png"
OUTPUT="$DIST_DIR/IngePresupuestos-${VERSION}-x86_64.AppImage"

# ── Validaciones ───────────────────────────────────────────────────────────
if [[ ! -d "$PYINSTALLER_OUT" ]]; then
    echo "ERROR: $PYINSTALLER_OUT no existe. Corré PyInstaller primero." >&2
    exit 1
fi

if [[ ! -f "$ICON_SRC" ]]; then
    echo "ERROR: ícono no encontrado en $ICON_SRC" >&2
    exit 1
fi

# ── Descargar appimagetool si no está ──────────────────────────────────────
APPIMAGETOOL="$REPO_ROOT/.appimagetool"
if [[ ! -x "$APPIMAGETOOL" ]]; then
    echo "→ Descargando appimagetool…"
    wget -q -O "$APPIMAGETOOL" \
        "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"
    chmod +x "$APPIMAGETOOL"
fi

# ── Armar la estructura AppDir ─────────────────────────────────────────────
echo "→ Armando $APPDIR…"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin"

# 1. Copiar todo el output de PyInstaller a usr/bin/ingepresupuestos/
cp -r "$PYINSTALLER_OUT" "$APPDIR/usr/bin/ingepresupuestos"

# 2. AppRun (entry point del AppImage)
cp "$SCRIPT_DIR/AppRun" "$APPDIR/AppRun"
chmod +x "$APPDIR/AppRun"

# 3. .desktop file en la raíz (requerido por appimagetool)
cp "$SCRIPT_DIR/ingepresupuestos.desktop" "$APPDIR/ingepresupuestos.desktop"

# 4. Ícono en la raíz (requerido) — appimagetool exige el .png a la altura
#    del .desktop. Usamos el de 256×256.
cp "$ICON_SRC" "$APPDIR/ingepresupuestos.png"

# 5. También en usr/share/icons/hicolor/256x256/apps/ por compat XDG
mkdir -p "$APPDIR/usr/share/icons/hicolor/256x256/apps"
cp "$ICON_SRC" "$APPDIR/usr/share/icons/hicolor/256x256/apps/ingepresupuestos.png"

# 6. .desktop también en la jerarquía estándar
mkdir -p "$APPDIR/usr/share/applications"
cp "$SCRIPT_DIR/ingepresupuestos.desktop" "$APPDIR/usr/share/applications/ingepresupuestos.desktop"

# ── Compilar el AppImage ───────────────────────────────────────────────────
echo "→ Compilando AppImage…"
# ARCH=x86_64 le dice a appimagetool la arquitectura target.
# --no-appstream evita un check estricto de metadata XML que no aportamos.
ARCH=x86_64 "$APPIMAGETOOL" --no-appstream "$APPDIR" "$OUTPUT"

# ── Reporte ───────────────────────────────────────────────────────────────
if [[ -f "$OUTPUT" ]]; then
    SIZE=$(du -h "$OUTPUT" | cut -f1)
    echo
    echo "✓ AppImage creado:"
    echo "  Archivo: $OUTPUT"
    echo "  Tamaño:  $SIZE"
    echo
    echo "Para probarlo:"
    echo "  chmod +x $OUTPUT  # ya viene ejecutable, por las dudas"
    echo "  $OUTPUT           # doble click o ejecutar"
else
    echo "✗ ERROR: no se generó el AppImage" >&2
    exit 1
fi

# Limpieza opcional del AppDir (queda en disco para debugging)
# rm -rf "$APPDIR"
