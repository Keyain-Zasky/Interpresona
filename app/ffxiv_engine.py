"""Safe EXH/EXD reader, compiler and hard injector for FFXIV SQPACK.

The important invariant is that compilation starts from the original EXD fixed
data.  CSV is a translation view; it is not treated as a complete replacement
for the binary schema.
"""

import binascii
import csv
import hashlib
import json
import os
import re
import shutil
import struct
import time
import zlib

PROJECT_DIR = os.path.abspath(os.environ.get(
    "INTERPRESONA_ENGINE_PROJECT_DIR",
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
))
# The Codex copy must never write CSV/EXD output into the original project.
RUNTIME_DIR = os.path.abspath(os.environ.get("INTERPRESONA_ENGINE_RUNTIME_DIR", os.path.join(PROJECT_DIR, "runtime")))
SETTINGS_PATH = os.path.join(PROJECT_DIR, "settings.json")
RUNTIME_SETTINGS_PATH = os.path.join(RUNTIME_DIR, "settings.json")
USER_SETTINGS_PATH = os.path.join(os.path.expanduser("~"), ".config", "ffxiv-zero-error-translator", "settings.json")
DEFAULT_SQPACK_DIR = os.path.join(os.path.expanduser("~"), "Games", "Steam", "FINAL FANTASY XIV Online", "game", "sqpack", "ffxiv")
# Sorgente ufficiale dei CSV del progetto locale. Le impostazioni utente
# possono comunque sovrascriverla per un ambiente di test separato.
DEFAULT_CSV_SOURCE_DIR = os.path.join(os.path.expanduser("~"), "FFXIV-Zero-Error-Translator", "data", "csv", "current")
DEFAULT_WORKSPACE_DIR = os.path.join(RUNTIME_DIR, "workspace")
DEFAULT_EXPORT_DIR = os.path.join(PROJECT_DIR, "export")
DEFAULT_EXD_DIR = os.path.join(RUNTIME_DIR, "exd")
CATALOG_FILE = os.path.abspath(os.environ.get("INTERPRESONA_ENGINE_CATALOG_FILE", os.path.join(PROJECT_DIR, "app", "ffxiv_sheets.txt")))
BUILTIN_SHEETS = (
    "addon", "lobby", "item", "quest", "eventtext", "weather", "customtalk",
    # Dialoghi Bozja richiamati da Sjeros e dagli ingressi del fronte.
    "custom/006/ctsmycentrance_00673",
    "custom/007/ctsmycentrancenormal_00705",
    "custom/007/ctsmycentrancehard_00706",
)
_SHEET_CATALOG_CACHE = None
_SHEET_CATALOG_CACHE_SIGNATURE = None
_INDEX_TABLE_CACHE = {}
_INDEX_ENTRIES_CACHE = {}
_INDEX2_ENTRIES_CACHE = {}
_TECHNICAL_COLUMN_CACHE = {}
_INDEX_CACHE_SIGNATURE = None
_INDEX_CACHE_CHECKED_AT = 0.0

# These columns are runtime identifiers even though their values look like
# ordinary lore terms.  They must never follow the Italian localisation.
FORCED_TECHNICAL_STRING_COLUMNS = {
    "aetheryte": frozenset({17}),
    "transport/aetheryte": frozenset({0}),
}


def _read_settings():
    for path in (USER_SETTINGS_PATH, SETTINGS_PATH, RUNTIME_SETTINGS_PATH):
        try:
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
                if isinstance(data, dict):
                    return data
        except (OSError, json.JSONDecodeError):
            pass
    return {}


_saved_settings = _read_settings()
SQPACK_DIR = _saved_settings.get("sqpack_dir", DEFAULT_SQPACK_DIR)
CSV_SOURCE_DIR = _saved_settings.get("csv_source_dir", DEFAULT_CSV_SOURCE_DIR)
configured_workspace = _saved_settings.get("workspace_dir", DEFAULT_WORKSPACE_DIR)
if "export_dir" not in _saved_settings and os.path.basename(os.path.normpath(configured_workspace)).lower() == "export":
    EXPORT_DIR = configured_workspace
    WORKSPACE_DIR = DEFAULT_WORKSPACE_DIR
else:
    EXPORT_DIR = _saved_settings.get("export_dir", DEFAULT_EXPORT_DIR)
    WORKSPACE_DIR = configured_workspace
EXD_DIR = _saved_settings.get("exd_dir", DEFAULT_EXD_DIR)
INDEX_PATH = os.path.join(SQPACK_DIR, "0a0000.win32.index")
CATALOG_DIRS = tuple(dict.fromkeys((CSV_SOURCE_DIR, WORKSPACE_DIR)))
os.makedirs(WORKSPACE_DIR, exist_ok=True)
os.makedirs(EXPORT_DIR, exist_ok=True)
os.makedirs(EXD_DIR, exist_ok=True)


def settings_snapshot():
    return {"sqpack_dir": SQPACK_DIR, "csv_source_dir": CSV_SOURCE_DIR,
            "workspace_dir": WORKSPACE_DIR, "export_dir": EXPORT_DIR, "exd_dir": EXD_DIR,
            "game_version": _game_version(),
            "sqpack_ok": os.path.exists(INDEX_PATH),
            "csv_source_ok": os.path.isdir(CSV_SOURCE_DIR),
            "workspace_ok": os.path.isdir(WORKSPACE_DIR),
            "export_ok": os.path.isdir(EXPORT_DIR) and os.access(EXPORT_DIR, os.W_OK),
            "exd_ok": os.path.isdir(EXD_DIR) and os.access(EXD_DIR, os.W_OK)}


def apply_settings(values):
    global SQPACK_DIR, INDEX_PATH, CSV_SOURCE_DIR, WORKSPACE_DIR, EXPORT_DIR, EXD_DIR, CATALOG_DIRS
    sqpack = os.path.abspath(os.path.expanduser(str(values.get("sqpack_dir", SQPACK_DIR)).strip()))
    csv_source = os.path.abspath(os.path.expanduser(str(values.get("csv_source_dir", CSV_SOURCE_DIR)).strip()))
    workspace = os.path.abspath(os.path.expanduser(str(values.get("workspace_dir", WORKSPACE_DIR)).strip()))
    export = os.path.abspath(os.path.expanduser(str(values.get("export_dir", EXPORT_DIR)).strip()))
    exd = os.path.abspath(os.path.expanduser(str(values.get("exd_dir", EXD_DIR)).strip()))
    if not sqpack or not csv_source or not workspace or not export or not exd:
        raise ValueError("Tutti i percorsi sono obbligatori.")
    os.makedirs(workspace, exist_ok=True)
    os.makedirs(export, exist_ok=True)
    os.makedirs(exd, exist_ok=True)
    SQPACK_DIR, CSV_SOURCE_DIR, WORKSPACE_DIR, EXPORT_DIR, EXD_DIR = sqpack, csv_source, workspace, export, exd
    INDEX_PATH = os.path.join(SQPACK_DIR, "0a0000.win32.index")
    CATALOG_DIRS = tuple(dict.fromkeys((CSV_SOURCE_DIR, WORKSPACE_DIR)))
    _invalidate_index_caches()
    os.makedirs(os.path.dirname(USER_SETTINGS_PATH), exist_ok=True)
    with open(USER_SETTINGS_PATH, "w", encoding="utf-8") as handle:
        json.dump({"sqpack_dir": SQPACK_DIR, "csv_source_dir": CSV_SOURCE_DIR,
                   "workspace_dir": WORKSPACE_DIR, "export_dir": EXPORT_DIR,
                   "exd_dir": EXD_DIR}, handle, indent=2)
    return settings_snapshot()

TYPE_WIDTH = {0x00: 4, 0x01: 1, 0x02: 1, 0x03: 1, 0x04: 2,
              0x05: 2, 0x06: 4, 0x07: 4, 0x09: 4, 0x0B: 8}

def crc32_lower(value):
    return binascii.crc32(value.encode("utf-8").lower()) ^ 0xFFFFFFFF


def _normalise_game_file(file_name):
    """Return a safe path relative to ``exd/`` and its hash components.

    Retail EXD files are not all in ``exd/`` directly: custom dialogue is
    stored below paths such as ``exd/custom/006/...``.  The previous lookup
    hashed the complete relative path as the filename and therefore could
    never find those files.
    """
    value = str(file_name).replace("\\", "/").strip("/").lower()
    if value.startswith("exd/"):
        value = value[4:]
    value = "/".join(part for part in value.split("/") if part not in ("", "."))
    if not value or ".." in value.split("/"):
        raise ValueError(f"Percorso EXD non valido: {file_name}")
    if "/" in value:
        relative_folder, filename = value.rsplit("/", 1)
        folder = f"exd/{relative_folder}"
    else:
        filename = value
        folder = "exd"
    return value, folder, filename


def _index_paths():
    paths = []
    try:
        for path in sorted(os.listdir(SQPACK_DIR)):
            if path.endswith(".win32.index"):
                candidate = os.path.join(SQPACK_DIR, path)
                if os.path.isfile(candidate):
                    paths.append(candidate)
    except OSError:
        pass
    if INDEX_PATH in paths:
        paths.remove(INDEX_PATH)
    return [INDEX_PATH] + paths if os.path.isfile(INDEX_PATH) else paths


def _index_signature():
    signature = []
    for path in _index_paths():
        try:
            stat = os.stat(path)
            signature.append((path, stat.st_size, stat.st_mtime_ns))
            index2_path = path.replace(".index", ".index2")
            stat2 = os.stat(index2_path)
            signature.append((index2_path, stat2.st_size, stat2.st_mtime_ns))
        except OSError:
            signature.append((path, None, None))
    return tuple(signature)


def _invalidate_index_caches(index_path=None):
    global _SHEET_CATALOG_CACHE, _SHEET_CATALOG_CACHE_SIGNATURE
    global _INDEX_CACHE_SIGNATURE, _INDEX_CACHE_CHECKED_AT
    if index_path is None:
        _INDEX_TABLE_CACHE.clear()
        _INDEX_ENTRIES_CACHE.clear()
        _INDEX2_ENTRIES_CACHE.clear()
        _TECHNICAL_COLUMN_CACHE.clear()
    else:
        _INDEX_TABLE_CACHE.pop(index_path, None)
        _INDEX_ENTRIES_CACHE.pop(index_path, None)
        _INDEX2_ENTRIES_CACHE.pop(index_path.replace(".index", ".index2"), None)
        _TECHNICAL_COLUMN_CACHE.clear()
    _SHEET_CATALOG_CACHE = None
    _SHEET_CATALOG_CACHE_SIGNATURE = None
    _INDEX_CACHE_SIGNATURE = None
    _INDEX_CACHE_CHECKED_AT = 0.0


def _ensure_index_cache_current(force=False):
    """Drop cached hashes when Steam replaces SqPack indexes after a patch."""
    global _INDEX_CACHE_SIGNATURE, _INDEX_CACHE_CHECKED_AT
    now = time.monotonic()
    if not force and now - _INDEX_CACHE_CHECKED_AT < 1.0:
        return
    signature = _index_signature()
    if _INDEX_CACHE_SIGNATURE is not None and signature != _INDEX_CACHE_SIGNATURE:
        _INDEX_TABLE_CACHE.clear()
        _INDEX_ENTRIES_CACHE.clear()
        _INDEX2_ENTRIES_CACHE.clear()
        _TECHNICAL_COLUMN_CACHE.clear()
        global _SHEET_CATALOG_CACHE, _SHEET_CATALOG_CACHE_SIGNATURE
        _SHEET_CATALOG_CACHE = None
        _SHEET_CATALOG_CACHE_SIGNATURE = None
    _INDEX_CACHE_SIGNATURE = signature
    _INDEX_CACHE_CHECKED_AT = now


def _dat_path(index_path, dat_id):
    """Resolve the DAT beside an index (including the ``.win32`` suffix)."""
    return os.path.join(SQPACK_DIR, os.path.basename(index_path).replace(".index", f".dat{dat_id}"))


def _index_table(index_path):
    cached = _INDEX_TABLE_CACHE.get(index_path)
    if cached is not None:
        return cached
    with open(index_path, "rb") as f:
        f.seek(1032)
        table_offset, table_size = struct.unpack("<II", f.read(8))
    cached = (table_offset, table_size)
    _INDEX_TABLE_CACHE[index_path] = cached
    return cached


def _index_entries(index_path):
    """Load one index once; repeated EXH checks must not rescan its bytes."""
    cached = _INDEX_ENTRIES_CACHE.get(index_path)
    if cached is not None:
        return cached
    table_offset, table_size = _index_table(index_path)
    entries = {}
    with open(index_path, "rb") as f:
        f.seek(table_offset)
        for i in range(table_size // 16):
            pos = table_offset + i * 16
            chunk = f.read(16)
            if len(chunk) != 16:
                break
            name_hash, folder_hash, raw_offset, _ = struct.unpack("<IIII", chunk)
            if raw_offset and raw_offset != 0xFFFFFFFF:
                entries[(folder_hash, name_hash)] = (
                    pos, (raw_offset & 0x0F) >> 1, (raw_offset & 0xFFFFFFF0) * 8
                )
    _INDEX_ENTRIES_CACHE[index_path] = entries
    return entries


def _locate_file(file_name):
    """Return index path, entry position, DAT id and offset for an EXD path."""
    _ensure_index_cache_current()
    _, folder, filename = _normalise_game_file(file_name)
    wanted_name = crc32_lower(filename)
    wanted_folder = crc32_lower(folder)
    for index_path in _index_paths():
        try:
            entry = _index_entries(index_path).get((wanted_folder, wanted_name))
            if entry is not None:
                pos, dat_id, offset = entry
                return index_path, pos, dat_id, offset
        except (OSError, struct.error, ValueError):
            continue
    return None


def get_file_offset(file_name):
    located = _locate_file(file_name)
    return (located[2], located[3]) if located else (None, None)


def extract_file(dat_idx, offset, index_path=None):
    """Extract a type-2 SQPACK entry and reject truncated/corrupt entries."""
    if dat_idx is None or offset is None:
        return None
    path = _dat_path(index_path or INDEX_PATH, dat_idx)
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


def read_file(file_name):
    located = _locate_file(file_name)
    if not located:
        return None
    index_path, _, dat_idx, offset = located
    return extract_file(dat_idx, offset, index_path)


def _root_sheet_names():
    root = read_file("root.exl")
    if not root:
        raise ValueError("root.exl non trovato negli SQPACK")
    names = []
    for line in root.decode("utf-8-sig", errors="strict").splitlines():
        line = line.strip()
        if not line or line.startswith("EXLT"):
            continue
        name = line.split(",", 1)[0].strip().lower()
        if name:
            names.append(name)
    if not names:
        raise ValueError("root.exl non contiene alcun foglio")
    return list(dict.fromkeys(names))


def available_exh_names():
    """Return known sheet names that actually exist in the current SQPACK.

    SQPACK stores hashes, not path strings, so a complete human-readable list
    requires an external sheet-name catalogue.  We combine the UI defaults,
    local rawexd catalogues and existing workspaces, then verify each EXH hash.
    """
    _ensure_index_cache_current(force=True)
    candidates = set(BUILTIN_SHEETS)
    # root.exl is the authoritative sheet catalogue for the installed patch.
    # The bundled text file is only a fallback for incomplete/old installs.
    try:
        candidates.update(_root_sheet_names())
    except (OSError, UnicodeDecodeError, ValueError):
        pass
    try:
        with open(CATALOG_FILE, encoding="utf-8") as catalog:
            candidates.update(line.strip().lower() for line in catalog
                              if line.strip() and not line.startswith("#"))
    except OSError:
        pass
    for directory in CATALOG_DIRS:
        try:
            for root, _, files in os.walk(directory):
                for filename in files:
                    relative = os.path.relpath(os.path.join(root, filename), directory)
                    stem, ext = os.path.splitext(relative)
                    if ext.lower() in (".csv", ".exh") and stem:
                        candidates.add(stem.replace(os.sep, "/").lower())
        except OSError:
            continue
    return sorted(name for name in candidates if get_file_offset(name + ".exh")[0] is not None)


def sheet_catalog():
    """Build the UI catalog with schema metadata, cached for the process."""
    global _SHEET_CATALOG_CACHE, _SHEET_CATALOG_CACHE_SIGNATURE
    _ensure_index_cache_current(force=True)
    signature = _INDEX_CACHE_SIGNATURE
    if _SHEET_CATALOG_CACHE is not None and _SHEET_CATALOG_CACHE_SIGNATURE == signature:
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
    _SHEET_CATALOG_CACHE_SIGNATURE = signature
    return catalog


def translation_category(name):
    """Human-oriented translation groups, applied only to text-bearing EXH."""
    n = name.lower()
    if n.startswith("custom/"):
        return "Dialoghi"
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
    required = 32 + column_count * 4 + page_count * 8 + language_count * 2
    if len(data) < required or row_size == 0:
        raise ValueError("EXH troncato o con dimensione riga nulla")
    if variant not in (1, 2):
        raise ValueError(f"Variant EXH non supportata: {variant}")
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
        if row_offset < 32 + index_size or row_offset + 6 > len(exd):
            raise ValueError("Offset riga EXD non valido")
        payload_size, sub_count = struct.unpack(">IH", exd[row_offset:row_offset + 6])
        end = row_offset + 6 + payload_size
        if end > len(exd):
            raise ValueError("Riga EXD oltre la fine del file")
        cursor = row_offset + 6
        minimum = sub_count * (row_size + (2 if variant == 2 else 0))
        if payload_size < minimum:
            raise ValueError("Payload EXD più corto dei fixed data dichiarati")
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
    # EXH columns are not guaranteed to be ordered by their byte offset.
    # Looking only at later definitions can cross an intervening string
    # pointer and overwrite it (Perform's 0x0B field exposed this case).
    following = [off for _, off in columns if off > start]
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
    if start < record["pool_start"] or start >= record["pool_end"]:
        raise ValueError("Offset stringa EXD fuori dal pool della riga")
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
        else:
            raise ValueError(
                f"Pagina EXD {name}_{start_id} inglese/neutra mancante nella patch corrente"
            )
    return result


def export_exh(exh_name):
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
        output_csv = os.path.join(EXPORT_DIR, f"{name}.csv")
        os.makedirs(os.path.dirname(output_csv), exist_ok=True)
        with open(output_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            header = ["RowID"] + (["SubrowID"] if schema["variant"] == 2 else []) + [f"Col_{i}" for i in range(schema["column_count"])]
            writer.writerow(header); writer.writerows(rows)
        with open(os.path.join(EXPORT_DIR, f"{name}_tags.json"), "w") as f: json.dump(tags, f, indent=2)
        with open(os.path.join(EXPORT_DIR, f"{name}_meta.json"), "w") as f: json.dump({"schema": schema, "rows": meta}, f, indent=2)
        return {"success": True, "rows": len(rows), "tags": len(tags), "file": output_csv, "pages": len(pages), "variant": schema["variant"]}
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


def _looks_machine_identifier(value):
    """Recognise common script/resource identifiers, not ordinary prose."""
    value = value.strip()
    if not value or any(char.isspace() for char in value):
        return False
    patterns = (
        r"[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+",
        r"[A-Z][A-Z0-9]*\d[A-Z0-9]*",
        r"(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_./-]+",
        r"[a-z]+(?:[A-Z][A-Za-z0-9]*)+",
    )
    return any(re.fullmatch(pattern, value) for pattern in patterns)


def _records_by_key(exd, schema):
    return {
        (record["row_id"], sub["sub_id"]): (record, sub)
        for record in _row_records(exd, schema)
        for sub in record["subs"]
    }


def _is_technical_column_stats(item):
    total, same = item["total"], item["same"]
    if not total or not same or same / total < 0.95:
        return False
    identifier_ratio = item["identifiers"] / same
    return identifier_ratio >= 0.5


def _detect_technical_string_columns(name, schema):
    """Infer non-translatable columns from Square Enix's own localisations.

    Script keys and resource paths remain byte-identical in Japanese, German
    and French, while player-facing text changes. Comparing those untouched
    languages makes the protection patch-aware and avoids a sheet allow-list.
    """
    cached = _TECHNICAL_COLUMN_CACHE.get(name)
    if cached is not None:
        return cached
    string_columns = [i for i, (typ, _) in enumerate(schema["columns"]) if typ == 0]
    stats = {
        i: {"total": 0, "same": 0, "identifiers": 0, "unique": set()}
        for i in string_columns
    }
    canonical = {}
    for start_id, _ in schema["pages"]:
        language_pages = {}
        for language in ("ja", "de", "fr"):
            data = read_file(f"{name}_{start_id}_{language}.exd")
            if data:
                language_pages[language] = (data, _records_by_key(data, schema))
        if len(language_pages) < 2:
            continue
        common_keys = set.intersection(*(set(rows) for _, rows in language_pages.values()))
        for key in common_keys:
            for col_index in string_columns:
                raw_values = []
                for data, rows in language_pages.values():
                    record, sub = rows[key]
                    raw_values.append(_raw_string(
                        data, record, sub["fixed"], schema["columns"], col_index
                    )[:-1])
                if all(value in (b"", b"0") for value in raw_values):
                    continue
                item = stats[col_index]
                item["total"] += 1
                if not all(value == raw_values[0] for value in raw_values[1:]):
                    continue
                item["same"] += 1
                raw = raw_values[0]
                item["unique"].add(raw)
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    continue
                if _looks_machine_identifier(text):
                    item["identifiers"] += 1
                if b"\x02" not in raw:
                    canonical[(key[0], key[1], col_index)] = text
    protected = set(FORCED_TECHNICAL_STRING_COLUMNS.get(name, ()))
    for col_index, item in stats.items():
        if _is_technical_column_stats(item):
            protected.add(col_index)
    result = (frozenset(protected), {
        key: value for key, value in canonical.items() if key[2] in protected
    })
    _TECHNICAL_COLUMN_CACHE[name] = result
    return result


def enforce_forced_technical_strings(exh_name, file_name, raw):
    """Restore mandatory runtime identifiers inside a compiled EXD page.

    Canonical values come from Square Enix's untranslated JA/DE/FR pages, so
    this also repairs a downloaded release compiled from a contaminated EN
    page without touching any player-facing Italian text.
    """
    name = exh_name.lower().replace(".exh", "")
    forced = FORCED_TECHNICAL_STRING_COLUMNS.get(name, frozenset())
    if not forced:
        return raw
    exh = read_file(f"{name}.exh")
    if not exh:
        raise ValueError(f"Schema EXH non disponibile per la protezione tecnica di {name}.")
    schema = parse_exh(exh)
    invalid = sorted(i for i in forced if i >= len(schema["columns"]) or schema["columns"][i][0] != 0)
    if invalid:
        raise ValueError(f"Colonne tecniche non compatibili con lo schema {name}: {invalid}.")
    _, canonical = _detect_technical_string_columns(name, schema)
    values = {}
    for record in _row_records(raw, schema):
        for sub in record["subs"]:
            key = (record["row_id"], sub["sub_id"])
            replacements = {}
            for col_index in forced:
                canonical_value = canonical.get((record["row_id"], sub["sub_id"], col_index))
                if canonical_value is None:
                    raise ValueError(
                        f"Valore tecnico canonico assente: {name}, riga {record['row_id']}, "
                        f"colonna {col_index}."
                    )
                replacements[col_index] = canonical_value
            values[key] = replacements
    return _compile_page(raw, schema, values, {})


def compile_exd(exh_name):
    name = exh_name.lower().replace(".exh", "")
    csv_path, tags_path, meta_path = (os.path.join(WORKSPACE_DIR, f"{name}{suffix}")
                                      for suffix in (".csv", "_tags.json", "_meta.json"))
    if not os.path.exists(csv_path):
        return {"error": "CSV mancante. Caricare o estrarre il file prima della compilazione."}
    schema = parse_exh(read_file(f"{name}.exh"))
    technical_columns, canonical_technical = _detect_technical_string_columns(name, schema)
    forced_technical = FORCED_TECHNICAL_STRING_COLUMNS.get(name, frozenset())
    # Tag dictionaries belong to the selected workspace and travel with the CSV.
    # This prevents an unrelated legacy directory from silently changing output.
    tag_source = tags_path
    if not os.path.exists(tag_source):
        return {"error": "Dizionario tag mancante nella workspace selezionata. Rieseguire l'estrazione."}
    tags = json.load(open(tag_source, encoding="utf-8"))
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f); header = next(reader); csv_rows = list(reader)
    has_sub = schema["variant"] == 2
    first = 2 if has_sub else 1
    # When present, *_original.csv is an authoritative source for protected
    # script-string columns. This can repair a prior bad inject even though the
    # currently mounted EXD already contains the translated identifier.
    protected_rows = {}
    original_csv_path = os.path.join(WORKSPACE_DIR, f"{name}_original.csv")
    if os.path.isfile(original_csv_path):
        with open(original_csv_path, newline="", encoding="utf-8-sig") as handle:
            original_reader = csv.reader(handle)
            original_header = next(original_reader, [])
            original_rows = list(original_reader)
        if original_header == header:
            def csv_key(row):
                return (int(row[0]), int(row[1]) if has_sub else None)
            candidate = {csv_key(row): row for row in original_rows if len(row) >= first}
            current_keys = {csv_key(row) for row in csv_rows if len(row) >= first}
            if set(candidate) == current_keys:
                protected_rows = candidate
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
        values = {
            i: value for i, value in enumerate(row[first:], start=0)
            if (row_index, i) not in invalid_cells
            and i < len(schema["columns"])
            and schema["columns"][i][0] == 0
            and i not in technical_columns
        }
        protected = protected_rows.get((int(meta["row_id"]), meta["sub_id"]))
        for i in technical_columns:
            position = first + i
            canonical = canonical_technical.get(
                (int(meta["row_id"]), meta["sub_id"], i)
            )
            if i in forced_technical:
                if canonical is None:
                    raise ValueError(
                        f"Valore tecnico canonico assente: {name}, riga {meta['row_id']}, colonna {i}."
                    )
                values[i] = canonical
            elif protected and position < len(protected):
                values[i] = protected[position]
            elif canonical is not None:
                values[i] = canonical
        values_by_file.setdefault(meta["file"], {})[(int(meta["row_id"]), meta["sub_id"])] = values
    compiled, files, byte_audit = [], [], []
    source_hashes, output_hashes = {}, {}
    for _, _, file_name, original in _page_files(name, schema):
        values = values_by_file.get(file_name, {})
        output = _compile_page(original, schema, values, effective_tags)
        destination = os.path.join(EXD_DIR, file_name)
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        with open(destination, "wb") as f: f.write(output)
        compiled.append(destination); files.append(file_name)
        source_hashes[file_name] = hashlib.sha256(original).hexdigest()
        output_hashes[file_name] = hashlib.sha256(output).hexdigest()
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
    manifest_path = os.path.join(EXD_DIR, f"{name}.manifest.json")
    os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
    with open(manifest_path, "w") as f:
        json.dump({
            "format": 2,
            "sheet": name,
            "game_version": _game_version(),
            "schema_sha256": hashlib.sha256(read_file(f"{name}.exh")).hexdigest(),
            "files": files,
            "source_sha256": source_hashes,
            "output_sha256": output_hashes,
        }, f, indent=2)
    changed_pages = sum(item["changed"] for item in byte_audit)
    return {"success": True, "size": sum(os.path.getsize(p) for p in compiled),
            "files": files, "pages": len(files), "variant": schema["variant"],
            "byte_audit": byte_audit, "changed_pages": changed_pages,
            "protected_columns": sorted(technical_columns),
            "protected_column_count": len(technical_columns)}


def audit_translation_pipeline():
    """Read-only audit of every text-bearing sheet in the installed patch.

    This deliberately discovers sheets from the game's current ``root.exl``.
    It therefore also detects new schemas/pages introduced by a future patch,
    rather than certifying only a hard-coded list from an older build.
    """
    issues = []
    issue_total = 0
    counts = {
        "root_sheets": 0, "indexed_exh": 0, "text_sheets": 0, "pages": 0,
        "rows": 0, "subrows": 0, "string_fields": 0,
    }
    categories = {}

    def report(sheet, detail):
        nonlocal issue_total
        issue_total += 1
        if len(issues) < 200:
            issues.append({"sheet": sheet, "detail": str(detail)})

    try:
        root_names = _root_sheet_names()
        counts["root_sheets"] = len(root_names)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        root_names = []
        report("root.exl", exc)
    names = available_exh_names()
    counts["indexed_exh"] = len(names)
    missing_from_indexes = sorted(set(root_names) - set(names))
    for name in missing_from_indexes:
        report(name, "EXH dichiarato in root.exl ma assente dagli indici SQPACK")
    for name in names:
        try:
            exh = read_file(f"{name}.exh")
            schema = parse_exh(exh)
            string_columns = [i for i, (typ, _) in enumerate(schema["columns"]) if typ == 0]
            if not string_columns:
                continue
            counts["text_sheets"] += 1
            category = translation_category(name)
            categories[category] = categories.get(category, 0) + 1
            for col_index, (typ, offset) in enumerate(schema["columns"]):
                width = _field_width(schema["columns"], col_index, schema["row_size"])
                if typ not in TYPE_WIDTH and not 0x19 <= typ <= 0x20:
                    report(name, f"Tipo colonna EXH sconosciuto 0x{typ:02X}")
                if offset + width > schema["row_size"]:
                    report(name, f"Colonna {col_index} oltre la dimensione riga")
            pages = _page_files(name, schema)
            if len(pages) != schema["page_count"]:
                report(name, f"Trovate {len(pages)} pagine su {schema['page_count']}")
            for _, _, file_name, exd in pages:
                target = _index_entry(file_name)
                target2 = _index2_entry(file_name, target[0]) if target else None
                if target is None:
                    report(name, f"{file_name}: voce index assente")
                elif target2 is None:
                    report(name, f"{file_name}: voce index2 assente")
                elif (target[2], target[3]) != (target2[1], target2[2]):
                    report(name, f"{file_name}: index e index2 non coincidono")
                records = _row_records(exd, schema)
                counts["pages"] += 1
                counts["rows"] += len(records)
                for record in records:
                    counts["subrows"] += len(record["subs"])
                    for sub in record["subs"]:
                        for col_index in string_columns:
                            _raw_string(exd, record, sub["fixed"], schema["columns"], col_index)
                            counts["string_fields"] += 1
        except (OSError, TypeError, ValueError, struct.error) as exc:
            report(name, exc)
    return {
        "success": issue_total == 0,
        "game_version": _game_version(),
        "counts": counts,
        "categories": dict(sorted(categories.items())),
        "issue_count": issue_total,
        "issues": issues,
        "issues_truncated": issue_total > len(issues),
    }


def _make_dat_entry(raw):
    chunks = [raw[i:i + 16000] for i in range(0, len(raw), 16000)] or [b""]
    infos, blocks, block_offset = [], bytearray(), 0
    for chunk in chunks:
        obj = zlib.compressobj(wbits=-15); compressed = obj.compress(chunk) + obj.flush()
        use_raw = len(compressed) >= len(chunk)
        if use_raw:
            # Nel writer SQPACK il blocco raw usa 32000 come sentinel nel
            # campo CompressedSize. Il payload deve quindi essere esteso fino
            # a quel limite; scrivere la sola dimensione reale (24/36 byte
            # per alcune pagine Item) produce EXD che il client può rifiutare
            # con un crash all'avvio.
            c_size = 32000
            payload = chunk + bytes(c_size - len(chunk))
        else:
            payload = compressed
            c_size = len(payload)
        pad = (128 - ((16 + c_size) % 128)) % 128
        infos.append((block_offset, 16 + c_size + pad, len(chunk)))
        blocks.extend(struct.pack("<IIII", 16, 0, c_size, len(chunk)))
        blocks.extend(payload); blocks.extend(bytes(pad)); block_offset += 16 + c_size + pad
    base = 24 + 8 * len(infos); header_len = base + ((128 - base % 128) % 128)
    header = struct.pack("<III", header_len, 2, len(raw)) + struct.pack("<II", (header_len + len(blocks)) // 128, len(blocks) // 128) + struct.pack("<I", len(infos))
    header += b"".join(struct.pack("<IHH", *item) for item in infos)
    header += bytes(header_len - len(header))
    return header + blocks


def _validate_dat_entry(entry, expected_raw):
    """Decode a generated Type-2 entry and verify every block before inject."""
    if len(entry) < 24:
        return False, "Entry SQPACK troppo corta."
    try:
        header_len, entry_type, raw_size = struct.unpack_from("<III", entry, 0)
        block_count = struct.unpack_from("<I", entry, 0x14)[0]
        if entry_type != 2 or raw_size != len(expected_raw) or header_len < 24:
            return False, "Header Type-2 non coerente."
        result = bytearray()
        for i in range(block_count):
            block_offset, _, declared_raw = struct.unpack_from("<IHH", entry, 0x18 + i * 8)
            absolute = header_len + block_offset
            block_header, _, compressed_size, uncompressed_size = struct.unpack_from(
                "<IIII", entry, absolute
            )
            if block_header != 16 or declared_raw != uncompressed_size:
                return False, f"Blocco {i}: header o dimensione dichiarata non validi."
            payload_start = absolute + block_header
            if compressed_size == 32000:
                chunk = entry[payload_start:payload_start + uncompressed_size]
            else:
                payload = entry[payload_start:payload_start + compressed_size]
                try:
                    chunk = zlib.decompress(payload, -15)
                except zlib.error:
                    chunk = zlib.decompress(payload)
            if len(chunk) != uncompressed_size:
                return False, f"Blocco {i}: decompressione di dimensione errata."
            result.extend(chunk)
        if bytes(result) != expected_raw:
            return False, "Roundtrip dei blocchi SQPACK non corrispondente."
        return True, ""
    except (struct.error, zlib.error, ValueError) as exc:
        return False, f"Entry SQPACK non valida: {exc}"


def _game_version():
    game_dir = os.path.dirname(os.path.dirname(SQPACK_DIR))
    version_path = os.path.join(game_dir, "ffxivgame.ver")
    try:
        with open(version_path, encoding="ascii") as handle:
            value = handle.read().strip("\x00\r\n ")
        return value or "unknown"
    except OSError:
        return "unknown"


def game_version():
    """Return the exact version declared by the selected FFXIV install."""
    return _game_version()


def _ensure_versioned_backup(source):
    """Keep adjacent backups tied to the game patch that produced them."""
    if not os.path.isfile(source):
        return
    version = _game_version()
    backup = source + ".bak"
    version_file = backup + ".version"
    stored = None
    try:
        stored = open(version_file, encoding="utf-8").read().strip()
    except OSError:
        pass
    if os.path.exists(backup) and stored != version:
        # A backup with no sidecar cannot safely be attributed to the current
        # patch. Preserve it as legacy and capture a fresh known-good source.
        safe_old = re.sub(r"[^0-9A-Za-z_.-]+", "_", stored or "legacy-unknown")
        rotated = backup + "." + safe_old
        sequence = 2
        while os.path.exists(rotated):
            rotated = backup + "." + safe_old + f".{sequence}"
            sequence += 1
        os.replace(backup, rotated)
        try:
            os.replace(version_file, rotated + ".version")
        except OSError:
            pass
    if not os.path.exists(backup):
        shutil.copy2(source, backup)
        with open(version_file, "w", encoding="utf-8") as handle:
            handle.write(version + "\n")


def restore_sqpack_backups():
    """Restore only backups belonging to the currently installed game patch."""
    pairs = []
    try:
        entries = os.listdir(SQPACK_DIR)
    except OSError as exc:
        return {"error": f"Cartella SQPACK non accessibile: {exc}"}
    for filename in entries:
        if not re.fullmatch(r"[0-9a-f]{6}\.win32\.(?:index2?|dat\d+)\.bak", filename, re.IGNORECASE):
            continue
        backup = os.path.join(SQPACK_DIR, filename)
        source = backup[:-4]
        try:
            stored = open(backup + ".version", encoding="utf-8").read().strip()
            with open(backup, "rb") as handle:
                magic = handle.read(8)
        except OSError as exc:
            return {"error": f"Backup non leggibile o privo della versione: {filename} ({exc})"}
        if stored != _game_version():
            return {"error": f"Backup {filename} appartenente alla patch {stored}, non a {_game_version()}."}
        if magic != b"SqPack\x00\x00":
            return {"error": f"Backup SQPACK non valido: {filename}."}
        pairs.append((source, backup))
    kinds = {"index": False, "index2": False, "dat": False}
    for source, _ in pairs:
        if source.endswith(".index"): kinds["index"] = True
        elif source.endswith(".index2"): kinds["index2"] = True
        elif re.search(r"\.dat\d+$", source): kinds["dat"] = True
    if not all(kinds.values()):
        return {"error": "Set di backup incompleto: servono index, index2 e almeno un DAT."}
    # Restore DATs first; publish their offsets only after the data is in place.
    pairs.sort(key=lambda pair: 1 if pair[0].endswith((".index", ".index2")) else 0)
    for source, backup in pairs:
        shutil.copy2(backup, source)
    _invalidate_index_caches()
    return {"success": True, "restored": [os.path.basename(source) for source, _ in pairs],
            "game_version": _game_version()}


def _index_entry(file_name):
    return _locate_file(file_name)


def _index2_entries(index2_path):
    """Load an index2 hash table once instead of scanning it for every page."""
    cached = _INDEX2_ENTRIES_CACHE.get(index2_path)
    if cached is not None:
        return cached
    entries = {}
    with open(index2_path, "rb") as handle:
        handle.seek(1032)
        table_offset, table_size = struct.unpack("<II", handle.read(8))
        handle.seek(table_offset)
        for i in range(table_size // 8):
            pos = table_offset + i * 8
            chunk = handle.read(8)
            if len(chunk) != 8:
                break
            name_hash, raw = struct.unpack("<II", chunk)
            if raw and raw != 0xFFFFFFFF:
                entries[name_hash] = (
                    pos, (raw & 0x0F) >> 1, (raw & 0xFFFFFFF0) * 8
                )
    _INDEX2_ENTRIES_CACHE[index2_path] = entries
    return entries


def _index2_entry(file_name, index_path=None):
    """Return the matching index2 entry for an EXD path, if present."""
    relative, _, _ = _normalise_game_file(file_name)
    wanted = crc32_lower("exd/" + relative)
    index2_path = (index_path or INDEX_PATH).replace(".index", ".index2")
    try:
        return _index2_entries(index2_path).get(wanted)
    except (OSError, struct.error):
        pass
    return None


def _inject_one(file_name, raw):
    target = _index_entry(file_name)
    if target is None:
        return {"error": f"{file_name} non trovato nell'indice; nessun dato scritto."}
    index_path, entry_pos, dat_idx, old_offset = target
    target2 = _index2_entry(file_name, index_path)
    if target2 is None:
        return {"error": f"{file_name}: voce index2 assente; inject annullato."}
    if (target2[1], target2[2]) != (dat_idx, old_offset):
        return {"error": f"{file_name}: index e index2 non indicano lo stesso DAT/offset; inject annullato."}
    dat_path = _dat_path(index_path, dat_idx)
    old_size = os.path.getsize(dat_path); new_offset = (old_size + 127) & ~127
    entry = _make_dat_entry(raw)
    valid, detail = _validate_dat_entry(entry, raw)
    if not valid:
        return {"error": f"{file_name}: {detail}"}
    with open(index_path, "rb") as idx:
        idx.seek(entry_pos + 8); old_index_value = idx.read(4)
    old_index2_value = None
    index2_path = index_path.replace(".index", ".index2")
    if target2 is not None:
        with open(index2_path, "rb") as idx2:
            idx2.seek(target2[0] + 4); old_index2_value = idx2.read(4)
    try:
        with open(dat_path, "ab") as dat:
            dat.write(bytes(new_offset - old_size)); dat.write(entry)
        if extract_file(dat_idx, new_offset, index_path) != raw:
            raise ValueError("Verifica di rilettura del nuovo blocco SQPACK fallita.")
        encoded = (new_offset // 8) | (dat_idx << 1)
        with open(index_path, "r+b") as idx:
            idx.seek(entry_pos + 8); idx.write(struct.pack("<I", encoded))
        if target2 is not None:
            with open(index2_path, "r+b") as idx2:
                idx2.seek(target2[0] + 4); idx2.write(struct.pack("<I", encoded))
        _invalidate_index_caches(index_path)
        relocated = _index_entry(file_name)
        if relocated is None or (relocated[2], relocated[3]) != (dat_idx, new_offset):
            raise ValueError("L'indice aggiornato non punta al nuovo blocco.")
        if read_file(file_name) != raw:
            raise ValueError("La pagina riletta dall'indice non corrisponde all'EXD compilato.")
        return {
            "file": file_name,
            "old_offset": hex(old_offset),
            "new_offset": hex(new_offset),
            "_rollback": {
                "index_path": index_path, "entry_pos": entry_pos,
                "old_index_value": old_index_value.hex(),
                "index2_path": index2_path if target2 is not None else None,
                "index2_pos": target2[0] if target2 is not None else None,
                "old_index2_value": old_index2_value.hex() if old_index2_value is not None else None,
                "dat_path": dat_path, "old_size": old_size,
            },
        }
    except Exception:
        try:
            with open(dat_path, "r+b") as dat: dat.truncate(old_size)
        except OSError:
            pass
        try:
            with open(index_path, "r+b") as idx:
                idx.seek(entry_pos + 8); idx.write(old_index_value)
            if target2 is not None and old_index2_value is not None:
                with open(index2_path, "r+b") as idx2:
                    idx2.seek(target2[0] + 4); idx2.write(old_index2_value)
        except OSError:
            pass
        _invalidate_index_caches(index_path)
        raise


def _rollback_injection(result):
    rollback = result.get("_rollback") or {}
    try:
        with open(rollback["dat_path"], "r+b") as dat:
            dat.truncate(int(rollback["old_size"]))
        with open(rollback["index_path"], "r+b") as idx:
            idx.seek(int(rollback["entry_pos"]) + 8)
            idx.write(bytes.fromhex(rollback["old_index_value"]))
        if rollback.get("index2_path") and rollback.get("old_index2_value"):
            with open(rollback["index2_path"], "r+b") as idx2:
                idx2.seek(int(rollback["index2_pos"]) + 4)
                idx2.write(bytes.fromhex(rollback["old_index2_value"]))
    finally:
        if rollback.get("index_path"):
            _invalidate_index_caches(rollback["index_path"])


def _prepare_inject_sqpack(exh_name):
    """Validate every input and generated block without writing game files."""
    name = exh_name.lower().replace(".exh", "")
    manifest_path = os.path.join(EXD_DIR, f"{name}.manifest.json")
    if not os.path.exists(manifest_path):
        return {"error": "Manifest compilazione assente. Estrarre e compilare nuovamente il foglio."}
    manifest = json.load(open(manifest_path, encoding="utf-8"))
    if manifest.get("format") != 2 or manifest.get("sheet") != name:
        return {"error": "Manifest obsoleto o riferito a un altro foglio. Ricompilare prima dell'inject."}
    if manifest.get("game_version") != _game_version():
        return {"error": "Il gioco è stato aggiornato dopo la compilazione. Estrarre e ricompilare il foglio."}
    current_exh = read_file(f"{name}.exh")
    if not current_exh or manifest.get("schema_sha256") != hashlib.sha256(current_exh).hexdigest():
        return {"error": "Schema EXH cambiato dopo la compilazione. Estrarre e ricompilare il foglio."}
    schema = parse_exh(current_exh)
    originals = {file_name: original for _, _, file_name, original in _page_files(name, schema)}
    files = manifest.get("files", [])
    if not files:
        return {"error": "Manifest senza file EXD."}
    if set(files) != set(originals):
        return {"error": "Le pagine EXD della patch non corrispondono al manifest. Ricompilare il foglio."}
    results = []
    byte_audit = []
    for file_name in files:
        path = os.path.join(EXD_DIR, file_name)
        if not os.path.isfile(path):
            return {"error": f"File compilato mancante: {file_name}. Nessun inject eseguito."}
        target = _index_entry(file_name)
        if target is None:
            return {"error": f"{file_name} non trovato nell'indice. Nessun inject eseguito."}
        target2 = _index2_entry(file_name, target[0])
        if target2 is None:
            return {"error": f"{file_name}: voce index2 assente. Nessun inject eseguito."}
        if (target[2], target[3]) != (target2[1], target2[2]):
            return {"error": f"{file_name}: index e index2 non coincidono. Nessun inject eseguito."}
        original = originals.get(file_name)
        if manifest.get("source_sha256", {}).get(file_name) != hashlib.sha256(original).hexdigest():
            return {"error": f"{file_name}: sorgente SQPACK cambiata dopo la compilazione. Ricompilare."}
        raw = open(path, "rb").read()
        if manifest.get("output_sha256", {}).get(file_name) != hashlib.sha256(raw).hexdigest():
            return {"error": f"{file_name}: checksum dell'EXD compilato non valido."}
        try:
            _row_records(raw, schema)
        except (ValueError, struct.error) as exc:
            return {"error": f"{file_name}: EXD compilato non valido ({exc})."}
        valid, detail = _validate_dat_entry(_make_dat_entry(raw), raw)
        if not valid:
            return {"error": f"{file_name}: preflight SQPACK fallito ({detail})."}
        results.append((file_name, raw))
        delta = len(raw) - len(original)
        byte_audit.append({
            "file": file_name,
            "original_bytes": len(original),
            "translated_bytes": len(raw),
            "delta_bytes": delta,
            "changed": delta != 0,
            "warning": (f"Dimensione EXD variata di {delta:+d} byte: possibile rischio di crash."
                        if delta else "")
        })
    return {
        "success": True, "name": name, "schema": schema,
        "originals": originals, "prepared": results,
        "byte_audit": byte_audit,
    }


def preflight_inject_sqpack(exh_name):
    """Public read-only inject validation for tests and patch audits."""
    prepared = _prepare_inject_sqpack(exh_name)
    if "error" in prepared:
        return prepared
    return {
        "success": True,
        "sheet": prepared["name"],
        "pages": len(prepared["prepared"]),
        "game_version": _game_version(),
        "byte_audit": prepared["byte_audit"],
        "changed_pages": sum(item["changed"] for item in prepared["byte_audit"]),
    }


def hard_inject_sqpack(exh_name):
    prepared = _prepare_inject_sqpack(exh_name)
    if "error" in prepared:
        return prepared
    results = prepared["prepared"]
    byte_audit = prepared["byte_audit"]
    # Preserve the first known-good state. Existing backups are never replaced.
    # Selected EXD pages can live in dat0, dat1, ...; backing up dat0 alone
    # makes the Studio restore incomplete for sheets stored elsewhere.
    backup_sources = []
    for file_name, _ in results:
        target = _index_entry(file_name)
        if target is not None:
            index_path, _, dat_idx, _ = target
            backup_sources.extend([
                index_path,
                index_path.replace(".index", ".index2"),
                _dat_path(index_path, dat_idx),
            ])
    for source in dict.fromkeys(backup_sources):
        _ensure_versioned_backup(source)
    injected = []
    try:
        for file_name, raw in results:
            result = _inject_one(file_name, raw)
            if "error" in result:
                raise RuntimeError(result["error"])
            injected.append(result)
    except Exception as exc:
        for result in reversed(injected):
            _rollback_injection(result)
        return {"error": f"Inject annullato e rollback eseguito: {exc}"}
    public_injected = [{k: v for k, v in item.items() if k != "_rollback"} for item in injected]
    return {"success": True, "files": public_injected, "pages": len(injected),
            "byte_audit": byte_audit,
            "changed_pages": sum(item["changed"] for item in byte_audit)}
