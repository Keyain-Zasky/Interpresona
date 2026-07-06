# Interpresona — FFXIV Dialogue & Interface Text Translation Tool

Interpresona is a premium, high-performance desktop application designed for extracting, translating, and injecting Final Fantasy XIV (FFXIV) game sheets (`.exh` / `.exd` formats). Built entirely from scratch in Python with zero external execution dependencies, it guarantees absolute data preservation while maintaining FFXIV control codes, variables, and color formatting tags.

---

## Key Features

- **Dual-Mode Architecture**:
  - **Manual Mode**: Directly browse and open isolated `.exh`/`.exd` files extracted from third-party tools.
  - **SqPack Game Loader**: Point the application directly to your FFXIV game installation folder to automatically map and decompress active archives on the fly.
- **Smart Filter Pipeline**:
  - Automatically isolates translatable dialogue text, stripping away thousands of technical metadata files and internal technical keys (e.g. `TEXT_` and `KEY_` placeholders).
- **SeString-Safe Masking**:
  - Safely masks binary control codes (color changes, speaker identifiers, name variable lookups) into secure placeholders (like `⟪VAR_0⟫`) to prevent machine translation engines or manual edits from corrupting game files.
- **Flexible Exporter / Importer**:
  - Export extracted text to standard CSV formats for automated bulk processing (Google Translate, DeepL, LibreTranslate) and re-import them with a single click.
- **Integrated Machine Translation (MT)**:
  - Perform automated in-app translations using DeepL or LibreTranslate API keys.
- **Modern Premium Interface**:
  - High-fidelity dark mode with clean tab routing, search/filter bars, interactive custom pill buttons, and visual focus indicators.

---

## How It Works

```mermaid
graph TD
    A[SqPack Game Files / Manual EXH & EXD] --> B[EXD Parser]
    B --> C[SeString Masker]
    C --> D[Translatable Dialogue List]
    D --> E[In-App Inline Editor / CSV Bulk Export]
    E --> F[Machine Translation / Manual Editing]
    F --> G[SeString Unmasker]
    G --> H[EXD Injector]
    H --> I[Translated EXD Output]
.exd page data is rebuilt with new string pointers and original variable bytes preserved.
```

### 1. Parsing
The application reads the `.exh` schema to determine column offsets, row sizes, row depths, and whether the sheets contain sub-rows. It then decompresses the `.exd` file, resolves string pointers (including shifts in flat sheets and literal bytes in sub-row indices), and outputs a structured key-value dataset.

### 2. Masking
Any binary payload containing localized variables (like `0x02` control tags) is parsed into `⟪VAR_X⟫` markers. This protects internal macros from syntax corruption during translation.

### 3. Translation
You can translate text using:
* The **Inline Editor** at the bottom of the main interface (press `Enter` to save).
* The **Auto-Translate** tab with a configured API provider.
* Exporting/Importing CSV templates.

### 4. Injection
When saving, the injector recalculates the string table boundaries, builds new binary payloads, preserves all integer columns, and writes the output back into the FFXIV client page format.

---

## Installation & Running

This project uses `uv` as its Python package and environment manager.

1. **Clone the repository**:
   ```bash
   git clone https://github.com/Keyain-Zasky/Interpresona.git
   cd Interpresona
   ```

2. **Run the Application**:
   ```bash
   uv run python run_gui.py
   ```

3. **Run Unit Tests**:
   ```bash
   uv run python interpresona/tests/run_all_tests.py
   ```

---

## Project Structure

* [interpresona/gui.py](file:///C:/Users/d.paolozzi/Documents/antigravity/beautiful-bose/interpresona/gui.py) — Tkinter graphical interface, styling theme, and event binds.
* [interpresona/core/parser.py](file:///C:/Users/d.paolozzi/Documents/antigravity/beautiful-bose/interpresona/core/parser.py) — Low-level binary `.exh` and `.exd` data reader.
* [interpresona/core/injector.py](file:///C:/Users/d.paolozzi/Documents/antigravity/beautiful-bose/interpresona/core/injector.py) — Low-level binary writer and string offsets allocator.
* [interpresona/core/masker.py](file:///C:/Users/d.paolozzi/Documents/antigravity/beautiful-bose/interpresona/core/masker.py) — Safe-regex masking engine for FFXIV SeString control codes.
* [interpresona/core/sqpack.py](file:///C:/Users/d.paolozzi/Documents/antigravity/beautiful-bose/interpresona/core/sqpack.py) — Zlib reader for FFXIV retail `.index` and `.dat` archives.

---

## License

This project is licensed under the MIT License. See the [LICENSE](file:///C:/Users/d.paolozzi/Documents/antigravity/beautiful-bose/LICENSE) file for more details.
