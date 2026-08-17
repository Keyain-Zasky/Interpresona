import math
import pytest
from interpresona.tests.mock_generator import (
    encode_varint,
    generate_control_code,
    make_color_control,
    make_character_name_control,
    make_reset_control,
    make_conditional_control,
    encode_integer_expr,
    encode_string_expr,
    encode_variable_expr,
    MockEXHGenerator,
    MockEXDGenerator,
    MockEXHParser,
    MockEXDParser,
    ControlCodeParser
)

def test_varint_encoding_boundaries():
    # Test Literal Mode (B < 0xF0, representing value B - 1)
    # B = value + 1. So value must be <= 238 (since 238 + 1 = 239 = 0xEF < 0xF0)
    for val in [0, 1, 10, 127, 238]:
        encoded = encode_varint(val)
        assert len(encoded) == 1
        assert encoded[0] == val + 1
        
        decoded, consumed = ControlCodeParser.parse_varint(encoded, 0)
        assert decoded == val
        assert consumed == 1

    # Test Prefix Mode 0xF0 (2 bytes consumed, value 239 to 255)
    for val in [239, 240, 255]:
        encoded = encode_varint(val)
        assert len(encoded) == 2
        assert encoded[0] == 0xF0
        assert encoded[1] == val
        
        decoded, consumed = ControlCodeParser.parse_varint(encoded, 0)
        assert decoded == val
        assert consumed == 2

    # Test Prefix Mode 0xF1 (3 bytes consumed, value 256 to 65535)
    for val in [256, 1000, 65535]:
        encoded = encode_varint(val)
        assert len(encoded) == 3
        assert encoded[0] == 0xF1
        assert encoded[1] == (val >> 8) & 0xFF
        assert encoded[2] == val & 0xFF
        
        decoded, consumed = ControlCodeParser.parse_varint(encoded, 0)
        assert decoded == val
        assert consumed == 3

    # Test Prefix Mode 0xF2 (4 bytes consumed, value 65536 to 16777215)
    for val in [65536, 100000, 16777215]:
        encoded = encode_varint(val)
        assert len(encoded) == 4
        assert encoded[0] == 0xF2
        assert encoded[1] == (val >> 16) & 0xFF
        assert encoded[2] == (val >> 8) & 0xFF
        assert encoded[3] == val & 0xFF
        
        decoded, consumed = ControlCodeParser.parse_varint(encoded, 0)
        assert decoded == val
        assert consumed == 4

    # Test Prefix Mode 0xF6 (5 bytes consumed, value 16777216 to 4294967295)
    for val in [16777216, 4294967295]:
        encoded = encode_varint(val)
        assert len(encoded) == 5
        assert encoded[0] == 0xF6
        assert encoded[1] == (val >> 24) & 0xFF
        assert encoded[2] == (val >> 16) & 0xFF
        assert encoded[3] == (val >> 8) & 0xFF
        assert encoded[4] == val & 0xFF
        
        decoded, consumed = ControlCodeParser.parse_varint(encoded, 0)
        assert decoded == val
        assert consumed == 5


def test_control_code_generation_and_parsing():
    # Test generation of reset control
    reset = make_reset_control()
    # 0x02, type 0x10, length value 0 (encoded as 0x01), 0x03
    assert reset == b'\x02\x10\x01\x03'
    
    parsed = ControlCodeParser.parse_string(reset)
    assert len(parsed) == 1
    assert parsed[0]['type'] == 'control'
    assert parsed[0]['code'] == 0x10
    assert parsed[0]['payload'] == b''
    assert parsed[0]['raw'] == reset

    # Test generation of color control
    color = make_color_control(5)
    # 0x02, type 0x40, length value 1 (encoded as 0x02), color_id 5 (encoded as 0x06), 0x03
    # Wait, let's trace encode_varint(5): 5+1 = 6. So payload is b'\x06' (len = 1).
    # Length of payload is 1, which is encoded as varint value 1 -> 2 (0x02).
    # So color = 0x02 + 0x40 + 0x02 + 0x06 + 0x03
    assert color == b'\x02\x40\x02\x06\x03'

    parsed = ControlCodeParser.parse_string(color)
    assert len(parsed) == 1
    assert parsed[0]['type'] == 'control'
    assert parsed[0]['code'] == 0x40
    assert parsed[0]['payload'] == b'\x06'
    assert parsed[0]['raw'] == color

    # Test nested conditional statement
    cond = make_conditional_control(
        encode_variable_expr(1),
        encode_string_expr(b"Opt " + make_color_control(5) + b"A"),
        encode_string_expr("Opt B")
    )
    
    parsed = ControlCodeParser.parse_string(cond)
    assert len(parsed) == 1
    assert parsed[0]['type'] == 'control'
    assert parsed[0]['code'] == 0x28
    
    # Reassemble string
    dialogue_bytes = b"Welcome, " + make_character_name_control() + b"! " + color + b" Choose: " + cond + b" Thank you."
    parsed_dialogue = ControlCodeParser.parse_string(dialogue_bytes)
    
    # Let's rebuild raw bytes
    rebuilt = b''.join(seg['raw'] for seg in parsed_dialogue)
    assert rebuilt == dialogue_bytes


def test_flat_sheet_generation_and_parsing():
    columns = [
        {'type': 0x0000, 'offset': 0},   # String
        {'type': 0x0001, 'offset': 4},   # Boolean
        {'type': 0x0002, 'offset': 5},   # Signed Byte
        {'type': 0x0003, 'offset': 6},   # Unsigned Byte
        {'type': 0x0004, 'offset': 8},   # Signed Int16
        {'type': 0x0005, 'offset': 10},  # Unsigned Int16
        {'type': 0x0006, 'offset': 12},  # Signed Int32
        {'type': 0x0007, 'offset': 16},  # Unsigned Int32
        {'type': 0x0009, 'offset': 20},  # Float
        {'type': 0x000B, 'offset': 24},  # Signed Int64
        {'type': 0x000C, 'offset': 32},  # Unsigned Int64
        {'type': 0x0019, 'offset': 40},  # Packed Bool 0
        {'type': 0x001A, 'offset': 40},  # Packed Bool 1
    ]
    pages = [{'start_id': 100, 'row_count': 2}]
    languages = [{'lang_id': 2, 'unk': 0}]  # English

    # Create dialog string with control codes
    dialog_bytes = (
        b"Hello, " + 
        make_character_name_control() + 
        b"! " + 
        make_color_control(3) + 
        b"Choose: " + 
        make_reset_control() + 
        make_conditional_control(
            encode_variable_expr(1), 
            encode_string_expr(b"Option " + make_color_control(5) + b"A"), 
            encode_string_expr("Option B")
        )
    )

    rows = [
        {
            'row_id': 100,
            'values': [
                dialog_bytes,                      # String
                True,                              # Boolean
                -12,                               # Signed Byte
                240,                               # Unsigned Byte
                -999,                              # Signed Int16
                65530,                             # Unsigned Int16
                -1234567,                          # Signed Int32
                4294967200,                        # Unsigned Int32
                3.14159,                           # Float
                -9223372036854775800,              # Signed Int64
                18446744073709551600,              # Unsigned Int64
                True,                              # Packed Bool 0
                False                              # Packed Bool 1
            ]
        },
        {
            'row_id': 101,
            'values': [
                b"Simple text without control code.",
                False,
                127,
                128,
                32767,
                0,
                0,
                0,
                0.0,
                0,
                0,
                False,
                True
            ]
        }
    ]

    # Generate EXH and EXD
    exh_gen = MockEXHGenerator(columns, pages, languages, depth=1, row_type=1)
    exh_bytes = exh_gen.generate()
    
    exd_gen = MockEXDGenerator(columns, depth=1)
    for row in rows:
        exd_gen.add_row(row['row_id'], row['values'])
    exd_bytes = exd_gen.generate()

    # Parse EXH back
    exh_parser = MockEXHParser(exh_bytes)
    assert exh_parser.magic == b'EXHF'
    assert exh_parser.version == 3
    assert exh_parser.row_size == exh_gen.row_size
    assert exh_parser.column_count == len(columns)
    assert exh_parser.page_count == len(pages)
    assert exh_parser.language_count == len(languages)
    assert exh_parser.row_type == 1
    assert exh_parser.depth == 1
    assert exh_parser.row_count == 2
    assert exh_parser.columns == columns
    assert exh_parser.pages == pages
    assert exh_parser.languages == languages

    # Parse EXD back
    exd_parser = MockEXDParser(exd_bytes, exh_parser.columns, depth=1, row_size=exh_parser.row_size)
    assert exd_parser.magic == b'EXDF'
    assert exd_parser.version == 2
    assert len(exd_parser.rows) == 2

    # Verify Row 100
    row100 = exd_parser.rows[0]
    assert row100['row_id'] == 100
    assert row100['values'][0] == dialog_bytes
    assert row100['values'][1] is True
    assert row100['values'][2] == -12
    assert row100['values'][3] == 240
    assert row100['values'][4] == -999
    assert row100['values'][5] == 65530
    assert row100['values'][6] == -1234567
    assert row100['values'][7] == 4294967200
    assert math.isclose(row100['values'][8], 3.14159, rel_tol=1e-5)
    assert row100['values'][9] == -9223372036854775800
    assert row100['values'][10] == 18446744073709551600
    assert row100['values'][11] is True
    assert row100['values'][12] is False

    # Verify Row 101
    row101 = exd_parser.rows[1]
    assert row101['row_id'] == 101
    assert row101['values'][0] == b"Simple text without control code."
    assert row101['values'][1] is False
    assert row101['values'][2] == 127
    assert row101['values'][3] == 128
    assert row101['values'][4] == 32767
    assert row101['values'][5] == 0
    assert row101['values'][6] == 0
    assert row101['values'][7] == 0
    assert math.isclose(row101['values'][8], 0.0, abs_tol=1e-5)
    assert row101['values'][9] == 0
    assert row101['values'][10] == 0
    assert row101['values'][11] is False
    assert row101['values'][12] is True


def test_sub_row_sheet_generation_and_parsing():
    columns = [
        {'type': 0x0000, 'offset': 0},  # String
        {'type': 0x0005, 'offset': 4},  # UInt16
    ]
    pages = [{'start_id': 1, 'row_count': 1}]
    languages = [{'lang_id': 2, 'unk': 0}]

    sub_rows = [
        {
            'sub_row_id': 0,
            'values': [b"Sub-row 0 text", 42]
        },
        {
            'sub_row_id': 1,
            'values': [b"Sub-row 1 text with name control " + make_character_name_control(), 999]
        }
    ]

    exh_gen = MockEXHGenerator(columns, pages, languages, depth=2, row_type=2)
    exh_bytes = exh_gen.generate()

    exd_gen = MockEXDGenerator(columns, depth=2)
    exd_gen.add_row(1, sub_rows=sub_rows)
    exd_bytes = exd_gen.generate()

    exh_parser = MockEXHParser(exh_bytes)
    assert exh_parser.row_type == 2
    assert exh_parser.depth == 2

    exd_parser = MockEXDParser(exd_bytes, exh_parser.columns, depth=2, row_size=exh_parser.row_size)
    assert len(exd_parser.rows) == 1
    
    row = exd_parser.rows[0]
    assert row['row_id'] == 1
    assert len(row['sub_rows']) == 2

    assert row['sub_rows'][0]['sub_row_id'] == 0
    assert row['sub_rows'][0]['values'][0] == b"Sub-row 0 text"
    assert row['sub_rows'][0]['values'][1] == 42

    assert row['sub_rows'][1]['sub_row_id'] == 1
    assert row['sub_rows'][1]['values'][0] == b"Sub-row 1 text with name control \x02\x17\x01\x03"
    assert row['sub_rows'][1]['values'][1] == 999
