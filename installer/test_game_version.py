import tempfile
import unittest
import struct
from pathlib import Path
from unittest import mock

from interpresona_installer import (
    engine,
    game_version,
    release_compatibility,
    selected_sheets,
    source_manifest_metadata,
    valid_release_exd_path,
)


class GameVersionCompatibilityTests(unittest.TestCase):
    def make_game(self, version="2026.08.11.0000.0000"):
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name) / "game"
        sqpack = root / "sqpack" / "ffxiv"
        sqpack.mkdir(parents=True)
        if version is not None:
            (root / "ffxivgame.ver").write_text(version + "\n", encoding="ascii")
        self.addCleanup(temporary.cleanup)
        return sqpack

    def test_reads_version_from_normal_sqpack_layout(self):
        game = self.make_game()
        self.assertEqual(game_version(game), "2026.08.11.0000.0000")

    def test_exact_version_is_compatible(self):
        game = self.make_game()
        result = release_compatibility(game, {"game_version": "2026.08.11.0000.0000"})
        self.assertTrue(result["compatible"])
        self.assertEqual(result["state"], "compatible")

    def test_different_version_is_rejected(self):
        game = self.make_game()
        result = release_compatibility(game, {"game_version": "2026.08.12.0000.0000"})
        self.assertFalse(result["compatible"])
        self.assertEqual(result["state"], "mismatch")

    def test_release_without_exact_version_is_rejected(self):
        game = self.make_game()
        result = release_compatibility(game, {"game_patch": "7.55"})
        self.assertFalse(result["compatible"])
        self.assertEqual(result["state"], "release-version-missing")

    def test_install_without_version_file_is_rejected(self):
        game = self.make_game(version=None)
        result = release_compatibility(game, {"game_version": "2026.08.11.0000.0000"})
        self.assertFalse(result["compatible"])
        self.assertEqual(result["state"], "game-version-missing")

    def test_downloaded_source_manifest_keeps_exact_version_contract(self):
        remote = {
            "version": "0.48",
            "game_patch": "7.55 Dawntrail Update",
            "game_version": "2026.08.11.0000.0000",
            "build_id": 123,
            "last_updated": "2026-08-29T00:00:00+00:00",
        }
        copied = source_manifest_metadata(remote)
        self.assertEqual(copied["game_version"], remote["game_version"])

    def test_hierarchical_sheet_name_is_preserved(self):
        self.assertEqual(
            selected_sheets(["custom/003/jobdefdrk_00300.csv"], False),
            ["custom/003/jobdefdrk_00300"],
        )

    def test_hierarchical_exd_path_is_valid_for_its_sheet(self):
        sheet = "custom/003/jobdefdrk_00300"
        self.assertTrue(valid_release_exd_path(sheet, sheet + "_0_en.exd"))
        self.assertFalse(valid_release_exd_path(sheet, "../jobdefdrk_00300_0_en.exd"))
        self.assertFalse(valid_release_exd_path(sheet, "custom/003/other_0_en.exd"))

    def test_forced_technical_string_replaces_only_runtime_identifier(self):
        schema = {
            "columns": [(0, 0)],
            "row_size": 4,
            "variant": 1,
            "pages": [(0, 1)],
        }
        string_pool = b"Tradotto\x00"
        fixed = struct.pack(">I", 0)
        padding = bytes((4 - ((2 + len(fixed) + len(string_pool)) % 4)) % 4)
        payload = fixed + string_pool + padding
        row = struct.pack(">IH", len(payload), 1) + payload
        raw = (
            b"EXDF\x00\x02\x00\x00"
            + struct.pack(">II", 8, len(row))
            + bytes(16)
            + struct.pack(">II", 1, 40)
            + row
        )
        canonical = {(1, None, 0): "Canonical"}
        with (
            mock.patch.dict(engine.FORCED_TECHNICAL_STRING_COLUMNS, {"test": frozenset({0})}, clear=True),
            mock.patch.object(engine, "read_file", return_value=b"EXHF"),
            mock.patch.object(engine, "parse_exh", return_value=schema),
            mock.patch.object(engine, "_detect_technical_string_columns", return_value=(frozenset({0}), canonical)),
        ):
            normalized = engine.enforce_forced_technical_strings("test", "test_0_en.exd", raw)
        record = engine._row_records(normalized, schema)[0]
        value = engine._raw_string(
            normalized, record, record["subs"][0]["fixed"], schema["columns"], 0
        )
        self.assertEqual(value, b"Canonical\x00")


if __name__ == "__main__":
    unittest.main()
