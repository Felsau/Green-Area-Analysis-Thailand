# Build gis_worker\ldd_codes_v2.json from the LUCODE.xls files inside a folder of real LDD province packages.
# Pinned GIS image, --network=none, root filesystem and both inputs read-only. The only writable mount is a fresh
# output folder; the result is copied to -Out afterwards. No database, cache or GEE.
param(
    [Parameter(Mandatory=$true)][string]$Packages,
    [string]$Out
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$image = 'sha256:fca4560d8a0d0198c0eb75fbf6598314cd8ed4a5e8bafa00e1d7298126aa04c9'
if (-not $Out) { $Out = Join-Path $repo 'green-area-backend\gis_worker\ldd_codes_v2.json' }
$folder = (Get-Item -LiteralPath $Packages).FullName
$work = Join-Path $repo ('green-area-backend\.venv\ldd-legend-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $work | Out-Null
$run = @('run', '--rm', '--network=none', '--read-only', '--cap-drop=ALL', '--security-opt=no-new-privileges:true', '--user=65534:65534',
    '--memory=1g', '--pids-limit=64', '--tmpfs=/tmp:rw,nosuid,size=64m,mode=1777',
    '--mount', "type=bind,src=$repo\green-area-backend\gis_worker\ldd_codes.json,dst=/app/ldd_codes.json,readonly",
    '--mount', "type=bind,src=$repo\dev\gis_local\build_ldd_legend.py,dst=/app/build_ldd_legend.py,readonly",
    '--mount', "type=bind,src=$folder,dst=/data,readonly",
    '--mount', "type=bind,src=$work,dst=/out",
    '--entrypoint', 'python3', $image, '-I', '-B', '/app/build_ldd_legend.py',
    '--base', '/app/ldd_codes.json', '--packages', '/data', '--out', '/out/ldd_codes_v2.json')
& docker @run
if ($LASTEXITCODE -ne 0 -or -not (Test-Path (Join-Path $work 'ldd_codes_v2.json'))) {
    throw "Legend build failed (docker exit code $LASTEXITCODE); nothing was copied. Work folder: $work"
}
Copy-Item -LiteralPath (Join-Path $work 'ldd_codes_v2.json') -Destination $Out -Force
"Asset: $Out"
