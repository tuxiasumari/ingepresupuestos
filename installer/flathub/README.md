# Edición Flathub de IngePresupuestos

Manifiesto y archivos para publicar IngePresupuestos en **Flathub** (la tienda
de apps de Linux). Es una **edición aparte** de la Flatpak de R2/GitHub
(`installer/flatpak/`): NO comparten configuración.

## Diferencias con las otras ediciones (por reglas de Flathub)

| Aspecto | Otras ediciones | Flathub |
|---|---|---|
| Reportes PDF / Word / Excel | ✅ | ✅ |
| Reportes **ODT / ODS** | ✅ (LibreOffice del host) | ❌ (Flathub prohíbe salir del sandbox) |
| Importar `.prs` (PowerCost) | host mdbtools | ✅ mdbtools **embebido** |
| PySide6 | pip | base-app `io.qt.PySide.BaseApp` |
| Dependencias Python | pip online | **offline** con hashes (`python3-requirements.yaml`) |
| Acceso a archivos | `--filesystem=home` | **portal** de archivos |

ODT/ODS degrada solo: sin acceso al host, `core/soffice.py::find_soffice()`
devuelve `None` y el reporte muestra un aviso (no crashea). No requiere cambios
de código compartido.

## Archivos

- `com.ingepresupuestos.IngePresupuestos.yml` — manifiesto (lint OK).
- `com.ingepresupuestos.IngePresupuestos.metainfo.xml` — AppStream (lint OK, con capturas).
- `com.ingepresupuestos.IngePresupuestos.desktop` — entrada de escritorio.
- `flathub-launcher.sh` — lanzador dentro del sandbox.
- `python3-requirements.yaml` — deps Python congeladas (generado, sin PySide6).

## Regenerar las dependencias Python (si cambia requirements.txt)

```bash
# reqs sin PySide6 (base-app), pyinstaller ni pyodbc (Windows) ni model2vec (Fase 2):
venv/bin/python flatpak-pip-generator.py \
  --runtime='org.freedesktop.Sdk//25.08' \
  --requirements-file reqs-flathub.txt \
  --yaml --output installer/flathub/python3-requirements
```
(`flatpak-pip-generator.py` se baja de github.com/flatpak/flatpak-builder-tools)

## Probar el build localmente (PENDIENTE — descarga varios GB)

Requiere el SDK de KDE + los base-apps (org.kde.Sdk//6.10, io.qt.PySide.BaseApp,
io.qt.qtwebengine.BaseApp):

```bash
cd installer/flathub
flatpak install flathub org.kde.Sdk//6.10 org.kde.Platform//6.10   # ~2-3 GB
flatpak run org.flatpak.Builder --force-clean --install-deps-from=flathub \
  --user --install builddir com.ingepresupuestos.IngePresupuestos.yml
flatpak run com.ingepresupuestos.IngePresupuestos
```
**Verificar en el build:**
1. La app abre (PySide6 del base-app en el PYTHONPATH correcto).
2. Importar/exportar funciona por el **portal** de archivos (sin `--filesystem=home`).
   Si algún flujo escribe a ruta fija (p.ej. export directo a Descargas), añadir
   `--filesystem=xdg-download` o justificar `--filesystem=home` en el PR.
3. Reportes PDF/Word/Excel OK; ODT/ODS muestra aviso (no crash).
4. `.prs` importa con el mdbtools embebido.
5. Lint del build: `flatpak run --command=flatpak-builder-lint org.flatpak.Builder builddir builddir`

## Enviar a Flathub (PENDIENTE — tras validar el build)

1. Fork de `github.com/flathub/flathub`.
2. Rama nueva; copiar a la RAÍZ del repo: el `.yml`, `.metainfo.xml`, `.desktop`,
   `flathub-launcher.sh` y `python3-requirements.yaml`.
3. PR contra la rama **`new-pr`** de `flathub/flathub` (NO master).
4. El bot compila y un revisor humano revisa (días–semanas; puede pedir ajustes).
5. Al aprobarse, Flathub crea el repo `flathub/com.ingepresupuestos.IngePresupuestos`
   y da acceso. La "app verificada" (✔) se obtiene luego probando dominio
   `ingepresupuestos.com`.

## Estado

- ✅ Manifiesto + metainfo + launcher + desktop + deps offline (lint limpio).
- ⏳ Build local de validación (multi-GB, iterativo).
- ⏳ PR a flathub/flathub.
