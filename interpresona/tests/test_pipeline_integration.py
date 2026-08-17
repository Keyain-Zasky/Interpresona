"""
Pipeline integration tests (no game files needed — uses mock data)
Tests the complete round-trip: EXH/EXD binary → extract → mask → translate → unmask → inject → re-parse
"""
import sys
import io
from pathlib import Path

# Force UTF-8 output on Windows consoles that default to CP1252
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import struct
from interpresona.tests.mock_generator import (
    MockEXHGenerator, MockEXDGenerator,
    make_character_name_control, make_color_control,
    make_reset_control, make_conditional_control,
    encode_variable_expr, encode_string_expr,
)
from interpresona.core.pipeline import TranslationPipeline
from interpresona.core.masker import mask, unmask, validate_placeholders
from interpresona.core.parser import EXHParser, EXDParser


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_flat_exh_exd():
    """Build EXH + EXD binaries for a simple flat sheet with control codes."""
    columns = [
        {'type': 0x0000, 'offset': 0},   # String col 0
        {'type': 0x0000, 'offset': 4},   # String col 1
        {'type': 0x0007, 'offset': 8},   # UInt32 col 2 (not translated)
    ]
    pages     = [{'start_id': 0, 'row_count': 3}]
    languages = [{'lang_id': 2, 'unk': 0}]

    # Build a complex SeString with control codes
    dialogue = (
        b"Hello, " +
        make_character_name_control() +          # ⟪VAR_0⟫
        b"! " +
        make_color_control(7) +                  # ⟪VAR_1⟫
        b"Choose: " +
        make_reset_control() +                   # ⟪VAR_2⟫
        make_conditional_control(
            encode_variable_expr(1),
            encode_string_expr(b"Option A"),
            encode_string_expr(b"Option B"),
        )                                         # ⟪VAR_3⟫
    )

    exh_gen = MockEXHGenerator(columns, pages, languages, depth=1, row_size=12)
    exh_bytes = exh_gen.generate()

    exd_gen = MockEXDGenerator(columns, depth=1, row_size=12)
    exd_gen.add_row(0, [dialogue, b"Simple plain text.", 42])
    exd_gen.add_row(1, [b"No vars here.", b"Also no vars.", 99])
    exd_gen.add_row(2, [b"", b"", 0])   # Empty strings

    exd_bytes = exd_gen.generate()
    return exh_bytes, exd_bytes, dialogue


def _make_mock_subrow_exh_exd():
    """Build EXH + EXD for a depth-2 sub-row sheet."""
    columns = [
        {'type': 0x0000, 'offset': 0},  # String col 0
        {'type': 0x0005, 'offset': 4},  # UInt16 col 1
    ]
    pages     = [{'start_id': 0, 'row_count': 1}]
    languages = [{'lang_id': 2, 'unk': 0}]

    sub_rows = [
        {'sub_row_id': 0, 'values': [make_character_name_control() + b" won!", 10]},
        {'sub_row_id': 1, 'values': [b"Regular text.", 20]},
    ]

    exh_gen = MockEXHGenerator(columns, pages, languages, depth=2, row_size=6)
    exh_bytes = exh_gen.generate()

    exd_gen = MockEXDGenerator(columns, depth=2, row_size=6)
    exd_gen.add_row(0, sub_rows=sub_rows)
    exd_bytes = exd_gen.generate()
    return exh_bytes, exd_bytes


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_masker_roundtrip_with_control_codes():
    """mask() → unmask() must yield the original bytes."""
    raw = (
        b"Welcome, " +
        make_character_name_control() +
        b"! " +
        make_color_control(5) +
        b"Good luck." +
        make_reset_control()
    )
    masked = mask(raw)
    assert "{0}" in masked.text
    assert "{1}" in masked.text
    assert "{2}" in masked.text
    assert len(masked.placeholders) == 3

    restored = unmask(masked.text, masked.placeholders)
    assert restored == raw, f"Round-trip mismatch:\n  expected {raw!r}\n  got      {restored!r}"
    print("  ✓ masker roundtrip with control codes")


def test_masker_no_control_codes():
    """mask() on plain text should produce identical text and empty placeholders."""
    raw = b"Simple plain text without any control codes."
    masked = mask(raw)
    assert masked.text == raw.decode("utf-8")
    assert not masked.placeholders
    restored = unmask(masked.text, masked.placeholders)
    assert restored == raw
    print("  ✓ masker on plain text")


def test_validate_placeholders_detects_removals():
    """validate_placeholders should catch deleted placeholder tokens."""
    raw = b"Hello " + make_character_name_control() + b"!"
    masked = mask(raw)
    # Simulate MT that removed the placeholder
    errors = validate_placeholders("Hello !", masked.placeholders)
    assert errors, "Expected validation to flag missing placeholder"
    print("  ✓ validate_placeholders catches removals")


def test_pipeline_flat_extract_inject_roundtrip():
    """
    Full pipeline test for flat (depth=1) sheets:
    EXH+EXD → extract → translate (simulated) → inject → re-parse → verify.
    """
    exh_bytes, exd_bytes, original_dialogue = _make_mock_flat_exh_exd()

    pipeline = TranslationPipeline(exh_bytes, exd_bytes)
    records = pipeline.extract()

    # Only non-empty string cells should be extracted
    assert len(records) > 0, "No records extracted"

    # Simulate translation: just append [TR] to masked text (keeps placeholders intact)
    for rec in records:
        rec.translated_text = rec.masked_text + " [TR]"

    # Inject
    new_exd_bytes = pipeline.inject()
    assert len(new_exd_bytes) > 32, "Injected EXD too small"

    # Re-parse and verify
    schema = EXHParser(exh_bytes).result
    reparsed = EXDParser(new_exd_bytes, schema)

    assert len(reparsed.rows) == 3
    row0_str0 = reparsed.rows[0].values[0]
    assert b" [TR]" in row0_str0, f"Translation not found in row0/col0: {row0_str0!r}"

    # Verify control codes are still intact
    assert make_character_name_control() in row0_str0, "Character name control code missing after inject"
    assert make_color_control(7) in row0_str0, "Color control code missing after inject"
    assert make_reset_control() in row0_str0, "Reset control code missing after inject"

    # Verify non-string column untouched
    assert reparsed.rows[0].values[2] == 42
    assert reparsed.rows[1].values[2] == 99
    print("  ✓ pipeline flat extract→inject roundtrip with control code preservation")


def test_pipeline_subrow_extract_inject_roundtrip():
    """
    Full pipeline test for sub-row (depth=2) sheets.
    """
    exh_bytes, exd_bytes = _make_mock_subrow_exh_exd()
    pipeline = TranslationPipeline(exh_bytes, exd_bytes)
    records = pipeline.extract()

    assert len(records) >= 1

    for rec in records:
        rec.translated_text = rec.masked_text + " [TR]"

    new_exd = pipeline.inject()
    schema = EXHParser(exh_bytes).result
    reparsed = EXDParser(new_exd, schema)

    assert len(reparsed.rows) == 1
    sub_rows = reparsed.rows[0].sub_rows
    assert len(sub_rows) == 2
    assert b" [TR]" in sub_rows[0]["values"][0], "Sub-row translation not injected"
    assert make_character_name_control() in sub_rows[0]["values"][0], \
        "Control code missing in sub-row after inject"
    print("  ✓ pipeline sub-row extract→inject roundtrip")


def test_pipeline_csv_export_import():
    """Test CSV round-trip: export → import → inject."""
    exh_bytes, exd_bytes, _ = _make_mock_flat_exh_exd()
    pipeline = TranslationPipeline(exh_bytes, exd_bytes)
    pipeline.extract()

    # Export CSV
    csv_text = pipeline.export_csv()
    assert "original" in csv_text.lower()
    assert "translated" in csv_text.lower()

    # Simulate filling in translations: add [TR] suffix to each original
    lines = csv_text.splitlines()
    header = lines[0]
    body = []
    import csv, io
    reader = csv.DictReader(io.StringIO(csv_text))
    rows_out = []
    for row in reader:
        row["translated"] = row["original"] + " [TR]"
        rows_out.append(row)

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=reader.fieldnames, quoting=csv.QUOTE_ALL)
    writer.writeheader()
    writer.writerows(rows_out)
    filled_csv = buf.getvalue()

    # Re-import
    errors = pipeline.import_translations_from_csv(filled_csv)
    assert not errors, f"Unexpected import errors: {errors}"

    # Inject and verify
    new_exd = pipeline.inject()
    schema = EXHParser(exh_bytes).result
    reparsed = EXDParser(new_exd, schema)
    row0_val = reparsed.rows[0].values[0]
    assert b" [TR]" in row0_val
    print("  ✓ pipeline CSV export→import→inject roundtrip")


def test_pipeline_stats():
    """Pipeline stats should accurately track pending/translated/errored counts."""
    exh_bytes, exd_bytes, _ = _make_mock_flat_exh_exd()
    pipeline = TranslationPipeline(exh_bytes, exd_bytes)
    pipeline.extract()

    stats = pipeline.stats
    assert stats["total"] == len(pipeline.records)
    assert stats["translated"] == 0
    assert stats["errored"] == 0

    # Translate one record
    pipeline.records[0].translated_text = "Test translation"
    stats2 = pipeline.stats
    assert stats2["translated"] == 1
    print("  ✓ pipeline stats are correct")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_masker_roundtrip_with_control_codes,
        test_masker_no_control_codes,
        test_validate_placeholders_detects_removals,
        test_pipeline_flat_extract_inject_roundtrip,
        test_pipeline_subrow_extract_inject_roundtrip,
        test_pipeline_csv_export_import,
        test_pipeline_stats,
    ]
    passed = 0
    failed = 0
    print(f"\n{'='*60}")
    print("  FFXIV Translation Tool - Integration Tests")
    print(f"{'='*60}\n")
    for t in tests:
        try:
            t()
            print(f"  PASS {t.__name__}")
            passed += 1
        except Exception as exc:
            import traceback
            print(f"  FAIL {t.__name__}: {exc}")
            traceback.print_exc()
            failed += 1

    print(f"\n{'='*60}")
    print(f"  Results: {passed} passed, {failed} failed")
    print(f"{'='*60}\n")
    if failed:
        sys.exit(1)
