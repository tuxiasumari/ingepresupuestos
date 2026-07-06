# Empaquetado MSIX para la Microsoft Store

Identidad del producto (Partner Center → «ingepresupuestos»):

| Campo | Valor |
|-------|-------|
| Package/Identity/Name | `MarcoSumari.ingepresupuestos` |
| Publisher | `CN=EE1CAE53-5428-4D95-AE8B-871AB9D0193C` |
| Publisher display name | `Marco Sumari` |
| Package Family Name | `MarcoSumari.ingepresupuestos_1enpbchnxx3hm` |
| Store ID | `9PN8FKLP4RH5` |

Estos valores ya están en `AppxManifest.xml`. **No cambiarlos** o la Store rechaza el paquete.

## Requisitos (en Windows)
- La carpeta `dist\ingepresupuestos\` generada por PyInstaller (`pyinstaller ingepresupuestos.spec`).
- **Windows SDK** instalado (aporta `makeappx.exe` y `signtool.exe`).

## 1. Empaquetar
```powershell
cd installer\msix
.\package-msix.ps1 -Version 2.4.20 -DistDir ..\..\dist\ingepresupuestos
# genera IngePresupuestos-2.4.20.msix
```

## 2. Probar en tu PC (opcional, recomendado)
El `.msix` que se sube a la Store va **sin firmar** (Microsoft lo firma). Para
instalarlo localmente y probar que abre, hay que firmarlo con un certificado
self-signed cuyo *Subject* sea exactamente el Publisher del manifiesto:

```powershell
# Crear el cert (una sola vez)
$cert = New-SelfSignedCertificate -Type CodeSigningCert `
  -Subject "CN=EE1CAE53-5428-4D95-AE8B-871AB9D0193C" `
  -KeyUsage DigitalSignature -FriendlyName "IngePresupuestos MSIX test" `
  -CertStoreLocation "Cert:\CurrentUser\My" `
  -TextExtension @("2.5.29.37={text}1.3.6.1.5.5.7.3.3", "2.5.29.19={text}")

# Exportarlo y confiarlo en la máquina (requiere admin)
$pwd = ConvertTo-SecureString -String "test" -Force -AsPlainText
Export-PfxCertificate -cert $cert -FilePath test.pfx -Password $pwd
# Importar test.pfx en "Equipo local → Entidades de certificación raíz de confianza"

# Firmar e instalar
$st = (Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin" -Recurse -Filter signtool.exe | ? FullName -match '\\x64\\' | Sort FullName -Desc | Select -First 1).FullName
& $st sign /fd SHA256 /f test.pfx /p test IngePresupuestos-2.4.20.msix
Add-AppxPackage .\IngePresupuestos-2.4.20.msix
```
Verifica que la app abre, calcula bien y guarda datos en `%LOCALAPPDATA%\Packages\MarcoSumari.ingepresupuestos_*`.

> En la versión MSIX el **auto-update propio se desactiva solo** (lo detecta
> `core.update_manager.es_msix()`); las actualizaciones las da la Store.

## 3. Subir a la Store
Partner Center → producto «ingepresupuestos» → **Packages** → sube el `.msix`
**sin firmar** → completa la ficha (descripción, capturas, política de
privacidad, clasificación de edad) → **Submit for certification**.

## Notas MSIX
- La app corre en contenedor: escribe sus datos en el perfil del usuario
  (`USER_DATA_DIR`), compatible con MSIX.
- La instalación de fuentes a nivel sistema queda virtualizada (inofensivo:
  Inter se carga en runtime).
- Sube una versión MSIX **nueva** (mayor `Version`) por cada release.
