# Call Copilot: connect a model subscription. Installs what is missing (Node.js + Codex CLI into the app
# folder, or Claude Code with its official installer) and opens the account sign-in.
# Used by the app (Settings → Connect) and by setup.ps1. Exit code: 0 — connected, 2 — installed but not
# signed in, 1 — failed.
param(
    [ValidateSet("codex", "claude")][string]$Backend = "codex",
    [string]$Dest = $PSScriptRoot,
    [ValidateSet("", "en", "ru")][string]$Lang = "",
    [switch]$NoLogin,   # install only, do not open the sign-in
    [switch]$Embedded   # called from setup.ps1: no banner, no pause
)
$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"
[Console]::OutputEncoding = [Text.Encoding]::UTF8
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
if (-not $Lang) {
    # same rule as the app (copilot/i18n.py): the Windows display language
    try {
        Add-Type -Namespace CallCopilot -Name Lang -ErrorAction Stop -MemberDefinition `
            '[DllImport("kernel32.dll")] public static extern ushort GetUserDefaultUILanguage();'
        $Lang = if (([CallCopilot.Lang]::GetUserDefaultUILanguage() -band 0x3FF) -eq 0x19) { "ru" } else { "en" }
    } catch {
        $Lang = if ([Globalization.CultureInfo]::InstalledUICulture.TwoLetterISOLanguageName -eq "ru") { "ru" } else { "en" }
    }
}
function L($en, $ru) { if ($Lang -eq "ru") { $ru } else { $en } }

$CodexVersion = "0.162.1"  # tested Codex CLI version
$Tools = Join-Path $Dest "tools"
$Name = if ($Backend -eq "codex") { "ChatGPT" } else { "Claude" }

function Ok($text) { Write-Host "    OK  $text" -ForegroundColor Green }
function Info($text) { Write-Host "    ... $text" -ForegroundColor Gray }
function Warn($text) { Write-Host "    !   $text" -ForegroundColor Yellow }
function Finish($code, $text) {
    if ($text) { Write-Host ""; Write-Host $text -ForegroundColor $(if ($code -eq 0) { "Green" } else { "Red" }) }
    if (-not $Embedded) {
        if ($code -eq 0) { Write-Host (L "This window closes in a moment — go back to Call Copilot." "Окно сейчас закроется — возвращайся в Call Copilot."); Start-Sleep 3 }
        else { Read-Host (L "Press Enter to close" "Нажми Enter, чтобы закрыть") | Out-Null }
    }
    exit $code
}
function Has($cmd) { [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }
function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}
function Download($url, $out) {
    Info "$(L 'downloading' 'скачиваю') $url"
    try { Invoke-WebRequest -Uri $url -OutFile $out -UseBasicParsing -ErrorAction Stop; return $true }
    catch { Warn "$(L 'could not download' 'не получилось скачать') $url ($_)"; return $false }
}

if (-not $Embedded) {
    Write-Host "==============================================" -ForegroundColor Magenta
    Write-Host "  Call Copilot — $(L 'connecting' 'подключение') $Name" -ForegroundColor Magenta
    Write-Host "==============================================" -ForegroundColor Magenta
}

if ($Backend -eq "codex") {
    function Find-Node {
        $local = Join-Path $Tools "node\node.exe"
        if (Test-Path $local) { return $local }
        if (Has node) {
            $n = (Get-Command node).Source
            try { $major = [int](("$(& $n --version)".Trim() -replace '^v', '').Split('.')[0]) } catch { $major = 0 }
            if ($major -ge 18) { return $n }
        }
        return $null
    }
    $node = Find-Node
    if (-not $node) {
        Info (L "Node.js not found — putting a portable copy into the app folder (nothing installed system-wide)" "Node.js не найден — кладу портативную версию в папку программы (без установки в систему)")
        try { $lts = (Invoke-RestMethod "https://nodejs.org/dist/index.json" -UseBasicParsing -ErrorAction Stop |
                      Where-Object { $_.lts } | Select-Object -First 1).version }
        catch { Finish 1 (L "Could not reach nodejs.org — check your internet connection." "Не получилось связаться с nodejs.org — проверь интернет.") }
        $zip = Join-Path $env:TEMP "node-$lts.zip"
        if (-not (Download "https://nodejs.org/dist/$lts/node-$lts-win-x64.zip" $zip)) { Finish 1 (L "Could not download Node.js." "Не получилось скачать Node.js.") }
        New-Item -ItemType Directory -Force $Tools | Out-Null
        try { Expand-Archive $zip -DestinationPath $Tools -Force -ErrorAction Stop } catch { Finish 1 "$(L 'Could not unpack Node.js' 'Не распаковался Node.js'): $_" }
        if (Test-Path (Join-Path $Tools "node")) { Remove-Item (Join-Path $Tools "node") -Recurse -Force }
        Rename-Item (Join-Path $Tools "node-$lts-win-x64") "node"
        $node = Join-Path $Tools "node\node.exe"
    }
    Ok "Node.js: $node"
    $codexJs = Join-Path $Tools "node_modules\@openai\codex\bin\codex.js"
    if (-not (Test-Path $codexJs)) {
        Info (L "installing Codex CLI $CodexVersion into the app folder" "ставлю Codex CLI $CodexVersion в папку программы")
        $env:Path = (Split-Path $node) + ";" + $env:Path  # npm calls node itself
        & (Join-Path (Split-Path $node) "npm.cmd") install --prefix $Tools --no-fund --no-audit --loglevel=error "@openai/codex@$CodexVersion"
        if (-not (Test-Path $codexJs)) { Finish 1 (L "Could not install Codex CLI." "Не получилось установить Codex CLI.") }
    }
    Ok (L "Codex CLI installed" "Codex CLI установлен")
    $signed = { (& $node $codexJs login status 2>&1 | Out-String) -match "Logged in" }
    if (& $signed) { Ok (L "already signed in to ChatGPT" "вход в ChatGPT уже выполнен"); Finish 0 (L "ChatGPT is connected." "ChatGPT подключён.") }
    if ($NoLogin) { Warn (L "not signed in to ChatGPT yet" "вход в ChatGPT пока не выполнен"); Finish 2 $null }
    Info (L "a browser opens now — sign in to your ChatGPT account (a Plus/Pro subscription is needed)" "сейчас откроется браузер — войди в свой аккаунт ChatGPT (нужна подписка Plus/Pro)")
    & $node $codexJs login
    if (& $signed) { Finish 0 (L "ChatGPT is connected." "ChatGPT подключён.") }
    Finish 2 (L "Sign-in was not completed. Try again: Settings → Connect." "Вход не завершён. Попробуй ещё раз: Настройки → Подключить.")
} else {
    function Find-Claude {
        if (Has claude) { return (Get-Command claude).Source }
        $p = Join-Path $env:USERPROFILE ".local\bin\claude.exe"
        if (Test-Path $p) { return $p }
        return $null
    }
    if (-not (Has git)) {  # Claude Code on Windows works through Git Bash
        Info (L "Git not found — installing" "Git не найден — устанавливаю")
        if (Has winget) {
            & winget install -e --id Git.Git --silent --accept-package-agreements --accept-source-agreements | Out-Host
            Refresh-Path
        }
        if (-not (Has git)) { Warn (L "Git was not installed — if Claude Code does not start, install Git from git-scm.com" "Git не установился — если Claude Code не запустится, поставь Git с git-scm.com") }
    }
    $claude = Find-Claude
    if (-not $claude) {
        Info (L "installing Claude Code with the official installer" "устанавливаю Claude Code официальным установщиком")
        try { Invoke-RestMethod "https://claude.ai/install.ps1" -UseBasicParsing -ErrorAction Stop | Invoke-Expression } catch { Warn "$_" }
        Refresh-Path
        $claude = Find-Claude
    }
    if (-not $claude) { Finish 1 (L "Could not install Claude Code (https://claude.com/claude-code)." "Не получилось установить Claude Code (https://claude.com/claude-code).") }
    Ok "Claude Code: $claude"
    $signed = { try { ((& $claude auth status --json 2>$null | Out-String) | ConvertFrom-Json).loggedIn -eq $true } catch { $false } }
    if (& $signed) { Ok (L "already signed in to Claude" "вход в Claude уже выполнен"); Finish 0 (L "Claude is connected." "Claude подключён.") }
    if ($NoLogin) { Warn (L "not signed in to Claude yet" "вход в Claude пока не выполнен"); Finish 2 $null }
    Info (L "a browser opens now — sign in to your Claude account (a Pro/Max subscription is needed)" "сейчас откроется браузер — войди в свой аккаунт Claude (нужна подписка Pro/Max)")
    & $claude auth login --claudeai
    if (& $signed) { Finish 0 (L "Claude is connected." "Claude подключён.") }
    Finish 2 (L "Sign-in was not completed. Try again: Settings → Connect." "Вход не завершён. Попробуй ещё раз: Настройки → Подключить.")
}
