param(
    # Skip resuming the existing local T0 core (the gateway probe is then NOT_RUN).
    [switch]$SkipT0
)
# A6 round 2 egress proof, DRY-RUN only. No Google contact, no token, no credential,
# no host firewall change. Creates and removes only Docker resources labelled
# gis.a6.egress.run=<run>. Output is copied into green-area-backend\.venv (gitignored)
# so it can be reviewed afterwards.
$ErrorActionPreference = 'Continue'
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repo
$py = Join-Path $repo 'green-area-backend\.venv\Scripts\python.exe'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$log = Join-Path $repo "green-area-backend\.venv\a6-egress-proof-$stamp.log"
$gisRuntime = 'C:\Users\chaya\.codex\visualizations\2026\10\04\01a107d9-ff44-7731-8bc3-91814ffd8d51\t0-local-supabase-20261027-v2'
$egressRoot = 'C:\Users\chaya\.codex\visualizations\2026\10\04\01a107d9-ff44-7731-8bc3-91814ffd8d51\a6-egress'

function Step([string]$name, [scriptblock]$body) {
    "===== $name  $(Get-Date -Format s)" | Tee-Object -FilePath $log -Append | Out-Host
    $global:LASTEXITCODE = 0
    & $body 2>&1 | ForEach-Object { "$_" } | Tee-Object -FilePath $log -Append | Out-Host
    "exit=$LASTEXITCODE" | Tee-Object -FilePath $log -Append | Out-Host
    return $LASTEXITCODE
}

Step 'git' { git rev-parse --short HEAD; git status --short } | Out-Null
if (-not $SkipT0) {
    Step 't0 core-start' { & $py -I -B dev/gis_ui/phase5_demo.py core-start --runtime-dir $gisRuntime } | Out-Null
}
Step 'windows tests' {
    Push-Location green-area-backend
    # tests/ is a package here, so add it like the boundary image does (/app/tests).
    $env:PYTHONPATH = (Resolve-Path tests).Path
    & .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests\test_gee_egress_relay.py tests\test_gee_credential_boundary.py tests\test_gee_genuine_foundation.py tests\test_gee_sdk_transport.py
    Pop-Location
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
} | Out-Null
$build = Step 'egress build' { & $py -I -B dev\gis_local\gee_egress_local.py build }
if ($build -eq 0) {
    $probe = Step 'egress probe (dry-run)' { & $py -I -B dev\gis_local\gee_egress_local.py probe }
    if ($probe -ne 0) { Step 'egress cleanup' { & $py -I -B dev\gis_local\gee_egress_local.py cleanup } | Out-Null }
    $latest = Get-ChildItem -Path $egressRoot -Directory -Filter 'run-*' -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($latest -and (Test-Path (Join-Path $latest.FullName 'evidence.json'))) {
        Copy-Item (Join-Path $latest.FullName 'evidence.json') (Join-Path $repo "green-area-backend\.venv\a6-egress-evidence-$stamp.json")
        "evidence copied: a6-egress-evidence-$stamp.json" | Tee-Object -FilePath $log -Append | Out-Host
    }
}
"DONE. Log: $log" | Out-Host
