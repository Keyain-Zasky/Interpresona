import struct

def encode_varint(value: int) -> bytes:
    """
    Encodes a non-negative integer into FFXIV variable-length integer byte representation.
    
    Literal Mode (value <= 238):
        Returns a single byte (value + 1). Range of byte: [1, 239] which is < 0xF0.
    Prefix Mode (value > 238):
        0xF0 + 1 byte
        0xF1 + 2 bytes
        0xF2 + 3 bytes
        0xF6 + 4 bytes
    """
    if value < 0:
        raise ValueError("Varint values must be non-negative")
    
    if value <= 238:
        return bytes([value + 1])
    elif value <= 0xFF:
        return struct.pack(">BB", 0xF0, value)
    elif value <= 0xFFFF:
        return struct.pack(">BH", 0xF1, value)
    elif value <= 0xFFFFFF:
        return bytes([0xF2, (value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF])
    elif value <= 0xFFFFFFFF:
        return struct.pack(">BI", 0xF6, value)
    else:
        raise ValueError(f"Value {value} is too large for 4-byte varint encoding")


def generate_control_code(code_type: int, payload: bytes) -> bytes:
    """
    Wraps a payload into an FFXIV dialogue control code envelope:
    0x02 + code_type (1 byte) + payload_length (varint) + payload + 0x03
    """
    length_bytes = encode_varint(len(payload))
    return b'\x02' + bytes([code_type]) + length_bytes + payload + b'\x03'


# Dialogue control code generators
def make_color_control(color_id: int) -> bytes:
    """
    Generates a color change control code (opcode 0x40).
    """
    payload = encode_varint(color_id)
    return generate_control_code(0x40, payload)


def make_character_name_control() -> bytes:
    """
    Generates an active character name control code (opcode 0x17).
    """
    return generate_control_code(0x17, b'')


def make_reset_control() -> bytes:
    """
    Generates a reset style control code (opcode 0x10).
    """
    return generate_control_code(0x10, b'')


def make_conditional_control(condition: bytes, true_branch: bytes, false_branch: bytes) -> bytes:
    """
    Generates an if/conditional control code (opcode 0x28).
    """
    payload = condition + true_branch + false_branch
    return generate_control_code(0x28, payload)


# Expression generators
def encode_integer_expr(val: int) -> bytes:
    """
    Encodes an integer expression (just serialized as a varint).
    """
    return encode_varint(val)


def encode_string_expr(val) -> bytes:
    """
    Encodes a string literal expression (opcode 0xE0).
    """
    if isinstance(val, str):
        val_bytes = val.encode('utf-8')
    else:
        val_bytes = bytes(val)
    return b'\xE0' + encode_varint(len(val_bytes)) + val_bytes


def encode_variable_expr(var_id: int, is_global: bool = False) -> bytes:
    """
    Encodes a variable reference expression (0xE1 for local, 0xE2 for global).
    """
    marker = 0xE2 if is_global else 0xE1
    return bytes([marker]) + encode_varint(var_id)


class MockEXHGenerator:
    """
    Generates mock binary FFXIV Excel Header (EXH) files.
    All data is stored in Big Endian.
    """
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

    def __init__(self, columns, pages, languages, depth=1, row_type=1, row_size=None):
        self.columns = columns  # list of dicts: {'type': int, 'offset': int}
        self.pages = pages      # list of dicts: {'start_id': int, 'row_count': int}
        self.languages = languages  # list of dicts: {'lang_id': int, 'unk': int}
        self.depth = depth
        self.row_type = 2 if depth == 2 else row_type
        
        if row_size is not None:
            self.row_size = row_size
        else:
            self.row_size = self.calculate_row_size()

    def calculate_row_size(self) -> int:
        size = 0
        for col in self.columns:
            col_type = col['type']
            if 0x19 <= col_type <= 0x38:
                col_size = (col_type - 0x19) // 8 + 1
            else:
                col_size = self.TYPE_SIZES.get(col_type, 1)
            size = max(size, col['offset'] + col_size)
        return size

    def generate(self) -> bytes:
        magic = b'EXHF'
        version = 3
        col_count = len(self.columns)
        page_count = len(self.pages)
        lang_count = len(self.languages)
        total_rows = sum(p['row_count'] for p in self.pages)
        
        header = struct.pack(
            ">4sHHHHHHBBHIII",
            magic,
            version,
            self.row_size,
            col_count,
            page_count,
            lang_count,
            0,  # reserved1
            self.row_type,
            self.depth - 1,
            0,  # reserved2
            total_rows,
            0,  # reserved3
            0   # reserved4
        )
        
        body = bytearray()
        for col in self.columns:
            body.extend(struct.pack(">HH", col['type'], col['offset']))
            
        for page in self.pages:
            body.extend(struct.pack(">II", page['start_id'], page['row_count']))
            
        for lang in self.languages:
            body.extend(struct.pack(">BB", lang['lang_id'], lang['unk']))
            
        return bytes(header + body)


class MockEXDGenerator:
    """
    Generates mock binary FFXIV Excel Data (EXD) files.
    All data is stored in Big Endian.
    """
    TYPE_SIZES = MockEXHGenerator.TYPE_SIZES

    def __init__(self, columns, depth=1, row_size=None, version=2):
        self.columns = columns
        self.depth = depth
        self.version = version
        self.rows = []
        
        if row_size is not None:
            self.row_size = row_size
        else:
            self.row_size = self.calculate_row_size()

    def calculate_row_size(self) -> int:
        size = 0
        for col in self.columns:
            col_type = col['type']
            if 0x19 <= col_type <= 0x38:
                col_size = (col_type - 0x19) // 8 + 1
            else:
                col_size = self.TYPE_SIZES.get(col_type, 1)
            size = max(size, col['offset'] + col_size)
        return size

    def add_row(self, row_id, values=None, sub_rows=None):
        """
        If depth == 1:
            values is a list or dict of column values.
        If depth == 2:
            sub_rows is a list of dicts: [{'sub_row_id': int, 'values': list/dict}]
        """
        if self.depth == 1:
            if values is None:
                raise ValueError("values must be provided for depth 1")
            self.rows.append({
                'row_id': row_id,
                'values': values
            })
        else:
            if sub_rows is None:
                raise ValueError("sub_rows must be provided for depth 2")
            self.rows.append({
                'row_id': row_id,
                'sub_rows': sub_rows
            })

    def generate(self) -> bytes:
        self.rows.sort(key=lambda r: r['row_id'])
        row_count = len(self.rows)
        
        offset_table_size = row_count * 8
        current_offset = 32 + offset_table_size
        
        offset_table = bytearray()
        data_table = bytearray()
        
        for row in self.rows:
            row_id = row['row_id']
            offset_table.extend(struct.pack(">II", row_id, current_offset))
            
            if self.depth == 1:
                values = row['values']
                fixed_data = bytearray(self.row_size)
                string_table = bytearray()
                
                for idx, col in enumerate(self.columns):
                    col_type = col['type']
                    col_offset = col['offset']
                    
                    if isinstance(values, dict):
                        val = values.get(idx)
                    else:
                        val = values[idx]
                        
                    if col_type == 0:  # String
                        if val is None:
                            val = b""
                        elif isinstance(val, str):
                            val = val.encode('utf-8')
                        str_offset = len(string_table)
                        struct.pack_into(">I", fixed_data, col_offset, str_offset)
                        string_table.extend(val)
                        string_table.append(0)  # Null terminator
                    elif col_type == 1:
                        fixed_data[col_offset] = 1 if val else 0
                    elif col_type == 2:
                        struct.pack_into(">b", fixed_data, col_offset, val or 0)
                    elif col_type == 3:
                        fixed_data[col_offset] = val or 0
                    elif col_type == 4:
                        struct.pack_into(">h", fixed_data, col_offset, val or 0)
                    elif col_type == 5:
                        struct.pack_into(">H", fixed_data, col_offset, val or 0)
                    elif col_type == 6:
                        struct.pack_into(">i", fixed_data, col_offset, val or 0)
                    elif col_type == 7:
                        struct.pack_into(">I", fixed_data, col_offset, val or 0)
                    elif col_type == 9:
                        struct.pack_into(">f", fixed_data, col_offset, val or 0.0)
                    elif col_type == 0x000B:
                        struct.pack_into(">q", fixed_data, col_offset, val or 0)
                    elif col_type == 0x000C:
                        struct.pack_into(">Q", fixed_data, col_offset, val or 0)
                    elif col_type in range(0x19, 0x39):  # Packed Bool
                        bit_index = col_type - 0x19
                        byte_offset = col_offset + (bit_index // 8)
                        bit_in_byte = bit_index % 8
                        if val:
                            fixed_data[byte_offset] |= (1 << bit_in_byte)
                        else:
                            fixed_data[byte_offset] &= ~(1 << bit_in_byte)
                    else:
                        size = self.TYPE_SIZES.get(col_type, 1)
                        if val is None:
                            val = b'\x00' * size
                        fixed_data[col_offset:col_offset+size] = val[:size]
                        
                row_data = fixed_data + string_table
                data_size = len(row_data)
                row_header = struct.pack(">IH", data_size, 1)
                data_table.extend(row_header + row_data)
                current_offset += 6 + data_size
                
            else:  # depth == 2
                sub_rows = row['sub_rows']
                sub_rows_data = bytearray()
                
                for sub_row in sub_rows:
                    sub_row_id = sub_row['sub_row_id']
                    sub_values = sub_row['values']
                    fixed_data = bytearray(self.row_size)
                    # Pad string table to match the sub_row_id offset since they share the same physical bytes
                    string_table = bytearray(sub_row_id)
                    
                    for idx, col in enumerate(self.columns):
                        col_type = col['type']
                        col_offset = col['offset']
                        
                        if isinstance(sub_values, dict):
                            val = sub_values.get(idx)
                        else:
                            val = sub_values[idx]
                            
                        if col_type == 0:  # String
                            if val is None:
                                val = b""
                            elif isinstance(val, str):
                                val = val.encode('utf-8')
                            str_offset = len(string_table)
                            # String offsets are packed in the upper 16 bits
                            struct.pack_into(">I", fixed_data, col_offset, str_offset << 16)
                            string_table.extend(val)
                            string_table.append(0)
                        elif col_type == 1:
                            fixed_data[col_offset] = 1 if val else 0
                        elif col_type == 2:
                            struct.pack_into(">b", fixed_data, col_offset, val or 0)
                        elif col_type == 3:
                            fixed_data[col_offset] = val or 0
                        elif col_type == 4:
                            struct.pack_into(">h", fixed_data, col_offset, val or 0)
                        elif col_type == 5:
                            struct.pack_into(">H", fixed_data, col_offset, val or 0)
                        elif col_type == 6:
                            struct.pack_into(">i", fixed_data, col_offset, val or 0)
                        elif col_type == 7:
                            struct.pack_into(">I", fixed_data, col_offset, val or 0)
                        elif col_type == 9:
                            struct.pack_into(">f", fixed_data, col_offset, val or 0.0)
                        elif col_type == 0x000B:
                            struct.pack_into(">q", fixed_data, col_offset, val or 0)
                        elif col_type == 0x000C:
                            struct.pack_into(">Q", fixed_data, col_offset, val or 0)
                        elif col_type in range(0x19, 0x39):  # Packed Bool
                            bit_index = col_type - 0x19
                            byte_offset = col_offset + (bit_index // 8)
                            bit_in_byte = bit_index % 8
                            if val:
                                fixed_data[byte_offset] |= (1 << bit_in_byte)
                            else:
                                fixed_data[byte_offset] &= ~(1 << bit_in_byte)
                        else:
                            size = self.TYPE_SIZES.get(col_type, 1)
                            if val is None:
                                val = b'\x00' * size
                            fixed_data[col_offset:col_offset+size] = val[:size]
                    
                    # Pack sub_row_id directly at offset 0
                    struct.pack_into(">H", fixed_data, 0, sub_row_id)
                    sub_rows_data.extend(fixed_data + string_table)
                    
                data_size = len(sub_rows_data)
                row_header = struct.pack(">IH", data_size, len(sub_rows))
                data_table.extend(row_header + sub_rows_data)
                current_offset += 6 + data_size
                
        magic = b'EXDF'
        data_table_size = len(data_table)
        
        header = struct.pack(
            ">4sHHII",
            magic,
            self.version,
            2,  # reserved/unknown (usually 2)
            offset_table_size,
            data_table_size
        )
        header += b'\x00' * 16  # padding
        
        return bytes(header + offset_table + data_table)


class MockEXHParser:
    """
    Parses a binary FFXIV Excel Header (EXH) buffer.
    """
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
            raise ValueError("Data too short for EXH header")
            
        (
            self.magic,
            self.version,
            self.row_size,
            self.column_count,
            self.page_count,
            self.language_count,
            _,  # reserved1
            self.row_type,
            depth_raw,
            _,  # reserved2
            self.row_count,
            _,  # reserved3
            _   # reserved4
        ) = struct.unpack(">4sHHHHHHBBHIII", self.data[:32])
        self.depth = depth_raw + 1
        
        if self.magic != b'EXHF':
            raise ValueError(f"Invalid EXH magic: {self.magic}")
            
        offset = 32
        for _ in range(self.column_count):
            col_type, col_offset = struct.unpack(">HH", self.data[offset:offset+4])
            self.columns.append({'type': col_type, 'offset': col_offset})
            offset += 4
            
        for _ in range(self.page_count):
            start_id, row_cnt = struct.unpack(">II", self.data[offset:offset+8])
            self.pages.append({'start_id': start_id, 'row_count': row_cnt})
            offset += 8
            
        for _ in range(self.language_count):
            lang_id, unk = struct.unpack(">BB", self.data[offset:offset+2])
            self.languages.append({'lang_id': lang_id, 'unk': unk})
            offset += 2


class MockEXDParser:
    """
    Parses a binary FFXIV Excel Data (EXD) buffer and extracts row/sub-row structures.
    """
    TYPE_SIZES = MockEXHGenerator.TYPE_SIZES

    def __init__(self, data: bytes, columns, depth=1, row_size=None):
        self.data = data
        self.columns = columns
        self.depth = depth
        self.row_size = row_size if row_size is not None else self.calculate_row_size()
        self.magic = None
        self.version = None
        self.index_table_size = None
        self.data_table_size = None
        self.index_table = []
        self.rows = []
        self.parse()

    def calculate_row_size(self) -> int:
        size = 0
        for col in self.columns:
            col_type = col['type']
            if 0x19 <= col_type <= 0x38:
                col_size = (col_type - 0x19) // 8 + 1
            else:
                col_size = self.TYPE_SIZES.get(col_type, 1)
            size = max(size, col['offset'] + col_size)
        return size

    def parse(self):
        if len(self.data) < 32:
            raise ValueError("Data too short for EXD header")
            
        (
            self.magic,
            self.version,
            reserved,
            self.index_table_size,
            self.data_table_size
        ) = struct.unpack(">4sHHII", self.data[:16])
        
        if self.magic != b'EXDF':
            raise ValueError(f"Invalid EXD magic: {self.magic}")
            
        offset_entries = self.index_table_size // 8
        offset = 32
        for _ in range(offset_entries):
            row_id, row_offset = struct.unpack(">II", self.data[offset:offset+8])
            self.index_table.append({'row_id': row_id, 'offset': row_offset})
            offset += 8
            
        for entry in self.index_table:
            row_id = entry['row_id']
            row_offset = entry['offset']
            
            data_size, sub_row_count = struct.unpack(">IH", self.data[row_offset:row_offset+6])
            
            if self.depth == 1:
                row_data_start = row_offset + 6
                fixed_data = self.data[row_data_start : row_data_start + self.row_size]
                string_table = self.data[row_data_start + self.row_size : row_offset + 6 + data_size]
                
                values = {}
                for idx, col in enumerate(self.columns):
                    col_type = col['type']
                    col_offset = col['offset']
                    
                    if col_type == 0:  # String
                        str_offset = struct.unpack(">I", fixed_data[col_offset:col_offset+4])[0]
                        str_bytes = bytearray()
                        s_idx = str_offset
                        while s_idx < len(string_table) and string_table[s_idx] != 0:
                            str_bytes.append(string_table[s_idx])
                            s_idx += 1
                        values[idx] = bytes(str_bytes)
                    elif col_type == 1:
                        values[idx] = fixed_data[col_offset] != 0
                    elif col_type == 2:
                        values[idx] = struct.unpack(">b", fixed_data[col_offset:col_offset+1])[0]
                    elif col_type == 3:
                        values[idx] = fixed_data[col_offset]
                    elif col_type == 4:
                        values[idx] = struct.unpack(">h", fixed_data[col_offset:col_offset+2])[0]
                    elif col_type == 5:
                        values[idx] = struct.unpack(">H", fixed_data[col_offset:col_offset+2])[0]
                    elif col_type == 6:
                        values[idx] = struct.unpack(">i", fixed_data[col_offset:col_offset+4])[0]
                    elif col_type == 7:
                        values[idx] = struct.unpack(">I", fixed_data[col_offset:col_offset+4])[0]
                    elif col_type == 9:
                        values[idx] = struct.unpack(">f", fixed_data[col_offset:col_offset+4])[0]
                    elif col_type == 0x000B:
                        values[idx] = struct.unpack(">q", fixed_data[col_offset:col_offset+8])[0]
                    elif col_type == 0x000C:
                        values[idx] = struct.unpack(">Q", fixed_data[col_offset:col_offset+8])[0]
                    elif col_type in range(0x19, 0x39):
                        bit_index = col_type - 0x19
                        byte_offset = col_offset + (bit_index // 8)
                        bit_in_byte = bit_index % 8
                        byte_val = fixed_data[byte_offset]
                        values[idx] = ((byte_val >> bit_in_byte) & 1) != 0
                    else:
                        size = self.TYPE_SIZES.get(col_type, 1)
                        values[idx] = fixed_data[col_offset : col_offset + size]
                        
                self.rows.append({
                    'row_id': row_id,
                    'values': values
                })
                
            else:  # depth == 2
                sub_rows = []
                sub_row_offset = row_offset + 6
                for _ in range(sub_row_count):
                    sub_row_id = struct.unpack(">H", self.data[sub_row_offset:sub_row_offset+2])[0]
                    fixed_data = self.data[sub_row_offset + 2 : sub_row_offset + 2 + self.row_size]
                    
                    string_offsets = []
                    for col in self.columns:
                        if col['type'] == 0:
                            str_offset = struct.unpack(">I", fixed_data[col['offset']:col['offset']+4])[0]
                            string_offsets.append(str_offset)
                            
                    if not string_offsets:
                         sub_row_len = 2 + self.row_size
                    else:
                         max_offset = max(string_offsets)
                         s_idx = sub_row_offset + 2 + self.row_size + max_offset
                         while s_idx < len(self.data) and self.data[s_idx] != 0:
                             s_idx += 1
                         s_idx += 1  # Include null terminator
                         sub_row_len = s_idx - sub_row_offset
                         
                    string_table = self.data[sub_row_offset + 2 + self.row_size : sub_row_offset + sub_row_len]
                    
                    values = {}
                    for idx, col in enumerate(self.columns):
                        col_type = col['type']
                        col_offset = col['offset']
                        
                        if col_type == 0:
                            str_offset = struct.unpack(">I", fixed_data[col_offset:col_offset+4])[0]
                            str_bytes = bytearray()
                            s_idx = str_offset
                            while s_idx < len(string_table) and string_table[s_idx] != 0:
                                str_bytes.append(string_table[s_idx])
                                s_idx += 1
                            values[idx] = bytes(str_bytes)
                        elif col_type == 1:
                            values[idx] = fixed_data[col_offset] != 0
                        elif col_type == 2:
                            values[idx] = struct.unpack(">b", fixed_data[col_offset:col_offset+1])[0]
                        elif col_type == 3:
                            values[idx] = fixed_data[col_offset]
                        elif col_type == 4:
                            values[idx] = struct.unpack(">h", fixed_data[col_offset:col_offset+2])[0]
                        elif col_type == 5:
                            values[idx] = struct.unpack(">H", fixed_data[col_offset:col_offset+2])[0]
                        elif col_type == 6:
                            values[idx] = struct.unpack(">i", fixed_data[col_offset:col_offset+4])[0]
                        elif col_type == 7:
                            values[idx] = struct.unpack(">I", fixed_data[col_offset:col_offset+4])[0]
                        elif col_type == 9:
                            values[idx] = struct.unpack(">f", fixed_data[col_offset:col_offset+4])[0]
                        elif col_type == 0x000B:
                            values[idx] = struct.unpack(">q", fixed_data[col_offset:col_offset+8])[0]
                        elif col_type == 0x000C:
                            values[idx] = struct.unpack(">Q", fixed_data[col_offset:col_offset+8])[0]
                        elif col_type in range(0x19, 0x39):
                            bit_index = col_type - 0x19
                            byte_offset = col_offset + (bit_index // 8)
                            bit_in_byte = bit_index % 8
                            byte_val = fixed_data[byte_offset]
                            values[idx] = ((byte_val >> bit_in_byte) & 1) != 0
                        else:
                            size = self.TYPE_SIZES.get(col_type, 1)
                            values[idx] = fixed_data[col_offset : col_offset + size]
                            
                    sub_rows.append({'sub_row_id': sub_row_id, 'values': values})
                    sub_row_offset += sub_row_len
                    
                self.rows.append({
                    'row_id': row_id,
                    'sub_rows': sub_rows
                })


class ControlCodeParser:
    """
    Parses dialogue control codes using the 0x02/0x03 envelopes with V-Int encoding.
    """
    @classmethod
    def parse_varint(cls, data: bytes, index: int) -> tuple[int, int]:
        """
        Parses a variable-length integer starting at index.
        Returns (value, bytes_consumed).
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
                raise ValueError("Varint out of bounds")
            return data[index+1], 2
        elif b == 0xF1:
            if index + 2 >= len(data):
                raise ValueError("Varint out of bounds")
            val = struct.unpack('>H', data[index+1:index+3])[0]
            return val, 3
        elif b == 0xF2:
            if index + 3 >= len(data):
                raise ValueError("Varint out of bounds")
            val = (data[index+1] << 16) | (data[index+2] << 8) | data[index+3]
            return val, 4
        elif b == 0xF6 or b == 0xFE:
            if index + 4 >= len(data):
                raise ValueError("Varint out of bounds")
            val = struct.unpack('>I', data[index+1:index+5])[0]
            return val, 5
        else:
            raise ValueError(f"Unknown varint prefix {hex(b)} at index {index}")

    @classmethod
    def parse_payload_expressions(cls, payload: bytes) -> list:
        segments = []
        idx = 0
        n = len(payload)
        while idx < n:
            b = payload[idx]
            if b == 0xE0:
                try:
                    length, consumed = cls.parse_varint(payload, idx+1)
                    str_start = idx + 1 + consumed
                    str_end = str_start + length
                    if str_end <= n:
                        sub_str_bytes = payload[str_start:str_end]
                        parsed_sub = cls.parse_string(sub_str_bytes, recursive=True)
                        segments.extend(parsed_sub)
                        idx = str_end
                        continue
                except ValueError:
                    pass
            elif b == 0x02:
                try:
                    if idx + 1 < n:
                        code_type = payload[idx+1]
                        length, consumed = cls.parse_varint(payload, idx+2)
                        p_start = idx + 2 + consumed
                        p_end = p_start + length
                        if p_end < n and payload[p_end] == 0x03:
                            nested_raw = payload[idx:p_end+1]
                            parsed_nested = cls.parse_string(nested_raw, recursive=True)
                            segments.extend(parsed_nested)
                            idx = p_end + 1
                            continue
                except ValueError:
                    pass
            idx += 1
        return segments

    @classmethod
    def parse_string(cls, raw_bytes: bytes, recursive: bool = False) -> list:
        """
        Parses raw bytes of an FFXIV SeString.
        Returns a list of dictionaries representing parsed text and control code segments.
        """
        segments = []
        idx = 0
        n = len(raw_bytes)
        while idx < n:
            if raw_bytes[idx] == 0x02:
                start_idx = idx
                if idx + 1 >= n:
                    raise ValueError("Malformed control code (missing type code)")
                code_type = raw_bytes[idx+1]
                length, consumed = cls.parse_varint(raw_bytes, idx+2)
                payload_start = idx + 2 + consumed
                payload_end = payload_start + length
                if payload_end >= n:
                    raise ValueError("Control code payload out of bounds")
                if raw_bytes[payload_end] != 0x03:
                    raise ValueError(f"Malformed control code: expected 0x03, got {hex(raw_bytes[payload_end])}")
                
                payload = raw_bytes[payload_start:payload_end]
                seg = {
                    'type': 'control',
                    'code': code_type,
                    'payload': payload,
                    'raw': raw_bytes[start_idx:payload_end+1]
                }
                if recursive:
                    seg['nested'] = cls.parse_payload_expressions(payload)
                segments.append(seg)
                idx = payload_end + 1
            else:
                # Parse text segment until 0x02
                start = idx
                while idx < n and raw_bytes[idx] != 0x02:
                    idx += 1
                text_bytes = raw_bytes[start:idx]
                segments.append({
                    'type': 'text',
                    'value': text_bytes.decode('utf-8', errors='replace'),
                    'raw': text_bytes
                })
        return segments
