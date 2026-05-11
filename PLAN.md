# GDriveLink Plan

## Completed

- Created a Python desktop app for uploading drag-and-dropped files to Google Drive.
- Added Google OAuth support using `credentials.json` and cached `token.pickle`.
- Set uploaded files to `anyone with the link` reader permissions.
- Displayed uploaded share links in the app.
- Added a button to copy the selected upload link.
- Automatically copied the latest uploaded link to the clipboard.
- Added vertical and horizontal scrollbars for file/link rows.
- Added a Drive folder textbox with `GDriveLink` as the default.
- Uploaded files into the selected Drive folder, creating it when needed.
- Added `Ctrl+V` clipboard image paste support.
- Added a clipboard image preview dialog before upload.
- Added a filename box for pasted clipboard images.
- Added VS Code F5 launch configuration.
- Added `pyproject.toml` project metadata and script entry point.
- Renamed the main script to `gdrivelink.py`.
- Added persistent upload history in `upload_history.json`.
- Loaded upload history on startup.
- Added a Drive Folder tab that refreshes and shows files in the selected Drive folder.
- Displayed current sharing permissions for each file in the Drive Folder tab.
- Made Drive Folder link-copy update the selected file to `anyone with the link can read` before copying.
- Rearranged the Drive Folder tab into compact file cards with per-file Open and Copy link actions.
- Added per-file Delete actions in the Drive Folder tab that move files to Google Drive trash.
- Updated Drive Folder delete behavior to remove deleted cards locally without reloading the whole folder.

## Next

- Runtime-test the full app flow once the local Python launcher responds normally.
- Consider packaging the app into a Windows executable.
- Consider adding delete, rename, or folder-open actions for Drive files.
