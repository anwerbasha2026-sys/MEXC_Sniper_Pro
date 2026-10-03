$ErrorActionPreference = "Stop"

if (-not (Test-Path ".\.env")) {
    Copy-Item ".\.env.example" ".\.env"
    Write-Host ".env created from .env.example"
    Write-Host "Open .env and enter your MEXC API credentials."
} else {
    Write-Host ".env already exists; nothing changed."
}
