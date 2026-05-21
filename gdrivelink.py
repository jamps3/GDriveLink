from __future__ import annotations

import json
import pickle
import queue
import sys
import tempfile
import threading
import urllib.request
import webbrowser
from urllib.parse import urlparse
from datetime import datetime
from pathlib import Path
from tkinter import BOTH, BOTTOM, END, LEFT, RIGHT, X, Y, Button, Canvas, Entry, Frame, Label, Listbox, Radiobutton, Scrollbar, StringVar, Toplevel, filedialog, messagebox
from tkinter.ttk import Notebook, Progressbar, Style

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
APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))
CLIENT_SECRET_FILE = APP_DIR / "credentials.json"
TOKEN_FILE = APP_DIR / "token.pickle"
HISTORY_FILE = APP_DIR / "upload_history.json"
SETTINGS_FILE = APP_DIR / "settings.json"
ICON_FILE = RESOURCE_DIR / "gdrivelink.ico"
SCOPES = ["https://www.googleapis.com/auth/drive.file"]
THEME_OPTIONS = ("system", "light", "dark")
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
    return [item for item in data if isinstance(item, dict)]


def save_history(history: list[dict[str, str]]) -> None:
    with HISTORY_FILE.open("w", encoding="utf-8") as history_file:
        json.dump(history, history_file, indent=2)
        history_file.write("\n")


def load_settings() -> dict[str, str]:
    if not SETTINGS_FILE.exists():
        return {}
    try:
        with SETTINGS_FILE.open("r", encoding="utf-8") as settings_file:
            data = json.load(settings_file)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    theme = data.get("theme", "system")
    if theme not in THEME_OPTIONS:
        theme = "system"
    return {"theme": theme}


def save_settings(settings: dict[str, str]) -> None:
    with SETTINGS_FILE.open("w", encoding="utf-8") as settings_file:
        json.dump(settings, settings_file, indent=2)
        settings_file.write("\n")


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
        if ICON_FILE.exists():
            self.root.iconbitmap(ICON_FILE)
        self.root.geometry("760x520")
        self.root.minsize(640, 640)

        self.status = StringVar(value="Drop files here, or choose files.")
        self.drive_folder_name = StringVar(value="GDriveLink")
        self.settings = load_settings()
        self.theme_choice = StringVar(value=self.settings.get("theme", "system"))
        self.theme = DARK_THEME if self._effective_theme_name() == "dark" else LIGHT_THEME
        self.style = Style(self.root)
        self.result_queue: queue.Queue[tuple[str, str, dict[str, str] | str | None, int]] = queue.Queue()
        self.drive_files_queue: queue.Queue[tuple[str, list[dict[str, str]] | str]] = queue.Queue()
        self.pending_uploads = 0
        self.preview_photo = None
        self.history = load_history()
        self.history_cards: list[Frame] = []
        self.drive_files_by_id: dict[str, dict[str, str]] = {}
        self.drive_cards_by_id: dict[str, Frame] = {}
        self.tray_icon = None

        self._configure_ttk_theme()
        self._build_ui()
        self._apply_theme()
        self._load_history_cards()
        self.root.bind_all("<Control-v>", self._handle_clipboard_paste)
        self.root.bind("<Unmap>", self._handle_window_unmap)
        self._setup_tray()
        self.root.after(100, self._poll_results)
        self.root.after(100, self._poll_drive_files)

    def _build_ui(self) -> None:
        container = Frame(self.root, padx=18, pady=18)
        container.pack(fill=BOTH, expand=True)

        header = Frame(container)
        header.pack(fill=X)
        header.configure(height=52)
        header.pack_propagate(False)

        title = Label(header, text=APP_TITLE, font=("Segoe UI", 18, "bold"), anchor="w")
        title.pack(side=LEFT, fill=X, expand=True)

        self.refresh_drive_button = Button(
            header,
            text="Refresh folder files",
            command=self._refresh_drive_files,
            font=("Segoe UI", 12, "bold"),
            padx=22,
            pady=10,
        )
        self.refresh_drive_button.pack(side=RIGHT)

        self.tabs = Notebook(container)
        self.tabs.pack(fill=BOTH, expand=True, pady=(12, 0))

        main_tab = Frame(self.tabs)
        history_tab = Frame(self.tabs)
        drive_tab = Frame(self.tabs)
        settings_tab = Frame(self.tabs)
        self.tabs.add(main_tab, text="Main")
        self.tabs.add(history_tab, text="Upload History")
        self.tabs.add(drive_tab, text="Drive Folder")
        self.tabs.add(settings_tab, text="Settings")

        hint = Label(
            main_tab,
            text="Files are uploaded to your Google Drive, shared as anyone with the link can read, and listed below.",
            font=("Segoe UI", 10),
            anchor="w",
            justify=LEFT,
        )
        hint.pack(fill="x", pady=(12, 16))

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
        self.drop_area.drop_target_register(DND_FILES)
        self.drop_area.dnd_bind("<<Drop>>", self._handle_drop)

        folder_frame = Frame(main_tab)
        folder_frame.pack(fill="x", pady=(12, 0))

        Label(folder_frame, text="Drive folder", anchor="w", font=("Segoe UI", 10)).pack(side=LEFT)
        Entry(folder_frame, textvariable=self.drive_folder_name).pack(side=LEFT, fill="x", expand=True, padx=(8, 0))

        controls = Frame(main_tab)
        controls.pack(fill="x", pady=12)

        Button(
            controls,
            text="Choose files",
            command=self._choose_files,
            font=("Segoe UI", 12, "bold"),
            padx=22,
            pady=10,
        ).pack(expand=True)

        self.progress = Progressbar(main_tab, mode="indeterminate")
        self.progress.pack(fill="x", pady=(0, 8))

        Label(main_tab, textvariable=self.status, anchor="w", font=("Segoe UI", 10)).pack(fill="x", pady=(0, 8))

        self.history_cards_canvas = Canvas(history_tab, highlightthickness=0)
        self.history_cards_scrollbar = Scrollbar(history_tab, orient="vertical", command=self.history_cards_canvas.yview)
        self.history_cards_frame = Frame(self.history_cards_canvas)
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

        self.drive_cards_canvas = Canvas(drive_tab, highlightthickness=0)
        self.drive_cards_scrollbar = Scrollbar(drive_tab, orient="vertical", command=self.drive_cards_canvas.yview)
        self.drive_cards_frame = Frame(self.drive_cards_canvas)
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
        self._build_settings_tab(settings_tab)

    def _build_settings_tab(self, settings_tab: Frame) -> None:
        theme_frame = Frame(settings_tab, padx=10, pady=12)
        theme_frame.pack(fill=X)
        Label(theme_frame, text="Theme", anchor="w", font=("Segoe UI", 12, "bold")).pack(fill=X)
        for value, label in (("system", "System default"), ("light", "Light"), ("dark", "Dark")):
            Radiobutton(
                theme_frame,
                text=label,
                value=value,
                variable=self.theme_choice,
                command=self._handle_theme_changed,
                font=("Segoe UI", 10),
                anchor="w",
            ).pack(fill=X, pady=(8, 0))

        data_frame = Frame(settings_tab, padx=10, pady=12)
        data_frame.pack(fill=X)
        Label(data_frame, text="App folder", anchor="w", font=("Segoe UI", 12, "bold")).pack(fill=X)
        Button(
            data_frame,
            text="Open token folder",
            command=self._open_app_folder,
            font=("Segoe UI", 10),
        ).pack(anchor="w", pady=(8, 0))

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
            "Horizontal.TProgressbar",
            background=colors["accent"],
            troughcolor=colors["surface_alt"],
            bordercolor=colors["border"],
            lightcolor=colors["accent"],
            darkcolor=colors["accent"],
        )

    def _apply_theme(self, root_widget=None) -> None:  # type: ignore[no-untyped-def]
        colors = self.theme
        widget = root_widget or self.root
        self._style_widget_tree(widget)
        set_windows_dark_title_bar(widget, self._effective_theme_name() == "dark")
        for child in widget.winfo_children():
            if isinstance(child, Toplevel):
                set_windows_dark_title_bar(child, self._effective_theme_name() == "dark")
        self.root.option_add("*selectBackground", colors["select"])
        self.root.option_add("*selectForeground", colors["select_text"])

    def _style_widget_tree(self, widget) -> None:  # type: ignore[no-untyped-def]
        colors = self.theme
        widget_class = widget.winfo_class()
        try:
            if widget_class in {"Tk", "Toplevel", "Frame", "Labelframe"}:
                widget.configure(background=colors["window"])
            elif isinstance(widget, Canvas):
                widget.configure(background=colors["window"])
            elif isinstance(widget, Label):
                background = colors["drop"] if widget is getattr(self, "drop_area", None) else colors["window"]
                widget.configure(background=background, foreground=colors["text"])
            elif isinstance(widget, Button):
                widget.configure(
                    background=colors["button"],
                    foreground=colors["text"],
                    activebackground=colors["button_active"],
                    activeforeground=colors["text"],
                    highlightbackground=colors["window"],
                    highlightcolor=colors["accent"],
                    relief="raised",
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
            elif isinstance(widget, Scrollbar):
                widget.configure(
                    background=colors["button"],
                    activebackground=colors["button_active"],
                    troughcolor=colors["surface_alt"],
                    highlightbackground=colors["window"],
                )
        except Exception:
            pass

        for child in widget.winfo_children():
            self._style_widget_tree(child)

    def _run_on_ui_thread(self, callback) -> None:  # type: ignore[no-untyped-def]
        try:
            self.root.after(0, callback)
        except RuntimeError:
            pass

    def _show_window_from_tray(self, icon=None, item=None) -> None:  # type: ignore[no-untyped-def]
        self._run_on_ui_thread(self._show_window)

    def _paste_link_from_tray(self, icon=None, item=None) -> None:  # type: ignore[no-untyped-def]
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

    def _toggle_window(self, icon=None, item=None) -> None:  # type: ignore[no-untyped-def]
        self._run_on_ui_thread(self._toggle_window_on_ui)

    def _toggle_window_on_ui(self) -> None:
        if self.root.state() == 'withdrawn':
            self._show_window()
        else:
            self._hide_to_tray()

    def _handle_window_unmap(self, _event=None) -> None:  # type: ignore[no-untyped-def]
        if self.root.state() == "iconic":
            self.root.after_idle(self._hide_to_tray)

    def _hide_to_tray(self) -> None:
        self.root.withdraw()
        if not self.tray_icon:
            self._setup_tray()

    def _quit_app(self, icon, item) -> None:
        self._run_on_ui_thread(self._on_close)

    def _on_close(self) -> None:
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

    def _add_history_card(self, item: dict[str, str]) -> None:
        if len(self.history_cards) == 0 and self.history_cards_frame.winfo_children():
            for child in list(self.history_cards_frame.winfo_children()):
                child.destroy()
        card = Frame(self.history_cards_frame, relief="ridge", borderwidth=1, padx=10, pady=8)
        card.pack(fill=X, pady=(0, 8))
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
            command=lambda current_item=item, current_card=card: self._remove_history_item(current_item, current_card),
        ).pack(side=RIGHT, padx=(0, 8))
        self._apply_theme(card)

    def _open_history_link(self, item: dict[str, str]) -> None:
        link = item.get("webViewLink")
        if link:
            webbrowser.open(link)

    def _copy_history_link(self, item: dict[str, str]) -> None:
        link = item.get("webViewLink", "")
        if link:
            self._copy_to_clipboard(link)
            self.status.set("Link copied to the clipboard.")

    def _remove_history_item(self, item: dict[str, str], card: Frame) -> None:
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

    def _choose_files(self) -> None:
        filenames = filedialog.askopenfilenames(title="Choose files to upload")
        if filenames:
            self._upload_files([Path(filename) for filename in filenames])

    def _handle_drop(self, event) -> None:  # type: ignore[no-untyped-def]
        files = [Path(file) for file in self.root.tk.splitlist(event.data)]
        self._upload_files(files)

    def _handle_clipboard_paste(self, _event=None) -> str:  # type: ignore[no-untyped-def]
        try:
            image = ImageGrab.grabclipboard()
        except Exception as exc:  # noqa: BLE001 - show clipboard errors in the UI.
            messagebox.showerror(APP_TITLE, f"Could not read an image from the clipboard:\n{exc}")
            return "break"

        if image is None:
            self.status.set("Clipboard does not contain an image.")
            return "break"

        if isinstance(image, list):
            image_paths = [Path(path) for path in image]
            self._upload_files(image_paths)
            return "break"

        self._show_clipboard_preview(image)
        return "break"

    def _show_clipboard_preview(self, image) -> None:  # type: ignore[no-untyped-def]
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
        Entry(filename_frame, textvariable=filename).pack(side=LEFT, fill=X, expand=True, padx=(8, 0))

        buttons = Frame(preview_window)
        buttons.pack(fill=X, padx=14, pady=(0, 14))

        Button(buttons, text="Cancel", command=preview_window.destroy).pack(side=RIGHT)
        Button(
            buttons,
            text="OK",
            command=lambda: self._confirm_clipboard_upload(preview_window, image, filename.get()),
        ).pack(side=RIGHT, padx=(0, 8))
        self._apply_theme(preview_window)

    def _confirm_clipboard_upload(self, preview_window: Toplevel, image, filename: str) -> None:  # type: ignore[no-untyped-def]
        preview_window.destroy()
        clean_filename = self._clean_clipboard_filename(filename)
        temp_path = Path(tempfile.gettempdir()) / clean_filename
        image.save(temp_path, "PNG")
        self._upload_files([temp_path], cleanup_after_upload=True)

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
                self.history.append(detail)
                save_history(self.history)
                self._add_history_card(detail)
                link = detail.get("webViewLink", "")
                self._copy_to_clipboard(link)
            else:
                self.status.set(f"{name}  ->  ERROR: {detail}")

        if got_result and self.pending_uploads == 0:
            self.progress.stop()
            self.status.set("Done. The latest uploaded link was copied to the clipboard.")

        current_state = self.root.state()
        if current_state == 'withdrawn':
            if not self.tray_icon:
                self._setup_tray()
        elif current_state == 'normal' and self.tray_icon:
            self.tray_icon.stop()
            self.tray_icon = None

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
                webbrowser.open(link)

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

    def _copy_to_clipboard(self, link: str) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(link)
        self.root.update_idletasks()

    def _open_app_folder(self) -> None:
        webbrowser.open(APP_DIR.as_uri())

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
        credentials = flow.run_local_server(port=0)

    with TOKEN_FILE.open("wb") as token:
        pickle.dump(credentials, token)

    return build("drive", "v3", credentials=credentials)


def get_or_create_folder(service, folder_name: str) -> str:  # type: ignore[no-untyped-def]
    escaped_name = folder_name.replace("\\", "\\\\").replace("'", "\\'")
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
        fields="nextPageToken, files(id, name, modifiedTime, webViewLink)",
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


def upload_and_share(service, file_path: Path, folder_id: str) -> dict[str, str]:  # type: ignore[no-untyped-def]
    media = MediaFileUpload(str(file_path), resumable=True)
    file_metadata = {"name": file_path.name, "parents": [folder_id]}
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
        "name": file_path.name,
        "webViewLink": shared_file["webViewLink"],
    }


def main() -> None:
    DriveUploaderApp().run()


if __name__ == "__main__":
    main()
