"""Safe EXH/EXD reader, compiler and hard injector for FFXIV SQPACK.

The important invariant is that compilation starts from the original EXD fixed
data.  CSV is a translation view; it is not treated as a complete replacement
for the binary schema.
"""

import binascii
import csv
import json
import os
import re
import shutil
import struct
import zlib

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CODE_DIR = PROJECT_DIR
# The Codex copy must never write CSV/EXD output into the original project.
PENUMBRA_DIR = os.path.join(PROJECT_DIR, "runtime")
SETTINGS_PATH = os.path.join(PROJECT_DIR, "settings.json")
LEGACY_SETTINGS_PATH = os.path.join(PENUMBRA_DIR, "settings.json")
USER_SETTINGS_PATH = os.path.join(os.path.expanduser("~"), ".config", "ffxiv-zero-error-translator", "settings.json")
DEFAULT_GAME_DIR = "/home/keyain/.local/share/Steam/steamapps/common/FINAL FANTASY XIV Online/game/sqpack/ffxiv"
DEFAULT_PROJECT_HOME = PROJECT_DIR
DEFAULT_TEST_DIR = "/home/keyain/Documents/Interpresona/tRad/Traduzione/workspace"
# Read-only compatibility source for CSVs produced by the previous exporter.
LEGACY_WORKSPACE_DIR = "/home/keyain/Documents/Interpresona/tRad/Traduzione/workspace"
RAWEXD_DIR = "/home/keyain/Documents/antigravity/beautiful-bose/FFXIVChnTextPatch-GP-Original/resource/rawexd"
CATALOG_FILE = os.path.join(PROJECT_DIR, "app", "ffxiv_sheets.txt")
BUILTIN_SHEETS = ("addon", "lobby", "item", "quest", "eventtext", "weather", "customtalk")
_SHEET_CATALOG_CACHE = None


def _read_settings():
    for path in (USER_SETTINGS_PATH, SETTINGS_PATH, LEGACY_SETTINGS_PATH):
        try:
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
                if isinstance(data, dict):
                    return data
        except (OSError, json.JSONDecodeError):
            pass
    return {}


def _migrate_settings(data):
    """Accept the previous four-path format while exposing only three paths."""
    if data.get("game_dir") and data.get("project_dir") and data.get("test_dir"):
        return data
    return {
        "game_dir": data.get("sqpack_dir", DEFAULT_GAME_DIR),
        "project_dir": data.get("project_dir", DEFAULT_PROJECT_HOME),
        "test_dir": data.get("test_dir", data.get("csv_source_dir", DEFAULT_TEST_DIR)),
    }


def _project_paths(project_home):
    data_dir = os.path.join(project_home, "data")
    return {
        "csv": os.path.join(data_dir, "csv", "current"),
        "exd": os.path.join(data_dir, "exd", "current"),
        "sqpack_backup": os.path.join(data_dir, "backup", "sqpack"),
        "csv_backup": os.path.join(data_dir, "backup", "csv"),
        "exd_backup": os.path.join(data_dir, "backup", "exd"),
        "export": os.path.join(project_home, "export"),
        "import_history": os.path.join(project_home, "history", "import"),
        "export_history": os.path.join(project_home, "history", "export"),
    }


def _configure_paths(values):
    global SQPACK_DIR, GAME_DIR, TEST_DIR, PROJECT_HOME, CSV_SOURCE_DIR
    global WORKSPACE_DIR, EXD_DIR, BACKUP_SQPACK_DIR, BACKUP_CSV_DIR
    global BACKUP_EXD_DIR, EXPORT_DIR, IMPORT_HISTORY_DIR, EXPORT_HISTORY_DIR, ISSUES_DB
    global INDEX_PATH, CATALOG_DIRS, _SHEET_CATALOG_CACHE
    settings = _migrate_settings(values)
    GAME_DIR = os.path.abspath(os.path.expanduser(str(settings["game_dir"]).strip()))
    PROJECT_HOME = os.path.abspath(os.path.expanduser(str(settings["project_dir"]).strip()))
    TEST_DIR = os.path.abspath(os.path.expanduser(str(settings["test_dir"]).strip()))
    if not GAME_DIR or not PROJECT_HOME or not TEST_DIR:
        raise ValueError("I tre percorsi sono obbligatori.")
    SQPACK_DIR = GAME_DIR
    CSV_SOURCE_DIR = TEST_DIR  # alias interno per compatibilità con gli endpoint esistenti
    paths = _project_paths(PROJECT_HOME)
    WORKSPACE_DIR = paths["csv"]
    EXD_DIR = paths["exd"]
    BACKUP_SQPACK_DIR = paths["sqpack_backup"]
    BACKUP_CSV_DIR = paths["csv_backup"]
    BACKUP_EXD_DIR = paths["exd_backup"]
    EXPORT_DIR = paths["export"]
    IMPORT_HISTORY_DIR = paths["import_history"]
    EXPORT_HISTORY_DIR = paths["export_history"]
    ISSUES_DB = os.path.join(PROJECT_HOME, "data", "issues.sqlite3")
    INDEX_PATH = os.path.join(SQPACK_DIR, "0a0000.win32.index")
    CATALOG_DIRS = (RAWEXD_DIR, TEST_DIR, LEGACY_WORKSPACE_DIR, WORKSPACE_DIR)
    os.makedirs(TEST_DIR, exist_ok=True)
    for directory in (WORKSPACE_DIR, EXD_DIR, BACKUP_SQPACK_DIR, BACKUP_CSV_DIR,
                      BACKUP_EXD_DIR, EXPORT_DIR, IMPORT_HISTORY_DIR,
                      EXPORT_HISTORY_DIR):
        os.makedirs(directory, exist_ok=True)
    _SHEET_CATALOG_CACHE = None


_saved_settings = _read_settings()
_configure_paths(_saved_settings)


def settings_snapshot():
    storage = storage_snapshot()
    return {"game_dir": GAME_DIR, "project_dir": PROJECT_HOME, "test_dir": TEST_DIR,
            "workspace_dir": WORKSPACE_DIR, "exd_dir": EXD_DIR,
            "export_dir": EXPORT_DIR, "backup_dir": BACKUP_SQPACK_DIR,
            "history_import_dir": IMPORT_HISTORY_DIR,
            "history_export_dir": EXPORT_HISTORY_DIR,
            "sqpack_ok": os.path.exists(INDEX_PATH),
            "test_ok": os.path.isdir(TEST_DIR),
            "workspace_ok": os.path.isdir(WORKSPACE_DIR),
            "exd_ok": os.path.isdir(EXD_DIR) and os.access(EXD_DIR, os.W_OK),
            "history": storage}


def apply_settings(values):
    _configure_paths(values)
    os.makedirs(os.path.dirname(USER_SETTINGS_PATH), exist_ok=True)
    with open(USER_SETTINGS_PATH, "w", encoding="utf-8") as handle:
        json.dump({"game_dir": GAME_DIR, "project_dir": PROJECT_HOME,
                   "test_dir": TEST_DIR}, handle, indent=2)
    return settings_snapshot()


def _timestamp():
    from datetime import datetime
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")


def new_history_dir(kind):
    # Exports live in the dedicated project/export area; imports live in the
    # explicit import history area. Both operations receive a unique folder.
    base = IMPORT_HISTORY_DIR if kind == "import" else EXPORT_DIR
    path = os.path.join(base, _timestamp())
    os.makedirs(path, exist_ok=False)
    return path


def storage_snapshot():
    def count_files(root):
        total = 0
        snapshots = 0
        try:
            snapshots = sum(1 for entry in os.scandir(root) if entry.is_dir())
            for current, _, files in os.walk(root):
                total += len(files)
        except OSError:
            pass
        return snapshots, total
    import_snapshots, import_files = count_files(IMPORT_HISTORY_DIR)
    export_snapshots, export_files = count_files(EXPORT_DIR)
    return {"import_snapshots": import_snapshots, "export_snapshots": export_snapshots,
            "files": import_files + export_files,
            "warning": import_files + export_files > 10 or import_snapshots + export_snapshots > 10}


def snapshot_current_data():
    """Keep a recoverable copy of the current CSV/EXD working state."""
    stamp = _timestamp()
    csv_dir = os.path.join(BACKUP_CSV_DIR, stamp)
    exd_dir = os.path.join(BACKUP_EXD_DIR, stamp)
    os.makedirs(csv_dir, exist_ok=False)
    os.makedirs(exd_dir, exist_ok=False)
    for source_dir, destination_dir, pattern in ((WORKSPACE_DIR, csv_dir, "*.csv"),
                                                  (EXD_DIR, exd_dir, "*.exd")):
        for source in __import__("glob").glob(os.path.join(source_dir, pattern)):
            shutil.copy2(source, os.path.join(destination_dir, os.path.basename(source)))
    return {"csv": csv_dir, "exd": exd_dir}


def csv_byte_audit(name, content):
    """Compare an incoming CSV with the best local original baseline.

    This is an early warning only: the authoritative byte measurement remains
    the EXD audit performed by compile_exd and hard_inject_sqpack.
    """
    stem = name.lower().replace(".csv", "")
    candidates = (f"{stem}_original.csv", f"{stem}_en.csv", f"{stem}.csv")
    baseline = next((os.path.join(WORKSPACE_DIR, candidate)
                     for candidate in candidates
                     if os.path.isfile(os.path.join(WORKSPACE_DIR, candidate))), None)
    translated_bytes = len(content)
    original_bytes = os.path.getsize(baseline) if baseline else None
    delta = translated_bytes - original_bytes if original_bytes is not None else None
    return {
        "file": f"{stem}.csv",
        "baseline": baseline,
        "original_bytes": original_bytes,
        "translated_bytes": translated_bytes,
        "delta_bytes": delta,
        "changed": delta not in (None, 0),
        "warning": (f"CSV più grande di {delta:+d} byte rispetto all'originale: il rischio reale va verificato dopo la compilazione EXD."
                    if delta and delta > 0 else
                    (f"CSV più piccolo di {abs(delta)} byte rispetto all'originale."
                     if delta and delta < 0 else
                     ("Nessun confronto CSV disponibile: compilare l'EXD per ottenere l'audit reale."
                      if delta is None else "")))
    }

FOLDER_HASH = binascii.crc32(b"exd") ^ 0xFFFFFFFF
TYPE_WIDTH = {0x00: 4, 0x01: 1, 0x02: 1, 0x03: 1, 0x04: 2,
              0x05: 2, 0x06: 4, 0x07: 4, 0x09: 4}


def crc32_lower(value):
    return binascii.crc32(value.encode("utf-8").lower()) ^ 0xFFFFFFFF


def get_file_offset(file_name, index_path=None):
    wanted = crc32_lower(file_name)
    index_path = index_path or INDEX_PATH
    try:
        with open(index_path, "rb") as f:
            f.seek(1032)
            table_offset, table_size = struct.unpack("<II", f.read(8))
            f.seek(table_offset)
            for _ in range(table_size // 16):
                name_hash, folder_hash, raw_offset, _ = struct.unpack("<IIII", f.read(16))
                if name_hash == wanted and folder_hash == FOLDER_HASH:
                    return (raw_offset & 0x0F) >> 1, (raw_offset & 0xFFFFFFF0) * 8
    except (OSError, struct.error):
        pass
    return None, None


def extract_file(dat_idx, offset, sqpack_dir=None, dat_suffix=""):
    """Extract a type-2 SQPACK entry and reject truncated/corrupt entries."""
    if dat_idx is None or offset is None:
        return None
    path = os.path.join(sqpack_dir or SQPACK_DIR, f"0a0000.win32.dat{dat_idx}{dat_suffix}")
    try:
        with open(path, "rb") as dat:
            dat.seek(offset)
            header = dat.read(12)
            if len(header) != 12:
                return None
            header_len, entry_type, expected_size = struct.unpack("<III", header)
            if entry_type != 2 or header_len < 24 or header_len % 8:
                return None
            dat.seek(offset + 0x14)
            raw = dat.read(4)
            if len(raw) != 4:
                return None
            block_count = struct.unpack("<I", raw)[0]
            dat.seek(offset + 0x18)
            infos = [struct.unpack("<IHH", dat.read(8)) for _ in range(block_count)]
            result = bytearray()
            for block_offset, _, _ in infos:
                dat.seek(offset + header_len + block_offset)
                bh = dat.read(16)
                if len(bh) != 16:
                    return None
                _, _, compressed_size, uncompressed_size = struct.unpack("<IIII", bh)
                compressed = dat.read(compressed_size)
                if len(compressed) != compressed_size:
                    return None
                if compressed_size >= 32000 or compressed_size >= uncompressed_size:
                    result.extend(compressed[:uncompressed_size])
                else:
                    try:
                        if compressed[:2] in (b"\x78\x9c", b"\x78\xda", b"\x78\x01"):
                            result.extend(zlib.decompress(compressed))
                        else:
                            result.extend(zlib.decompress(compressed, -15))
                    except zlib.error:
                        return None
            if len(result) != expected_size:
                return None
            return result
    except (OSError, struct.error):
        return None


def read_file(file_name, sqpack_dir=None, index_path=None, dat_suffix=""):
    return extract_file(*get_file_offset(file_name, index_path),
                        sqpack_dir=sqpack_dir, dat_suffix=dat_suffix)


def read_backup_file(file_name):
    """Read an original EXH/EXD from the project's immutable SQPACK backup."""
    backup_index = os.path.join(BACKUP_SQPACK_DIR, "0a0000.win32.index.bak")
    return read_file(file_name, BACKUP_SQPACK_DIR, backup_index, ".bak")


def available_exh_names():
    """Return known sheet names that actually exist in the current SQPACK.

    SQPACK stores hashes, not path strings, so a complete human-readable list
    requires an external sheet-name catalogue.  We combine the UI defaults,
    local rawexd catalogues and existing workspaces, then verify each EXH hash.
    """
    candidates = set(BUILTIN_SHEETS)
    try:
        with open(CATALOG_FILE, encoding="utf-8") as catalog:
            candidates.update(line.strip().lower() for line in catalog
                              if line.strip() and not line.startswith("#"))
    except OSError:
        pass
    for directory in CATALOG_DIRS + (WORKSPACE_DIR,):
        try:
            for entry in os.scandir(directory):
                stem, ext = os.path.splitext(entry.name)
                if ext.lower() in (".csv", ".exh") and stem:
                    candidates.add(stem.lower())
        except OSError:
            continue
    return sorted(name for name in candidates if get_file_offset(name + ".exh")[0] is not None)


def sheet_catalog():
    """Build the UI catalog with schema metadata, cached for the process."""
    global _SHEET_CATALOG_CACHE
    if _SHEET_CATALOG_CACHE is not None:
        return _SHEET_CATALOG_CACHE
    catalog = []
    for name in available_exh_names():
        try:
            schema = parse_exh(read_file(name + ".exh"))
            has_text = any(typ == 0 for typ, _ in schema["columns"])
            if not has_text:
                continue
            category = translation_category(name)
            catalog.append({"name": name, "category": category,
                            "variant": schema["variant"],
                            "pages": schema["page_count"],
                            "columns": schema["column_count"],
                            "rows": struct.unpack(">I", read_file(name + ".exh")[20:24])[0],
                            "has_text": has_text})
        except (ValueError, struct.error, TypeError):
            continue
    _SHEET_CATALOG_CACHE = catalog
    return catalog


def translation_category(name):
    """Human-oriented translation groups, applied only to text-bearing EXH."""
    n = name.lower()
    rules = (
        ("Interfaccia", ("addon", "lobby", "hud", "uicolor", "uiconst", "uilookup", "loading", "chatbubble")),
        ("GUI", ("ui", "menu", "guide", "howto", "tutorial", "tooltip", "command", "log", "status", "icon", "pointmenu", "window")),
        ("Dialoghi", ("talk", "text", "story", "cutscene", "subtitle", "dialog", "yell", "scenario", "event", "battle")),
        ("Oggetti", ("item", "weapon", "armor", "equip", "materia", "recipe", "furniture", "housing", "mount", "minion", "ornament", "stain", "treasure", "shop", "food")),
        ("Missioni", ("quest", "journal", "leve", "achievement", "fate", "hunt", "challenge", "guildorder", "duty")),
        ("Personaggi e NPC", ("npc", "chara", "character", "resident", "race", "tribe", "classjob", "companion", "emote", "face")),
        ("Mondo e luoghi", ("place", "territory", "map", "zone", "weather", "world", "aetheryte", "town", "region")),
    )
    for category, prefixes in rules:
        if any(token in n for token in prefixes):
            return category
    return "Sistema"


def parse_exh(data):
    if not data or data[:4] != b"EXHF" or len(data) < 32:
        raise ValueError("EXH non valido")
    row_size, column_count, page_count, language_count = struct.unpack(">HHHH", data[6:14])
    variant = data[17]
    columns = [struct.unpack(">HH", data[32 + i * 4:36 + i * 4])
               for i in range(column_count)]
    page_base = 32 + column_count * 4
    pages = [struct.unpack(">II", data[page_base + i * 8:page_base + i * 8 + 8])
             for i in range(page_count)]
    return {"row_size": row_size, "column_count": column_count,
            "page_count": page_count, "language_count": language_count,
            "variant": variant, "columns": columns, "pages": pages}


def _row_records(exd, schema):
    if not exd or exd[:4] != b"EXDF" or len(exd) < 32:
        raise ValueError("EXD non valido")
    index_size, _ = struct.unpack(">II", exd[8:16])
    if 32 + index_size > len(exd) or index_size % 8:
        raise ValueError("Indice EXD non valido")
    records = []
    variant = schema["variant"]
    row_size = schema["row_size"]
    for pos in range(32, 32 + index_size, 8):
        row_id, row_offset = struct.unpack(">II", exd[pos:pos + 8])
        payload_size, sub_count = struct.unpack(">IH", exd[row_offset:row_offset + 6])
        end = row_offset + 6 + payload_size
        if end > len(exd):
            raise ValueError("Riga EXD oltre la fine del file")
        cursor = row_offset + 6
        subs = []
        for sub_index in range(sub_count):
            sub_id = None
            if variant == 2:
                sub_id = struct.unpack(">H", exd[cursor:cursor + 2])[0]
                cursor += 2
            fixed = bytes(exd[cursor:cursor + row_size])
            if len(fixed) != row_size:
                raise ValueError("Fixed data EXD troncato")
            subs.append({"sub_id": sub_id, "index": sub_index,
                         "fixed": fixed})
            cursor += row_size
        pool_start = cursor
        records.append({"row_id": row_id, "offset": row_offset,
                        "payload_size": payload_size, "sub_count": sub_count,
                        "subs": subs, "pool_start": pool_start,
                        "pool_end": end})
    return records


def _field_width(columns, index, row_size):
    typ = columns[index][0]
    if typ in TYPE_WIDTH:
        return TYPE_WIDTH[typ]
    start = columns[index][1]
    following = [off for _, off in columns[index + 1:] if off > start]
    return max(1, min(following + [row_size]) - start)


def _decode_value(fixed, columns, index):
    typ, offset = columns[index]
    width = _field_width(columns, index, len(fixed))
    raw = fixed[offset:offset + width]
    if typ == 0x00:
        return None
    if typ == 0x01 or 0x19 <= typ <= 0x20:
        return str(bool(raw[0] & (1 << (typ - 0x19))) if typ >= 0x19 else bool(raw[0]))
    formats = {0x02: ">b", 0x03: ">B", 0x04: ">h", 0x05: ">H",
               0x06: ">i", 0x07: ">I", 0x09: ">f"}
    if typ in formats:
        return str(struct.unpack(formats[typ], raw[:TYPE_WIDTH[typ]])[0])
    return "@HEX:" + raw.hex().upper()


def _read_tag(data, start):
    """Return (tag bytes, next position), or None for an invalid control."""
    if start + 3 > len(data) or data[start] != 2:
        return None
    pos = start + 2
    marker = data[pos]
    pos += 1
    if marker < 0xF0:
        length = marker
    elif marker == 0xF0 and pos < len(data):
        length = data[pos]; pos += 1
    elif marker == 0xF2 and pos + 2 <= len(data):
        length = int.from_bytes(data[pos:pos + 2], "big"); pos += 2
    elif marker == 0xFA and pos + 3 <= len(data):
        length = int.from_bytes(data[pos:pos + 3], "big"); pos += 3
    elif marker == 0xFE and pos + 4 <= len(data):
        length = int.from_bytes(data[pos:pos + 4], "big"); pos += 4
    else:
        return None
    end = pos + length
    if end > len(data) or end <= start or data[end - 1] != 3:
        return None
    return bytes(data[start:end]), end


def parse_sestring(buffer, start_idx, tag_dict, tag_reverse, counter):
    out = []
    idx = start_idx
    while idx < len(buffer) and buffer[idx] != 0:
        if buffer[idx] == 2:
            parsed = _read_tag(buffer, idx)
            if parsed:
                tag, idx = parsed
            else:
                end = buffer.find(b"\x00", idx)
                end = len(buffer) if end < 0 else end
                tag, idx = bytes(buffer[idx:end]), end
            key = tag.hex().upper()
            if key not in tag_reverse:
                tag_reverse[key] = counter[0]
                tag_dict[str(counter[0])] = key
                counter[0] += 1
            out.append("{" + str(tag_reverse[key]) + "}")
        else:
            end = idx
            while end < len(buffer) and buffer[end] not in (0, 2):
                end += 1
            try:
                out.append(bytes(buffer[idx:end]).decode("utf-8"))
            except UnicodeDecodeError:
                raw = bytes(buffer[idx:end])
                key = raw.hex().upper()
                if key not in tag_reverse:
                    tag_reverse[key] = counter[0]
                    tag_dict[str(counter[0])] = key
                    counter[0] += 1
                out.append("{" + str(tag_reverse[key]) + "}")
            idx = end
    return "".join(out)


def _string_value(exd, record, fixed, columns, index, tags, reverse, counter):
    offset = columns[index][1]
    relative = struct.unpack(">I", fixed[offset:offset + 4])[0]
    return parse_sestring(exd, record["pool_start"] + relative,
                          tags, reverse, counter)


def _raw_string(exd, record, fixed, columns, index):
    """Return the original NUL-terminated SeString bytes unchanged."""
    offset = columns[index][1]
    relative = struct.unpack(">I", fixed[offset:offset + 4])[0]
    start = record["pool_start"] + relative
    end = exd.find(b"\x00", start, record["pool_end"])
    return bytes(exd[start:record["pool_end"] if end < 0 else end + 1])


def get_tags_dict_path(exh_name):
    return os.path.join(WORKSPACE_DIR, f"{exh_name}_tags.json")


def get_meta_path(exh_name):
    return os.path.join(WORKSPACE_DIR, f"{exh_name}_meta.json")


def _page_files(name, schema):
    result = []
    for start_id, row_count in schema["pages"]:
        candidates = [f"{name}_{start_id}_en.exd", f"{name}_{start_id}.exd"]
        for candidate in candidates:
            data = read_file(candidate)
            if data:
                result.append((start_id, row_count, candidate, data))
                break
    return result


def export_exh(exh_name, output_dir=None):
    name = exh_name.lower().replace(".exh", "")
    exh = read_file(f"{name}.exh")
    if not exh:
        return {"error": f"File {name}.exh non trovato nell'indice."}
    try:
        schema = parse_exh(exh)
        pages = _page_files(name, schema)
        tags, reverse, counter, rows, meta = {}, {}, [1], [], []
        for _, _, file_name, exd in pages:
            records = _row_records(exd, schema)
            for record in records:
                for sub in record["subs"]:
                    values = [record["row_id"]]
                    if schema["variant"] == 2:
                        values.append(sub["sub_id"])
                    for col_index, (typ, _) in enumerate(schema["columns"]):
                        if typ == 0:
                            values.append(_string_value(exd, record, sub["fixed"], schema["columns"], col_index, tags, reverse, counter))
                        else:
                            values.append(_decode_value(sub["fixed"], schema["columns"], col_index))
                    rows.append(values)
                    meta.append({"file": file_name, "row_id": record["row_id"],
                                 "sub_id": sub["sub_id"], "fixed": sub["fixed"].hex().upper()})
        output_dir = output_dir or new_history_dir("export")
        os.makedirs(output_dir, exist_ok=True)
        with open(os.path.join(output_dir, f"{name}.csv"), "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            header = ["RowID"] + (["SubrowID"] if schema["variant"] == 2 else []) + [f"Col_{i}" for i in range(schema["column_count"])]
            writer.writerow(header); writer.writerows(rows)
        with open(os.path.join(output_dir, f"{name}_tags.json"), "w") as f: json.dump(tags, f, indent=2)
        with open(os.path.join(output_dir, f"{name}_meta.json"), "w") as f: json.dump({"schema": schema, "rows": meta}, f, indent=2)
        return {"success": True, "rows": len(rows), "tags": len(tags),
                "file": os.path.join(output_dir, f"{name}.csv"),
                "history_dir": output_dir, "pages": len(pages), "variant": schema["variant"]}
    except (ValueError, struct.error, OSError) as exc:
        return {"error": f"Errore EXH/EXD durante l'estrazione: {exc}"}


def compile_sestring(text, tag_dict):
    if not text:
        return bytearray(b"\x00")
    out = bytearray()
    for part in re.split(r"(\{[0-9]+\})", text):
        if re.fullmatch(r"\{[0-9]+\}", part) and part[1:-1] in tag_dict:
            out.extend(bytes.fromhex(tag_dict[part[1:-1]]))
        else:
            out.extend(part.encode("utf-8"))
    out.append(0)
    return out


def _legacy_tag_aliases(name, schema, csv_rows, meta_rows):
    """Match placeholder numbers from older CSV exports to current tag bytes.

    Older exporters could assign different numbers to the same SeString tag.
    The bytes are the real identity, so align the old CSV with the untouched
    EXD source and use the current raw tag bytes when compiling.
    """
    source_tags, reverse, counter = {}, {}, [1]
    source_values = {}
    for _, _, file_name, exd in _page_files(name, schema):
        for record in _row_records(exd, schema):
            for sub in record["subs"]:
                key = (record["row_id"], sub["sub_id"])
                values = {}
                for col_index, (typ, _) in enumerate(schema["columns"]):
                    if typ == 0:
                        values[col_index] = _string_value(
                            exd, record, sub["fixed"], schema["columns"],
                            col_index, source_tags, reverse, counter)
                source_values[key] = values

    aliases = {}
    conflicts = set()
    first = 2 if schema["variant"] == 2 else 1
    for row, meta in zip(csv_rows, meta_rows):
        source = source_values.get((int(meta["row_id"]), meta["sub_id"]), {})
        for col_index, (typ, _) in enumerate(schema["columns"]):
            if typ != 0 or first + col_index >= len(row):
                continue
            old_tokens = re.findall(r"\{(\d+)\}", row[first + col_index])
            current_tokens = re.findall(r"\{(\d+)\}", source.get(col_index, ""))
            if len(old_tokens) != len(current_tokens):
                continue
            for old_id, current_id in zip(old_tokens, current_tokens):
                raw = source_tags.get(current_id)
                if raw is None:
                    continue
                if old_id in aliases and aliases[old_id] != raw:
                    conflicts.add(old_id)
                else:
                    aliases[old_id] = raw
    for key in conflicts:
        aliases.pop(key, None)
    return aliases


def _encode_value(fixed, columns, index, value):
    typ, offset = columns[index]
    if value is None or value == "":
        return
    if typ == 0x00:
        return
    if typ == 0x01:
        fixed[offset] = 1 if str(value).lower() in ("1", "true", "yes") else 0
        return
    if 0x19 <= typ <= 0x20:
        mask = 1 << (typ - 0x19)
        if str(value).lower() in ("1", "true", "yes"):
            fixed[offset] |= mask
        else:
            fixed[offset] &= ~mask
        return
    if str(value).startswith("@HEX:"):
        raw = bytes.fromhex(str(value)[5:]); fixed[offset:offset + len(raw)] = raw; return
    formats = {0x02: ">b", 0x03: ">B", 0x04: ">h", 0x05: ">H", 0x06: ">i", 0x07: ">I", 0x09: ">f"}
    if typ in formats:
        struct.pack_into(formats[typ], fixed, offset, float(value) if typ == 0x09 else int(value))


def _compile_page(exd, schema, csv_values, tags):
    records = _row_records(exd, schema)
    data_rows, index = bytearray(), []
    for record in records:
        rendered_subs, pool = [], bytearray()
        for sub in record["subs"]:
            key = (record["row_id"], sub["sub_id"])
            values = csv_values.get(key, {})
            fixed = bytearray(sub["fixed"])
            for col_index, (typ, offset) in enumerate(schema["columns"]):
                if typ == 0:
                    text = values.get(col_index)
                    original_string = _raw_string(exd, record, fixed, schema["columns"], col_index)
                    # Empty strings in the shipped EXD are meaningful
                    # sentinels for optional fields (notably Item row 0 and
                    # a few sparse item records). Never turn such a field
                    # into a populated string during translation: the client
                    # expects the original empty state and may dereference
                    # the record differently when it is filled.
                    if text is None or (text and original_string == b"\x00"):
                        rel = len(pool)
                        pool.extend(original_string)
                    else:
                        rel = len(pool)
                        pool.extend(compile_sestring(text, tags))
                    struct.pack_into(">I", fixed, offset, rel)
                elif col_index in values:
                    _encode_value(fixed, schema["columns"], col_index, values[col_index])
            rendered_subs.append((sub["sub_id"], fixed))
        fixed_region = bytearray()
        for sub_id, fixed in rendered_subs:
            if schema["variant"] == 2:
                fixed_region.extend(struct.pack(">H", sub_id))
            fixed_region.extend(fixed)
        pad = (4 - ((2 + len(fixed_region) + len(pool)) % 4)) % 4
        payload = fixed_region + pool + bytes(pad)
        row_offset = 32 + 8 * len(records) + len(data_rows)
        index.append((record["row_id"], row_offset))
        data_rows.extend(struct.pack(">IH", len(payload), record["sub_count"]))
        data_rows.extend(payload)
    out = bytearray(b"EXDF\x00\x02\x00\x00")
    out.extend(struct.pack(">II", len(index) * 8, len(data_rows)))
    out.extend(bytes(16))
    for row_id, offset in index: out.extend(struct.pack(">II", row_id, offset))
    out.extend(data_rows)
    return bytes(out)


def compile_exd(exh_name):
    name = exh_name.lower().replace(".exh", "")
    csv_path, tags_path, meta_path = (os.path.join(WORKSPACE_DIR, f"{name}{suffix}")
                                      for suffix in (".csv", "_tags.json", "_meta.json"))
    if not os.path.exists(csv_path):
        return {"error": "CSV mancante. Caricare o estrarre il file prima della compilazione."}
    schema = parse_exh(read_file(f"{name}.exh"))
    # Old translations used the same CSV layout but a different tag numbering.
    # Prefer the new dictionary, then fall back to the legacy read-only location.
    tag_source = tags_path
    if not os.path.exists(tag_source):
        legacy_tags = os.path.join(LEGACY_WORKSPACE_DIR, f"{name}_tags.json")
        if os.path.exists(legacy_tags):
            tag_source = legacy_tags
    if not os.path.exists(tag_source):
        return {"error": "Dizionario tag mancante. Rieseguire l'estrazione o fornire il vecchio *_tags.json."}
    tags = json.load(open(tag_source, encoding="utf-8"))
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f); header = next(reader); csv_rows = list(reader)
    has_sub = schema["variant"] == 2
    if os.path.exists(meta_path):
        meta_rows = json.load(open(meta_path, encoding="utf-8"))["rows"]
    else:
        # Legacy CSVs have no metadata. Reconstruct the stable row order from
        # the current EXH/EXD pages; this does not alter the legacy files.
        meta_rows = []
        for _, _, file_name, original in _page_files(name, schema):
            for record in _row_records(original, schema):
                for sub in record["subs"]:
                    meta_rows.append({"file": file_name, "row_id": record["row_id"],
                                      "sub_id": sub["sub_id"]})
    if len(csv_rows) != len(meta_rows):
        return {"error": "CSV e metadati non hanno lo stesso numero di righe; rieseguire l'estrazione."}
    # Accept translations produced by the previous exporter: placeholder
    # numbers are presentation IDs, while the raw SeString bytes are stable.
    effective_tags = dict(tags)
    # Legacy numbering can collide with current numbering, therefore aliases
    # must replace same-number entries when they are observed in this CSV.
    effective_tags.update(_legacy_tag_aliases(name, schema, csv_rows, meta_rows))
    invalid_cells = set()
    first = 2 if schema["variant"] == 2 else 1
    for row_index, row in enumerate(csv_rows):
        for col_index, (typ, _) in enumerate(schema["columns"]):
            if typ == 0 and first + col_index < len(row):
                if any(token not in effective_tags for token in
                       re.findall(r"\{(\d+)\}", row[first + col_index])):
                    # Preserve the original binary SeString instead of
                    # emitting literal {1234} text into the game client.
                    invalid_cells.add((row_index, col_index))
    values_by_file = {}
    for row_index, (row, meta) in enumerate(zip(csv_rows, meta_rows)):
        first = 2 if has_sub else 1
        values = {i: value for i, value in enumerate(row[first:], start=0)
                  if (row_index, i) not in invalid_cells}
        values_by_file.setdefault(meta["file"], {})[(int(meta["row_id"]), meta["sub_id"])] = values
    compiled, files, byte_audit = [], [], []
    for _, _, file_name, original in _page_files(name, schema):
        values = values_by_file.get(file_name, {})
        output = _compile_page(original, schema, values, effective_tags)
        destination = os.path.join(EXD_DIR, file_name)
        with open(destination, "wb") as f: f.write(output)
        compiled.append(destination); files.append(file_name)
        delta = len(output) - len(original)
        byte_audit.append({
            "file": file_name,
            "original_bytes": len(original),
            "translated_bytes": len(output),
            "delta_bytes": delta,
            "changed": delta != 0,
            "warning": (f"Dimensione EXD variata di {delta:+d} byte: verificare la compatibilità."
                        if delta else "")
        })
    with open(os.path.join(EXD_DIR, f"{name}.manifest.json"), "w") as f:
        json.dump({"files": files}, f, indent=2)
    changed_pages = sum(item["changed"] for item in byte_audit)
    return {"success": True, "size": sum(os.path.getsize(p) for p in compiled),
            "files": files, "pages": len(files), "variant": schema["variant"],
            "byte_audit": byte_audit, "changed_pages": changed_pages}


def _make_dat_entry(raw):
    chunks = [raw[i:i + 16000] for i in range(0, len(raw), 16000)] or [b""]
    infos, blocks, block_offset = [], bytearray(), 0
    for chunk in chunks:
        obj = zlib.compressobj(wbits=-15); compressed = obj.compress(chunk) + obj.flush()
        use_raw = len(compressed) >= len(chunk)
        payload = chunk if use_raw else compressed
        # FFXIV's SQPACK format marks an uncompressed block with the special
        # compressed-size value 32000. Writing the raw length here makes
        # Lumina/Dalamud interpret the raw bytes as Deflate, which can cause
        # the exact startup error: bytesRead (...) != BlockDataSize (...).
        block_size_field = 32000 if use_raw else len(payload)
        c_size = len(payload); pad = (128 - ((16 + c_size) % 128)) % 128
        infos.append((block_offset, 16 + c_size + pad, len(chunk)))
        blocks.extend(struct.pack("<IIII", 16, 0, block_size_field, len(chunk)))
        blocks.extend(payload); blocks.extend(bytes(pad)); block_offset += 16 + c_size + pad
    base = 24 + 8 * len(infos); header_len = base + ((128 - base % 128) % 128)
    header = struct.pack("<III", header_len, 2, len(raw)) + struct.pack("<II", (header_len + len(blocks)) // 128, len(blocks) // 128) + struct.pack("<I", len(infos))
    header += b"".join(struct.pack("<IHH", *item) for item in infos)
    header += bytes(header_len - len(header))
    return header + blocks


def _index_entry(file_name):
    wanted = crc32_lower(file_name)
    with open(INDEX_PATH, "rb") as f:
        f.seek(1032); table_offset, table_size = struct.unpack("<II", f.read(8)); f.seek(table_offset)
        for i in range(table_size // 16):
            pos = table_offset + i * 16
            name_hash, folder_hash, raw, _ = struct.unpack("<IIII", f.read(16))
            if name_hash == wanted and folder_hash == FOLDER_HASH:
                return pos, (raw & 0x0F) >> 1, (raw & 0xFFFFFFF0) * 8
    return None


def _index2_entry(file_name):
    """Return the matching index2 entry for an EXD path, if present."""
    wanted = crc32_lower("exd/" + file_name)
    index2_path = INDEX_PATH.replace(".index", ".index2")
    try:
        with open(index2_path, "rb") as f:
            f.seek(1032)
            table_offset, table_size = struct.unpack("<II", f.read(8))
            f.seek(table_offset)
            for i in range(table_size // 8):
                pos = table_offset + i * 8
                name_hash, raw = struct.unpack("<II", f.read(8))
                if name_hash == wanted:
                    return pos, (raw & 0x0F) >> 1, (raw & 0xFFFFFFF0) * 8
    except (OSError, struct.error):
        pass
    return None


def _inject_one(file_name, raw):
    target = _index_entry(file_name)
    if target is None:
        return {"error": f"{file_name} non trovato nell'indice; nessun dato scritto."}
    entry_pos, dat_idx, old_offset = target
    target2 = _index2_entry(file_name)
    if target2 is not None and target2[1] != dat_idx:
        return {"error": f"{file_name}: index e index2 indicano dat diversi; inject annullato."}
    dat_path = os.path.join(SQPACK_DIR, f"0a0000.win32.dat{dat_idx}")
    old_size = os.path.getsize(dat_path); new_offset = (old_size + 127) & ~127
    entry = _make_dat_entry(raw)
    try:
        with open(dat_path, "ab") as dat:
            dat.write(bytes(new_offset - old_size)); dat.write(entry)
        encoded = (new_offset // 8) | (dat_idx << 1)
        with open(INDEX_PATH, "r+b") as idx:
            idx.seek(entry_pos + 8); idx.write(struct.pack("<I", encoded))
        if target2 is not None:
            index2_path = INDEX_PATH.replace(".index", ".index2")
            with open(index2_path, "r+b") as idx2:
                idx2.seek(target2[0] + 4); idx2.write(struct.pack("<I", encoded))
        return {"file": file_name, "old_offset": hex(old_offset), "new_offset": hex(new_offset)}
    except Exception:
        try:
            with open(dat_path, "r+b") as dat: dat.truncate(old_size)
        except OSError:
            pass
        raise


def hard_inject_sqpack(exh_name):
    name = exh_name.lower().replace(".exh", "")
    manifest_path = os.path.join(EXD_DIR, f"{name}.manifest.json")
    if not os.path.exists(manifest_path):
        return {"error": "Manifest compilazione assente. Estrarre e compilare nuovamente il foglio."}
    files = json.load(open(manifest_path, encoding="utf-8")).get("files", [])
    if not files:
        return {"error": "Manifest senza file EXD."}
    results = []
    for file_name in files:
        path = os.path.join(EXD_DIR, file_name)
        if not os.path.isfile(path):
            return {"error": f"File compilato mancante: {file_name}. Nessun inject eseguito."}
        if _index_entry(file_name) is None:
            return {"error": f"{file_name} non trovato nell'indice. Nessun inject eseguito."}
        results.append((file_name, open(path, "rb").read()))
    # Preserve the first known-good state inside the project. Existing backups
    # are never replaced, and the game's legacy .bak files remain untouched.
    for source in (os.path.join(SQPACK_DIR, "0a0000.win32.dat0"), INDEX_PATH,
                   INDEX_PATH.replace(".index", ".index2")):
        backup = os.path.join(BACKUP_SQPACK_DIR, os.path.basename(source) + ".bak")
        if not os.path.exists(backup):
            shutil.copy2(source, backup)
    schema = parse_exh(read_file(f"{name}.exh"))
    live_originals = {file_name: original for _, _, file_name, original in _page_files(name, schema)}
    # Always compare against the project's pristine SQPACK backup when it is
    # available. This prevents a second inject from hiding the first size
    # increase by comparing against an already translated page.
    originals, baseline_sources = {}, {}
    for _, _, file_name, live_original in _page_files(name, schema):
        backup_original = read_backup_file(file_name)
        originals[file_name] = backup_original or live_original
        baseline_sources[file_name] = "project_sqpack_backup" if backup_original else "current_sqpack"
    injected = [_inject_one(file_name, raw) for file_name, raw in results]
    byte_audit = []
    for file_name, raw in results:
        original = originals.get(file_name, b"")
        delta = len(raw) - len(original)
        byte_audit.append({
            "file": file_name,
            "original_bytes": len(original),
            "translated_bytes": len(raw),
            "delta_bytes": delta,
            "changed": delta != 0,
            "baseline": baseline_sources.get(file_name, "current_sqpack"),
            "warning": (f"Dimensione EXD variata di {delta:+d} byte: possibile rischio di crash."
                        if delta else "")
        })
    return {"success": True, "files": injected, "pages": len(injected),
            "byte_audit": byte_audit,
            "changed_pages": sum(item["changed"] for item in byte_audit)}
