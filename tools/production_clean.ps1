$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$toolsDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectDir = [IO.Path]::GetFullPath((Join-Path $toolsDir ".."))
$cleanerScript = Join-Path $toolsDir "production_clean.py"
$venvPython = Join-Path $projectDir ".venv\Scripts\python.exe"

function Test-AppPython {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $false)][string[]]$Prefix = @()
    )
    $previousErrorAction = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $Executable @Prefix -c "import sqlalchemy, sys; print(sys.executable)" *> $null
        return ($LASTEXITCODE -eq 0)
    } finally {
        $ErrorActionPreference = $previousErrorAction
    }
}

function Find-Python {
    # py.exe escreve uma mensagem de erro quando uma versao consultada nao
    # existe. Durante a busca isso e normal e nao pode encerrar o processo.
    $previousErrorAction = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $launcher = Get-Command "py.exe" -ErrorAction SilentlyContinue
        if ($launcher) {
            foreach ($version in @("3.15", "3.14", "3.13", "3.12", "3.11")) {
                if (Test-AppPython -Executable $launcher.Source -Prefix @("-$version")) {
                    return @{ Exe = $launcher.Source; Prefix = @("-$version") }
                }
            }
        }
        $python = Get-Command "python.exe" -ErrorAction SilentlyContinue
        if ($python) {
            if (Test-AppPython -Executable $python.Source) {
                return @{ Exe = $python.Source; Prefix = @() }
            }
        }
        return $null
    } finally {
        $ErrorActionPreference = $previousErrorAction
    }
}

try {
    if (-not (Test-Path -LiteralPath $cleanerScript -PathType Leaf)) {
        throw "Arquivo não encontrado: $cleanerScript"
    }
    if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
        if (-not (Test-AppPython -Executable $venvPython)) {
            throw "O ambiente .venv existe, mas não contém SQLAlchemy. Execute INSTALAR.bat antes da limpeza."
        }
        $python = @{ Exe = $venvPython; Prefix = @() }
    } else {
        $python = Find-Python
    }
    if (-not $python) {
        throw "Nenhum Python com as dependências do EscutaPet foi encontrado. Execute INSTALAR.bat antes da limpeza."
    }
    Write-Host ("Python selecionado: " + $python.Exe + " " + ($python.Prefix -join " ")) -ForegroundColor Green
    $pythonArguments = @()
    $pythonArguments += $python.Prefix
    $pythonArguments += @($cleanerScript, "--confirm", "APAGAR")
    & $python.Exe @pythonArguments
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
    exit 0
} catch {
    Write-Host ("ERRO: " + $_.Exception.Message) -ForegroundColor Red
    exit 2
}
