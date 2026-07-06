; Script Inno Setup para IngePresupuestos.
;
; Genera un instalador .exe profesional para Windows con wizard en español,
; EULA, accesos directos, registro en "Agregar o quitar programas" y
; desinstalador automático.
;
; Compilar local (necesita Inno Setup 6+ instalado):
;     iscc /DMyAppVersion=2.2.0 installer\ingepresupuestos.iss
;
; Compilar desde GitHub Actions: ver .github/workflows/build-windows.yml
;
; El AppId es un GUID FIJO — NO cambiarlo entre versiones, sino Windows
; pensaría que cada release es una app distinta y no haría upgrade limpio.

#define MyAppName "IngePresupuestos"
#define MyAppPublisher "Ing. Marco Sumari Tellez"
#define MyAppURL "https://ingepresupuestos.com"
#define MyAppExeName "ingepresupuestos.exe"

; MyAppVersion se inyecta desde el comando de compilación con /DMyAppVersion=X.Y.Z
; Si no se pasa, default para testing local.
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0-dev"
#endif

[Setup]
; AppId GUID FIJO — generado una sola vez. Cambiar esto rompe upgrades.
AppId={{7F0E6389-C972-4472-B7A9-1A14FFD8CF0F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
VersionInfoVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription=Software para la elaboración de Presupuestos de Obra
VersionInfoProductName={#MyAppName}

; Carpeta de instalación — Program Files con autoredirección 32/64-bit.
; PrivilegesRequired=admin → pide UAC pero queda en Program Files (estándar
; profesional). Si quisieras instalación sin UAC, cambiar a "lowest" y
; DefaultDirName a "{autopf}\{#MyAppName}" (igual queda en Program Files
; solo si el user tiene perms; sino va a %LocalAppData%\Programs\).
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog

; Archivo de licencia que el usuario debe aceptar.
LicenseFile=EULA.txt

; Salida — donde queda el setup.exe compilado y cómo se llama.
OutputDir=..\dist
OutputBaseFilename=ingepresupuestos-setup-v{#MyAppVersion}

; Comportamiento del wizard
WizardStyle=modern
ShowLanguageDialog=no
DisableWelcomePage=no
DisableDirPage=auto
DisableProgramGroupPage=auto

; Compresión — sólida + lzma2 para tamaño mínimo.
Compression=lzma2/max
SolidCompression=yes

; Ícono del instalador en sí (el ícono que se ve en el .exe del setup).
SetupIconFile=..\resources\icons\elementary\24\ingepresupuestos.ico

; Ícono que va en "Agregar o quitar programas" + uninstaller.
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName} {#MyAppVersion}

; Permite re-ejecutar el instalador para reparar / actualizar.
CloseApplications=force
RestartApplications=no

; Mínimo Windows 10. El bundle PyInstaller no anda en 8 ni 7.
MinVersion=10.0


[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"


[Tasks]
Name: "desktopicon"; Description: "Crear acceso directo en el {cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "quicklaunchicon"; Description: "Crear acceso directo en la barra de inicio rápido"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked; OnlyBelowVersion: 6.1


[Files]
; Copiar TODO el output de PyInstaller a la carpeta de instalación.
; "recursesubdirs" mantiene la estructura interna (_internal/, resources/, etc.)
Source: "..\dist\ingepresupuestos\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs


[Icons]
; Menú Inicio
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Comment: "Software para la elaboración de Presupuestos de Obra"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"

; Escritorio (opcional, según tasks)
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{userappdata}\Microsoft\Internet Explorer\Quick Launch\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: quicklaunchicon


[Run]
; Opción de ejecutar la app justo después de instalar (checkbox final del wizard).
Filename: "{app}\{#MyAppExeName}"; Description: "Ejecutar {#MyAppName}"; Flags: nowait postinstall skipifsilent


[UninstallDelete]
; Borrar archivos generados por la app que NO viven en {app}.
; OJO: NO borramos %APPDATA%\ingepresupuestos\ porque ahí están la BD, los
; backups y la licencia del usuario — se conservan para reinstalaciones.
Type: filesandordirs; Name: "{app}\__pycache__"
