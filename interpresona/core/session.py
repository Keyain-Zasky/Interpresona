"""
Session Persistence
===================
Saves and restores the full translation state (extraction records + metadata)
as a JSON file.  This lets you pause work, close the tool, and resume later
without losing any translations.

Session file schema (JSON):
{
  "version": 2,
  "sheet_name": "NpcYell",
  "language": "en",
  "source_files": {"exh": "...", "exd": "..."},   // original file paths (info only)
  "exh_b64": "<base64>",      // raw EXH bytes
  "exd_pages_b64": ["<base64>", ...],   // one entry per page (v2+)
  "records": [
    {
      "row_id": 0,
      "sub_row_id": null,
      "col_idx": 0,
      "original_b64": "<base64>",   // original SeString bytes
      "masked_text": "Hello ⟪VAR_0⟫!",
      "translated_text": "Ciao ⟪VAR_0⟫!",
      "placeholders": {"0": "<base64>"},  // n → base64-encoded control code bytes
      "errors": []
    },
    ...
  ]
}
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Optional

from .pipeline import ExtractionRecord, TranslationPipeline


SESSION_VERSION = 2


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _fromb64(s: str) -> bytes:
    return base64.b64decode(s)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def save_session(
    path: Path,
    pipeline: TranslationPipeline,
    sheet_name: str = "",
    language: str = "",
    source_exh_path: str = "",
    source_exd_path: str = "",
) -> None:
    """
    Serialise the current pipeline state to a .ffxivts session file.
    Supports multi-page EXD sheets — all pages are stored.
    """
    records_data = []
    for rec in pipeline.records:
        ph_encoded = {str(n): _b64(raw) for n, raw in rec.placeholders.items()}
        records_data.append({
            "row_id":          rec.row_id,
            "sub_row_id":      rec.sub_row_id,
            "col_idx":         rec.col_idx,
            "original_b64":    _b64(rec.original_bytes),
            "masked_text":     rec.masked_text,
            "translated_text": rec.translated_text or "",
            "placeholders":    ph_encoded,
            "errors":          list(rec.errors),
        })

    # Save all EXD pages
    exd_pages_b64 = [_b64(p) for p in pipeline._exd_pages]

    session = {
        "version":       SESSION_VERSION,
        "sheet_name":    sheet_name,
        "language":      language,
        "source_files":  {"exh": source_exh_path, "exd": source_exd_path},
        "exh_b64":       _b64(pipeline._exh_bytes),
        "exd_pages_b64": exd_pages_b64,
        # Legacy single-page key for back-compat readers
        "exd_b64":       exd_pages_b64[0] if exd_pages_b64 else "",
        "records":       records_data,
    }

    path.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")


def load_session(path: Path) -> tuple[TranslationPipeline, dict]:
    """
    Deserialise a session file.

    Returns:
        (pipeline, metadata)  where metadata contains sheet_name, language, etc.
    Raises:
        ValueError if the file format is invalid.
    """
    raw = path.read_text(encoding="utf-8")
    try:
        session = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid session file: {exc}") from exc

    version = session.get("version", 0)
    if version not in (1, 2):
        raise ValueError(f"Unsupported session version {version} (expected 1 or 2)")

    exh_bytes = _fromb64(session["exh_b64"])

    # Support both v1 (single exd_b64) and v2 (list exd_pages_b64)
    if "exd_pages_b64" in session and session["exd_pages_b64"]:
        exd_pages = [_fromb64(p) for p in session["exd_pages_b64"]]
    elif "exd_b64" in session:
        exd_pages = [_fromb64(session["exd_b64"])]
    else:
        raise ValueError("Session file contains no EXD data")

    # Reconstruct the pipeline (re-parses binary)
    pipeline = TranslationPipeline(exh_bytes, exd_pages)
    pipeline.extract()  # builds record list from fresh parse

    # Overlay the saved translations onto the freshly-extracted records
    saved_map = {}
    for r in session.get("records", []):
        key = (r["row_id"], r.get("sub_row_id"), r["col_idx"])
        saved_map[key] = r

    for rec in pipeline.records:
        saved = saved_map.get(rec.key)
        if saved is None:
            continue
        translated = saved.get("translated_text", "")
        if translated:
            rec.translated_text = translated
        # Restore placeholder map (JSON keys are strings → convert back to int)
        if "placeholders" in saved:
            rec.placeholders = {
                int(n): _fromb64(b64) for n, b64 in saved["placeholders"].items()
            }
        errors = saved.get("errors", [])
        if errors:
            rec.errors = list(errors)

    metadata = {
        "sheet_name":   session.get("sheet_name", ""),
        "language":     session.get("language", ""),
        "source_files": session.get("source_files", {}),
        "version":      version,
    }
    return pipeline, metadata


def session_summary(path: Path) -> dict:
    """
    Read only the metadata from a session file (fast, without full decode).
    Returns a dict with version, sheet_name, language, record counts.
    """
    raw = path.read_text(encoding="utf-8")
    session = json.loads(raw)
    records = session.get("records", [])
    translated = sum(1 for r in records if r.get("translated_text", ""))
    errored    = sum(1 for r in records if r.get("errors", []))
    return {
        "version":    session.get("version"),
        "sheet_name": session.get("sheet_name", ""),
        "language":   session.get("language", ""),
        "total":      len(records),
        "translated": translated,
        "pending":    len(records) - translated - errored,
        "errored":    errored,
    }
