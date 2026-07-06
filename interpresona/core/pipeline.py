"""
Translation Pipeline
====================
High-level orchestration that ties together:
  1. Parse EXH (schema) + EXD (rows)
  2. Extract localizable strings → ExtractionRecord list
  3. Mask control codes → safe text for MT
  4. (Optional) Apply MT translation
  5. Validate placeholder integrity
  6. Unmask translated text → binary SeString bytes
  7. Inject translated bytes back → new EXD binary

Everything operates on in-memory bytes, so the caller is responsible for
reading/writing actual files.
"""
from __future__ import annotations

import json
import csv
import io
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Optional

from .parser import EXHParser, EXDParser, EXHSchema, RowData
from .masker import mask, unmask, validate_placeholders, MaskedString
from .injector import EXDInjector


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ExtractionRecord:
    """One extractable string cell."""
    row_id: int
    sub_row_id: Optional[int]         # None for depth-1 sheets
    col_idx: int
    original_bytes: bytes             # raw SeString bytes
    masked_text: str                  # text safe for MT (control codes replaced)
    translated_text: Optional[str]    # filled in after MT
    placeholders: dict[int, bytes]    # n → control-code bytes
    errors: list[str] = field(default_factory=list)

    @property
    def key(self):
        return (self.row_id, self.sub_row_id, self.col_idx)

    def as_csv_row(self) -> dict:
        return {
            "row_id": self.row_id,
            "sub_row_id": "" if self.sub_row_id is None else self.sub_row_id,
            "col_idx": self.col_idx,
            "original": self.masked_text,
            "translated": self.translated_text or "",
        }


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class TranslationPipeline:
    """
    Manages the full extract → mask → translate → unmask → inject lifecycle.

    Multi-page support
    ------------------
    FFXIV splits large sheets across multiple EXD files (pages).  The EXH header
    lists each page's start row-ID and row count.

    Pass a list of EXD byte-strings (one per page, in page order) instead of a
    single bytes object to load all pages at once::

        pipeline = TranslationPipeline(exh_bytes, [page0_bytes, page1_bytes, ...])

    When injecting, call inject_all() to get a dict {page_index: translated_bytes}.
    The single-page inject() convenience method still works for page 0 only.
    """

    @property
    def exh_bytes(self) -> bytes:
        return self._exh_bytes

    def __init__(self, exh_bytes: bytes, exd_bytes):
        """
        exd_bytes: bytes (single page) or list[bytes] (one entry per page).
        """
        self._exh_bytes = exh_bytes
        # Normalise to list[bytes]
        if isinstance(exd_bytes, (bytes, bytearray)):
            self._exd_pages: list[bytes] = [bytes(exd_bytes)]
        else:
            self._exd_pages = [bytes(b) for b in exd_bytes]
        # Back-compat: _exd_bytes = page 0
        self._exd_bytes = self._exd_pages[0] if self._exd_pages else b""
        self.schema: Optional[EXHSchema] = None
        self.rows: list[RowData] = []
        self._row_page: dict[int, int] = {}   # row_id → page index
        self.records: list[ExtractionRecord] = []
        self._parse()

    # ------------------------------------------------------------------
    # Step 1: Parse
    # ------------------------------------------------------------------
    def _parse(self):
        exh_parser = EXHParser(self._exh_bytes)
        self.schema = exh_parser.result
        self.rows = []
        self._row_page = {}
        for page_idx, page_bytes in enumerate(self._exd_pages):
            page_parser = EXDParser(page_bytes, self.schema)
            for row in page_parser.rows:
                self._row_page[row.row_id] = page_idx
            self.rows.extend(page_parser.rows)

    # ------------------------------------------------------------------
    # Step 2: Extract & Mask
    # ------------------------------------------------------------------
    def extract(self) -> list[ExtractionRecord]:
        """Extract all string columns and mask their control codes."""
        self.records = []

        for row in self.rows:
            if self.schema.depth == 1:
                self._extract_values(row.row_id, None, row.values)
            else:
                for sub in row.sub_rows:
                    self._extract_values(row.row_id, sub["sub_row_id"], sub["values"])

        return self.records

    def _extract_values(
        self,
        row_id: int,
        sub_row_id: Optional[int],
        values: dict[int, Any],
    ):
        for idx, col in enumerate(self.schema.columns):
            if not col.is_string:
                continue
            raw: bytes = values.get(idx, b"")
            if not raw:
                continue
            try:
                masked = mask(raw)
            except Exception as exc:
                masked = MaskedString(text=raw.decode("utf-8", errors="replace"), placeholders={})
                # Store as record with error
                rec = ExtractionRecord(
                    row_id=row_id, sub_row_id=sub_row_id, col_idx=idx,
                    original_bytes=raw, masked_text=masked.text,
                    translated_text=None, placeholders={},
                    errors=[f"Masking error: {exc}"],
                )
                self.records.append(rec)
                continue

            self.records.append(ExtractionRecord(
                row_id=row_id, sub_row_id=sub_row_id, col_idx=idx,
                original_bytes=raw, masked_text=masked.text,
                translated_text=None, placeholders=masked.placeholders,
            ))

    # ------------------------------------------------------------------
    # Step 3: Export for translation
    # ------------------------------------------------------------------
    def export_csv(self) -> str:
        """Return a CSV string with columns: row_id, sub_row_id, col_idx, original, translated."""
        buf = io.StringIO()
        writer = csv.DictWriter(
            buf, fieldnames=["row_id", "sub_row_id", "col_idx", "original", "translated"],
            quoting=csv.QUOTE_ALL,
        )
        writer.writeheader()
        for rec in self.records:
            writer.writerow(rec.as_csv_row())
        return buf.getvalue()

    def export_json(self) -> str:
        """Return a JSON array of extraction records (without raw bytes)."""
        data = [
            {
                "row_id": r.row_id,
                "sub_row_id": r.sub_row_id,
                "col_idx": r.col_idx,
                "original": r.masked_text,
                "translated": r.translated_text or "",
            }
            for r in self.records
        ]
        return json.dumps(data, ensure_ascii=False, indent=2)

    # ------------------------------------------------------------------
    # Step 4: Import translations
    # ------------------------------------------------------------------
    def import_translations_from_csv(self, csv_text: str) -> list[str]:
        """
        Read back a translated CSV and populate record.translated_text.
        Returns a list of validation warnings/errors.
        """
        errors: list[str] = []
        reader = csv.DictReader(io.StringIO(csv_text))
        index = {r.key: r for r in self.records}

        for row in reader:
            try:
                rid = int(row["row_id"])
                sid = None if row.get("sub_row_id", "") == "" else int(row["sub_row_id"])
                cidx = int(row["col_idx"])
                translated = row.get("translated", "")
            except (KeyError, ValueError) as exc:
                errors.append(f"Malformed CSV row: {exc}")
                continue

            key = (rid, sid, cidx)
            rec = index.get(key)
            if rec is None:
                errors.append(f"Unknown key in CSV: {key}")
                continue

            # Validate placeholder integrity
            ph_errors = validate_placeholders(translated, rec.placeholders)
            if ph_errors:
                errors.extend([f"Row {rid}/{sid}/col{cidx}: {e}" for e in ph_errors])
                rec.errors.extend(ph_errors)
            else:
                rec.translated_text = translated

        return errors

    def import_translations_from_json(self, json_text: str) -> list[str]:
        """Same as import_translations_from_csv but for JSON input."""
        errors: list[str] = []
        try:
            data = json.loads(json_text)
        except json.JSONDecodeError as exc:
            return [f"Invalid JSON: {exc}"]

        index = {r.key: r for r in self.records}
        for item in data:
            try:
                rid = int(item["row_id"])
                sid = item.get("sub_row_id")
                cidx = int(item["col_idx"])
                translated = item.get("translated", "")
            except (KeyError, ValueError) as exc:
                errors.append(f"Malformed JSON item: {exc}")
                continue
            key = (rid, sid, cidx)
            rec = index.get(key)
            if rec is None:
                errors.append(f"Unknown key: {key}")
                continue
            ph_errors = validate_placeholders(translated, rec.placeholders)
            if ph_errors:
                errors.extend([f"Row {rid}/{sid}/col{cidx}: {e}" for e in ph_errors])
                rec.errors.extend(ph_errors)
            else:
                rec.translated_text = translated
        return errors

    def apply_machine_translation(self, translate_fn: Callable[[list[str]], list[str]]) -> list[str]:
        """
        Call *translate_fn* on all untranslated records (batch).

        translate_fn(texts: list[str]) -> list[str]
            Must return exactly as many strings as it receives.

        Returns validation errors detected post-translation.
        """
        pending = [r for r in self.records if not r.translated_text and not r.errors]
        if not pending:
            return []

        texts = [r.masked_text for r in pending]
        try:
            results = translate_fn(texts)
        except Exception as exc:
            return [f"MT engine error: {exc}"]

        if len(results) != len(pending):
            return [f"MT engine returned {len(results)} results for {len(pending)} inputs"]

        errors: list[str] = []
        for rec, translated in zip(pending, results):
            ph_errors = validate_placeholders(translated, rec.placeholders)
            if ph_errors:
                errors.extend([f"Row {rec.row_id}/{rec.sub_row_id}/col{rec.col_idx}: {e}" for e in ph_errors])
                rec.errors.extend(ph_errors)
            else:
                rec.translated_text = translated
        return errors

    # ------------------------------------------------------------------
    # Step 5: Build overrides & inject
    # ------------------------------------------------------------------
    def build_overrides(self) -> dict:
        """
        Convert translated records into the override dict expected by EXDInjector.
        Only records with a valid translated_text are included.
        Records with errors are skipped.
        """
        overrides: dict = {}
        for rec in self.records:
            if not rec.translated_text or rec.errors:
                continue
            try:
                new_bytes = unmask(rec.translated_text, rec.placeholders)
            except Exception as exc:
                rec.errors.append(f"Unmask error: {exc}")
                continue

            if self.schema.depth == 1:
                key = rec.row_id
            else:
                key = (rec.row_id, rec.sub_row_id)

            if key not in overrides:
                overrides[key] = {}
            overrides[key][rec.col_idx] = new_bytes

        return overrides

    def inject(self) -> bytes:
        """
        Build and return the translated EXD binary for page 0.
        For multi-page sheets use inject_all().
        """
        return self.inject_all().get(0, b"")

    def inject_all(self) -> dict[int, bytes]:
        """
        Build translated EXD binaries for ALL pages.
        Returns {page_index: translated_bytes}.
        Only rows whose page_index is known are included in each page file.
        """
        overrides = self.build_overrides()
        results: dict[int, bytes] = {}

        for page_idx, page_bytes in enumerate(self._exd_pages):
            # Parse this page fresh to get its original row list
            page_parser = EXDParser(page_bytes, self.schema)
            page_rows = page_parser.rows

            injector = EXDInjector(self.schema, page_rows)
            injector.apply_overrides(overrides)
            results[page_idx] = injector.build()

        return results

    @property
    def page_count(self) -> int:
        """Number of EXD pages loaded."""
        return len(self._exd_pages)

    # ------------------------------------------------------------------
    # Convenience stats
    # ------------------------------------------------------------------
    @property
    def stats(self) -> dict:
        total = len(self.records)
        translated = sum(1 for r in self.records if r.translated_text)
        errored = sum(1 for r in self.records if r.errors)
        return {
            "total": total,
            "translated": translated,
            "pending": total - translated - errored,
            "errored": errored,
            "pages": self.page_count,
        }
