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
DEFAULT_EXD_DIR = os.path.join(RUNTIME_DIR, "exd")
CATALOG_FILE = os.path.abspath(os.environ.get("INTERPRESONA_ENGINE_CATALOG_FILE", os.path.join(PROJECT_DIR, "app", "ffxiv_sheets.txt")))
BUILTIN_SHEETS = ("addon", "lobby", "item", "quest", "eventtext", "weather", "customtalk")
_SHEET_CATALOG_CACHE = None


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
WORKSPACE_DIR = _saved_settings.get("workspace_dir", DEFAULT_WORKSPACE_DIR)
EXD_DIR = _saved_settings.get("exd_dir", DEFAULT_EXD_DIR)
INDEX_PATH = os.path.join(SQPACK_DIR, "0a0000.win32.index")
CATALOG_DIRS = tuple(dict.fromkeys((CSV_SOURCE_DIR, WORKSPACE_DIR)))
os.makedirs(WORKSPACE_DIR, exist_ok=True)
os.makedirs(EXD_DIR, exist_ok=True)


def settings_snapshot():
    return {"sqpack_dir": SQPACK_DIR, "csv_source_dir": CSV_SOURCE_DIR,
            "workspace_dir": WORKSPACE_DIR, "exd_dir": EXD_DIR,
            "sqpack_ok": os.path.exists(INDEX_PATH),
            "csv_source_ok": os.path.isdir(CSV_SOURCE_DIR),
            "workspace_ok": os.path.isdir(WORKSPACE_DIR),
            "exd_ok": os.path.isdir(EXD_DIR) and os.access(EXD_DIR, os.W_OK)}


def apply_settings(values):
    global SQPACK_DIR, INDEX_PATH, CSV_SOURCE_DIR, WORKSPACE_DIR, EXD_DIR, CATALOG_DIRS, _SHEET_CATALOG_CACHE
    sqpack = os.path.abspath(os.path.expanduser(str(values.get("sqpack_dir", SQPACK_DIR)).strip()))
    csv_source = os.path.abspath(os.path.expanduser(str(values.get("csv_source_dir", CSV_SOURCE_DIR)).strip()))
    workspace = os.path.abspath(os.path.expanduser(str(values.get("workspace_dir", WORKSPACE_DIR)).strip()))
    exd = os.path.abspath(os.path.expanduser(str(values.get("exd_dir", EXD_DIR)).strip()))
    if not sqpack or not csv_source or not workspace or not exd:
        raise ValueError("Tutti i percorsi sono obbligatori.")
    os.makedirs(workspace, exist_ok=True)
    os.makedirs(exd, exist_ok=True)
    SQPACK_DIR, CSV_SOURCE_DIR, WORKSPACE_DIR, EXD_DIR = sqpack, csv_source, workspace, exd
    INDEX_PATH = os.path.join(SQPACK_DIR, "0a0000.win32.index")
    CATALOG_DIRS = tuple(dict.fromkeys((CSV_SOURCE_DIR, WORKSPACE_DIR)))
    _SHEET_CATALOG_CACHE = None
    os.makedirs(os.path.dirname(USER_SETTINGS_PATH), exist_ok=True)
    with open(USER_SETTINGS_PATH, "w", encoding="utf-8") as handle:
        json.dump({"sqpack_dir": SQPACK_DIR, "csv_source_dir": CSV_SOURCE_DIR,
                   "workspace_dir": WORKSPACE_DIR, "exd_dir": EXD_DIR}, handle, indent=2)
    return settings_snapshot()

FOLDER_HASH = binascii.crc32(b"exd") ^ 0xFFFFFFFF
TYPE_WIDTH = {0x00: 4, 0x01: 1, 0x02: 1, 0x03: 1, 0x04: 2,
              0x05: 2, 0x06: 4, 0x07: 4, 0x09: 4}


def crc32_lower(value):
    return binascii.crc32(value.encode("utf-8").lower()) ^ 0xFFFFFFFF


def get_file_offset(file_name):
    wanted = crc32_lower(file_name)
    try:
        with open(INDEX_PATH, "rb") as f:
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


def extract_file(dat_idx, offset):
    """Extract a type-2 SQPACK entry and reject truncated/corrupt entries."""
    if dat_idx is None or offset is None:
        return None
    path = os.path.join(SQPACK_DIR, f"0a0000.win32.dat{dat_idx}")
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
    return extract_file(*get_file_offset(file_name))


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
    for directory in CATALOG_DIRS:
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
        with open(os.path.join(WORKSPACE_DIR, f"{name}.csv"), "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            header = ["RowID"] + (["SubrowID"] if schema["variant"] == 2 else []) + [f"Col_{i}" for i in range(schema["column_count"])]
            writer.writerow(header); writer.writerows(rows)
        with open(get_tags_dict_path(name), "w") as f: json.dump(tags, f, indent=2)
        with open(get_meta_path(name), "w") as f: json.dump({"schema": schema, "rows": meta}, f, indent=2)
        return {"success": True, "rows": len(rows), "tags": len(tags), "file": os.path.join(WORKSPACE_DIR, f"{name}.csv"), "pages": len(pages), "variant": schema["variant"]}
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
    # Tag dictionaries belong to the selected workspace and travel with the CSV.
    # This prevents an unrelated legacy directory from silently changing output.
    tag_source = tags_path
    if not os.path.exists(tag_source):
        return {"error": "Dizionario tag mancante nella workspace selezionata. Rieseguire l'estrazione."}
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
    with open(INDEX_PATH, "rb") as idx:
        idx.seek(entry_pos + 8); old_index_value = idx.read(4)
    old_index2_value = None
    index2_path = INDEX_PATH.replace(".index", ".index2")
    if target2 is not None:
        with open(index2_path, "rb") as idx2:
            idx2.seek(target2[0] + 4); old_index2_value = idx2.read(4)
    try:
        with open(dat_path, "ab") as dat:
            dat.write(bytes(new_offset - old_size)); dat.write(entry)
        encoded = (new_offset // 8) | (dat_idx << 1)
        with open(INDEX_PATH, "r+b") as idx:
            idx.seek(entry_pos + 8); idx.write(struct.pack("<I", encoded))
        if target2 is not None:
            with open(index2_path, "r+b") as idx2:
                idx2.seek(target2[0] + 4); idx2.write(struct.pack("<I", encoded))
        return {"file": file_name, "old_offset": hex(old_offset), "new_offset": hex(new_offset)}
    except Exception:
        try:
            with open(dat_path, "r+b") as dat: dat.truncate(old_size)
        except OSError:
            pass
        try:
            with open(INDEX_PATH, "r+b") as idx:
                idx.seek(entry_pos + 8); idx.write(old_index_value)
            if target2 is not None and old_index2_value is not None:
                with open(index2_path, "r+b") as idx2:
                    idx2.seek(target2[0] + 4); idx2.write(old_index2_value)
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
    # Preserve the first known-good state. Existing backups are never replaced.
    # Selected EXD pages can live in dat0, dat1, ...; backing up dat0 alone
    # makes the Studio restore incomplete for sheets stored elsewhere.
    backup_sources = [INDEX_PATH, INDEX_PATH.replace(".index", ".index2")]
    for file_name, _ in results:
        target = _index_entry(file_name)
        if target is not None:
            backup_sources.append(os.path.join(SQPACK_DIR, f"0a0000.win32.dat{target[1]}"))
    for source in dict.fromkeys(backup_sources):
        backup = source + ".bak"
        if os.path.isfile(source) and not os.path.exists(backup):
            shutil.copy2(source, backup)
    schema = parse_exh(read_file(f"{name}.exh"))
    originals = {file_name: original for _, _, file_name, original in _page_files(name, schema)}
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
            "warning": (f"Dimensione EXD variata di {delta:+d} byte: possibile rischio di crash."
                        if delta else "")
        })
    return {"success": True, "files": injected, "pages": len(injected),
            "byte_audit": byte_audit,
            "changed_pages": sum(item["changed"] for item in byte_audit)}
