#!/usr/bin/env bash
# Construye e instala el Flatpak de IngePresupuestos (usuario).
#
#   ./installer/flatpak/build-flatpak.sh            # build + install
#   ./installer/flatpak/build-flatpak.sh --bundle   # + genera .flatpak distribuible
#
# Toma una copia LIMPIA del árbol de trabajo (excluye venv, .git, dist,
# release/ con PII de clientes, backups, etc.) y la empaqueta.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
APPID="com.ingepresupuestos.IngePresupuestos"
STAGING="$HERE/.staging"
STATE_DIR="$HERE/.flatpak-builder"
BUILD_DIR="$STAGING/build"
SRC_DIR="$STAGING/src"

# flatpak-builder se distribuye como app Flatpak (org.flatpak.Builder). Usar el
# binario del sistema si existe; si no, invocarlo vía `flatpak run`.
if command -v flatpak-builder >/dev/null 2>&1; then
  BUILDER="flatpak-builder"
else
  BUILDER="flatpak run org.flatpak.Builder"
fi

echo "▶ Copiando fuente limpia a $SRC_DIR …"
rm -rf "$SRC_DIR"
mkdir -p "$SRC_DIR"
rsync -a \
  --exclude 'venv/' \
  --exclude '.git/' \
  --exclude 'dist/' \
  --exclude 'build/' \
  --exclude 'release/' \
  --exclude '.claude/' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --exclude 'backups/' \
  --exclude '*.bak*' \
  --exclude 'node_modules/' \
  --exclude 'installer/flatpak/.staging/' \
  --exclude 'installer/flatpak/.flatpak-builder/' \
  "$REPO/" "$SRC_DIR/"

echo "▶ Construyendo con flatpak-builder …"
$BUILDER \
  --user --force-clean --install --disable-rofiles-fuse \
  --state-dir "$STATE_DIR" \
  "$BUILD_DIR" "$HERE/$APPID.yml"

if [ "${1:-}" = "--bundle" ]; then
  REPO_OSTREE="$STAGING/repo"
  BUNDLE="$STAGING/${APPID}.flatpak"
  echo "▶ Exportando bundle distribuible …"
  $BUILDER --user --force-clean --disable-rofiles-fuse --repo "$REPO_OSTREE" \
    --state-dir "$STATE_DIR" "$BUILD_DIR" "$HERE/$APPID.yml"
  flatpak build-bundle "$REPO_OSTREE" "$BUNDLE" "$APPID"
  echo "✔ Bundle: $BUNDLE"
fi

echo ""
echo "✔ Instalado. Ejecuta:  flatpak run $APPID"
