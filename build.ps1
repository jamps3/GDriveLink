Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$version = (Get-Content VERSION).Trim()
$parts = $version.Split('.')
if ($parts.Count -ne 3) {
    throw "VERSION must use major.minor.patch format, found '$version'."
}

$parts[2] = [int]$parts[2] + 1
$newVersion = ($parts -join '.')
Set-Content VERSION $newVersion

$runtimeFiles = @("credentials.json", "token.pickle", "upload_history.json", "settings.json")
$ignoreRules = @(
    "credentials.json",
    "token.pickle",
    "upload_history.json",
    "settings.json",
    "**/credentials.json",
    "**/token.pickle",
    "**/upload_history.json",
    "**/settings.json"
)

if (-not (Test-Path ".gitignore")) {
    New-Item -ItemType File -Path ".gitignore" | Out-Null
}

$gitignore = Get-Content ".gitignore"
foreach ($rule in $ignoreRules) {
    if ($gitignore -notcontains $rule) {
        Add-Content ".gitignore" $rule
    }
}

$previousReleaseDir = Get-ChildItem -Path "dist" -Directory -Filter "GDriveLink-v*" -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -ne "GDriveLink-v$newVersion" } |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean GDriveLink.spec

$releaseDir = Join-Path "dist" "GDriveLink-v$newVersion"
if (Test-Path $releaseDir) {
    Remove-Item -Recurse -Force $releaseDir
}

New-Item -ItemType Directory -Path $releaseDir | Out-Null
Move-Item -Force "dist\GDriveLink.exe" (Join-Path $releaseDir "GDriveLink.exe")

foreach ($file in @("README.md", "LICENSE")) {
    if (Test-Path $file) {
        Copy-Item -Force $file $releaseDir
    }
}

foreach ($file in $runtimeFiles) {
    $previousFile = $null
    if ($previousReleaseDir) {
        $candidate = Join-Path $previousReleaseDir.FullName $file
        if (Test-Path $candidate) {
            $previousFile = $candidate
        }
    }

    if ($previousFile) {
        Move-Item -Force $previousFile (Join-Path $releaseDir $file)
    } elseif (Test-Path $file) {
        Copy-Item -Force $file $releaseDir
    }
}

Write-Host "Built dist\GDriveLink-v$newVersion\GDriveLink.exe"
