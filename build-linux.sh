#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
cd "$root"

version="$(tr -d '[:space:]' < VERSION)"
if [[ ! "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "VERSION must use major.minor.patch format, found '$version'." >&2
  exit 1
fi

while true; do
  read -rp "VERSION [$version]: " input_version
  if [[ -z "$input_version" ]]; then
    new_version="$version"
    break
  fi
  if [[ "$input_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    new_version="$input_version"
    break
  fi
  echo "Invalid version format. Use major.minor.patch."
done

printf '%s\n' "$new_version" > VERSION

# Update APP_VERSION in gdrivelink.py
sed -i "s/APP_VERSION = \"[^\"]*\"/APP_VERSION = \"$new_version\"/" gdrivelink.py

download_url="https://github.com/jamps3/GDriveLink/blob/main/dist/GDriveLink-v${new_version}/GDriveLink.exe"
perl -0pi -e "s|\\[GDriveLink\\.exe\\]\\(https://github\\.com/jamps3/GDriveLink/blob/main/dist/GDriveLink-v[^/]+/GDriveLink\\.exe\\)|[GDriveLink.exe]($download_url)|" README.md

AppName="GDriveLink"
Platform="linux-x64"
BuildName="${AppName}-v${new_version}-${Platform}"
PackageDir="$root/dist/$BuildName"
ReleaseDir="$root/release/v${new_version}"

rm -rf "$root/build"
rm -rf "$PackageDir"
mkdir -p "$PackageDir"
mkdir -p "$ReleaseDir"

python_exec=""
if [[ -x ".venv-linux/bin/python" ]]; then
  python_exec=".venv-linux/bin/python"
elif [[ -x ".venv/bin/python" ]]; then
  python_exec=".venv/bin/python"
else
  echo "Expected a Linux virtual environment at .venv-linux/bin/python or .venv/bin/python." >&2
  echo "Create one with: python3 -m venv .venv-linux" >&2
  exit 1
fi

"$python_exec" -m PyInstaller --noconfirm --clean GDriveLink.spec

if [[ -f "dist/GDriveLink" ]]; then
  mv "dist/GDriveLink" "$PackageDir/GDriveLink"
elif [[ -f "dist/GDriveLink.exe" ]]; then
  mv "dist/GDriveLink.exe" "$PackageDir/GDriveLink.exe"
else
  echo "Could not find PyInstaller output in dist/." >&2
  exit 1
fi

for file in README.md LICENSE CHANGELOG.md; do
  if [[ -f "$file" ]]; then
    cp -f "$file" "$PackageDir/"
  fi
done

ArchivePath="$ReleaseDir/$BuildName.tar.gz"
rm -f "$ArchivePath"
tar -C "$root/dist" -czf "$ArchivePath" "$BuildName"

if command -v sha256sum >/dev/null 2>&1; then
  sha256sum "$ArchivePath" > "$ReleaseDir/sha256sums-linux.txt"
elif command -v shasum >/dev/null 2>&1; then
  shasum -a 256 "$ArchivePath" > "$ReleaseDir/sha256sums-linux.txt"
else
  echo "Warning: no sha256sum or shasum command found; skipping checksum generation." >&2
fi

echo "Created: $ArchivePath"
