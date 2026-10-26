# Builds dist\CallCopilot-Setup.exe and dist\CallCopilot-Setup.zip.
# Only code and the icon are packaged: about.md, context.md, config.json, logs, .venv and tools never are.
$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
$Dist = Join-Path $Root "dist"
$Stage = Join-Path $Dist "stage"
$App = Join-Path $Stage "app"

if (Test-Path $Dist) { Remove-Item $Dist -Recurse -Force }
New-Item -ItemType Directory -Force (Join-Path $App "copilot"), (Join-Path $App "assets") | Out-Null

$files = @("app.py", "run.bat", "README.md", "requirements.txt", "assets\icon.ico")
foreach ($f in $files) { Copy-Item (Join-Path $Root $f) (Join-Path $App $f) }
Get-ChildItem (Join-Path $Root "copilot") -Filter *.py | Copy-Item -Destination (Join-Path $App "copilot")

# Windows PowerShell 5.1 reads scripts without BOM as ANSI -> Cyrillic would break. Save scripts as UTF-8 with BOM.
function Copy-WithBom($from, $to) {
    [IO.File]::WriteAllText($to, [IO.File]::ReadAllText($from, [Text.Encoding]::UTF8), (New-Object Text.UTF8Encoding($true)))
}
Copy-WithBom (Join-Path $PSScriptRoot "setup.ps1") (Join-Path $Stage "setup.ps1")
Copy-Item (Join-Path $PSScriptRoot "Setup.cmd") $Stage
# the uninstaller lives in the app folder
Copy-WithBom (Join-Path $PSScriptRoot "uninstall.ps1") (Join-Path $App "uninstall.ps1")
Copy-WithBom (Join-Path $PSScriptRoot "connect.ps1") (Join-Path $App "connect.ps1")
Copy-Item (Join-Path $PSScriptRoot "Uninstall.cmd") $App
Copy-Item (Join-Path $Root "README.ru.md"), (Join-Path $Root "LICENSE") $App

# zip variant: Setup.cmd + setup.ps1 + app\
Compress-Archive -Path (Join-Path $Stage "Setup.cmd"), (Join-Path $Stage "setup.ps1"), $App -DestinationPath (Join-Path $Dist "CallCopilot-Setup.zip")

# exe variant: small C# launcher (built-in .NET Framework compiler) with Setup.cmd, setup.ps1 and app.zip embedded
Compress-Archive -Path (Join-Path $App "*") -DestinationPath (Join-Path $Stage "app.zip")
$csc = Join-Path $env:SystemRoot "Microsoft.NET\Framework64\v4.0.30319\csc.exe"
$exe = Join-Path $Dist "CallCopilot-Setup.exe"
& $csc /nologo /target:exe /optimize+ "/out:$exe" `
    "/win32icon:$(Join-Path $Root 'assets\icon.ico')" "/win32manifest:$(Join-Path $PSScriptRoot 'launcher.manifest')" `
    "/resource:$(Join-Path $Stage 'Setup.cmd'),Setup.cmd" "/resource:$(Join-Path $Stage 'setup.ps1'),setup.ps1" `
    "/resource:$(Join-Path $Stage 'app.zip'),app.zip" (Join-Path $PSScriptRoot "launcher.cs")
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $exe)) { throw "csc failed to build $exe" }

Remove-Item $Stage -Recurse -Force
Get-ChildItem $Dist -File | Select-Object Name, @{n = "KB"; e = { [int]($_.Length / 1KB) } }
