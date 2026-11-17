import unittest

from automation import body_profiles as P


class TestProfiles(unittest.TestCase):
    def test_list_contains_angel_and_ebb(self):
        ids = P.list_profiles()
        self.assertIn("ANGEL", ids)
        self.assertIn("EBB", ids)

    def test_load_angel(self):
        prof = P.load("angel")          # 大小写不敏感
        self.assertEqual(prof["body_id"], "ANGEL")
        self.assertTrue(prof["available"])
        self.assertTrue(prof["source"]["mesh_json"])

    def test_unknown_body_raises(self):
        with self.assertRaises(P.ProfileError):
            P.load("NOPE")

    def test_ebb_is_placeholder(self):
        prof = P.load("EBB")
        self.assertFalse(prof["available"])
        self.assertEqual(prof["status"], "AWAITING_SOURCE")
        with self.assertRaises(P.ProfileError):
            P.require_source(prof)

    def test_validate_rejects_placeholder_with_data(self):
        prof = P.load("EBB")
        bad = dict(prof)
        bad["source"] = dict(prof["source"])
        bad["source"]["mesh_json"] = "something.json"
        with self.assertRaises(P.ProfileError):
            P.validate(bad)

    def test_output_paths_template(self):
        prof = P.load("ANGEL")
        paths = P.output_paths(prof, override="out/x")
        self.assertEqual(paths["dir"].name, "x")
        self.assertEqual(paths["static"].name, "ANGEL_Body_Static.glb")
        self.assertEqual(paths["morphology"].name, "ANGEL_Morphology.json")

    def test_output_version_follows_profile(self):
        prof = P.load("ANGEL")
        prof = dict(prof)
        prof["asset_version"] = "9.9.9"
        self.assertIn("9.9.9", str(P.output_dir(prof)))


if __name__ == "__main__":
    unittest.main()
