"""
EXH / EXD Binary Parser
=======================
Parses FFXIV Excel Header (.exh) and Excel Data (.exd) files from raw bytes.
Built entirely from scratch — no external community libraries.
"""
import struct
from dataclasses import dataclass, field
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Column type → fixed size map
# ---------------------------------------------------------------------------
_TYPE_SIZES: dict[int, int] = {
    0x0000: 4,  # String  (4-byte offset into string table)
    0x0001: 1,  # Boolean
    0x0002: 1,  # Int8
    0x0003: 1,  # UInt8
    0x0004: 2,  # Int16
    0x0005: 2,  # UInt16
    0x0006: 4,  # Int32
    0x0007: 4,  # UInt32
    0x0009: 4,  # Float32
    0x000B: 8,  # Int64
    0x000C: 8,  # UInt64
}
# Bit-packed booleans 0x0019 … 0x0038 → stored in 1 shared byte per group of 8
for _t in range(0x0019, 0x0039):
    _TYPE_SIZES[_t] = 1


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class ColumnDef:
    col_type: int
    offset: int

    @property
    def is_string(self) -> bool:
        return self.col_type == 0x0000

    @property
    def is_bitbool(self) -> bool:
        return 0x0019 <= self.col_type <= 0x0038

    @property
    def size(self) -> int:
        return _TYPE_SIZES.get(self.col_type, 1)


@dataclass
class PageDef:
    start_row_id: int
    row_count: int


@dataclass
class LanguageDef:
    lang_code: int
    padding: int = 0


@dataclass
class EXHSchema:
    magic: bytes
    version: int
    row_size: int
    row_type: int
    depth: int
    row_count: int
    columns: list[ColumnDef] = field(default_factory=list)
    pages: list[PageDef] = field(default_factory=list)
    languages: list[LanguageDef] = field(default_factory=list)


@dataclass
class RowData:
    row_id: int
    values: dict[int, Any] = field(default_factory=dict)   # col_idx -> value
    sub_rows: list[dict] = field(default_factory=list)       # for depth-2 sheets


# ---------------------------------------------------------------------------
# Varint codec (FFXIV custom variable-length integer)
# ---------------------------------------------------------------------------
def decode_varint(data: bytes, index: int) -> tuple[int, int]:
    """Decode a varint starting at *index*. Returns (value, bytes_consumed)."""
    if index >= len(data):
        raise ValueError(f"decode_varint: index {index} out of bounds (len={len(data)})")
    b = data[index]
    if b == 0x00:
        raise ValueError("decode_varint: illegal 0x00 byte")
    if b < 0xF0:
        return b - 1, 1
    if b == 0xF0:
        if index + 1 >= len(data):
            raise ValueError("decode_varint: truncated 0xF0 prefix")
        return data[index + 1], 2
    if b == 0xF1:
        if index + 2 >= len(data):
            raise ValueError("decode_varint: truncated 0xF1 prefix")
        return struct.unpack(">H", data[index + 1: index + 3])[0], 3
    if b == 0xF2:
        if index + 3 >= len(data):
            raise ValueError("decode_varint: truncated 0xF2 prefix")
        v = (data[index + 1] << 16) | (data[index + 2] << 8) | data[index + 3]
        return v, 4
    if b in (0xF6, 0xFE):
        if index + 4 >= len(data):
            raise ValueError("decode_varint: truncated 0xF6/0xFE prefix")
        return struct.unpack(">I", data[index + 1: index + 5])[0], 5
    raise ValueError(f"decode_varint: unknown prefix 0x{b:02X} at index {index}")


def encode_varint(value: int) -> bytes:
    """Encode a non-negative integer into FFXIV varint bytes."""
    if value < 0:
        raise ValueError("encode_varint: value must be non-negative")
    if value <= 238:
        return bytes([value + 1])
    if value <= 0xFF:
        return bytes([0xF0, value])
    if value <= 0xFFFF:
        return struct.pack(">BH", 0xF1, value)
    if value <= 0xFFFFFF:
        return bytes([0xF2, (value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF])
    if value <= 0xFFFFFFFF:
        return struct.pack(">BI", 0xF6, value)
    raise ValueError(f"encode_varint: value {value} exceeds 32-bit maximum")


# ---------------------------------------------------------------------------
# EXH parser
# ---------------------------------------------------------------------------
class EXHParser:
    """Parse a raw EXH binary buffer into an EXHSchema."""

    MAGIC = b"EXHF"
    HEADER_FMT = ">4sHHHHHHBBHIII"  # 32 bytes
    HEADER_SIZE = struct.calcsize(HEADER_FMT)

    def __init__(self, data: bytes):
        self.data = data
        self.schema: Optional[EXHSchema] = None
        self._parse()

    def _parse(self):
        if len(self.data) < self.HEADER_SIZE:
            raise ValueError(f"EXH data too short: {len(self.data)} < {self.HEADER_SIZE}")

        fields = struct.unpack(self.HEADER_FMT, self.data[: self.HEADER_SIZE])
        magic, version, row_size, col_count, page_count, lang_count, \
            _r1, row_type, depth_raw, _r2, row_count, _r3, _r4 = fields

        if magic != self.MAGIC:
            raise ValueError(f"Invalid EXH magic: {magic!r}")

        depth = depth_raw + 1

        expected_min = self.HEADER_SIZE + col_count * 4 + page_count * 8 + lang_count * 2
        if len(self.data) < expected_min:
            raise ValueError(f"EXH data truncated: expected at least {expected_min} bytes")

        offset = self.HEADER_SIZE
        columns = []
        for _ in range(col_count):
            ctype, coffset = struct.unpack(">HH", self.data[offset: offset + 4])
            columns.append(ColumnDef(col_type=ctype, offset=coffset))
            offset += 4

        pages = []
        for _ in range(page_count):
            start_id, rc = struct.unpack(">II", self.data[offset: offset + 8])
            pages.append(PageDef(start_row_id=start_id, row_count=rc))
            offset += 8

        languages = []
        for _ in range(lang_count):
            lcode, pad = struct.unpack(">BB", self.data[offset: offset + 2])
            languages.append(LanguageDef(lang_code=lcode, padding=pad))
            offset += 2

        self.schema = EXHSchema(
            magic=magic, version=version, row_size=row_size,
            row_type=row_type, depth=depth, row_count=row_count,
            columns=columns, pages=pages, languages=languages,
        )

    @property
    def result(self) -> EXHSchema:
        return self.schema


# ---------------------------------------------------------------------------
# EXD parser
# ---------------------------------------------------------------------------
class EXDParser:
    """Parse a raw EXD binary buffer into a list of RowData objects."""

    MAGIC = b"EXDF"
    HEADER_FMT = ">4sHHII16s"  # 32 bytes
    HEADER_SIZE = struct.calcsize(HEADER_FMT)

    def __init__(self, data: bytes, schema: EXHSchema):
        self.data = data
        self.schema = schema
        self._index: list[dict] = []
        self.rows: list[RowData] = []
        self._parse()

    def _parse(self):
        if len(self.data) < self.HEADER_SIZE:
            raise ValueError(f"EXD data too short: {len(self.data)} < {self.HEADER_SIZE}")

        magic, version, _res, idx_size, _data_size, _pad = struct.unpack(
            self.HEADER_FMT, self.data[: self.HEADER_SIZE]
        )
        if magic != self.MAGIC:
            raise ValueError(f"Invalid EXD magic: {magic!r}")

        if len(self.data) < self.HEADER_SIZE + idx_size:
            raise ValueError("EXD index table truncated")

        offset = self.HEADER_SIZE
        idx_count = idx_size // 8
        for _ in range(idx_count):
            row_id, row_off = struct.unpack(">II", self.data[offset: offset + 8])
            self._index.append({"row_id": row_id, "offset": row_off})
            offset += 8

        for entry in self._index:
            self.rows.append(self._parse_row(entry["row_id"], entry["offset"]))

    def _parse_row(self, row_id: int, row_offset: int) -> RowData:
        if row_offset + 6 > len(self.data):
            raise ValueError(f"Row {row_id}: offset {row_offset} out of bounds")
        data_size, sub_row_count = struct.unpack(">IH", self.data[row_offset: row_offset + 6])
        row_end = row_offset + 6 + data_size

        if self.schema.row_type == 1:
            values = self._parse_flat_values(row_offset + 6, row_end)
            return RowData(row_id=row_id, values=values)
        else:
            sub_rows = self._parse_sub_rows(row_offset + 6, row_end, sub_row_count)
            return RowData(row_id=row_id, sub_rows=sub_rows)

    def _parse_flat_values(self, data_start: int, row_end: int) -> dict[int, Any]:
        row_size = self.schema.row_size
        fixed_data = self.data[data_start: data_start + row_size]
        string_table = self.data[data_start + row_size: row_end]
        return self._decode_columns(fixed_data, string_table)

    def _parse_sub_rows(self, data_start: int, row_end: int, count: int) -> list[dict]:
        sub_rows = []
        ptr = data_start
        row_size = self.schema.row_size
        for _ in range(count):
            if ptr + 2 > row_end:
                raise ValueError("Sub-row ID out of bounds")
            sub_id = struct.unpack(">H", self.data[ptr: ptr + 2])[0]
            # Column offsets are relative to the start of the sub-row (ptr), which overlaps with sub_row_id
            fixed_data = self.data[ptr: ptr + row_size]

            # Find sub-row string table end by scanning for null terminator after last string
            string_offsets = []
            for col in self.schema.columns:
                if col.is_string:
                    val_32 = struct.unpack(">I", fixed_data[col.offset: col.offset + 4])[0]
                    # Check if standard 32-bit offset or shifted
                    if val_32 < row_end - (ptr + row_size):
                        str_off = val_32
                    else:
                        str_off = val_32 >> 16
                    string_offsets.append(str_off)
            str_table_start = ptr + row_size
            if not string_offsets:
                str_table_end = str_table_start
            else:
                scan = str_table_start + max(string_offsets)
                while scan < row_end and self.data[scan] != 0:
                    scan += 1
                str_table_end = scan + 1  # include null terminator

            string_table = self.data[str_table_start: str_table_end]
            values = self._decode_columns(fixed_data, string_table)
            sub_rows.append({"sub_row_id": sub_id, "values": values})
            ptr = str_table_end

        return sub_rows

    def _decode_columns(self, fixed_data: bytes, string_table: bytes) -> dict[int, Any]:
        values: dict[int, Any] = {}
        for idx, col in enumerate(self.schema.columns):
            values[idx] = self._decode_col(fixed_data, string_table, col)
        return values

    def _decode_col(self, fixed_data: bytes, string_table: bytes, col: ColumnDef) -> Any:
        ct, off = col.col_type, col.offset
        if ct == 0x0000:  # String
            # FFXIV string pointers are 4 bytes. In some files they are shifted to the upper 16 bits,
            # in others (like sub-rows or flat quest files) they are stored as standard 32-bit offsets.
            val_32 = struct.unpack(">I", fixed_data[off: off + 4])[0]
            # If the offset fits in the string table, use it. If shifted, shift down.
            if val_32 < len(string_table):
                str_off = val_32
            else:
                str_off = val_32 >> 16
            
            end = str_off
            while end < len(string_table) and string_table[end] != 0:
                end += 1
            return bytes(string_table[str_off: end])
        if ct == 0x0001:
            return fixed_data[off] != 0
        if ct == 0x0002:
            return struct.unpack(">b", fixed_data[off: off + 1])[0]
        if ct == 0x0003:
            return fixed_data[off]
        if ct == 0x0004:
            return struct.unpack(">h", fixed_data[off: off + 2])[0]
        if ct == 0x0005:
            return struct.unpack(">H", fixed_data[off: off + 2])[0]
        if ct == 0x0006:
            return struct.unpack(">i", fixed_data[off: off + 4])[0]
        if ct == 0x0007:
            return struct.unpack(">I", fixed_data[off: off + 4])[0]
        if ct == 0x0009:
            return struct.unpack(">f", fixed_data[off: off + 4])[0]
        if ct == 0x000B:
            return struct.unpack(">q", fixed_data[off: off + 8])[0]
        if ct == 0x000C:
            return struct.unpack(">Q", fixed_data[off: off + 8])[0]
        if 0x0019 <= ct <= 0x0038:
            bit_index = ct - 0x0019
            byte_off = off + (bit_index // 8)
            bit_in_byte = bit_index % 8
            return ((fixed_data[byte_off] >> bit_in_byte) & 1) != 0
        # Unknown type — return raw bytes
        size = _TYPE_SIZES.get(ct, 1)
        return fixed_data[off: off + size]
