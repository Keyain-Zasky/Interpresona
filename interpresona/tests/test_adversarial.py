import struct
import pytest
import math
from interpresona.tests.mock_generator import (
    encode_varint as gen_encode_varint,
    ControlCodeParser,
    MockEXHGenerator,
    MockEXDGenerator,
    make_color_control,
    make_character_name_control,
    make_reset_control,
    make_conditional_control,
    encode_variable_expr,
    encode_string_expr
)
from interpresona.tests.test_poc_parser import (
    encode_varint as parser_encode_varint,
    decode_varint as parser_decode_varint,
    EXHParser,
    EXDParser
)

# ==============================================================================
# 1. Varint Edge Cases & Boundaries
# ==============================================================================

def test_varint_negative_and_overflow():
    """Test how encoding functions handle negative values and overflows."""
    # Test parser_encode_varint negative and huge inputs
    with pytest.raises(ValueError):
        parser_encode_varint(-1)
    
    with pytest.raises(ValueError):
        parser_encode_varint(-1000)

    with pytest.raises(ValueError):
        parser_encode_varint(4294967296)  # 2^32 (overflow)

    with pytest.raises(ValueError):
        parser_encode_varint(99999999999)  # Huge integer

    # Test gen_encode_varint negative and huge inputs
    with pytest.raises(ValueError):
        gen_encode_varint(-1)
        
    with pytest.raises(ValueError):
        gen_encode_varint(4294967296)


def test_varint_decoder_oob():
    """Test how decoding functions handle truncated or out-of-bounds buffers."""
    # Truncated F0 prefix (requires 2 bytes, got 1)
    with pytest.raises((IndexError, ValueError)):
        parser_decode_varint(b'\xF0')
        
    with pytest.raises(ValueError):
        ControlCodeParser.parse_varint(b'\xF0', 0)

    # Truncated F1 prefix (requires 3 bytes, got 2)
    with pytest.raises((struct.error, ValueError)):
        parser_decode_varint(b'\xF1\x00')
        
    with pytest.raises(ValueError):
        ControlCodeParser.parse_varint(b'\xF1\x00', 0)

    # Truncated F2 prefix (requires 4 bytes, got 3)
    with pytest.raises((IndexError, ValueError)):
        parser_decode_varint(b'\xF2\x00\x00')
        
    with pytest.raises(ValueError):
        ControlCodeParser.parse_varint(b'\xF2\x00\x00', 0)

    # Truncated F6 prefix (requires 5 bytes, got 4)
    with pytest.raises((struct.error, ValueError)):
        parser_decode_varint(b'\xF6\x00\x00\x00')
        
    with pytest.raises(ValueError):
        ControlCodeParser.parse_varint(b'\xF6\x00\x00\x00', 0)


def test_varint_decoder_unknown_prefixes():
    """Test decoding of undefined/reserved prefixes (e.g. 0xF3, 0xFF)."""
    invalid_prefixes = [0xF3, 0xF4, 0xF5, 0xF7, 0xF8, 0xF9, 0xFA, 0xFB, 0xFC, 0xFD, 0xFF]
    for prefix in invalid_prefixes:
        data = bytes([prefix, 0x00, 0x00, 0x00, 0x00])
        with pytest.raises(ValueError) as excinfo:
            parser_decode_varint(data, 0)
        assert "Unknown varint prefix" in str(excinfo.value)
        
        with pytest.raises(ValueError) as excinfo_gen:
            ControlCodeParser.parse_varint(data, 0)
        assert "Unknown varint prefix" in str(excinfo_gen.value)


# ==============================================================================
# 2. Malformed EXH & EXD Files
# ==============================================================================

def test_exh_malformed_headers():
    """Test parser against malformed or short EXH headers."""
    # Empty EXH
    with pytest.raises(ValueError) as excinfo:
        EXHParser(b'')
    assert "EXH data too short" in str(excinfo.value)

    # Short EXH
    with pytest.raises(ValueError) as excinfo:
        EXHParser(b'\x00' * 31)
    assert "EXH data too short" in str(excinfo.value)

    # Invalid Magic
    with pytest.raises(ValueError) as excinfo:
        EXHParser(b'WONG' + b'\x00' * 28)
    assert "Invalid EXH magic" in str(excinfo.value)

    # Header claims 5 columns, but file terminates immediately after header (32 bytes)
    # Magic = EXHF, Version = 3, RowSize = 10, Columns = 5, Pages = 0, Languages = 0, RowType = 1, Depth = 0, RowCount = 0
    header_only = struct.pack(">4sHHHHHHBBHIII", b'EXHF', 3, 10, 5, 0, 0, 0, 1, 0, 0, 0, 0, 0)
    with pytest.raises(struct.error):
        EXHParser(header_only)


def test_exd_malformed_headers():
    """Test parser against malformed or short EXD headers."""
    # Empty EXD
    with pytest.raises(ValueError) as excinfo:
        EXDParser(b'', [], 10)
    assert "EXD data too short" in str(excinfo.value)

    # Short EXD
    with pytest.raises(ValueError) as excinfo:
        EXDParser(b'\x00' * 31, [], 10)
    assert "EXD data too short" in str(excinfo.value)

    # Invalid Magic
    with pytest.raises(ValueError) as excinfo:
        EXDParser(b'WONG' + b'\x00' * 28, [], 10)
    assert "Invalid EXD magic" in str(excinfo.value)

    # Claims large index table size but data is truncated
    # Magic = EXDF, Version = 2, reserved = 2, IndexTableSize = 1000, DataTableSize = 0, padding 16 bytes
    header_only = struct.pack(">4sHHII16s", b'EXDF', 2, 2, 1000, 0, b'\x00' * 16)
    with pytest.raises(struct.error):
        EXDParser(header_only, [], 10)


def test_exd_out_of_bounds_offsets():
    """Test EXD parser where the offset table points to invalid locations."""
    columns = [{'type': 0x0003, 'offset': 0}] # UInt8
    # 32 byte header + 8 bytes index table = 40 bytes total.
    # Index table entry: Row ID = 1, Offset = 9999 (far out of bounds)
    exd_data = struct.pack(">4sHHII16s", b'EXDF', 2, 2, 8, 0, b'\x00' * 16)
    exd_data += struct.pack(">II", 1, 9999)

    parser = EXDParser(exd_data, columns, row_size=1, depth=1)
    with pytest.raises(struct.error):
        parser.parse_rows()


def test_exd_row_data_truncated():
    """Test EXD parser when row headers claim more data than exists."""
    columns = [{'type': 0x0003, 'offset': 0}] # UInt8
    # Row header starts at offset 40.
    # Row Header: Data Size = 1000 (claims 1000 bytes follow), SubRow Count = 1
    exd_data = struct.pack(">4sHHII16s", b'EXDF', 2, 2, 8, 1006, b'\x00' * 16)
    exd_data += struct.pack(">II", 1, 40)
    exd_data += struct.pack(">IH", 1000, 1)
    exd_data += b'\x42' # only 1 byte of actual row data

    parser = EXDParser(exd_data, columns, row_size=1, depth=1)
    # The parser attempts to slice fixed_data = self.data[46 : 46 + 1] -> b'\x42'
    # but string_table is sliced as self.data[47 : 40 + 6 + 1000] -> self.data[47 : 1046] which is empty.
    # Wait, if we check fixed column value, it will read from b'\x42' (offset 0 -> 0x42 = 66)
    rows = parser.parse_rows()
    assert len(rows) == 1
    assert rows[0]['values'][0] == 66
    
    # But if columns require more bytes than available, e.g. row_size is 10, it will return truncated fixed_data
    # and fail when parsing columns. Let's test that:
    columns_large = [{'type': 0x0006, 'offset': 0}] # Int32 (4 bytes)
    parser_large = EXDParser(exd_data, columns_large, row_size=10, depth=1)
    # fixed_data will be self.data[46 : 46 + 10] -> b'\x42' (length 1, but we need 4 bytes for Int32)
    with pytest.raises(struct.error):
        parser_large.parse_rows()


# ==============================================================================
# 3. Control Code Envelope Robustness
# ==============================================================================

def test_control_code_unbalanced_and_malformed():
    """Test SeString parser with malformed or truncated control envelopes."""
    # Truncated control envelope missing type code (only 0x02)
    with pytest.raises(ValueError) as excinfo:
        ControlCodeParser.parse_string(b'\x02')
    assert "Malformed control code (missing type code)" in str(excinfo.value)

    # Missing payload length varint entirely
    with pytest.raises((IndexError, ValueError)):
        ControlCodeParser.parse_string(b'\x02\x10')

    # Claims payload length is 10, but buffer ends
    with pytest.raises(ValueError) as excinfo:
        # 0x02 (STX) + 0x10 (type) + 0x0B (varint value 10) + 2 bytes of payload
        ControlCodeParser.parse_string(b'\x02\x10\x0B\x41\x42')
    assert "Control code payload out of bounds" in str(excinfo.value)

    # Wrong end byte (claims payload length is 2, payload is 'AB', but end byte is not 0x03)
    with pytest.raises(ValueError) as excinfo:
        # 0x02 + 0x10 + 0x03 (varint value 2) + b'AB' + 0x04 (instead of 0x03)
        ControlCodeParser.parse_string(b'\x02\x10\x03\x41\x42\x04')
    assert "expected 0x03, got 0x4" in str(excinfo.value)


# ==============================================================================
# 4. Deeply Nested Control Structures
# ==============================================================================

def test_deep_nested_control_structures():
    """Test parsing of deeply nested control structures (like conditional chains)."""
    # Create nested structure:
    # IF LocalVar(1)
    #   THEN "Color 5: " + ColorControl(5) + "Nested IF LocalVar(2)"
    #     THEN "Color 6: " + ColorControl(6)
    #     ELSE "Color 7: " + ColorControl(7)
    #   ELSE "Reset: " + ResetControl()
    
    inner_true = encode_string_expr(b"Color 6: " + make_color_control(6))
    inner_false = encode_string_expr(b"Color 7: " + make_color_control(7))
    inner_cond = make_conditional_control(
        encode_variable_expr(2),
        inner_true,
        inner_false
    )
    
    outer_true = encode_string_expr(b"Color 5: " + make_color_control(5) + inner_cond)
    outer_false = encode_string_expr(b"Reset: " + make_reset_control())
    
    outer_cond = make_conditional_control(
        encode_variable_expr(1),
        outer_true,
        outer_false
    )
    
    # We parse the flat outer control structure first
    parsed = ControlCodeParser.parse_string(outer_cond)
    assert len(parsed) == 1
    assert parsed[0]['type'] == 'control'
    assert parsed[0]['code'] == 0x28  # Conditional opcode
    
    # Let's write a recursive parser helper to simulate what the actual translator
    # would do (or what the parser *should* do to find nested translatable strings)
    def recursive_parse(segments: list) -> list:
        results = []
        for seg in segments:
            if seg['type'] == 'text':
                results.append(seg)
            elif seg['type'] == 'control':
                # Parse the payload recursively if it's conditional (0x28) or string expr (0xE0)
                # Opcode 0x28 payload format: condition_expr + true_expr + false_expr
                # Opcode 0xE0 payload format: varint_len + string_bytes
                sub_segments = []
                payload = seg['payload']
                
                idx = 0
                while idx < len(payload):
                    if payload[idx] == 0xE0:
                        # String expression: 0xE0 + length (varint) + string_bytes
                        length, consumed = ControlCodeParser.parse_varint(payload, idx+1)
                        str_start = idx + 1 + consumed
                        str_end = str_start + length
                        sub_str_bytes = payload[str_start:str_end]
                        # Parse sub string
                        parsed_sub = ControlCodeParser.parse_string(sub_str_bytes)
                        sub_segments.extend(recursive_parse(parsed_sub))
                        idx = str_end
                    elif payload[idx] == 0x02:
                        # Another nested control code inside payload directly
                        if idx + 1 >= len(payload):
                            break
                        code_type = payload[idx+1]
                        length, consumed = ControlCodeParser.parse_varint(payload, idx + 2)
                        p_start = idx + 2 + consumed
                        p_end = p_start + length
                        # Validate 0x03 suffix
                        if p_end >= len(payload) or payload[p_end] != 0x03:
                            idx += 1
                            continue
                        nested_raw = payload[idx : p_end + 1]
                        parsed_nested = ControlCodeParser.parse_string(nested_raw)
                        sub_segments.extend(recursive_parse(parsed_nested))
                        idx = p_end + 1
                    else:
                        idx += 1
                
                results.append({
                    'type': 'control',
                    'code': seg['code'],
                    'payload': seg['payload'],
                    'raw': seg['raw'],
                    'nested': sub_segments
                })
        return results

    nested_parsed = recursive_parse(parsed)
    assert len(nested_parsed) == 1
    
    # Drill down to verify our recursive parse extracted strings correctly:
    # Outer level has conditional 0x28
    outer_control = nested_parsed[0]
    assert outer_control['type'] == 'control'
    assert outer_control['code'] == 0x28
    
    # Outer control's nested segments should contain the texts from the true/false branches
    nested_segs = outer_control['nested']
    # True branch text should be: "Color 5: "
    # True branch color control
    # Inner conditional control (code 0x28)
    # False branch text should be: "Reset: "
    # False branch reset control
    
    text_values = [s['value'] for s in nested_segs if s['type'] == 'text']
    assert "Color 5: " in text_values
    assert "Reset: " in text_values
    
    # Find the nested inner conditional control code
    inner_cond_segs = [s for s in nested_segs if s['type'] == 'control' and s['code'] == 0x28]
    assert len(inner_cond_segs) == 1
    
    inner_cond_control = inner_cond_segs[0]
    # Inner control's nested segments should contain the texts from its true/false branches
    inner_nested_segs = inner_cond_control['nested']
    inner_text_values = [s['value'] for s in inner_nested_segs if s['type'] == 'text']
    assert "Color 6: " in inner_text_values
    assert "Color 7: " in inner_text_values


if __name__ == '__main__':
    pytest.main(['-v', __file__])
