#!/bin/bash
cd "$(dirname "$0")"
# Qt elige backend automáticamente. Para forzar xcb (X11), exportar antes:
#   export INGEPPTO_FORCE_XCB=1
if [ "$INGEPPTO_FORCE_XCB" = "1" ]; then
    export QT_QPA_PLATFORM=xcb
fi
source venv/bin/activate
python3 main.py
