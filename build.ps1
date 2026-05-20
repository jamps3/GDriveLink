.\.venv\Scripts\Activate.ps1

$version = (Get-Content VERSION).Trim()
$parts = $version.Split('.')
$parts[2] = [int]$parts[2] + 1
$newVersion = ($parts -join '.')
Set-Content VERSION $newVersion

pyinstaller --clean GDriveLink.spec
Move-Item -Force "dist\GDriveLink.exe" "dist\GDriveLink-v$newVersion.exe" -ErrorAction SilentlyContinue