"""
EXD Injector
============
Takes a parsed EXDParser result, replaces string column values with new
translated bytes, and serialises the whole thing back to a valid binary EXD.

Key guarantee: only string columns whose values are explicitly overridden are
changed.  All numeric columns, bit-packed booleans, and untouched strings are
written back verbatim, preserving the exact binary layout.
"""
from __future__ import annotations

import struct
from typing import Any

from .parser import EXHSchema, RowData, ColumnDef, encode_varint, _TYPE_SIZES


# ---------------------------------------------------------------------------
# Helper: serialise a single column value into the fixed-data block
# ---------------------------------------------------------------------------

def _pack_col(fixed_data: bytearray, col: ColumnDef, value: Any) -> None:
    """Write *value* for *col* into *fixed_data* in-place."""
    ct, off = col.col_type, col.offset
    if ct == 0x0000:
        # String: the 4-byte value is packed with the offset in the upper 16 bits
        struct.pack_into(">I", fixed_data, off, value << 16)
    elif ct == 0x0001:
        fixed_data[off] = 1 if value else 0
    elif ct == 0x0002:
        struct.pack_into(">b", fixed_data, off, value or 0)
    elif ct == 0x0003:
        fixed_data[off] = value or 0
    elif ct == 0x0004:
        struct.pack_into(">h", fixed_data, off, value or 0)
    elif ct == 0x0005:
        struct.pack_into(">H", fixed_data, off, value or 0)
    elif ct == 0x0006:
        struct.pack_into(">i", fixed_data, off, value or 0)
    elif ct == 0x0007:
        struct.pack_into(">I", fixed_data, off, value or 0)
    elif ct == 0x0009:
        struct.pack_into(">f", fixed_data, off, value or 0.0)
    elif ct == 0x000B:
        struct.pack_into(">q", fixed_data, off, value or 0)
    elif ct == 0x000C:
        struct.pack_into(">Q", fixed_data, off, value or 0)
    elif 0x0019 <= ct <= 0x0038:
        bit_index = ct - 0x0019
        byte_off = off + (bit_index // 8)
        bit_in_byte = bit_index % 8
        if value:
            fixed_data[byte_off] |= (1 << bit_in_byte)
        else:
            fixed_data[byte_off] &= ~(1 << bit_in_byte)
    else:
        size = _TYPE_SIZES.get(ct, 1)
        if value is None:
            value = b"\x00" * size
        fixed_data[off: off + size] = bytes(value)[:size]


# ---------------------------------------------------------------------------
# Build one flat row block
# ---------------------------------------------------------------------------

def _build_flat_row(
    schema: EXHSchema,
    values: dict[int, Any],
    overrides: dict[int, bytes],  # col_idx → new string bytes
) -> bytes:
    """
    Serialise one flat (depth=1) row into bytes:
        row_header (6) + fixed_data (row_size) + string_table
    """
    fixed_data = bytearray(schema.row_size)
    string_table = bytearray()

    for idx, col in enumerate(schema.columns):
        val = overrides.get(idx, values.get(idx))
        if col.is_string:
            if val is None:
                val = b""
            elif isinstance(val, str):
                val = val.encode("utf-8")
            str_off = len(string_table)
            _pack_col(fixed_data, col, str_off)
            string_table.extend(val)
            string_table.append(0)
        else:
            _pack_col(fixed_data, col, val)

    row_payload = bytes(fixed_data) + bytes(string_table)
    row_header = struct.pack(">IH", len(row_payload), 1)
    return row_header + row_payload


# ---------------------------------------------------------------------------
# Build one sub-row block (depth=2)
# ---------------------------------------------------------------------------

def _build_subrow_entry(
    schema: EXHSchema,
    sub_row_id: int,
    values: dict[int, Any],
    overrides: dict[int, bytes],
) -> bytes:
    fixed_data = bytearray(schema.row_size)
    # Pack the sub_row_id into the first 2 bytes of fixed_data
    struct.pack_into(">H", fixed_data, 0, sub_row_id)
    # Pad string table to match the sub_row_id offset since they share the same physical bytes
    string_table = bytearray(sub_row_id)

    for idx, col in enumerate(schema.columns):
        val = overrides.get(idx, values.get(idx))
        if col.is_string:
            if val is None:
                val = b""
            elif isinstance(val, str):
                val = val.encode("utf-8")
            str_off = len(string_table)
            _pack_col(fixed_data, col, str_off)
            string_table.extend(val)
            string_table.append(0)
        else:
            # Skip packing at offset 0 since it is occupied by sub_row_id
            if col.offset >= 2:
                _pack_col(fixed_data, col, val)

    return bytes(fixed_data) + bytes(string_table)


# ---------------------------------------------------------------------------
# Public injector
# ---------------------------------------------------------------------------

class EXDInjector:
    """
    Re-serialises an EXD file with translated string overrides.

    Usage::

        injector = EXDInjector(schema, parsed_rows)
        # overrides: { row_id: { col_idx: new_bytes } }
        injector.apply_overrides(overrides)
        new_binary = injector.build()
    """

    def __init__(self, schema: EXHSchema, rows: list[RowData]):
        self.schema = schema
        self.rows = rows
        self._overrides: dict[int, dict[int, bytes]] = {}

    def apply_overrides(self, overrides: dict[int, dict[int, bytes]]) -> None:
        """
        Set string overrides.
        *overrides* is a mapping:  row_id → { col_idx → new_utf8_bytes }
        For depth-2 sheets, use a compound key tuple (row_id, sub_row_id):
            { (row_id, sub_row_id) → { col_idx → bytes } }
        """
        self._overrides = overrides

    def build(self) -> bytes:
        """Build and return the binary EXD file with overrides applied."""
        sorted_rows = sorted(self.rows, key=lambda r: r.row_id)

        offset_table = bytearray()
        data_table = bytearray()
        current_offset = 32 + len(sorted_rows) * 8  # header + index table

        for row in sorted_rows:
            offset_table.extend(struct.pack(">II", row.row_id, current_offset))

            if self.schema.depth == 1:
                row_overrides = self._overrides.get(row.row_id, {})
                block = _build_flat_row(self.schema, row.values, row_overrides)
            else:
                sub_blocks = bytearray()
                for sub in row.sub_rows:
                    key = (row.row_id, sub["sub_row_id"])
                    sub_overrides = self._overrides.get(key, {})
                    sub_block = _build_subrow_entry(
                        self.schema,
                        sub["sub_row_id"],
                        sub["values"],
                        sub_overrides,
                    )
                    sub_blocks.extend(sub_block)
                row_header = struct.pack(">IH", len(sub_blocks), len(row.sub_rows))
                block = row_header + bytes(sub_blocks)

            data_table.extend(block)
            current_offset += len(block)

        idx_size = len(offset_table)
        data_size = len(data_table)
        header = struct.pack(">4sHHII", b"EXDF", 2, 2, idx_size, data_size)
        header += b"\x00" * 16  # padding

        return header + bytes(offset_table) + bytes(data_table)
