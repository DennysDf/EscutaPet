$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$projectDir = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$whisperDir = Join-Path $projectDir "tools\whisper"
$ffmpegDir = Join-Path $projectDir "tools\ffmpeg"
$modelDir = Join-Path $whisperDir "models"
$tempDir = Join-Path ([IO.Path]::GetTempPath()) ("escutapet-transcription-" + [guid]::NewGuid().ToString("N"))

New-Item -ItemType Directory -Force -Path $whisperDir, $ffmpegDir, $modelDir, $tempDir | Out-Null
try {
    $whisperExe = Get-ChildItem $whisperDir -Filter "whisper-cli.exe" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $whisperExe) {
        Write-Host "Baixando whisper.cpp 1.8.4 para Windows x64..."
        $archive = Join-Path $tempDir "whisper.zip"
        Invoke-WebRequest "https://github.com/ggml-org/whisper.cpp/releases/download/v1.8.4/whisper-bin-x64.zip" -OutFile $archive
        Expand-Archive -Path $archive -DestinationPath $whisperDir -Force
    }

    $model = Join-Path $modelDir "ggml-base-q5_1.bin"
    if (-not (Test-Path $model)) {
        Write-Host "Baixando modelo Whisper base multilíngue quantizado..."
        Invoke-WebRequest "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base-q5_1.bin?download=true" -OutFile $model
    }

    $ffmpegExe = Get-ChildItem $ffmpegDir -Filter "ffmpeg.exe" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $ffmpegExe) {
        Write-Host "Baixando FFmpeg para converter OGG, Opus, WebM e outros formatos..."
        $archive = Join-Path $tempDir "ffmpeg.zip"
        Invoke-WebRequest "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip" -OutFile $archive
        Expand-Archive -Path $archive -DestinationPath $ffmpegDir -Force
    }

    $whisperExe = Get-ChildItem $whisperDir -Filter "whisper-cli.exe" -Recurse | Select-Object -First 1
    $ffmpegExe = Get-ChildItem $ffmpegDir -Filter "ffmpeg.exe" -Recurse | Select-Object -First 1
    if (-not $whisperExe -or -not $ffmpegExe -or -not (Test-Path $model)) {
        throw "Um ou mais componentes não foram encontrados após o download."
    }
    Write-Host "Whisper: $($whisperExe.FullName)"
    Write-Host "Modelo: $model"
    Write-Host "FFmpeg: $($ffmpegExe.FullName)"
}
finally {
    if (Test-Path $tempDir) { Remove-Item -LiteralPath $tempDir -Recurse -Force }
}
