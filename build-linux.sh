#!/usr/bin/env bash
set -euo pipefail

version="$(tr -d '[:space:]' < VERSION)"
IFS='.' read -r major minor patch extra <<< "$version"

if [[ -n "${extra:-}" || -z "${major:-}" || -z "${minor:-}" || -z "${patch:-}" ]]; then
  echo "VERSION must use major.minor.patch format, found '$version'." >&2
  exit 1
fi

new_version="${major}.${minor}.$((patch + 1))"
printf '%s\n' "$new_version" > VERSION

download_url="https://github.com/jamps3/GDriveLink/blob/main/dist/GDriveLink-v${new_version}/GDriveLink.exe"
perl -0pi -e "s|\\[GDriveLink\\.exe\\]\\(https://github\\.com/jamps3/GDriveLink/blob/main/dist/GDriveLink-v[^/]+/GDriveLink\\.exe\\)|[GDriveLink.exe]($download_url)|" README.md

runtime_files=(credentials.json token.pickle upload_history.json settings.json)
ignore_rules=(
  credentials.json
  token.pickle
  upload_history.json
  settings.json
  '**/credentials.json'
  '**/token.pickle'
  '**/upload_history.json'
  '**/settings.json'
)

touch .gitignore
for rule in "${ignore_rules[@]}"; do
  if ! grep -Fxq "$rule" .gitignore; then
    printf '%s\n' "$rule" >> .gitignore
  fi
done

previous_release_dir=""
if [[ -d dist ]]; then
  previous_release_dir="$(
    find dist -maxdepth 1 -type d -name 'GDriveLink-v*' ! -name "GDriveLink-v${new_version}" -printf '%T@ %p\n' 2>/dev/null |
      sort -nr |
      awk 'NR == 1 { sub(/^[^ ]+ /, ""); print }'
  )"
fi

if [[ ! -x ".venv/bin/python" ]]; then
  echo "Expected virtual environment at .venv/bin/python." >&2
  exit 1
fi

".venv/bin/python" -m PyInstaller --noconfirm --clean GDriveLink.spec

release_dir="dist/GDriveLink-v${new_version}"
rm -rf "$release_dir"
mkdir -p "$release_dir"

if [[ -f "dist/GDriveLink" ]]; then
  mv "dist/GDriveLink" "$release_dir/GDriveLink"
elif [[ -f "dist/GDriveLink.exe" ]]; then
  mv "dist/GDriveLink.exe" "$release_dir/GDriveLink.exe"
else
  echo "Could not find PyInstaller output in dist/." >&2
  exit 1
fi

for file in README.md LICENSE; do
  if [[ -f "$file" ]]; then
    cp "$file" "$release_dir/"
  fi
done

for file in "${runtime_files[@]}"; do
  if [[ -n "$previous_release_dir" && -f "$previous_release_dir/$file" ]]; then
    mv -f "$previous_release_dir/$file" "$release_dir/"
  elif [[ -f "$file" ]]; then
    cp -f "$file" "$release_dir/"
  fi
done

echo "Built ${release_dir}/"
