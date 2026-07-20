"""
Interpresona — Simplified Step-by-Step Wizard GUI
=================================================
A streamlined, compact wizard interface for non-technical users.
Guides the user step-by-step:
  Step 1: Select Input Data (Game SqPack / Folder / File)
  Step 2: Translation Service Setup & Connection Test
  Step 3: Select Output Destination
  Step 4: Execute & Real-Time Progress
"""
from __future__ import annotations

import os
import sys
import json
import threading
import urllib.request
import urllib.parse
import ssl
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from pathlib import Path
from typing import Optional

# Ensure project root is in path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from interpresona import __version__
from interpresona.core.sqpack import SqPackReader
from interpresona.core.parser import EXHParser
from interpresona.core.pipeline import TranslationPipeline
from interpresona.core.masker import validate_placeholders
from interpresona.core.translator import (
    DeepLTranslator, LibreTranslateTranslator, MockTranslator,
    BaseTranslator, TranslationError,
)

# ---------------------------------------------------------------------------
# Styling palette (Ultra High-Contrast Modern Dark Theme)
# ---------------------------------------------------------------------------
BG_DARK       = "#0d0f17"
BG_MID        = "#141724"
BG_CARD       = "#1c2032"
BG_INPUT      = "#22273d"
BG_SELECT     = "#262c47"
BG_HOVER      = "#2d3454"
ACCENT        = "#7c3aed"
ACCENT_LIGHT  = "#c084fc"
SUCCESS       = "#10b981"
WARNING       = "#f59e0b"
ERROR_COL     = "#ef4444"
TEXT_PRI      = "#ffffff"
TEXT_SEC      = "#cbd5e1"
TEXT_DIM      = "#94a3b8"
BORDER        = "#333a56"
BORDER_SELECT = "#7c3aed"

FONT_HEAD     = ("Segoe UI", 14, "bold")
FONT_SUB      = ("Segoe UI", 10, "bold")
FONT_BODY     = ("Segoe UI", 9)
FONT_MONO     = ("Consolas", 9)
FONT_SMALL    = ("Segoe UI", 8)


def enable_high_dpi_awareness():
    """Enable High DPI awareness for crisp vector font anti-aliasing on Windows."""
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # Process_Per_Monitor_DPI_Aware_V2
    except Exception:
        try:
            import ctypes
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


class FlatButton(tk.Button):
    def __init__(self, parent, text="", command=None, accent=False, danger=False, **kw):
        self._accent = accent
        self._danger = danger
        self._normal_bg = ACCENT if accent else (ERROR_COL if danger else "#282d44")
        self._disabled_bg = "#24283b"
        self._disabled_fg = "#64748b"

        super().__init__(
            parent, text=text, command=command, bg=self._normal_bg, fg=TEXT_PRI,
            activebackground=ACCENT_LIGHT if accent else (BG_HOVER if not danger else "#f87171"),
            activeforeground=TEXT_PRI,
            disabledforeground=self._disabled_fg,
            relief="flat", bd=0,
            font=FONT_SUB, cursor="hand2", padx=16, pady=8, **kw
        )
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)

    def config(self, cnf=None, **kw):
        if "state" in kw:
            if kw["state"] == "disabled":
                kw["bg"] = self._disabled_bg
                kw["fg"] = self._disabled_fg
                kw["cursor"] = "arrow"
            elif kw["state"] in ("normal", "active"):
                kw["bg"] = self._normal_bg
                kw["fg"] = TEXT_PRI
                kw["cursor"] = "hand2"
        super().config(cnf, **kw)

    def configure(self, cnf=None, **kw):
        self.config(cnf, **kw)

    def _on_enter(self, e):
        if self.cget("state") != "disabled":
            self.config(bg=ACCENT_LIGHT if self._accent else (BG_HOVER if not self._danger else "#f87171"))

    def _on_leave(self, e):
        if self.cget("state") != "disabled":
            self.config(bg=self._normal_bg)


class InterpresonaSimpleApp(tk.Tk):
    """Simplified Step-by-Step Wizard GUI Window."""

    def __init__(self):
        enable_high_dpi_awareness()
        super().__init__()
        try:
            self.tk.call("tk", "scaling", 1.25)
        except Exception:
            pass

        self.title("Interpresona — Guided Translation Wizard")
        self.geometry("900x700")
        self.minsize(820, 580)
        self.configure(bg=BG_DARK)

        # Wizard state
        self._current_step = 1
        self._source_type = tk.StringVar(value="sqpack")  # sqpack, folder, file
        self._game_path_var = tk.StringVar()
        self._selected_sqpack_sheet_var = tk.StringVar(value="(Tutti i fogli - Batch Completo)")
        self._input_folder_var = tk.StringVar()
        self._input_file_var = tk.StringVar()

        # Translator config
        self._backend_var = tk.StringVar(value="libretranslate")
        self._libre_url_var = tk.StringVar(value="https://translate.systemofagamer.it")
        self._deepl_key_var = tk.StringVar()
        self._source_lang_var = tk.StringVar(value="en")
        self._target_lang_var = tk.StringVar(value="it")

        # Output folder
        self._output_folder_var = tk.StringVar(value=str(Path.cwd() / "translated_output"))

        # Execution state
        self._is_cancelled = False
        self._is_running = False

        self._setup_styles()
        self._build_ui()
        self._auto_detect_game_folder()
        self._show_step(1)

        # Run background update check
        threading.Thread(target=self._check_updates_bg, daemon=True).start()

    def _auto_detect_game_folder(self):
        """Auto-detect standard FFXIV game / sqpack locations."""
        candidates = [
            Path(r"C:\Users\d.paolozzi\Documents\antigravity\beautiful-bose\sqpack"),
            Path(r"C:\Program Files (x86)\SquareEnix\FINAL FANTASY XIV - A Realm Reborn"),
            Path(r"C:\SquareEnix\FINAL FANTASY XIV - A Realm Reborn"),
            Path.cwd() / "sqpack",
            Path.cwd(),
        ]
        for c in candidates:
            if c.exists():
                if (c / "game" / "sqpack").exists():
                    self._game_path_var.set(str(c))
                    self._populate_sqpack_sheets_async()
                    return
                elif list(c.glob("*.index")) or list(c.glob("*.win32.index")):
                    self._game_path_var.set(str(c))
                    self._populate_sqpack_sheets_async()
                    return
                elif (c / "exd").exists() or (c / "ffxiv").exists():
                    self._game_path_var.set(str(c))
                    self._populate_sqpack_sheets_async()
                    return

    def _populate_sqpack_sheets_async(self):
        path_str = self._game_path_var.get().strip().strip('"')
        if not path_str or not hasattr(self, "_sqpack_sheet_cmb"):
            return

        def worker(target_path: str):
            if not Path(target_path).exists():
                return
            try:
                reader = SqPackReader.from_game_directory(Path(target_path))
                sheets = reader.list_exd_sheets()
                if sheets:
                    items = ["(Tutti i fogli - Batch Completo)"] + sorted(sheets)
                    self.after(0, lambda: self._sqpack_sheet_cmb.config(values=items))
            except Exception:
                pass

        threading.Thread(target=worker, args=(path_str,), daemon=True).start()

    def _setup_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", background=BG_DARK, foreground=TEXT_PRI)
        style.configure("TProgressbar", thickness=16, troughcolor=BG_MID, background=ACCENT, bordercolor=BG_MID)
        
        # High contrast combobox styling
        style.configure("TCombobox",
                        fieldbackground=BG_INPUT,
                        background=BG_INPUT,
                        foreground=TEXT_PRI,
                        arrowcolor=TEXT_PRI,
                        bordercolor=BORDER,
                        darkcolor=BG_INPUT,
                        lightcolor=BG_INPUT,
                        padding=6)
        style.map("TCombobox",
                  fieldbackground=[("readonly", BG_INPUT), ("focus", BG_INPUT)],
                  foreground=[("readonly", TEXT_PRI), ("focus", TEXT_PRI)],
                  selectbackground=[("readonly", ACCENT)])
        
        self.option_add("*TCombobox*Listbox.background", BG_INPUT)
        self.option_add("*TCombobox*Listbox.foreground", TEXT_PRI)
        self.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.option_add("*TCombobox*Listbox.selectForeground", TEXT_PRI)

    def _build_ui(self):
        # Header bar (Top)
        hdr = tk.Frame(self, bg=BG_MID, pady=10, padx=16)
        hdr.pack(fill="x", side="top")

        tk.Label(hdr, text="Interpresona", bg=BG_MID, fg=ACCENT_LIGHT, font=("Segoe UI", 16, "bold")).pack(side="left")
        tk.Label(hdr, text=" Wizard", bg=BG_MID, fg=TEXT_PRI, font=("Segoe UI", 16)).pack(side="left")
        tk.Label(hdr, text=f"v{__version__}", bg=BG_MID, fg=TEXT_DIM, font=FONT_SMALL).pack(side="left", padx=10, pady=4)

        # Advanced Mode Switch Button
        FlatButton(hdr, text="Modalità Avanzata ⚙", command=self._switch_to_advanced, accent=False).pack(side="right")

        # Top Stepper Bar (Top)
        self._stepper_frame = tk.Frame(self, bg=BG_DARK, pady=12)
        self._stepper_frame.pack(fill="x", side="top", padx=16)

        self._step_labels = []
        steps_info = [
            ("1", "Origine Dati"),
            ("2", "Traduttore"),
            ("3", "Destinazione"),
            ("4", "Esecuzione"),
        ]
        for i, (num, name) in enumerate(steps_info):
            lbl_frame = tk.Frame(self._stepper_frame, bg=BG_DARK)
            lbl_frame.pack(side="left", expand=True)

            circle = tk.Label(lbl_frame, text=num, bg=BG_CARD, fg=TEXT_SEC, font=("Segoe UI", 10, "bold"), width=3, height=1)
            circle.pack(side="left", padx=4)

            name_lbl = tk.Label(lbl_frame, text=name, bg=BG_DARK, fg=TEXT_SEC, font=FONT_BODY)
            name_lbl.pack(side="left", padx=4)

            self._step_labels.append((circle, name_lbl))

        # Bottom navigation bar - ALWAYS PINNED TO BOTTOM FIRST!
        nav_bar = tk.Frame(self, bg=BG_MID, pady=10, padx=16)
        nav_bar.pack(fill="x", side="bottom")

        self._btn_back = FlatButton(nav_bar, text="◀ Indietro", command=self._prev_step)
        self._btn_back.pack(side="left")

        self._btn_next = FlatButton(nav_bar, text="Avanti ▶", command=self._next_step, accent=True)
        self._btn_next.pack(side="right")

        # Main content card stack (Middle remaining space)
        self._card_container = tk.Frame(self, bg=BG_DARK, padx=16, pady=4)
        self._card_container.pack(fill="both", expand=True, side="top")

        # Create step cards
        self._card_step1 = self._build_step1_card()
        self._card_step2 = self._build_step2_card()
        self._card_step3 = self._build_step3_card()
        self._card_step4 = self._build_step4_card()

    def _create_entry(self, parent, variable, width=None, **kwargs) -> tk.Entry:
        e = tk.Entry(
            parent,
            textvariable=variable,
            width=width,
            bg=BG_INPUT,
            fg=TEXT_PRI,
            insertbackground=TEXT_PRI,
            font=FONT_BODY,
            bd=0,
            relief="flat",
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
            **kwargs
        )
        return e

    # ------------------------------------------------------------------
    # Step 1: Input Source Card (Custom Anti-Aliased Radio Cards)
    # ------------------------------------------------------------------
    def _build_step1_card(self) -> tk.Frame:
        card = tk.Frame(self._card_container, bg=BG_CARD, padx=20, pady=20, bd=1, highlightbackground=BORDER, highlightthickness=1)

        tk.Label(card, text="Passo 1: Scegli l'origine dei dati da tradurre", bg=BG_CARD, fg=ACCENT_LIGHT, font=FONT_HEAD).pack(anchor="w", pady=(0, 4))
        tk.Label(card, text="Seleziona la modalità di caricamento dei file di gioco o estratti:", bg=BG_CARD, fg=TEXT_SEC, font=FONT_BODY).pack(anchor="w", pady=(0, 16))

        self._opt_cards = {}

        # Option A: SQPACK Game Folder Card
        self._opt_cards["sqpack"] = self._create_option_card(
            card, key="sqpack",
            title="🎮 Cartella di Gioco FFXIV (SqPack completo)",
            subtitle="Traduce i file .exd leggendo gli archivi di gioco (tutti i fogli o uno specifico)",
            var=self._game_path_var,
            browse_cmd=self._browse_game_dir,
            has_sheet_selector=True
        )

        # Option B: Folder with EXH/EXD Files Card
        self._opt_cards["folder"] = self._create_option_card(
            card, key="folder",
            title="📂 Cartella di File Estratti (.exh / .exd)",
            subtitle="Traduce tutti i file .exd estratti presenti all'interno di una cartella locale sul tuo PC",
            var=self._input_folder_var,
            browse_cmd=self._browse_input_folder
        )

        # Option C: Single File Pair Card
        self._opt_cards["file"] = self._create_option_card(
            card, key="file",
            title="📄 Singolo File EXD",
            subtitle="Carica e traduce un singolo file .exd estratto accompagnato dal rispettivo .exh",
            var=self._input_file_var,
            browse_cmd=self._browse_input_file
        )

        self._update_step1_inputs()
        return card

    def _create_option_card(self, parent, key: str, title: str, subtitle: str, var: tk.StringVar, browse_cmd, has_sheet_selector=False) -> dict:
        frame = tk.Frame(parent, bg=BG_MID, padx=14, pady=12, bd=1, highlightbackground=BORDER, highlightthickness=1, cursor="hand2")
        frame.pack(fill="x", pady=6)

        hdr_line = tk.Frame(frame, bg=BG_MID, cursor="hand2")
        hdr_line.pack(fill="x")

        # Custom vector radio dot indicator
        dot_lbl = tk.Label(hdr_line, text="●", bg=BG_MID, fg=ACCENT_LIGHT, font=("Segoe UI", 12))
        dot_lbl.pack(side="left", padx=(0, 8))

        title_lbl = tk.Label(hdr_line, text=title, bg=BG_MID, fg=TEXT_PRI, font=FONT_SUB, cursor="hand2")
        title_lbl.pack(side="left")

        sub_lbl = tk.Label(frame, text=subtitle, bg=BG_MID, fg=TEXT_DIM, font=FONT_SMALL, cursor="hand2")
        sub_lbl.pack(anchor="w", padx=24, pady=(2, 8))

        entry_frame = tk.Frame(frame, bg=BG_MID)
        entry_frame.pack(fill="x", padx=24)

        entry = self._create_entry(entry_frame, variable=var)
        entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        btn = FlatButton(entry_frame, text="Sfoglia...", command=browse_cmd)
        btn.pack(side="right")

        sheet_sel_frame = None
        if has_sheet_selector:
            sheet_sel_frame = tk.Frame(frame, bg=BG_MID)
            sheet_sel_frame.pack(fill="x", padx=24, pady=(8, 0))

            tk.Label(sheet_sel_frame, text="Foglio specifico:", bg=BG_MID, fg=TEXT_SEC, font=FONT_BODY, cursor="hand2").pack(side="left", padx=(0, 8))
            self._sqpack_sheet_cmb = ttk.Combobox(
                sheet_sel_frame,
                textvariable=self._selected_sqpack_sheet_var,
                values=["(Tutti i fogli - Batch Completo)"],
                state="readonly",
                width=34
            )
            self._sqpack_sheet_cmb.pack(side="left")

        card_info = {
            "frame": frame,
            "dot": dot_lbl,
            "title": title_lbl,
            "sub": sub_lbl,
            "entry_frame": entry_frame,
            "hdr_line": hdr_line,
            "sheet_sel_frame": sheet_sel_frame,
        }

        def on_click(e=None):
            self._source_type.set(key)
            self._update_step1_inputs()

        bind_targets = [frame, hdr_line, title_lbl, sub_lbl, dot_lbl]
        if sheet_sel_frame:
            bind_targets.append(sheet_sel_frame)

        for w in bind_targets:
            w.bind("<Button-1>", on_click)

        return card_info

    def _update_step1_inputs(self):
        active_key = self._source_type.get()
        for key, card in self._opt_cards.items():
            is_active = (key == active_key)
            bg_col = BG_SELECT if is_active else BG_MID
            border_col = BORDER_SELECT if is_active else BORDER
            dot_col = ACCENT_LIGHT if is_active else TEXT_DIM
            dot_txt = "●" if is_active else "○"

            card["frame"].config(bg=bg_col, highlightbackground=border_col, highlightthickness=2 if is_active else 1)
            card["hdr_line"].config(bg=bg_col)
            card["entry_frame"].config(bg=bg_col)
            card["title"].config(bg=bg_col)
            card["sub"].config(bg=bg_col)
            card["dot"].config(bg=bg_col, fg=dot_col, text=dot_txt)
            if card.get("sheet_sel_frame"):
                card["sheet_sel_frame"].config(bg=bg_col)
                for child in card["sheet_sel_frame"].winfo_children():
                    if isinstance(child, tk.Label):
                        child.config(bg=bg_col)

    def _browse_game_dir(self):
        path = filedialog.askdirectory(title="Seleziona cartella di gioco FFXIV (o sqpack)")
        if path:
            self._game_path_var.set(path)
            self._source_type.set("sqpack")
            self._update_step1_inputs()
            self._populate_sqpack_sheets_async()

    def _browse_input_folder(self):
        path = filedialog.askdirectory(title="Seleziona cartella contenente i file .exh/.exd")
        if path:
            self._input_folder_var.set(path)
            self._source_type.set("folder")
            self._update_step1_inputs()

    def _browse_input_file(self):
        path = filedialog.askopenfilename(title="Seleziona file .exd", filetypes=[("FFXIV EXD Data", "*.exd"), ("Tutti i file", "*.*")])
        if path:
            self._input_file_var.set(path)
            self._source_type.set("file")
            self._update_step1_inputs()

    # ------------------------------------------------------------------
    # Step 2: Translation Service Setup Card
    # ------------------------------------------------------------------
    def _build_step2_card(self) -> tk.Frame:
        card = tk.Frame(self._card_container, bg=BG_CARD, padx=20, pady=20, bd=1, highlightbackground=BORDER, highlightthickness=1)

        tk.Label(card, text="Passo 2: Configura il servizio di Traduzione", bg=BG_CARD, fg=ACCENT_LIGHT, font=FONT_HEAD).pack(anchor="w", pady=(0, 4))
        tk.Label(card, text="Scegli il motore di traduzione e verifica che la connessione sia attiva:", bg=BG_CARD, fg=TEXT_SEC, font=FONT_BODY).pack(anchor="w", pady=(0, 16))

        # Backend Selector
        b_frame = tk.Frame(card, bg=BG_CARD)
        b_frame.pack(fill="x", pady=6)
        tk.Label(b_frame, text="Motore Traduzione:", bg=BG_CARD, fg=TEXT_PRI, font=FONT_SUB).pack(side="left", padx=(0, 10))

        cmb = ttk.Combobox(b_frame, textvariable=self._backend_var, values=["libretranslate", "deepl", "mock"], state="readonly", width=22)
        cmb.pack(side="left")
        cmb.bind("<<ComboboxSelected>>", lambda e: self._update_step2_backend())

        # Config Panel Frame
        self._cfg_panel = tk.Frame(card, bg=BG_MID, padx=16, pady=16, bd=1, highlightbackground=BORDER, highlightthickness=1)
        self._cfg_panel.pack(fill="x", pady=14)

        # LibreTranslate Fields
        self._libre_frame = tk.Frame(self._cfg_panel, bg=BG_MID)
        tk.Label(self._libre_frame, text="URL Server LibreTranslate:", bg=BG_MID, fg=TEXT_PRI, font=FONT_BODY).pack(anchor="w")
        self._create_entry(self._libre_frame, variable=self._libre_url_var).pack(fill="x", pady=(4, 8))
        tk.Label(self._libre_frame, text="Endpoint predefinito impostato su https://translate.systemofagamer.it", bg=BG_MID, fg=TEXT_DIM, font=FONT_SMALL).pack(anchor="w")

        # DeepL Fields
        self._deepl_frame = tk.Frame(self._cfg_panel, bg=BG_MID)
        tk.Label(self._deepl_frame, text="Chiave API DeepL (Authentication Key):", bg=BG_MID, fg=TEXT_PRI, font=FONT_BODY).pack(anchor="w")
        self._create_entry(self._deepl_frame, variable=self._deepl_key_var).pack(fill="x", pady=(4, 8))

        # Language selection
        lang_frame = tk.Frame(self._cfg_panel, bg=BG_MID)
        lang_frame.pack(fill="x", pady=(12, 0))

        tk.Label(lang_frame, text="Da Lingua:", bg=BG_MID, fg=TEXT_SEC, font=FONT_BODY).pack(side="left", padx=(0, 6))
        self._create_entry(lang_frame, variable=self._source_lang_var, width=6).pack(side="left", padx=(0, 20))

        tk.Label(lang_frame, text="A Lingua:", bg=BG_MID, fg=TEXT_SEC, font=FONT_BODY).pack(side="left", padx=(0, 6))
        self._create_entry(lang_frame, variable=self._target_lang_var, width=6).pack(side="left")

        # Test Connection Button
        test_frame = tk.Frame(card, bg=BG_CARD)
        test_frame.pack(fill="x", pady=10)

        FlatButton(test_frame, text="⚡ Testa Connessione Servizio", command=self._test_connection).pack(side="left")
        self._test_result_lbl = tk.Label(test_frame, text="", bg=BG_CARD, font=FONT_SUB)
        self._test_result_lbl.pack(side="left", padx=14)

        self._update_step2_backend()
        return card

    def _update_step2_backend(self):
        b = self._backend_var.get()
        self._libre_frame.pack_forget()
        self._deepl_frame.pack_forget()

        if b == "libretranslate":
            self._libre_frame.pack(fill="x", before=self._cfg_panel.winfo_children()[-1])
        elif b == "deepl":
            self._deepl_frame.pack(fill="x", before=self._cfg_panel.winfo_children()[-1])

    def _test_connection(self):
        self._test_result_lbl.config(text="Verifica in corso...", fg=WARNING)
        self.update()

        b = self._backend_var.get()
        url = self._libre_url_var.get()
        key = self._deepl_key_var.get()
        src = self._source_lang_var.get()
        tgt = self._target_lang_var.get()

        def do_test(b_val, url_val, key_val, src_val, tgt_val):
            try:
                if b_val == "libretranslate":
                    t = LibreTranslateTranslator(url=url_val, source_lang=src_val, target_lang=tgt_val)
                elif b_val == "deepl":
                    t = DeepLTranslator(api_key=key_val, source_lang=src_val, target_lang=tgt_val)
                else:
                    t = MockTranslator()

                res = t.translate(["Hello {0} world"])
                if res and res[0]:
                    self.after(0, lambda: self._test_result_lbl.config(text="✓ Connessione Riuscita!", fg=SUCCESS))
                else:
                    self.after(0, lambda: self._test_result_lbl.config(text="⚠ Nessun testo restituito", fg=WARNING))
            except Exception as exc:
                err_msg = str(exc)[:60]
                self.after(0, lambda: self._test_result_lbl.config(text=f"✖ Errore: {err_msg}", fg=ERROR_COL))

        threading.Thread(target=do_test, args=(b, url, key, src, tgt), daemon=True).start()

    # ------------------------------------------------------------------
    # Step 3: Destination Card
    # ------------------------------------------------------------------
    def _build_step3_card(self) -> tk.Frame:
        card = tk.Frame(self._card_container, bg=BG_CARD, padx=20, pady=20, bd=1, highlightbackground=BORDER, highlightthickness=1)

        tk.Label(card, text="Passo 3: Seleziona dove salvare i file tradotti", bg=BG_CARD, fg=ACCENT_LIGHT, font=FONT_HEAD).pack(anchor="w", pady=(0, 4))
        tk.Label(card, text="I file tradotti (.exd ed .exh) verranno salvati nella cartella specificata:", bg=BG_CARD, fg=TEXT_SEC, font=FONT_BODY).pack(anchor="w", pady=(0, 16))

        out_box = tk.Frame(card, bg=BG_MID, padx=16, pady=16, bd=1, highlightbackground=BORDER, highlightthickness=1)
        out_box.pack(fill="x", pady=10)

        tk.Label(out_box, text="Cartella di Destinazione Output:", bg=BG_MID, fg=TEXT_PRI, font=FONT_SUB).pack(anchor="w", pady=(0, 6))

        e_frame = tk.Frame(out_box, bg=BG_MID)
        e_frame.pack(fill="x")
        self._create_entry(e_frame, variable=self._output_folder_var).pack(side="left", fill="x", expand=True, padx=(0, 8))
        FlatButton(e_frame, text="Sfoglia...", command=self._browse_output_folder).pack(side="right")

        tk.Label(card, text="💡 Suggerimento: Puoi creare una nuova cartella qualsiasi per conservare i file tradotti pronti per il gioco.", bg=BG_CARD, fg=TEXT_DIM, font=FONT_SMALL).pack(anchor="w", pady=(20, 0))

        return card

    def _browse_output_folder(self):
        path = filedialog.askdirectory(title="Seleziona cartella di destinazione output")
        if path:
            self._output_folder_var.set(path)

    # ------------------------------------------------------------------
    # Step 4: Execution Progress Card
    # ------------------------------------------------------------------
    def _build_step4_card(self) -> tk.Frame:
        card = tk.Frame(self._card_container, bg=BG_CARD, padx=20, pady=20, bd=1, highlightbackground=BORDER, highlightthickness=1)

        tk.Label(card, text="Passo 4: Esecuzione e Stato Traduzione", bg=BG_CARD, fg=ACCENT_LIGHT, font=FONT_HEAD).pack(anchor="w", pady=(0, 4))
        self._exec_subtitle = tk.Label(card, text="Pronto per iniziare. Clicca su 'Avvia Traduzione' per cominciare.", bg=BG_CARD, fg=TEXT_SEC, font=FONT_BODY)
        self._exec_subtitle.pack(anchor="w", pady=(0, 12))

        # Progress bar + labels
        self._progress_bar = ttk.Progressbar(card, mode="determinate")
        self._progress_bar.pack(fill="x", pady=(4, 8))

        self._status_var = tk.StringVar(value="In attesa dell'avvio...")
        tk.Label(card, textvariable=self._status_var, bg=BG_CARD, fg=TEXT_PRI, font=FONT_SUB).pack(anchor="w", pady=(0, 10))

        # Control buttons bar during execution
        ctl_bar = tk.Frame(card, bg=BG_CARD)
        ctl_bar.pack(fill="x", pady=(0, 10))

        self._btn_start_exec = FlatButton(ctl_bar, text="🚀 Avvia Traduzione", command=self._start_execution, accent=True)
        self._btn_start_exec.pack(side="left")

        self._btn_stop_exec = FlatButton(ctl_bar, text="⏹ Interrompi", command=self._stop_execution, danger=True)
        self._btn_stop_exec.pack(side="left", padx=10)
        self._btn_stop_exec.config(state="disabled")

        self._btn_open_out = FlatButton(ctl_bar, text="📁 Apri Cartella Output", command=self._open_output_folder)
        self._btn_open_out.pack(side="right")
        self._btn_open_out.config(state="disabled")

        # Live log view
        tk.Label(card, text="Registro Eventi Traduzione:", bg=BG_CARD, fg=TEXT_SEC, font=FONT_SUB).pack(anchor="w", pady=(12, 4))
        self._log_text = scrolledtext.ScrolledText(card, bg=BG_INPUT, fg=TEXT_PRI, font=FONT_MONO, height=10, state="disabled", relief="flat", insertbackground=TEXT_PRI)
        self._log_text.pack(fill="both", expand=True)

        self._log_text.tag_config("info", foreground=TEXT_SEC)
        self._log_text.tag_config("success", foreground=SUCCESS)
        self._log_text.tag_config("warning", foreground=WARNING)
        self._log_text.tag_config("error", foreground=ERROR_COL)

        return card

    def _log(self, msg: str, level: str = "info"):
        self._log_text.config(state="normal")
        self._log_text.insert("end", msg + "\n", level)
        self._log_text.see("end")
        self._log_text.config(state="disabled")

    def _open_output_folder(self):
        out_dir = self._output_folder_var.get()
        if os.path.exists(out_dir):
            import webbrowser
            webbrowser.open(out_dir)

    # ------------------------------------------------------------------
    # Step Navigation Logic
    # ------------------------------------------------------------------
    def _show_step(self, step_num: int):
        self._current_step = step_num

        # Hide all step cards
        for card in (self._card_step1, self._card_step2, self._card_step3, self._card_step4):
            card.pack_forget()

        # Update step bar styling
        for idx, (circle, name_lbl) in enumerate(self._step_labels, start=1):
            if idx == step_num:
                circle.config(bg=ACCENT, fg=TEXT_PRI)
                name_lbl.config(fg=ACCENT_LIGHT, font=FONT_SUB)
            elif idx < step_num:
                circle.config(bg=SUCCESS, fg=TEXT_PRI)
                name_lbl.config(fg=TEXT_PRI, font=FONT_BODY)
            else:
                circle.config(bg=BG_CARD, fg=TEXT_SEC)
                name_lbl.config(fg=TEXT_SEC, font=FONT_BODY)

        # Show target card
        if step_num == 1:
            self._card_step1.pack(fill="both", expand=True)
            self._btn_back.config(state="disabled")
            self._btn_next.config(state="normal", text="Avanti ▶")
        elif step_num == 2:
            self._card_step2.pack(fill="both", expand=True)
            self._btn_back.config(state="normal")
            self._btn_next.config(state="normal", text="Avanti ▶")
        elif step_num == 3:
            self._card_step3.pack(fill="both", expand=True)
            self._btn_back.config(state="normal")
            self._btn_next.config(state="normal", text="Vai all'Esecuzione ▶")
        elif step_num == 4:
            self._card_step4.pack(fill="both", expand=True)
            self._btn_back.config(state="normal" if not self._is_running else "disabled")
            self._btn_next.config(state="disabled")

    def _next_step(self):
        if self._current_step == 1:
            game_path = self._game_path_var.get().strip().strip('"')
            folder_path = self._input_folder_var.get().strip().strip('"')
            file_path = self._input_file_var.get().strip().strip('"')

            st = self._source_type.get()

            # Auto-detect populated path if active option field is empty
            if st == "sqpack" and not game_path:
                if folder_path:
                    st = "folder"
                    self._source_type.set("folder")
                elif file_path:
                    st = "file"
                    self._source_type.set("file")
            elif st == "folder" and not folder_path:
                if game_path:
                    st = "sqpack"
                    self._source_type.set("sqpack")
                elif file_path:
                    st = "file"
                    self._source_type.set("file")
            elif st == "file" and not file_path:
                if game_path:
                    st = "sqpack"
                    self._source_type.set("sqpack")
                elif folder_path:
                    st = "folder"
                    self._source_type.set("folder")

            active_path = game_path if st == "sqpack" else (folder_path if st == "folder" else file_path)

            if not active_path:
                messagebox.showwarning("Attenzione", "Seleziona una cartella o un file valido prima di proseguire.")
                return

            if not Path(active_path).exists():
                messagebox.showerror("Errore Percorso", f"Il percorso selezionato non esiste sul tuo PC:\n\n{active_path}")
                return

            self._show_step(2)
        elif self._current_step == 2:
            b = self._backend_var.get()
            if b == "libretranslate" and not self._libre_url_var.get():
                messagebox.showwarning("Attenzione", "Inserisci l'URL del server LibreTranslate.")
                return
            elif b == "deepl" and not self._deepl_key_var.get():
                messagebox.showwarning("Attenzione", "Inserisci la chiave API DeepL.")
                return
            self._show_step(3)
        elif self._current_step == 3:
            if not self._output_folder_var.get():
                messagebox.showwarning("Attenzione", "Seleziona la cartella di destinazione output.")
                return
            self._show_step(4)

    def _prev_step(self):
        if self._current_step > 1 and not self._is_running:
            self._show_step(self._current_step - 1)

    # ------------------------------------------------------------------
    # Step 4 Execution Workflow
    # ------------------------------------------------------------------
    def _create_translator_instance(self) -> BaseTranslator:
        b = self._backend_var.get()
        src = self._source_lang_var.get().strip() or "en"
        tgt = self._target_lang_var.get().strip() or "it"

        if b == "libretranslate":
            url = self._libre_url_var.get().strip() or "https://translate.systemofagamer.it"
            return LibreTranslateTranslator(url=url, source_lang=src, target_lang=tgt)
        elif b == "deepl":
            key = self._deepl_key_var.get().strip()
            return DeepLTranslator(api_key=key, source_lang=src, target_lang=tgt)
        else:
            return MockTranslator()

    def _start_execution(self):
        if self._is_running:
            return

        self._is_running = True
        self._is_cancelled = False
        self._btn_start_exec.config(state="disabled")
        self._btn_stop_exec.config(state="normal")
        self._btn_open_out.config(state="disabled")
        self._btn_back.config(state="disabled")
        self._progress_bar["value"] = 0

        # Launch execution worker thread
        threading.Thread(target=self._worker_execute, daemon=True).start()

    def _stop_execution(self):
        if self._is_running:
            self._is_cancelled = True
            self._status_var.set("Interruzione in corso...")
            self._log("Richiesta di interruzione inviata dall'utente.", "warning")

    def _worker_execute(self):
        st = self._source_type.get()
        out_dir = Path(self._output_folder_var.get())
        out_dir.mkdir(parents=True, exist_ok=True)

        try:
            translator = self._create_translator_instance()
            self._log(f"Inizializzato motore {translator.name} ({self._source_lang_var.get()} ➔ {self._target_lang_var.get()})", "info")

            if st == "sqpack":
                self._execute_sqpack_batch(translator, out_dir)
            elif st == "folder":
                self._execute_folder_batch(translator, out_dir)
            else:
                self._execute_single_file(translator, out_dir)

            if not self._is_cancelled:
                self.after(0, lambda: self._status_var.set("✓ Traduzione completata con successo!"))
                self.after(0, lambda: self._log("Tutte le operazioni sono state completate.", "success"))
                self.after(0, lambda: self._btn_open_out.config(state="normal"))
        except Exception as exc:
            err_msg = str(exc)
            self.after(0, lambda: self._status_var.set(f"Errore: {err_msg[:60]}"))
            self.after(0, lambda: self._log(f"Errore durante l'esecuzione: {err_msg}", "error"))
        finally:
            self._is_running = False
            self.after(0, lambda: self._btn_start_exec.config(state="normal"))
            self.after(0, lambda: self._btn_stop_exec.config(state="disabled"))
            self.after(0, lambda: self._btn_back.config(state="normal"))

    def _execute_sqpack_batch(self, translator: BaseTranslator, out_dir: Path):
        game_path = Path(self._game_path_var.get())
        self._log(f"Lettura archivi SqPack da {game_path}...", "info")

        reader = SqPackReader.from_game_directory(game_path)
        all_sheets = reader.list_exd_sheets()

        sel_sheet = self._selected_sqpack_sheet_var.get().strip()
        if sel_sheet and not sel_sheet.startswith("("):
            sheets = [sel_sheet]
            self._log(f"Processamento foglio singolo selezionato: '{sel_sheet}'", "info")
        else:
            sheets = all_sheets
            self._log(f"Trovati {len(sheets)} fogli EXD da processare in batch.", "info")

        total_sheets = len(sheets)

        import re
        technical_key_pat = re.compile(r"^[A-Z][A-Z0-9_]{4,80}$")
        success_count = 0

        for idx, sheet_name in enumerate(sheets, start=1):
            if self._is_cancelled:
                self._log("Esecuzione interrotta dall'utente.", "warning")
                break

            self.after(0, lambda i=idx, tot=total_sheets, name=sheet_name: [
                self._progress_bar.config(value=int(i / tot * 100)),
                self._status_var.set(f"Processando foglio {i}/{tot}: {name}")
            ])

            exh_p = SqPackReader.exh_path(sheet_name)
            if not reader.file_exists(exh_p):
                continue

            try:
                exh_bytes = reader.read_file(exh_p)
                schema = EXHParser(exh_bytes).result

                exd_pages = []
                pages_to_check = schema.pages if schema.pages else [type("PageDef", (), {"start_row_id": 0})()]
                for p_def in pages_to_check:
                    page_id = getattr(p_def, "start_row_id", 0)
                    page_bytes = None
                    for candidate_lang in ("en", "ja", "de", "fr", ""):
                        c_path = SqPackReader.exd_path(sheet_name, page=page_id, lang=candidate_lang)
                        if reader.file_exists(c_path):
                            page_bytes = reader.read_file(c_path)
                            break
                    if page_bytes is not None:
                        exd_pages.append(page_bytes)

                if not exd_pages:
                    continue

                pipeline = TranslationPipeline(exh_bytes, exd_pages)
                records = pipeline.extract()

                targets = []
                for rec in records:
                    t_str = rec.masked_text.strip()
                    if technical_key_pat.match(t_str) or t_str.startswith("TEXT_") or t_str.startswith("KEY_"):
                        continue
                    if not rec.translated_text and not rec.errors:
                        targets.append(rec)

                if targets:
                    self._log(f"Foglio {sheet_name}: traduzione di {len(targets)} stringhe...", "info")
                    CHUNK = 10
                    for c_start in range(0, len(targets), CHUNK):
                        if self._is_cancelled:
                            break
                        chunk = targets[c_start: c_start + CHUNK]
                        texts = [r.masked_text for r in chunk]
                        try:
                            translated_list = translator.translate(texts)
                            for rec, trans in zip(chunk, translated_list):
                                ph_err = validate_placeholders(trans, rec.placeholders)
                                if not ph_err:
                                    rec.translated_text = trans
                        except Exception as chunk_exc:
                            self._log(f"Avviso blocco {c_start}/{len(targets)} su {sheet_name}: {chunk_exc}", "warning")

                # Save translated EXD/EXH to out_dir
                safe_name = sheet_name.replace("/", "_")
                page_data = pipeline.inject_all()
                for p_id, binary in page_data.items():
                    (out_dir / f"{safe_name}_{p_id}.exd").write_bytes(binary)
                (out_dir / f"{safe_name}.exh").write_bytes(exh_bytes)

                success_count += 1
            except Exception as exc:
                self._log(f"Errore su foglio {sheet_name}: {exc}", "error")

        self._log(f"Completati {success_count} fogli salvati in {out_dir}", "success")

    def _execute_folder_batch(self, translator: BaseTranslator, out_dir: Path):
        inp_dir = Path(self._input_folder_var.get())
        exh_files = list(inp_dir.glob("*.exh"))
        total = len(exh_files)
        self._log(f"Trovati {total} file .exh nella cartella.", "info")

        import re
        technical_key_pat = re.compile(r"^[A-Z][A-Z0-9_]{4,80}$")

        for idx, exh_file in enumerate(exh_files, start=1):
            if self._is_cancelled:
                break
            sheet_stem = exh_file.stem
            self.after(0, lambda i=idx, tot=total, s=sheet_stem: [
                self._progress_bar.config(value=int(i / tot * 100)),
                self._status_var.set(f"Processando {i}/{tot}: {s}")
            ])

            exd_files = sorted(inp_dir.glob(f"{sheet_stem}_*.exd"))
            if not exd_files:
                continue

            try:
                exh_bytes = exh_file.read_bytes()
                exd_pages = [f.read_bytes() for f in exd_files]
                pipeline = TranslationPipeline(exh_bytes, exd_pages)
                records = pipeline.extract()

                targets = []
                for rec in records:
                    t_str = rec.masked_text.strip()
                    if technical_key_pat.match(t_str) or t_str.startswith("TEXT_") or t_str.startswith("KEY_"):
                        continue
                    if not rec.translated_text and not rec.errors:
                        targets.append(rec)

                if targets:
                    self._log(f"File {sheet_stem}: traduzione di {len(targets)} stringhe...", "info")
                    CHUNK = 20
                    for c_start in range(0, len(targets), CHUNK):
                        if self._is_cancelled:
                            break
                        chunk = targets[c_start: c_start + CHUNK]
                        texts = [r.masked_text for r in chunk]
                        translated_list = translator.translate(texts)
                        for rec, trans in zip(chunk, translated_list):
                            ph_err = validate_placeholders(trans, rec.placeholders)
                            if not ph_err:
                                rec.translated_text = trans

                page_data = pipeline.inject_all()
                for page_id, binary in page_data.items():
                    (out_dir / f"{sheet_stem}_{page_id}.exd").write_bytes(binary)
                (out_dir / exh_file.name).write_bytes(exh_bytes)
            except Exception as exc:
                self._log(f"Errore su {sheet_stem}: {exc}", "error")

    def _execute_single_file(self, translator: BaseTranslator, out_dir: Path):
        exd_path = Path(self._input_file_var.get())
        sheet_stem = exd_path.stem.rsplit("_", 1)[0] if "_" in exd_path.stem else exd_path.stem
        exh_path = exd_path.parent / f"{sheet_stem}.exh"

        if not exh_path.exists():
            raise FileNotFoundError(f"File schema EXH non trovato in {exh_path}")

        self._log(f"Caricamento {exd_path.name} e {exh_path.name}...", "info")
        exh_bytes = exh_path.read_bytes()
        exd_bytes = exd_path.read_bytes()

        pipeline = TranslationPipeline(exh_bytes, [exd_bytes])
        records = pipeline.extract()

        targets = [r for r in records if r.masked_text.strip() and not r.translated_text and not r.errors]
        self._log(f"Estratte {len(targets)} stringhe traducibili.", "info")

        if targets:
            CHUNK = 20
            for c_start in range(0, len(targets), CHUNK):
                if self._is_cancelled:
                    break
                chunk = targets[c_start: c_start + CHUNK]
                texts = [r.masked_text for r in chunk]
                translated_list = translator.translate(texts)
                for rec, trans in zip(chunk, translated_list):
                    ph_err = validate_placeholders(trans, rec.placeholders)
                    if not ph_err:
                        rec.translated_text = trans

                pct = int((c_start + len(chunk)) / len(targets) * 100)
                self.after(0, lambda p=pct: self._progress_bar.config(value=p))

        page_data = pipeline.inject_all()
        binary = page_data.get(0, b"")
        (out_dir / exd_path.name).write_bytes(binary)
        (out_dir / exh_path.name).write_bytes(exh_bytes)
        self._log(f"Salvati {exd_path.name} e {exh_path.name} in {out_dir}", "success")

    # ------------------------------------------------------------------
    # Mode Switcher Helper
    # ------------------------------------------------------------------
    def _switch_to_advanced(self):
        self.destroy()
        from interpresona.gui import main as main_advanced
        main_advanced()

    def _check_updates_bg(self):
        try:
            url = "https://api.github.com/repos/Keyain-Zasky/Interpresona/releases/latest"
            req = urllib.request.Request(url, headers={"User-Agent": "Interpresona-SimpleWizard"})
            ctx = ssl._create_unverified_context()
            with urllib.request.urlopen(req, context=ctx, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                latest_tag = data.get("tag_name", "v0.0.0").lstrip("v")
                current_tag = __version__.lstrip("v")

                latest_parts = [int(x) for x in latest_tag.split(".") if x.isdigit()]
                current_parts = [int(x) for x in current_tag.split(".") if x.isdigit()]

                if latest_parts > current_parts:
                    self.after(500, lambda: messagebox.showinfo(
                        "Aggiornamento Disponibile",
                        f"È disponibile una nuova versione di Interpresona ({data.get('tag_name')}).\nVersione attuale: v{__version__}."
                    ))
        except Exception:
            pass


def main():
    app = InterpresonaSimpleApp()
    app.mainloop()


if __name__ == "__main__":
    main()
