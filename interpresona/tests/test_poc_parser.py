import struct
import pytest
from interpresona.tests.mock_generator import MockEXHGenerator, MockEXDGenerator

# ==============================================================================
# Proof-of-Concept Parser Code
# ==============================================================================

def encode_varint(val: int) -> bytes:
    """Encodes an integer into FFXIV variable-length format."""
    if 0 <= val < 239:
        return bytes([val + 1])
    elif 239 <= val <= 255:
        return bytes([0xF0, val])
    elif 256 <= val <= 65535:
        return b'\xF1' + struct.pack('>H', val)
    elif 65536 <= val <= 16777215:
        return b'\xF2' + bytes([(val >> 16) & 0xFF, (val >> 8) & 0xFF, val & 0xFF])
    elif 16777216 <= val <= 4294967295:
        return b'\xF6' + struct.pack('>I', val)
    else:
        raise ValueError(f"Value out of bounds for varint: {val}")

def decode_varint(data: bytes, index: int = 0) -> tuple[int, int]:
    """
    Decodes an integer from FFXIV variable-length format starting at index.
    
    Returns:
        tuple[int, int]: (decoded_value, bytes_consumed)
    """
    if index >= len(data):
        raise ValueError("Index out of bounds")
    b = data[index]
    if b == 0x00:
        raise ValueError("Invalid varint literal 0x00")
    if b < 0xF0:
        return b - 1, 1
    elif b == 0xF0:
        if index + 1 >= len(data):
            raise ValueError("Truncated varint")
        return data[index+1], 2
    elif b == 0xF1:
        if index + 2 >= len(data):
            raise ValueError("Truncated varint")
        val = struct.unpack('>H', data[index+1:index+3])[0]
        return val, 3
    elif b == 0xF2:
        if index + 3 >= len(data):
            raise ValueError("Truncated varint")
        val = (data[index+1] << 16) | (data[index+2] << 8) | data[index+3]
        return val, 4
    elif b == 0xF6 or b == 0xFE:
        if index + 4 >= len(data):
            raise ValueError("Truncated varint")
        val = struct.unpack('>I', data[index+1:index+5])[0]
        return val, 5
    else:
        raise ValueError(f"Unknown varint prefix {hex(b)} at index {index}")


class EXHParser:
    """Parses binary Excel Header (EXH) metadata files."""
    def __init__(self, data: bytes):
        self.data = data
        self.magic = None
        self.version = None
        self.row_size = None
        self.column_count = None
        self.page_count = None
        self.language_count = None
        self.row_type = None
        self.depth = None
        self.row_count = None
        self.columns = []
        self.pages = []
        self.languages = []
        self.parse()

    def parse(self):
        if len(self.data) < 32:
            raise ValueError("EXH data too short")
            
        try:
            header = struct.unpack('>4sHHHHHHBBHIII', self.data[:32])
        except struct.error as e:
            raise ValueError(f"Malformed EXH header: {e}")
            
        self.magic = header[0]
        if self.magic != b'EXHF':
            raise ValueError(f"Invalid EXH magic: {self.magic}")
            
        self.version = header[1]
        self.row_size = header[2]
        self.column_count = header[3]
        self.page_count = header[4]
        self.language_count = header[5]
        self.row_type = header[7]
        self.depth = header[8] + 1
        self.row_count = header[10]

        expected_size = 32 + (self.column_count * 4) + (self.page_count * 8) + (self.language_count * 2)
        if len(self.data) < expected_size:
            raise struct.error("EXH data truncated for tables")

        offset = 32
        try:
            for _ in range(self.column_count):
                col_type, col_offset = struct.unpack('>HH', self.data[offset:offset+4])
                self.columns.append({'type': col_type, 'offset': col_offset})
                offset += 4

            for _ in range(self.page_count):
                start_id, row_cnt = struct.unpack('>II', self.data[offset:offset+8])
                self.pages.append({'start_id': start_id, 'row_count': row_cnt})
                offset += 8

            for _ in range(self.language_count):
                lang_id, unk = struct.unpack('>BB', self.data[offset:offset+2])
                self.languages.append({'lang_id': lang_id, 'unk': unk})
                offset += 2
        except (struct.error, IndexError) as e:
            raise ValueError(f"Malformed EXH tables: {e}")


class EXDParser:
    """Parses binary Excel Data (EXD) files and resolves columns and strings."""
    TYPE_SIZES = {
        0x0000: 4,  # String
        0x0001: 1,  # Boolean
        0x0002: 1,  # Signed Byte
        0x0003: 1,  # Unsigned Byte
        0x0004: 2,  # Signed Int16
        0x0005: 2,  # Unsigned Int16
        0x0006: 4,  # Signed Int32
        0x0007: 4,  # Unsigned Int32
        0x0009: 4,  # Float
        0x000B: 8,  # Signed Int64
        0x000C: 8,  # Unsigned Int64
    }
    for t in range(0x19, 0x39):
        TYPE_SIZES[t] = 1

    def __init__(self, data: bytes, exh_columns: list, row_size: int, depth: int = 1):
        self.data = data
        self.columns = exh_columns
        self.row_size = row_size
        self.depth = depth
        self.magic = None
        self.version = None
        self.index_table_size = None
        self.data_table_size = None
        self.index_table = []
        self.parse_header()

    def parse_header(self):
        if len(self.data) < 32:
            raise ValueError("EXD data too short")
            
        try:
            header = struct.unpack('>4sHHII16s', self.data[:32])
        except struct.error as e:
            raise ValueError(f"Malformed EXD header: {e}")
            
        self.magic = header[0]
        if self.magic != b'EXDF':
            raise ValueError(f"Invalid EXD magic: {self.magic}")
            
        self.version = header[1]
        self.index_table_size = header[3]
        self.data_table_size = header[4]

        if len(self.data) < 32 + self.index_table_size:
            raise struct.error("EXD data truncated for index table")

        offset = 32
        index_count = self.index_table_size // 8
        try:
            for _ in range(index_count):
                row_id, row_offset = struct.unpack('>II', self.data[offset:offset+8])
                self.index_table.append({'row_id': row_id, 'offset': row_offset})
                offset += 8
        except (struct.error, IndexError) as e:
            raise ValueError(f"Malformed EXD index table: {e}")

    def parse_rows(self) -> list:
        rows = []
        for entry in self.index_table:
            row_id = entry['row_id']
            row_offset = entry['offset']
            
            if row_offset + 6 > len(self.data):
                raise struct.error(f"Row offset {row_offset} out of bounds")
            
            try:
                data_size, sub_row_count = struct.unpack('>IH', self.data[row_offset:row_offset+6])
            except struct.error as e:
                raise struct.error(f"Malformed row header at offset {row_offset}: {e}")
            
            row_end = min(row_offset + 6 + data_size, len(self.data))
            
            if self.depth == 1:
                row_data_start = row_offset + 6
                if self.row_size > data_size:
                    raise ValueError(f"Row size {self.row_size} exceeds data size {data_size}")
                fixed_data = self.data[row_data_start : row_data_start + self.row_size]
                string_table = self.data[row_data_start + self.row_size : row_end]
                
                values = {}
                for col_idx, col in enumerate(self.columns):
                    col_type = col['type']
                    col_offset = col['offset']
                    
                    if col_type in range(0x19, 0x39):
                        bit_index = col_type - 0x19
                        size = (bit_index // 8) + 1
                    else:
                        size = self.TYPE_SIZES.get(col_type, 1)
                        
                    if col_offset + size > len(fixed_data):
                        raise struct.error(f"Column offset {col_offset} with size {size} exceeds fixed data boundary")
                        
                    try:
                        val = self.parse_column_value(fixed_data, col_type, col_offset, string_table)
                    except (struct.error, IndexError) as e:
                        raise ValueError(f"Failed parsing column value: {e}")
                    values[col_idx] = val
                    
                rows.append({
                    'row_id': row_id,
                    'values': values
                })
            else:
                # depth == 2
                sub_rows = []
                sub_row_offset = row_offset + 6
                for _ in range(sub_row_count):
                    if sub_row_offset + 2 > row_end:
                        raise ValueError("Sub-row ID offset out of row bounds")
                    try:
                        sub_row_id = struct.unpack('>H', self.data[sub_row_offset:sub_row_offset+2])[0]
                    except struct.error as e:
                        raise ValueError(f"Malformed sub-row ID at offset {sub_row_offset}: {e}")
                        
                    if sub_row_offset + 2 + self.row_size > row_end:
                        raise ValueError("Sub-row fixed data out of row bounds")
                    fixed_data = self.data[sub_row_offset + 2 : sub_row_offset + 2 + self.row_size]
                    
                    # Find maximum string offset to find sub-row string table boundary
                    string_offsets = []
                    for col in self.columns:
                        if col['type'] == 0x0000:
                            if col['offset'] + 4 > len(fixed_data):
                                raise ValueError("String column offset out of fixed data bounds")
                            str_offset = struct.unpack('>I', fixed_data[col['offset']:col['offset']+4])[0]
                            string_offsets.append(str_offset)
                            
                    if not string_offsets:
                        sub_row_len = 2 + self.row_size
                    else:
                        max_offset = max(string_offsets)
                        s_idx = sub_row_offset + 2 + self.row_size + max_offset
                        if s_idx >= row_end:
                            raise ValueError(f"String offset {max_offset} out of row bounds")
                        while s_idx < row_end and self.data[s_idx] != 0:
                            s_idx += 1
                        if s_idx >= row_end:
                            raise ValueError("Sub-row string table missing null terminator within row boundary")
                        s_idx += 1  # Include null terminator
                        sub_row_len = s_idx - sub_row_offset
                        
                    if sub_row_offset + sub_row_len > row_end:
                        raise ValueError("Sub-row length exceeds row data bounds")
                        
                    string_table = self.data[sub_row_offset + 2 + self.row_size : sub_row_offset + sub_row_len]
                    
                    values = {}
                    for col_idx, col in enumerate(self.columns):
                        col_type = col['type']
                        col_offset = col['offset']
                        
                        if col_type in range(0x19, 0x39):
                            bit_index = col_type - 0x19
                            size = (bit_index // 8) + 1
                        else:
                            size = self.TYPE_SIZES.get(col_type, 1)
                            
                        if col_offset + size > len(fixed_data):
                            raise ValueError(f"Column offset {col_offset} with size {size} exceeds sub-row fixed data boundary")
                            
                        try:
                            val = self.parse_column_value(fixed_data, col_type, col_offset, string_table)
                        except (struct.error, IndexError) as e:
                            raise ValueError(f"Failed parsing column value: {e}")
                        values[col_idx] = val
                        
                    sub_rows.append({
                        'sub_row_id': sub_row_id,
                        'values': values
                    })
                    sub_row_offset += sub_row_len
                    
                rows.append({
                    'row_id': row_id,
                    'sub_rows': sub_rows
                })
        return rows

    def parse_column_value(self, fixed_data: bytes, col_type: int, col_offset: int, string_table: bytes) -> any:
        if col_type == 0x0000:  # String
            str_offset = struct.unpack(">I", fixed_data[col_offset : col_offset + 4])[0]
            str_bytes = bytearray()
            idx = str_offset
            while idx < len(string_table) and string_table[idx] != 0:
                str_bytes.append(string_table[idx])
                idx += 1
            return bytes(str_bytes)
        elif col_type == 0x0001:  # Bool
            return fixed_data[col_offset] != 0
        elif col_type == 0x0002:  # Int8
            return struct.unpack(">b", fixed_data[col_offset : col_offset + 1])[0]
        elif col_type == 0x0003:  # UInt8
            return fixed_data[col_offset]
        elif col_type == 0x0004:  # Int16
            return struct.unpack(">h", fixed_data[col_offset : col_offset + 2])[0]
        elif col_type == 0x0005:  # UInt16
            return struct.unpack(">H", fixed_data[col_offset : col_offset + 2])[0]
        elif col_type == 0x0006:  # Int32
            return struct.unpack(">i", fixed_data[col_offset : col_offset + 4])[0]
        elif col_type == 0x0007:  # UInt32
            return struct.unpack(">I", fixed_data[col_offset : col_offset + 4])[0]
        elif col_type == 0x0009:  # Float32
            return struct.unpack(">f", fixed_data[col_offset : col_offset + 4])[0]
        elif col_type == 0x000B:  # Int64
            return struct.unpack(">q", fixed_data[col_offset : col_offset + 8])[0]
        elif col_type == 0x000C:  # UInt64
            return struct.unpack(">Q", fixed_data[col_offset : col_offset + 8])[0]
        elif 0x0019 <= col_type <= 0x0038:  # Bit-packed Boolean
            bit_index = col_type - 0x0019
            byte_offset = col_offset + (bit_index // 8)
            bit_in_byte = bit_index % 8
            byte_val = fixed_data[byte_offset]
            return ((byte_val >> bit_in_byte) & 1) != 0
        else:
            size = self.TYPE_SIZES.get(col_type, 1)
            return fixed_data[col_offset : col_offset + size]


# ==============================================================================
# Pytest Test Cases
# ==============================================================================

def test_varint_roundtrip():
    """Validates variable-length integer encoding/decoding across boundary limits."""
    test_values = [
        0, 1, 42, 127, 237, 238,  # Literal Mode
        239, 240, 255,            # F0 Prefix
        256, 1000, 65535,         # F1 Prefix
        65536, 100000, 16777215,  # F2 Prefix
        16777216, 4294967295      # F6 Prefix
    ]
    for val in test_values:
        encoded = encode_varint(val)
        decoded, consumed = decode_varint(encoded, 0)
        assert decoded == val, f"Varint round-trip mismatch for value {val}"
        assert consumed == len(encoded), f"Consumed byte count mismatch for value {val}"


def test_exh_generator_and_parser():
    """Verifies that MockEXHGenerator output is correctly parsed by EXHParser."""
    columns = [
        {'type': 0x0000, 'offset': 0},  # String
        {'type': 0x0003, 'offset': 4},  # UInt8
        {'type': 0x0005, 'offset': 6},  # UInt16
        {'type': 0x0019, 'offset': 8},  # Bit-packed Bool (bit 0)
        {'type': 0x001A, 'offset': 8},  # Bit-packed Bool (bit 1)
    ]
    pages = [
        {'start_id': 0, 'row_count': 100},
        {'start_id': 100, 'row_count': 50}
    ]
    languages = [
        {'lang_id': 1, 'unk': 0},  # Japanese
        {'lang_id': 2, 'unk': 0}   # English
    ]
    
    # 1. Build flat sheet EXH
    exh_gen = MockEXHGenerator(row_size=10, columns=columns, pages=pages, languages=languages, depth=1)
    exh_data = exh_gen.generate()
    
    # 2. Parse flat sheet EXH
    parser = EXHParser(exh_data)
    assert parser.magic == b'EXHF'
    assert parser.version == 3
    assert parser.row_size == 10
    assert parser.column_count == 5
    assert parser.page_count == 2
    assert parser.language_count == 2
    assert parser.row_type == 1
    assert parser.depth == 1
    assert parser.row_count == 150
    assert parser.columns == columns
    assert parser.pages == pages
    assert parser.languages == languages


def test_exd_flat_generator_and_parser():
    """Verifies that MockEXDGenerator for flat sheets generates valid bytes correctly parsed by EXDParser."""
    columns = [
        {'type': 0x0000, 'offset': 0},  # String column
        {'type': 0x0006, 'offset': 4},  # Int32 column
        {'type': 0x0019, 'offset': 8},  # Bit-packed Bool bit 0
        {'type': 0x001A, 'offset': 8},  # Bit-packed Bool bit 1
    ]
    
    # Create rows
    # String offset is relative to the start of the string table.
    # String 1 starts at 0. String 2 starts at len("Hello") + 1 = 6.
    string1 = b"Hello"
    string2 = b"World!"
    
    exd_gen = MockEXDGenerator(columns, depth=1, row_size=9)
    exd_gen.add_row(row_id=1, values=[string1, 123456, True, False])
    exd_gen.add_row(row_id=2, values=[string2, -98765, False, True])
    
    exd_data = exd_gen.generate()
    
    # Parse back
    parser = EXDParser(exd_data, columns, row_size=9, depth=1)
    assert parser.magic == b'EXDF'
    assert parser.version == 2
    assert len(parser.index_table) == 2
    assert parser.index_table[0]['row_id'] == 1
    assert parser.index_table[1]['row_id'] == 2
    
    rows = parser.parse_rows()
    assert len(rows) == 2
    
    # Verify Row 1
    assert rows[0]['row_id'] == 1
    assert rows[0]['values'][0] == b"Hello"
    assert rows[0]['values'][1] == 123456
    assert rows[0]['values'][2] is True
    assert rows[0]['values'][3] is False
    
    # Verify Row 2
    assert rows[1]['row_id'] == 2
    assert rows[1]['values'][0] == b"World!"
    assert rows[1]['values'][1] == -98765
    assert rows[1]['values'][2] is False
    assert rows[1]['values'][3] is True


def test_exd_subrow_generator_and_parser():
    """Verifies that sub-row EXD sheets (depth=2) are generated and parsed correctly."""
    columns = [
        {'type': 0x0000, 'offset': 0},  # String column
        {'type': 0x0005, 'offset': 4},  # UInt16 column
    ]
    
    sub_rows_1 = [
        {
            'sub_row_id': 0,
            'values': [b"Sub-row 1-0", 100]
        },
        {
            'sub_row_id': 1,
            'values': [b"Sub-row 1-1", 200]
        }
    ]
    
    sub_rows_2 = [
        {
            'sub_row_id': 0,
            'values': [b"Sub-row 2-0", 300]
        }
    ]
    
    exd_gen = MockEXDGenerator(columns, depth=2, row_size=6)
    exd_gen.add_row(row_id=10, sub_rows=sub_rows_1)
    exd_gen.add_row(row_id=20, sub_rows=sub_rows_2)
    
    exd_data = exd_gen.generate()
    
    # Parse back
    parser = EXDParser(exd_data, columns, row_size=6, depth=2)
    assert parser.magic == b'EXDF'
    assert parser.version == 2
    assert len(parser.index_table) == 2
    
    rows = parser.parse_rows()
    assert len(rows) == 2
    
    # Verify Row 10 (2 sub-rows)
    assert rows[0]['row_id'] == 10
    assert len(rows[0]['sub_rows']) == 2
    assert rows[0]['sub_rows'][0]['sub_row_id'] == 0
    assert rows[0]['sub_rows'][0]['values'][0] == b"Sub-row 1-0"
    assert rows[0]['sub_rows'][0]['values'][1] == 100
    assert rows[0]['sub_rows'][1]['sub_row_id'] == 1
    assert rows[0]['sub_rows'][1]['values'][0] == b"Sub-row 1-1"
    assert rows[0]['sub_rows'][1]['values'][1] == 200
    
    # Verify Row 20 (1 sub-row)
    assert rows[1]['row_id'] == 20
    assert len(rows[1]['sub_rows']) == 1
    assert rows[1]['sub_rows'][0]['sub_row_id'] == 0
    assert rows[1]['sub_rows'][0]['values'][0] == b"Sub-row 2-0"
    assert rows[1]['sub_rows'][0]['values'][1] == 300


if __name__ == '__main__':
    try:
        test_varint_roundtrip()
        test_exh_generator_and_parser()
        test_exd_flat_generator_and_parser()
        test_exd_subrow_generator_and_parser()
        print("All tests passed successfully!")
    except Exception as e:
        import traceback
        traceback.print_exc()
        import sys
        sys.exit(1)

