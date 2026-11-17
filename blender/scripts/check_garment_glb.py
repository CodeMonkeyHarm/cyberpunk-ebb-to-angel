"""Blender 后台导入验证：服装 GLB。

用法：
  blender -b --factory-startup --python check_garment_glb.py -- --dir <glb_dir> --out <json>

对每个 .glb：统计对象数、顶点、面、材质、世界包围盒，并检查是否存在退化面/空物体。
不做任何修改，只读取。
"""
import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    args = {}
    i = 0
    while i < len(argv):
        if argv[i].startswith("--"):
            args[argv[i][2:]] = argv[i + 1]
            i += 2
        else:
            i += 1
    return args


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def main():
    args = parse_args()
    gdir = Path(args["dir"])
    out = Path(args["out"])
    results = []
    for glb in sorted(gdir.glob("*.glb")):
        reset()
        before = set(bpy.data.objects)
        bpy.ops.import_scene.gltf(filepath=str(glb))
        new = [o for o in bpy.data.objects if o not in before and o.type == "MESH"]
        verts = sum(len(o.data.vertices) for o in new)
        polys = sum(len(o.data.polygons) for o in new)
        mn = Vector((1e9, 1e9, 1e9))
        mx = Vector((-1e9, -1e9, -1e9))
        for o in new:
            for v in o.data.vertices:
                w = o.matrix_world @ v.co
                for k in range(3):
                    mn[k] = min(mn[k], w[k])
                    mx[k] = max(mx[k], w[k])
        degenerate = 0
        for o in new:
            for p in o.data.polygons:
                if p.area < 1e-12:
                    degenerate += 1
        results.append({
            "glb": glb.name,
            "mesh_objects": [o.name for o in new],
            "vertices": verts,
            "polygons": polys,
            "materials": sorted({m.name for o in new for m in o.data.materials if m}),
            "bbox_min": [round(mn[k], 6) for k in range(3)],
            "bbox_max": [round(mx[k], 6) for k in range(3)],
            "size": [round(mx[k] - mn[k], 6) for k in range(3)],
            "degenerate_faces": degenerate,
            "status": "OK" if new and verts > 0 else "EMPTY",
        })
        print(f"[check] {glb.name}: {len(new)} obj / {verts} v / {polys} poly")

    payload = {"status": "OK", "blender": bpy.app.version_string, "results": results}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("GARMENT_CHECK_OK " + json.dumps({"count": len(results), "out": str(out)}, ensure_ascii=False))


main()
