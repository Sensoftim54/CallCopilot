# Call Copilot uninstaller. Lives in the app folder (Uninstall.cmd) and is registered in Windows
# "Settings → Apps". Removes the app folder, its shortcuts and the Apps entry. Python, Node.js, Claude Code
# and your ChatGPT/Claude sign-ins stay — other programs may use them.
param(
    [string]$Dest = $PSScriptRoot,
    [ValidateSet("", "en", "ru")][string]$Lang = "",
    [switch]$Quiet,      # no questions: remove the app, keep a copy of your data
    [switch]$Relocated   # internal: already running from a temp copy
)
$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [Text.Encoding]::UTF8
if (-not $Lang) {
    # same rule as the app (copilot/i18n.py): the Windows display language; Get-UICulture is unreliable here
    try {
        Add-Type -Namespace CallCopilot -Name Lang -ErrorAction Stop -MemberDefinition `
            '[DllImport("kernel32.dll")] public static extern ushort GetUserDefaultUILanguage();'
        $Lang = if (([CallCopilot.Lang]::GetUserDefaultUILanguage() -band 0x3FF) -eq 0x19) { "ru" } else { "en" }
    } catch {
        $Lang = if ([Globalization.CultureInfo]::InstalledUICulture.TwoLetterISOLanguageName -eq "ru") { "ru" } else { "en" }
    }
}
function L($en, $ru) { if ($Lang -eq "ru") { $ru } else { $en } }
function Ask($q) { if ($Quiet) { return $false }; return ("$(Read-Host $q)".Trim().ToLower() -in "y", "yes", "д", "да") }

$Dest = (Resolve-Path $Dest -ErrorAction SilentlyContinue).Path
if (-not $Dest -or -not (Test-Path (Join-Path $Dest "app.py")) -or -not (Test-Path (Join-Path $Dest "copilot"))) {
    Write-Host (L "This does not look like a Call Copilot folder: $Dest" "Это не похоже на папку Call Copilot: $Dest") -ForegroundColor Red
    exit 1
}

# A script cannot delete the folder it runs from — continue from a temp copy.
if (-not $Relocated) {
    $tmp = Join-Path $env:TEMP "CallCopilot-uninstall.ps1"
    Copy-Item $PSCommandPath $tmp -Force
    $argv = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$tmp`"", "-Dest", "`"$Dest`"", "-Relocated")
    if ($Lang) { $argv += @("-Lang", $Lang) }
    if ($Quiet) { $argv += "-Quiet" }
    Set-Location $env:TEMP  # do not hold the app folder as the current directory
    $p = Start-Process powershell -ArgumentList $argv -NoNewWindow -Wait -PassThru -WorkingDirectory $env:TEMP
    exit $p.ExitCode
}

Write-Host "==============================================" -ForegroundColor Magenta
Write-Host "  Call Copilot — $(L 'uninstall' 'удаление')" -ForegroundColor Magenta
Write-Host "  $(L 'Folder' 'Папка'): $Dest" -ForegroundColor Magenta
Write-Host "==============================================" -ForegroundColor Magenta
if (-not $Quiet -and -not (Ask (L "Remove Call Copilot? (y/N)" "Удалить Call Copilot? (д/Н)"))) {
    Write-Host (L "Cancelled." "Отменено."); exit 0
}

# 1. Your data: About me, Context, settings, call logs
$data = @("about.md", "context.md", "logs") | ForEach-Object { Join-Path $Dest $_ } | Where-Object { Test-Path $_ }
if ($data) {  # config.json alone (just settings) is not worth a copy; with real data it goes along
    $data += @(Join-Path $Dest "config.json") | Where-Object { Test-Path $_ }
    $wipe = Ask (L "Delete your data too (About me, Context, call logs)? Otherwise it is saved to Documents. (y/N)" `
                   "Удалить и твои данные («Обо мне», «Контекст», журналы созвонов)? Иначе они сохранятся в «Документы». (д/Н)")
    if (-not $wipe) {
        $keep = Join-Path ([Environment]::GetFolderPath("MyDocuments")) "Call Copilot data"
        New-Item -ItemType Directory -Force $keep | Out-Null
        Copy-Item $data $keep -Recurse -Force
        Write-Host "    OK  $(L 'your data is saved in' 'твои данные сохранены в') $keep" -ForegroundColor Green
    }
}

# 2. Close the running app (and its model requests)
Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($Dest, "OrdinalIgnoreCase") -or
                                                ($_.CommandLine -and $_.CommandLine -like "*$Dest*" -and $_.Name -match "python|node") } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Milliseconds 800

# 3. Shortcuts — only those that point into this install
$sh = New-Object -ComObject WScript.Shell
foreach ($dir in [Environment]::GetFolderPath("Desktop"), [Environment]::GetFolderPath("Programs")) {
    $lnk = Join-Path $dir "Call Copilot.lnk"
    if ((Test-Path $lnk) -and $sh.CreateShortcut($lnk).TargetPath -like "$Dest*") { Remove-Item $lnk -Force }
}
Write-Host "    OK  $(L 'shortcuts removed' 'ярлыки удалены')" -ForegroundColor Green

# 4. Entry in Settings → Apps
$key = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\CallCopilot"
if ((Test-Path $key) -and (Get-ItemProperty $key).InstallLocation -eq $Dest) { Remove-Item $key -Recurse -Force }

# 5. The app folder
Remove-Item $Dest -Recurse -Force -ErrorAction SilentlyContinue
if (Test-Path $Dest) { Write-Host "    !   $(L 'some files are still in use — delete the folder later' 'часть файлов занята — удали папку позже'): $Dest" -ForegroundColor Yellow }
else { Write-Host "    OK  $(L 'app folder removed' 'папка программы удалена')" -ForegroundColor Green }

# 6. Speech recognition model in the shared Hugging Face cache (other apps may use it — ask)
$model = Join-Path $env:USERPROFILE ".cache\huggingface\hub\models--Systran--faster-whisper-small"
if ((Test-Path $model) -and (Ask (L "Also delete the Whisper speech model (~460 MB, shared cache)? (y/N)" `
                                     "Удалить и модель распознавания речи Whisper (~460 МБ, общий кэш)? (д/Н)"))) {
    Remove-Item $model -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "    OK  $(L 'model removed' 'модель удалена')" -ForegroundColor Green
}

Write-Host ""
Write-Host (L "Call Copilot is removed. Python, Node.js, Claude Code and your ChatGPT/Claude sign-ins were left in place." `
              "Call Copilot удалён. Python, Node.js, Claude Code и вход в ChatGPT/Claude оставлены на месте.") -ForegroundColor Green
if (-not $Quiet) { Read-Host (L "Press Enter to close" "Нажми Enter, чтобы закрыть") | Out-Null }
