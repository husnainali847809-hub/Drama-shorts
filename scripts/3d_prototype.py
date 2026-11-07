"""Render a deterministic 5-second stylized 3D cartoon prototype with Blender.

Run:
  blender -b -P scripts/3d_prototype.py -- --output output/prototype.mp4
"""
import argparse
import math
import os
import subprocess
import sys
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]


def cli_args():
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="output/prototype.mp4")
    return parser.parse_args(args)


def material(name, color, roughness=0.72):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*color, 1.0)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Roughness"].default_value = roughness
    return mat


def uv_sphere(name, location, scale, mat, parent=None, segments=32, rings=20):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=segments, ring_count=rings, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    obj.data.materials.append(mat)
    bpy.ops.object.shade_smooth()
    if parent:
        obj.parent = parent
    return obj


def cylinder_between(name, start, end, radius, mat, vertices=24):
    a, b = Vector(start), Vector(end)
    direction = b - a
    bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=radius, depth=direction.length,
                                        location=(a + b) / 2)
    obj = bpy.context.object
    obj.name = name
    obj.rotation_mode = "QUATERNION"
    obj.rotation_quaternion = direction.to_track_quat("Z", "Y")
    obj.data.materials.append(mat)
    bpy.ops.object.shade_smooth()
    bevel = obj.modifiers.new("Soft rounded edges", "BEVEL")
    bevel.width = min(radius * 0.22, 0.08)
    bevel.segments = 3
    obj.modifiers.new("Weighted corner normals", "WEIGHTED_NORMAL")
    return obj


def look_at(obj, point):
    obj.rotation_euler = (Vector(point) - obj.location).to_track_quat("-Z", "Y").to_euler()


def build_scene(output_path):
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)

    brown = material("Warm caramel fur", (0.48, 0.19, 0.075))
    light_brown = material("Face and belly", (0.88, 0.58, 0.34))
    cream = material("Eye whites", (1.0, 0.96, 0.82))
    dark = material("Deep cocoa", (0.055, 0.025, 0.02))
    pink = material("Ear inner", (0.95, 0.34, 0.32))
    green = material("Jungle grass", (0.12, 0.34, 0.16))
    leaf_a = material("Leaf green", (0.13, 0.42, 0.19))
    leaf_b = material("Leaf light", (0.28, 0.57, 0.24))
    trunk = material("Tree bark", (0.28, 0.13, 0.065))
    gold = material("Golden hat", (0.98, 0.61, 0.08))

    # Ground and softly layered jungle backdrop.
    bpy.ops.mesh.primitive_plane_add(size=200, location=(0, 0, -0.08))
    ground = bpy.context.object
    ground.name = "Soft green jungle floor"
    ground.data.materials.append(green)

    for i, x in enumerate((-4.0, -2.8, 2.8, 4.0)):
        height = 2.8 + (i % 2) * 0.6
        cylinder_between("Rounded tree trunk", (x, 1.2, 0), (x, 1.2, height), 0.22, trunk)
        uv_sphere("Tree canopy", (x, 1.2, height + 0.55), (1.0, 0.65, 1.0),
                  leaf_a if i % 2 else leaf_b)

    # Character root lets the whole character bounce without changing its rig.
    root = bpy.data.objects.new("Momo character root", None)
    bpy.context.collection.objects.link(root)

    uv_sphere("Momo body", (0, 0, 1.15), (0.66, 0.48, 0.83), brown, root)
    uv_sphere("Momo belly", (0, -0.405, 1.12), (0.43, 0.12, 0.58), light_brown, root)
    uv_sphere("Momo head", (0, -0.02, 2.25), (0.82, 0.62, 0.77), brown, root)
    uv_sphere("Momo face patch", (0, -0.565, 2.12), (0.57, 0.13, 0.43), light_brown, root)
    uv_sphere("Momo muzzle", (0, -0.68, 1.99), (0.31, 0.12, 0.18), light_brown, root)

    for side in (-1, 1):
        uv_sphere("Round ear", (side * 0.78, -0.05, 2.35), (0.27, 0.18, 0.31), brown, root)
        uv_sphere("Ear center", (side * 0.79, -0.205, 2.35), (0.14, 0.045, 0.19), pink, root)
        uv_sphere("Eye white", (side * 0.29, -0.675, 2.36), (0.16, 0.075, 0.21), cream, root)
        uv_sphere("Eye pupil", (side * 0.27, -0.744, 2.34), (0.075, 0.04, 0.115), dark, root)

    uv_sphere("Nose", (0, -0.79, 2.06), (0.105, 0.07, 0.075), dark, root)
    # A simple jaunty top hat.
    bpy.ops.mesh.primitive_cylinder_add(vertices=48, radius=0.48, depth=0.09,
                                        location=(0.08, -0.02, 2.91))
    brim = bpy.context.object
    brim.name = "Hat brim"
    brim.data.materials.append(gold)
    bpy.ops.mesh.primitive_cylinder_add(vertices=48, radius=0.31, depth=0.48,
                                        location=(0.08, -0.02, 3.18))
    crown = bpy.context.object
    crown.name = "Hat crown"
    crown.data.materials.append(gold)
    uv_sphere("Left foot", (-0.37, -0.12, 0.28), (0.35, 0.48, 0.19), dark, root)
    uv_sphere("Right foot", (0.37, -0.12, 0.28), (0.35, 0.48, 0.19), dark, root)

    # Arms are separate animated pieces for a clear wave.
    left_arm = uv_sphere("Momo waving arm", (0.78, -0.05, 1.68), (0.19, 0.22, 0.56), brown, root)
    left_arm.rotation_euler[1] = math.radians(-28)
    uv_sphere("Momo waving hand", (0.99, -0.08, 2.12), (0.23, 0.2, 0.22), light_brown, root)
    right_arm = uv_sphere("Momo other arm", (-0.77, -0.02, 1.47), (0.19, 0.22, 0.53), brown, root)
    uv_sphere("Momo other hand", (-0.87, -0.08, 1.05), (0.22, 0.2, 0.2), light_brown, root)

    # Curved tail behind the body.
    curve = bpy.data.curves.new("Momo curled tail", "CURVE")
    curve.dimensions = "3D"
    curve.bevel_depth = 0.075
    curve.bevel_resolution = 4
    spline = curve.splines.new("BEZIER")
    spline.bezier_points.add(3)
    for point, co in zip(spline.bezier_points,
                         ((0.45, 0.25, 0.9), (1.1, 0.35, 0.85),
                          (1.25, 0.3, 1.45), (0.82, 0.25, 1.48))):
        point.co = co
        point.handle_left_type = "AUTO"
        point.handle_right_type = "AUTO"
    tail = bpy.data.objects.new("Momo curled tail", curve)
    bpy.context.collection.objects.link(tail)
    tail.data.materials.append(brown)
    tail.parent = root

    # Camera and lighting.
    bpy.ops.object.camera_add(location=(0, -10.5, 3.0))
    camera = bpy.context.object
    camera.name = "Portrait cartoon camera"
    look_at(camera, (0, 0, 1.65))
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = 4.9
    bpy.context.scene.camera = camera

    bpy.ops.object.light_add(type="AREA", location=(-4, -5, 7))
    key = bpy.context.object
    key.name = "Large soft key light"
    key.data.energy = 850
    key.data.shape = "DISK"
    key.data.size = 5
    look_at(key, (0, 0, 1.5))

    bpy.ops.object.light_add(type="AREA", location=(4, 1, 5))
    fill = bpy.context.object
    fill.name = "Warm rim light"
    fill.data.energy = 550
    fill.data.size = 4
    look_at(fill, (0, 0, 1.7))

    scene = bpy.context.scene
    # Blender 5.x exposes EEVEE under this engine identifier.
    scene.render.engine = "BLENDER_EEVEE"
    if hasattr(scene, "eevee"):
        scene.eevee.taa_render_samples = 8
    scene.render.resolution_x = 360
    scene.render.resolution_y = 640
    scene.render.resolution_percentage = 100
    scene.render.fps = 12
    scene.frame_start = 1
    scene.frame_end = 60
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "Medium High Contrast"
    scene.world.color = (0.12, 0.12, 0.12)

    # Gentle bounce and a readable repeated wave.
    for frame, z in ((1, 0.0), (12, 0.10), (24, 0.0), (36, 0.10),
                     (48, 0.0), (60, 0.08), (72, 0.0), (96, 0.10), (120, 0.0)):
        root.location.z = z
        root.keyframe_insert(data_path="location", frame=frame)
    for frame, angle in ((1, -25), (12, 18), (24, -18), (36, 20),
                         (48, -18), (60, 18), (72, -18), (96, 18), (120, -25)):
        left_arm.rotation_euler[1] = math.radians(angle)
        left_arm.keyframe_insert(data_path="rotation_euler", frame=frame)

    # Soft contact shadows and filmic-looking ambient shading.
    scene.render.image_settings.color_depth = "8"
    scene.camera.data.lens = 50
    scene.render.filepath = str((ROOT / "output" / "frames" / "frame_").resolve())
    scene.render.use_file_extension = True
    scene.render.film_transparent = False
    scene.camera.data.dof.use_dof = False

    output_path.parent.mkdir(parents=True, exist_ok=True)
    (ROOT / "output" / "frames").mkdir(parents=True, exist_ok=True)
    bpy.ops.render.render(animation=True)

    pattern = str((ROOT / "output" / "frames" / "frame_").resolve()) + "%04d.png"
    command = [
        "ffmpeg", "-y", "-framerate", "12", "-start_number", "1",
        "-i", pattern, "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", "-crf", "20", str(output_path.resolve())
    ]
    subprocess.run(command, check=True)
    print("3D prototype created:", output_path)


if __name__ == "__main__":
    args = cli_args()
    output = Path(args.output)
    if not output.is_absolute():
        output = ROOT / output
    build_scene(output)
