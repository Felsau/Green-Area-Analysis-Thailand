# Read-only inventory of one real LDD Shapefile ZIP under ldd-policy-v2.
# Pinned GIS image, --network=none, the ZIP folder mounted read-only. Writes only the JSON
# report next to the logs in green-area-backend\.venv. No database, cache or GEE.
param(
    [Parameter(Mandatory=$true)][string]$Zip,
    [Parameter(Mandatory=$true)][string]$Province,
    [Parameter(Mandatory=$true)][int]$Year,
    [ValidateSet('EPSG:32647','EPSG:32648','EPSG:4326')][string]$Crs = 'EPSG:32647',
    [ValidateSet('auto','utf-8','cp874','tis-620')][string]$Encoding = 'auto'
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$image = 'sha256:fca4560d8a0d0198c0eb75fbf6598314cd8ed4a5e8bafa00e1d7298126aa04c9'
$file = Get-Item -LiteralPath $Zip
$out = Join-Path $repo ("green-area-backend\.venv\ldd-inventory-" + $file.BaseName + "-" + (Get-Date -Format 'yyyyMMdd-HHmmss') + ".json")
docker run --rm --network=none --read-only --cap-drop=ALL --security-opt=no-new-privileges:true --user=65534:65534 `
    --memory=1g --pids-limit=64 --tmpfs=/tmp:rw,nosuid,size=256m,mode=1777 `
    --mount "type=bind,src=$repo\green-area-backend\gis_worker,dst=/app/gis_worker,readonly" `
    --mount "type=bind,src=$repo\dev\gis_local\ldd_inventory.py,dst=/app/ldd_inventory.py,readonly" `
    --mount "type=bind,src=$($file.DirectoryName),dst=/data,readonly" `
    --entrypoint python3 $image -I -B /app/ldd_inventory.py --province $Province --year $Year --crs $Crs --encoding $Encoding ("/data/" + $file.Name) |
    Out-File -FilePath $out -Encoding utf8
if ($LASTEXITCODE -ne 0 -or (Get-Item -LiteralPath $out).Length -lt 10) {
    Remove-Item -LiteralPath $out -ErrorAction SilentlyContinue
    throw "LDD inventory failed (docker exit code $LASTEXITCODE); nothing was saved. The message above says why."
}
Get-Content $out -TotalCount 60
"Saved: $out"
