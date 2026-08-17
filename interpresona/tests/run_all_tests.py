"""
Comprehensive automated tests for the FFXIV Translation Tool.
Tests the full pipeline without any external dependencies or game files.
Run with:  uv run python tests/run_all_tests.py
"""
from __future__ import annotations
import sys, struct, io, csv, json, base64, traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace") if hasattr(sys.stdout, "reconfigure") else None

from interpresona.tests.mock_generator import (
    MockEXHGenerator, MockEXDGenerator,
    make_character_name_control, make_color_control,
    make_reset_control, make_conditional_control,
    encode_variable_expr, encode_string_expr,
)
from interpresona.core.parser import EXHParser, EXDParser
from interpresona.core.masker import mask, unmask, validate_placeholders
from interpresona.core.pipeline import TranslationPipeline, ExtractionRecord
from interpresona.core.injector import EXDInjector
from interpresona.core.translator import MockTranslator, TranslationError
from interpresona.core.session import save_session, load_session, session_summary

PASS = 0
FAIL = 0


def _run(fn):
    global PASS, FAIL
    try:
        fn()
        print(f"  PASS  {fn.__name__}")
        PASS += 1
    except Exception as exc:
        print(f"  FAIL  {fn.__name__}: {exc}")
        traceback.print_exc()
        FAIL += 1


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _flat_sheet(n_rows=3, n_string_cols=2, n_int_cols=1):
    """Generate a minimal flat EXH+EXD pair."""
    # String cols take 4 bytes each (offset pointer), int cols take 4 bytes (uint32)
    columns = []
    off = 0
    for i in range(n_string_cols):
        columns.append({"type": 0x0000, "offset": off})
        off += 4
    for i in range(n_int_cols):
        columns.append({"type": 0x0007, "offset": off})
        off += 4
    row_size = off  # total fixed-data bytes

    pages = [{"start_id": 0, "row_count": n_rows}]
    languages = [{"lang_id": 2, "unk": 0}]

    exh = MockEXHGenerator(columns, pages, languages, depth=1, row_size=row_size).generate()
    gen = MockEXDGenerator(columns, depth=1, row_size=row_size)
    for i in range(n_rows):
        # Build values matching columns order: strings first, then ints
        vals = []
        for s in range(n_string_cols):
            vals.append(f"Text {i}{chr(65+s)}".encode())  # b"Text 0A", b"Text 0B", ...
        for k in range(n_int_cols):
            vals.append(i * 10 + k)
        gen.add_row(i, vals)
    exd = gen.generate()
    return exh, exd, columns


def _complex_sheet():
    """Sheet with control codes in strings."""
    row_size = 8  # 2 string cols × 4 bytes
    columns = [{"type": 0x0000, "offset": 0}, {"type": 0x0000, "offset": 4}]
    pages = [{"start_id": 0, "row_count": 2}]
    languages = [{"lang_id": 2, "unk": 0}]

    dialogue = (
        b"Hello, " + make_character_name_control() +
        b"! " + make_color_control(7) + b"Welcome!" + make_reset_control()
    )
    plain = b"Simple text."

    exh = MockEXHGenerator(columns, pages, languages, depth=1, row_size=row_size).generate()
    gen = MockEXDGenerator(columns, depth=1, row_size=row_size)
    gen.add_row(0, [dialogue, plain])
    gen.add_row(1, [b"Row 1 text.", b"More text."])
    exd = gen.generate()
    return exh, exd, dialogue


def _subrow_sheet():
    """Depth-2 sub-row sheet."""
    row_size = 6  # 1 string col (4) + 1 uint16 col (2)
    columns = [{"type": 0x0000, "offset": 0}, {"type": 0x0005, "offset": 4}]
    pages = [{"start_id": 0, "row_count": 1}]
    languages = [{"lang_id": 2, "unk": 0}]

    exh = MockEXHGenerator(columns, pages, languages, depth=2, row_size=row_size).generate()
    gen = MockEXDGenerator(columns, depth=2, row_size=row_size)
    gen.add_row(0, sub_rows=[
        {"sub_row_id": 0, "values": [make_character_name_control() + b" says hi!", 10]},
        {"sub_row_id": 1, "values": [b"Reply text.", 20]},
    ])
    exd = gen.generate()
    return exh, exd


# ─── Masker Tests ──────────────────────────────────────────────────────────────

def test_mask_plain_text():
    raw = b"Hello world, this is plain text."
    result = mask(raw)
    assert result.text == "Hello world, this is plain text."
    assert result.placeholders == {}
    assert unmask(result.text, result.placeholders) == raw


def test_mask_control_codes_roundtrip():
    raw = (b"Say " + make_character_name_control() + b" and " +
           make_color_control(3) + b"continue." + make_reset_control())
    result = mask(raw)
    assert "{0}" in result.text
    assert "{1}" in result.text
    assert "{2}" in result.text
    assert len(result.placeholders) == 3
    restored = unmask(result.text, result.placeholders)
    assert restored == raw, f"Roundtrip failed:\n  exp={raw!r}\n  got={restored!r}"


def test_mask_consecutive_placeholders():
    raw = make_character_name_control() + make_color_control(1) + make_reset_control()
    result = mask(raw)
    # Check that spaces were inserted between adjacent placeholders
    assert result.text == "{0} {1} {2}"
    restored = unmask(result.text, result.placeholders)
    assert restored == raw


def test_mask_placeholder_at_start():
    raw = make_character_name_control() + b" joined the battle!"
    result = mask(raw)
    assert result.text.startswith("{0}")
    assert unmask(result.text, result.placeholders) == raw


def test_mask_placeholder_at_end():
    raw = b"Game Over" + make_reset_control()
    result = mask(raw)
    assert result.text.endswith("{0}")
    assert unmask(result.text, result.placeholders) == raw


def test_validate_placeholders_all_present():
    raw = b"Hi " + make_character_name_control() + b"!"
    result = mask(raw)
    errors = validate_placeholders(result.text, result.placeholders)
    assert errors == []


def test_validate_placeholders_missing():
    raw = b"Hi " + make_character_name_control() + b"!"
    result = mask(raw)
    errors = validate_placeholders("Hi !", result.placeholders)  # placeholder removed
    assert len(errors) == 1
    assert "removed" in errors[0].lower()


def test_validate_placeholders_extra():
    raw = b"Hello"
    result = mask(raw)
    # MT hallucinated a placeholder
    errors = validate_placeholders("Hello {0}", result.placeholders)
    assert len(errors) == 1
    assert "introduced" in errors[0].lower()


def test_unmask_unknown_placeholder_raises():
    try:
        unmask("Hello {99} world", {})
        assert False, "Should have raised ValueError"
    except ValueError:
        pass


# ─── Parser Tests ─────────────────────────────────────────────────────────────

def test_parser_flat_sheet_columns():
    exh, exd, columns = _flat_sheet(n_rows=2, n_string_cols=2, n_int_cols=1)
    schema = EXHParser(exh).result
    assert schema.depth == 1
    assert len(schema.columns) == 3
    assert schema.columns[0].is_string
    assert schema.columns[1].is_string
    assert not schema.columns[2].is_string


def test_parser_flat_sheet_row_values():
    exh, exd, _ = _flat_sheet(n_rows=3)
    schema = EXHParser(exh).result
    rows = EXDParser(exd, schema).rows
    assert len(rows) == 3
    # col 0 and 1 are strings, col 2 is uint32
    assert rows[0].values[0] == b"Text 0A"
    assert rows[1].values[0] == b"Text 1A"
    assert rows[2].values[2] == 20  # int col (i=2, k=0 → 2*10+0 = 20)


def test_parser_subrow_sheet():
    exh, exd = _subrow_sheet()
    schema = EXHParser(exh).result
    assert schema.depth == 2
    rows = EXDParser(exd, schema).rows
    assert len(rows) == 1
    assert len(rows[0].sub_rows) == 2
    assert rows[0].sub_rows[1]["values"][0] == b"Reply text."


def test_parser_bad_magic_raises():
    try:
        EXHParser(b"BAAD" + b"\x00" * 50)
        assert False, "Should have raised ValueError"
    except ValueError:
        pass


def test_parser_preserves_int_values():
    exh, exd, _ = _flat_sheet(n_rows=5, n_string_cols=1, n_int_cols=1)
    schema = EXHParser(exh).result
    rows = EXDParser(exd, schema).rows
    for i, row in enumerate(rows):
        # col 0 = string, col 1 = uint32, value = i*10+0
        assert row.values[1] == i * 10, f"Row {i}: expected int {i*10}, got {row.values[1]}"


# ─── Pipeline Tests ────────────────────────────────────────────────────────────

def test_pipeline_extracts_only_strings():
    exh, exd, _ = _flat_sheet(n_rows=3, n_string_cols=2, n_int_cols=2)
    pipeline = TranslationPipeline(exh, exd)
    records = pipeline.extract()
    # Only non-empty string cells => rows 0,1,2 × cols 0,1 = 6 cells
    assert all(isinstance(r, ExtractionRecord) for r in records)
    assert all(r.col_idx in (0, 1) for r in records)


def test_pipeline_empty_strings_skipped():
    row_size = 4
    columns = [{"type": 0x0000, "offset": 0}]
    pages = [{"start_id": 0, "row_count": 2}]
    languages = [{"lang_id": 2, "unk": 0}]
    exh = MockEXHGenerator(columns, pages, languages, depth=1, row_size=row_size).generate()
    gen = MockEXDGenerator(columns, depth=1, row_size=row_size)
    gen.add_row(0, [b"Real text"])
    gen.add_row(1, [b""])  # empty — should be skipped
    exd = gen.generate()
    pipeline = TranslationPipeline(exh, exd)
    records = pipeline.extract()
    assert len(records) == 1
    assert records[0].masked_text == "Real text"


def test_pipeline_control_codes_masked_in_records():
    exh, exd, dialogue = _complex_sheet()
    pipeline = TranslationPipeline(exh, exd)
    records = pipeline.extract()
    rec0 = next(r for r in records if r.row_id == 0 and r.col_idx == 0)
    assert "{0}" in rec0.masked_text
    assert b"\x02" not in rec0.masked_text.encode("utf-8", errors="replace")


def test_pipeline_inject_roundtrip_flat():
    exh, exd, dialogue = _complex_sheet()
    pipeline = TranslationPipeline(exh, exd)
    records = pipeline.extract()
    for rec in records:
        rec.translated_text = "[IT] " + rec.masked_text
    new_exd = pipeline.inject()
    schema = EXHParser(exh).result
    reparsed = EXDParser(new_exd, schema)
    r0 = reparsed.rows[0].values[0]
    assert b"[IT] " in r0
    assert make_character_name_control() in r0
    assert make_color_control(7) in r0
    assert make_reset_control() in r0


def test_pipeline_inject_preserves_int_columns():
    exh, exd, _ = _flat_sheet(n_rows=3, n_string_cols=1, n_int_cols=1)
    pipeline = TranslationPipeline(exh, exd)
    records = pipeline.extract()
    for rec in records:
        rec.translated_text = "Translated"
    new_exd = pipeline.inject()
    schema = EXHParser(exh).result
    reparsed = EXDParser(new_exd, schema)
    for i, row in enumerate(reparsed.rows):
        # col 1 is uint32, value = i*10+0
        assert row.values[1] == i * 10, f"Int value corrupted at row {i}: got {row.values[1]}"


def test_pipeline_inject_subrow():
    exh, exd = _subrow_sheet()
    pipeline = TranslationPipeline(exh, exd)
    records = pipeline.extract()
    for rec in records:
        rec.translated_text = "[IT] " + rec.masked_text
    new_exd = pipeline.inject()
    schema = EXHParser(exh).result
    reparsed = EXDParser(new_exd, schema)
    sub_rows = reparsed.rows[0].sub_rows
    assert b"[IT] " in sub_rows[0]["values"][0]
    assert make_character_name_control() in sub_rows[0]["values"][0]


def test_pipeline_untranslated_keeps_original():
    exh, exd, _ = _flat_sheet(n_rows=2, n_string_cols=1)
    pipeline = TranslationPipeline(exh, exd)
    records = pipeline.extract()
    # Only translate first record
    records[0].translated_text = "Tradotto"
    new_exd = pipeline.inject()
    schema = EXHParser(exh).result
    reparsed = EXDParser(new_exd, schema)
    assert reparsed.rows[0].values[0] == b"Tradotto"
    assert reparsed.rows[1].values[0] == b"Text 1A"  # original preserved


def test_pipeline_error_record_keeps_original():
    exh, exd, _ = _flat_sheet(n_rows=2, n_string_cols=1)
    pipeline = TranslationPipeline(exh, exd)
    records = pipeline.extract()
    records[0].translated_text = "Good translation"
    records[1].translated_text = "Has errors"
    records[1].errors = ["Placeholder missing"]
    new_exd = pipeline.inject()
    schema = EXHParser(exh).result
    reparsed = EXDParser(new_exd, schema)
    assert reparsed.rows[0].values[0] == b"Good translation"
    assert reparsed.rows[1].values[0] == b"Text 1A"  # original kept — error blocked inject


def test_pipeline_multipage():
    """Multi-page: two EXD pages, each with different rows, merged correctly."""
    row_size = 4
    columns = [{"type": 0x0000, "offset": 0}]
    languages = [{"lang_id": 2, "unk": 0}]
    pages = [{"start_id": 0, "row_count": 2}, {"start_id": 2, "row_count": 2}]
    exh = MockEXHGenerator(columns, pages, languages, depth=1, row_size=row_size).generate()

    # Page 0: rows 0,1
    gen0 = MockEXDGenerator(columns, depth=1, row_size=row_size)
    gen0.add_row(0, [b"Page0 Row0"])
    gen0.add_row(1, [b"Page0 Row1"])
    exd0 = gen0.generate()

    # Page 1: rows 2,3
    gen1 = MockEXDGenerator(columns, depth=1, row_size=row_size)
    gen1.add_row(2, [b"Page1 Row2"])
    gen1.add_row(3, [b"Page1 Row3"])
    exd1 = gen1.generate()

    pipeline = TranslationPipeline(exh, [exd0, exd1])
    records = pipeline.extract()
    assert len(records) == 4
    assert pipeline.page_count == 2

    for rec in records:
        rec.translated_text = "[IT] " + rec.masked_text

    pages_out = pipeline.inject_all()
    assert set(pages_out.keys()) == {0, 1}

    schema = EXHParser(exh).result
    p0_rows = EXDParser(pages_out[0], schema).rows
    p1_rows = EXDParser(pages_out[1], schema).rows
    assert p0_rows[0].values[0] == b"[IT] Page0 Row0"
    assert p1_rows[0].values[0] == b"[IT] Page1 Row2"


def test_pipeline_stats_accuracy():
    exh, exd, _ = _flat_sheet(n_rows=4, n_string_cols=1)
    pipeline = TranslationPipeline(exh, exd)
    pipeline.extract()
    s = pipeline.stats
    assert s["total"] == 4
    assert s["translated"] == 0
    assert s["pending"] == 4
    assert s["errored"] == 0

    pipeline.records[0].translated_text = "Done"
    pipeline.records[1].errors = ["oops"]
    s2 = pipeline.stats
    assert s2["translated"] == 1
    assert s2["errored"] == 1
    assert s2["pending"] == 2


def test_pipeline_csv_roundtrip():
    exh, exd, _ = _flat_sheet(n_rows=2, n_string_cols=1)
    pipeline = TranslationPipeline(exh, exd)
    pipeline.extract()
    csv_text = pipeline.export_csv()
    # Fill translations
    reader = csv.DictReader(io.StringIO(csv_text))
    rows_out = []
    for row in reader:
        row["translated"] = "[IT] " + row["original"]
        rows_out.append(row)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["row_id", "sub_row_id", "col_idx", "original", "translated"],
                             quoting=csv.QUOTE_ALL)
    writer.writeheader()
    writer.writerows(rows_out)
    errors = pipeline.import_translations_from_csv(buf.getvalue())
    assert not errors, f"Import errors: {errors}"
    new_exd = pipeline.inject()
    schema = EXHParser(exh).result
    reparsed = EXDParser(new_exd, schema)
    assert b"[IT] " in reparsed.rows[0].values[0]


def test_pipeline_json_roundtrip():
    exh, exd, _ = _flat_sheet(n_rows=2, n_string_cols=1)
    pipeline = TranslationPipeline(exh, exd)
    pipeline.extract()
    j = json.loads(pipeline.export_json())
    for item in j:
        item["translated"] = "[IT] " + item["original"]
    errors = pipeline.import_translations_from_json(json.dumps(j))
    assert not errors
    for rec in pipeline.records:
        assert rec.translated_text and rec.translated_text.startswith("[IT] ")


def test_pipeline_placeholder_corruption_rejected():
    """MT output that drops a placeholder must be rejected (not injected)."""
    exh, exd, dialogue = _complex_sheet()
    pipeline = TranslationPipeline(exh, exd)
    records = pipeline.extract()
    rec_with_vars = next(r for r in records if r.placeholders)
    # Simulate MT removing placeholder
    bad_translation = "Ciao amico!"
    ph_errors = validate_placeholders(bad_translation, rec_with_vars.placeholders)
    assert ph_errors  # must catch it
    rec_with_vars.errors = ph_errors  # mark as errored
    rec_with_vars.translated_text = bad_translation
    new_exd = pipeline.inject()
    schema = EXHParser(exh).result
    reparsed = EXDParser(new_exd, schema)
    original_val = reparsed.rows[0].values[0]
    # The record had errors → original is kept
    assert b"Ciao amico!" not in original_val


# ─── Translator Tests ──────────────────────────────────────────────────────────

def test_mock_translator_basic():
    mt = MockTranslator(prefix="[EN] ")
    results = mt.translate(["hello world", "test"])
    assert results[0] == "[EN] HELLO WORLD"
    assert results[1] == "[EN] TEST"


def test_mock_translator_preserves_placeholders():
    mt = MockTranslator(prefix="")
    results = mt.translate(["Hello {0} world {1}!"])
    assert "{0}" in results[0]
    assert "{1}" in results[0]


def test_pipeline_apply_machine_translation():
    exh, exd, _ = _flat_sheet(n_rows=3, n_string_cols=1)
    pipeline = TranslationPipeline(exh, exd)
    pipeline.extract()
    mt = MockTranslator(prefix="[IT] ")
    errors = pipeline.apply_machine_translation(mt.translate)
    assert not errors
    for rec in pipeline.records:
        assert rec.translated_text and rec.translated_text.startswith("[IT] ")


# ─── Session Tests ─────────────────────────────────────────────────────────────

def test_session_save_load_roundtrip(tmp_path=None):
    import tempfile, os
    exh, exd, _ = _flat_sheet(n_rows=3, n_string_cols=2)
    pipeline = TranslationPipeline(exh, exd)
    pipeline.extract()
    pipeline.records[0].translated_text = "Traduzione uno"
    pipeline.records[1].translated_text = "Traduzione due"

    with tempfile.NamedTemporaryFile(suffix=".ffxivts", delete=False) as f:
        session_path = Path(f.name)
    try:
        save_session(session_path, pipeline, sheet_name="TestSheet", language="it")
        restored, meta = load_session(session_path)
        assert meta["sheet_name"] == "TestSheet"
        assert meta["language"] == "it"
        assert len(restored.records) == len(pipeline.records)
        r0 = next(r for r in restored.records if r.key == pipeline.records[0].key)
        assert r0.translated_text == "Traduzione uno"
        r1 = next(r for r in restored.records if r.key == pipeline.records[1].key)
        assert r1.translated_text == "Traduzione due"
        # Untranslated records remain None
        for rec in restored.records:
            if rec.key not in (pipeline.records[0].key, pipeline.records[1].key):
                assert not rec.translated_text
    finally:
        os.unlink(session_path)


def test_session_summary_counts():
    import tempfile, os
    exh, exd, _ = _flat_sheet(n_rows=4, n_string_cols=1)
    pipeline = TranslationPipeline(exh, exd)
    pipeline.extract()
    pipeline.records[0].translated_text = "Done"
    pipeline.records[1].errors = ["Broken"]

    with tempfile.NamedTemporaryFile(suffix=".ffxivts", delete=False) as f:
        session_path = Path(f.name)
    try:
        save_session(session_path, pipeline)
        summary = session_summary(session_path)
        assert summary["total"] == 4
        assert summary["translated"] == 1
        assert summary["errored"] == 1
        assert summary["pending"] == 2
    finally:
        os.unlink(session_path)


# ─── End-to-end independence test ─────────────────────────────────────────────

def test_full_workflow_no_external_tools():
    """
    Verifies the entire workflow runs standalone with no external dependencies:
    load → extract → mask → translate → validate → inject → verify.
    No game files, no internet, no external libraries.
    """
    exh, exd, dialogue = _complex_sheet()

    # 1. Parse
    pipeline = TranslationPipeline(exh, exd)
    records = pipeline.extract()
    assert len(records) > 0

    # 2. All records expose human-readable text only (no raw binary bytes)
    for rec in records:
        assert isinstance(rec.masked_text, str)
        assert b"\x02" not in rec.masked_text.encode("utf-8", errors="replace"), \
            "Control code byte leaked into user-visible text"

    # 3. Machine translate (mock)
    mt = MockTranslator(prefix="")
    pipeline.apply_machine_translation(mt.translate)

    # 4. Validate — no corrupt records
    errored = [r for r in records if r.errors]
    assert not errored, f"Records with errors: {errored}"

    # 5. Inject
    new_exd = pipeline.inject()
    assert len(new_exd) > 32

    # 6. Re-parse — verify binary integrity
    schema = EXHParser(exh).result
    reparsed = EXDParser(new_exd, schema)
    assert len(reparsed.rows) == 2

    r0 = reparsed.rows[0].values[0]
    # Control codes must be byte-for-byte identical
    assert make_character_name_control() in r0, "Character name control code missing after inject"
    assert make_color_control(7) in r0,          "Color control code missing after inject"
    assert make_reset_control() in r0,            "Reset control code missing after inject"

    # Integer columns untouched (none in this sheet, but schema must parse cleanly)
    assert reparsed.rows[0].row_id == 0
    assert reparsed.rows[1].row_id == 1

    print("    => Full standalone workflow verified, 0 external dependencies")


# ─── Runner ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        # Masker
        test_mask_plain_text,
        test_mask_control_codes_roundtrip,
        test_mask_placeholder_at_start,
        test_mask_placeholder_at_end,
        test_validate_placeholders_all_present,
        test_validate_placeholders_missing,
        test_validate_placeholders_extra,
        test_unmask_unknown_placeholder_raises,
        # Parser
        test_parser_flat_sheet_columns,
        test_parser_flat_sheet_row_values,
        test_parser_subrow_sheet,
        test_parser_bad_magic_raises,
        test_parser_preserves_int_values,
        # Pipeline
        test_pipeline_extracts_only_strings,
        test_pipeline_empty_strings_skipped,
        test_pipeline_control_codes_masked_in_records,
        test_pipeline_inject_roundtrip_flat,
        test_pipeline_inject_preserves_int_columns,
        test_pipeline_inject_subrow,
        test_pipeline_untranslated_keeps_original,
        test_pipeline_error_record_keeps_original,
        test_pipeline_multipage,
        test_pipeline_stats_accuracy,
        test_pipeline_csv_roundtrip,
        test_pipeline_json_roundtrip,
        test_pipeline_placeholder_corruption_rejected,
        # Translator
        test_mock_translator_basic,
        test_mock_translator_preserves_placeholders,
        test_pipeline_apply_machine_translation,
        # Session
        test_session_save_load_roundtrip,
        test_session_summary_counts,
        # End-to-end
        test_full_workflow_no_external_tools,
    ]

    print(f"\n{'='*64}")
    print("  FFXIV Translation Tool — Full Audit Test Suite")
    print(f"{'='*64}\n")

    for t in tests:
        _run(t)

    print(f"\n{'='*64}")
    print(f"  Results: {PASS} passed, {FAIL} failed out of {PASS+FAIL} tests")
    print(f"{'='*64}\n")
    sys.exit(0 if FAIL == 0 else 1)
