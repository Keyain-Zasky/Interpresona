import tempfile
import unittest
from pathlib import Path

from interpresona_installer import game_version, release_compatibility, source_manifest_metadata


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


if __name__ == "__main__":
    unittest.main()
