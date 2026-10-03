# Windows equivalent of the Makefile: ./run.ps1 <target> [doc]
# Uses .venv\Scripts\python.exe when present, else `python` on PATH.
param(
    [Parameter(Mandatory = $true)][string]$Target,
    [string]$Doc
)
$ErrorActionPreference = 'Stop'
$py = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) { $py = 'python' }

switch ($Target) {
    'setup'      { & $py -m pip install -e ".[dev,llm]" }
    'test'       { & $py -m pytest -q }
    'smoke'      { & $py -m pytest -q -m smoke }
    'api'        { & $py -m navigator api }
    { $_ -in 'ingest-doc', 'rerun-live' } {
        if (-not $Doc) { throw "usage: ./run.ps1 $Target <path-to-doc>" }
        & $py -m navigator $Target $Doc
    }
    default      { & $py -m navigator $Target }
}
exit $LASTEXITCODE
