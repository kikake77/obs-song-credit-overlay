$ErrorActionPreference = "Stop"

Set-Location -LiteralPath $PSScriptRoot
python -m PyInstaller --noconfirm --clean SongCreditManager.spec

Write-Host ""
Write-Host "Build complete: $PSScriptRoot\dist\SongCreditManagerForOBS.exe"
