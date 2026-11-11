#!/usr/bin/env python3
"""
Prompt Clipboard — a small phrase clipboard for macOS.

Click a phrase to copy it. Phrases live outside the app bundle, so the .app is
read-only and can be dropped straight into /Applications.

Design notes (each one is a v1 bug that made the app unusable):
  * Normal window, NOT overrideredirect  -> macOS actually composites it.
  * No LSUIElement                       -> real Dock icon, Cmd-Q, Cmd-Tab.
  * Menu bar with Quit                   -> always a way out, even if the
                                            window ends up somewhere odd.
  * Saved geometry is clamped on-screen  -> can never restore off-display.
  * Data in Application Support          -> survives rebuilds; bundle stays
                                            read-only.
  * No hardcoded paths anywhere          -> move the app wherever you like.

Headless entry points (no GUI, so they work over SSH and in scripts):
  --selftest   build the whole UI off-screen and verify it, then exit
  --doctor     print environment diagnostics
  --list       print stored phrases
  --copy LABEL copy a phrase to the clipboard from the command line
  --add LABEL TEXT   add a phrase
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import tkinter as tk
from tkinter import messagebox

APP_ID = "PromptClipboard"
DISPLAY_NAME = "Prompt Clipboard"

# Folder names this app has shipped under, newest first. First run copies
# phrases from the first one that has any, so a rename never strands data.
LEGACY_APP_IDS = ("ClipboardWidget2", "ClipboardWidget")

# The old variable still works, so existing shells and scripts keep resolving.
HOME_ENV_VARS = ("PROMPT_CLIPBOARD_HOME", "CLIPBOARD_WIDGET_HOME")

HERE = os.path.dirname(os.path.abspath(__file__))
MAX_LABEL_LEN = 28

# ---- colors -----------------------------------------------------------------
BG = "#1e1f24"
BAR_BG = "#2a2b31"
BTN_BG = "#33343c"
BTN_HOVER = "#3f7bd6"
FG = "#e8e8ea"
MUTED = "#8a8a93"
ACCENT = "#3f7bd6"
OK = "#4caf50"


# ---- paths ------------------------------------------------------------------
def support_dir(app_id: str) -> str:
    """~/Library/Application Support/<app_id>, without creating it."""
    return os.path.join(
        os.path.expanduser("~"), "Library", "Application Support", app_id
    )


def data_dir() -> str:
    """Where phrases and window state live.

    Override with PROMPT_CLIPBOARD_HOME, or the older CLIPBOARD_WIDGET_HOME,
    which is still honoured.
    """
    override = next(
        (os.environ[name] for name in HOME_ENV_VARS if os.environ.get(name)), None
    )
    base = override or support_dir(APP_ID)
    os.makedirs(base, exist_ok=True)
    return base


def phrases_path() -> str:
    return os.path.join(data_dir(), "phrases.json")


def state_path() -> str:
    return os.path.join(data_dir(), "state.json")


# ---- persistence ------------------------------------------------------------
def _read_json(path, fallback):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return fallback


def _write_json(path, payload) -> bool:
    """Write atomically so a crash mid-save can't truncate the file."""
    folder = os.path.dirname(path)
    try:
        fd, tmp = tempfile.mkstemp(dir=folder, prefix=".tmp-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            os.replace(tmp, path)
            return True
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except OSError:
        return False


def _clean(raw) -> list:
    out = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, dict):
            continue
        text = item.get("text") or ""
        if not text:
            continue
        out.append({"label": item.get("label") or text, "text": text})
    return out


def seed_if_empty() -> str | None:
    """First run: adopt phrases from an older install, else the bundled seed.

    This only ever copies. The old folder is left exactly as it was, so a
    rename can't lose anyone's phrases and an older build still finds its data.
    """
    target = phrases_path()
    if os.path.exists(target):
        return None

    # Real phrases from a previous name beat the starter set in the bundle.
    folders = [support_dir(old) for old in LEGACY_APP_IDS]
    folders.append(os.path.join(os.path.dirname(HERE), "clipboard_widget"))
    folders.append(HERE)                      # phrases.seed.json in the .app

    for folder in folders:
        for name in ("phrases.json", "phrases.seed.json"):
            data = _clean(_read_json(os.path.join(folder, name), None))
            if not data:
                continue
            _write_json(target, data)
            # Carry window size, position and always-on-top over too, so an
            # upgrade doesn't silently reset where the window opens.
            old_state = _read_json(os.path.join(folder, "state.json"), None)
            if isinstance(old_state, dict) and not os.path.exists(state_path()):
                _write_json(state_path(), old_state)
            return os.path.join(folder, name)
    return None


def load_phrases() -> list:
    return _clean(_read_json(phrases_path(), []))


def save_phrases(phrases) -> bool:
    return _write_json(phrases_path(), phrases)


def load_state() -> dict:
    state = _read_json(state_path(), {})
    return state if isinstance(state, dict) else {}


def save_state(state) -> bool:
    return _write_json(state_path(), state)


# ---- clipboard --------------------------------------------------------------
def copy_to_clipboard(text: str, root: "tk.Misc | None" = None) -> bool:
    ok = False
    try:
        subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)
        ok = True
    except (OSError, subprocess.CalledProcessError):
        pass
    if root is not None:
        try:
            root.clipboard_clear()
            root.clipboard_append(text)
            root.update_idletasks()
            ok = True
        except tk.TclError:
            pass
    return ok


# ---- edit dialog ------------------------------------------------------------
class PhraseDialog(tk.Toplevel):
    """Label + multi-line text. Returns None on cancel."""

    def __init__(self, parent, title, label="", text=""):
        super().__init__(parent)
        self.result = None
        self.title(title)
        self.configure(bg=BG)
        self.resizable(True, True)
        self.transient(parent)

        tk.Label(self, text="Label", bg=BG, fg=MUTED,
                 font=("SF Pro Text", 11)).pack(anchor="w", padx=12, pady=(12, 2))
        self.label_var = tk.StringVar(value=label)
        entry = tk.Entry(self, textvariable=self.label_var, bg=BTN_BG, fg=FG,
                         insertbackground=FG, relief="flat",
                         font=("SF Pro Text", 12))
        entry.pack(fill="x", padx=12, ipady=4)

        tk.Label(self, text="Text to copy", bg=BG, fg=MUTED,
                 font=("SF Pro Text", 11)).pack(anchor="w", padx=12, pady=(12, 2))
        self.text_box = tk.Text(self, height=6, width=44, bg=BTN_BG, fg=FG,
                                insertbackground=FG, relief="flat", wrap="word",
                                font=("SF Pro Text", 12))
        self.text_box.pack(fill="both", expand=True, padx=12)
        self.text_box.insert("1.0", text)

        row = tk.Frame(self, bg=BG)
        row.pack(fill="x", padx=12, pady=12)
        tk.Button(row, text="Cancel", command=self._cancel).pack(side="right")
        tk.Button(row, text="Save", default="active",
                  command=self._save).pack(side="right", padx=(0, 8))

        self.bind("<Escape>", lambda e: self._cancel())
        self.bind("<Command-Return>", lambda e: self._save())
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        entry.focus_set()

    def _save(self):
        text = self.text_box.get("1.0", "end-1c").strip()
        if not text:
            messagebox.showwarning(DISPLAY_NAME, "Text cannot be empty.", parent=self)
            return
        self.result = {"label": self.label_var.get().strip() or text, "text": text}
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()


# ---- settings ---------------------------------------------------------------
class PreferencesDialog(tk.Toplevel):
    """Settings window. One home for options, so later ones have somewhere
    to land instead of accumulating in the menu bar."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.title("Settings")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.transient(parent)

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=16, pady=(14, 10))

        tk.Label(body, text="Window", bg=BG, fg=MUTED,
                 font=("SF Pro Text", 11)).pack(anchor="w")
        # Deliberately the same variable the View menu uses, so the checkbox
        # and the menu item cannot drift out of sync.
        tk.Checkbutton(
            body, text="Keep window on top of other apps",
            variable=app.on_top_var, command=app.toggle_on_top,
            bg=BG, fg=FG, activebackground=BG, activeforeground=FG,
            selectcolor=BTN_BG, highlightthickness=0, bd=0,
            font=("SF Pro Text", 12),
        ).pack(anchor="w", pady=(6, 0))
        tk.Label(body, text="Remembered between launches.", bg=BG, fg=MUTED,
                 font=("SF Pro Text", 10)).pack(anchor="w", padx=(22, 0))

        tk.Frame(body, bg=BAR_BG, height=1).pack(fill="x", pady=14)

        tk.Label(body, text="Your phrases", bg=BG, fg=MUTED,
                 font=("SF Pro Text", 11)).pack(anchor="w")
        tk.Label(body, text=data_dir(), bg=BG, fg=FG, justify="left",
                 wraplength=300, font=("SF Pro Text", 10)).pack(anchor="w",
                                                                pady=(4, 8))
        tk.Button(body, text="Reveal in Finder",
                  command=app.reveal_data).pack(anchor="w")

        row = tk.Frame(self, bg=BG)
        row.pack(fill="x", padx=16, pady=(0, 14))
        tk.Button(row, text="Done", default="active",
                  command=self.destroy).pack(side="right")

        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Command-w>", lambda e: self.destroy())


# ---- scrollable list --------------------------------------------------------
class ScrollArea(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self.canvas = tk.Canvas(self, bg=BG, highlightthickness=0, bd=0)
        bar = tk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.inner = tk.Frame(self.canvas, bg=BG)
        self._window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self.canvas.bind(
            "<Configure>",
            lambda e: self.canvas.itemconfigure(self._window, width=e.width),
        )
        self.canvas.bind("<Enter>", lambda e: self._wheel(True))
        self.canvas.bind("<Leave>", lambda e: self._wheel(False))

    def _wheel(self, on):
        if on:
            self.canvas.bind_all("<MouseWheel>", self._scroll)
        else:
            self.canvas.unbind_all("<MouseWheel>")

    def _scroll(self, event):
        self.canvas.yview_scroll(-1 * int(event.delta), "units")


# ---- main window ------------------------------------------------------------
class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.phrases = load_phrases()
        self.filter_text = ""
        self.rows = []
        self.prefs = None

        state = load_state()
        self.on_top = bool(state.get("on_top", True))

        root.title(DISPLAY_NAME)
        root.configure(bg=BG)
        root.minsize(240, 200)
        self._restore_geometry(state.get("geometry"))
        root.attributes("-topmost", self.on_top)
        root.protocol("WM_DELETE_WINDOW", self.quit)

        self._build_menu()
        self._build_search()
        self.area = ScrollArea(root)
        self.area.pack(fill="both", expand=True, padx=8, pady=(0, 4))
        self.status = tk.Label(root, text="", bg=BAR_BG, fg=MUTED, anchor="w",
                               font=("SF Pro Text", 10))
        self.status.pack(fill="x", side="bottom", ipady=3)

        self.render()
        self._bind_shortcuts()

    # -- geometry ------------------------------------------------------------
    def _restore_geometry(self, geo):
        """Restore size/position, clamped so it can never land off-screen."""
        width, height, x, y = 300, 420, 120, 120
        if isinstance(geo, dict):
            width = int(geo.get("w", width))
            height = int(geo.get("h", height))
            x = int(geo.get("x", x))
            y = int(geo.get("y", y))
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        width = max(240, min(width, sw))
        height = max(200, min(height, sh))
        x = max(0, min(x, sw - 120))
        y = max(0, min(y, sh - 80))
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def _save_geometry(self):
        state = load_state()
        state["geometry"] = {
            "w": self.root.winfo_width(), "h": self.root.winfo_height(),
            "x": self.root.winfo_x(), "y": self.root.winfo_y(),
        }
        state["on_top"] = self.on_top
        save_state(state)

    # -- chrome --------------------------------------------------------------
    def _build_menu(self):
        menubar = tk.Menu(self.root)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="New Phrase", accelerator="Cmd+N",
                              command=self.add_phrase)
        file_menu.add_separator()
        file_menu.add_command(label="Settings…", accelerator="Cmd+,",
                              command=self.show_preferences)
        file_menu.add_command(label="Reveal Data Folder", command=self.reveal_data)
        file_menu.add_separator()
        file_menu.add_command(label="Quit", accelerator="Cmd+Q", command=self.quit)
        menubar.add_cascade(label="File", menu=file_menu)

        view_menu = tk.Menu(menubar, tearoff=0)
        self.on_top_var = tk.BooleanVar(value=self.on_top)
        view_menu.add_checkbutton(label="Always on Top", variable=self.on_top_var,
                                  command=self.toggle_on_top)
        menubar.add_cascade(label="View", menu=view_menu)

        self.root.config(menu=menubar)

        # Also puts Settings… in the application menu, where macOS users look
        # for it first. Only exists on Aqua Tk, hence the guard.
        try:
            self.root.createcommand("::tk::mac::ShowPreferences",
                                    self.show_preferences)
        except tk.TclError:
            pass

    def _build_search(self):
        bar = tk.Frame(self.root, bg=BAR_BG)
        bar.pack(fill="x")
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self.on_search())
        entry = tk.Entry(bar, textvariable=self.search_var, bg=BTN_BG, fg=FG,
                         insertbackground=FG, relief="flat",
                         font=("SF Pro Text", 12))
        entry.pack(side="left", fill="x", expand=True, padx=(8, 4), pady=6, ipady=3)
        self.search_entry = entry

        add = tk.Label(bar, text="＋", bg=BAR_BG, fg=ACCENT, cursor="hand2",
                       font=("SF Pro Text", 15, "bold"))
        add.pack(side="right", padx=8)
        add.bind("<Button-1>", lambda e: self.add_phrase())

    def _bind_shortcuts(self):
        self.root.bind("<Command-n>", lambda e: self.add_phrase())
        self.root.bind("<Command-q>", lambda e: self.quit())
        self.root.bind("<Command-f>", lambda e: self.search_entry.focus_set())
        self.root.bind("<Command-comma>", lambda e: self.show_preferences())
        self.root.bind("<Escape>", lambda e: self.clear_search())
        for n in range(1, 10):
            self.root.bind(f"<Command-Key-{n}>",
                           lambda e, i=n - 1: self.copy_visible(i))

    # -- rendering -----------------------------------------------------------
    def visible(self) -> list:
        if not self.filter_text:
            return list(enumerate(self.phrases))
        needle = self.filter_text.lower()
        return [(i, p) for i, p in enumerate(self.phrases)
                if needle in p["label"].lower() or needle in p["text"].lower()]

    def render(self):
        for child in self.area.inner.winfo_children():
            child.destroy()
        self.rows = []

        items = self.visible()
        if not items:
            msg = ("No phrases yet.\nClick ＋ to add one."
                   if not self.phrases else "No matches.")
            tk.Label(self.area.inner, text=msg, bg=BG, fg=MUTED,
                     font=("SF Pro Text", 11), justify="center").pack(pady=20)
            return

        for slot, (index, item) in enumerate(items):
            label = item["label"]
            if len(label) > MAX_LABEL_LEN:
                label = label[: MAX_LABEL_LEN - 1] + "…"
            hint = f"⌘{slot + 1}  " if slot < 9 else ""

            row = tk.Label(self.area.inner, text=f"{hint}{label}", anchor="w",
                           bg=BTN_BG, fg=FG, font=("SF Pro Text", 12),
                           padx=10, pady=7, cursor="hand2")
            row.pack(fill="x", pady=2)
            row.bind("<Button-1>", lambda e, i=index: self.copy(i))
            row.bind("<Enter>", lambda e, w=row: w.config(bg=BTN_HOVER, fg="white"))
            row.bind("<Leave>", lambda e, w=row: w.config(bg=BTN_BG, fg=FG))
            for seq in ("<Button-2>", "<Button-3>", "<Control-Button-1>"):
                row.bind(seq, lambda e, i=index: self.context_menu(e, i))
            self.rows.append(row)

    def flash(self, message):
        self.status.config(text=message, fg=OK)
        self.root.after(1400, lambda: self.status.config(text="", fg=MUTED))

    # -- actions -------------------------------------------------------------
    def on_search(self):
        self.filter_text = self.search_var.get().strip()
        self.render()

    def clear_search(self):
        self.search_var.set("")

    def copy(self, index):
        if not 0 <= index < len(self.phrases):
            return
        item = self.phrases[index]
        copy_to_clipboard(item["text"], self.root)
        self.flash(f"Copied “{item['label']}”")

    def copy_visible(self, slot):
        items = self.visible()
        if slot < len(items):
            self.copy(items[slot][0])

    def add_phrase(self):
        dialog = PhraseDialog(self.root, "New Phrase")
        self.root.wait_window(dialog)
        if dialog.result:
            self.phrases.append(dialog.result)
            self._persist()

    def edit_phrase(self, index):
        current = self.phrases[index]
        dialog = PhraseDialog(self.root, "Edit Phrase",
                              current["label"], current["text"])
        self.root.wait_window(dialog)
        if dialog.result:
            self.phrases[index] = dialog.result
            self._persist()

    def delete_phrase(self, index):
        label = self.phrases[index]["label"]
        if messagebox.askyesno(DISPLAY_NAME, f"Delete “{label}”?", parent=self.root):
            del self.phrases[index]
            self._persist()

    def move(self, index, delta):
        target = index + delta
        if 0 <= target < len(self.phrases):
            self.phrases[index], self.phrases[target] = (
                self.phrases[target], self.phrases[index])
            self._persist()

    def context_menu(self, event, index):
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="Edit…", command=lambda: self.edit_phrase(index))
        menu.add_command(label="Move Up", command=lambda: self.move(index, -1))
        menu.add_command(label="Move Down", command=lambda: self.move(index, 1))
        menu.add_separator()
        menu.add_command(label="Delete", command=lambda: self.delete_phrase(index))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def toggle_on_top(self):
        self.on_top = bool(self.on_top_var.get())
        self.root.attributes("-topmost", self.on_top)
        self._save_geometry()

    def show_preferences(self):
        """Open Settings, or raise the one already open — Cmd+, is easy to
        hit twice, and a stack of identical windows is its own bug."""
        if self.prefs is not None and self.prefs.winfo_exists():
            self.prefs.deiconify()
            self.prefs.lift()
            self.prefs.focus_force()
        else:
            self.prefs = PreferencesDialog(self.root, self)
        return self.prefs

    def reveal_data(self):
        subprocess.run(["open", data_dir()], check=False)

    def _persist(self):
        if not save_phrases(self.phrases):
            messagebox.showerror(
                DISPLAY_NAME,
                f"Could not write to:\n{phrases_path()}",
                parent=self.root,
            )
        self.render()

    def quit(self):
        self._save_geometry()
        self.root.destroy()


# ---- headless entry points --------------------------------------------------
def cmd_doctor() -> int:
    print(f"{DISPLAY_NAME} — diagnostics")
    print(f"  python      : {sys.executable}")
    print(f"  version     : {sys.version.split()[0]}")
    print(f"  script      : {os.path.abspath(__file__)}")
    print(f"  data dir    : {data_dir()}")
    print(f"  phrases file: {phrases_path()}")
    writable = os.access(data_dir(), os.W_OK)
    print(f"  writable    : {writable}")
    try:
        import tkinter
        patch = tkinter.Tcl().eval("info patchlevel")
        good = tkinter.TkVersion >= 8.6
        print(f"  tkinter     : {'OK' if good else 'TOO OLD'} (Tk {patch})")
        if not good:
            print("                Tk 8.5 cannot draw this window on modern macOS:")
            print("                buttons appear, everything else stays blank.")
            print("                Use a python3 with Tk 8.6+, e.g. brew install python-tk")
            return 1
    except Exception as exc:                                   # noqa: BLE001
        print(f"  tkinter     : MISSING ({exc})")
        return 1
    print(f"  phrases     : {len(load_phrases())}")
    return 0 if writable else 1


def cmd_selftest() -> int:
    """Build the real UI off-screen and verify it. No visible window.

    Always runs against a throwaway data folder — it writes probe phrases, and
    must never touch the real ones.
    """
    sandbox = tempfile.mkdtemp(prefix="prompt-clipboard-selftest-")
    os.environ["PROMPT_CLIPBOARD_HOME"] = sandbox
    try:
        return _selftest_body()
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


def _selftest_body() -> int:
    checks, failures = [], 0

    def check(name, ok, detail=""):
        nonlocal failures
        if not ok:
            failures += 1
        checks.append(f"  [{'PASS' if ok else 'FAIL'}] {name}"
                      + (f" — {detail}" if detail else ""))

    check("Tk 8.6+ (8.5 draws a blank window)", tk.TkVersion >= 8.6,
          f"Tk {tk.Tcl().eval('info patchlevel')}")
    check("data dir writable", os.access(data_dir(), os.W_OK), data_dir())

    probe = [{"label": "selftest", "text": "hello"}]
    check("save phrases", save_phrases(probe))
    check("load round-trip", load_phrases() == probe)

    try:
        root = tk.Tk()
        root.withdraw()
        app = App(root)
        root.update_idletasks()
        check("window built", True)
        check("rows rendered", len(app.rows) == 1, f"{len(app.rows)} row(s)")
        check("menu attached", bool(root.cget("menu")))
        check("geometry on-screen",
              app.root.winfo_x() >= 0 and app.root.winfo_y() >= 0)
        app.filter_text = "nope"
        check("filter works", app.visible() == [])

        prefs = app.show_preferences()
        root.update_idletasks()
        check("settings window opens", prefs is not None and prefs.winfo_exists())
        check("settings window is single-instance",
              app.show_preferences() is prefs)

        was = app.on_top
        app.on_top_var.set(not was)      # what the settings checkbox drives
        app.toggle_on_top()
        check("always-on-top toggles", app.on_top is not was,
              f"{was} -> {app.on_top}")
        check("always-on-top persisted",
              bool(load_state().get("on_top")) == app.on_top)
        app.on_top_var.set(was)
        app.toggle_on_top()
        prefs.destroy()

        root.destroy()
    except Exception as exc:                                   # noqa: BLE001
        check("window built", False, repr(exc))

    print(f"{DISPLAY_NAME} self-test")
    print("\n".join(checks))
    print(f"  {len(checks) - failures}/{len(checks)} passed")
    return 1 if failures else 0


def cmd_list() -> int:
    items = load_phrases()
    if not items:
        print("(no phrases)")
        return 0
    for i, item in enumerate(items, 1):
        preview = item["text"].replace("\n", " ")
        if len(preview) > 60:
            preview = preview[:59] + "…"
        print(f"{i:>2}. {item['label']}\n    {preview}")
    return 0


def cmd_copy(label: str) -> int:
    needle = label.lower()
    for item in load_phrases():
        if item["label"].lower() == needle:
            copy_to_clipboard(item["text"])
            print(f"Copied “{item['label']}”")
            return 0
    print(f"No phrase labelled “{label}”", file=sys.stderr)
    return 1


def cmd_add(label: str, text: str) -> int:
    items = load_phrases()
    items.append({"label": label, "text": text})
    if not save_phrases(items):
        print(f"Could not write {phrases_path()}", file=sys.stderr)
        return 1
    print(f"Added “{label}”")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="prompt-clipboard",
                                     description=DISPLAY_NAME)
    parser.add_argument("--selftest", action="store_true",
                        help="verify the UI off-screen, then exit")
    parser.add_argument("--doctor", action="store_true",
                        help="print environment diagnostics")
    parser.add_argument("--list", action="store_true", help="print phrases")
    parser.add_argument("--copy", metavar="LABEL", help="copy a phrase by label")
    parser.add_argument("--add", nargs=2, metavar=("LABEL", "TEXT"),
                        help="add a phrase")
    args = parser.parse_args(argv)

    # Before seeding: the self-test promises it never touches the real phrase
    # folder, and migrating into it here would quietly break that promise.
    if args.selftest:
        return cmd_selftest()

    seed_if_empty()

    if args.doctor:
        return cmd_doctor()
    if args.list:
        return cmd_list()
    if args.copy:
        return cmd_copy(args.copy)
    if args.add:
        return cmd_add(args.add[0], args.add[1])

    # Refuse to draw a blank window. Apple's system Tk 8.5 renders native
    # buttons but nothing else, which looks like a broken app rather than an
    # unsupported one. Use osascript for the warning — it never depends on Tk.
    if tk.TkVersion < 8.6:
        message = (
            f"This copy of Python uses Tk {tk.TkVersion}, which cannot draw "
            "the window on modern macOS. Use a python3 with Tk 8.6 or newer, "
            "for example: brew install python-tk"
        )
        print(message, file=sys.stderr)
        subprocess.run(
            ["/usr/bin/osascript", "-e",
             f'display alert "{DISPLAY_NAME}" message "{message}"'],
            check=False,
        )
        return 1

    root = tk.Tk()
    App(root)
    # A plain Tk app can launch behind other windows; ask macOS to front it.
    root.update_idletasks()
    root.deiconify()
    root.lift()
    root.focus_force()
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
