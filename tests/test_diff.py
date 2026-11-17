import unittest

from automation import body_diff as D

from .helpers import cylinder


class TestPending(unittest.TestCase):
    def test_ebb_missing_gives_pending(self):
        r = D.field("EBB", "ANGEL")
        self.assertEqual(r["status"], "PENDING")
        self.assertTrue(r["reasons"])
        # 关键：不得给出任何编造的数值
        self.assertIsNone(r["measurements"])
        self.assertIsNone(r["surface"])
        self.assertEqual(r["confidence"]["level"], "NONE")

    def test_unknown_body_gives_pending_with_reason(self):
        r = D.field("NOT_A_BODY", "ANGEL")
        self.assertEqual(r["status"], "PENDING")
        self.assertEqual(r["datasource"]["source"]["error"] is not None, True)


class TestCompareModels(unittest.TestCase):
    def test_identity(self):
        a = cylinder(radius=0.1, segments=64)
        b = cylinder(radius=0.1, segments=64)
        r = D.compare_models(a, b, correspondence_kwargs={"cell_m": 0.05})
        self.assertEqual(r["status"], "READY")
        self.assertEqual(r["measurements"]["height"]["delta_m"], 0.0)
        self.assertEqual(r["surface"]["signed_normal_delta_m"]["median"], 0.0)
        self.assertEqual(r["confidence"]["level"], "HIGH")
        for name, reg in r["measurements"]["regions"].items():
            if reg["width_m"]["delta"] is not None:
                self.assertEqual(reg["width_m"]["delta"], 0.0)

    def test_thicker(self):
        a = cylinder(radius=0.10, segments=96)
        b = cylinder(radius=0.11, segments=96)
        r = D.compare_models(a, b, correspondence_kwargs={"cell_m": 0.05})
        self.assertEqual(r["status"], "READY")
        w = r["measurements"]["regions"]["thigh"]["width_m"]
        self.assertAlmostEqual(w["delta"], 0.02, delta=0.002)
        s = r["surface"]["signed_normal_delta_m"]
        # 源半径小 → 顶点落在目标表面内侧 → 有符号位移应为负
        self.assertLess(s["median"], 0.0)
        self.assertAlmostEqual(abs(s["median"]), 0.01, delta=0.002)

    def test_height_delta(self):
        a = cylinder(height=1.0)
        b = cylinder(height=1.1)
        r = D.compare_models(a, b, correspondence_kwargs={"cell_m": 0.05})
        self.assertAlmostEqual(r["measurements"]["height"]["delta_m"], 0.1, delta=1e-6)
        self.assertAlmostEqual(r["measurements"]["height"]["delta_ratio"], 0.1, delta=1e-5)

    def test_region_map_uses_height_not_name(self):
        a = cylinder()
        b = cylinder()
        r = D.compare_models(a, b, correspondence_kwargs={"cell_m": 0.05})
        m = r["measurements"]["region_map"]
        self.assertEqual(len(m), 10)
        for name, entry in m.items():
            self.assertIn("target_region", entry)
            self.assertLessEqual(abs(entry["delta_height_norm"]), 1.0)


if __name__ == "__main__":
    unittest.main()
