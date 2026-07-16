"""
Interpresona — FFXIV Dialogue & Interface Text Translation GUI
==============================================================
A premium single-window Tkinter application for extracting, translating,
and injecting FFXIV sheet data (.exh/.exd) safely.
"""
from __future__ import annotations

import os
import sys
import json
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from pathlib import Path
from typing import Optional

# Add the project root to the path so we can import the core package
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from interpresona import __version__
from interpresona.core.pipeline import TranslationPipeline, ExtractionRecord
from interpresona.core.masker import validate_placeholders as _validate_ph
from interpresona.core.sqpack import SqPackReader
from interpresona.core.session import save_session, load_session, session_summary
from interpresona.core.translator import (
    DeepLTranslator, LibreTranslateTranslator, MockTranslator,
    BaseTranslator, TranslationError,
)


# ---------------------------------------------------------------------------
# Colour palette & style constants
# ---------------------------------------------------------------------------
BG_DARK     = "#0f111a"   # deepest background
BG_MID      = "#161929"   # panel backgrounds
BG_CARD     = "#1c2033"   # card / frame backgrounds
BG_HOVER    = "#232740"
ACCENT      = "#7b5ea7"   # purple accent
ACCENT_LIGHT= "#a17dcc"
SUCCESS     = "#4caf7d"
WARNING     = "#e8a838"
ERROR_COL   = "#e05252"
TEXT_PRI    = "#e8eaf0"
TEXT_SEC    = "#8a8fa8"
TEXT_DIM    = "#525672"
BORDER      = "#2a2f4a"

FONT_HEAD   = ("Segoe UI", 16, "bold")
FONT_SUB    = ("Segoe UI", 11, "bold")
FONT_BODY   = ("Segoe UI", 10)
FONT_MONO   = ("Consolas", 9)
FONT_SMALL  = ("Segoe UI", 8)


# ---------------------------------------------------------------------------
# Reusable widgets
# ---------------------------------------------------------------------------

class FlatButton(tk.Button):
    def __init__(self, parent, text="", command=None, accent=False, danger=False, **kw):
        bg = ACCENT if accent else (ERROR_COL if danger else BG_CARD)
        fg = TEXT_PRI
        abg = ACCENT_LIGHT if accent else BG_HOVER
        super().__init__(
            parent, text=text, command=command,
            bg=bg, fg=fg, activebackground=abg, activeforeground=fg,
            relief="flat", borderwidth=0, padx=14, pady=7,
            font=FONT_BODY, cursor="hand2", **kw
        )
        self.default_bg = bg
        self.hover_bg = abg
        self.bind("<Enter>", lambda e: self.config(bg=self.hover_bg))
        self.bind("<Leave>", lambda e: self.config(bg=self.default_bg))


class SectionLabel(tk.Label):
    def __init__(self, parent, text="", **kw):
        super().__init__(parent, text=text, bg=BG_MID, fg=ACCENT_LIGHT,
                         font=FONT_SUB, **kw)


class StatusBar(tk.Frame):
    def __init__(self, parent, **kw):
        super().__init__(parent, bg=BG_DARK, height=26, **kw)
        self._label = tk.Label(self, text="Ready", bg=BG_DARK, fg=TEXT_SEC,
                               font=FONT_SMALL, anchor="w")
        self._label.pack(side="left", padx=8)
        self._stats = tk.Label(self, text="", bg=BG_DARK, fg=TEXT_DIM,
                               font=FONT_SMALL, anchor="e")
        self._stats.pack(side="right", padx=8)

    def set(self, msg: str, colour: str = TEXT_SEC):
        self._label.config(text=msg, fg=colour)

    def set_stats(self, stats: dict):
        if not stats:
            self._stats.config(text="")
            return
        t = stats.get("total", 0)
        tr = stats.get("translated", 0)
        p = stats.get("pending", 0)
        e = stats.get("errored", 0)
        self._stats.config(
            text=f"Total: {t}  ok {tr}  ... {p}  ! {e}"
        )


# ---------------------------------------------------------------------------
# Sheet Browser Dialog
# ---------------------------------------------------------------------------

class SheetBrowserDialog(tk.Toplevel):
    """
    Modal dialog that shows a searchable list of all EXD sheets
    discovered from the game's root.exl file.
    """
    def __init__(self, parent, sheets: list[str]):
        super().__init__(parent)
        self.title("Browse EXD Sheets")
        self.geometry("520x560")
        self.configure(bg=BG_DARK)
        self.resizable(True, True)
        self.transient(parent)
        self.grab_set()

        self.result: Optional[str] = None
        self._all_sheets = sheets

        self._build()
        self.wait_window(self)

    def _build(self):
        header = tk.Frame(self, bg=BG_MID, pady=10)
        header.pack(fill="x")
        tk.Label(header, text="Select an EXD Sheet", bg=BG_MID, fg=ACCENT_LIGHT,
                 font=FONT_SUB).pack(side="left", padx=14)
        tk.Label(header, text=f"{len(self._all_sheets)} sheets available",
                 bg=BG_MID, fg=TEXT_DIM, font=FONT_SMALL).pack(side="right", padx=14)

        search_frame = tk.Frame(self, bg=BG_DARK)
        search_frame.pack(fill="x", padx=10, pady=(8, 4))
        tk.Label(search_frame, text="Search:", bg=BG_DARK, fg=TEXT_SEC,
                 font=FONT_SMALL).pack(side="left", padx=(0, 6))
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._filter())
        search_entry = tk.Entry(search_frame, textvariable=self._search_var,
                                bg=BG_CARD, fg=TEXT_PRI, insertbackground=TEXT_PRI,
                                relief="flat", font=FONT_BODY)
        search_entry.pack(side="left", fill="x", expand=True, ipady=4)
        search_entry.focus_set()

        list_frame = tk.Frame(self, bg=BG_DARK)
        list_frame.pack(fill="both", expand=True, padx=10, pady=4)
        sb = ttk.Scrollbar(list_frame)
        sb.pack(side="right", fill="y")
        self._listbox = tk.Listbox(
            list_frame, bg=BG_CARD, fg=TEXT_PRI, selectbackground=ACCENT,
            selectforeground=TEXT_PRI, font=FONT_MONO, relief="flat",
            yscrollcommand=sb.set, activestyle="none",
        )
        self._listbox.pack(fill="both", expand=True)
        sb.config(command=self._listbox.yview)
        self._listbox.bind("<Double-1>", lambda e: self._confirm())
        self._listbox.bind("<Return>",   lambda e: self._confirm())

        btn_frame = tk.Frame(self, bg=BG_DARK)
        btn_frame.pack(fill="x", padx=10, pady=8)
        FlatButton(btn_frame, text="Cancel", command=self.destroy).pack(side="right", padx=(6, 0))
        FlatButton(btn_frame, text="Load Selected", command=self._confirm,
                   accent=True).pack(side="right")

        self._populate(self._all_sheets)

    def _populate(self, sheets: list[str]):
        self._listbox.delete(0, "end")
        for s in sheets:
            self._listbox.insert("end", s)
        if sheets:
            self._listbox.selection_set(0)

    def _filter(self):
        q = self._search_var.get().lower()
        filtered = [s for s in self._all_sheets if q in s.lower()]
        self._populate(filtered)

    def _confirm(self):
        sel = self._listbox.curselection()
        if sel:
            self.result = self._listbox.get(sel[0])
        self.destroy()


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------

class InterpresonaApp(tk.Tk):
    """Main application window."""

    def __init__(self):
        super().__init__()
        self.title("Interpresona — FFXIV Translation Tool")
        self.geometry("1200x750")
        self.minsize(900, 600)
        self.configure(bg=BG_DARK)

        # State
        self._pipeline: Optional[TranslationPipeline] = None
        self._exh_path: Optional[Path] = None
        self._exd_path: Optional[Path] = None
        self._sqpack_reader: Optional[SqPackReader] = None
        self._sqpack_sheets: list[str] = []
        self._current_sheet_name: str = ""   # name of currently loaded sheet
        self._entry_map: dict[str, tuple] = {}  # iid → (row_id, sub_row_id, col_idx)
        self._mode: Optional[str] = None    # "manual" or "sqpack"

        self._setup_styles()
        self._build_ui()
        self._show_startup_overlay()

        # Run autoupdater in a background thread to prevent startup freezes
        import threading
        threading.Thread(target=self._check_for_updates, daemon=True).start()

    def _check_for_updates(self):
        try:
            import urllib.request
            import urllib.parse
            import ssl
            import json
            
            url = "https://api.github.com/repos/Keyain-Zasky/Interpresona/releases/latest"
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Interpresona-AutoUpdater"}
            )
            ctx = ssl._create_unverified_context()
            with urllib.request.urlopen(req, context=ctx, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                latest_tag = data.get("tag_name", "v0.0.0").strip("v")
                current_tag = __version__
                
                # Compare versions semantically (split dots)
                latest_parts = [int(x) for x in latest_tag.split(".") if x.isdigit()]
                current_parts = [int(x) for x in current_tag.split(".") if x.isdigit()]
                
                if latest_parts > current_parts:
                    # Update is available, prompt user in the main thread safely
                    self.after(500, lambda: self._prompt_update(data.get("tag_name"), data.get("html_url")))
        except Exception as e:
            # Silently ignore updates connection issues
            pass

    def _prompt_update(self, new_version: str, release_url: str):
        msg = f"A new version of Interpresona ({new_version}) is available!\n\nWould you like to open the GitHub page to download the latest update?"
        if messagebox.askyesno("Update Available", msg):
            import webbrowser
            webbrowser.open(release_url)

    # ------------------------------------------------------------------
    # Style setup
    # ------------------------------------------------------------------
    def _setup_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        
        # Base backgrounds & text colors
        style.configure(".",
                        background=BG_DARK,
                        foreground=TEXT_PRI,
                        bordercolor=BORDER,
                        lightcolor=BORDER,
                        darkcolor=BORDER)

        # Scrollbars (modern flat design, no arrows, custom thumb)
        style.layout("Vertical.TScrollbar", [
            ("Vertical.Scrollbar.trough", {
                "children": [
                    ("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})
                ],
                "sticky": "ns"
            })
        ])
        style.layout("Horizontal.TScrollbar", [
            ("Horizontal.Scrollbar.trough", {
                "children": [
                    ("Horizontal.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})
                ],
                "sticky": "ew"
            })
        ])
        
        style.configure("TScrollbar",
                        troughcolor=BG_DARK,
                        background=BORDER,
                        bordercolor=BG_DARK,
                        arrowcolor=TEXT_DIM,
                        relief="flat",
                        width=8)
        style.map("TScrollbar",
                  background=[("active", ACCENT), ("pressed", ACCENT_LIGHT)])

        # Treeview (premium flat table styling)
        style.configure("Treeview",
                        background=BG_CARD,
                        foreground=TEXT_PRI,
                        fieldbackground=BG_CARD,
                        rowheight=28,
                        borderwidth=0,
                        font=FONT_BODY)
        style.configure("Treeview.Heading",
                        background=BG_MID,
                        foreground=ACCENT_LIGHT,
                        font=FONT_SUB,
                        borderwidth=0,
                        relief="flat")
        style.map("Treeview",
                  background=[("selected", ACCENT)],
                  foreground=[("selected", TEXT_PRI)])

        # Tabs / Notebook (custom modern borderless flat tabs)
        style.configure("TNotebook", background=BG_DARK, borderwidth=0, highlightthickness=0)
        style.configure("TNotebook.Tab",
                        background=BG_MID,
                        foreground=TEXT_SEC,
                        font=FONT_SUB,
                        padding=[24, 10],
                        borderwidth=0,
                        focuscolor="",
                        lightcolor=BG_DARK,
                        darkcolor=BG_DARK,
                        relief="flat")
        # Ensure selected state doesn't change padding or shrink sizes
        style.map("TNotebook.Tab",
                  background=[("selected", ACCENT), ("active", BG_HOVER)],
                  foreground=[("selected", TEXT_PRI), ("active", TEXT_PRI)],
                  lightcolor=[("selected", ACCENT), ("active", BG_HOVER)],
                  darkcolor=[("selected", ACCENT), ("active", BG_HOVER)],
                  padding=[("selected", [24, 10]), ("active", [24, 10])])

        style.configure("TPanedwindow", background=BG_DARK)
        
        # Soft Premium Combobox Styling (dark mode matching)
        style.configure("TCombobox",
                        fieldbackground=BG_CARD,
                        background=BG_MID,
                        foreground=TEXT_PRI,
                        arrowcolor=TEXT_PRI,
                        bordercolor=BORDER,
                        lightcolor=BORDER,
                        darkcolor=BORDER,
                        padding=6)
        style.map("TCombobox",
                  fieldbackground=[("readonly", BG_CARD)],
                  foreground=[("readonly", TEXT_PRI)])
        # Configure the dropdown listbox option popup style
        self.option_add("*TCombobox*Listbox.background", BG_CARD)
        self.option_add("*TCombobox*Listbox.foreground", TEXT_PRI)
        self.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.option_add("*TCombobox*Listbox.selectForeground", TEXT_PRI)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self):
        # ── Header ──────────────────────────────────────────────────────
        header = tk.Frame(self, bg=BG_DARK)
        header.pack(fill="x", padx=0, pady=0)

        tk.Label(header, text="Interpresona", bg=BG_DARK, fg=ACCENT,
                 font=("Segoe UI", 22, "bold")).pack(side="left", padx=(18, 4), pady=12)
        tk.Label(header, text="— FFXIV Translation Tool", bg=BG_DARK, fg=TEXT_PRI,
                 font=("Segoe UI", 22)).pack(side="left", pady=12)
        tk.Label(header, text="EXH/EXD  ·  SeString-safe  ·  Variable-preserving",
                 bg=BG_DARK, fg=TEXT_DIM,
                 font=FONT_SMALL).pack(side="left", padx=18, pady=12)

        # Mode quick-toggle button in header
        self._mode_btn = FlatButton(header, text="Switch Mode", command=self._show_startup_overlay, accent=False)
        self._mode_btn.pack(side="right", padx=18, pady=12)

        sep = tk.Frame(self, bg=BORDER, height=1)
        sep.pack(fill="x")

        # ── Body split: left sidebar + right paned area ──────────────────
        body = tk.Frame(self, bg=BG_DARK)
        body.pack(fill="both", expand=True, padx=0, pady=0)

        # Left sidebar with Scrollbar support for smaller screens
        sidebar_outer = tk.Frame(body, bg=BG_MID, width=250)
        sidebar_outer.pack(side="left", fill="y")
        sidebar_outer.pack_propagate(False)

        canvas = tk.Canvas(sidebar_outer, bg=BG_MID, bd=0, highlightthickness=0, width=230)
        scrollbar = ttk.Scrollbar(sidebar_outer, orient="vertical", command=canvas.yview)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        canvas.configure(yscrollcommand=scrollbar.set)

        sidebar = tk.Frame(canvas, bg=BG_MID, width=230)
        sidebar_window = canvas.create_window((0, 0), window=sidebar, anchor="nw", width=230)

        def _on_sidebar_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))

        sidebar.bind("<Configure>", _on_sidebar_configure)
        
        # Mousewheel scrolling for the sidebar
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", lambda event: _on_mousewheel(event) if ".canvas" in str(event.widget) else None)

        self._build_sidebar(sidebar)

        vsep = tk.Frame(body, bg=BORDER, width=1)
        vsep.pack(side="left", fill="y")

        # Right main area
        main = tk.Frame(body, bg=BG_DARK)
        main.pack(side="left", fill="both", expand=True)
        self._build_main(main)

        # ── Status bar ──────────────────────────────────────────────────
        sep2 = tk.Frame(self, bg=BORDER, height=1)
        sep2.pack(fill="x")
        self._status = StatusBar(self)
        self._status.pack(fill="x")

    def _show_startup_overlay(self):
        # Create an inline overlay frame inside the main window
        self._overlay_frame = tk.Frame(self, bg=BG_DARK)
        self._overlay_frame.place(relx=0, rely=0, relwidth=1, relheight=1)

        # Center Container
        center = tk.Frame(self._overlay_frame, bg=BG_DARK)
        center.place(relx=0.5, rely=0.5, anchor="center")

        title_lbl = tk.Label(center, text="Interpresona", bg=BG_DARK, fg=ACCENT, font=("Segoe UI", 36, "bold"))
        title_lbl.pack(pady=(0, 6))

        tagline = tk.Label(center, text="FFXIV dialogue and interface text translation suite", bg=BG_DARK, fg=TEXT_SEC, font=FONT_BODY)
        tagline.pack(pady=(0, 36))

        options_frame = tk.Frame(center, bg=BG_DARK)
        options_frame.pack()

        # SQPACK Option Card
        sq_card = tk.Frame(options_frame, bg=BG_CARD, bd=1, highlightbackground=BORDER, highlightthickness=1)
        sq_card.pack(side="left", padx=10, ipadx=8, ipady=8)
        
        sq_title = tk.Label(sq_card, text="SQPACK SINGLE SHEET", bg=BG_CARD, fg=ACCENT_LIGHT, font=FONT_SUB)
        sq_title.pack(pady=(16, 6))
        sq_desc = tk.Label(sq_card, text="Browse and translate single dialogue sheets directly from FFXIV game repository files", bg=BG_CARD, fg=TEXT_SEC, font=FONT_SMALL, wraplength=180)
        sq_desc.pack(pady=(0, 20))
        
        FlatButton(sq_card, text="Select Mode", command=lambda: self._set_mode("sqpack"), accent=True).pack(pady=(0, 10))

        # SQPACK BATCH Card
        sq_batch_card = tk.Frame(options_frame, bg=BG_CARD, bd=1, highlightbackground=BORDER, highlightthickness=1)
        sq_batch_card.pack(side="left", padx=10, ipadx=8, ipady=8)
        
        sq_b_title = tk.Label(sq_batch_card, text="SQPACK BATCH MT", bg=BG_CARD, fg=ACCENT_LIGHT, font=FONT_SUB)
        sq_b_title.pack(pady=(16, 6))
        sq_b_desc = tk.Label(sq_batch_card, text="Batch translate ALL dialogue sheets directly from FFXIV game files and save them", bg=BG_CARD, fg=TEXT_SEC, font=FONT_SMALL, wraplength=180)
        sq_b_desc.pack(pady=(0, 20))
        
        FlatButton(sq_batch_card, text="Select Mode", command=lambda: self._set_mode("sqpack_batch"), accent=True).pack(pady=(0, 10))

        # MANUAL Option Card
        man_card = tk.Frame(options_frame, bg=BG_CARD, bd=1, highlightbackground=BORDER, highlightthickness=1)
        man_card.pack(side="left", padx=10, ipadx=8, ipady=8)

        man_title = tk.Label(man_card, text="MANUAL SINGLE FILE", bg=BG_CARD, fg=ACCENT_LIGHT, font=FONT_SUB)
        man_title.pack(pady=(16, 6))
        man_desc = tk.Label(man_card, text="Load and translate a single standalone EXH/EXD file pair extracted on your PC", bg=BG_CARD, fg=TEXT_SEC, font=FONT_SMALL, wraplength=180)
        man_desc.pack(pady=(0, 20))

        FlatButton(man_card, text="Select Mode", command=lambda: self._set_mode("manual"), accent=True).pack(pady=(0, 10))

        # MASS Option Card
        mass_card = tk.Frame(options_frame, bg=BG_CARD, bd=1, highlightbackground=BORDER, highlightthickness=1)
        mass_card.pack(side="left", padx=10, ipadx=8, ipady=8)

        mass_title = tk.Label(mass_card, text="FILES BATCH MT", bg=BG_CARD, fg=ACCENT_LIGHT, font=FONT_SUB)
        mass_title.pack(pady=(16, 6))
        mass_desc = tk.Label(mass_card, text="Batch translate an entire folder containing standalone EXH/EXD files automatically", bg=BG_CARD, fg=TEXT_SEC, font=FONT_SMALL, wraplength=180)
        mass_desc.pack(pady=(0, 20))

        FlatButton(mass_card, text="Select Mode", command=lambda: self._set_mode("mass"), accent=True).pack(pady=(0, 10))

    def _set_mode(self, mode: str):
        self._mode = mode
        
        # Smooth transition effect using widget updates
        def animate_fade(alpha=1.0):
            if alpha > 0.0:
                # Dim background during transition
                self._overlay_frame.config(bg=BG_DARK)
                self.after(16, lambda: animate_fade(alpha - 0.1))
            else:
                self._overlay_frame.destroy()
                
                # Apply visibility changes
                self._manual_section.pack_forget()
                self._game_section.pack_forget()
                self._mass_section.pack_forget()
                self._sqpack_batch_section.pack_forget()

                if mode == "manual":
                    self._manual_section.pack(fill="x", before=self._translation_sep)
                    self._status.set("Manual Files Mode loaded.", SUCCESS)
                elif mode == "mass":
                    self._mass_section.pack(fill="x", before=self._translation_sep)
                    self._status.set("Files Batch MT Mode loaded.", SUCCESS)
                elif mode == "sqpack_batch":
                    self._sqpack_batch_section.pack(fill="x", before=self._translation_sep)
                    self._status.set("SqPack Batch MT Mode loaded.", SUCCESS)
                else:
                    self._game_section.pack(fill="x", before=self._translation_sep)
                    self._status.set("SqPack Game Loader Mode loaded.", SUCCESS)
        
        animate_fade()

    # ------------------------------------------------------------------
    # Sidebar
    # ------------------------------------------------------------------
    def _build_sidebar(self, parent: tk.Frame):
        pad = {"padx": 12, "pady": 4}

        # Manual files mode section wrapper
        self._manual_section = tk.Frame(parent, bg=BG_MID)
        self._manual_section.pack(fill="x")

        SectionLabel(self._manual_section, text="MANUAL SINGLE FILE").pack(anchor="w", padx=12, pady=(16, 4))
        tk.Label(self._manual_section, text="Schema file (.exh)", bg=BG_MID, fg=TEXT_SEC, font=FONT_SMALL).pack(anchor="w", **pad)
        
        self._exh_var = tk.StringVar(value="No file selected")
        tk.Label(self._manual_section, textvariable=self._exh_var, bg=BG_MID, fg=TEXT_DIM,
                 font=FONT_SMALL, wraplength=200, justify="left").pack(anchor="w", padx=12)
        FlatButton(self._manual_section, text="Browse EXH…", command=self._browse_exh).pack(fill="x", padx=12, pady=(4, 8))

        tk.Label(self._manual_section, text="Data file (.exd)", bg=BG_MID, fg=TEXT_SEC, font=FONT_SMALL).pack(anchor="w", **pad)
        self._exd_var = tk.StringVar(value="No file selected")
        tk.Label(self._manual_section, textvariable=self._exd_var, bg=BG_MID, fg=TEXT_DIM,
                 font=FONT_SMALL, wraplength=200, justify="left").pack(anchor="w", padx=12)
        FlatButton(self._manual_section, text="Browse EXD…", command=self._browse_exd).pack(fill="x", padx=12, pady=(4, 8))

        FlatButton(self._manual_section, text="Load & Extract", command=self._load_and_extract, accent=True).pack(fill="x", padx=12, pady=(4, 12))

        # Files Batch MT section wrapper
        self._mass_section = tk.Frame(parent, bg=BG_MID)
        self._mass_section.pack_forget()

        SectionLabel(self._mass_section, text="FILES BATCH MT").pack(anchor="w", padx=12, pady=(16, 4))
        tk.Label(self._mass_section, text="Source folder containing files", bg=BG_MID, fg=TEXT_SEC, font=FONT_SMALL).pack(anchor="w", **pad)
        self._mass_src_var = tk.StringVar(value="No folder selected")
        tk.Label(self._mass_section, textvariable=self._mass_src_var, bg=BG_MID, fg=TEXT_DIM,
                 font=FONT_SMALL, wraplength=200, justify="left").pack(anchor="w", padx=12)
        FlatButton(self._mass_section, text="Select Source Folder…", command=self._browse_mass_src).pack(fill="x", padx=12, pady=(4, 8))

        tk.Label(self._mass_section, text="Output destination folder", bg=BG_MID, fg=TEXT_SEC, font=FONT_SMALL).pack(anchor="w", **pad)
        self._mass_out_var = tk.StringVar(value="No folder selected")
        tk.Label(self._mass_section, textvariable=self._mass_out_var, bg=BG_MID, fg=TEXT_DIM,
                 font=FONT_SMALL, wraplength=200, justify="left").pack(anchor="w", padx=12)
        FlatButton(self._mass_section, text="Select Output Folder…", command=self._browse_mass_out).pack(fill="x", padx=12, pady=(4, 8))

        FlatButton(self._mass_section, text="Run Batch Translate", command=self._run_mass_translate, accent=True).pack(fill="x", padx=12, pady=(4, 12))

        # SqPack Batch MT section wrapper
        self._sqpack_batch_section = tk.Frame(parent, bg=BG_MID)
        self._sqpack_batch_section.pack_forget()

        SectionLabel(self._sqpack_batch_section, text="SQPACK BATCH MT").pack(anchor="w", padx=12, pady=(16, 4))
        tk.Label(self._sqpack_batch_section, text="Game directory", bg=BG_MID, fg=TEXT_SEC, font=FONT_SMALL).pack(anchor="w", padx=12)
        self._sqb_game_dir_var = tk.StringVar(value="Not set")
        tk.Label(self._sqpack_batch_section, textvariable=self._sqb_game_dir_var, bg=BG_MID, fg=TEXT_DIM,
                 font=FONT_SMALL, wraplength=200, justify="left").pack(anchor="w", padx=12)
        FlatButton(self._sqpack_batch_section, text="Browse Game Folder…", command=self._browse_sqb_game_dir).pack(fill="x", padx=12, pady=(4, 4))

        tk.Label(self._sqpack_batch_section, text="Language", bg=BG_MID, fg=TEXT_SEC, font=FONT_SMALL).pack(anchor="w", padx=12, pady=(6, 0))
        self._sqb_lang_var = tk.StringVar(value="en")
        sqb_lang_frame = tk.Frame(self._sqpack_batch_section, bg=BG_MID)
        sqb_lang_frame.pack(fill="x", padx=12, pady=(2, 4))
        ttk.Combobox(sqb_lang_frame, textvariable=self._sqb_lang_var,
                     values=["en", "ja", "de", "fr", "chs", "cht", "ko"],
                     state="readonly", width=8, font=FONT_BODY).pack(side="left")

        tk.Label(self._sqpack_batch_section, text="Output destination folder", bg=BG_MID, fg=TEXT_SEC, font=FONT_SMALL).pack(anchor="w", **pad)
        self._sqb_out_var = tk.StringVar(value="No folder selected")
        tk.Label(self._sqpack_batch_section, textvariable=self._sqb_out_var, bg=BG_MID, fg=TEXT_DIM,
                 font=FONT_SMALL, wraplength=200, justify="left").pack(anchor="w", padx=12)
        FlatButton(self._sqpack_batch_section, text="Select Output Folder…", command=self._browse_sqb_out).pack(fill="x", padx=12, pady=(4, 8))

        FlatButton(self._sqpack_batch_section, text="Run SqPack Batch MT", command=self._run_sqpack_batch_translate, accent=True).pack(fill="x", padx=12, pady=(4, 12))

        # Game files loader mode section wrapper
        self._game_section = tk.Frame(parent, bg=BG_MID)
        self._game_section.pack_forget()

        SectionLabel(self._game_section, text="SQPACK SINGLE SHEET").pack(anchor="w", padx=12, pady=(16, 4))
        tk.Label(self._game_section, text="Game directory", bg=BG_MID, fg=TEXT_SEC, font=FONT_SMALL).pack(anchor="w", padx=12)
        
        self._game_dir_var = tk.StringVar(value="Not set")
        tk.Label(self._game_section, textvariable=self._game_dir_var, bg=BG_MID, fg=TEXT_DIM,
                 font=FONT_SMALL, wraplength=200, justify="left").pack(anchor="w", padx=12)
        FlatButton(self._game_section, text="Browse Game Folder…", command=self._browse_game_dir).pack(fill="x", padx=12, pady=(4, 4))

        tk.Label(self._game_section, text="Language", bg=BG_MID, fg=TEXT_SEC, font=FONT_SMALL).pack(anchor="w", padx=12, pady=(6, 0))
        self._lang_var = tk.StringVar(value="en")
        lang_frame = tk.Frame(self._game_section, bg=BG_MID)
        lang_frame.pack(fill="x", padx=12, pady=(2, 4))
        
        lang_menu = ttk.Combobox(lang_frame, textvariable=self._lang_var,
                                  values=["en", "ja", "de", "fr", "chs", "cht", "ko"],
                                  state="readonly", width=8,
                                  font=FONT_BODY)
        lang_menu.pack(side="left")

        FlatButton(self._game_section, text="Browse & Load Sheet…", command=self._browse_and_load_sheet, accent=True).pack(fill="x", padx=12, pady=(2, 12))

        self._translation_sep = tk.Frame(parent, bg=BORDER, height=1)
        self._translation_sep.pack(fill="x", padx=12, pady=4)

        SectionLabel(parent, text="TRANSLATION").pack(anchor="w", padx=12, pady=(12, 4))
        FlatButton(parent, text="Export CSV for MT…", command=self._export_csv).pack(fill="x", padx=12, pady=4)
        FlatButton(parent, text="Import Translated CSV…", command=self._import_csv).pack(fill="x", padx=12, pady=4)

        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", padx=12, pady=8)

        SectionLabel(parent, text="OUTPUT").pack(anchor="w", padx=12, pady=(4, 4))
        FlatButton(parent, text="Save Translated EXD...", command=self._save_exd, accent=True).pack(fill="x", padx=12, pady=4)

        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", padx=12, pady=8)

        # Filler
        tk.Frame(parent, bg=BG_MID).pack(fill="both", expand=True)

        # Version footer
        tk.Label(parent, text=f"Interpresona v{__version__}  |  Step-by-step Wizard", bg=BG_MID, fg=TEXT_DIM, font=FONT_SMALL).pack(pady=10)

    # ------------------------------------------------------------------
    # Main content area
    # ------------------------------------------------------------------
    def _build_main(self, parent: tk.Frame):
        # ── Step Indicator Panel ─────────────────────────────────────────
        self._steps_frame = tk.Frame(parent, bg=BG_MID, padx=12, pady=10)
        self._steps_frame.pack(fill="x", padx=10, pady=(10, 4))
        
        self._step_labels = []
        steps_data = [
            ("1. LOAD / BROWSE", "Select game folder or files", 0),
            ("2. REVIEW STRINGS", "Browse & edit dialogue table", 1),
            ("3. AUTO-TRANSLATE", "Run machine translation", 2),
            ("4. EXPORT & SAVE", "Export translated data", 3),
        ]
        
        for name, desc, tab_idx in steps_data:
            step_box = tk.Frame(self._steps_frame, bg=BG_CARD, highlightbackground=BORDER, highlightthickness=1, cursor="hand2")
            step_box.pack(side="left", fill="x", expand=True, padx=4)
            
            lbl_title = tk.Label(step_box, text=name, bg=BG_CARD, fg=TEXT_SEC, font=("Segoe UI", 10, "bold"))
            lbl_title.pack(anchor="w", padx=10, pady=(6, 2))
            
            lbl_desc = tk.Label(step_box, text=desc, bg=BG_CARD, fg=TEXT_DIM, font=("Segoe UI", 8))
            lbl_desc.pack(anchor="w", padx=10, pady=(0, 6))
            
            # Click handles to switch tabs
            for w in (step_box, lbl_title, lbl_desc):
                w.bind("<Button-1>", lambda e, idx=tab_idx: self._select_step(idx))
            
            self._step_labels.append((tab_idx, step_box, lbl_title, lbl_desc))

        # Divider
        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", padx=10, pady=4)

        # Notebook (tabs) - hide standard tab headers, use steps for navigation
        nb_frame = tk.Frame(parent, bg=BG_DARK)
        nb_frame.pack(fill="both", expand=True)

        # Custom style to hide notebook tabs entirely
        style = ttk.Style(self)
        style.layout("NoTabs.TNotebook", []) # Hides tabs
        
        self._nb = ttk.Notebook(nb_frame, style="NoTabs.TNotebook")
        self._nb.pack(fill="both", expand=True, padx=10, pady=10)

        # Rearrange tabs: 0 = Load Info, 1 = Strings, 2 = Auto-Translate, 3 = Schema/Log
        self._tab_loadinfo = tk.Frame(self._nb, bg=BG_DARK)
        self._tab_strings  = tk.Frame(self._nb, bg=BG_DARK)
        self._tab_mt       = tk.Frame(self._nb, bg=BG_DARK)
        self._tab_export   = tk.Frame(self._nb, bg=BG_DARK)

        self._nb.add(self._tab_loadinfo, text="  Load  ")
        self._nb.add(self._tab_strings,  text="  Strings  ")
        self._nb.add(self._tab_mt,       text="  Auto-Translate  ")
        self._nb.add(self._tab_export,   text="  Export  ")

        self._build_loadinfo_tab(self._tab_loadinfo)
        self._build_strings_tab(self._tab_strings)
        self._build_mt_tab(self._tab_mt)
        self._build_export_tab(self._tab_export)

        # Add schema/logs to a standalone bottom section or within tab views to keep simple
        self._tab_schema = self._tab_export
        self._tab_log = self._tab_export

        # Pre-build schema widgets within the export tab frame container so they exist from start
        self._build_schema_tab(self._tab_export)

        # Highlight first step
        self._select_step(0)

    def _select_step(self, active_idx: int):
        self._nb.select(active_idx)
        
        # Color coding for active steps
        for tab_idx, step_box, lbl_title, lbl_desc in self._step_labels:
            if tab_idx == active_idx:
                step_box.config(bg=ACCENT, highlightbackground=ACCENT)
                lbl_title.config(bg=ACCENT, fg=TEXT_PRI)
                lbl_desc.config(bg=ACCENT, fg=TEXT_PRI)
            else:
                step_box.config(bg=BG_CARD, highlightbackground=BORDER)
                lbl_title.config(bg=BG_CARD, fg=TEXT_SEC)
                lbl_desc.config(bg=BG_CARD, fg=TEXT_DIM)

    def _build_loadinfo_tab(self, parent: tk.Frame):
        container = tk.Frame(parent, bg=BG_DARK, padx=30, pady=30)
        container.pack(fill="both", expand=True)

        tk.Label(container, text="STEP 1: LOAD YOUR DATA SOURCE", bg=BG_DARK, fg=ACCENT_LIGHT, font=("Segoe UI", 16, "bold")).pack(anchor="w", pady=(0, 10))
        tk.Label(container, text="Please select your desired mode of operation using the 'Switch Mode' button in the top right, then configure your loaded paths in the left sidebar panel.", bg=BG_DARK, fg=TEXT_SEC, font=FONT_BODY, justify="left", wraplength=700).pack(anchor="w", pady=(0, 24))

        card = tk.Frame(container, bg=BG_CARD, padx=20, pady=20, bd=1, highlightbackground=BORDER, highlightthickness=1)
        card.pack(fill="x", pady=10)

        tk.Label(card, text="Current Session Status", bg=BG_CARD, fg=TEXT_PRI, font=FONT_SUB).pack(anchor="w", pady=(0, 12))
        
        self._load_status_lbl = tk.Label(card, text="No sheet or files loaded. Select a source on the left sidebar.", bg=BG_CARD, fg=WARNING, font=FONT_BODY, justify="left")
        self._load_status_lbl.pack(anchor="w")

        FlatButton(container, text="Proceed to Step 2: Review Strings →", command=lambda: self._select_step(1), accent=True).pack(anchor="w", pady=30)

    def _build_export_tab(self, parent: tk.Frame):
        container = tk.Frame(parent, bg=BG_DARK, padx=30, pady=30)
        container.pack(fill="both", expand=True)

        tk.Label(container, text="STEP 4: SAVE & EXPORT RESULTS", bg=BG_DARK, fg=ACCENT_LIGHT, font=("Segoe UI", 16, "bold")).pack(anchor="w", pady=(0, 10))
        tk.Label(container, text="Finalize your translation work by exporting to CSV formats, saving your custom database session, or reconstructing translation-injected EXD binary sheets.", bg=BG_DARK, fg=TEXT_SEC, font=FONT_BODY, justify="left", wraplength=700).pack(anchor="w", pady=(0, 24))

        grid = tk.Frame(container, bg=BG_DARK)
        grid.pack(fill="x", pady=10)

        # Re-pack outputs in a modern layout grid
        c1 = tk.Frame(grid, bg=BG_CARD, padx=20, pady=16, bd=1, highlightbackground=BORDER, highlightthickness=1)
        c1.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        tk.Label(c1, text="Original Sheets / CSVs", bg=BG_CARD, fg=TEXT_PRI, font=FONT_SUB).pack(anchor="w", pady=(0, 8))
        FlatButton(c1, text="Export CSV for MT…", command=self._export_csv).pack(fill="x", pady=4)
        FlatButton(c1, text="Import Translated CSV…", command=self._import_csv).pack(fill="x", pady=4)

        c2 = tk.Frame(grid, bg=BG_CARD, padx=20, pady=16, bd=1, highlightbackground=BORDER, highlightthickness=1)
        c2.grid(row=0, column=1, sticky="nsew", padx=8, pady=8)
        tk.Label(c2, text="Binary Injection EXD", bg=BG_CARD, fg=TEXT_PRI, font=FONT_SUB).pack(anchor="w", pady=(0, 8))
        FlatButton(c2, text="Save Translated EXD...", command=self._save_exd, accent=True).pack(fill="x", pady=4)

        c3 = tk.Frame(grid, bg=BG_CARD, padx=20, pady=16, bd=1, highlightbackground=BORDER, highlightthickness=1)
        c3.grid(row=0, column=2, sticky="nsew", padx=8, pady=8)
        tk.Label(c3, text="Session Database", bg=BG_CARD, fg=TEXT_PRI, font=FONT_SUB).pack(anchor="w", pady=(0, 8))
        FlatButton(c3, text="Save Session...", command=self._save_session).pack(fill="x", pady=4)
        FlatButton(c3, text="Load Session...", command=self._load_session).pack(fill="x", pady=4)

        # Log & Schema toggle frame
        logs_card = tk.Frame(container, bg=BG_CARD, padx=16, pady=16, bd=1, highlightbackground=BORDER, highlightthickness=1)
        logs_card.pack(fill="both", expand=True, pady=16)
        tk.Label(logs_card, text="Console logs & diagnostic trace output:", bg=BG_CARD, fg=TEXT_SEC, font=FONT_SMALL).pack(anchor="w")
        
        self._log = scrolledtext.ScrolledText(
            logs_card, bg=BG_DARK, fg=TEXT_PRI, insertbackground=TEXT_PRI,
            font=FONT_MONO, state="disabled", relief="flat", height=8
        )
        self._log.pack(fill="both", expand=True, pady=(6, 0))
        self._log.tag_config("info",    foreground=TEXT_SEC)
        self._log.tag_config("success", foreground=SUCCESS)
        self._log.tag_config("warning", foreground=WARNING)
        self._log.tag_config("error",   foreground=ERROR_COL)

    # ------------------------------------------------------------------
    # Strings tab
    # ------------------------------------------------------------------
    def _build_strings_tab(self, parent: tk.Frame):
        # Toolbar
        toolbar = tk.Frame(parent, bg=BG_MID)
        toolbar.pack(fill="x", pady=(0, 6))

        tk.Label(toolbar, text="Filter:", bg=BG_MID, fg=TEXT_SEC,
                 font=FONT_SMALL).pack(side="left", padx=(8, 4), pady=6)
        self._filter_var = tk.StringVar()
        self._filter_var.trace_add("write", lambda *_: self._apply_filter())
        filter_entry = tk.Entry(toolbar, textvariable=self._filter_var,
                                bg=BG_CARD, fg=TEXT_PRI, insertbackground=TEXT_PRI,
                                relief="flat", font=FONT_BODY, width=30)
        filter_entry.pack(side="left", padx=4, pady=6, ipady=3)

        self._show_var = tk.StringVar(value="all")
        self._filter_pills = []
        
        def _on_pill_click(clicked_val):
            self._show_var.set(clicked_val)
            self._apply_filter()
            # Update background colors dynamically to simulate premium active tabs
            for pill_val, pill_btn in self._filter_pills:
                if pill_val == clicked_val:
                    pill_btn.config(bg=ACCENT, fg=TEXT_PRI)
                else:
                    pill_btn.config(bg=BG_CARD, fg=TEXT_SEC)

        for val, label in [("all", "All"), ("pending", "Pending"), ("done", "Translated"), ("error", "Errors")]:
            # Initial active styling
            init_bg = ACCENT if val == "all" else BG_CARD
            init_fg = TEXT_PRI if val == "all" else TEXT_SEC
            
            btn = tk.Button(toolbar, text=label, command=lambda v=val: _on_pill_click(v),
                            bg=init_bg, fg=init_fg, activebackground=ACCENT_LIGHT, activeforeground=TEXT_PRI,
                            font=FONT_SMALL, relief="flat", borderwidth=0, padx=12, pady=4, cursor="hand2")
            btn.pack(side="left", padx=3, pady=6)
            self._filter_pills.append((val, btn))

        # Treeview with columns — translator-friendly view (no internal indices)
        cols = ("entry", "original", "translated", "status")
        tree_frame = tk.Frame(parent, bg=BG_DARK)
        tree_frame.pack(fill="both", expand=True)

        xsb = ttk.Scrollbar(tree_frame, orient="horizontal")
        ysb = ttk.Scrollbar(tree_frame, orient="vertical")

        self._tree = ttk.Treeview(
            tree_frame, columns=cols, show="headings",
            yscrollcommand=ysb.set, xscrollcommand=xsb.set, selectmode="extended"
        )
        ysb.config(command=self._tree.yview)
        xsb.config(command=self._tree.xview)

        self._tree.heading("entry",      text="#")
        self._tree.heading("original",   text="Source Text")
        self._tree.heading("translated", text="Translation")
        self._tree.heading("status",     text="Status")

        self._tree.column("entry",      width=55,  stretch=False, anchor="center")
        self._tree.column("original",   width=420, stretch=True)
        self._tree.column("translated", width=420, stretch=True)
        self._tree.column("status",     width=90,  stretch=False, anchor="center")

        self._tree.tag_configure("done",    foreground=SUCCESS)
        self._tree.tag_configure("error",   foreground=ERROR_COL)
        self._tree.tag_configure("pending", foreground=WARNING)

        self._tree.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        xsb.grid(row=1, column=0, sticky="ew")
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)

        self._tree.bind("<<TreeviewSelect>>", self._on_row_select)
        self._tree.bind("<Double-1>", self._on_row_double_click)

        # Inline editor at bottom
        editor_frame = tk.Frame(parent, bg=BG_MID)
        editor_frame.pack(fill="x", pady=(6, 0))

        tk.Label(editor_frame, text="Inline editor (selected row):",
                 bg=BG_MID, fg=TEXT_SEC, font=FONT_SMALL).pack(anchor="w", padx=10, pady=(8, 2))

        edit_row = tk.Frame(editor_frame, bg=BG_MID)
        edit_row.pack(fill="x", padx=10, pady=(0, 8))

        # Multiline text areas with custom border simulation (premium cards with thin borders)
        original_border = tk.Frame(edit_row, bg=BORDER, bd=1, highlightthickness=0)
        original_border.pack(side="left", fill="both", expand=True, padx=(0, 6))
        self._edit_original = tk.Text(original_border, bg=BG_DARK, fg=TEXT_SEC,
                                      relief="flat", font=FONT_BODY, height=3,
                                      wrap="word", insertbackground=TEXT_PRI,
                                      padx=8, pady=6,
                                      selectbackground=ACCENT, selectforeground=TEXT_PRI)
        self._edit_original.pack(fill="both", expand=True, padx=1, pady=1)
        self._edit_original.config(state="disabled")

        translated_border = tk.Frame(edit_row, bg=BORDER, bd=1, highlightthickness=0)
        translated_border.pack(side="left", fill="both", expand=True, padx=(0, 6))
        self._edit_translated = tk.Text(translated_border, bg=BG_CARD, fg=TEXT_PRI,
                                        relief="flat", font=FONT_BODY, height=3,
                                        wrap="word", insertbackground=TEXT_PRI,
                                        padx=8, pady=6,
                                        selectbackground=ACCENT, selectforeground=TEXT_PRI)
        self._edit_translated.pack(fill="both", expand=True, padx=1, pady=1)

        # Custom focus highlight simulation
        self._edit_translated.bind("<FocusIn>", lambda e: translated_border.config(bg=ACCENT))
        self._edit_translated.bind("<FocusOut>", lambda e: translated_border.config(bg=BORDER))

        # Bind Enter to commit, Shift+Enter to insert newlines
        def _on_enter_pressed(event):
            self._commit_inline_edit()
            return "break"
        self._edit_translated.bind("<Return>", _on_enter_pressed)

        # Style-aligned Save Button
        FlatButton(edit_row, text="Save Translation", command=self._commit_inline_edit,
                   accent=True).pack(side="left", fill="y", ipadx=10)

        self._selected_key: Optional[tuple] = None

    # ------------------------------------------------------------------
    # Schema tab
    # ------------------------------------------------------------------
    def _build_schema_tab(self, parent: tk.Frame):
        lbl = tk.Label(parent, text="EXH Schema Details", bg=BG_DARK, fg=ACCENT_LIGHT,
                       font=FONT_SUB)
        lbl.pack(anchor="w", padx=12, pady=(12, 6))

        cols = ("field", "value")
        self._schema_tree = ttk.Treeview(parent, columns=cols, show="headings", height=8)
        self._schema_tree.heading("field", text="Field")
        self._schema_tree.heading("value", text="Value")
        self._schema_tree.column("field", width=200, stretch=False)
        self._schema_tree.column("value", width=600, stretch=True)
        self._schema_tree.pack(fill="x", padx=12)

        tk.Label(parent, text="Column Definitions", bg=BG_DARK, fg=ACCENT_LIGHT,
                 font=FONT_SUB).pack(anchor="w", padx=12, pady=(16, 6))

        col_cols = ("idx", "type_hex", "type_name", "offset", "is_string")
        self._col_tree = ttk.Treeview(parent, columns=col_cols, show="headings")
        self._col_tree.heading("idx",       text="#")
        self._col_tree.heading("type_hex",  text="Type (hex)")
        self._col_tree.heading("type_name", text="Type")
        self._col_tree.heading("offset",    text="Offset")
        self._col_tree.heading("is_string", text="String?")
        for c in col_cols:
            self._col_tree.column(c, width=120, stretch=(c == "type_name"))
        sb = ttk.Scrollbar(parent, command=self._col_tree.yview)
        self._col_tree.configure(yscrollcommand=sb.set)
        self._col_tree.pack(fill="both", expand=True, padx=12, pady=(0, 8))

    # ------------------------------------------------------------------
    # Log tab
    # ------------------------------------------------------------------
    def _build_log_tab(self, parent: tk.Frame):
        hdr = tk.Frame(parent, bg=BG_DARK)
        hdr.pack(fill="x")
        tk.Label(hdr, text="Event Log", bg=BG_DARK, fg=ACCENT_LIGHT,
                 font=FONT_SUB).pack(side="left", padx=12, pady=8)
        FlatButton(hdr, text="Clear", command=self._clear_log).pack(side="right", padx=12, pady=6)

        self._log = scrolledtext.ScrolledText(
            parent, bg=BG_CARD, fg=TEXT_PRI, insertbackground=TEXT_PRI,
            font=FONT_MONO, state="disabled", relief="flat"
        )
        self._log.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self._log.tag_config("info",    foreground=TEXT_SEC)
        self._log.tag_config("success", foreground=SUCCESS)
        self._log.tag_config("warning", foreground=WARNING)
        self._log.tag_config("error",   foreground=ERROR_COL)

    # ------------------------------------------------------------------
    # Auto-Translate tab
    # ------------------------------------------------------------------
    def _build_mt_tab(self, parent: tk.Frame):
        tk.Label(parent, text="Machine Translation Settings", bg=BG_DARK,
                 fg=ACCENT_LIGHT, font=FONT_SUB).pack(anchor="w", padx=14, pady=(14, 6))

        # ── Backend selector ─────────────────────────────────────────────
        card = tk.Frame(parent, bg=BG_CARD, padx=14, pady=12)
        card.pack(fill="x", padx=12, pady=4)

        tk.Label(card, text="Backend", bg=BG_CARD, fg=TEXT_SEC,
                 font=FONT_SMALL).grid(row=0, column=0, sticky="w")
        self._mt_backend_var = tk.StringVar(value="deepl")
        backend_menu = ttk.Combobox(card, textvariable=self._mt_backend_var,
                                     values=["deepl", "libretranslate", "mock"],
                                     state="readonly", width=18, font=FONT_BODY)
        backend_menu.grid(row=0, column=1, sticky="w", padx=(10, 0))
        backend_menu.bind("<<ComboboxSelected>>", lambda e: self._on_backend_change())

        # ── DeepL settings ───────────────────────────────────────────────
        self._deepl_frame = tk.Frame(parent, bg=BG_CARD, padx=14, pady=10)
        self._deepl_frame.pack(fill="x", padx=12, pady=4)
        tk.Label(self._deepl_frame, text="DeepL API Key", bg=BG_CARD,
                 fg=TEXT_SEC, font=FONT_SMALL).grid(row=0, column=0, sticky="w")
        self._deepl_key_var = tk.StringVar()
        deepl_entry = tk.Entry(self._deepl_frame, textvariable=self._deepl_key_var,
                               show="*", bg=BG_MID, fg=TEXT_PRI, insertbackground=TEXT_PRI,
                               relief="flat", font=FONT_MONO, width=38)
        deepl_entry.grid(row=0, column=1, padx=(10, 0), ipady=3)

        tk.Label(self._deepl_frame, text="Source lang", bg=BG_CARD,
                 fg=TEXT_SEC, font=FONT_SMALL).grid(row=1, column=0, sticky="w", pady=(6, 0))
        self._deepl_src_var = tk.StringVar(value="JA")
        tk.Entry(self._deepl_frame, textvariable=self._deepl_src_var,
                 bg=BG_MID, fg=TEXT_PRI, insertbackground=TEXT_PRI,
                 relief="flat", font=FONT_BODY, width=8).grid(row=1, column=1, sticky="w",
                                                               padx=(10, 0), pady=(6, 0), ipady=3)

        tk.Label(self._deepl_frame, text="Target lang", bg=BG_CARD,
                 fg=TEXT_SEC, font=FONT_SMALL).grid(row=2, column=0, sticky="w", pady=(4, 0))
        self._deepl_tgt_var = tk.StringVar(value="EN-GB")
        tk.Entry(self._deepl_frame, textvariable=self._deepl_tgt_var,
                 bg=BG_MID, fg=TEXT_PRI, insertbackground=TEXT_PRI,
                 relief="flat", font=FONT_BODY, width=8).grid(row=2, column=1, sticky="w",
                                                               padx=(10, 0), pady=(4, 0), ipady=3)

        # ── LibreTranslate settings ──────────────────────────────────────
        self._libre_frame = tk.Frame(parent, bg=BG_CARD, padx=14, pady=10)
        tk.Label(self._libre_frame, text="LibreTranslate URL", bg=BG_CARD,
                 fg=TEXT_SEC, font=FONT_SMALL).grid(row=0, column=0, sticky="w")
        self._libre_url_var = tk.StringVar(value="https://libretranslate.com")
        tk.Entry(self._libre_frame, textvariable=self._libre_url_var,
                 bg=BG_MID, fg=TEXT_PRI, insertbackground=TEXT_PRI,
                 relief="flat", font=FONT_MONO, width=38).grid(row=0, column=1, padx=(10, 0), ipady=3)
        tk.Label(self._libre_frame, text="API Key (optional)", bg=BG_CARD,
                 fg=TEXT_SEC, font=FONT_SMALL).grid(row=1, column=0, sticky="w", pady=(6, 0))
        self._libre_key_var = tk.StringVar()
        tk.Entry(self._libre_frame, textvariable=self._libre_key_var,
                 show="*", bg=BG_MID, fg=TEXT_PRI, insertbackground=TEXT_PRI,
                 relief="flat", font=FONT_MONO, width=38).grid(row=1, column=1, padx=(10, 0),
                                                                pady=(6, 0), ipady=3)
        tk.Label(self._libre_frame, text="Source lang", bg=BG_CARD,
                 fg=TEXT_SEC, font=FONT_SMALL).grid(row=2, column=0, sticky="w", pady=(4, 0))
        self._libre_src_var = tk.StringVar(value="ja")
        tk.Entry(self._libre_frame, textvariable=self._libre_src_var,
                 bg=BG_MID, fg=TEXT_PRI, insertbackground=TEXT_PRI,
                 relief="flat", font=FONT_BODY, width=8).grid(row=2, column=1, sticky="w",
                                                                padx=(10, 0), pady=(4, 0), ipady=3)
        tk.Label(self._libre_frame, text="Target lang", bg=BG_CARD,
                 fg=TEXT_SEC, font=FONT_SMALL).grid(row=3, column=0, sticky="w", pady=(4, 0))
        self._libre_tgt_var = tk.StringVar(value="en")
        tk.Entry(self._libre_frame, textvariable=self._libre_tgt_var,
                 bg=BG_MID, fg=TEXT_PRI, insertbackground=TEXT_PRI,
                 relief="flat", font=FONT_BODY, width=8).grid(row=3, column=1, sticky="w",
                                                               padx=(10, 0), pady=(4, 0), ipady=3)

        # Show/hide correct frame
        self._on_backend_change()

        # ── Progress & run button ────────────────────────────────────────
        run_card = tk.Frame(parent, bg=BG_CARD, padx=14, pady=12)
        run_card.pack(fill="x", padx=12, pady=(8, 4))

        tk.Label(run_card, text="Scope:", bg=BG_CARD, fg=TEXT_SEC,
                 font=FONT_SMALL).grid(row=0, column=0, sticky="w")
        self._mt_scope_var = tk.StringVar(value="pending")
        scope_menu = ttk.Combobox(run_card, textvariable=self._mt_scope_var,
                                   values=["pending", "all"],
                                   state="readonly", width=12, font=FONT_BODY)
        scope_menu.grid(row=0, column=1, sticky="w", padx=(10, 0))

        FlatButton(run_card, text="Run Auto-Translate", command=self._run_mt,
                   accent=True).grid(row=0, column=2, padx=(20, 0))

        self._mt_progress_var = tk.StringVar(value="")
        tk.Label(run_card, textvariable=self._mt_progress_var, bg=BG_CARD,
                 fg=TEXT_SEC, font=FONT_SMALL).grid(row=1, column=0, columnspan=3,
                                                     sticky="w", pady=(8, 0))
        self._mt_progress_bar = ttk.Progressbar(run_card, length=400, mode="determinate")
        self._mt_progress_bar.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(4, 0))

        tk.Label(parent,
                 text="Placeholders (⟪VAR_n⟫) are automatically preserved.\n"
                      "Strings where the MT engine removes a placeholder are rejected.",
                 bg=BG_DARK, fg=TEXT_DIM, font=FONT_SMALL,
                 justify="left").pack(anchor="w", padx=14, pady=(10, 0))

    def _on_backend_change(self):
        backend = self._mt_backend_var.get()
        self._deepl_frame.pack_forget()
        self._libre_frame.pack_forget()
        if backend == "deepl":
            self._deepl_frame.pack(fill="x", padx=12, pady=4)
        elif backend == "libretranslate":
            self._libre_frame.pack(fill="x", padx=12, pady=4)

    def _build_translator(self) -> BaseTranslator:
        backend = self._mt_backend_var.get()
        if backend == "deepl":
            key = self._deepl_key_var.get().strip()
            if not key:
                raise ValueError("DeepL API key is required.")
            return DeepLTranslator(
                api_key=key,
                source_lang=self._deepl_src_var.get().strip() or None,
                target_lang=self._deepl_tgt_var.get().strip() or "EN-GB",
            )
        elif backend == "libretranslate":
            return LibreTranslateTranslator(
                url=self._libre_url_var.get().strip(),
                api_key=self._libre_key_var.get().strip(),
                source_lang=self._libre_src_var.get().strip(),
                target_lang=self._libre_tgt_var.get().strip(),
            )
        else:  # mock
            return MockTranslator()

    def _run_mt(self):
        if not self._pipeline:
            messagebox.showwarning("No data", "Load an EXH/EXD pair first.")
            return
        try:
            translator = self._build_translator()
        except ValueError as exc:
            messagebox.showerror("Configuration Error", str(exc))
            return

        scope = self._mt_scope_var.get()
        if scope == "pending":
            targets = [r for r in self._pipeline.records
                       if not r.translated_text and not r.errors]
        else:
            targets = [r for r in self._pipeline.records if not r.errors]

        if not targets:
            messagebox.showinfo("Nothing to translate",
                                "No pending strings found (all may already be translated).")
            return

        total = len(targets)
        self._mt_progress_bar["maximum"] = total
        self._mt_progress_bar["value"] = 0
        errors_found: list[str] = []

        CHUNK = 20
        for chunk_start in range(0, total, CHUNK):
            chunk = targets[chunk_start: chunk_start + CHUNK]
            texts = [r.masked_text for r in chunk]
            try:
                results = translator.translate(texts)
            except TranslationError as exc:
                errors_found.append(str(exc))
                self._log_msg(f"MT error: {exc}", "error")
                break

            for rec, translated in zip(chunk, results):
                from interpresona.core.masker import validate_placeholders
                ph_errors = validate_placeholders(translated, rec.placeholders)
                if ph_errors:
                    rec.errors.extend(ph_errors)
                    errors_found.extend(ph_errors)
                    self._log_msg(f"Row {rec.row_id}: placeholder mismatch — skipped", "warning")
                else:
                    rec.translated_text = translated

            self._mt_progress_bar["value"] = min(chunk_start + CHUNK, total)
            progress_pct = int((chunk_start + CHUNK) / total * 100)
            self._mt_progress_var.set(
                f"Translating... {min(chunk_start + CHUNK, total)}/{total} ({progress_pct}%)"
            )
            self.update()

        self._mt_progress_var.set(f"Done. {total} strings processed.")
        self._populate_strings_table(self._pipeline.records)
        self._status.set_stats(self._pipeline.stats)
        if errors_found:
            self._log_msg(f"MT completed with {len(errors_found)} issue(s).", "warning")
        else:
            self._log_msg(f"MT completed. {total} strings translated.", "success")

    # ------------------------------------------------------------------
    # Session save / load
    # ------------------------------------------------------------------
    def _save_session(self):
        if not self._pipeline:
            messagebox.showwarning("No data", "Load an EXH/EXD pair first.")
            return
        path = filedialog.asksaveasfilename(
            title="Save Session",
            defaultextension=".ffxivts",
            filetypes=[("FFXIV Translation Session", "*.ffxivts"), ("All files", "*")],
        )
        if not path:
            return
        try:
            save_session(
                Path(path),
                self._pipeline,
                sheet_name=getattr(self, "_current_sheet_name", ""),
                language=getattr(self, "_lang_var", type("", (), {"get": lambda s: ""})()).get(),
                source_exh_path=str(self._exh_path or ""),
                source_exd_path=str(self._exd_path or ""),
            )
            self._log_msg(f"Session saved: {Path(path).name}", "success")
            self._status.set(f"Session saved: {Path(path).name}", SUCCESS)
        except Exception as exc:
            self._log_msg(f"Save session error: {exc}", "error")
            messagebox.showerror("Save Error", str(exc))

    def _load_session(self):
        path = filedialog.askopenfilename(
            title="Load Session",
            filetypes=[("FFXIV Translation Session", "*.ffxivts"), ("All files", "*")],
        )
        if not path:
            return
        try:
            # Show quick summary before loading
            summary = session_summary(Path(path))
            msg = (f"Sheet: {summary['sheet_name'] or 'unknown'}\n"
                   f"Total strings: {summary['total']}\n"
                   f"Translated: {summary['translated']}  "
                   f"Pending: {summary['pending']}  "
                   f"Errors: {summary['errored']}\n\nLoad this session?")
            if not messagebox.askyesno("Load Session", msg):
                return

            self._pipeline, metadata = load_session(Path(path))
            self._populate_schema_tab()
            self._populate_strings_table(self._pipeline.records)
            self._status.set_stats(self._pipeline.stats)
            sheet = metadata.get("sheet_name", "")
            self._log_msg(
                f"Session loaded: {Path(path).name}"
                + (f" ({sheet})" if sheet else ""), "success"
            )
            self._status.set(f"Session loaded: {Path(path).name}", SUCCESS)
            
            # Step-by-step GUI improvements: update load status panel and advance step
            self._load_status_lbl.config(
                text=f"✓ LOADED SESSION DATABASE:\n- File: {Path(path).name}\n- Associated Sheet: {sheet or 'standalone'}\n- String Count: {len(self._pipeline.records)}\nReady to translate.",
                fg=SUCCESS
            )
            self._select_step(1)
        except Exception as exc:
            self._log_msg(f"Load session error: {exc}", "error")
            messagebox.showerror("Load Error", str(exc))

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _browse_exh(self):
        p = filedialog.askopenfilename(
            title="Select EXH file", filetypes=[("EXH Files", "*.exh"), ("All files", "*")])
        if p:
            self._exh_path = Path(p)
            self._exh_var.set(self._exh_path.name)
            self._log_msg(f"EXH: {p}", "info")

    def _browse_exd(self):
        p = filedialog.askopenfilename(
            title="Select EXD file", filetypes=[("EXD Files", "*.exd"), ("All files", "*")])
        if p:
            self._exd_path = Path(p)
            self._exd_var.set(self._exd_path.name)
            self._log_msg(f"EXD: {p}", "info")

    def _browse_mass_src(self):
        p = filedialog.askdirectory(title="Select Source Folder containing EXH/EXD files")
        if p:
            self._mass_src_path = Path(p)
            self._mass_src_var.set(self._mass_src_path.name)
            self._log_msg(f"Mass Source Folder: {p}", "info")

    def _browse_mass_out(self):
        p = filedialog.askdirectory(title="Select Output Destination Folder")
        if p:
            self._mass_out_path = Path(p)
            self._mass_out_var.set(self._mass_out_path.name)
            self._log_msg(f"Mass Output Folder: {p}", "info")

    def _browse_sqb_game_dir(self):
        p = filedialog.askdirectory(title="Select FFXIV Game Directory (the folder containing 'game/')")
        if p:
            self._sqb_game_path = Path(p)
            self._sqb_game_dir_var.set(self._sqb_game_path.name)
            self._log_msg(f"SqPack Game Folder: {p}", "info")

    def _browse_sqb_out(self):
        p = filedialog.askdirectory(title="Select Output Destination Folder")
        if p:
            self._sqb_out_path = Path(p)
            self._sqb_out_var.set(self._sqb_out_path.name)
            self._log_msg(f"SqPack Batch Output Folder: {p}", "info")

    def _run_sqpack_batch_translate(self):
        game_dir = getattr(self, "_sqb_game_path", None)
        out_dir = getattr(self, "_sqb_out_path", None)
        lang = self._sqb_lang_var.get()
        if not game_dir or not out_dir:
            messagebox.showwarning("Missing folders", "Please select both game directory and output folders first.")
            return

        try:
            translator = self._build_translator()
        except ValueError as exc:
            messagebox.showerror("Configuration Error", str(exc))
            return

        self._log_msg("Opening SqPack database...", "info")
        try:
            reader = SqPackReader.from_game_directory(game_dir)
            raw_sheets = reader.list_exd_sheets()
            # Filter dialogue sheets
            sheets = [
                s for s in raw_sheets
                if any(x in s.lower() for x in ("quest", "talk", "text", "opening", "cutscene", "dawn", "addon", "chat", "bubble"))
            ]
        except Exception as exc:
            messagebox.showerror("SqPack Error", f"Could not load game files: {exc}")
            return

        if not sheets:
            messagebox.showinfo("No sheets", "No dialogue sheets found in root.exl.")
            return

        # Switch to Auto-Translate step so the user can visually track progress
        self._select_step(2)

        self._log_msg(f"Starting batch translation of {len(sheets)} SqPack sheet(s) to language '{lang}'...", "info")
        self._status.set("SqPack Batch MT...", WARNING)

        # Set up progress bar
        self._mt_progress_bar["maximum"] = len(sheets)
        self._mt_progress_bar["value"] = 0

        import re
        technical_key_pat = re.compile(r"^[A-Z][A-Z0-9_]{4,80}$")

        success_count = 0
        for i, sheet_name in enumerate(sheets):
            # Update UI progress metrics
            self._mt_progress_bar["value"] = i
            self._mt_progress_var.set(
                f"SqPack Batch: processing {sheet_name} ({i}/{len(sheets)} sheets translated)"
            )
            self.update()

            self._log_msg(f"Processing sheet {sheet_name}...", "info")
            
            exh_path = SqPackReader.exh_path(sheet_name)
            if not reader.file_exists(exh_path):
                self._log_msg(f"  EXH schema file not found in SqPack: {exh_path}", "warning")
                continue

            try:
                exh_bytes = reader.read_file(exh_path)
                
                # Check page count
                from interpresona.core.parser import EXHParser
                schema = EXHParser(exh_bytes).result
                n_pages = len(schema.pages) if schema.pages else 1

                exd_pages: list[bytes] = []
                for page_idx in range(n_pages):
                    page_bytes = None
                    for candidate_lang in (lang, ""):
                        candidate = SqPackReader.exd_path(sheet_name, page=page_idx, lang=candidate_lang)
                        if reader.file_exists(candidate):
                            page_bytes = reader.read_file(candidate)
                            break
                    if page_bytes is not None:
                        exd_pages.append(page_bytes)
                    else:
                        break

                if not exd_pages:
                    self._log_msg(f"  No EXD page 0 files found for language {lang}", "warning")
                    continue

                pipeline = TranslationPipeline(exh_bytes, exd_pages)
                records = pipeline.extract()

                # Filter translatable targets (skipping technical IDs)
                targets = []
                for rec in records:
                    text_str = rec.masked_text.strip()
                    if technical_key_pat.match(text_str) or text_str.startswith("TEXT_") or text_str.startswith("KEY_"):
                        continue
                    if not rec.translated_text and not rec.errors:
                        targets.append(rec)

                if targets:
                    self._log_msg(f"  Translating {len(targets)} string(s)...", "info")
                    CHUNK = 20
                    for chunk_start in range(0, len(targets), CHUNK):
                        chunk = targets[chunk_start: chunk_start + CHUNK]
                        texts = [r.masked_text for r in chunk]
                        translated_list = translator.translate(texts)
                        for rec, translated in zip(chunk, translated_list):
                            # Verify placeholders
                            from interpresona.core.masker import validate_placeholders as _val
                            ph_err = _val(translated, rec.placeholders)
                            if ph_err:
                                self._log_msg(f"    Row {rec.row_id}: placeholder mismatch — skipped", "warning")
                            else:
                                rec.translated_text = translated

                # Save translated EXD pages back to output folder.
                # Since sheet names can contain folders (e.g. quest/004/ManFst008_00448),
                safe_sheet_name = sheet_name.replace("/", "_")
                page_data = pipeline.inject_all()
                for page_id, binary in page_data.items():
                    out_name = f"{safe_sheet_name}_{page_id}.exd"
                    (Path(out_dir) / out_name).write_bytes(binary)
                
                # Save EXH Alongside
                (Path(out_dir) / f"{safe_sheet_name}.exh").write_bytes(exh_bytes)
                self._log_msg(f"  Successfully translated and saved {sheet_name}", "success")
                success_count += 1
            except Exception as exc:
                self._log_msg(f"  Error processing sheet {sheet_name}: {exc}", "error")

        self._mt_progress_bar["value"] = len(sheets)
        self._mt_progress_var.set(f"SqPack Batch finished: {success_count} / {len(sheets)} translated.")
        self._log_msg(f"SqPack Batch translation completed. {success_count} / {len(sheets)} sheets translated.", "success")
        self._status.set(f"SqPack Batch finished. {success_count} sheets saved.", SUCCESS)
        self.update()

    def _run_mass_translate(self):
        src_dir = getattr(self, "_mass_src_path", None)
        out_dir = getattr(self, "_mass_out_path", None)
        if not src_dir or not out_dir:
            messagebox.showwarning("Missing folders", "Please select both source and output folders first.")
            return

        try:
            translator = self._build_translator()
        except ValueError as exc:
            messagebox.showerror("Configuration Error", str(exc))
            return

        # Scan for .exh files case-insensitively, supporting recursive layout or nested folder structures
        exh_files = []
        for root, dirs, files in os.walk(str(src_dir)):
            for f in files:
                if f.lower().endswith(".exh"):
                    exh_files.append(Path(root) / f)

        if not exh_files:
            self._log_msg(f"Scan directory: {src_dir} (scanned recursively)", "warning")
            messagebox.showinfo("No files found", "No .exh schema files found (even recursively) in the source folder.")
            return

        self._select_step(2)
        self._log_msg(f"Starting batch translation of {len(exh_files)} sheet(s)...", "info")
        self._status.set("Batch translating...", WARNING)
        self._mt_progress_bar["maximum"] = len(exh_files)
        self._mt_progress_bar["value"] = 0

        import re
        technical_key_pat = re.compile(r"^[A-Z][A-Z0-9_]{4,80}$")

        success_count = 0
        for i, exh_path in enumerate(exh_files):
            self._mt_progress_bar["value"] = i
            self._mt_progress_var.set(f"Batch Translate: {exh_path.stem} ({i}/{len(exh_files)})")
            self.update()
            
            # Find matching .exd files case-insensitively in the same directory as the EXH
            exh_dir = exh_path.parent
            exh_stem_lower = exh_path.stem.lower()
            exd_files = []
            
            for entry in exh_dir.iterdir():
                if entry.is_file() and entry.suffix.lower() == ".exd":
                    entry_stem_lower = entry.stem.lower() # Verify stem, not name with extension
                    # Check if matching sheet stem or stem + page (e.g. quest_0.exd)
                    if entry_stem_lower == exh_stem_lower or entry_stem_lower.startswith(exh_stem_lower + "_"):
                        exd_files.append(entry)

            if not exd_files:
                self._log_msg(f"  Skipping {exh_path.name}: no matching .exd files found in {exh_dir}", "warning")
                continue

            # Sort files by suffix pages if named like _0.exd, _1.exd
            exd_files.sort(key=lambda x: x.name)

            self._log_msg(f"Translating sheet {exh_path.name} from {exh_dir.name}...", "info")
            try:
                exh_bytes = exh_path.read_bytes()
                exd_pages = [f.read_bytes() for f in exd_files]
                
                pipeline = TranslationPipeline(exh_bytes, exd_pages)
                records = pipeline.extract()

                # Filter translatable targets (skipping technical IDs)
                targets = []
                for rec in records:
                    text_str = rec.masked_text.strip()
                    if technical_key_pat.match(text_str) or text_str.startswith("TEXT_") or text_str.startswith("KEY_"):
                        continue
                    if not rec.translated_text and not rec.errors:
                        targets.append(rec)

                if targets:
                    self._log_msg(f"  Found {len(targets)} translatable string(s). Translating...", "info")
                    # Batch translate targets in chunks
                    CHUNK = 20
                    for chunk_start in range(0, len(targets), CHUNK):
                        chunk = targets[chunk_start: chunk_start + CHUNK]
                        texts = [r.masked_text for r in chunk]
                        translated_list = translator.translate(texts)
                        for rec, translated in zip(chunk, translated_list):
                            # Verify placeholders
                            from interpresona.core.masker import validate_placeholders as _val
                            ph_err = _val(translated, rec.placeholders)
                            if ph_err:
                                self._log_msg(f"    Row {rec.row_id}: placeholder mismatch — skipped", "warning")
                            else:
                                rec.translated_text = translated
                        self.update()

                # Save translated exd files back to output folder
                page_data = pipeline.inject_all()
                for page_id, binary in page_data.items():
                    # Preserve exact filename structure of source EXD files
                    if len(exd_files) == 1 and not "_" in exd_files[0].stem:
                        out_name = f"{exh_path.stem}.exd"
                    else:
                        out_name = f"{exh_path.stem}_{page_id}.exd"
                    (Path(out_dir) / out_name).write_bytes(binary)
                
                # Write matching exh schema alongside
                (Path(out_dir) / exh_path.name).write_bytes(exh_bytes)
                self._log_msg(f"  Successfully saved {exh_path.stem} translated files to output folder", "success")
                success_count += 1
            except Exception as exc:
                self._log_msg(f"  Error processing sheet {exh_path.name}: {exc}", "error")

        self._mt_progress_bar["value"] = len(exh_files)
        self._mt_progress_var.set(f"Batch completed: {success_count} / {len(exh_files)} sheets translated.")
        self._log_msg(f"Batch translation completed. {success_count} / {len(exh_files)} sheets translated.", "success")
        self._status.set(f"Batch MT finished. {success_count} sheets saved.", SUCCESS)
        self.update()

    def _browse_game_dir(self):
        p = filedialog.askdirectory(title="Select FFXIV Game Directory (the folder containing 'game/')")
        if not p:
            return
        game_dir = Path(p)
        self._status.set("Opening SqPack index...", WARNING)
        self.update_idletasks()
        try:
            reader = SqPackReader.from_game_directory(game_dir)
            self._sqpack_reader = reader
            
            # Filter sheets: keep only sheets with names implying readable dialogs or texts,
            # like quest, talk, text, addon, guide, opening, cutscene, etc.
            raw_sheets = reader.list_exd_sheets()
            self._sqpack_sheets = [
                s for s in raw_sheets
                if any(x in s.lower() for x in ("quest", "talk", "text", "opening", "cutscene", "dawn", "addon", "chat", "bubble"))
            ]
            self._game_dir_var.set(game_dir.name)
            msg = (f"SqPack opened: {reader.entry_count} index entries, "
                   f"{len(self._sqpack_sheets)} dialog sheets filtered from {len(raw_sheets)} total")
            self._status.set(msg, SUCCESS)
            self._log_msg(msg, "success")
        except Exception as exc:
            self._status.set(f"SqPack error: {exc}", ERROR_COL)
            self._log_msg(f"SqPack open error: {exc}", "error")
            messagebox.showerror("SqPack Error", str(exc))

    def _browse_and_load_sheet(self):
        if not self._sqpack_reader:
            messagebox.showwarning(
                "No game loaded",
                "Click 'Browse Game Folder' first to open the FFXIV SqPack index."
            )
            return
        if not self._sqpack_sheets:
            messagebox.showwarning("No sheets", "root.exl could not be read or returned no sheets.")
            return

        dlg = SheetBrowserDialog(self, self._sqpack_sheets)
        sheet_name = dlg.result
        if not sheet_name:
            return

        lang = self._lang_var.get()
        self._current_sheet_name = sheet_name

        self._status.set(f"Loading {sheet_name} ({lang})...", WARNING)
        self.update_idletasks()

        # ── 1. Read EXH ────────────────────────────────────────────────────
        exh_path = SqPackReader.exh_path(sheet_name)
        try:
            exh_bytes = self._sqpack_reader.read_file(exh_path)
            self._log_msg(f"Read EXH: {exh_path} ({len(exh_bytes)} bytes)", "info")
        except FileNotFoundError as exc:
            self._log_msg(f"EXH not found: {exc}", "error")
            messagebox.showerror("Not Found", str(exc))
            return
        except Exception as exc:
            self._log_msg(f"EXH read error: {exc}", "error")
            messagebox.showerror("Read Error", str(exc))
            return

        # ── 2. Read page count from EXH schema ─────────────────────────────
        from interpresona.core.parser import EXHParser
        try:
            schema = EXHParser(exh_bytes).result
            n_pages = len(schema.pages) if schema.pages else 1
        except Exception:
            n_pages = 1

        self._log_msg(f"Sheet has {n_pages} page(s) defined in EXH", "info")

        # ── 3. Load each page ──────────────────────────────────────────────
        exd_pages: list[bytes] = []
        for page_idx in range(n_pages):
            page_bytes = None
            for candidate_lang in (lang, ""):
                candidate = SqPackReader.exd_path(sheet_name, page=page_idx, lang=candidate_lang)
                if self._sqpack_reader.file_exists(candidate):
                    try:
                        page_bytes = self._sqpack_reader.read_file(candidate)
                        self._log_msg(
                            f"  Page {page_idx}: {candidate} ({len(page_bytes)} bytes)", "info"
                        )
                        break
                    except Exception as exc:
                        self._log_msg(f"  Page {page_idx} read error ({candidate}): {exc}", "warning")

            if page_bytes is None:
                if page_idx == 0:
                    msg = f"EXD page 0 not found for '{sheet_name}' (lang={lang})"
                    self._log_msg(msg, "error")
                    messagebox.showerror("Not Found", msg)
                    return
                else:
                    self._log_msg(f"  Page {page_idx}: not found — stopping at page {page_idx}", "warning")
                    break
            exd_pages.append(page_bytes)

        # ── 4. Feed to pipeline ────────────────────────────────────────────
        try:
            self._pipeline = TranslationPipeline(exh_bytes, exd_pages)
            records = self._pipeline.extract()
            self._populate_schema_tab()
            self._populate_strings_table(records)
            pages_loaded = self._pipeline.page_count
            self._status.set(
                f"Loaded '{sheet_name}' ({lang}) — {pages_loaded} page(s), {len(records)} strings",
                SUCCESS,
            )
            self._status.set_stats(self._pipeline.stats)
            self._log_msg(
                f"Extracted {len(records)} strings from '{sheet_name}' "
                f"({pages_loaded} page(s))", "success"
            )
            
            # Step-by-step GUI improvements: update load status panel and advance step
            self._load_status_lbl.config(
                text=f"✓ LOADED: '{sheet_name}' ({lang})\n- Total Pages: {pages_loaded}\n- String Cells Extracted: {len(records)}\nReady to translate.",
                fg=SUCCESS
            )
            self._select_step(1)
        except Exception as exc:
            self._status.set(f"Parse error: {exc}", ERROR_COL)
            self._log_msg(f"Pipeline error: {exc}", "error")
            messagebox.showerror("Parse Error", str(exc))


    def _load_and_extract(self):
        if not self._exh_path or not self._exd_path:
            messagebox.showwarning("Missing files", "Please select both an EXH and an EXD file first.")
            return
        try:
            exh_bytes = self._exh_path.read_bytes()
            exd_bytes = self._exd_path.read_bytes()
            self._status.set("Parsing files…", WARNING)
            self.update_idletasks()

            self._pipeline = TranslationPipeline(exh_bytes, exd_bytes)
            records = self._pipeline.extract()

            self._populate_schema_tab()
            self._populate_strings_table(records)
            self._status.set(
                f"Loaded {self._exh_path.name} + {self._exd_path.name} — "
                f"{len(records)} string cells extracted", SUCCESS
            )
            self._status.set_stats(self._pipeline.stats)
            self._log_msg(
                f"Extracted {len(records)} translatable string cells from "
                f"{self._exd_path.name}", "success"
            )
            
            # Step-by-step GUI improvements: update load status panel and advance step
            self._load_status_lbl.config(
                text=f"✓ LOADED MANUAL FILES:\n- Schema: {self._exh_path.name}\n- Data: {self._exd_path.name}\n- Strings: {len(records)}",
                fg=SUCCESS
            )
            self._select_step(1)
        except Exception as exc:
            self._status.set(f"Error: {exc}", ERROR_COL)
            self._log_msg(f"Load error: {exc}", "error")
            messagebox.showerror("Load Error", str(exc))

    def _export_csv(self):
        if not self._pipeline:
            messagebox.showwarning("No data", "Load an EXH/EXD pair first.")
            return
        path = filedialog.asksaveasfilename(
            title="Save extraction CSV",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")]
        )
        if not path:
            return
        try:
            Path(path).write_text(self._pipeline.export_csv(), encoding="utf-8-sig")
            self._log_msg(f"Exported CSV to {path}", "success")
            self._status.set(f"Exported: {Path(path).name}", SUCCESS)
        except Exception as exc:
            self._log_msg(f"Export error: {exc}", "error")
            messagebox.showerror("Export Error", str(exc))

    def _import_csv(self):
        if not self._pipeline:
            messagebox.showwarning("No data", "Load an EXH/EXD pair first.")
            return
        path = filedialog.askopenfilename(
            title="Import translated CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*")]
        )
        if not path:
            return
        try:
            csv_text = Path(path).read_text(encoding="utf-8-sig")
            errors = self._pipeline.import_translations_from_csv(csv_text)
            self._populate_strings_table(self._pipeline.records)
            self._status.set_stats(self._pipeline.stats)
            if errors:
                self._log_msg(f"CSV imported with {len(errors)} warnings:", "warning")
                for e in errors[:20]:
                    self._log_msg(f"  ⚠ {e}", "warning")
            else:
                self._log_msg(f"CSV imported cleanly from {Path(path).name}", "success")
                self._status.set(f"Imported: {Path(path).name}", SUCCESS)
        except Exception as exc:
            self._log_msg(f"Import error: {exc}", "error")
            messagebox.showerror("Import Error", str(exc))

    def _save_exd(self):
        if not self._pipeline:
            messagebox.showwarning("No data", "Load an EXH/EXD pair first.")
            return
        stats = self._pipeline.stats
        if stats["translated"] == 0:
            if not messagebox.askyesno(
                "No translations",
                "No strings are translated yet. Save anyway (original content will be preserved)?",
            ):
                return

        n_pages = self._pipeline.page_count
        sheet = getattr(self, "_current_sheet_name", "")
        lang  = self._lang_var.get() if hasattr(self, "_lang_var") else "en"

        if n_pages <= 1:
            # Single-page: save to one file
            default_name = (
                f"{sheet}_0.{lang}_translated.exd" if sheet
                else (self._exd_path.stem + "_translated.exd" if self._exd_path else "output.exd")
            )
            path = filedialog.asksaveasfilename(
                title="Save translated EXD",
                defaultextension=".exd",
                filetypes=[("EXD files", "*.exd"), ("All files", "*")],
                initialfile=default_name,
            )
            if not path:
                return
            try:
                dest_file = Path(path)
                page_data = self._pipeline.inject_all()
                binary = page_data.get(0, b"")
                dest_file.write_bytes(binary)
                self._log_msg(f"Saved translated EXD ({len(binary):,} bytes) to {dest_file.name}", "success")
                
                # Also save the EXH file alongside the EXD
                exh_name = f"{sheet}.exh" if sheet else (self._exh_path.name if self._exh_path else "output.exh")
                exh_dest = dest_file.parent / exh_name
                exh_dest.write_bytes(self._pipeline.exh_bytes)
                self._log_msg(f"Saved matching EXH schema ({len(self._pipeline.exh_bytes):,} bytes) to {exh_dest.name}", "success")
                
                self._status.set(f"Saved EXD and EXH to {dest_file.parent.name}/", SUCCESS)
            except Exception as exc:
                self._log_msg(f"Save error: {exc}", "error")
                messagebox.showerror("Save Error", str(exc))
        else:
            # Multi-page: ask for an output directory, write EXD pages and the EXH schema there
            out_dir = filedialog.askdirectory(
                title=f"Select output folder for translated EXD page files & EXH schema"
            )
            if not out_dir:
                return
            try:
                dest_dir = Path(out_dir)
                page_data = self._pipeline.inject_all()
                saved = 0
                for page_id, binary in page_data.items():
                    exd_name = f"{sheet}_{page_id}.exd" if sheet else (self._exd_path.stem + f"_{page_id}.exd" if self._exd_path else f"page_{page_id}.exd")
                    dest_file = dest_dir / exd_name
                    dest_file.write_bytes(binary)
                    self._log_msg(f"Saved translated EXD page {page_id} ({len(binary):,} bytes) to {dest_file.name}", "success")
                    saved += 1
                
                # Also save the EXH file in the multi-page folder
                exh_name = f"{sheet}.exh" if sheet else (self._exh_path.name if self._exh_path else "output.exh")
                exh_dest = dest_dir / exh_name
                exh_dest.write_bytes(self._pipeline.exh_bytes)
                self._log_msg(f"Saved matching EXH schema ({len(self._pipeline.exh_bytes):,} bytes) to {exh_dest.name}", "success")
                
                self._log_msg(f"Saved {saved} EXD page(s) and EXH schema to {out_dir}", "success")
                self._status.set(f"Saved EXD and EXH to {dest_dir.name}/", SUCCESS)
            except Exception as exc:
                self._log_msg(f"Save error: {exc}", "error")
                messagebox.showerror("Save Error", str(exc))

    # ------------------------------------------------------------------
    # Inline editor
    # ------------------------------------------------------------------
    def _on_row_select(self, event=None):
        sel = self._tree.selection()
        if not sel:
            return
        iid = sel[0]
        vals = self._tree.item(iid, "values")
        # vals = (entry_num, original, translated, status)
        original   = vals[1]
        translated = vals[2]

        self._edit_original.config(state="normal")
        self._edit_original.delete("1.0", "end")
        self._edit_original.insert("1.0", original)
        self._edit_original.config(state="disabled")

        self._edit_translated.delete("1.0", "end")
        self._edit_translated.insert("1.0", translated)
        self._edit_translated.focus_set()

        # Store current key using the entry map (avoids exposing internal indices)
        key_tuple = self._entry_map.get(iid)
        if key_tuple:
            self._selected_key = key_tuple

    def _on_row_double_click(self, event=None):
        self._edit_translated.focus_set()

    def _commit_inline_edit(self, event=None):
        if not self._pipeline or not self._selected_key:
            return
        # Get content from Text box (strip trailing newline added automatically by Text)
        translated = self._edit_translated.get("1.0", "end-1c").strip()
        key = self._selected_key
        # Find the record
        rec = next((r for r in self._pipeline.records if r.key == key), None)
        if rec is None:
            return
        errors = _validate_ph(translated, rec.placeholders)
        if errors:
            self._log_msg(f"⚠ Placeholder validation failed for {key}:", "warning")
            for e in errors:
                self._log_msg(f"    {e}", "warning")
            messagebox.showwarning(
                "Placeholder mismatch",
                "Translation contains placeholder errors:\n" + "\n".join(errors[:5])
            )
            return
        rec.translated_text = translated
        rec.errors = []
        self._populate_strings_table(self._pipeline.records)
        self._status.set_stats(self._pipeline.stats)
        # User-facing message: don't expose (row_id, sub_row_id, col_idx) tuple
        self._log_msg("Translation saved.", "success")

    # ------------------------------------------------------------------
    # Table population helpers
    # ------------------------------------------------------------------
    def _populate_strings_table(self, records: list[ExtractionRecord]):
        self._tree.delete(*self._tree.get_children())
        self._entry_map = {}
        show = self._show_var.get()
        filt = self._filter_var.get().lower()

        # Compile a quick regex to identify pure technical ID keys (e.g., uppercase alphanum/underscore keys)
        import re
        technical_key_pat = re.compile(r"^[A-Z][A-Z0-9_]{4,80}$")

        entry_num = 0
        for rec in records:
            # Skip records whose masked text is a pure technical key
            text_str = rec.masked_text.strip()
            if technical_key_pat.match(text_str) or text_str.startswith("TEXT_") or text_str.startswith("KEY_"):
                continue

            if rec.errors:
                status, tag = "⚠ Error", "error"
            elif rec.translated_text:
                status, tag = "✓ Done", "done"
            else:
                status, tag = "Pending", "pending"

            if show == "done"    and tag != "done":    continue
            if show == "pending" and tag != "pending":  continue
            if show == "error"   and tag != "error":    continue

            orig_preview = rec.masked_text[:160]
            trans_preview = (rec.translated_text or "")[:160]

            if filt and filt not in orig_preview.lower() and filt not in trans_preview.lower():
                continue

            entry_num += 1
            iid = self._tree.insert(
                "", "end",
                values=(entry_num, orig_preview, trans_preview, status),
                tags=(tag,),
            )
            # Map iid → internal key so row selection can find the record
            self._entry_map[iid] = (rec.row_id, rec.sub_row_id, rec.col_idx)

    def _apply_filter(self):
        if self._pipeline:
            self._populate_strings_table(self._pipeline.records)

    def _populate_schema_tab(self):
        schema = self._pipeline.schema

        # Info table
        self._schema_tree.delete(*self._schema_tree.get_children())
        info = [
            ("Magic",        schema.magic.decode()),
            ("Version",      schema.version),
            ("Row size",     schema.row_size),
            ("Depth",        schema.depth),
            ("Row type",     schema.row_type),
            ("Total rows",   schema.row_count),
            ("Columns",      len(schema.columns)),
            ("Pages",        len(schema.pages)),
            ("Languages",    ", ".join(str(l.lang_code) for l in schema.languages)),
        ]
        for field, val in info:
            self._schema_tree.insert("", "end", values=(field, val))

        # Column table
        self._col_tree.delete(*self._col_tree.get_children())
        type_names = {
            0x0000: "String", 0x0001: "Bool", 0x0002: "Int8",
            0x0003: "UInt8", 0x0004: "Int16", 0x0005: "UInt16",
            0x0006: "Int32", 0x0007: "UInt32", 0x0009: "Float32",
            0x000B: "Int64", 0x000C: "UInt64",
        }
        for idx, col in enumerate(schema.columns):
            if 0x0019 <= col.col_type <= 0x0038:
                tname = f"BitBool[{col.col_type - 0x0019}]"
            else:
                tname = type_names.get(col.col_type, f"Unknown(0x{col.col_type:04X})")
            self._col_tree.insert("", "end", values=(
                idx, f"0x{col.col_type:04X}", tname, col.offset, "Yes" if col.is_string else ""
            ))

    # ------------------------------------------------------------------
    # Log helpers
    # ------------------------------------------------------------------
    def _log_msg(self, msg: str, level: str = "info"):
        self._log.config(state="normal")
        self._log.insert("end", msg + "\n", level)
        self._log.see("end")
        self._log.config(state="disabled")

    def _clear_log(self):
        self._log.config(state="normal")
        self._log.delete("1.0", "end")
        self._log.config(state="disabled")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    app = InterpresonaApp()
    app.mainloop()


if __name__ == "__main__":
    main()
