<#
.SYNOPSIS
  Empaqueta la app (carpeta onedir de PyInstaller) como MSIX para la Microsoft Store.

.DESCRIPTION
  1. Sustituye la versión en el AppxManifest (x.y.z.0).
  2. Copia el manifiesto y la carpeta Assets dentro de la carpeta de PyInstaller.
  3. Empaqueta con makeappx.exe (Windows SDK).

  El .msix resultante se SUBE A PARTNER CENTER SIN FIRMAR: Microsoft lo firma al
  publicar. Para probarlo localmente hay que firmarlo con un certificado
  self-signed cuyo Subject == el Publisher del manifiesto (ver README.md).

.EXAMPLE
  .\package-msix.ps1 -Version 2.4.20 -DistDir ..\..\dist\ingepresupuestos
#>
param(
    [Parameter(Mandatory = $true)] [string]$Version,
    [Parameter(Mandatory = $true)] [string]$DistDir,
    [string]$Output = ""
)
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

# Versión MSIX = 4 partes con la última en 0 (requisito de la Store).
$v = $Version.TrimStart("v")
$parts = $v.Split(".")
while ($parts.Count -lt 3) { $parts += "0" }
$msixVersion = "{0}.{1}.{2}.0" -f $parts[0], $parts[1], $parts[2]

if (-Not (Test-Path "$DistDir\ingepresupuestos.exe")) {
    throw "No se encontró ingepresupuestos.exe en $DistDir (¿corriste PyInstaller?)"
}

# 1. Manifiesto con la versión inyectada → dentro de la carpeta de la app.
$manifest = Get-Content "$here\AppxManifest.xml" -Raw
$manifest = $manifest -replace 'Version="0\.0\.0\.0"', "Version=`"$msixVersion`""
Set-Content -Path "$DistDir\AppxManifest.xml" -Value $manifest -Encoding UTF8

# 2. Assets (logos).
Copy-Item -Path "$here\Assets" -Destination "$DistDir\Assets" -Recurse -Force

# 3. Localizar makeappx.exe (Windows SDK, la versión más reciente).
$kits = "${env:ProgramFiles(x86)}\Windows Kits\10\bin"
$makeappx = Get-ChildItem -Path $kits -Recurse -Filter makeappx.exe -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -match '\\x64\\' } |
            Sort-Object FullName -Descending | Select-Object -First 1
if (-Not $makeappx) { throw "makeappx.exe no encontrado. Instala el Windows SDK." }

# 3b. resources.pri — indexa las variantes de iconos (scale/targetsize/
#     altform-unplated) para que la BARRA DE TAREAS muestre el icono SIN la
#     placa blanca cuadrada (Windows usa la variante «unplated»). Es ADITIVO:
#     si makepri no está o falla, se omite y el paquete se arma igual que antes
#     (con placa), sin romper el build.
$distFull = (Resolve-Path $DistDir).Path
try {
    $makepri = Get-ChildItem -Path $kits -Recurse -Filter makepri.exe -ErrorAction SilentlyContinue |
               Where-Object { $_.FullName -match '\\x64\\' } |
               Sort-Object FullName -Descending | Select-Object -First 1
    if ($makepri) {
        $priconfig = Join-Path ([System.IO.Path]::GetTempPath()) "ingeppto_priconfig.xml"
        & $makepri.FullName createconfig /cf $priconfig /dq "es-PE" /o | Out-Null
        & $makepri.FullName new /pr $distFull /cf $priconfig `
              /mn "$distFull\AppxManifest.xml" /of "$distFull\resources.pri" /o | Out-Null
        if (Test-Path "$distFull\resources.pri") {
            Write-Host "resources.pri generado (icono sin placa en la barra de tareas)."
        }
    } else {
        Write-Host "makepri.exe no encontrado — se omite resources.pri (icono con placa)."
    }
} catch {
    Write-Host "makepri falló ($($_.Exception.Message)) — se omite resources.pri."
}

if ([string]::IsNullOrEmpty($Output)) {
    $Output = "IngePresupuestos-$Version.msix"
}

Write-Host "Empaquetando MSIX $msixVersion -> $Output"

# 4. Mapping file: empaquetamos archivo por archivo (no /d) para poder EXCLUIR
#    rutas con corchetes — p.ej. el "[Content_Types].xml" de las plantillas
#    descomprimidas de python-docx. Los corchetes son nombre reservado del
#    formato MSIX y hacen fallar a makeappx con 0x8007007b.
$distFull  = (Resolve-Path $DistDir).Path
$mapping   = Join-Path ([System.IO.Path]::GetTempPath()) "ingeppto_msix_mapping.txt"
$lines     = New-Object System.Collections.Generic.List[string]
$lines.Add("[Files]")
$incluidos = 0
$excluidos = 0
Get-ChildItem -Path $distFull -Recurse -File | ForEach-Object {
    $rel = $_.FullName.Substring($distFull.Length).TrimStart('\')
    # makeappx rechaza (0x8007007b) nombres reservados del formato OPC/MSIX.
    # El árbol DESCOMPRIMIDO de la plantilla de python-docx los trae todos:
    # "[Content_Types].xml" (corchetes) y carpetas "_rels" / archivos "*.rels".
    # No se usan en runtime: python-docx abre templates\default.docx (el .zip).
    # Se excluye el subárbol completo + guardas generales por si aparecen en otro sitio.
    if ($rel -match '\\docx\\templates\\default-docx-template\\' -or
        $rel -match '[\[\]]' -or
        $rel -match '(^|\\)_rels(\\|$)' -or
        $rel -match '\.rels$') {
        Write-Host "  excluido (reservado MSIX): $rel"
        $excluidos++
        return
    }
    # Concatenación (no -f): el operador -f tiene mayor precedencia que la coma
    # en PowerShell, así que '... -f $a, $b' le pasaría un solo argumento a -f.
    $lines.Add('"' + $_.FullName + '" "' + $rel + '"')
    $incluidos++
}
# Sin BOM: makeappx no parsea bien el mapping si empieza con BOM UTF-8.
[System.IO.File]::WriteAllLines($mapping, $lines)
Write-Host "Mapping: $incluidos archivos incluidos, $excluidos excluidos"

& $makeappx.FullName pack /o /f $mapping /p $Output
if ($LASTEXITCODE -ne 0) { throw "makeappx falló ($LASTEXITCODE)" }
Write-Host "OK: $Output"
