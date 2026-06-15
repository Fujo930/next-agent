$ErrorActionPreference = "Stop"

Push-Location "$PSScriptRoot\NextAgentGUI"
npm run build
Pop-Location

uv sync --extra dev
uv run --no-sync pyinstaller --noconfirm --clean "$PSScriptRoot\NextAgent.spec"

Write-Host "Built: $PSScriptRoot\dist\NextAgent.exe"
