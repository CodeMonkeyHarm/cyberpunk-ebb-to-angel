import math
import unittest

from automation import body_morphology as M

from .helpers import cylinder


class TestSection(unittest.TestCase):
    def setUp(self):
        self.r = 0.10
        self.h = 1.0
        self.model = cylinder(radius=self.r, height=self.h, segments=96)
        self.an = M.BodyMorphologyAnalyzer(self.model)

    def test_section_area_matches_circle(self):
        sec = self.an.section(0.5)
        expect = math.pi * self.r ** 2
        # 96 边形：面积 = (n/2) r² sin(2π/n)，与 πr² 差 <0.05%
        self.assertEqual(sec["loops"], 1)
        self.assertAlmostEqual(sec["area_m2"], expect, delta=expect * 0.001)
        self.assertAlmostEqual(sec["width_m"], 2 * self.r, delta=0.002)
        self.assertAlmostEqual(sec["thickness_m"], 2 * self.r, delta=0.002)
        self.assertEqual(sec["open_polylines"], 0)
        self.assertEqual(sec["quality"], "OK")

    def test_section_empty_above_mesh(self):
        sec = self.an.section(1.5)
        self.assertEqual(sec["loops"], 0)
        self.assertEqual(sec["quality"], "EMPTY")

    def test_stability_is_small_on_smooth_body(self):
        reg = self.an.region("thigh")
        self.assertIsNotNone(reg["section"]["stability_rel_change"])
        self.assertLess(reg["section"]["stability_rel_change"], 1e-3)

    def test_silhouette_width(self):
        f = self.an.silhouette("front", 50)
        self.assertAlmostEqual(f["max_extent_m"], 2 * self.r, delta=0.003)
        self.assertEqual(len(f["profile"]), f["bands"])

    def test_upper_arm_not_applicable_without_arms(self):
        reg = self.an.region("upper_arm")
        self.assertEqual(reg["status"], "N/A")
        self.assertFalse(reg["applicable"])
        self.assertTrue(reg["reliability"]["reasons"])

    def test_height_normalization(self):
        self.assertAlmostEqual(self.an.height_norm(0.0), 0.0, places=6)
        self.assertAlmostEqual(self.an.height_norm(1.0), 1.0, places=6)


if __name__ == "__main__":
    unittest.main()
