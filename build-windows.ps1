Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = $PSScriptRoot
Set-Location $Root

$Version = (Get-Content VERSION).Trim()
if ($Version -notmatch '^[0-9]+\.[0-9]+\.[0-9]+$') {
    throw "VERSION must use major.minor.patch format, found '$Version'."
}

while ($true) {
    $inputVersion = Read-Host "VERSION [$Version]"
    if ([string]::IsNullOrWhiteSpace($inputVersion)) {
        break
    }

    $trimmedVersion = $inputVersion.Trim()
    if ($trimmedVersion -match '^[0-9]+\.[0-9]+\.[0-9]+$') {
        $Version = $trimmedVersion
        break
    }

    Write-Host "Invalid version format. Use major.minor.patch."
}

Set-Content VERSION $Version

$AppName = "GDriveLink"
$Platform = "windows-x64"
$BuildName = "$AppName-v$Version-$Platform"
$PackageDir = Join-Path $Root "dist\$BuildName"
$ReleaseDir = Join-Path $Root "release\v$Version"

Remove-Item -Recurse -Force "$Root\build" -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force $PackageDir -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $PackageDir | Out-Null
New-Item -ItemType Directory -Force $ReleaseDir | Out-Null

$pythonExe = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
    throw "Expected virtual environment at .venv\Scripts\python.exe."
}

& $pythonExe -m PyInstaller --noconfirm --clean GDriveLink.spec

$builtExe = Join-Path $Root "dist\$AppName.exe"
if (-not (Test-Path $builtExe)) {
    throw "Could not find $builtExe after PyInstaller build."
}

Move-Item -Force $builtExe (Join-Path $PackageDir "$AppName.exe")

foreach ($file in @("README.md", "LICENSE", "CHANGELOG.md")) {
    if (Test-Path $file) {
        Copy-Item -Force $file $PackageDir
    }
}

$ZipPath = Join-Path $ReleaseDir "$BuildName.zip"
Remove-Item -Force $ZipPath -ErrorAction SilentlyContinue
Compress-Archive -Path $PackageDir -DestinationPath $ZipPath

Get-FileHash $ZipPath -Algorithm SHA256 | ForEach-Object {
    "$($_.Hash)  $(Split-Path $_.Path -Leaf)"
} | Set-Content (Join-Path $ReleaseDir "sha256sums-windows.txt")

Write-Host "Created: $ZipPath"
