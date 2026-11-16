[CmdletBinding(PositionalBinding=$false)]
param(
    [string]$Python = "",
    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$Arguments
)
$ErrorActionPreference = "Stop"
if (-not $Python) {
    $localPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
    if (Test-Path -LiteralPath $localPython) { $Python = $localPython }
    else { $Python = 'python' }
}
& $Python (Join-Path $PSScriptRoot 'run_imagine.py') @Arguments
exit $LASTEXITCODE
