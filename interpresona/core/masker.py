"""
SeString Masker / Unmasker
==========================
Extracts FFXIV dialogue control codes from SeString bytes, replaces them
with safe text placeholders for machine translation, then restores them.

Key invariant:  mask(raw) → (masked_text, map)
                unmask(translated_text, map) → bytes == original control codes

The masked text is safe to pass to any MT engine without risk of corrupting
control code bytes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .parser import decode_varint

# Placeholder format:  ⟪VAR_n⟫   (uses Unicode brackets unlikely to appear in text)
_PLACEHOLDER_RE = re.compile(r"⟪VAR_(\d+)⟫")
_PLACEHOLDER_FMT = "⟪VAR_{n}⟫"


@dataclass
class MaskedString:
    """Result of masking a SeString."""
    text: str                           # Human-readable text with placeholders
    placeholders: dict[int, bytes]      # n → original raw bytes of control code


@dataclass
class Segment:
    """A single parsed segment of a SeString."""
    kind: str          # "text" | "control"
    value: bytes       # raw bytes of this segment


# ---------------------------------------------------------------------------
# Low-level SeString scanner
# ---------------------------------------------------------------------------

def _scan_segments(raw: bytes) -> list[Segment]:
    """
    Split raw SeString bytes into alternating text and control-code segments.
    Control codes have the form: 0x02 <type> <varint-len> <payload> 0x03
    """
    segments: list[Segment] = []
    n = len(raw)
    i = 0
    while i < n:
        if raw[i] == 0x02:
            # Parse control code
            start = i
            if i + 1 >= n:
                raise ValueError(f"Truncated control code at byte {i}: missing type byte")
            i += 2  # skip 0x02 and type
            length, consumed = decode_varint(raw, i)
            i += consumed
            payload_end = i + length
            if payload_end >= n:
                raise ValueError(
                    f"Control code payload out of bounds: payload_end={payload_end}, n={n}"
                )
            if raw[payload_end] != 0x03:
                raise ValueError(
                    f"Expected 0x03 at {payload_end}, got 0x{raw[payload_end]:02X}"
                )
            end = payload_end + 1
            segments.append(Segment(kind="control", value=raw[start:end]))
            i = end
        else:
            # Accumulate text until the next 0x02 or end
            start = i
            while i < n and raw[i] != 0x02:
                i += 1
            segments.append(Segment(kind="text", value=raw[start:i]))
    return segments


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def mask(raw: bytes) -> MaskedString:
    """
    Replace every control code in *raw* with a numbered placeholder.

    Returns a MaskedString whose .text field can be safely machine-translated.
    """
    segments = _scan_segments(raw)
    parts: list[str] = []
    placeholders: dict[int, bytes] = {}
    counter = 0

    for seg in segments:
        if seg.kind == "text":
            parts.append(seg.value.decode("utf-8", errors="replace"))
        else:
            token = _PLACEHOLDER_FMT.format(n=counter)
            placeholders[counter] = seg.value
            parts.append(token)
            counter += 1

    return MaskedString(text="".join(parts), placeholders=placeholders)


def unmask(translated: str, placeholders: dict[int, bytes]) -> bytes:
    """
    Replace placeholders in *translated* back with the original binary control codes.

    Returns the reassembled SeString bytes ready to be written into the EXD file.
    Raises ValueError if a placeholder index referenced in the text is missing from
    the map (indicating the MT engine corrupted a token).
    """
    result = bytearray()
    last = 0
    for m in _PLACEHOLDER_RE.finditer(translated):
        n = int(m.group(1))
        if n not in placeholders:
            raise ValueError(
                f"unmask: placeholder ⟪VAR_{n}⟫ not found in map "
                f"(MT engine may have altered or deleted it)"
            )
        # Append text before this placeholder
        text_chunk = translated[last: m.start()]
        result.extend(text_chunk.encode("utf-8"))
        # Append original control code bytes
        result.extend(placeholders[n])
        last = m.end()

    # Append any trailing text
    result.extend(translated[last:].encode("utf-8"))
    return bytes(result)


def validate_placeholders(translated: str, expected: dict[int, bytes]) -> list[str]:
    """
    Validate that all expected placeholders are still present in *translated*.
    Returns a list of error messages (empty = OK).
    """
    errors: list[str] = []
    found_indices = {int(m.group(1)) for m in _PLACEHOLDER_RE.finditer(translated)}
    expected_indices = set(expected.keys())

    missing = expected_indices - found_indices
    extra = found_indices - expected_indices
    for n in sorted(missing):
        errors.append(f"Placeholder ⟪VAR_{n}⟫ was removed by the MT engine")
    for n in sorted(extra):
        errors.append(f"Unknown placeholder ⟪VAR_{n}⟫ introduced by the MT engine")
    return errors
