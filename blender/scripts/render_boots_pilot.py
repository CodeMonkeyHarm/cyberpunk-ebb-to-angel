"""Render source and safe boots over the same ANGEL body for geometry QA."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def arguments():
    argv = sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    for name in ("body", "source", "safe", "out"):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--candidate-label", default="safe")
    parser.add_argument("--closeup", action="store_true")
    return parser.parse_args(argv)


def imported(path):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(path))
    return [obj for obj in bpy.data.objects if obj not in before]


def material(name, rgba, roughness):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = rgba
    mat.use_nodes = True
    shader = mat.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = rgba
    shader.inputs["Roughness"].default_value = roughness
    return mat


def apply_material(objects, mat):
    for obj in objects:
        if obj.type == "MESH":
            obj.data.materials.clear()
            obj.data.materials.append(mat)


def light(position, energy, size):
    data = bpy.data.lights.new("Area", type="AREA")
    data.energy = energy
    data.shape = "DISK"
    data.size = size
    obj = bpy.data.objects.new("Area", data)
    bpy.context.collection.objects.link(obj)
    obj.location = position
    obj.rotation_euler = (Vector((0, 0, 0.7))-obj.location).to_track_quat("-Z", "Y").to_euler()


def main():
    a = arguments()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 12
    scene.render.resolution_x = 800
    scene.render.resolution_y = 900
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.world = bpy.data.worlds.new("QA background")
    scene.world.color = (0.09, 0.09, 0.09)
    scene.view_settings.view_transform = "Standard"
    body_mat = material("body_skin", (0.58, 0.38, 0.27, 1), 0.85)
    boot_mat = material("boots_black", (0.025, 0.045, 0.05, 1), 0.55)
    body = imported(a.body)
    apply_material(body, body_mat)
    light((1.7, -2.0, 2.2), 650, 2.0)
    light((-1.3, 1.5, 1.7), 450, 2.5)
    camera_data = bpy.data.cameras.new("camera")
    camera = bpy.data.objects.new("camera", camera_data)
    bpy.context.collection.objects.link(camera)
    scene.camera = camera
    camera_data.type = "ORTHO"
    focus_z = 1.02 if a.closeup else 0.67
    camera_data.ortho_scale = 0.56 if a.closeup else 1.5
    target = Vector((0, 0, focus_z))
    views = {"front": (0, -2.5, focus_z), "back": (0, 2.5, focus_z),
             "side": (2.5, 0, focus_z)}
    for label, path in (("source", a.source), (a.candidate_label, a.safe)):
        boot = imported(path)
        apply_material(boot, boot_mat)
        for view, position in views.items():
            camera.location = position
            camera.rotation_euler = (target-camera.location).to_track_quat("-Z", "Y").to_euler()
            scene.render.filepath = str(out/f"{label}_{view}.png")
            bpy.ops.render.render(write_still=True)
            print("RENDERED", scene.render.filepath, flush=True)
        for obj in boot:
            bpy.data.objects.remove(obj, do_unlink=True)


if __name__ == "__main__":
    main()
