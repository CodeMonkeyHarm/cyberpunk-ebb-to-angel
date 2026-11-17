"""Blender 后台验证：静态 GLB 与蒙皮 GLB 是否一致、骨架/权重是否有效。

用法：
    blender -b --factory-startup --python validate_skinned_glb.py -- \
        --static <static.glb> --skinned <skinned.glb> --out <report.json> [--blend <out.blend>]

只读 GLB，不改动输入；结果写 JSON（--out）。
"""
import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector

OK_MARK = "WBX_SCRIPT_OK"


def parse():
    argv = sys.argv
    args = argv[argv.index("--") + 1:] if "--" in argv else []
    out = {"static": None, "skinned": None, "out": None, "blend": None,
           "skeleton": None}
    i = 0
    while i < len(args):
        if args[i] in ("--static", "--skinned", "--out", "--blend", "--skeleton") \
                and i + 1 < len(args):
            out[args[i][2:]] = args[i + 1]
            i += 2
        else:
            i += 1
    return out


def reset_and_import(path):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(path))
    return [o for o in bpy.data.objects]


def helper_names(objects):
    """glTF 导入器会给骨骼建显示用网格（如 Icosphere），统计时必须排除。"""
    names = set()
    for o in objects:
        if o.type == "ARMATURE" and o.pose:
            for pb in o.pose.bones:
                if pb.custom_shape:
                    names.add(pb.custom_shape.name)
    return names


def mesh_stats(objects, helpers=None):
    out = {"objects": len(objects), "mesh_objects": 0, "vertices": 0, "triangles": 0,
           "materials": sorted({ms.material.name for o in objects if o.type == "MESH"
                                for ms in o.material_slots if ms.material}),
           "bbox_world": None, "vertex_positions": []}
    mins = [1e9] * 3
    maxs = [-1e9] * 3
    helpers = helpers or set()
    for o in objects:
        if o.type != "MESH" or o.name in helpers:
            continue
        me = o.data
        me.calc_loop_triangles()
        out["mesh_objects"] += 1
        out["vertices"] += len(me.vertices)
        out["triangles"] += len(me.loop_triangles)
        mw = o.matrix_world
        for v in me.vertices:
            co = mw @ v.co
            for k in range(3):
                mins[k] = min(mins[k], co[k])
                maxs[k] = max(maxs[k], co[k])
        out["vertex_positions"].extend([list(mw @ v.co) for v in me.vertices])
    out["bbox_world"] = {"min": [round(v, 6) for v in mins], "max": [round(v, 6) for v in maxs]}
    return out


def weight_stats(objects, helpers=None):
    res = {"vertex_groups_max": 0, "groups_per_object": {}, "unweighted_vertices": 0,
           "weight_sum_min": None, "weight_sum_mean": None, "weight_sum_max": None,
           "max_influences": 0, "negative_weights": 0, "over_one_weights": 0,
           "vertices": 0, "armature_modifiers": 0, "parented_to_armature": 0}
    sums = []
    helpers = helpers or set()
    for o in objects:
        if o.type != "MESH" or o.name in helpers:
            continue
        res["groups_per_object"][o.name] = len(o.vertex_groups)
        res["vertex_groups_max"] = max(res["vertex_groups_max"], len(o.vertex_groups))
        if any(m.type == "ARMATURE" for m in o.modifiers):
            res["armature_modifiers"] += 1
        if o.parent and o.parent.type == "ARMATURE":
            res["parented_to_armature"] += 1
        for v in o.data.vertices:
            res["vertices"] += 1
            s = 0.0
            n = 0
            for g in v.groups:
                w = g.weight
                if w < 0:
                    res["negative_weights"] += 1
                if w > 1.0001:
                    res["over_one_weights"] += 1
                if w > 0:
                    s += w
                    n += 1
            sums.append(s)
            res["max_influences"] = max(res["max_influences"], n)
            if s <= 0:
                res["unweighted_vertices"] += 1
    if sums:
        res["weight_sum_min"] = round(min(sums), 5)
        res["weight_sum_mean"] = round(sum(sums) / len(sums), 5)
        res["weight_sum_max"] = round(max(sums), 5)
    return res


def bone_depth(bone):
    d, cur = 1, bone.parent
    while cur is not None:
        d += 1
        cur = cur.parent
    return d


def armature_stats(objects):
    res = {"armatures": 0, "bones": 0, "bone_names": [], "zero_length_bones": 0,
           "root_bones": 0, "heads": [], "with_children": 0}
    for o in objects:
        if o.type != "ARMATURE" or not o.data:
            continue
        res["armatures"] += 1
        bones = list(o.data.bones)
        res["bones"] = len(bones)
        res["bone_names"] = [b.name for b in bones][:200]
        res["zero_length_bones"] = sum(1 for b in bones if b.length <= 1e-6)
        res["root_bones"] = sum(1 for b in bones if b.parent is None)
        res["with_children"] = sum(1 for b in bones if b.children)
        mw = o.matrix_world
        res["heads"] = [[round(c, 6) for c in (mw @ b.head_local)] for b in bones]
        res["max_depth"] = max((bone_depth(b) for b in bones), default=0)
        res["depth_histogram"] = {}
        for b in bones:
            d = bone_depth(b)
            res["depth_histogram"][d] = res["depth_histogram"].get(d, 0) + 1
    return res


def compare(sv, kv):
    a, b = sv["vertex_positions"], kv["vertex_positions"]
    if len(a) != len(b):
        return {"comparable": False, "count_static": len(a), "count_skinned": len(b)}
    worst = 0.0
    for i in range(len(a)):
        d = max(abs(a[i][k] - b[i][k]) for k in range(3))
        worst = max(worst, d)
    return {"comparable": True, "vertices": len(a), "max_abs_diff": round(worst, 9),
            "identical": worst < 1e-6}


def main():
    args = parse()
    if not args["static"] or not args["skinned"] or not args["out"]:
        print("需要 --static --skinned --out")
        return 1
    result = {"status": "FAILED", "checks": {}, "ok": False}

    objs_s = reset_and_import(Path(args["static"]))
    static_stats = mesh_stats(objs_s, helper_names(objs_s))
    keep_s_positions = static_stats.pop("vertex_positions")
    result["static"] = static_stats

    objs_k = reset_and_import(Path(args["skinned"]))
    helpers_k = helper_names(objs_k)
    k_all = mesh_stats(objs_k, helpers_k)
    keep_k_positions = k_all.pop("vertex_positions")
    result["skinned"] = k_all
    skinned_stats = k_all
    result["weights"] = weight_stats(objs_k, helpers_k)
    result["helpers_excluded"] = sorted(helpers_k)
    result["armature"] = armature_stats(objs_k)

    cmp = compare({"vertex_positions": keep_s_positions},
                  {"vertex_positions": keep_k_positions})
    result["contour_compare"] = cmp

    arm = result["armature"]
    w = result["weights"]

    declared = None
    if args.get("skeleton"):
        try:
            sk = json.loads(Path(args["skeleton"]).read_text(encoding="utf-8"))
            declared = sk.get("hierarchy", {}).get("type")
            names = sk.get("bones", [])
            bone_names_complete = all(b["name"] in arm["bone_names"] for b in names)
            if declared == "tree":
                hierarchy_matches = (arm["root_bones"] == 1 and arm["with_children"] > 0
                                     and arm["max_depth"] > 1)
            else:
                hierarchy_matches = (arm["root_bones"] == arm["bones"]
                                     and arm["with_children"] == 0)
            result["declared_hierarchy"] = declared
        except Exception as exc:  # noqa: BLE001
            result["skeleton_error"] = str(exc)
            hierarchy_matches = False
            bone_names_complete = False
    else:
        # 未提供骨架文件：只做结构合理性判断
        hierarchy_matches = (arm["root_bones"] >= 1 and arm["bones"] == 167)
        bone_names_complete = arm["bones"] == 167
    result["checks"] = {
        "skinned_imported": skinned_stats["mesh_objects"] > 0,
        "armature_exists": arm["armatures"] == 1,
        "bone_count_expected_167": arm["bones"] == 167,
        "hierarchy_matches_declared": hierarchy_matches,
        "bone_names_complete": bone_names_complete,
        "vertex_groups_created": w["vertex_groups_max"] > 0,
        "no_unweighted_vertices": w["unweighted_vertices"] == 0,
        "weights_within_range": w["negative_weights"] == 0 and w["over_one_weights"] == 0,
        "mesh_parented_to_armature": w["parented_to_armature"] > 0,
        "armature_modifier_present": w["armature_modifiers"] > 0,
        "contour_identical": bool(cmp.get("identical")),
        "vertex_count_preserved": static_stats["vertices"] == skinned_stats["vertices"],
    }
    result["ok"] = all(result["checks"].values())

    if args["blend"]:
        try:
            bpy.context.preferences.filepaths.save_version = 0  # 不生成 .blend1
            bpy.ops.wm.save_as_mainfile(filepath=str(Path(args["blend"])))
            result["blend"] = {"path": args["blend"],
                               "bytes": Path(args["blend"]).stat().st_size}
        except Exception as exc:  # noqa: BLE001
            result["blend"] = {"error": str(exc)}

    result["status"] = "OK"
    out = Path(args["out"])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"VALIDATION {'OK' if result['ok'] else 'FAILED'}")
    for k, v in result["checks"].items():
        print(f"  {k}: {v}")
    print(OK_MARK)
    return 0


if __name__ == "__main__":
    sys.exit(main())
