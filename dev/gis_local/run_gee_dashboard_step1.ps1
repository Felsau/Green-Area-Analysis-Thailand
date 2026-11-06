# GEE Dashboard processing (scope 2.1.15), step 1: tests + rolled-back probe of migration 048.
# No Google call, no token, no committed database change: the probe applies 048 and a
# lifecycle check inside a transaction that is ROLLED BACK on both local T0 databases.
$ErrorActionPreference = 'Continue'
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repo
$py = Join-Path $repo 'green-area-backend\.venv\Scripts\python.exe'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$log = Join-Path $repo "green-area-backend\.venv\gee-dashboard-step1-$stamp.log"
$gisRuntime = 'C:\Users\chaya\.codex\visualizations\2026\10\04\01a107d9-ff44-7731-8bc3-91814ffd8d51\t0-local-supabase-20261027-v2'

function Step([string]$name, [scriptblock]$body) {
    "===== $name  $(Get-Date -Format s)" | Tee-Object -FilePath $log -Append | Out-Host
    $global:LASTEXITCODE = 0
    & $body 2>&1 | ForEach-Object { "$_" } | Tee-Object -FilePath $log -Append | Out-Host
    "exit=$LASTEXITCODE" | Tee-Object -FilePath $log -Append | Out-Host
}

Step 'git' { git rev-parse --short HEAD; git status --short }
Step 't0 core-start' { & $py -I -B dev/gis_ui/phase5_demo.py core-start --runtime-dir $gisRuntime }
Step 'backend tests' {
    Push-Location green-area-backend
    $env:PYTHONPATH = (Resolve-Path tests).Path
    & .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests\test_gee_dashboard_processing.py tests\test_processing_api.py tests\test_processing_provider.py tests\test_gee_egress_relay.py tests\test_gee_credential_boundary.py
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    Pop-Location
}
Step 'frontend tests' {
    Push-Location green-area-frontend
    npx vitest run src/components/GisManagement.test.js src/utils/gisClient.test.js
    Pop-Location
}
Step 'migration 048 rolled-back probe' { & $py -I -B dev\gis_local\gee_dashboard_local.py probe --runtime-dir $gisRuntime }
"DONE. Log: $log" | Out-Host
