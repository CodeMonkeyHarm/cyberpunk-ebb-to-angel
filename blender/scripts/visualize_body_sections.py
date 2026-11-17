"""Blender 可视化：把身形网格与截面环路放进同一个 .blend，并渲染正交视图。

用法（由 automation/main.py 调用）：
    blender -b -P visualize_body_sections.py -- \
        --body ANGEL --glb <skinned.glb> --morphology <*_Morphology.json> \
        --outdir <dir> --blend <dir>/ANGEL_Body_Sections.blend --render

坐标：GLB 导入后 Blender 场景为 Z-up，与 CP77 源坐标同向，
所以形态 JSON 里的 (x, y, z) 可以直接用，不需要再转换。
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

STATUS_COLOR = {
    "HIGH": (0.15, 0.75, 0.30, 1.0),
    "MEDIUM": (0.95, 0.70, 0.10, 1.0),
    "LOW": (0.90, 0.15, 0.15, 1.0),
    "N/A": (0.45, 0.45, 0.45, 1.0),
}


def parse_args() -> dict:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    args = {"render": False}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--render":
            args["render"] = True
            i += 1
            continue
        if a.startswith("--"):
            args[a[2:]] = argv[i + 1]
            i += 2
            continue
        i += 1
    return args


def reset_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def import_glb(path: Path) -> list:
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(path))
    return [o for o in bpy.data.objects if o not in before]


def mesh_objects(objects: list) -> list:
    """排除 glTF 导入器为骨骼生成的显示网格（如 Icosphere，42 顶点、无顶点组）。"""
    helpers = set()
    for o in objects:
        if o.type == "ARMATURE" and o.pose:
            for pb in o.pose.bones:
                if pb.custom_shape:
                    helpers.add(pb.custom_shape.name)
    out = []
    for o in objects:
        if o.type != "MESH" or o.name in helpers:
            continue
        small_no_groups = len(o.data.vertices) < 512 and len(o.vertex_groups) == 0
        if small_no_groups:
            helpers.add(o.name)
            continue
        out.append(o)
    return out


def make_section_curve(name: str, loop_points: list, z: float, color, width: float = 0.0025):
    """把一串 XY 点变成高度 z 处的多段线（曲线，带 bevel 以便看清）。"""
    cu = bpy.data.curves.new(name, type="CURVE")
    cu.dimensions = "3D"
    cu.bevel_depth = width
    cu.bevel_resolution = 2
    sp = cu.splines.new("POLY")
    pts = loop_points + ([loop_points[0]] if loop_points else [])
    sp.points.add(len(pts) - 1)
    for i, (x, y) in enumerate(pts):
        sp.points[i].co = (x, y, z, 1.0)
    obj = bpy.data.objects.new(name, cu)
    mat = bpy.data.materials.get(f"M_{name}")
    if mat is None:
        mat = bpy.data.materials.new(f"M_{name}")
        mat.diffuse_color = color
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf:
            bsdf.inputs["Base Color"].default_value = color
            bsdf.inputs["Emission Color"].default_value = color
            bsdf.inputs["Emission Strength"].default_value = 1.5
    cu.materials.append(mat)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def bounds(objects: list) -> tuple[Vector, Vector]:
    """直接从数据取包围盒：曲线对象的 bound_box 在新建对象上不可靠。"""
    mn = Vector((1e9, 1e9, 1e9))
    mx = Vector((-1e9, -1e9, -1e9))
    for o in objects:
        pts = []
        if o.type == "MESH":
            mw = o.matrix_world
            pts = [mw @ v.co for v in o.data.vertices]
        elif o.type == "CURVE":
            for sp in o.data.splines:
                pts.extend(Vector((p.co[0], p.co[1], p.co[2])) for p in sp.points)
        for w in pts:
            mn = Vector((min(mn.x, w.x), min(mn.y, w.y), min(mn.z, w.z)))
            mx = Vector((max(mx.x, w.x), max(mx.y, w.y), max(mx.z, w.z)))
    return mn, mx


def setup_camera(mn: Vector, mx: Vector, direction: str = "front"):
    center = (mn + mx) / 2
    factor = 1.35 if direction == "three_quarter" else 1.05
    size = max((mx - mn).x, (mx - mn).z) * factor
    cam_data = bpy.data.cameras.new("Cam")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = size
    cam = bpy.data.objects.new("Cam", cam_data)
    bpy.context.scene.collection.objects.link(cam)
    dist = max((mx - mn).length, 1.0) * 2.0
    # 角色朝 +Y（脚趾指 +Y），所以正面相机放在 +Y 侧朝 -Y 看
    if direction == "front":
        cam.location = center + Vector((0, dist, 0))
        cam.rotation_euler = (math.radians(90), 0, math.radians(180))
    elif direction == "side":
        cam.location = center + Vector((-dist, 0, 0))
        cam.rotation_euler = (math.radians(90), 0, math.radians(-90))
    else:  # three-quarter（右前上方）
        cam.location = center + Vector((-dist * 0.7, dist * 0.7, dist * 0.25))
        cam.rotation_euler = (math.radians(78), 0, math.radians(225))
    bpy.context.scene.camera = cam
    return cam


def add_lights():
    data = bpy.data.lights.new("Key", type="SUN")
    data.energy = 4.0
    obj = bpy.data.objects.new("Key", data)
    obj.rotation_euler = (math.radians(55), 0, math.radians(30))
    bpy.context.scene.collection.objects.link(obj)
    data2 = bpy.data.lights.new("Fill", type="SUN")
    data2.energy = 2.0
    obj2 = bpy.data.objects.new("Fill", data2)
    obj2.rotation_euler = (math.radians(70), 0, math.radians(-120))
    bpy.context.scene.collection.objects.link(obj2)


def render_views(render_dir: Path, mn: Vector, mx: Vector, body: str) -> list:
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.show_cavity = True
    scene.render.resolution_x = 720
    scene.render.resolution_y = 1200
    scene.render.film_transparent = False
    scene.world = bpy.data.worlds.new("W")
    scene.world.color = (0.05, 0.05, 0.06)
    out = []
    for direction in ("front", "side", "three_quarter"):
        cam = setup_camera(mn, mx, direction)
        scene.camera = cam
        scene.render.filepath = str((render_dir / f"{body}_{direction}.png").resolve())
        try:
            bpy.ops.render.render(write_still=True)
            out.append(scene.render.filepath)
        except Exception as exc:  # noqa: BLE001
            out.append(f"FAILED:{direction}:{exc}")
        bpy.data.objects.remove(cam, do_unlink=True)
    return out


def main() -> None:
    args = parse_args()
    body = args.get("body", "ANGEL")
    glb = Path(args["glb"])
    morph = json.loads(Path(args["morphology"]).read_text(encoding="utf-8"))
    outdir = Path(args["outdir"])
    outdir.mkdir(parents=True, exist_ok=True)
    render_dir = (outdir / "renders").resolve()
    render_dir.mkdir(exist_ok=True)

    reset_scene()
    objs = import_glb(glb)
    meshes = mesh_objects(objs)
    detail = morph.get("sections_detail") or {}
    regions = morph.get("regions") or {}

    curves = []
    for name, sec in detail.items():
        reg = regions.get(name) or {}
        status = reg.get("status", "N/A")
        z = sec.get("z")
        if z is None or status == "N/A":
            continue  # 不适用的区域不画，避免误读
        color = STATUS_COLOR.get(status, STATUS_COLOR["N/A"])
        for li, loop in enumerate(sec.get("loop_data") or []):
            pts = loop.get("contour") or []
            if len(pts) < 3:
                continue
            curves.append(make_section_curve(
                f"SECTION_{name}_{li:02d}_{status}", pts, z, color))

    add_lights()
    mn, mx = bounds(meshes + curves) if meshes else (Vector((-1, -1, 0)),
                                                     Vector((1, 1, 2)))
    renders = render_views(render_dir, mn, mx, body) if args.get("render") else []

    blend_path = Path(args["blend"])
    bpy.context.preferences.filepaths.save_version = 0  # 不生成 .blend1
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))

    result = {
        "status": "OK",
        "body": body,
        "glb": str(glb),
        "objects": {"meshes": [o.name for o in meshes], "curves": len(curves),
                    "curve_names": [c.name for c in curves][:40]},
        "regions_with_curves": sorted(detail.keys()),
        "region_status": {n: r.get("status") for n, r in regions.items()},
        "bounds": {"min": list(mn), "max": list(mx)},
        "renders": renders,
        "blend": str(blend_path),
        "blend_bytes": blend_path.stat().st_size if blend_path.is_file() else 0,
    }
    print("VISUALIZE_OK " + json.dumps(result, ensure_ascii=False))


main()
