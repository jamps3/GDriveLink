from __future__ import annotations

from html import escape
import json
import os
import pickle
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import webbrowser
from urllib.parse import parse_qsl, urlparse, urlencode
from datetime import datetime
from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, X, Y, BooleanVar, Button, Canvas, Checkbutton, Entry, Frame, Label, Listbox, PhotoImage, Radiobutton, Scrollbar, StringVar, Toplevel, filedialog, messagebox
from tkinter.ttk import Checkbutton as TtkCheckbutton, Notebook, Progressbar, Radiobutton as TtkRadiobutton, Scrollbar as TtkScrollbar, Style

from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from PIL import Image, ImageGrab, ImageTk
from pystray import Icon as TrayIcon, Menu, MenuItem
from tkinterdnd2 import DND_FILES, TkinterDnD


APP_TITLE = "GDriveLink"
APP_VERSION = "1.1.0"
APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))
VERSION_FILE = APP_DIR / "VERSION"
CLIENT_SECRET_FILE = APP_DIR / "credentials.json"
TOKEN_FILE = APP_DIR / "token.pickle"
HISTORY_FILE = APP_DIR / "upload_history.json"
SETTINGS_FILE = APP_DIR / "settings.json"
STARTUP_APP_ID = "GDriveLink"
SINGLE_INSTANCE_MUTEX_NAME = "Global\\GDriveLinkSingleInstance"
SINGLE_INSTANCE_LOCK_FILE = "gdrivelink.lock"
ICON_FILE = RESOURCE_DIR / "assets" / "gdrivelink.ico"
ICON_PNG_FILE = RESOURCE_DIR / "assets" / "GDriveLink-icon-256.png"
LOGO_FILE = RESOURCE_DIR / "assets" / "GDriveLink-logo-128.png"
ABOUT_ICON_FILE = RESOURCE_DIR / "assets" / "about.png"
CLIPBOARD_ICON_FILE = RESOURCE_DIR / "assets" / "clipboard.png"
CHOOSE_ICON_FILE = RESOURCE_DIR / "assets" / "choose.png"
OPEN_DRIVE_ICON_FILE = RESOURCE_DIR / "assets" / "open_drive.png"
REFRESH_DRIVE_ICON_FILE = RESOURCE_DIR / "assets" / "refresh_drive.png"
SCOPES = ["https://www.googleapis.com/auth/drive.file"]
THEME_OPTIONS = ("system", "light", "dark")
DEFAULT_CONFIRM_HISTORY_DRIVE_DELETIONS = True
DEFAULT_CONFIRM_DRIVE_FOLDER_DELETIONS = True
DEFAULT_OPEN_WITH_OS = False
DEFAULT_SCREENSHOT_MONITOR_ENABLED = False
DEFAULT_SCREENSHOT_MONITOR_FOLDER = str(Path.home() / "Pictures" / "Screenshots")
DEFAULT_OMIT_DRIVESDK_QUERY = False
SCREENSHOT_MONITOR_POLL_INTERVAL = 2.0
SCREENSHOT_MONITOR_STABLE_WAIT = 1.0
LIGHT_THEME = {
    "window": "#f5f7fb",
    "surface": "#ffffff",
    "surface_alt": "#eef2f7",
    "border": "#cfd7e3",
    "text": "#1f2933",
    "muted": "#52616f",
    "accent": "#2563eb",
    "accent_text": "#ffffff",
    "button": "#e6edf7",
    "button_active": "#d6e2f2",
    "entry": "#ffffff",
    "entry_text": "#111827",
    "select": "#cfe0ff",
    "select_text": "#0f172a",
    "drop": "#f4f7fb",
}
DARK_THEME = {
    "window": "#111827",
    "surface": "#1f2937",
    "surface_alt": "#273445",
    "border": "#4b5563",
    "text": "#f3f4f6",
    "muted": "#cbd5e1",
    "accent": "#60a5fa",
    "accent_text": "#08111f",
    "button": "#374151",
    "button_active": "#4b5563",
    "entry": "#111827",
    "entry_text": "#f9fafb",
    "select": "#1d4ed8",
    "select_text": "#ffffff",
    "drop": "#182233",
}
SINGLE_INSTANCE_LOCK = None

APP_DESCRIPTION = (
    "GDriveLink is a small Python desktop app for quickly turning local files and clipboard images "
    "into Google Drive share links. Drop files into the app, press `Ctrl+V`, or use the clipboard upload "
    "button to preview and upload copied images or files. Uploads go into a configurable Drive folder, "
    "are shared as `anyone with the link can read`, and the resulting link is copied to the clipboard.\n\n"
    "The app also keeps local upload history in `upload_history.json` and includes a Drive Folder tab "
    "with compact file cards for refreshing the selected Drive folder, viewing each file's current "
    "sharing status, and copying links from existing Drive files after ensuring link sharing is enabled. "
    "The main screen can also open the selected synced Drive folder in Explorer."
)


def load_history() -> list[dict[str, str]]:
    if not HISTORY_FILE.exists():
        return []
    try:
        with HISTORY_FILE.open("r", encoding="utf-8") as history_file:
            data = json.load(history_file)
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    items = [item for item in data if isinstance(item, dict)]
    items.sort(key=lambda item: item.get("uploaded_at", ""), reverse=True)
    return items


def save_history(history: list[dict[str, str]]) -> None:
    with HISTORY_FILE.open("w", encoding="utf-8") as history_file:
        json.dump(history, history_file, indent=2)
        history_file.write("\n")


def default_settings() -> dict[str, bool | str]:
    return {
        "theme": "system",
        "confirm_history_drive_deletions": DEFAULT_CONFIRM_HISTORY_DRIVE_DELETIONS,
        "confirm_drive_folder_deletions": DEFAULT_CONFIRM_DRIVE_FOLDER_DELETIONS,
        "open_with_os": DEFAULT_OPEN_WITH_OS,
        "screenshot_monitor_enabled": DEFAULT_SCREENSHOT_MONITOR_ENABLED,
        "screenshot_monitor_folder": DEFAULT_SCREENSHOT_MONITOR_FOLDER,
        "omit_drivesdk_query": DEFAULT_OMIT_DRIVESDK_QUERY,
    }


def load_app_version() -> str:
    version = APP_VERSION
    try:
        if VERSION_FILE.exists():
            file_text = VERSION_FILE.read_text(encoding="utf-8").strip()
            if file_text:
                version = file_text
    except Exception:
        pass
    return version


def load_settings() -> dict[str, bool | str]:
    if not SETTINGS_FILE.exists():
        return default_settings()
    try:
        with SETTINGS_FILE.open("r", encoding="utf-8") as settings_file:
            data = json.load(settings_file)
    except (OSError, json.JSONDecodeError):
        return default_settings()
    if not isinstance(data, dict):
        return default_settings()
    theme = data.get("theme", "system")
    if theme not in THEME_OPTIONS:
        theme = "system"
    return {
        "theme": theme,
        "confirm_history_drive_deletions": bool(
            data.get("confirm_history_drive_deletions", DEFAULT_CONFIRM_HISTORY_DRIVE_DELETIONS)
        ),
        "confirm_drive_folder_deletions": bool(
            data.get("confirm_drive_folder_deletions", DEFAULT_CONFIRM_DRIVE_FOLDER_DELETIONS)
        ),
        "open_with_os": bool(data.get("open_with_os", DEFAULT_OPEN_WITH_OS)),
        "screenshot_monitor_enabled": bool(
            data.get("screenshot_monitor_enabled", DEFAULT_SCREENSHOT_MONITOR_ENABLED)
        ),
        "screenshot_monitor_folder": str(
            data.get("screenshot_monitor_folder", DEFAULT_SCREENSHOT_MONITOR_FOLDER)
        ),
        "omit_drivesdk_query": bool(
            data.get("omit_drivesdk_query", DEFAULT_OMIT_DRIVESDK_QUERY)
        ),
    }


def save_settings(settings: dict[str, bool | str]) -> None:
    with SETTINGS_FILE.open("w", encoding="utf-8") as settings_file:
        json.dump(settings, settings_file, indent=2)
        settings_file.write("\n")


def startup_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [str(Path(sys.executable).resolve())]
    script_path = Path(__file__).resolve()
    executable = Path(sys.executable).resolve()
    if executable.name.lower() == "python.exe":
        pythonw = executable.with_name("pythonw.exe")
        if pythonw.exists():
            executable = pythonw
    return [str(executable), str(script_path)]


def startup_command_string() -> str:
    return subprocess.list2cmdline(startup_command())


def windows_startup_key_path() -> str:
    return r"Software\Microsoft\Windows\CurrentVersion\Run"


def linux_autostart_file() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "autostart" / "gdrivelink.desktop"


def macos_launch_agent_file() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / "com.gdrivelink.plist"


def is_open_with_os_enabled() -> bool:
    try:
        if sys.platform == "win32":
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, windows_startup_key_path()) as key:
                value, _value_type = winreg.QueryValueEx(key, STARTUP_APP_ID)
                return value == startup_command_string()
        if sys.platform == "darwin":
            return macos_launch_agent_file().exists()
        return linux_autostart_file().exists()
    except OSError:
        return False


def set_open_with_os_enabled(enabled: bool) -> None:
    if sys.platform == "win32":
        import winreg

        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER,
            windows_startup_key_path(),
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            if enabled:
                winreg.SetValueEx(key, STARTUP_APP_ID, 0, winreg.REG_SZ, startup_command_string())
            else:
                try:
                    winreg.DeleteValue(key, STARTUP_APP_ID)
                except FileNotFoundError:
                    pass
        return

    if sys.platform == "darwin":
        launch_agent = macos_launch_agent_file()
        if enabled:
            command = startup_command()
            program_arguments = "\n".join(f"    <string>{escape(part)}</string>" for part in command)
            launch_agent.parent.mkdir(parents=True, exist_ok=True)
            launch_agent.write_text(
                "\n".join(
                    [
                        '<?xml version="1.0" encoding="UTF-8"?>',
                        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
                        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">',
                        '<plist version="1.0">',
                        "<dict>",
                        "  <key>Label</key>",
                        "  <string>com.gdrivelink</string>",
                        "  <key>ProgramArguments</key>",
                        "  <array>",
                        program_arguments,
                        "  </array>",
                        "  <key>RunAtLoad</key>",
                        "  <true/>",
                        "</dict>",
                        "</plist>",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
        else:
            launch_agent.unlink(missing_ok=True)
        return

    autostart_file = linux_autostart_file()
    if enabled:
        autostart_file.parent.mkdir(parents=True, exist_ok=True)
        autostart_file.write_text(
            "\n".join(
                [
                    "[Desktop Entry]",
                    "Type=Application",
                    f"Name={APP_TITLE}",
                    f"Exec={startup_command_string()}",
                    "Terminal=false",
                    "X-GNOME-Autostart-enabled=true",
                    "",
                ]
            ),
            encoding="utf-8",
        )
    else:
        autostart_file.unlink(missing_ok=True)


def acquire_single_instance_lock():  # type: ignore[no-untyped-def]
    if sys.platform != "win32":
        import fcntl

        lock_dir = Path(os.environ.get("XDG_RUNTIME_DIR", tempfile.gettempdir()))
        lock_file = lock_dir / SINGLE_INSTANCE_LOCK_FILE
        handle = lock_file.open("w", encoding="utf-8")
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close()
            return None
        return handle

    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.CreateMutexW(None, True, SINGLE_INSTANCE_MUTEX_NAME)
    if not handle:
        return None
    if ctypes.get_last_error() == 183:
        kernel32.CloseHandle(handle)
        return None
    return handle


def system_prefers_dark_theme() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            value, _value_type = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return value == 0
    except OSError:
        return False


def set_windows_dark_title_bar(window, enabled: bool) -> None:  # type: ignore[no-untyped-def]
    if sys.platform != "win32":
        return
    try:
        import ctypes

        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        value = ctypes.c_int(1 if enabled else 0)
        for attribute in (20, 19):
            result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd,
                attribute,
                ctypes.byref(value),
                ctypes.sizeof(value),
            )
            if result == 0:
                break
    except Exception:
        return


class DriveUploaderApp:
    def __init__(self) -> None:
        self.root = TkinterDnD.Tk()
        self.root.title(APP_TITLE)
        self.icon_photo = None
        icon_set = False
        if sys.platform.startswith("win") and ICON_FILE.exists():
            try:
                self.root.iconbitmap(ICON_FILE)
                icon_set = True
            except Exception:
                icon_set = False
        if not icon_set and ICON_PNG_FILE.exists():
            try:
                self.icon_photo = PhotoImage(file=str(ICON_PNG_FILE))
                self.root.iconphoto(True, self.icon_photo)
            except Exception:
                pass
        self.root.geometry("690x650")
        self.root.minsize(690, 750)

        self.status = StringVar(
            value=(
                "Drop files here, paste from clipboard, or choose files.\n\n"
                "Uploaded files are:\n"
                "- Uploaded to your selected Google Drive folder\n"
                "- Shared so anyone with the link can view them\n"
                "- Added to the Upload History tab"
            )
        )
        self.drive_folder_name = StringVar(value="GDriveLink")
        self.settings = load_settings()
        self.theme_choice = StringVar(value=str(self.settings.get("theme", "system")))
        self.confirm_history_drive_deletions = BooleanVar(
            value=bool(
                self.settings.get("confirm_history_drive_deletions", DEFAULT_CONFIRM_HISTORY_DRIVE_DELETIONS)
            )
        )
        self.confirm_drive_folder_deletions = BooleanVar(
            value=bool(self.settings.get("confirm_drive_folder_deletions", DEFAULT_CONFIRM_DRIVE_FOLDER_DELETIONS))
        )
        self.open_with_os = BooleanVar(value=is_open_with_os_enabled())
        self.screenshot_monitor_enabled = BooleanVar(
            value=bool(self.settings.get("screenshot_monitor_enabled", DEFAULT_SCREENSHOT_MONITOR_ENABLED))
        )
        self.screenshot_monitor_folder = StringVar(
            value=str(self.settings.get("screenshot_monitor_folder", DEFAULT_SCREENSHOT_MONITOR_FOLDER))
        )
        self.omit_drivesdk_query = BooleanVar(
            value=bool(self.settings.get("omit_drivesdk_query", DEFAULT_OMIT_DRIVESDK_QUERY))
        )
        self.settings["open_with_os"] = self.open_with_os.get()
        self.theme = DARK_THEME if self._effective_theme_name() == "dark" else LIGHT_THEME
        self.style = Style(self.root)
        self.result_queue: queue.Queue[tuple[str, str, object, int]] = queue.Queue()
        self.drive_files_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.decision_queue: queue.Queue[tuple[str, str | None]] = queue.Queue()
        self.pending_uploads = 0
        self.preview_photo = None
        self.history = load_history()
        self.version = load_app_version()
        self.history_cards: list[Frame] = []
        self.drive_files_by_id: dict[str, dict[str, str]] = {}
        self.drive_cards_by_id: dict[str, Frame] = {}
        self.tray_icon = None
        self.header_logo = self._load_logo(56)
        self.dialog_logo = self._load_logo(56)
        self.about_icon = self._load_image(ABOUT_ICON_FILE, 32)
        self.clipboard_icon = self._load_image_exact(CLIPBOARD_ICON_FILE)
        self.choose_icon = self._load_image_exact(CHOOSE_ICON_FILE)
        self.open_drive_icon = self._load_image_exact(OPEN_DRIVE_ICON_FILE)
        self.refresh_drive_icon = self._load_image_exact(REFRESH_DRIVE_ICON_FILE)
        self.choose_button = None

        # Screenshot monitor state
        self._screenshot_known_files: set[tuple[str, int]] = set()
        self._screenshot_watcher_thread: threading.Thread | None = None
        self._screenshot_watcher_stop = threading.Event()
        self._screenshot_last_status_update = ""

        self._configure_ttk_theme()
        self._build_ui()
        self._apply_theme()
        if self.choose_button:
            self.choose_button.focus_set()
        self._load_history_cards()
        self.root.bind_all("<Control-v>", self._handle_clipboard_paste)
        self.root.bind_all("<MouseWheel>", self._handle_canvas_mousewheel)
        self.root.bind_all("<Shift-MouseWheel>", self._handle_canvas_mousewheel)
        self.root.bind_all("<Button-4>", self._handle_canvas_mousewheel)
        self.root.bind_all("<Button-5>", self._handle_canvas_mousewheel)
        self.root.bind("<Unmap>", self._handle_window_unmap)
        self.root.bind("<Return>", self._handle_main_return)
        self._setup_tray()
        self.root.after(100, self._poll_results)
        self.root.after(100, self._poll_drive_files)
        self.root.after(200, self._init_screenshot_monitor)

    def _init_screenshot_monitor(self) -> None:
        """Start or stop the screenshot monitor based on current settings."""
        if self.screenshot_monitor_enabled.get():
            self._start_screenshot_watcher()
        else:
            self._stop_screenshot_watcher()

    def _start_screenshot_watcher(self) -> None:
        """Start the background thread that watches the screenshot folder."""
        if self._screenshot_watcher_thread and self._screenshot_watcher_thread.is_alive():
            return

        self._screenshot_watcher_stop.clear()
        folder_path = Path(self.screenshot_monitor_folder.get().strip() or DEFAULT_SCREENSHOT_MONITOR_FOLDER)

        if not folder_path.exists():
            self.status.set(f"Screenshot monitor: folder not found ({folder_path})")
            return

        # Re-initialize known files from current folder contents
        self._screenshot_known_files.clear()
        self._scan_folder_for_known_files(folder_path)

        self._screenshot_watcher_thread = threading.Thread(
            target=self._screenshot_watcher_loop,
            args=(folder_path,),
            daemon=True,
        )
        self._screenshot_watcher_thread.start()
        self.status.set(f"Screenshot monitor active: watching {folder_path}")

    def _stop_screenshot_watcher(self) -> None:
        """Stop the background screenshot watcher."""
        self._screenshot_watcher_stop.set()
        if self._screenshot_watcher_thread:
            self._screenshot_watcher_thread = None
        self.status.set("Screenshot monitor stopped")

    def _scan_folder_for_known_files(self, folder_path: Path) -> None:
        """Populate the known files set from the current folder contents."""
        if not folder_path.exists():
            return
        try:
            for entry in folder_path.iterdir():
                if entry.is_file():
                    try:
                        size = entry.stat().st_size
                        self._screenshot_known_files.add((entry.name, size))
                    except OSError:
                        pass
        except OSError:
            pass

    def _screenshot_watcher_loop(self, folder_path: Path) -> None:
        """Background loop that polls the screenshot folder for new files."""
        while not self._screenshot_watcher_stop.is_set():
            try:
                if not folder_path.exists():
                    self._run_on_ui_thread(
                        lambda: (
                            self.screenshot_monitor_enabled.set(False)
                            if not self._screenshot_watcher_stop.is_set()
                            else None,
                            self.status.set("Screenshot monitor: folder no longer exists"),
                        )
                    )
                    break

                new_files: list[Path] = []
                try:
                    for entry in folder_path.iterdir():
                        if entry.is_file():
                            try:
                                stat = entry.stat()
                                key = (entry.name, stat.st_size)
                                if key not in self._screenshot_known_files:
                                    # Check if the file is stable (finished writing)
                                    if self._is_file_stable(entry):
                                        self._screenshot_known_files.add(key)
                                        new_files.append(entry)
                            except OSError:
                                pass
                except OSError:
                    pass

                if new_files:
                    # Upload new files on the UI thread
                    self._run_on_ui_thread(
                        lambda files=new_files: self._on_screenshots_detected(files)
                    )

            except Exception:
                pass

            self._screenshot_watcher_stop.wait(SCREENSHOT_MONITOR_POLL_INTERVAL)

    def _is_file_stable(self, file_path: Path) -> bool:
        """Check if a file has finished being written by comparing size twice."""
        try:
            size1 = file_path.stat().st_size
            time.sleep(SCREENSHOT_MONITOR_STABLE_WAIT)
            size2 = file_path.stat().st_size
            return size1 == size2 and size1 > 0
        except OSError:
            return False

    def _on_screenshots_detected(self, files: list[Path]) -> None:
        """Called on UI thread when new screenshots are detected."""
        if not files:
            return
        file_names = ", ".join(f.name for f in files)
        self.status.set(f"Screenshot detected, uploading: {file_names}")
        self._upload_files(files)

    def _build_ui(self) -> None:
        container = self._frame(self.root, padx=18, pady=18)
        container.pack(fill=BOTH, expand=True)

        header = self._frame(container)
        header.pack(fill=X)
        header.configure(height=52)
        header.pack_propagate(False)

        if self.header_logo:
            self._label(header, image=self.header_logo).pack(side=LEFT, padx=(0, 12))
        else:
            self._label(header, text=APP_TITLE, font=("Segoe UI", 18, "bold"), anchor="w").pack(
                side=LEFT,
                fill=X,
                expand=True,
            )

        refresh_button_options = {
            "command": self._refresh_drive_files,
            "padx": 8,
            "pady": 8,
            "relief": "flat",
            "borderwidth": 0,
            "bg": self.theme["window"],
            "activebackground": self.theme["window"],
            "highlightthickness": 0,
        }
        if self.refresh_drive_icon:
            refresh_button_options["image"] = self.refresh_drive_icon
        else:
            refresh_button_options["text"] = "Refresh Drive"
            refresh_button_options["font"] = ("Segoe UI", 12, "bold")
            refresh_button_options["padx"] = 22
            refresh_button_options["pady"] = 10
        self.refresh_drive_button = Button(header, **refresh_button_options)
        self.refresh_drive_button._gdrive_icon_button = True  # type: ignore[attr-defined]
        self.refresh_drive_button.pack(side=RIGHT)

        about_button_options = {
            "command": self._show_about,
            "padx": 8,
            "pady": 8,
            "relief": "flat",
            "borderwidth": 0,
            "bg": self.theme["window"],
            "activebackground": self.theme["window"],
            "highlightthickness": 0,
        }
        if self.about_icon:
            about_button_options["image"] = self.about_icon
        else:
            about_button_options["text"] = "About"
            about_button_options["font"] = ("Segoe UI", 10)
            about_button_options["padx"] = 10
            about_button_options["pady"] = 4
        about_button_frame_width = self.about_icon.width() if self.about_icon else 64
        about_button_frame_height = self.about_icon.height() if self.about_icon else 32
        about_button_frame = self._frame(header, width=about_button_frame_width, height=about_button_frame_height)
        about_button_frame.pack(side=RIGHT, padx=(0, 8))
        about_button_frame.pack_propagate(False)
        about_button = Button(about_button_frame, **about_button_options)
        about_button._gdrive_icon_button = True  # type: ignore[attr-defined]
        about_button.pack(fill=BOTH, expand=True)

        self.tabs = Notebook(container)
        self.tabs.pack(fill=BOTH, expand=True, pady=(12, 0))

        main_tab = self._frame(self.tabs)
        history_tab = self._frame(self.tabs)
        drive_tab = self._frame(self.tabs)
        settings_tab = self._frame(self.tabs)
        self.tabs.add(main_tab, text="Main")
        self.tabs.add(history_tab, text="Upload History")
        self.tabs.add(drive_tab, text="Drive Folder")
        self.tabs.add(settings_tab, text="Settings")

        self.drop_area = Label(
            main_tab,
            text="Drop files here",
            relief="ridge",
            borderwidth=2,
            height=6,
            font=("Segoe UI", 16),
            background="#f4f7fb",
            foreground="#263238",
        )
        self.drop_area.pack(fill="x")
        self.drop_area.drop_target_register(DND_FILES)  # type: ignore[attr-defined]
        self.drop_area.dnd_bind("<<Drop>>", self._handle_drop)  # type: ignore[attr-defined]

        folder_frame = self._frame(main_tab)
        folder_frame.pack(fill="x", pady=(12, 0))

        self._label(folder_frame, text="Drive folder", anchor="w", font=("Segoe UI", 10)).pack(side=LEFT)
        Entry(folder_frame, textvariable=self.drive_folder_name).pack(side=LEFT, fill="x", expand=True, padx=(8, 0))

        controls = self._frame(main_tab)
        controls.pack(anchor="center", pady=12)

        upload_top_row = self._frame(controls)
        upload_top_row.pack(anchor="center")
        upload_bottom_row = self._frame(controls)
        upload_bottom_row.pack(anchor="center", pady=(8, 0))

        clipboard_button_width = self.clipboard_icon.width() if self.clipboard_icon else 200
        choose_button_width = self.choose_icon.width() if self.choose_icon else 200
        open_drive_button_width = self.open_drive_icon.width() if self.open_drive_icon else 200
        upload_button_height = 58

        clipboard_button_frame = self._frame(
            upload_top_row,
            width=clipboard_button_width,
            height=upload_button_height,
        )
        clipboard_button_frame.pack(side=LEFT)
        clipboard_button_frame.pack_propagate(False)
        clipboard_button = Button(
            clipboard_button_frame,
            command=self._handle_clipboard_paste,
            padx=0,
            pady=10,
            relief="flat",
            borderwidth=0,
            bg=self.theme["window"],
            activebackground=self.theme["window"],
            highlightthickness=0,
        )
        clipboard_button._gdrive_icon_button = True  # type: ignore[attr-defined]
        if self.clipboard_icon:
            clipboard_button.configure(image=self.clipboard_icon, pady=0)
        else:
            clipboard_button.configure(text="Upload from clipboard", font=("Segoe UI", 12, "bold"))
        clipboard_button.pack(fill=BOTH, expand=True)

        choose_button_frame = self._frame(upload_top_row, width=choose_button_width, height=upload_button_height)
        choose_button_frame.pack(side=LEFT, padx=(8, 0))
        choose_button_frame.pack_propagate(False)
        self.choose_button = Button(
            choose_button_frame,
            command=self._choose_files,
            padx=0,
            pady=10,
            relief="flat",
            borderwidth=0,
            bg=self.theme["window"],
            activebackground=self.theme["window"],
            highlightthickness=0,
        )
        self.choose_button._gdrive_icon_button = True  # type: ignore[attr-defined]
        if self.choose_icon:
            self.choose_button.configure(image=self.choose_icon, pady=0)
        else:
            self.choose_button.configure(text="Choose files", font=("Segoe UI", 12, "bold"))
        self.choose_button.pack(fill=BOTH, expand=True)

        open_drive_button_frame = self._frame(
            upload_bottom_row,
            width=open_drive_button_width,
            height=upload_button_height,
        )
        open_drive_button_frame.pack()
        open_drive_button_frame.pack_propagate(False)
        open_drive_button = Button(
            open_drive_button_frame,
            command=self._open_selected_drive_folder,
            padx=0,
            pady=10,
            relief="flat",
            borderwidth=0,
            bg=self.theme["window"],
            activebackground=self.theme["window"],
            highlightthickness=0,
        )
        open_drive_button._gdrive_icon_button = True  # type: ignore[attr-defined]
        if self.open_drive_icon:
            open_drive_button.configure(image=self.open_drive_icon, pady=0)
        else:
            open_drive_button.configure(text="Open Drive folder", font=("Segoe UI", 12, "bold"))
        open_drive_button.pack(fill=BOTH, expand=True)

        self.progress = Progressbar(main_tab, mode="indeterminate")
        self.progress.pack(fill="x", pady=(0, 8))

        self._label(
            main_tab,
            textvariable=self.status,
            anchor="nw",
            justify=LEFT,
            font=("Segoe UI", 10),
            padx=2,
        ).pack(fill="x", pady=(0, 8))

        self.history_cards_canvas = Canvas(history_tab, highlightthickness=0, background=self.theme["window"])
        self.history_cards_scrollbar = TtkScrollbar(
            history_tab,
            orient="vertical",
            command=self.history_cards_canvas.yview,
            style="Vertical.TScrollbar",
        )
        self.history_cards_frame = self._frame(self.history_cards_canvas)
        self.history_cards_frame.bind(
            "<Configure>",
            lambda _event: self.history_cards_canvas.configure(scrollregion=self.history_cards_canvas.bbox("all")),
        )
        self.history_cards_canvas_window = self.history_cards_canvas.create_window(
            (0, 0),
            window=self.history_cards_frame,
            anchor="nw",
        )
        self.history_cards_canvas.configure(yscrollcommand=self.history_cards_scrollbar.set)
        self.history_cards_canvas.bind(
            "<Configure>",
            lambda event: self.history_cards_canvas.itemconfigure(self.history_cards_canvas_window, width=event.width),
        )
        self.history_cards_canvas.pack(side=LEFT, fill=BOTH, expand=True)
        self.history_cards_scrollbar.pack(side=RIGHT, fill=Y)

        self.drive_cards_canvas = Canvas(drive_tab, highlightthickness=0, background=self.theme["window"])
        self.drive_cards_scrollbar = TtkScrollbar(
            drive_tab,
            orient="vertical",
            command=self.drive_cards_canvas.yview,
            style="Vertical.TScrollbar",
        )
        self.drive_cards_frame = self._frame(self.drive_cards_canvas)
        self.drive_cards_frame.bind(
            "<Configure>",
            lambda _event: self.drive_cards_canvas.configure(scrollregion=self.drive_cards_canvas.bbox("all")),
        )
        self.drive_cards_canvas_window = self.drive_cards_canvas.create_window(
            (0, 0),
            window=self.drive_cards_frame,
            anchor="nw",
        )
        self.drive_cards_canvas.configure(yscrollcommand=self.drive_cards_scrollbar.set)
        self.drive_cards_canvas.bind(
            "<Configure>",
            lambda event: self.drive_cards_canvas.itemconfigure(self.drive_cards_canvas_window, width=event.width),
        )
        self.drive_cards_canvas.pack(side=LEFT, fill=BOTH, expand=True)
        self.drive_cards_scrollbar.pack(side=RIGHT, fill=Y)
        footer = self._frame(container)
        footer.pack(fill=X, pady=(6, 0))
        self.version_label = self._label(
            footer,
            text=f"Version {self.version}",
            anchor="e",
            font=("Segoe UI", 8),
            foreground=self.theme["muted"],
            background=self.theme["window"],
        )
        self.version_label.pack(side=RIGHT)
        self._build_settings_tab(settings_tab)

    def _build_settings_tab(self, settings_tab: Frame) -> None:
        theme_frame = self._frame(settings_tab, padx=10, pady=12)
        theme_frame.pack(fill=X)
        self._label(theme_frame, text="Theme", anchor="w", font=("Segoe UI", 12, "bold")).pack(fill=X)
        for value, label in (("system", "System default"), ("light", "Light"), ("dark", "Dark")):
            self._radiobutton(
                theme_frame,
                text=label,
                value=value,
                variable=self.theme_choice,
                command=self._handle_theme_changed,
                font=("Segoe UI", 10),
                anchor="w",
            ).pack(fill=X, pady=(8, 0))

        data_frame = self._frame(settings_tab, padx=10, pady=12)
        data_frame.pack(fill=X)
        self._label(data_frame, text="Folders", anchor="w", font=("Segoe UI", 12, "bold")).pack(fill=X)
        self._button(
            data_frame,
            text="Open token folder",
            command=self._open_app_folder,
            font=("Segoe UI", 10),
        ).pack(anchor="w", pady=(8, 0))

        startup_frame = self._frame(settings_tab, padx=10, pady=12)
        startup_frame.pack(fill=X)
        self._label(startup_frame, text="Startup", anchor="w", font=("Segoe UI", 12, "bold")).pack(fill=X)
        self._checkbutton(
            startup_frame,
            text="Open with OS",
            variable=self.open_with_os,
            command=self._handle_open_with_os_changed,
            font=("Segoe UI", 10),
            anchor="w",
        ).pack(fill=X, pady=(8, 0))
        self._checkbutton(
            startup_frame,
            text="Omit '?usp=drivesdk' from copied Drive links",
            variable=self.omit_drivesdk_query,
            command=self._handle_omit_drivesdk_query_changed,
            font=("Segoe UI", 10),
            anchor="w",
        ).pack(fill=X, pady=(8, 0))

        screenshot_frame = self._frame(settings_tab, padx=10, pady=12)
        screenshot_frame.pack(fill=X)
        self._label(screenshot_frame, text="Screenshot monitor", anchor="w", font=("Segoe UI", 12, "bold")).pack(fill=X)
        self._checkbutton(
            screenshot_frame,
            text="Monitor screenshot folder for new files and auto-upload",
            variable=self.screenshot_monitor_enabled,
            command=self._handle_screenshot_monitor_changed,
            font=("Segoe UI", 10),
            anchor="w",
        ).pack(fill=X, pady=(8, 0))
        folder_path_frame = self._frame(screenshot_frame)
        folder_path_frame.pack(fill=X, pady=(8, 0))
        self._label(folder_path_frame, text="Folder", anchor="w", font=("Segoe UI", 10)).pack(side=LEFT)
        self.screenshot_monitor_entry = Entry(
            folder_path_frame,
            textvariable=self.screenshot_monitor_folder,
            font=("Segoe UI", 9),
        )
        self.screenshot_monitor_entry.pack(side=LEFT, fill=X, expand=True, padx=(8, 0))
        self._button(
            folder_path_frame,
            text="Browse...",
            command=self._browse_screenshot_folder,
            font=("Segoe UI", 9),
            padx=6,
            pady=2,
        ).pack(side=RIGHT, padx=(8, 0))

        deletion_frame = self._frame(settings_tab, padx=10, pady=12)
        deletion_frame.pack(fill=X)
        self._label(deletion_frame, text="Delete confirmations", anchor="w", font=("Segoe UI", 12, "bold")).pack(fill=X)
        self._checkbutton(
            deletion_frame,
            text="Confirm file deletions in Upload History?",
            variable=self.confirm_history_drive_deletions,
            command=self._handle_delete_settings_changed,
            font=("Segoe UI", 10),
            anchor="w",
        ).pack(fill=X, pady=(8, 0))
        self._checkbutton(
            deletion_frame,
            text="Confirm file deletions in Drive Folder?",
            variable=self.confirm_drive_folder_deletions,
            command=self._handle_delete_settings_changed,
            font=("Segoe UI", 10),
            anchor="w",
        ).pack(fill=X, pady=(8, 0))

    def _handle_omit_drivesdk_query_changed(self) -> None:
        self.settings["omit_drivesdk_query"] = self.omit_drivesdk_query.get()
        save_settings(self.settings)

    def _handle_screenshot_monitor_changed(self) -> None:
        enabled = self.screenshot_monitor_enabled.get()
        folder = self.screenshot_monitor_folder.get().strip() or DEFAULT_SCREENSHOT_MONITOR_FOLDER
        self.settings["screenshot_monitor_enabled"] = enabled
        self.settings["screenshot_monitor_folder"] = folder
        save_settings(self.settings)
        if enabled:
            self.screenshot_monitor_folder.set(folder)
            self._start_screenshot_watcher()
        else:
            self._stop_screenshot_watcher()

    def _browse_screenshot_folder(self) -> None:
        folder = filedialog.askdirectory(
            title="Select screenshot folder",
            initialdir=self.screenshot_monitor_folder.get() or str(Path.home() / "Pictures"),
        )
        if folder:
            self.screenshot_monitor_folder.set(folder)
            self._handle_screenshot_monitor_changed()

    def _handle_canvas_mousewheel(self, event) -> str | None:  # type: ignore[no-untyped-def]
        canvas = self._selected_scroll_canvas()
        if canvas is None or not self._pointer_is_inside_widget(canvas):
            return

        bbox = canvas.bbox("all")
        if bbox is None:
            return
        content_height = bbox[3] - bbox[1]
        viewport_height = canvas.winfo_height()
        scrollable_height = max(0, content_height - viewport_height)
        if scrollable_height == 0:
            return

        if getattr(event, "num", None) == 4:
            pixels = -48
        elif getattr(event, "num", None) == 5:
            pixels = 48
        else:
            pixels = -(event.delta / 120) * 48

        top, _bottom = canvas.yview()
        next_top = top + (pixels / scrollable_height)
        next_top = max(0.0, min(1.0, next_top))
        canvas.yview_moveto(next_top)
        return "break"

    def _selected_scroll_canvas(self) -> Canvas | None:
        if not getattr(self, "tabs", None):
            return None
        selected_tab = self.tabs.tab(self.tabs.select(), "text")
        if selected_tab == "Upload History":
            return self.history_cards_canvas
        if selected_tab == "Drive Folder":
            return self.drive_cards_canvas
        return None

    def _pointer_is_inside_widget(self, widget) -> bool:  # type: ignore[no-untyped-def]
        pointer_x = widget.winfo_pointerx()
        pointer_y = widget.winfo_pointery()
        widget_x = widget.winfo_rootx()
        widget_y = widget.winfo_rooty()
        return (
            widget_x <= pointer_x < widget_x + widget.winfo_width()
            and widget_y <= pointer_y < widget_y + widget.winfo_height()
        )

    def _frame(self, parent, **options):  # type: ignore[no-untyped-def]
        options.setdefault("background", self.theme["window"])
        return Frame(parent, **options)

    def _label(self, parent, **options):  # type: ignore[no-untyped-def]
        options.setdefault("background", self.theme["window"])
        options.setdefault("foreground", self.theme["text"])
        return Label(parent, **options)

    def _button(self, parent, **options):  # type: ignore[no-untyped-def]
        options.setdefault("background", self.theme["button"])
        options.setdefault("foreground", self.theme["text"])
        options.setdefault("activebackground", self.theme["button_active"])
        options.setdefault("activeforeground", self.theme["text"])
        options.setdefault("highlightbackground", self.theme["window"])
        options.setdefault("highlightcolor", self.theme["accent"])
        options.setdefault("relief", "raised")
        return Button(parent, **options)

    def _radiobutton(self, parent, **options):  # type: ignore[no-untyped-def]
        options.pop("font", None)
        options.pop("anchor", None)
        options.setdefault("style", "Settings.TRadiobutton")
        return TtkRadiobutton(parent, **options)

    def _checkbutton(self, parent, **options):  # type: ignore[no-untyped-def]
        options.pop("font", None)
        options.pop("anchor", None)
        options.setdefault("style", "Settings.TCheckbutton")
        return TtkCheckbutton(parent, **options)

    def _setup_tray(self) -> None:
        if self.tray_icon:
            return
        if not ICON_FILE.exists():
            return
        icon_image = Image.open(ICON_FILE)
        menu = Menu(
            MenuItem("Show", self._show_window_from_tray, default=True),
            MenuItem("Paste link", self._paste_link_from_tray),
            MenuItem("Quit", self._quit_app)
        )
        self.tray_icon = TrayIcon("GDriveLink", icon_image, "GDriveLink", menu=menu)
        self.tray_icon.run_detached()

    def _effective_theme_name(self) -> str:
        selected_theme = self.theme_choice.get() if hasattr(self, "theme_choice") else "system"
        if selected_theme == "dark" or (selected_theme == "system" and system_prefers_dark_theme()):
            return "dark"
        return "light"

    def _handle_theme_changed(self) -> None:
        selected_theme = self.theme_choice.get()
        if selected_theme not in THEME_OPTIONS:
            selected_theme = "system"
            self.theme_choice.set(selected_theme)
        self.settings["theme"] = selected_theme
        save_settings(self.settings)
        self.theme = DARK_THEME if self._effective_theme_name() == "dark" else LIGHT_THEME
        self._configure_ttk_theme()
        self._apply_theme()

    def _handle_delete_settings_changed(self) -> None:
        self.settings["confirm_history_drive_deletions"] = self.confirm_history_drive_deletions.get()
        self.settings["confirm_drive_folder_deletions"] = self.confirm_drive_folder_deletions.get()
        save_settings(self.settings)

    def _handle_open_with_os_changed(self) -> None:
        enabled = self.open_with_os.get()
        try:
            set_open_with_os_enabled(enabled)
        except OSError as error:
            self.open_with_os.set(not enabled)
            messagebox.showerror(APP_TITLE, f"Could not update OS startup setting:\n\n{error}")
            return
        self.settings["open_with_os"] = enabled
        save_settings(self.settings)

    def _configure_ttk_theme(self) -> None:
        try:
            self.style.theme_use("clam")
        except Exception:
            pass
        colors = self.theme
        self.style.configure(
            ".",
            background=colors["window"],
            foreground=colors["text"],
            fieldbackground=colors["entry"],
            bordercolor=colors["border"],
            lightcolor=colors["border"],
            darkcolor=colors["border"],
            troughcolor=colors["surface_alt"],
        )
        self.style.configure("TNotebook", background=colors["window"], borderwidth=0)
        self.style.configure(
            "TNotebook.Tab",
            background=colors["surface_alt"],
            foreground=colors["text"],
            padding=(14, 8),
        )
        self.style.map(
            "TNotebook.Tab",
            background=[("selected", colors["surface"]), ("active", colors["button_active"])],
            foreground=[("selected", colors["text"]), ("active", colors["text"])],
        )
        self.style.configure(
            "Settings.TRadiobutton",
            background=colors["window"],
            foreground=colors["text"],
            focuscolor=colors["window"],
            font=("Segoe UI", 10),
        )
        self.style.map(
            "Settings.TRadiobutton",
            background=[("active", colors["window"]), ("selected", colors["window"])],
            foreground=[("active", colors["text"]), ("selected", colors["text"])],
        )
        self.style.configure(
            "Settings.TCheckbutton",
            background=colors["window"],
            foreground=colors["text"],
            focuscolor=colors["window"],
            font=("Segoe UI", 10),
        )
        self.style.map(
            "Settings.TCheckbutton",
            background=[("active", colors["window"]), ("selected", colors["window"])],
            foreground=[("active", colors["text"]), ("selected", colors["text"])],
        )
        self.style.configure(
            "Horizontal.TProgressbar",
            background=colors["accent"],
            troughcolor=colors["surface_alt"],
            bordercolor=colors["border"],
            lightcolor=colors["accent"],
            darkcolor=colors["accent"],
        )
        self.style.configure(
            "Vertical.TScrollbar",
            background=colors["button"],
            troughcolor=colors["window"],
            bordercolor=colors["window"],
            arrowcolor=colors["text"],
            lightcolor=colors["button"],
            darkcolor=colors["button"],
            relief="flat",
            width=14,
        )
        self.style.map(
            "Vertical.TScrollbar",
            background=[("active", colors["button_active"]), ("pressed", colors["button_active"])],
            arrowcolor=[("active", colors["text"]), ("pressed", colors["text"])],
        )

    def _apply_theme(self, root_widget=None) -> None:
        colors = self.theme
        widget = root_widget or self.root
        self._style_widget_tree(widget)
        set_windows_dark_title_bar(widget, self._effective_theme_name() == "dark")
        for child in widget.winfo_children():
            if isinstance(child, Toplevel):
                set_windows_dark_title_bar(child, self._effective_theme_name() == "dark")
        self.root.option_add("*selectBackground", colors["select"])
        self.root.option_add("*selectForeground", colors["select_text"])

    def _style_widget_tree(self, widget) -> None:
        colors = self.theme
        widget_class = widget.winfo_class()
        try:
            if widget_class in {"Tk", "Toplevel", "Frame", "Labelframe"}:
                widget.configure(background=colors["window"])
            elif isinstance(widget, Canvas):
                widget.configure(background=colors["window"])
            elif isinstance(widget, Label):
                background = colors["drop"] if widget is getattr(self, "drop_area", None) else colors["window"]
                foreground = colors["muted"] if widget is getattr(self, "version_label", None) else colors["text"]
                widget.configure(background=background, foreground=foreground)
            elif isinstance(widget, Button):
                if getattr(widget, "_gdrive_icon_button", False):
                    widget.configure(
                        background=colors["window"],
                        activebackground=colors["window"],
                    )
                else:
                    widget.configure(
                        background=colors["button"],
                        foreground=colors["text"],
                        activebackground=colors["button_active"],
                        activeforeground=colors["text"],
                        highlightbackground=colors["window"],
                        highlightcolor=colors["accent"],
                    )
            elif isinstance(widget, Entry):
                widget.configure(
                    background=colors["entry"],
                    foreground=colors["entry_text"],
                    insertbackground=colors["entry_text"],
                    highlightbackground=colors["border"],
                    highlightcolor=colors["accent"],
                )
            elif isinstance(widget, Listbox):
                widget.configure(
                    background=colors["entry"],
                    foreground=colors["entry_text"],
                    selectbackground=colors["select"],
                    selectforeground=colors["select_text"],
                    highlightbackground=colors["border"],
                    highlightcolor=colors["accent"],
                )
            elif isinstance(widget, Radiobutton):
                widget.configure(
                    background=colors["window"],
                    foreground=colors["text"],
                    activebackground=colors["window"],
                    activeforeground=colors["text"],
                    selectcolor=colors["surface_alt"],
                    highlightbackground=colors["window"],
                )
            elif isinstance(widget, Checkbutton):
                widget.configure(
                    background=colors["window"],
                    foreground=colors["text"],
                    activebackground=colors["window"],
                    activeforeground=colors["text"],
                    selectcolor=colors["surface_alt"],
                    highlightbackground=colors["window"],
                )
            elif isinstance(widget, Scrollbar):
                widget.configure(
                    background=colors["button"],
                    activebackground=colors["button_active"],
                    troughcolor=colors["surface_alt"],
                    borderwidth=0,
                    elementborderwidth=1,
                    highlightbackground=colors["window"],
                    highlightcolor=colors["window"],
                    highlightthickness=0,
                    relief="flat",
                    width=14,
                )
        except Exception:
            pass

        for child in widget.winfo_children():
            self._style_widget_tree(child)

    def _run_on_ui_thread(self, callback) -> None:
        try:
            self.root.after(0, callback)
        except RuntimeError:
            pass

    def _show_window_from_tray(self, icon=None, item=None) -> None:
        self._run_on_ui_thread(self._show_window)

    def _paste_link_from_tray(self, icon=None, item=None) -> None:
        self._run_on_ui_thread(self._paste_link)

    def _paste_link(self) -> None:
        try:
            link = self.root.clipboard_get()
        except Exception:
            messagebox.showerror(APP_TITLE, "Could not read clipboard.")
            return
        if not link or not link.strip().lower().startswith(("http://", "https://")):
            messagebox.showinfo(APP_TITLE, "Clipboard does not contain a valid link.")
            return

        link = link.strip()
        try:
            parsed = urlparse(link)
            filename = Path(parsed.path).name or "downloaded_file"
            if not Path(filename).suffix:
                filename += ".bin"
            temp_path = Path(tempfile.gettempdir()) / filename
            urllib.request.urlretrieve(link, temp_path)
            self._upload_files([temp_path], cleanup_after_upload=True)
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Failed to download or upload from link:\n{exc}")

    def _show_window(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _toggle_window(self, icon=None, item=None) -> None:
        self._run_on_ui_thread(self._toggle_window_on_ui)

    def _toggle_window_on_ui(self) -> None:
        if self.root.state() == 'withdrawn':
            self._show_window()
        else:
            self._hide_to_tray()

    def _handle_window_unmap(self, _event=None) -> None:
        if self.root.state() == "iconic":
            self.root.after_idle(self._hide_to_tray)

    def _hide_to_tray(self) -> None:
        self.root.withdraw()
        if not self.tray_icon:
            self._setup_tray()

    def _quit_app(self, icon, item) -> None:
        self._run_on_ui_thread(self._on_close)

    def _on_close(self) -> None:
        self._stop_screenshot_watcher()
        if self.tray_icon:
            self.tray_icon.stop()
        self.root.quit()

    def _clear_history_cards(self) -> None:
        self.history_cards.clear()
        for child in self.history_cards_frame.winfo_children():
            child.destroy()

    def _show_history_message(self, message: str) -> None:
        Label(
            self.history_cards_frame,
            text=message,
            anchor="w",
            justify=LEFT,
            font=("Segoe UI", 10),
            padx=10,
            pady=10,
        ).pack(fill=X)
        self._apply_theme(self.history_cards_frame)

    def _load_history_cards(self) -> None:
        self._clear_history_cards()
        if not self.history:
            self._show_history_message("No past uploads yet. Files you upload will be listed here as cards.")
        else:
            for item in self.history:
                self._add_history_card(item)

    def _add_history_card(self, item: dict[str, str], at_top: bool = False) -> None:
        if len(self.history_cards) == 0 and self.history_cards_frame.winfo_children():
            for child in list(self.history_cards_frame.winfo_children()):
                child.destroy()
        card = Frame(self.history_cards_frame, relief="ridge", borderwidth=1, padx=10, pady=8)
        if at_top and self.history_cards_frame.winfo_children():
            card.pack(fill=X, pady=(0, 8), before=self.history_cards_frame.winfo_children()[0])
        else:
            card.pack(fill=X, pady=(0, 8))
        if at_top:
            self.history_cards.insert(0, card)
        else:
            self.history_cards.append(card)

        top_row = Frame(card)
        top_row.pack(fill=X)

        name = item.get("name", "")
        Label(top_row, text=name, anchor="w", font=("Segoe UI", 10, "bold")).pack(side=LEFT, fill=X, expand=True)

        folder_name = item.get("folder_name", "")
        Label(top_row, text=f"[{folder_name}]", anchor="e", font=("Segoe UI", 9)).pack(side=RIGHT, padx=(8, 0))

        permission = item.get("sharingStatus", "Anyone with link can read")
        Label(top_row, text=permission, anchor="e", font=("Segoe UI", 9)).pack(side=RIGHT, padx=(8, 0))

        meta_row = Frame(card)
        meta_row.pack(fill=X, pady=(5, 0))

        uploaded_at = item.get("uploaded_at", "")
        Label(meta_row, text=f"Uploaded: {uploaded_at}", anchor="w", font=("Segoe UI", 9)).pack(
            side=LEFT, fill=X, expand=True
        )

        delete_from_drive = BooleanVar(value=False)
        Button(
            meta_row,
            text="Open",
            command=lambda current_item=item: self._open_history_link(current_item),
        ).pack(side=RIGHT, padx=(8, 0))
        Button(
            meta_row,
            text="Set sharing",
            command=lambda current_item=item: self._set_history_sharing(current_item),
        ).pack(side=RIGHT)
        Button(
            meta_row,
            text="Copy link",
            command=lambda current_item=item: self._copy_history_link(current_item),
        ).pack(side=RIGHT)
        Button(
            meta_row,
            text="Remove",
            command=lambda current_item=item, current_card=card, current_delete=delete_from_drive: self._remove_history_item(
                current_item,
                current_card,
                current_delete.get(),
            ),
        ).pack(side=RIGHT, padx=(0, 8))
        Checkbutton(
            meta_row,
            text="Delete from Drive?",
            variable=delete_from_drive,
            font=("Segoe UI", 9),
        ).pack(side=RIGHT, padx=(0, 8))
        self._apply_theme(card)

    def _open_history_link(self, item: dict[str, str]) -> None:
        link = item.get("webViewLink")
        if link:
            webbrowser.open(self._normalize_drive_link(link))

    def _copy_history_link(self, item: dict[str, str]) -> None:
        link = item.get("webViewLink", "")
        if link:
            self._copy_to_clipboard(link)
            self.status.set("Link copied to the clipboard.")

    def _remove_history_item(self, item: dict[str, str], card: Frame, delete_from_drive: bool = False) -> None:
        if delete_from_drive:
            name = item.get("name", "this file")
            if not item.get("id"):
                self.status.set(f"Could not delete '{name}' from Drive because this history entry has no file ID.")
                return
            if self.confirm_history_drive_deletions.get():
                confirmed = messagebox.askyesno(
                    APP_TITLE,
                    f"Remove '{name}' from Upload History and delete it from Google Drive?",
                )
                if not confirmed:
                    return
            self.status.set(f"Deleting '{name}' from Drive...")
            worker = threading.Thread(
                target=self._remove_history_item_from_drive_worker,
                args=(item, card),
                daemon=True,
            )
            worker.start()
            return
        self._remove_history_item_from_view(item, card)

    def _remove_history_item_from_view(self, item: dict[str, str], card: Frame) -> None:
        try:
            self.history.remove(item)
        except ValueError:
            pass
        save_history(self.history)
        try:
            self.history_cards.remove(card)
        except ValueError:
            pass
        card.destroy()
        if not self.history:
            self._show_history_message("No past uploads yet. Files you upload will be listed here as cards.")

    def _remove_history_item_from_drive_worker(self, item: dict[str, str], card: Frame) -> None:
        name = item.get("name", "file")
        try:
            service = get_drive_service()
            trash_drive_file(service, item["id"])
            def notify_success():
                self._remove_history_item_from_view(item, card)
                self.status.set(f"Deleted '{name}' from Drive and removed it from Upload History.")
            self._run_on_ui_thread(notify_success)
        except Exception as exc:
            self._run_on_ui_thread(lambda e=str(exc): self.status.set(f"Could not delete '{name}' from Drive: {e}"))

    def _set_history_sharing(self, item: dict[str, str]) -> None:
        name = item.get("name", "file")
        self.status.set(f"Updating sharing permission for '{name}'...")
        worker = threading.Thread(target=self._set_history_sharing_worker, args=(item,), daemon=True)
        worker.start()

    def _set_history_sharing_worker(self, item: dict[str, str]) -> None:
        name = item.get("name", "file")
        try:
            service = get_drive_service()
            new_status, shared_file = cycle_sharing_permission(service, item["id"])
            if "webViewLink" in shared_file:
                item["webViewLink"] = shared_file["webViewLink"]
            item["sharingStatus"] = new_status
            save_history(self.history)
            def notify_success():
                self._load_history_cards()
                self.status.set(f"Sharing set to '{new_status}' for '{name}'.")
            self._run_on_ui_thread(notify_success)
        except Exception as exc:
            self._run_on_ui_thread(lambda e=str(exc): self.status.set(f"Could not set sharing for '{name}': {e}"))

    def _handle_main_return(self, _event=None) -> None:
        focused = self.root.focus_get()
        if focused and focused.winfo_toplevel() != self.root:
            return
        if self.tabs and self.tabs.index(self.tabs.select()) == 0 and self.choose_button:
            self.choose_button.invoke()

    def _choose_files(self) -> None:
        filenames = filedialog.askopenfilenames(title="Choose files to upload")
        if filenames:
            self._upload_files([Path(filename) for filename in filenames])

    def _handle_drop(self, event) -> None:
        files = [Path(file) for file in self.root.tk.splitlist(event.data)]
        self._upload_files(files)

    def _handle_clipboard_paste(self, _event=None) -> str | None:
        try:
            image = ImageGrab.grabclipboard()
        except Exception as exc:  # noqa: BLE001 - show clipboard errors in the UI.
            messagebox.showerror(APP_TITLE, f"Could not read an image from the clipboard:\n{exc}")
            return "break"

        if image is None:
            self.status.set("Clipboard does not contain an image or a file.")
            return "break"

        if isinstance(image, list):
            paths = [Path(p) for p in image]
            self._show_clipboard_files_preview(paths)
            return "break"

        self._show_clipboard_preview(image)
        return "break"

    def _show_clipboard_preview(self, image) -> None:
        preview_window = Toplevel(self.root)
        preview_window.title("Clipboard image preview")
        preview_window.transient(self.root)
        preview_window.grab_set()
        preview_window.minsize(360, 300)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = StringVar(value=f"clipboard_image_{timestamp}.png")

        preview_image = image.copy()
        preview_image.thumbnail((720, 420))
        self.preview_photo = ImageTk.PhotoImage(preview_image)

        Label(preview_window, text="Upload clipboard image?", font=("Segoe UI", 12, "bold")).pack(
            fill=X,
            padx=14,
            pady=(14, 8),
        )
        Label(preview_window, image=self.preview_photo).pack(fill=BOTH, expand=True, padx=14, pady=(0, 14))

        filename_frame = Frame(preview_window)
        filename_frame.pack(fill=X, padx=14, pady=(0, 14))
        Label(filename_frame, text="Filename", anchor="w", font=("Segoe UI", 10)).pack(side=LEFT)
        filename_entry = Entry(filename_frame, textvariable=filename)
        filename_entry.pack(side=LEFT, fill=X, expand=True, padx=(8, 0))

        buttons = Frame(preview_window)
        buttons.pack(fill=X, padx=14, pady=(0, 14))

        Button(buttons, text="Cancel", command=preview_window.destroy).pack(side=RIGHT)
        ok_button = Button(
            buttons,
            text="OK",
            command=lambda: self._confirm_clipboard_upload(preview_window, image, filename.get()),
        )
        ok_button.pack(side=RIGHT, padx=(0, 8))
        preview_window.bind("<Return>", lambda e: ok_button.invoke())
        preview_window.bind("<Escape>", lambda e: preview_window.destroy())
        filename_entry.focus_set()
        filename_entry.icursor(END)
        self._apply_theme(preview_window)

    def _confirm_clipboard_upload(self, preview_window: Toplevel, image, filename: str) -> None:
        preview_window.destroy()
        clean_filename = self._clean_clipboard_filename(filename)
        temp_path = Path(tempfile.gettempdir()) / clean_filename
        image.save(temp_path, "PNG")
        self._upload_files([temp_path], cleanup_after_upload=True)

    def _show_clipboard_files_preview(self, paths: list[Path]) -> None:
        preview_window = Toplevel(self.root)
        preview_window.title("Clipboard files preview")
        preview_window.transient(self.root)
        preview_window.grab_set()
        preview_window.minsize(360, 300)
        Label(preview_window, text="Upload clipboard files?", font=("Segoe UI", 12, "bold")).pack(
            fill=X,
            padx=14,
            pady=(14, 8),
        )
        info_frame = Frame(preview_window)
        info_frame.pack(fill=BOTH, expand=True, padx=14, pady=(0, 14))
        for path in paths:
            size = 0
            try:
                size = path.stat().st_size
            except OSError:
                pass
            if size >= 1048576:
                size_str = f"{size / 1048576:.1f} MB"
            elif size >= 1024:
                size_str = f"{size / 1024:.1f} KB"
            else:
                size_str = f"{size} B"
            Label(info_frame, text=f"{path.name} ({size_str})", anchor="w", font=("Segoe UI", 10)).pack(fill=X, pady=(0, 4))
        buttons = Frame(preview_window)
        buttons.pack(fill=X, padx=14, pady=(0, 14))
        Button(buttons, text="Cancel", command=preview_window.destroy).pack(side=RIGHT)
        ok_button = Button(
            buttons,
            text="OK",
            command=lambda: self._confirm_clipboard_files_upload(preview_window, paths),
        )
        ok_button.pack(side=RIGHT, padx=(0, 8))
        preview_window.bind("<Return>", lambda e: ok_button.invoke())
        preview_window.bind("<Escape>", lambda e: preview_window.destroy())
        ok_button.focus_set()
        self._apply_theme(preview_window)

    def _confirm_clipboard_files_upload(self, preview_window: Toplevel, paths: list[Path]) -> None:
        preview_window.destroy()
        self._upload_files(paths)

    def _clean_clipboard_filename(self, filename: str) -> str:
        clean_name = Path(filename.strip()).name
        if not clean_name:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            clean_name = f"clipboard_image_{timestamp}.png"
        if Path(clean_name).suffix.lower() != ".png":
            clean_name = f"{Path(clean_name).stem}.png"
        return clean_name

    def _upload_files(self, paths: list[Path], cleanup_after_upload: bool = False) -> None:
        files = [path for path in paths if path.is_file()]
        if not files:
            messagebox.showinfo(APP_TITLE, "Drop or choose one or more files.")
            return

        self.status.set(f"Uploading {len(files)} file(s)...")
        self.pending_uploads += len(files)
        self.progress.start(10)

        folder_name = self.drive_folder_name.get().strip() or "GDriveLink"
        self.drive_folder_name.set(folder_name)

        worker = threading.Thread(
            target=self._upload_worker,
            args=(files, folder_name, cleanup_after_upload),
            daemon=True,
        )
        worker.start()

    def _upload_worker(self, files: list[Path], folder_name: str, cleanup_after_upload: bool) -> None:
        try:
            service = get_drive_service()
            folder_id = get_or_create_folder(service, folder_name)
            for file_path in files:
                try:
                    name = file_path.name
                    existing_id = find_existing_file_in_folder(service, folder_id, name)
                    if existing_id:
                        suggested = get_unique_filename(service, folder_id, name)
                        self.result_queue.put(("conflict", name, (file_path, folder_id, existing_id, suggested), 0))
                        action, chosen_name = self.decision_queue.get()
                        if action == "cancel":
                            continue
                        elif action == "rename":
                            final_name = chosen_name or suggested
                            uploaded_file = upload_and_share(service, file_path, folder_id, final_name)
                        else:
                            uploaded_file = overwrite_file_content(service, file_path, existing_id)
                    else:
                        uploaded_file = upload_and_share(service, file_path, folder_id)
                    uploaded_file["folder_name"] = folder_name
                    uploaded_file["uploaded_at"] = datetime.now().isoformat(timespec="seconds")
                    uploaded_file["sharingStatus"] = "Anyone with link can read"
                    self.result_queue.put(("success", file_path.name, uploaded_file, 1))
                except Exception as exc:  # noqa: BLE001 - surface upload errors in the UI.
                    self.result_queue.put(("error", file_path.name, str(exc), 1))
                finally:
                    if cleanup_after_upload:
                        try:
                            file_path.unlink(missing_ok=True)
                        except OSError:
                            pass
        except Exception as exc:  # noqa: BLE001 - surface auth errors in the UI.
            self.result_queue.put(("fatal", "Google Drive authorization failed", str(exc), len(files)))

    def _show_duplicate_dialog(self, original_name: str, suggested_name: str) -> tuple[str, str | None]:
        self._show_root_for_modal()
        dialog = Toplevel(self.root)
        dialog.title("Duplicate file")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.minsize(480, 160)

        Label(dialog, text=f"A file named '{original_name}' already exists in the Drive folder.", font=("Segoe UI", 10)).pack(
            fill=X, padx=14, pady=(14, 4)
        )
        Label(dialog, text="New name for renamed copy (editable):", font=("Segoe UI", 10)).pack(
            fill=X, padx=14, pady=(0, 4)
        )

        name_var = StringVar(value=suggested_name)
        entry = Entry(dialog, textvariable=name_var)
        entry.pack(fill=X, padx=14, pady=(0, 14))

        buttons = Frame(dialog)
        buttons.pack(fill=X, padx=14, pady=(0, 14))

        result: dict[str, str | None] = {"action": None, "name": None}

        def on_overwrite():
            result["action"] = "overwrite"
            result["name"] = None
            dialog.destroy()

        def on_rename():
            new_name = name_var.get().strip() or suggested_name
            result["action"] = "rename"
            result["name"] = new_name
            dialog.destroy()

        def on_cancel():
            result["action"] = "cancel"
            result["name"] = None
            dialog.destroy()

        Button(buttons, text="Overwrite existing", command=on_overwrite).pack(side=LEFT)
        Button(buttons, text="Rename with name above", command=on_rename).pack(side=LEFT, padx=(8, 0))
        Button(buttons, text="Cancel / Skip", command=on_cancel).pack(side=RIGHT)

        entry.focus_set()
        entry.icursor(END)
        dialog.bind("<Return>", lambda e: on_rename())
        dialog.bind("<Escape>", lambda e: on_cancel())
        dialog.protocol("WM_DELETE_WINDOW", on_cancel)
        self._apply_theme(dialog)
        self._center_window(dialog, 520, 180)
        dialog.lift()
        dialog.focus_force()
        dialog.attributes("-topmost", True)
        dialog.after(250, lambda: dialog.attributes("-topmost", False) if dialog.winfo_exists() else None)
        dialog.wait_window()

        return result["action"] or "cancel", result["name"]

    def _show_root_for_modal(self) -> None:
        if self.root.state() == "withdrawn":
            self.root.deiconify()
        if self.root.state() == "iconic":
            self.root.state("normal")
        self.root.lift()
        self.root.focus_force()

    def _center_window(self, window: Toplevel, width: int, height: int) -> None:
        self.root.update_idletasks()
        window.update_idletasks()
        parent_x = self.root.winfo_rootx()
        parent_y = self.root.winfo_rooty()
        parent_width = max(self.root.winfo_width(), width)
        parent_height = max(self.root.winfo_height(), height)
        x = parent_x + max(0, (parent_width - width) // 2)
        y = parent_y + max(0, (parent_height - height) // 2)
        window.geometry(f"{width}x{height}+{x}+{y}")

    def _load_logo(self, height: int) -> ImageTk.PhotoImage | None:
        return self._load_image(LOGO_FILE, height)

    def _load_image(self, image_file: Path, height: int) -> ImageTk.PhotoImage | None:
        if not image_file.exists():
            return None
        try:
            img = Image.open(image_file)
            ratio = height / img.height
            target_w = int(img.width * ratio)
            img = img.resize((target_w, height), Image.Resampling.LANCZOS)
            return ImageTk.PhotoImage(img)
        except Exception:
            return None

    def _load_image_exact(self, image_file: Path) -> ImageTk.PhotoImage | None:
        if not image_file.exists():
            return None
        try:
            return ImageTk.PhotoImage(Image.open(image_file))
        except Exception:
            return None

    def _show_about(self) -> None:
        about = Toplevel(self.root)
        about.title("About GDriveLink")
        about.transient(self.root)
        about.minsize(500, 420)

        if self.dialog_logo:
            Label(about, image=self.dialog_logo).pack(pady=(16, 4))
        else:
            Label(about, text=APP_TITLE, font=("Segoe UI", 18, "bold")).pack(pady=(16, 4))
        Label(about, text=f"Version {self.version}", font=("Segoe UI", 10)).pack()

        Label(
            about,
            text=APP_DESCRIPTION,
            font=("Segoe UI", 10),
            wraplength=460,
            justify=LEFT,
            anchor="nw",
        ).pack(fill=X, padx=20, pady=12)

        Label(about, text="© 2026 Jan-Erik Labbas. All rights reserved.", font=("Segoe UI", 9)).pack(pady=(0, 4))
        Label(about, text="MIT License", font=("Segoe UI", 9)).pack(pady=(0, 8))

        support = Frame(about)
        support.pack()
        Label(support, text="Support me on PayPal: ", font=("Segoe UI", 10)).pack(side=LEFT)
        link = Label(
            support,
            text="paypal.me/jamps3",
            font=("Segoe UI", 10, "underline"),
            cursor="hand2",
        )
        link.pack(side=LEFT)
        link.bind("<Button-1>", lambda _e: webbrowser.open("https://paypal.me/jamps3"))

        close_button = Button(about, text="Close", command=about.destroy, font=("Segoe UI", 10), padx=20, pady=6)
        close_button.pack(pady=16)

        about.bind("<Escape>", lambda _e: about.destroy())
        about.bind("<Return>", lambda _e: close_button.invoke())

        self._apply_theme(about)
        link.configure(foreground=self.theme["accent"])
        self._center_window(about, 520, 440)
        about.lift()
        about.focus_force()
        close_button.focus_set()

    def _poll_results(self) -> None:
        got_result = False
        while True:
            try:
                kind, name, detail, completed_count = self.result_queue.get_nowait()
            except queue.Empty:
                break

            got_result = True
            self.pending_uploads = max(0, self.pending_uploads - completed_count)
            if kind == "success" and isinstance(detail, dict):
                self.history.insert(0, detail)
                save_history(self.history)
                self._add_history_card(detail, at_top=True)
                link = detail.get("webViewLink", "")
                self._copy_to_clipboard(link)
            elif kind == "conflict" and isinstance(detail, tuple) and len(detail) == 4:
                file_path, folder_id, existing_id, suggested_name = detail
                action, chosen_name = self._show_duplicate_dialog(name, suggested_name)
                if action == "cancel":
                    self.pending_uploads = max(0, self.pending_uploads - 1)
                    self.status.set(f"Skipped upload of {name} (duplicate name).")
                self.decision_queue.put((action, chosen_name))
            else:
                self.status.set(f"{name}  ->  ERROR: {detail}")

        if got_result and self.pending_uploads == 0:
            self.progress.stop()
            self.status.set("Done. The latest uploaded link was copied to the clipboard.")

        self.root.after(100, self._poll_results)

    def _refresh_drive_files(self) -> None:
        for tab_id in self.tabs.tabs():
            if self.tabs.tab(tab_id, "text") == "Drive Folder":
                self.tabs.select(tab_id)
                break
        folder_name = self.drive_folder_name.get().strip() or "GDriveLink"
        self.drive_folder_name.set(folder_name)
        self.status.set(f"Loading files in Drive folder '{folder_name}'...")
        self._clear_drive_cards()
        self._show_drive_message("Loading...")
        worker = threading.Thread(target=self._refresh_drive_files_worker, args=(folder_name,), daemon=True)
        worker.start()

    def _refresh_drive_files_worker(self, folder_name: str) -> None:
        try:
            service = get_drive_service()
            folder_id = get_or_create_folder(service, folder_name)
            files = list_drive_folder_files(service, folder_id)
            self.drive_files_queue.put(("success", files))
        except Exception as exc:  # noqa: BLE001 - surface Drive errors in the UI.
            self.drive_files_queue.put(("error", str(exc)))

    def _poll_drive_files(self) -> None:
        while True:
            try:
                kind, detail = self.drive_files_queue.get_nowait()
            except queue.Empty:
                break

            if kind == "success" and isinstance(detail, list):
                self._clear_drive_cards()
                if not detail:
                    self._show_drive_message("No files found in this Drive folder.")
                for item in detail:
                    self._add_drive_file_card(item)
                self.status.set("Drive folder file list loaded.")
            elif kind == "copy_success" and isinstance(detail, list) and detail:
                item = detail[0]
                link = item.get("webViewLink", "")
                if link:
                    self._copy_to_clipboard(link)
                self.status.set("Selected Drive folder link copied and sharing is enabled.")
                self._refresh_drive_files()
            elif kind == "copy_error":
                self._clear_drive_cards()
                self._show_drive_message(f"ERROR: {detail}")
                self.status.set("Could not update sharing permission.")
            elif kind == "perm_success" and isinstance(detail, list) and detail:
                self.status.set("Sharing permission updated for Drive file.")
                self._refresh_drive_files()
            elif kind == "perm_error":
                self._clear_drive_cards()
                self._show_drive_message(f"ERROR: {detail}")
                self.status.set("Could not update sharing permission.")
            elif kind == "delete_success":
                if isinstance(detail, dict):
                    file_id = detail.get("id", "")
                    name = detail.get("name", "File")
                    self._remove_drive_file_card(file_id)
                    self.status.set(f"Deleted '{name}' from Drive.")
                else:
                    self.status.set("Deleted file from Drive.")
            elif kind == "delete_error":
                self._show_drive_message(f"ERROR: {detail}")
                self.status.set("Could not delete Drive file.")
            else:
                self._clear_drive_cards()
                self._show_drive_message(f"ERROR: {detail}")
                self.status.set("Could not load Drive folder files.")

        self.root.after(100, self._poll_drive_files)

    def _copy_drive_file_link(self, file_id: str) -> None:
        item = self.drive_files_by_id.get(file_id)
        if not item:
            return
        self.status.set("Updating file sharing permission before copying link...")
        worker = threading.Thread(target=self._copy_drive_link_worker, args=(item,), daemon=True)
        worker.start()

    def _set_drive_file_sharing(self, file_id: str) -> None:
        item = self.drive_files_by_id.get(file_id)
        if not item:
            return
        self.status.set("Updating file sharing permission...")
        worker = threading.Thread(target=self._set_drive_sharing_worker, args=(item,), daemon=True)
        worker.start()

    def _delete_drive_file(self, file_id: str) -> None:
        item = self.drive_files_by_id.get(file_id)
        if not item:
            return
        name = item.get("name", "this file")
        if self.confirm_drive_folder_deletions.get():
            confirmed = messagebox.askyesno(APP_TITLE, f"Delete '{name}' from the Drive folder?")
            if not confirmed:
                return
        self.status.set(f"Deleting '{name}' from Drive...")
        worker = threading.Thread(target=self._delete_drive_file_worker, args=(item,), daemon=True)
        worker.start()

    def _open_drive_file_link(self, file_id: str) -> None:
        item = self.drive_files_by_id.get(file_id)
        if item:
            link = item.get("webViewLink")
            if link:
                webbrowser.open(self._normalize_drive_link(link))

    def _clear_drive_cards(self) -> None:
        self.drive_files_by_id.clear()
        self.drive_cards_by_id.clear()
        for child in self.drive_cards_frame.winfo_children():
            child.destroy()

    def _show_drive_message(self, message: str) -> None:
        Label(
            self.drive_cards_frame,
            text=message,
            anchor="w",
            justify=LEFT,
            font=("Segoe UI", 10),
            padx=10,
            pady=10,
        ).pack(fill=X)
        self._apply_theme(self.drive_cards_frame)

    def _add_drive_file_card(self, item: dict[str, str]) -> None:
        file_id = item.get("id", "")
        if file_id:
            self.drive_files_by_id[file_id] = item

        card = Frame(self.drive_cards_frame, relief="ridge", borderwidth=1, padx=10, pady=8)
        card.pack(fill=X, pady=(0, 8))
        if file_id:
            self.drive_cards_by_id[file_id] = card

        top_row = Frame(card)
        top_row.pack(fill=X)

        name = item.get("name", "")
        Label(top_row, text=name, anchor="w", font=("Segoe UI", 10, "bold")).pack(side=LEFT, fill=X, expand=True)

        permission = item.get("sharingStatus", "Unknown")
        Label(top_row, text=permission, anchor="e", font=("Segoe UI", 9)).pack(side=RIGHT, padx=(8, 0))

        meta_row = Frame(card)
        meta_row.pack(fill=X, pady=(5, 0))

        modified_time = item.get("modifiedTime", "")
        Label(meta_row, text=f"Modified: {modified_time}", anchor="w", font=("Segoe UI", 9)).pack(
            side=LEFT,
            fill=X,
            expand=True,
        )

        Button(meta_row, text="Open", command=lambda current_id=file_id: self._open_drive_file_link(current_id)).pack(
            side=RIGHT,
            padx=(8, 0),
        )
        Button(
            meta_row,
            text="Copy link",
            command=lambda current_id=file_id: self._copy_drive_file_link(current_id),
        ).pack(side=RIGHT)
        Button(
            meta_row,
            text="Set sharing",
            command=lambda current_id=file_id: self._set_drive_file_sharing(current_id),
        ).pack(side=RIGHT)
        Button(
            meta_row,
            text="Delete",
            command=lambda current_id=file_id: self._delete_drive_file(current_id),
        ).pack(side=RIGHT, padx=(0, 8))
        self._apply_theme(card)

    def _copy_drive_link_worker(self, item: dict[str, str]) -> None:
        try:
            service = get_drive_service()
            shared_file = ensure_anyone_reader_permission(service, item["id"])
            shared_file["name"] = item.get("name", "")
            shared_file["modifiedTime"] = item.get("modifiedTime", "")
            shared_file["sharingStatus"] = "Anyone with link can read"
            self.drive_files_queue.put(("copy_success", [shared_file]))
        except Exception as exc:  # noqa: BLE001 - surface Drive errors in the UI.
            self.drive_files_queue.put(("copy_error", str(exc)))

    def _set_drive_sharing_worker(self, item: dict[str, str]) -> None:
        try:
            service = get_drive_service()
            new_status, shared_file = cycle_sharing_permission(service, item["id"])
            shared_file["name"] = item.get("name", "")
            shared_file["modifiedTime"] = item.get("modifiedTime", "")
            shared_file["sharingStatus"] = new_status
            self.drive_files_queue.put(("perm_success", [shared_file]))
        except Exception as exc:  # noqa: BLE001 - surface Drive errors in the UI.
            self.drive_files_queue.put(("perm_error", str(exc)))

    def _delete_drive_file_worker(self, item: dict[str, str]) -> None:
        try:
            service = get_drive_service()
            trash_drive_file(service, item["id"])
            self.drive_files_queue.put(("delete_success", {"id": item["id"], "name": item.get("name", "File")}))
        except Exception as exc:  # noqa: BLE001 - surface Drive errors in the UI.
            self.drive_files_queue.put(("delete_error", str(exc)))

    def _remove_drive_file_card(self, file_id: str) -> None:
        card = self.drive_cards_by_id.pop(file_id, None)
        self.drive_files_by_id.pop(file_id, None)
        if card:
            card.destroy()
        if not self.drive_files_by_id:
            self._show_drive_message("No files found in this Drive folder.")

    def _normalize_drive_link(self, link: str) -> str:
        if not self.settings.get("omit_drivesdk_query", False):
            return link
        try:
            parsed = urlparse(link)
            if not parsed.query:
                return link
            query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
            filtered = [(k, v) for k, v in query_pairs if not (k == "usp" and v == "drivesdk")]
            if len(filtered) == len(query_pairs):
                return link
            new_query = urlencode(filtered, doseq=True)
            return parsed._replace(query=new_query).geturl()
        except Exception:
            return link

    def _copy_to_clipboard(self, link: str) -> None:
        link = self._normalize_drive_link(link)
        self.root.clipboard_clear()
        self.root.clipboard_append(link)
        self.root.update_idletasks()

    def _open_app_folder(self) -> None:
        webbrowser.open(APP_DIR.as_uri())

    def _open_selected_drive_folder(self) -> None:
        folder_name = self.drive_folder_name.get().strip() or "GDriveLink"
        folder_path = find_local_google_drive_folder(folder_name)
        if folder_path is None:
            self.status.set(f"Could not find a synced Google Drive folder named '{folder_name}' in Explorer.")
            messagebox.showerror(
                APP_TITLE,
                "Could not find that folder in your local Google Drive sync location.\n\n"
                f"Folder: {folder_name}",
            )
            return
        if hasattr(os, "startfile"):
            os.startfile(folder_path)
        else:
            webbrowser.open(folder_path.as_uri())
        self.status.set(f"Opened Drive folder in Explorer: {folder_path}")

    def run(self) -> None:
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.mainloop()


def get_drive_service():
    credentials: Credentials | None = None

    if TOKEN_FILE.exists():
        try:
            with TOKEN_FILE.open("rb") as token:
                credentials = pickle.load(token)
        except Exception:
            credentials = None
            try:
                TOKEN_FILE.unlink(missing_ok=True)
            except OSError:
                pass

    if credentials and credentials.expired and credentials.refresh_token:
        try:
            credentials.refresh(Request())
        except RefreshError:
            credentials = None
            try:
                TOKEN_FILE.unlink(missing_ok=True)
            except OSError:
                pass

    if not credentials or not credentials.valid:
        if not CLIENT_SECRET_FILE.exists():
            raise FileNotFoundError(
                f"Missing {CLIENT_SECRET_FILE.name}. Download an OAuth desktop client JSON from Google Cloud "
                f"Console and save it beside this script as {CLIENT_SECRET_FILE.name}."
            )
        flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
        credentials = flow.run_local_server(port=0)  # type: ignore[assignment]

    with TOKEN_FILE.open("wb") as token:
        pickle.dump(credentials, token)

    return build("drive", "v3", credentials=credentials)


def find_local_google_drive_folder(folder_name: str) -> Path | None:
    requested_path = Path(folder_name).expanduser()
    if requested_path.is_absolute() and requested_path.exists():
        return requested_path

    candidates = [
        Path.home() / "Google Drive",
        Path.home() / "Google Drive" / "My Drive",
        Path.home() / "Google Drive" / "Oma Drive",
        Path.home() / "My Drive",
        Path.home() / "Oma Drive",
    ]
    if sys.platform == "win32":
        candidates.extend(Path(f"{letter}:") / "My Drive" for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ")
        candidates.extend(Path(f"{letter}:") / "Oma Drive" for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ")
        candidates.extend(Path(f"{letter}:") / "Shared drives" for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ")

    relative_folder = Path(folder_name)
    for root in candidates:
        candidate = root / relative_folder
        if candidate.exists():
            return candidate

    if sys.platform == "win32":
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            drive_root = Path(f"{letter}:\\")
            if not drive_root.exists():
                continue
            direct_candidate = drive_root / relative_folder
            if direct_candidate.exists():
                return direct_candidate
            try:
                children = [child for child in drive_root.iterdir() if child.is_dir()]
            except OSError:
                continue
            for child in children:
                candidate = child / relative_folder
                if candidate.exists():
                    return candidate
    return None


def get_or_create_folder(service, folder_name: str) -> str:  # type: ignore[no-untyped-def]
    escaped_name = _escape_for_drive_query(folder_name)
    query = (
        f"name = '{escaped_name}' and "
        "mimeType = 'application/vnd.google-apps.folder' and "
        "trashed = false"
    )
    existing_folders = (
        service.files()
        .list(q=query, spaces="drive", fields="files(id, name)", pageSize=1)
        .execute()
        .get("files", [])
    )
    if existing_folders:
        return existing_folders[0]["id"]

    folder_metadata = {
        "name": folder_name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    created_folder = service.files().create(body=folder_metadata, fields="id").execute()
    return created_folder["id"]


def list_drive_folder_files(service, folder_id: str) -> list[dict[str, str]]:  # type: ignore[no-untyped-def]
    query = f"'{folder_id}' in parents and trashed = false"
    files: list[dict[str, str]] = []
    request = service.files().list(
        q=query,
        spaces="drive",
        fields="nextPageToken, files(id, name, modifiedTime, webViewLink, parents)",
        orderBy="modifiedTime desc",
        pageSize=100,
    )
    while request is not None:
        response = request.execute()
        for item in response.get("files", []):
            item["sharingStatus"] = get_sharing_status(service, item["id"])
            files.append(item)
        request = service.files().list_next(request, response)
    return files


def get_sharing_status(service, file_id: str) -> str:  # type: ignore[no-untyped-def]
    permissions = (
        service.permissions()
        .list(fileId=file_id, fields="permissions(id, type, role, allowFileDiscovery)")
        .execute()
        .get("permissions", [])
    )
    for permission in permissions:
        if permission.get("type") == "anyone" and permission.get("role") == "reader":
            if permission.get("allowFileDiscovery"):
                return "Public on web can read"
            return "Anyone with link can read"
    return "Restricted"


def ensure_anyone_reader_permission(service, file_id: str) -> dict[str, str]:  # type: ignore[no-untyped-def]
    permissions = (
        service.permissions()
        .list(fileId=file_id, fields="permissions(id, type, role, allowFileDiscovery)")
        .execute()
        .get("permissions", [])
    )
    for permission in permissions:
        if permission.get("type") == "anyone":
            if permission.get("role") == "reader" and not permission.get("allowFileDiscovery"):
                break
            service.permissions().update(
                fileId=file_id,
                permissionId=permission["id"],
                body={"type": "anyone", "role": "reader", "allowFileDiscovery": False},
                fields="id",
            ).execute()
            break
    else:
        service.permissions().create(
            fileId=file_id,
            body={"type": "anyone", "role": "reader", "allowFileDiscovery": False},
            fields="id",
        ).execute()

    return service.files().get(fileId=file_id, fields="id, webViewLink").execute()


def _remove_anyone_permissions(service, file_id: str) -> None:  # type: ignore[no-untyped-def]
    permissions = (
        service.permissions()
        .list(fileId=file_id, fields="permissions(id, type)")
        .execute()
        .get("permissions", [])
    )
    for permission in permissions:
        if permission.get("type") == "anyone":
            try:
                service.permissions().delete(fileId=file_id, permissionId=permission["id"]).execute()
            except Exception:
                pass


def cycle_sharing_permission(service, file_id: str) -> tuple[str, dict[str, str]]:  # type: ignore[no-untyped-def]
    current = get_sharing_status(service, file_id)
    if current == "Restricted":
        file_info = ensure_anyone_reader_permission(service, file_id)
        return "Anyone with link can read", file_info
    if current == "Anyone with link can read":
        _remove_anyone_permissions(service, file_id)
        service.permissions().create(
            fileId=file_id,
            body={"type": "anyone", "role": "reader", "allowFileDiscovery": True},
            fields="id",
        ).execute()
        file_info = service.files().get(fileId=file_id, fields="id, webViewLink").execute()
        return "Public on web can read", file_info
    _remove_anyone_permissions(service, file_id)
    file_info = service.files().get(fileId=file_id, fields="id, webViewLink").execute()
    return "Restricted", file_info


def trash_drive_file(service, file_id: str) -> None:  # type: ignore[no-untyped-def]
    service.files().update(fileId=file_id, body={"trashed": True}, fields="id, trashed").execute()


def _escape_for_drive_query(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def find_existing_file_in_folder(service, folder_id: str, filename: str) -> str | None:  # type: ignore[no-untyped-def]
    escaped_name = _escape_for_drive_query(filename)
    query = f"name = '{escaped_name}' and '{folder_id}' in parents and trashed = false"
    existing = (
        service.files()
        .list(q=query, spaces="drive", fields="files(id)", pageSize=1)
        .execute()
        .get("files", [])
    )
    return existing[0]["id"] if existing else None


def get_unique_filename(service, folder_id: str, filename: str) -> str:  # type: ignore[no-untyped-def]
    if find_existing_file_in_folder(service, folder_id, filename) is None:
        return filename
    if '.' in filename:
        stem, suffix = filename.rsplit('.', 1)
        suffix = '.' + suffix
    else:
        stem, suffix = filename, ''
    match = re.search(r' \((\d+)\)$', stem)
    if match:
        base = stem[: match.start()]
        start = int(match.group(1)) + 1
    else:
        base = stem
        start = 1
    for i in range(start, start + 1000):
        candidate = f"{base} ({i}){suffix}"
        if find_existing_file_in_folder(service, folder_id, candidate) is None:
            return candidate
    return f"{base} (copy){suffix}"


def overwrite_file_content(service, file_path: Path, file_id: str) -> dict[str, str]:  # type: ignore[no-untyped-def]
    media = MediaFileUpload(str(file_path), resumable=True)
    service.files().update(fileId=file_id, media_body=media, fields="id, webViewLink").execute()
    try:
        service.permissions().create(
            fileId=file_id,
            body={"type": "anyone", "role": "reader", "allowFileDiscovery": False},
            fields="id",
        ).execute()
    except Exception:
        pass
    shared_file = service.files().get(fileId=file_id, fields="webViewLink").execute()
    return {
        "id": file_id,
        "name": file_path.name,
        "webViewLink": shared_file["webViewLink"],
    }


def upload_and_share(service, file_path: Path, folder_id: str, filename: str | None = None) -> dict[str, str]:  # type: ignore[no-untyped-def]
    media = MediaFileUpload(str(file_path), resumable=True)
    use_name = filename or file_path.name
    file_metadata = {"name": use_name, "parents": [folder_id]}
    uploaded_file = (
        service.files()
        .create(body=file_metadata, media_body=media, fields="id, webViewLink")
        .execute()
    )

    service.permissions().create(
        fileId=uploaded_file["id"],
        body={"type": "anyone", "role": "reader", "allowFileDiscovery": False},
        fields="id",
    ).execute()

    shared_file = service.files().get(fileId=uploaded_file["id"], fields="webViewLink").execute()
    return {
        "id": uploaded_file["id"],
        "name": use_name,
        "webViewLink": shared_file["webViewLink"],
    }


def main() -> None:
    global SINGLE_INSTANCE_LOCK

    SINGLE_INSTANCE_LOCK = acquire_single_instance_lock()
    if SINGLE_INSTANCE_LOCK is None:
        return
    DriveUploaderApp().run()


if __name__ == "__main__":
    main()