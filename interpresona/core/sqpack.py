"""
SqPack Reader
=============
Reads FFXIV SqPack index + data files to extract raw EXH/EXD bytes.
Built entirely from scratch — no external dependencies beyond Python stdlib.

Architecture:
  SqPackIndex  — parses .index files, maps (folder_crc32, file_crc32) → (dat_id, offset)
  SqPackData   — opens .dat files, decompresses block-encoded file data
  SqPackReader — high-level API: open game dir, read any game-path file, list sheets
"""
from __future__ import annotations

import binascii
import struct
import zlib
from pathlib import Path
from typing import Optional


# ─── Constants ──────────────────────────────────────────────────────────────

SQPACK_MAGIC       = b"SqPack\x00\x00"
BLOCK_UNCOMPRESSED = 32_000   # sentinel: block data is stored verbatim


# ─── Path hashing ────────────────────────────────────────────────────────────

def _crc32(text: str) -> int:
    """FFXIV path hash: bitwise-NOT of CRC32 of lowercased ASCII text.
    
    FFXIV stores path hashes as ~crc32 (inverted CRC32), not plain crc32.
    This applies to both folder hashes and filename hashes stored in .index files.
    """
    return ~binascii.crc32(text.lower().encode("ascii")) & 0xFFFFFFFF


def _split_game_path(game_path: str) -> tuple[str, str]:
    """Split 'exd/quest/60000/sheet.exh' → ('exd/quest/60000', 'sheet.exh')."""
    game_path = game_path.lower().replace("\\", "/").strip("/")
    if "/" in game_path:
        folder, filename = game_path.rsplit("/", 1)
    else:
        folder, filename = "", game_path
    return folder, filename


# ─── SqPackIndex ─────────────────────────────────────────────────────────────

class SqPackIndex:
    """
    Parses a .index file and exposes a hash-based lookup.

    Index file layout:
        [0x000] SqPack header (header_size bytes, typically 0x400)
                  [0x000] magic: b'SqPack\\x00\\x00'
                  [0x00C] header_size: uint32
        [header_size] Segment descriptor 0 (file entries):
                  [+0x00] segment_size: uint32  (bytes, i.e. count × 16)
                  [+0x04] segment_offset: uint32 (absolute file offset of entries)
                  [+0x08] sha1: bytes[20]
        [segment_offset] File entry table:
                  Per entry (16 bytes):
                    file_hash   uint32  CRC32 of lowercase filename
                    folder_hash uint32  CRC32 of lowercase folder
                    data_loc    uint32  encodes dat_id + byte_offset
                    padding     uint32  (0)

    data_loc encoding:
        bit 0:     flag (unused)
        bits [3:1]: dat file index (0‒7)
        bits [31:4]: absolute byte offset in dat file ÷ 128
    """

    ENTRY_SIZE = 16

    def __init__(self, index_path: Path):
        self._path = index_path
        # (folder_hash, file_hash) → (dat_id, byte_offset)
        self._entries: dict[tuple[int, int], tuple[int, int]] = {}
        self._load()

    # ------------------------------------------------------------------
    def _load(self):
        raw = self._path.read_bytes()

        if len(raw) < 0x410:
            raise ValueError(f"Index file too small ({len(raw)} bytes): {self._path}")

        if raw[:8] != SQPACK_MAGIC:
            raise ValueError(f"Not a SqPack file — bad magic: {self._path}")

        # SqPack header size (at 0x0C)
        header_size = struct.unpack_from("<I", raw, 0x0C)[0]
        if header_size < 0x10 or header_size > len(raw):
            header_size = 0x400  # safe default

        # Segment descriptor layout (immediately after SqPack header):
        #   [+0x00] unknown / sub-header size
        #   [+0x04] flags / type (1 = file entries)
        #   [+0x08] segment_offset: absolute file offset of the file-entry table
        #   [+0x0C] segment_size:   byte length of the file-entry table
        #   [+0x10] sha1[20 bytes]
        # This is the standard retail FFXIV index format.
        seg_offset = struct.unpack_from("<I", raw, header_size + 0x08)[0]
        seg_size   = struct.unpack_from("<I", raw, header_size + 0x0C)[0]

        # If primary layout is invalid, try the legacy [size, offset] order
        if not self._valid_segment(raw, seg_offset, seg_size):
            seg_size   = struct.unpack_from("<I", raw, header_size + 0x00)[0]
            seg_offset = struct.unpack_from("<I", raw, header_size + 0x04)[0]

        if not self._valid_segment(raw, seg_offset, seg_size):
            # Last-resort: entries typically start at 0x800
            seg_offset = 0x800
            available = len(raw) - seg_offset
            seg_size = available - (available % self.ENTRY_SIZE)

        self._parse_entries(raw, seg_offset, seg_size)

    def _valid_segment(self, raw: bytes, offset: int, size: int) -> bool:
        return (
            offset >= 0x400
            and size > 0
            and size % self.ENTRY_SIZE == 0
            and offset + size <= len(raw)
        )

    def _parse_entries(self, raw: bytes, offset: int, size: int):
        count = size // self.ENTRY_SIZE
        for i in range(count):
            base = offset + i * self.ENTRY_SIZE
            file_hash, folder_hash, data_loc, padding = struct.unpack_from(
                "<IIII", raw, base
            )
            # Skip empty / deleted entries
            if padding != 0 or data_loc == 0 or data_loc == 0xFFFF_FFFF:
                continue

            dat_id      = (data_loc >> 1) & 0x7
            byte_offset = (data_loc >> 4) * 128

            self._entries[(folder_hash, file_hash)] = (dat_id, byte_offset)

    # ------------------------------------------------------------------
    def lookup(self, game_path: str) -> Optional[tuple[int, int]]:
        """Return (dat_id, byte_offset) for a game path, or None."""
        folder, filename = _split_game_path(game_path)
        key = (_crc32(folder), _crc32(filename))
        return self._entries.get(key)

    def file_exists(self, game_path: str) -> bool:
        return self.lookup(game_path) is not None

    @property
    def entry_count(self) -> int:
        return len(self._entries)


# ─── SqPackData ──────────────────────────────────────────────────────────────

class SqPackData:
    """
    Reads and decompresses files from .dat archives.

    File layout at an entry's byte_offset:
        [+0x00] header_size:   uint32   size of file-info header (incl. block list)
        [+0x04] file_type:     uint32   1=empty, 2=standard, 3=model, 4=texture
        [+0x08] raw_size:      uint32   total decompressed size
        [+0x0C] unknown:       uint32
        [+0x10] block_buf_sz:  uint32   max block decompressed size (e.g. 0x4000)
        [+0x14] block_count:   uint32

        Followed by block_count × 8-byte block entries:
          block_offset:     uint32   offset of block data from file header start
          compressed_sz:    uint16   compressed block size (32000 = uncompressed)
          decompressed_sz:  uint16

        Each block at (base + block_offset):
          blk_header_sz:    uint32   (usually 0x10)
          unknown:          uint32
          compressed_sz:    uint32
          decompressed_sz:  uint32
          data:             bytes    (raw deflate or verbatim)
    """

    def __init__(self, dat_files: dict[int, Path]):
        self._dats = dat_files  # {dat_id: Path}

    def read_file(self, dat_id: int, byte_offset: int) -> bytes:
        dat_path = self._dats.get(dat_id)
        if dat_path is None:
            raise FileNotFoundError(f"DAT file {dat_id} not available")
        raw = dat_path.read_bytes()
        return self._decompress(raw, byte_offset)

    # ------------------------------------------------------------------
    def _decompress(self, raw: bytes, base: int) -> bytes:
        if base + 24 > len(raw):
            raise ValueError(f"File offset 0x{base:X} exceeds DAT size {len(raw)}")

        header_size, file_type, raw_size, _unk = struct.unpack_from("<IIII", raw, base)

        if file_type == 1:
            return b""
        if file_type != 2:
            raise ValueError(f"Unsupported SqPack file type {file_type} at 0x{base:X}")

        _block_buf, block_count = struct.unpack_from("<II", raw, base + 0x10)

        # Block entries (8 bytes each) start at base + 0x18
        blocks: list[tuple[int, int, int]] = []
        for i in range(block_count):
            entry_off = base + 0x18 + i * 8
            if entry_off + 8 > len(raw):
                break
            blk_off, cmp_sz, decmp_sz = struct.unpack_from("<IHH", raw, entry_off)
            blocks.append((blk_off, cmp_sz, decmp_sz))

        result = bytearray()
        for blk_off, _, _ in blocks:
            # Block offsets are relative to (base + header_size), not base
            abs_blk = base + header_size + blk_off
            if abs_blk + 16 > len(raw):
                raise ValueError(f"Block at 0x{abs_blk:X} out of bounds")

            blk_hdr_sz, _unk2, blk_cmp, blk_decmp = struct.unpack_from(
                "<IIII", raw, abs_blk
            )
            data_start = abs_blk + blk_hdr_sz

            if blk_cmp == BLOCK_UNCOMPRESSED:
                result.extend(raw[data_start: data_start + blk_decmp])
            else:
                chunk = raw[data_start: data_start + blk_cmp]
                try:
                    result.extend(zlib.decompress(chunk, -15))  # raw deflate
                except zlib.error:
                    result.extend(zlib.decompress(chunk))        # zlib wrapper

        return bytes(result)



# ─── SqPackReader (high-level) ────────────────────────────────────────────────

class SqPackReader:
    """
    High-level entry point.  Combines SqPackIndex + SqPackData.

    Typical usage::

        reader = SqPackReader.from_game_directory(Path('C:/ff14'))
        exh_bytes = reader.read_file('exd/NpcYell.exh')
        exd_bytes = reader.read_file('exd/NpcYell_0.en.exd')
        sheets    = reader.list_exd_sheets()   # reads exd/root.exl
    """

    def __init__(self, index: SqPackIndex, data: SqPackData):
        self._index = index
        self._data = data
        self._archives: list[tuple[SqPackIndex, SqPackData]] = []

    def mount_archive(self, index: SqPackIndex, data: SqPackData):
        self._archives.append((index, data))

    # ------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------

    @classmethod
    def from_sqpack_dir(cls, sqpack_dir: Path, category: str = "exd") -> "SqPackReader":
        """
        Loads SqPack index and data files from a directory by scanning for all index files
        (e.g., exd.index, 0a0000.win32.index, 0c0100.win32.index, etc.) and loading their associated dat files.
        """
        # Determine paths to scan
        retail_dir = sqpack_dir / "ffxiv"
        custom_dir = sqpack_dir / category
        
        scan_dirs = []
        if retail_dir.exists():
            scan_dirs.append(retail_dir)
        if custom_dir.exists():
            scan_dirs.append(custom_dir)
        if sqpack_dir.exists() and sqpack_dir not in scan_dirs:
            scan_dirs.append(sqpack_dir)

        # Scan for all index files in candidate directories
        index_files: list[Path] = []
        for d in scan_dirs:
            for pattern in ("*.index", "*.win32.index"):
                for p in d.glob(pattern):
                    if p.is_file() and p not in index_files:
                        index_files.append(p)

        if not index_files:
            raise FileNotFoundError(
                f"Could not find any SqPack index files (.index or .win32.index) inside {sqpack_dir}.\n"
                f"Please ensure you selected the correct FFXIV 'sqpack' folder or game directory."
            )

        # Load first index file as primary
        primary_index_path = index_files[0]
        primary_prefix = primary_index_path.name.split(".")[0]
        primary_dir = primary_index_path.parent
        
        # Load primary dat files
        primary_dats: dict[int, Path] = {}
        for i in range(8):
            for pattern in (f"{primary_prefix}.dat{i}", f"{primary_prefix}.win32.dat{i}"):
                p = primary_dir / pattern
                if p.exists():
                    primary_dats[i] = p
                    break

        reader = cls(SqPackIndex(primary_index_path), SqPackData(primary_dats))
        
        # Keep track of loaded prefixes to avoid duplicates
        loaded_prefixes = {primary_prefix}

        # Dynamically mount all other discovered index and dat files in the scanned directories
        for index_path in index_files[1:]:
            prefix = index_path.name.split(".")[0]
            if prefix in loaded_prefixes:
                continue
            
            d = index_path.parent
            dats: dict[int, Path] = {}
            for i in range(8):
                for pattern in (f"{prefix}.dat{i}", f"{prefix}.win32.dat{i}"):
                    p = d / pattern
                    if p.exists():
                        dats[i] = p
                        break
            
            if dats:
                reader.mount_archive(SqPackIndex(index_path), SqPackData(dats))
                loaded_prefixes.add(prefix)

        return reader

    @classmethod
    def from_game_directory(cls, game_dir: Path) -> "SqPackReader":
        """
        Auto-detect the sqpack directory inside the given game root.
        Performs a recursive search for index files if not found immediately.
        """
        # 1. Direct candidates checking first
        for candidate in (
            game_dir / "game" / "sqpack",
            game_dir / "sqpack",
            game_dir,
        ):
            if candidate.exists():
                if list(candidate.glob("*.index")) or list(candidate.glob("*.win32.index")) or \
                   (candidate / "ffxiv").exists() or (candidate / "exd").exists():
                    return cls.from_sqpack_dir(candidate, "exd")

        # 2. Fallback deep recursive scanner to find the folder containing index files
        # We look for ffxiv or exd subfolders, or any folder containing win32.index
        for p in game_dir.rglob("*.win32.index"):
            if p.is_file():
                # The folder containing win32.index could be: <sqpack>/ffxiv/ or <sqpack>/exd/ or <sqpack>/
                parent = p.parent
                if parent.name in ("ffxiv", "exd"):
                    return cls.from_sqpack_dir(parent.parent, "exd")
                return cls.from_sqpack_dir(parent, "exd")

        # 3. Last fallback: check for any .index file recursively
        for p in game_dir.rglob("*.index"):
            if p.is_file():
                parent = p.parent
                if parent.name in ("ffxiv", "exd"):
                    return cls.from_sqpack_dir(parent.parent, "exd")
                return cls.from_sqpack_dir(parent, "exd")

        raise FileNotFoundError(
            f"Could not find any SqPack index files inside {game_dir}.\n"
            f"Expected game folder layout containing 'sqpack' subdirectories or .index files."
        )

    # ------------------------------------------------------------------
    # File access
    # ------------------------------------------------------------------

    def read_file(self, game_path: str) -> bytes:
        # 1. Lookup in main index
        loc = self._index.lookup(game_path)
        if loc is not None:
            dat_id, byte_offset = loc
            return self._data.read_file(dat_id, byte_offset)

        # 2. Fallback to mounted archives (common, quest, etc.)
        for index, data in self._archives:
            loc = index.lookup(game_path)
            if loc is not None:
                dat_id, byte_offset = loc
                return data.read_file(dat_id, byte_offset)

        raise FileNotFoundError(
            f"Not found in SqPack index: {game_path!r}\n"
            f"(indexes have {self.entry_count} entries)"
        )

    def file_exists(self, game_path: str) -> bool:
        if self._index.lookup(game_path) is not None:
            return True
        for index, _ in self._archives:
            if index.lookup(game_path) is not None:
                return True
        return False

    @property
    def entry_count(self) -> int:
        total = len(self._index._entries)
        for index, _ in self._archives:
            total += len(index._entries)
        return total

    # ------------------------------------------------------------------
    # Sheet discovery
    # ------------------------------------------------------------------

    def list_exd_sheets(self) -> list[str]:
        """
        Parse exd/root.exl and return sorted sheet names.

        root.exl format:
            EXLT,2
            NpcYell,0
            Quest/60000/OpeningChapter_00636,1
            ...
        Column 1 = sheet name, column 2 = row type (ignored here).
        """
        try:
            raw = self.read_file("exd/root.exl")
            text = raw.decode("utf-8-sig", errors="replace")
        except Exception:
            return []

        sheets: list[str] = []
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("EXLT"):
                continue
            if "," in line:
                name = line.split(",", 1)[0].strip()
            else:
                name = line.strip()
            if name:
                sheets.append(name)
        return sorted(sheets, key=str.lower)

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    @staticmethod
    def exh_path(sheet_name: str) -> str:
        """'NpcYell' → 'exd/NpcYell.exh'"""
        return f"exd/{sheet_name}.exh"

    @staticmethod
    def exd_path(sheet_name: str, page: int = 0, lang: str = "en") -> str:
        """'NpcYell', 0, 'en' → 'exd/NpcYell_0_en.exd'"""
        if lang and lang.lower() != "none":
            return f"exd/{sheet_name}_{page}_{lang.lower()}.exd"
        return f"exd/{sheet_name}_{page}.exd"

    @property
    def entry_count(self) -> int:
        return self._index.entry_count
