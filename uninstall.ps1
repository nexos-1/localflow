# LocalFlow entfernen - Logik (Doppelklick-Einstieg: uninstall.bat).
#   -Root:   Installationsordner (kommt von uninstall.bat)
#   -DryRun: nur anzeigen, was passieren wuerde (nichts aendern, keine Fragen)
#
# Entfernt alle Spuren AUSSERHALB des Ordners (App beenden, Autostart,
# Startmenue) und bietet optional an: Whisper-Modell-Cache (~1,6 GB),
# Ollama-Modell gemma3:4b, Alt-Datenordner (%APPDATA%\LocalFlow, Layout
# vor v0.2) und zum Schluss den kompletten Ordner inkl. Diktat-History.
param(
    [string]$Root = $PSScriptRoot,
    [switch]$DryRun
)
$ErrorActionPreference = "SilentlyContinue"
$Root = (Resolve-Path $Root).Path.TrimEnd("\") + "\"

function Ask($frage) {
    if ($DryRun) { return $false }
    return (Read-Host "$frage [j/N]") -match "^[jJyY]"
}

Write-Host "== LocalFlow entfernen ==" -ForegroundColor Cyan
if ($DryRun) { Write-Host "(DRY-RUN: es wird nichts geaendert)" -ForegroundColor Yellow }
Write-Host "Ordner: $Root"

# 1. Laufende LocalFlow-Prozesse (nur DIESER Installation) beenden
$procs = Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
    Where-Object { $_.CommandLine -match [regex]::Escape($Root + "run.py") }
if ($procs) {
    Write-Host "[1] Beende LocalFlow ($(@($procs).Count) Prozess(e))..."
    if (-not $DryRun) { $procs | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }; Start-Sleep 1 }
} else { Write-Host "[1] LocalFlow laeuft nicht." }

# 2. Autostart-Eintrag
$run = Get-ItemProperty "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" -Name LocalFlow
if ($run) {
    Write-Host "[2] Entferne Autostart-Eintrag..."
    if (-not $DryRun) { Remove-ItemProperty "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" -Name LocalFlow -Force }
} else { Write-Host "[2] Kein Autostart-Eintrag." }

# 3. Startmenue-Verknuepfung
$lnk = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\LocalFlow.lnk"
if (Test-Path $lnk) {
    Write-Host "[3] Entferne Startmenue-Verknuepfung..."
    if (-not $DryRun) { Remove-Item $lnk -Force -Confirm:$false }
} else { Write-Host "[3] Keine Startmenue-Verknuepfung." }

# 4. Whisper-Modell-Cache (liegt AUSSERHALB des Ordners, ~1,6 GB)
$hub = "$env:USERPROFILE\.cache\huggingface\hub"
$models = Get-ChildItem $hub -Directory -Filter "models--*faster-whisper*"
foreach ($m in $models) {
    $gb = [math]::Round((Get-ChildItem $m.FullName -Recurse -File | Measure-Object Length -Sum).Sum / 1GB, 1)
    Write-Host "[4] Whisper-Modell-Cache gefunden: $($m.Name) (~$gb GB)"
    if (Ask "    Loeschen? (nur von LocalFlow genutzt, laedt bei Neuinstallation neu)") {
        Remove-Item $m.FullName -Recurse -Force -Confirm:$false
        Write-Host "    geloescht."
    }
}
if (-not $models) { Write-Host "[4] Kein Whisper-Modell-Cache gefunden." }

# 5. Ollama-Cleanup-Modell (Ollama selbst wird NICHT angefasst)
if (Get-Command ollama -ErrorAction SilentlyContinue) {
    $list = & ollama list 2>$null
    if ($list -match "gemma3:4b") {
        Write-Host "[5] Ollama-Modell gemma3:4b vorhanden (~3 GB)."
        if (Ask "    Loeschen? (NUR wenn du es nicht anderweitig nutzt)") {
            & ollama rm gemma3:4b
        }
    } else { Write-Host "[5] Ollama-Modell gemma3:4b nicht vorhanden." }
} else { Write-Host "[5] Ollama nicht installiert - nichts zu tun." }

# 6. Alt-Datenordner (Layout vor v0.2)
$legacy = "$env:APPDATA\LocalFlow"
if (Test-Path $legacy) {
    Write-Host "[6] Alt-Datenordner gefunden: $legacy (Layout vor v0.2)"
    if (Ask "    Loeschen? (enthaelt ggf. alte History/Config)") {
        Remove-Item $legacy -Recurse -Force -Confirm:$false
        Write-Host "    geloescht."
    }
} else { Write-Host "[6] Kein Alt-Datenordner." }

# 7. Kompletter Ordner (inkl. data\ = DEINE Diktat-History!)
if ($DryRun) {
    Write-Host "[7] (DryRun) Wuerde anbieten, den Ordner inkl. data\ zu loeschen."
    Write-Host "`nDRY-RUN fertig - nichts wurde geaendert." -ForegroundColor Yellow
    exit 0
}
Write-Host ""
Write-Host "ACHTUNG: $($Root)data\ enthaelt deine komplette Diktat-History." -ForegroundColor Yellow
if (Ask "[7] Diesen Ordner KOMPLETT loeschen (App + venv + History)?") {
    Write-Host "Ordner wird in 3 Sekunden entfernt. LocalFlow ist deinstalliert." -ForegroundColor Green
    Start-Process cmd.exe -WorkingDirectory $env:TEMP -WindowStyle Hidden `
        -ArgumentList "/c timeout /t 3 /nobreak >nul & rd /s /q `"$($Root.TrimEnd('\'))`""
    exit 42   # Signal an uninstall.bat: sofort beenden (Datei verschwindet gleich)
}
Write-Host ""
Write-Host "Fertig. Zum vollstaendigen Entfernen einfach diesen Ordner loeschen." -ForegroundColor Green
Write-Host "(Deine Diktat-History liegt in data\localflow.sqlite, falls du sie behalten willst.)"
exit 0
