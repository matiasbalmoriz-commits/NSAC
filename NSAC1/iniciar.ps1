$python = 'C:\Program Files\QGIS 4.2.3\bin\python-qgis.bat'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    $python = 'python'
}

& $python (Join-Path $PSScriptRoot 'servidor.py') @args
exit $LASTEXITCODE
