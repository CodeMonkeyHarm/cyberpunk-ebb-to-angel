import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import prepare_boot_recipe


class TestRecipePreparation(unittest.TestCase):
    def test_rejects_wrong_body_before_creating_recipe(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            report = root / "reports/phase2/BodyDifference_EBBRB_to_ANGEL.json"
            report.parent.mkdir(parents=True)
            report.write_text(json.dumps({"source_body": "EBB", "target_body": "ANGEL"}))
            with patch.object(prepare_boot_recipe, "ROOT", root):
                with self.assertRaisesRegex(ValueError, "EBBRB-to-ANGEL"):
                    prepare_boot_recipe.main()
            self.assertFalse((root / "config/boot_recipe.local.json").exists())

    def test_rejects_field_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            report = root / "reports/phase2/BodyDifference_EBBRB_to_ANGEL.json"
            field = root / "audit/phase2/diff_v2/displacement_field.npz"
            report.parent.mkdir(parents=True)
            field.parent.mkdir(parents=True)
            field.write_bytes(b"wrong field")
            report.write_text(json.dumps({"source_body": "EBBRB", "target_body": "ANGEL",
                                          "displacement_field": {"sha256": "different"}}))
            with patch.object(prepare_boot_recipe, "ROOT", root):
                with self.assertRaisesRegex(ValueError, "Field bytes"):
                    prepare_boot_recipe.main()
            self.assertFalse((root / "config/boot_recipe.local.json").exists())
