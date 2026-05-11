# GDriveLink

GDriveLink is a small Python desktop app for quickly turning local files and clipboard images into Google Drive share links. Drop files into the app, or press `Ctrl+V` to preview and upload a copied image. Uploads go into a configurable Drive folder, are shared as `anyone with the link can read`, and the resulting link is copied to the clipboard.

The app also keeps local upload history in `upload_history.json` and includes a Drive Folder tab with compact file cards for refreshing the selected Drive folder, viewing each file's current sharing status, and copying links from existing Drive files after ensuring link sharing is enabled.

## Setup

1. Create a Google Cloud project.
2. Enable the Google Drive API.
3. Configure the OAuth consent screen.
4. Create an OAuth client ID for a **Desktop app**.
5. Download the client JSON and save it in this folder as `credentials.json`.
6. Create and activate a virtual environment:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

7. Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

## Run

```powershell
.\.venv\Scripts\python.exe gdrivelink.py
```

On first run, Google opens an OAuth sign-in page. After authorization, the app stores `token.pickle` beside the script so future uploads do not need another sign-in unless the token expires or is revoked.

You can also copy an image to the clipboard and press `Ctrl+V` in the app. The app shows a preview first. You can edit the filename, then pressing OK uploads the image as a PNG and copies the share link to the clipboard.

## VS Code

Open this folder in VS Code and press F5. The included `.vscode/launch.json` runs `gdrivelink.py` from the workspace folder.

## Build Windows EXE

Install PyInstaller into the virtual environment:

```powershell
.\.venv\Scripts\python.exe -m pip install pyinstaller
```

Build the app:

```powershell
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean GDriveLink.spec
```

The executable is created at:

```text
dist\GDriveLink.exe
```

Keep `credentials.json` beside the executable for first-run Google OAuth setup. The build is a single-file executable, so there is no `_internal` folder to distribute. The generated `build\` folder is ignored by Git.

## Notes

- Verified with Python 3.14.5 in `.venv`.
- The app window uses `gdrivelink.ico` as its program icon. `gdrivelink-icon.png` is a preview/source image for the icon.
- Uploaded files are created in the Drive folder shown in the app. The default folder is `GDriveLink`.
- If the configured Drive folder does not exist, the app creates it.
- Successful uploads are saved to `upload_history.json` and loaded into the Upload History tab on startup.
- The Drive Folder tab shows compact cards for files currently present in the selected Drive folder, including their current link-sharing status.
- Copying a link from a Drive Folder card first changes that file to `anyone with the link can read`, then copies the link.
- Deleting a file from a Drive Folder card moves it to Google Drive trash and removes it from the current view.
- The app requests the `drive.file` scope, so it can manage files it creates or files the user explicitly opens with the app.
- Delete `token.pickle` to sign in with a different Google account.
