$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$managerDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectDir = [IO.Path]::GetFullPath((Join-Path $managerDir "..\.."))
$buildVenv = Join-Path $managerDir ".build-venv"
$buildDir = Join-Path $managerDir "build"
$iconFile = Join-Path $buildDir "EscutaPet.ico"
$logFile = Join-Path $buildDir "ultimo_build.log"
$requirements = Join-Path $managerDir "requirements_manager.txt"
$iconScript = Join-Path $managerDir "prepare_windows_icon.py"
$managerScript = Join-Path $managerDir "escutapet_server_manager.py"
$versionFile = Join-Path $managerDir "version_info.txt"
$outputExe = Join-Path $projectDir "EscutaPet_Gerenciador.exe"
$transcriptStarted = $false
$exitCode = 0

New-Item -ItemType Directory -Force -Path $buildDir | Out-Null
try {
    Start-Transcript -Path $logFile -Force | Out-Null
    $transcriptStarted = $true
} catch {
    Write-Host "Aviso: nao foi possivel iniciar o transcript do PowerShell."
}

function Run-Step {
    param(
        [Parameter(Mandatory = $true)][string]$Title,
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $false)][string[]]$Arguments = @()
    )
    Write-Host ""
    Write-Host ("==> " + $Title) -ForegroundColor Cyan
    Write-Host ($Executable + " " + ($Arguments -join " ")) -ForegroundColor DarkGray
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Title falhou com codigo $LASTEXITCODE."
    }
}

function Find-Python {
    # O Python Launcher devolve texto no stderr quando uma versao nao esta
    # instalada. Isso e esperado durante a busca; nao deve interromper o
    # PowerShell antes de testar as outras versoes.
    $previousErrorAction = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $launcher = Get-Command "py.exe" -ErrorAction SilentlyContinue
        if ($launcher) {
            foreach ($version in @("3.15", "3.14", "3.13", "3.12", "3.11")) {
                & $launcher.Source "-$version" -c "import sys; print(sys.executable)" *> $null
                if ($LASTEXITCODE -eq 0) {
                    return @{ Exe = $launcher.Source; Prefix = @("-$version") }
                }
            }
        }
        $python = Get-Command "python.exe" -ErrorAction SilentlyContinue
        if ($python) {
            & $python.Source -c "import sys; print(sys.executable)" *> $null
            if ($LASTEXITCODE -eq 0) {
                return @{ Exe = $python.Source; Prefix = @() }
            }
        }
        return $null
    } finally {
        $ErrorActionPreference = $previousErrorAction
    }
}

try {
    Write-Host "====================================================="
    Write-Host " ESCUTAPET 3.6.0 - COMPILADOR DO GERENCIADOR"
    Write-Host "====================================================="
    Write-Host ("Projeto: " + $projectDir)
    Write-Host ("Log: " + $logFile)

    foreach ($requiredFile in @($requirements, $iconScript, $managerScript, $versionFile)) {
        if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) {
            throw "Arquivo obrigatorio nao encontrado: $requiredFile"
        }
    }
    if (-not (Test-Path -LiteralPath (Join-Path $projectDir "launcher.py") -PathType Leaf)) {
        throw "A pasta raiz do EscutaPet nao foi reconhecida: $projectDir"
    }

    $python = Find-Python
    if (-not $python) {
        throw "Python nao encontrado. Instale Python 3.11, 3.12, 3.13, 3.14 ou 3.15 com o Python Launcher."
    }
    Write-Host ("Python selecionado: " + $python.Exe + " " + ($python.Prefix -join " ")) -ForegroundColor Green

    $venvPython = Join-Path $buildVenv "Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        $venvArgs = @()
        $venvArgs += $python.Prefix
        $venvArgs += @("-m", "venv", $buildVenv)
        Run-Step "Criando ambiente isolado de compilacao" $python.Exe $venvArgs
    }
    if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        throw "O ambiente de compilacao nao criou Scripts\python.exe."
    }

    Run-Step "Atualizando pip" $venvPython @("-m", "pip", "install", "--upgrade", "pip", "--disable-pip-version-check")
    Run-Step "Instalando PyInstaller, Pillow e pystray" $venvPython @("-m", "pip", "install", "-r", $requirements, "--no-input", "--disable-pip-version-check")
    Run-Step "Gerando icone do Windows" $venvPython @($iconScript, $projectDir, $iconFile)

    $pyinstaller = Join-Path $buildVenv "Scripts\pyinstaller.exe"
    if (-not (Test-Path -LiteralPath $pyinstaller -PathType Leaf)) {
        throw "PyInstaller nao foi encontrado em $pyinstaller"
    }
    if (Test-Path -LiteralPath $outputExe) {
        try {
            $stream = [IO.File]::Open($outputExe, [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
            $stream.Close()
        } catch {
            throw "Feche o EscutaPet_Gerenciador.exe antes de recompilar. O arquivo esta em uso."
        }
    }

    $pyinstallerArgs = @(
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name", "EscutaPet_Gerenciador",
        "--icon", $iconFile,
        "--version-file", $versionFile,
        "--hidden-import", "pystray._win32",
        "--distpath", $projectDir,
        "--workpath", (Join-Path $buildDir "work"),
        "--specpath", $buildDir,
        $managerScript
    )
    Run-Step "Compilando executavel" $pyinstaller $pyinstallerArgs

    if (-not (Test-Path -LiteralPath $outputExe -PathType Leaf)) {
        throw "O PyInstaller terminou sem criar $outputExe"
    }
    $sizeMb = [Math]::Round((Get-Item -LiteralPath $outputExe).Length / 1MB, 2)
    Write-Host ""
    Write-Host "GERENCIADOR CRIADO COM SUCESSO" -ForegroundColor Green
    Write-Host ("Arquivo: " + $outputExe)
    Write-Host ("Tamanho: " + $sizeMb + " MB")
    Write-Host "O icone foi obtido da identidade visual atual do EscutaPet."
} catch {
    $exitCode = 1
    Write-Host ""
    Write-Host "ERRO AO GERAR O GERENCIADOR" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host ("Log completo: " + $logFile)
} finally {
    if ($transcriptStarted) {
        try { Stop-Transcript | Out-Null } catch {}
    }
}

exit $exitCode
