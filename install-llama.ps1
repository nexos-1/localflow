# LocalFlow - AI-Cleanup-Engine (llama.cpp + Gemma 3 4B) installieren.
# Wird von install.ps1 aufgerufen; einzeln:
#   powershell -ExecutionPolicy Bypass -File install-llama.ps1 [-DataDir <ordner>]
#
# Laedt llama-server (llama.cpp b10991 vom 2026-09-15, Vulkan-Build) und das
# Modell gemma-3-4b-it-Q4_K_M.gguf (ggml-org, Revision vom 2025-05-21) nach
# <DataDir>\llamacpp\. Beide Downloads sind gepinnt und per SHA-256 geprueft
# (14-Tage-Regel). Vorhandene Dateien bleiben unangetastet.
#
# Warum Vulkan statt CUDA: gemessen 2026-10-08 auf RTX 5080 gleich schnell
# im Diktat (228 vs. 220 ms Median), aber 30 MB statt 546 MB (CUDA-Runtime)
# und laeuft auf jeder GPU (NVIDIA/AMD/Intel); ohne GPU nutzt der Build die CPU.
# Exit-Code 0 = Engine bereit, 1 = nicht verfuegbar (LocalFlow nutzt dann Ollama).

param([string]$DataDir = "")

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
if (-not $DataDir) {
    $DataDir = if ($env:LOCALFLOW_DATA_DIR) { $env:LOCALFLOW_DATA_DIR } else { Join-Path $PSScriptRoot "data" }
}

$LlamaTag = "b10991"
$LlamaAsset = "llama-$LlamaTag-bin-win-vulkan-x64.zip"
$LlamaSha = "591c715f6a5727854e1c1f137afc985edca565e8b50225c80444e7f48c4cf59a"
$ModelRev = "d0976223747697cb51e056d85c532013931fe52e"
$ModelFile = "gemma-3-4b-it-Q4_K_M.gguf"
$ModelSha = "882e8d2db44dc554fb0ea5077cb7e4bc49e7342a1f0da57901c0802ea21a0863"

$binDir = Join-Path $DataDir "llamacpp\bin"
$modelDir = Join-Path $DataDir "llamacpp\models"
$server = Join-Path $binDir "llama-server.exe"
$model = Join-Path $modelDir $ModelFile

function Get-Verified([string]$url, [string]$target, [string]$sha) {
    # curl.exe (Windows 10+) ist bei GB-Dateien deutlich schneller als
    # Invoke-WebRequest unter PowerShell 5.1.
    & curl.exe -fsSL -o $target $url
    if ($LASTEXITCODE -ne 0) { throw "Download fehlgeschlagen: $url" }
    $actual = (Get-FileHash -Algorithm SHA256 $target).Hash.ToLower()
    if ($actual -ne $sha) {
        Remove-Item $target -Force
        throw "SHA-256 stimmt nicht ($target): $actual"
    }
}

try {
    if ($env:PROCESSOR_ARCHITECTURE -ne "AMD64") {
        Write-Host "Hinweis: llama.cpp-Engine nur fuer x64 vorgesehen - Cleanup ueber Ollama." -ForegroundColor Yellow
        exit 1
    }
    if (-not (Test-Path $server)) {
        Write-Host "Lade llama.cpp $LlamaTag ($LlamaAsset, ~30 MB)..."
        New-Item -ItemType Directory -Force $binDir | Out-Null
        $zip = Join-Path ([IO.Path]::GetTempPath()) $LlamaAsset
        Get-Verified "https://github.com/ggml-org/llama.cpp/releases/download/$LlamaTag/$LlamaAsset" $zip $LlamaSha
        Expand-Archive -Path $zip -DestinationPath $binDir -Force
        Remove-Item $zip -Force
    }
    if (-not (Test-Path $model)) {
        Write-Host "Lade Cleanup-Modell $ModelFile (~2,5 GB)..."
        New-Item -ItemType Directory -Force $modelDir | Out-Null
        $part = "$model.part"
        Get-Verified "https://huggingface.co/ggml-org/gemma-3-4b-it-GGUF/resolve/$ModelRev/$ModelFile" $part $ModelSha
        Move-Item $part $model -Force
    }
    Write-Host "AI-Cleanup: llama.cpp $LlamaTag + $ModelFile bereit." -ForegroundColor Green
    exit 0
} catch {
    Write-Host "Hinweis: llama.cpp-Engine nicht installiert ($($_.Exception.Message))" -ForegroundColor Yellow
    exit 1
}
