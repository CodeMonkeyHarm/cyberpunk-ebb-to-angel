"""生成一个带骨骼/顶点组的测试 GLB（仅用于验证分析脚本的 skin 读取路径）。

用法：
    blender -b --factory-startup --python make_fixture_rigged.py -- --out <file.glb>
"""
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def parse():
    argv = sys.argv
    args = argv[argv.index("--") + 1:] if "--" in argv else []
    out = None
    for i, a in enumerate(args):
        if a == "--out" and i + 1 < len(args):
            out = args[i + 1]
    return out


def main():
    out = parse()
    if not out:
        print("缺少 --out")
        return 1
    bpy.ops.wm.read_factory_settings(use_empty=True)

    # 3 节骨骼
    arm_data = bpy.data.armatures.new("TestRig")
    arm = bpy.data.objects.new("TestRig", arm_data)
    bpy.context.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    prev = None
    for i, name in enumerate(("Root", "Mid", "Tip")):
        b = arm_data.edit_bones.new(name)
        b.head = Vector((0, 0, i * 0.2))
        b.tail = Vector((0, 0, (i + 1) * 0.2))
        if prev:
            b.parent = prev
            b.use_connect = True
        prev = b
    bpy.ops.object.mode_set(mode="OBJECT")

    # 柱状网格
    bpy.ops.mesh.primitive_cylinder_add(vertices=16, depth=0.6, radius=0.08,
                                        location=(0, 0, 0.3))
    mesh_obj = bpy.context.active_object
    mesh_obj.name = "TestShaft"

    g_root = mesh_obj.vertex_groups.new(name="Root")
    g_tip = mesh_obj.vertex_groups.new(name="Tip")
    for v in mesh_obj.data.vertices:
        w = max(0.0, min(1.0, v.co.z / 0.6))
        g_root.add([v.index], 1.0 - w, "REPLACE")
        g_tip.add([v.index], w, "REPLACE")

    mesh_obj.parent = arm
    mod = mesh_obj.modifiers.new("Armature", "ARMATURE")
    mod.object = arm

    mat = bpy.data.materials.new("TestMat")
    mat.use_nodes = True
    mesh_obj.data.materials.append(mat)

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.export_scene.gltf(filepath=str(Path(out)), export_format="GLB",
                              use_selection=True, export_skins=True,
                              export_apply=False)
    print("FIXTURE_OK", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
