# Call Copilot installer. Checks everything the app needs on this PC, installs what is missing and puts the app
# into %LOCALAPPDATA%\CallCopilot. No admin rights needed (except the rare case of a missing VC++ Runtime).
# Messages are in Russian on Russian Windows and in English everywhere else (override with -Lang en|ru).
param(
    [ValidateSet("", "codex", "claude")][string]$Backend = "",  # which subscription to use; empty — ask
    [string]$Dest = (Join-Path $env:LOCALAPPDATA "CallCopilot"),
    [ValidateSet("", "en", "ru")][string]$Lang = "",
    [switch]$NoShortcuts,  # for testing the installer: do not touch shortcuts
    [switch]$Unattended    # ask nothing (account sign-in and launching at the end are skipped)
)
# Not Stop: in Windows PowerShell 5.1 any pip/npm/codex output to stderr would then abort the install.
# Errors are checked explicitly — by $LASTEXITCODE and by the files that must exist.
$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"  # otherwise Invoke-WebRequest downloads several times slower
[Console]::OutputEncoding = [Text.Encoding]::UTF8
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

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

$PythonUrl = "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe"
$Steps = 8

function Step($n, $text) { Write-Host ""; Write-Host "[$n/$Steps] $text" -ForegroundColor Cyan }
function Ok($text) { Write-Host "    OK  $text" -ForegroundColor Green }
function Info($text) { Write-Host "    ... $text" -ForegroundColor Gray }
function Warn($text) { Write-Host "    !   $text" -ForegroundColor Yellow }
function Fail($text) {
    Write-Host ""
    Write-Host "$(L 'ERROR' 'ОШИБКА'): $text" -ForegroundColor Red
    if (-not $Unattended) { Read-Host (L "Press Enter to close" "Нажми Enter, чтобы закрыть") | Out-Null }
    exit 1
}
function Has($cmd) { [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }
function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}
function Download($url, $out) {
    Info "$(L 'downloading' 'скачиваю') $url"
    try { Invoke-WebRequest -Uri $url -OutFile $out -UseBasicParsing -ErrorAction Stop }
    catch { Fail "$(L "could not download $url — check your internet connection." "не получилось скачать $url — проверь интернет.") ($_)" }
}
function Set-ShortcutAppId($path, $appId) {
    # System.AppUserModel.ID on a .lnk — WScript.Shell cannot set it, so a small COM helper does
    if (-not ("CallCopilot.Lnk" -as [type])) {
        Add-Type -Language CSharp -TypeDefinition @"
using System; using System.Runtime.InteropServices;
namespace CallCopilot {
  [StructLayout(LayoutKind.Sequential, Pack = 4)] public struct PropertyKey { public Guid fmtid; public uint pid; }
  [StructLayout(LayoutKind.Explicit)] public struct PropVariant {
    [FieldOffset(0)] public ushort vt; [FieldOffset(8)] public IntPtr p; [FieldOffset(16)] public IntPtr p2; }
  [ComImport, Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IPropertyStore {
    void GetCount(out uint c); void GetAt(uint i, out PropertyKey k); void GetValue(ref PropertyKey k, out PropVariant v);
    void SetValue(ref PropertyKey k, ref PropVariant v); void Commit(); }
  [ComImport, Guid("0000010B-0000-0000-C000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IPersistFile {
    void GetClassID(out Guid g); [PreserveSig] int IsDirty();
    void Load([MarshalAs(UnmanagedType.LPWStr)] string f, uint mode); void Save([MarshalAs(UnmanagedType.LPWStr)] string f, bool remember);
    void SaveCompleted([MarshalAs(UnmanagedType.LPWStr)] string f); void GetCurFile([MarshalAs(UnmanagedType.LPWStr)] out string f); }
  public static class Lnk {
    static PropertyKey Key() { return new PropertyKey { fmtid = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), pid = 5 }; }
    static object Open(string path) {
      object link = Activator.CreateInstance(Type.GetTypeFromCLSID(new Guid("00021401-0000-0000-C000-000000000046")));
      ((IPersistFile)link).Load(path, 2); return link; }
    public static void SetAppId(string path, string appId) {
      object link = Open(path); var key = Key();
      var pv = new PropVariant { vt = 31, p = Marshal.StringToCoTaskMemUni(appId) };
      try { var ps = (IPropertyStore)link; ps.SetValue(ref key, ref pv); ps.Commit(); ((IPersistFile)link).Save(path, true); }
      finally { Marshal.FreeCoTaskMem(pv.p); } }
    public static string GetAppId(string path) {
      object link = Open(path); var key = Key(); PropVariant pv;
      ((IPropertyStore)link).GetValue(ref key, out pv);
      return pv.vt == 31 ? Marshal.PtrToStringUni(pv.p) : null; }
  }
}
"@
    }
    [CallCopilot.Lnk]::SetAppId($path, $appId)
}
function Winget-Install($id, $extra = @()) {
    if (-not (Has winget)) { return }
    Info "winget install $id"
    & winget install -e --id $id --silent --accept-package-agreements --accept-source-agreements @extra | Out-Host
    Refresh-Path
}

Write-Host "==============================================" -ForegroundColor Magenta
Write-Host "  Call Copilot — $(L 'setup' 'установка')" -ForegroundColor Magenta
Write-Host "  $(L 'Folder' 'Папка'): $Dest" -ForegroundColor Magenta
Write-Host "==============================================" -ForegroundColor Magenta

# ---------- 1. App files ----------
Step 1 (L "Copying the app" "Копирую программу")
$Src = Join-Path $PSScriptRoot "app"  # the zip release has an app folder next to Setup.cmd
$Repo = Split-Path $PSScriptRoot -Parent
if (-not (Test-Path $Src)) {
    $zip = Join-Path $PSScriptRoot "app.zip"  # Setup.exe brings it as an archive
    $tmpSrc = Join-Path $env:TEMP "CallCopilot-app"
    if (Test-Path $tmpSrc) { Remove-Item $tmpSrc -Recurse -Force }
    if (Test-Path $zip) {
        try { Expand-Archive $zip -DestinationPath $tmpSrc -Force -ErrorAction Stop } catch { Fail "$(L 'could not unpack app.zip' 'не распаковался app.zip'): $_" }
    } elseif (Test-Path (Join-Path $Repo "app.py")) {
        # run from a git checkout (installer\Setup.cmd): take only the app files, not .venv / logs / personal data
        New-Item -ItemType Directory -Force (Join-Path $tmpSrc "copilot"), (Join-Path $tmpSrc "assets") | Out-Null
        foreach ($f in "app.py", "run.bat", "requirements.txt", "README.md", "README.ru.md", "LICENSE", "assets\icon.ico") {
            if (Test-Path (Join-Path $Repo $f)) { Copy-Item (Join-Path $Repo $f) (Join-Path $tmpSrc $f) }
        }
        Copy-Item (Join-Path $Repo "copilot\*.py") (Join-Path $tmpSrc "copilot")
        Copy-Item (Join-Path $PSScriptRoot "uninstall.ps1"), (Join-Path $PSScriptRoot "Uninstall.cmd"), (Join-Path $PSScriptRoot "connect.ps1") $tmpSrc
    } else {
        Fail (L "There is no app folder or app.zip next to the installer" "Рядом с установщиком нет папки app или app.zip")
    }
    $Src = $tmpSrc
}
New-Item -ItemType Directory -Force $Dest | Out-Null
# Only code is overwritten: About me, Context, settings and logs survive an update.
try { Copy-Item -Path (Join-Path $Src "*") -Destination $Dest -Recurse -Force -ErrorAction Stop }
catch { Fail "$(L 'could not copy the files (is the app running? close it)' 'не получилось скопировать файлы (программа сейчас запущена? закрой её)'): $_" }
Ok "$(L 'files in' 'файлы в') $Dest"

# ---------- 2. Python ----------
Step 2 (L "Checking Python (3.10–3.13 required)" "Проверяю Python (нужен 3.10–3.13)")
function Find-Python {
    $cands = @()
    foreach ($v in "312", "311", "313", "310") {
        $cands += Join-Path $env:LOCALAPPDATA "Programs\Python\Python$v\python.exe"
        $cands += Join-Path $env:ProgramFiles "Python$v\python.exe"
    }
    if (Has py) {
        foreach ($v in "3.12", "3.11", "3.13", "3.10") {
            try { $p = & py "-$v" -c "import sys; print(sys.executable)" 2>$null; if ($LASTEXITCODE -eq 0 -and $p) { $cands += "$p".Trim() } } catch {}
        }
    }
    if (Has python) { $cands += (Get-Command python).Source }
    foreach ($c in $cands) {
        if ($c -and ($c -notlike "*WindowsApps*") -and (Test-Path $c)) {  # the Microsoft Store stub does not count
            try { $ver = & $c -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null } catch { continue }
            if ("$ver".Trim() -in "3.10", "3.11", "3.12", "3.13") { return $c }
        }
    }
    return $null
}
$py = Find-Python
if (-not $py) {
    Info (L "no suitable Python found — installing Python 3.12" "подходящий Python не найден — устанавливаю Python 3.12")
    Winget-Install "Python.Python.3.12" @("--scope", "user")
    $py = Find-Python
    if (-not $py) {
        $exe = Join-Path $env:TEMP "python-3.12-setup.exe"
        Download $PythonUrl $exe
        Start-Process $exe -ArgumentList "/quiet InstallAllUsers=0 PrependPath=1 Include_test=0" -Wait
        $py = Find-Python
    }
    if (-not $py) { Fail (L "Could not install Python. Install Python 3.12 from python.org and run the setup again." "Не получилось установить Python. Поставь Python 3.12 с python.org и запусти установку ещё раз.") }
}
Ok "Python: $py"

# ---------- 3. Visual C++ Runtime (needed by speech recognition and the UI) ----------
Step 3 (L "Checking Microsoft Visual C++ Runtime" "Проверяю Microsoft Visual C++ Runtime")
if (Test-Path "$env:SystemRoot\System32\vcruntime140_1.dll") {
    Ok (L "already installed" "уже установлен")
} else {
    Info (L "not found — installing (Windows will ask for admin permission)" "не найден — устанавливаю (Windows попросит разрешение администратора)")
    $exe = Join-Path $env:TEMP "vc_redist.x64.exe"
    Download "https://aka.ms/vs/17/release/vc_redist.x64.exe" $exe
    try { Start-Process $exe -ArgumentList "/install /quiet /norestart" -Verb RunAs -Wait } catch { Warn "$(L 'install cancelled' 'установка отменена'): $_" }
    if (Test-Path "$env:SystemRoot\System32\vcruntime140_1.dll") { Ok (L "installed" "установлен") }
    else { Warn (L "VC++ Runtime is not installed — if the app does not start, install it manually: https://aka.ms/vs/17/release/vc_redist.x64.exe" "VC++ Runtime не установлен — если программа не запустится, поставь его вручную: https://aka.ms/vs/17/release/vc_redist.x64.exe") }
}

# ---------- 4. Python environment and libraries ----------
Step 4 (L "Installing libraries (speech recognition, UI, audio) — a few minutes" "Устанавливаю библиотеки (распознавание речи, интерфейс, звук) — несколько минут")
$venvPy = Join-Path $Dest ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    & $py -m venv (Join-Path $Dest ".venv")
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $venvPy)) { Fail (L "could not create the Python environment" "не получилось создать окружение Python") }
}
& $venvPy -m pip install --upgrade pip --quiet --disable-pip-version-check
& $venvPy -m pip install -r (Join-Path $Dest "requirements.txt") --disable-pip-version-check --progress-bar on
if ($LASTEXITCODE -ne 0) { Fail (L "pip could not install the libraries (check your internet connection and run again)" "pip не смог установить библиотеки (проверь интернет и запусти ещё раз)") }
& $venvPy -c "import faster_whisper, pyaudiowpatch, keyboard; from PyQt6 import QtWidgets"
if ($LASTEXITCODE -ne 0) { Fail (L "the libraries are installed but do not load (installing the VC++ Runtime often helps)" "библиотеки установились, но не загружаются (часто помогает установка VC++ Runtime)") }
Ok (L "libraries are in place" "библиотеки на месте")

# ---------- 5. Choosing the subscription ----------
Step 5 (L "Choosing which subscription runs the model" "Выбираю, через какую подписку работает модель")
if (-not $Backend) {
    if ($Unattended) { $Backend = "codex" } else {
        Write-Host "    1 — ChatGPT (Codex)   [$(L 'default' 'по умолчанию')]"
        Write-Host "    2 — Claude (Claude Code)"
        $a = Read-Host (L "    Type 1 or 2" "    Введи 1 или 2")
        $Backend = if ("$a".Trim() -eq "2") { "claude" } else { "codex" }
    }
}
& $venvPy -c "import json, os, sys; p = sys.argv[1]; c = json.load(open(p, encoding='utf-8')) if os.path.exists(p) else {}; c['backend'] = sys.argv[2]; json.dump(c, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)" (Join-Path $Dest "config.json") $Backend
Ok "$(L 'subscription' 'подписка'): $Backend"

# ---------- 6. The model: Codex CLI or Claude Code (shared with Settings → Connect in the app) ----------
Step 6 (L "Connecting the model" "Подключаю модель")
$connectArgs = @{ Backend = $Backend; Dest = $Dest; Lang = $Lang; Embedded = $true; NoLogin = [bool]$Unattended }
& (Join-Path $Dest "connect.ps1") @connectArgs
if ($LASTEXITCODE -eq 1) { Fail (L "could not connect the model — see the messages above" "не получилось подключить модель — см. сообщения выше") }
if ($LASTEXITCODE -eq 2) { Warn (L "not signed in yet — sign in later in the app: Settings → Connect" "вход пока не выполнен — войди позже в программе: Настройки → Подключить") }

# ---------- 7. Speech recognition model ----------
Step 7 (L "Downloading the Whisper small speech recognition model (~460 MB, once)" "Скачиваю модель распознавания речи Whisper small (~460 МБ, один раз)")
& $venvPy -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8')"
if ($LASTEXITCODE -ne 0) { Warn (L "the model was not downloaded — the app will download it on first launch" "модель не скачалась — программа скачает её при первом запуске") } else { Ok (L "model ready" "модель готова") }

# ---------- 8. Shortcuts ----------
Step 8 (L "Creating shortcuts" "Создаю ярлыки")
$pyw = Join-Path $Dest ".venv\Scripts\pythonw.exe"
if ($NoShortcuts) {
    Info (L "skipped (-NoShortcuts)" "пропускаю (-NoShortcuts)")
} else {
    $sh = New-Object -ComObject WScript.Shell
    $places = @([Environment]::GetFolderPath("Desktop"), (Join-Path ([Environment]::GetFolderPath("Programs")) ""))
    foreach ($dir in $places) {
        $lnk = Join-Path $dir "Call Copilot.lnk"
        $s = $sh.CreateShortcut($lnk)
        $s.TargetPath = $pyw
        $s.Arguments = "`"$(Join-Path $Dest 'app.py')`""
        $s.WorkingDirectory = $Dest
        $s.IconLocation = (Join-Path $Dest "assets\icon.ico") + ",0"
        $s.Description = L "Call Copilot — hints during calls" "Call Copilot — подсказки во время созвона"
        $s.Save()
        # the same app id the window uses — the taskbar then takes the icon from this shortcut and pins it correctly
        try { Set-ShortcutAppId $lnk "CallCopilot.App" } catch { Warn "$(L 'could not tag the shortcut' 'не получилось пометить ярлык'): $_" }
    }
    Ok (L "desktop and Start menu" "рабочий стол и меню «Пуск»")
    # entry in Settings → Apps (per user, no admin) so the app can be removed like any other
    $key = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\CallCopilot"
    New-Item -Path $key -Force | Out-Null
    $kb = [int]((Get-ChildItem $Dest -Recurse -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum / 1KB)
    $props = @{
        DisplayName = "Call Copilot"; DisplayVersion = "1.0.0"; Publisher = "Call Copilot contributors"
        DisplayIcon = (Join-Path $Dest "assets\icon.ico"); InstallLocation = $Dest
        UninstallString = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$(Join-Path $Dest 'uninstall.ps1')`""
        QuietUninstallString = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$(Join-Path $Dest 'uninstall.ps1')`" -Quiet"
    }
    foreach ($k in $props.Keys) { New-ItemProperty -Path $key -Name $k -Value $props[$k] -PropertyType String -Force | Out-Null }
    foreach ($k in "NoModify", "NoRepair") { New-ItemProperty -Path $key -Name $k -Value 1 -PropertyType DWord -Force | Out-Null }
    New-ItemProperty -Path $key -Name EstimatedSize -Value $kb -PropertyType DWord -Force | Out-Null
    Ok (L "added to Settings → Apps (uninstall from there or with Uninstall.cmd in the app folder)" "добавлено в «Параметры → Приложения» (удалить можно оттуда или через Uninstall.cmd в папке программы)")
}

Write-Host ""
Write-Host (L "Done! Call Copilot is installed." "Готово! Call Copilot установлен.") -ForegroundColor Green
Write-Host (L "Before a call, fill in the About me tab (once) and Context (for each call)." "Перед созвоном заполни вкладку «Обо мне» (один раз) и «Контекст» (под каждый созвон).")
if (-not $Unattended) {
    $a = Read-Host (L "Launch now? (Enter — yes, n — no)" "Запустить сейчас? (Enter — да, n — нет)")
    if ("$a".Trim().ToLower() -ne "n") { Start-Process $pyw -ArgumentList "`"$(Join-Path $Dest 'app.py')`"" -WorkingDirectory $Dest }
}
