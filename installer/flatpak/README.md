# Flatpak — IngePresupuestos

Empaquetado Flatpak para Linux. App-id: **`com.ingepresupuestos.IngePresupuestos`**.

## Construir e instalar (local)

```bash
./installer/flatpak/build-flatpak.sh
flatpak run com.ingepresupuestos.IngePresupuestos
```

Genera además un `.flatpak` distribuible (para pasar a otra persona):

```bash
./installer/flatpak/build-flatpak.sh --bundle
# → installer/flatpak/.staging/com.ingepresupuestos.IngePresupuestos.flatpak
# instalar en otra máquina:  flatpak install --user ./com.ingepresupuestos.IngePresupuestos.flatpak
```

## Requisitos del sistema (una sola vez)

```bash
flatpak install --user flathub org.flatpak.Builder \
    org.freedesktop.Platform//25.08 org.freedesktop.Sdk//25.08
```

## Qué hace el manifiesto

- **Runtime**: `org.freedesktop.Platform 25.08` (Python 3.13). PySide6 se instala
  con `pip` y trae su propio Qt (no depende del Qt del sistema).
- **Código**: se copia una instantánea *limpia* del árbol de trabajo (el script
  excluye `venv/`, `.git/`, `dist/`, `release/` —PII de clientes—, backups…).
- **Programas externos** (LibreOffice para ODT/ODS, mdbtools para `.prs`): NO se
  empaquetan; se usan los del **host** vía `flatpak-spawn --host`. El código lo
  detecta con `core.config.es_flatpak()` y enruta las llamadas
  (`core/soffice.py`, `core/powercost_prs_importer.py`). Bajo Flatpak los
  temporales se redirigen a `~/.var/app/<id>/…/tmp` (ruta real que el host ve).

## Notas

- Reportes **PDF / Excel / Word** funcionan nativos (librerías Python).
- Reportes **ODT / ODS** y la importación de **`.prs`** requieren que el
  **host** tenga LibreOffice / mdbtools instalados.
- El auto-updater y la instalación de fuentes system-wide se desactivan bajo
  Flatpak (las actualizaciones llegan por `flatpak update`).

## Pendiente para publicar en Flathub (Etapa 2)

- Reemplazar el `pip install` con red por un módulo pip **offline** con hashes
  (`flatpak-pip-generator`).
- Capturas (`<screenshots>`) en el `.metainfo.xml`.
- Resolver la licencia: Flathub exige que el manifiesto sea reproducible; el
  código puede seguir siendo propietario, pero conviene revisar los términos.
- Empaquetar **mdbtools** dentro (para no depender del host) si se quiere que
  la importación `.prs` funcione sin instalar nada extra.
