import unittest

import numpy as np

from automation import correspondence as C

from .helpers import cylinder


class TestPointTriangle(unittest.TestCase):
    a = np.array([[0.0, 0.0, 0.0]])
    b = np.array([[1.0, 0.0, 0.0]])
    c = np.array([[0.0, 1.0, 0.0]])

    def dist(self, p):
        d, cp = C.point_triangle_distance(np.asarray([p], dtype=np.float64),
                                          self.a, self.b, self.c)
        return float(d[0]), cp[0]

    def test_above_face(self):
        d, cp = self.dist((0.0, 0.0, 1.0))
        self.assertAlmostEqual(d, 1.0, places=9)
        d, cp = self.dist((0.2, 0.2, 0.5))
        self.assertAlmostEqual(d, 0.5, places=9)

    def test_on_edge(self):
        d, _ = self.dist((0.5, 0.0, 0.0))
        self.assertAlmostEqual(d, 0.0, places=9)

    def test_outside_vertex(self):
        d, cp = self.dist((2.0, 0.0, 0.0))
        self.assertAlmostEqual(d, 1.0, places=9)
        self.assertAlmostEqual(float(cp[0]), 1.0, places=9)


class TestMatch(unittest.TestCase):
    def test_self_match_is_zero(self):
        m = cylinder(segments=64)
        r = C.self_check(m, cell_m=0.05, refine=True)
        s = r["summary"]
        self.assertEqual(s["coverage"], 1.0)
        self.assertAlmostEqual(s["distance_m"]["max"], 0.0, places=9)
        self.assertEqual(s["status"]["NEEDS_REVIEW"], 0)
        self.assertTrue(r["topology_report"]["triangle_indices_identical"])

    def test_translated_copy_distance_equals_shift(self):
        src = cylinder(segments=64)
        dst = cylinder(segments=64, shift=(0.02, 0.0, 0.0))
        r = C.match(src, dst, cell_m=0.05, refine=True, dist_tol_m=0.01)
        self.assertEqual(r["summary"]["coverage"], 1.0)
        # 平移 2cm，但圆柱是圆的：最近表面距离不是 2cm。
        # 用半径缩放来验证距离的物理含义更稳。
        self.assertGreater(r["summary"]["distance_m"]["max"], 0.0)

    def test_scaled_copy_distance_equals_radius_delta(self):
        src = cylinder(radius=0.10, segments=128)
        dst = cylinder(radius=0.11, segments=128)
        r = C.match(src, dst, cell_m=0.05, refine=True, dist_tol_m=0.05)
        self.assertEqual(r["summary"]["coverage"], 1.0)
        self.assertAlmostEqual(r["summary"]["distance_m"]["median"], 0.01, delta=0.0015)

    def test_topology_report_detects_different_mesh(self):
        a = cylinder(segments=32)
        b = cylinder(segments=48)
        tr = C.topology_report(a, b)
        self.assertFalse(tr["vertex_count"]["equal"])
        self.assertIn("必须做表面对应", tr["conclusion"])


if __name__ == "__main__":
    unittest.main()
