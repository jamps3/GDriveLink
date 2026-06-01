Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = $PSScriptRoot
$wrapper = Join-Path $Root 'build-windows.ps1'
if (-not (Test-Path $wrapper)) {
    throw "Cannot find build-windows.ps1 in $Root"
}
& $wrapper @Args