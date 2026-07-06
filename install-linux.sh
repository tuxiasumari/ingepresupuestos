#!/usr/bin/env bash
# Instalador para Linux — registra ingePresupuestos en el sistema:
#   - Copia binario + assets a ~/.local/share/ingepresupuestos-bin/
#   - Crea ~/.local/share/applications/ingepresupuestos.desktop
#     (para que aparezca en el menú de aplicaciones y dock)
#   - Copia el ícono a ~/.local/share/icons/hicolor/256x256/apps/
#
# Uso: ./install-linux.sh   (corrélo DENTRO de la carpeta descomprimida
#                            del .tar.gz de la release)
#
# Desinstalar: ./install-linux.sh --uninstall

set -e

# Donde el .desktop espera encontrar el binario y los íconos.
PREFIX="${HOME}/.local"
APP_DIR="${PREFIX}/share/ingepresupuestos-bin"
DESKTOP_FILE="${PREFIX}/share/applications/ingepresupuestos.desktop"
ICON_DIR="${PREFIX}/share/icons/hicolor/256x256/apps"
ICON_FILE="${ICON_DIR}/ingepresupuestos.png"

# Colores
G='\033[0;32m'; R='\033[0;31m'; Y='\033[0;33m'; N='\033[0m'

# ── Desinstalar ────────────────────────────────────────────────────────────
if [ "$1" = "--uninstall" ]; then
    echo -e "${Y}Desinstalando ingePresupuestos…${N}"
    rm -rf "$APP_DIR"
    rm -f "$DESKTOP_FILE"
    rm -f "$ICON_FILE"
    update-desktop-database "${PREFIX}/share/applications" 2>/dev/null || true
    gtk-update-icon-cache "${PREFIX}/share/icons/hicolor" 2>/dev/null || true
    echo -e "${G}✓ Desinstalado${N}"
    exit 0
fi

# ── Verificar que estamos en la carpeta correcta ──────────────────────────
HERE="$(cd "$(dirname "$0")" && pwd)"

if [ ! -f "${HERE}/ingepresupuestos" ] || [ ! -d "${HERE}/_internal" ]; then
    echo -e "${R}Error:${N} no encuentro el binario 'ingepresupuestos' ni la"
    echo "carpeta '_internal/' en este directorio:"
    echo "  ${HERE}"
    echo
    echo "Ejecutá este script DESDE la carpeta descomprimida del"
    echo ".tar.gz de la release (la que contiene 'ingepresupuestos' y"
    echo "'_internal/')."
    exit 1
fi

ICON_SRC="${HERE}/_internal/resources/icons/elementary/24/ingepresupuestos.png"
if [ ! -f "$ICON_SRC" ]; then
    echo -e "${R}Error:${N} no encuentro el ícono en ${ICON_SRC}"
    exit 1
fi

# ── Copiar binario + assets a destino ─────────────────────────────────────
echo -e "${G}→ Copiando archivos a ${APP_DIR}…${N}"
mkdir -p "$APP_DIR"
# Si ya había una instalación previa, la limpiamos primero.
rm -rf "${APP_DIR}/_internal" "${APP_DIR}/ingepresupuestos"
cp -r "${HERE}/_internal" "$APP_DIR/"
cp "${HERE}/ingepresupuestos" "$APP_DIR/"
chmod +x "${APP_DIR}/ingepresupuestos"

# ── Copiar ícono ──────────────────────────────────────────────────────────
echo -e "${G}→ Copiando ícono…${N}"
mkdir -p "$ICON_DIR"
cp "$ICON_SRC" "$ICON_FILE"

# ── Crear .desktop ────────────────────────────────────────────────────────
echo -e "${G}→ Creando lanzador (.desktop)…${N}"
mkdir -p "$(dirname "$DESKTOP_FILE")"
cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=ingePresupuestos
GenericName=Presupuestos de obra
Comment=Sistema de presupuestos para obras peruanas (CAPECO, RNE)
Exec=${APP_DIR}/ingepresupuestos
Icon=ingepresupuestos
Terminal=false
Categories=Office;Finance;
StartupWMClass=ingepresupuestos
Keywords=presupuesto;obra;ACU;CAPECO;construccion;
EOF
chmod +x "$DESKTOP_FILE"

# ── Refrescar caches ──────────────────────────────────────────────────────
update-desktop-database "${PREFIX}/share/applications" 2>/dev/null || true
gtk-update-icon-cache "${PREFIX}/share/icons/hicolor" 2>/dev/null || true

echo
echo -e "${G}✓ Instalación completa${N}"
echo
echo "Ya podés:"
echo "  • Buscar 'ingePresupuestos' en el menú de aplicaciones de Ubuntu."
echo "  • Anclarlo al dock haciendo click derecho cuando esté abierto."
echo
echo "Para desinstalar:  ${HERE}/install-linux.sh --uninstall"
echo "Binario directo:   ${APP_DIR}/ingepresupuestos"
