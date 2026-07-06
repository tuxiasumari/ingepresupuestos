#!/usr/bin/env bash
# Script de release — bumpea versión, commit, tag y push.
#
# Uso:
#   ./release.sh 0.5.0       → crea release v0.5.0
#   ./release.sh             → modo interactivo (pregunta versión)
#
# Lo que hace, en orden:
#   1. Verifica que estás en la rama main y sin cambios pendientes.
#   2. Actualiza CURRENT_VERSION en core/update_manager.py.
#   3. Hace commit del cambio de versión.
#   4. Crea tag anotado vX.Y.Z.
#   5. Pushea commit y tag a GitHub.
#   6. GitHub Actions detecta el tag y arranca los builds Linux+Windows.
#   7. Cuando terminan (~10 min), los .zip aparecen en la página Releases.
#
# Si algo falla, lee el mensaje y arregla — el script NO continúa por su cuenta.

set -e   # stop al primer error

cd "$(dirname "$0")"  # asegurar CWD = directorio del repo

# Colores
G='\033[0;32m'  # verde
R='\033[0;31m'  # rojo
Y='\033[0;33m'  # amarillo
N='\033[0m'     # reset

# ── 1. Argumentos ──────────────────────────────────────────────────────────
VERSION="${1:-}"
if [ -z "$VERSION" ]; then
    # Modo interactivo: mostrar versión actual y pedir nueva
    actual=$(grep '^CURRENT_VERSION' core/update_manager.py | head -1 | cut -d'"' -f2)
    echo -e "Versión actual: ${Y}${actual}${N}"
    read -p "Nueva versión (sin 'v', ej. 0.5.0): " VERSION
fi

# Validar formato semver (X.Y.Z)
if ! [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo -e "${R}Error:${N} versión debe ser X.Y.Z (ej. 0.5.0, 1.2.3)"
    exit 1
fi
TAG="v${VERSION}"

# ── 2. Checks de git ──────────────────────────────────────────────────────
rama=$(git rev-parse --abbrev-ref HEAD)
if [ "$rama" != "main" ]; then
    echo -e "${R}Error:${N} no estás en la rama main (estás en '${rama}')"
    echo "Cambia a main con: git checkout main"
    exit 1
fi

if [ -n "$(git status --porcelain)" ]; then
    echo -e "${R}Error:${N} hay cambios sin commit. Commitea o stashea primero."
    git status --short
    exit 1
fi

# ¿El tag ya existe?
if git rev-parse "$TAG" >/dev/null 2>&1; then
    echo -e "${R}Error:${N} el tag $TAG ya existe."
    echo "Elige otra versión o borra el tag con: git tag -d $TAG"
    exit 1
fi

# ── 3. Actualizar versión en el código ────────────────────────────────────
echo -e "${G}→ Actualizando CURRENT_VERSION a ${VERSION}${N}"
sed -i "s/^CURRENT_VERSION = \".*\"/CURRENT_VERSION = \"${VERSION}\"/" \
    core/update_manager.py

# Verificar que el sed funcionó
nueva=$(grep '^CURRENT_VERSION' core/update_manager.py | head -1 | cut -d'"' -f2)
if [ "$nueva" != "$VERSION" ]; then
    echo -e "${R}Error:${N} no pude actualizar CURRENT_VERSION."
    git checkout core/update_manager.py
    exit 1
fi

# ── 4. Confirmar antes de pushear ─────────────────────────────────────────
echo
echo -e "${Y}Listo para crear release ${TAG}:${N}"
echo "  • Commit: 'chore: bump version to ${VERSION}'"
echo "  • Tag:    ${TAG}"
echo "  • Push:   origin main + tag"
echo "  • Trigger: GitHub Actions compila Linux+Windows automáticamente."
echo
read -p "¿Continuar? [y/N] " confirm
if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
    echo "Cancelado. Reverteo cambio en update_manager.py..."
    git checkout core/update_manager.py
    exit 0
fi

# ── 5. Commit + tag + push ────────────────────────────────────────────────
git add core/update_manager.py
git commit -m "chore: bump version to ${VERSION}"
git tag -a "$TAG" -m "Release ${TAG}"
git push origin main
git push origin "$TAG"

# ── 6. Resumen ─────────────────────────────────────────────────────────────
echo
echo -e "${G}✓ Tag ${TAG} pusheado${N}"
echo
echo "Siguiente paso (esperar ~10 min):"
echo "  1. Abre https://github.com/tuxiasumari/ingepresupuestos-pyside6/actions"
echo "  2. Verás dos workflows corriendo: 'Build Linux' y 'Build Windows'"
echo "  3. Cuando ambos terminen, los binarios aparecen en:"
echo "     https://github.com/tuxiasumari/ingepresupuestos-pyside6/releases/tag/${TAG}"
echo "  4. Descarga ingepresupuestos-windows.zip y pásaselo a los beta testers."
