"""Render v3/v4 dress over the same ANGEL body for offline chest inspection."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--body", required=True)
    parser.add_argument("--v3", required=True)
    parser.add_argument("--v4", required=True)
    parser.add_argument("--author", required=True)
    parser.add_argument("--wide", required=True)
    parser.add_argument("--out", required=True)
    return parser.parse_args(argv)


def material(name, rgba, roughness):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = rgba
    mat.use_nodes = True
    shader = mat.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = rgba
    shader.inputs["Roughness"].default_value = roughness
    return mat


def imported(path):
    old = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(path))
    return [obj for obj in bpy.data.objects if obj not in old and obj.type == "MESH"]


def set_material(objects, mat):
    for obj in objects:
        obj.data.materials.clear()
        obj.data.materials.append(mat)


def area_light(location, energy, size):
    light = bpy.data.lights.new("Area", type="AREA")
    light.energy = energy
    light.shape = "DISK"
    light.size = size
    obj = bpy.data.objects.new("Area", light)
    bpy.context.collection.objects.link(obj)
    obj.location = location
    direction = Vector((0, 0, 1.1)) - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def main():
    a = args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 16
    scene.render.resolution_x = 800
    scene.render.resolution_y = 800
    scene.render.resolution_percentage = 100
    scene.world = bpy.data.worlds.new("QA background")
    scene.world.color = (0.09, 0.09, 0.09)
    scene.view_settings.view_transform = "Standard"
    scene.render.image_settings.file_format = "PNG"
    body_mat = material("body_skin", (0.72, 0.47, 0.32, 1), 0.85)
    dress_mat = material("dress_black", (0.03, 0.08, 0.07, 1), 0.55)
    body = imported(a.body)
    set_material(body, body_mat)
    area_light((1.6, -2.0, 2.5), 700, 2.0)
    area_light((-1.3, 1.5, 2.0), 450, 2.5)
    camera_data = bpy.data.cameras.new("camera")
    camera = bpy.data.objects.new("camera", camera_data)
    bpy.context.collection.objects.link(camera)
    scene.camera = camera
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = 0.92
    target = Vector((0, 0, 1.08))
    views = {"front": (0, -2.5, 1.08), "back": (0, 2.5, 1.08),
             "side": (2.5, 0, 1.08)}
    for label, path in (("v3", a.v3), ("v4", a.v4), ("v4_wide", a.wide),
                        ("author", a.author)):
        dress = imported(path)
        set_material(dress, dress_mat)
        for view, position in views.items():
            camera.location = position
            camera.rotation_euler = (target - camera.location).to_track_quat("-Z", "Y").to_euler()
            scene.render.filepath = str(out / f"{label}_{view}.png")
            bpy.ops.render.render(write_still=True)
            print("RENDERED", scene.render.filepath)
        bpy.data.objects.remove(dress[0], do_unlink=True)


if __name__ == "__main__":
    main()
