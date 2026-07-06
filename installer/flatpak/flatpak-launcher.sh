#!/bin/sh
# Lanzador de IngePresupuestos dentro del sandbox Flatpak.
# - NO forzamos plataforma Qt: en Wayland el sandbox recibe WAYLAND_DISPLAY
#   pero NO DISPLAY, así que forzar xcb rompía ("could not connect to display").
#   Qt auto-detecta: wayland si hay WAYLAND_DISPLAY, xcb si hay DISPLAY (X11).
#   El escape INGEPPTO_FORCE_XCB=1 sigue disponible (lo maneja main.py).
# - Agrega el site-packages de /app al PYTHONPATH (independiente de la versión
#   de Python del runtime).
PYVER=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
export PYTHONPATH="/app/lib/python${PYVER}/site-packages:${PYTHONPATH}"
cd /app/ingepresupuestos || exit 1
exec python3 main.py "$@"
