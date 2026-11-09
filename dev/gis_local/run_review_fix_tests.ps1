# Review fixes (3 Nov 2026): cross-platform source integrity, method registry, LDD policy v2.
# Windows (CRLF checkout) side of the LF/CRLF proof. No Google call, no database write,
# no network inside the Linux test container (--network=none, read-only mounts).
$ErrorActionPreference = 'Continue'
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repo
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$log = Join-Path $repo "green-area-backend\.venv\review-fix-tests-$stamp.log"
$image = 'sha256:fca4560d8a0d0198c0eb75fbf6598314cd8ed4a5e8bafa00e1d7298126aa04c9'

function Step([string]$name, [scriptblock]$body) {
    "===== $name  $(Get-Date -Format s)" | Tee-Object -FilePath $log -Append | Out-Host
    $global:LASTEXITCODE = 0
    & $body 2>&1 | ForEach-Object { "$_" } | Tee-Object -FilePath $log -Append | Out-Host
    "exit=$LASTEXITCODE" | Tee-Object -FilePath $log -Append | Out-Host
}

Step 'git' { git rev-parse --short HEAD; git status --short }
Step 'source fingerprint (raw / LF canonical)' {
    $files = 'green-area-backend\gee_utils.py','green-area-backend\routers\ndvi\compute.py','green-area-backend\routers\lst.py','green-area-backend\gis_worker\registry.json'
    & .\green-area-backend\.venv\Scripts\python.exe -I -B -c "import sys,hashlib;[print(p, hashlib.sha256(open(p,'rb').read()).hexdigest()[:16], hashlib.sha256(open(p,'rb').read().replace(b'\r\n',b'\n')).hexdigest()[:16], open(p,'rb').read().count(b'\r\n')) for p in sys.argv[1:]]" @files
}
Step 'backend tests (Windows venv, full suite)' {
    Push-Location green-area-backend
    $env:PYTHONPATH = (Resolve-Path tests).Path
    # Native GIS tests (rasterio/fiona/shapely) run in the pinned Linux image below.
    $native = 'test_ldd_native.py','test_ldd_prepare_native.py','test_ldd_policy_native.py','test_gis_native_provider.py',
        'test_ldd_publication_native.py','test_gis_worker_unit.py','test_geotiff_native.py','test_geotiff_prepare_native.py','test_geotiff_bands_native.py'
    $ignore = $native | ForEach-Object { "--ignore=tests\$_" }
    & .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --continue-on-collection-errors -rfE @ignore tests
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    Pop-Location
}
Step 'native GIS tests (pinned Linux image, CRLF bind mount)' {
    $backend = (Resolve-Path green-area-backend).Path
    $code = "import sys;sys.path[:0]=['/work','/work/tests'];import pytest;raise SystemExit(pytest.main(['-q','-p','no:cacheprovider','--basetemp','/tmp/pt','/work/tests/test_ldd_native.py','/work/tests/test_ldd_prepare_native.py','/work/tests/test_ldd_policy_native.py','/work/tests/test_ldd_policy.py','/work/tests/test_gis_native_provider.py','/work/tests/test_ldd_publication_native.py','/work/tests/test_gis_worker_unit.py','/work/tests/test_geotiff_native.py','/work/tests/test_geotiff_prepare_native.py','/work/tests/test_geotiff_bands_native.py']))"
    docker run --rm --network=none --read-only --cap-drop=ALL --security-opt=no-new-privileges:true --user=65534:65534 `
        --memory=2g --pids-limit=128 --tmpfs=/tmp:rw,nosuid,size=512m,mode=1777 -e PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 `
        --mount "type=bind,src=$backend\gis_worker,dst=/work/gis_worker,readonly" `
        --mount "type=bind,src=$backend\tests,dst=/work/tests,readonly" `
        --mount "type=bind,src=$backend\gee_utils.py,dst=/work/gee_utils.py,readonly" `
        --mount "type=bind,src=$backend\routers,dst=/work/routers,readonly" `
        --mount "type=bind,src=$backend\migrations,dst=/work/migrations,readonly" `
        --entrypoint python3 $image -I -B -c $code
}
Step 'frontend tests' {
    Push-Location green-area-frontend
    npx vitest run src/components/GisManagement.test.js
    Pop-Location
}
"DONE. Log: $log" | Out-Host
