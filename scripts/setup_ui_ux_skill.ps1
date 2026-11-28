$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { throw "Node.js is required to install UI/UX Pro Max." }
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { throw "npm is required to install UI/UX Pro Max." }
npm exec --yes --package=ui-ux-pro-max-cli@2.15.0 -- uipro init --ai universal --force
Write-Host ""
Write-Host "UI/UX Pro Max installed under .agents/skills/ui-ux-pro-max/"
Write-Host "Review the generated files, then commit them if you want the full skill versioned with Planline."
