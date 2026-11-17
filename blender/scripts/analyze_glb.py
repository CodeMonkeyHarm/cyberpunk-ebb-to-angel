"""Blender 后台分析脚本：只读 GLB，输出结构化 JSON。不修改任何模型。

用法：
    blender -b --factory-startup --python analyze_glb.py -- \
        --glb <file.glb> --out <report.json> [--detail]

输出 JSON 字段：
    status / glb / blender_version / scene / objects[] / meshes[] / materials[]
    armatures[] / summary{}
"""
import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector

OK_MARK = "WBX_SCRIPT_OK"


def parse_args():
    argv = sys.argv
    args = argv[argv.index("--") + 1:] if "--" in argv else []
    out = {"glb": None, "out": None, "detail": False}
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--glb" and i + 1 < len(args):
            out["glb"] = args[i + 1]
            i += 2
        elif a == "--out" and i + 1 < len(args):
            out["out"] = args[i + 1]
            i += 2
        elif a == "--detail":
            out["detail"] = True
            i += 1
        else:
            i += 1
    return out


def world_bbox(obj):
    pts = [obj.matrix_world @ Vector(c) for c in obj.bound_box] if obj.type == "MESH" else []
    if not pts:
        return None
    mn = [min(p[i] for p in pts) for i in range(3)]
    mx = [max(p[i] for p in pts) for i in range(3)]
    return {"min": [round(v, 6) for v in mn], "max": [round(v, 6) for v in mx]}


def local_bbox(me):
    if not me.vertices:
        return None
    xs = [v.co.x for v in me.vertices]
    ys = [v.co.y for v in me.vertices]
    zs = [v.co.z for v in me.vertices]
    return {"min": [round(min(xs), 6), round(min(ys), 6), round(min(zs), 6)],
            "max": [round(max(xs), 6), round(max(ys), 6), round(max(zs), 6)]}


def collect():
    data = {"blender_version": bpy.app.version_string, "units": None,
            "objects": [], "meshes": [], "materials": [], "armatures": [],
            "images": [], "collections": [c.name for c in bpy.data.collections],
            "helpers": []}
    us = bpy.context.scene.unit_settings
    data["units"] = {"system": us.system, "scale_length": round(us.scale_length, 6),
                     "length_unit": us.length_unit}

    # glTF 导入器会为骨骼创建辅助显示网格（如 Icosphere），不计入模型统计
    helpers = set()
    for ob in bpy.data.objects:
        if ob.type == "ARMATURE" and ob.pose:
            for pb in ob.pose.bones:
                if pb.custom_shape:
                    helpers.add(pb.custom_shape.name)
    data["helpers"] = sorted(helpers)

    for obj in bpy.data.objects:
        if obj.name in helpers:
            continue
        rec = {"name": obj.name, "type": obj.type,
               "parent": obj.parent.name if obj.parent else None,
               "children": [c.name for c in obj.children],
               "location": [round(v, 6) for v in obj.location],
               "rotation_euler": [round(v, 6) for v in obj.rotation_euler],
               "scale": [round(v, 6) for v in obj.scale],
               "dimensions": [round(v, 6) for v in obj.dimensions],
               "modifiers": [{"name": m.name, "type": m.type} for m in obj.modifiers],
               "vertex_groups": [g.name for g in obj.vertex_groups],
               "materials": [ms.material.name if ms.material else None
                             for ms in obj.material_slots]}
        bb = world_bbox(obj)
        if bb:
            rec["world_bbox"] = bb
        data["objects"].append(rec)

        if obj.type == "MESH" and obj.data:
            me = obj.data
            me.calc_loop_triangles()
            uv = [layer.name for layer in me.uv_layers]
            data["meshes"].append({
                "object": obj.name,
                "mesh": me.name,
                "vertices": len(me.vertices),
                "edges": len(me.edges),
                "polygons": len(me.polygons),
                "triangles": len(me.loop_triangles),
                "uv_layers": uv,
                "color_attributes": [a.name for a in me.color_attributes],
                "materials": rec["materials"],
                "vertex_group_count": len(obj.vertex_groups),
                "local_bbox": local_bbox(me),
                "world_bbox": bb,
                "dimensions": rec["dimensions"],
                "has_shape_keys": bool(me.shape_keys),
                "custom_normals": bool(getattr(me, "has_custom_normals", False)),
            })

        if obj.type == "ARMATURE" and obj.data:
            bones = list(obj.data.bones)
            data["armatures"].append({
                "object": obj.name,
                "bone_count": len(bones),
                "root_bones": [b.name for b in bones if b.parent is None][:10],
                "bones_preview": [b.name for b in bones][:40],
            })

    for mat in bpy.data.materials:
        entry = {"name": mat.name, "users": mat.users, "use_nodes": mat.use_nodes,
                 "nodes": [], "images": []}
        if mat.use_nodes and mat.node_tree:
            for node in mat.node_tree.nodes:
                entry["nodes"].append({"name": node.name, "type": node.type})
                if node.type == "TEX_IMAGE" and node.image:
                    entry["images"].append(node.image.name)
        entry["images"] = sorted(set(entry["images"]))
        data["materials"].append(entry)

    for img in bpy.data.images:
        data["images"].append({"name": img.name, "size": list(img.size),
                               "filepath": img.filepath, "packed": bool(img.packed_file)})
    return data


def summarize(data):
    meshes = data["meshes"]
    total_v = sum(m["vertices"] for m in meshes)
    total_t = sum(m["triangles"] for m in meshes)
    biggest = max(meshes, key=lambda m: m["vertices"]) if meshes else None
    arm = data["armatures"][0] if data["armatures"] else None
    return {
        "object_count": len(data["objects"]),
        "mesh_count": len(meshes),
        "armature_count": len(data["armatures"]),
        "material_count": len(data["materials"]),
        "image_count": len(data["images"]),
        "total_vertices": total_v,
        "total_triangles": total_t,
        "largest_mesh": {"object": biggest["object"], "vertices": biggest["vertices"]}
        if biggest else None,
        "bone_count": arm["bone_count"] if arm else 0,
        "has_uv": any(m["uv_layers"] for m in meshes),
        "has_vertex_groups": any(m["vertex_group_count"] > 0 for m in meshes),
        "scene_dimensions": {
            "x": round(max((o["dimensions"][0] for o in data["objects"]), default=0), 6),
            "y": round(max((o["dimensions"][1] for o in data["objects"]), default=0), 6),
            "z": round(max((o["dimensions"][2] for o in data["objects"]), default=0), 6),
        },
    }


def main():
    args = parse_args()
    if not args["glb"] or not args["out"]:
        print("缺少 --glb / --out")
        return 1
    glb = Path(args["glb"])
    if not glb.is_file():
        print(f"glb 不存在: {glb}")
        return 1

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(glb))

    data = collect()
    data["glb"] = str(glb)
    data["glb_bytes"] = glb.stat().st_size
    data["summary"] = summarize(data)
    data["status"] = "OK"

    out = Path(args["out"])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"ANALYZED {glb.name} -> {out}")
    print(OK_MARK)
    return 0


if __name__ == "__main__":
    sys.exit(main())
