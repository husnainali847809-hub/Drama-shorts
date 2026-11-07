"""Render a lightweight stylized 3D animal scene using Blender primitives."""
import argparse, sys
from pathlib import Path
import bpy
from mathutils import Vector

def cli():
    args=sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else []
    p=argparse.ArgumentParser()
    p.add_argument("--scene-index",type=int,required=True)
    p.add_argument("--seconds",type=int,default=10)
    p.add_argument("--output",required=True)
    return p.parse_args(args)

def mat(name,color,rough=0.8):
    m=bpy.data.materials.new(name); m.diffuse_color=(*color,1); m.roughness=rough
    return m

def sphere(name,loc,scale,m,parent=None):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=12,ring_count=8,radius=1,location=loc)
    o=bpy.context.object; o.name=name; o.scale=scale; o.data.materials.append(m)
    if parent:
        o.parent=parent; o.matrix_parent_inverse=parent.matrix_world.inverted()
    return o

def cylinder(name,loc,radius,depth,m):
    bpy.ops.mesh.primitive_cylinder_add(vertices=10,radius=radius,depth=depth,location=loc)
    o=bpy.context.object; o.name=name; o.data.materials.append(m); return o

def tiger(M):
    root=bpy.data.objects.new("Timo_root",None); bpy.context.collection.objects.link(root)
    sphere("Timo_body",(0,0,0.95),(.62,.40,.58),M["orange"],root)
    sphere("Timo_head",(0,-.04,1.72),(.55,.44,.50),M["orange"],root)
    sphere("Timo_muzzle",(0,-.42,1.57),(.32,.16,.19),M["cream"],root)
    sphere("Timo_nose",(0,-.56,1.68),(.08,.05,.06),M["dark"],root)
    for x in (-.36,.36):
        sphere("Timo_ear",(x,0,2.12),(.17,.14,.20),M["orange"],root)
        sphere("Timo_eye",(x*.62,-.42,1.82),(.065,.04,.08),M["eye"],root)
        sphere("Timo_cheek_stripe",(x*.78,-.43,1.48),(.05,.035,.16),M["dark"],root)
    for x in (-.34,.34):
        for y in (-.20,.20): sphere("Timo_leg",(x,y,.42),(.15,.16,.36),M["orange"],root)
    sphere("Timo_tail",(.70,.25,1.0),(.42,.11,.11),M["orange"],root)
    sphere("Timo_tail_tip",(1.02,.25,1.10),(.13,.12,.13),M["dark"],root)
    return root

def bunny(M):
    root=bpy.data.objects.new("Bunny_root",None); bpy.context.collection.objects.link(root)
    sphere("Bunny_body",(0,0,.75),(.40,.32,.45),M["white"],root)
    sphere("Bunny_head",(0,-.03,1.42),(.41,.36,.41),M["white"],root)
    sphere("Bunny_muzzle",(0,-.34,1.28),(.22,.12,.14),M["white"],root)
    sphere("Bunny_nose",(0,-.45,1.38),(.06,.04,.05),M["pink"],root)
    for x in (-.20,.20):
        ear=sphere("Bunny_ear",(x,.02,1.94),(.12,.11,.44),M["white"],root)
        ear.rotation_euler[1]=-x*.8
        sphere("Bunny_inner_ear",(x,-.075,1.94),(.06,.025,.32),M["pink"],root)
        sphere("Bunny_eye",(x*.72,-.34,1.53),(.05,.035,.065),M["eye"],root)
    for x in (-.23,.23): sphere("Bunny_foot",(x,-.05,.36),(.17,.20,.13),M["white"],root)
    sphere("Bunny_tail",(.36,.17,.78),(.14,.14,.14),M["white"],root)
    return root

def animate(obj,seconds,idx):
    obj.keyframe_insert(data_path="location",frame=1)
    obj.location.x += .45 if idx in (2,6,7) else 0
    if idx==5: obj.location.z=.12
    obj.keyframe_insert(data_path="location",frame=seconds*24)
    obj.rotation_euler[2]=.07 if idx in (1,3) else -.04
    obj.keyframe_insert(data_path="rotation_euler",frame=seconds*24)
    # Blender 5.x changed the Action F-Curve API. Keep Blender's default
    # smooth Bezier interpolation instead of accessing the removed action.fcurves.

def build(idx,seconds,out):
    bpy.ops.object.select_all(action="SELECT"); bpy.ops.object.delete(use_global=False)
    M={
      "orange":mat("Tiger orange",(.92,.32,.055)),
      "cream":mat("Cream",(.98,.80,.55)),
      "dark":mat("Stripe dark",(.09,.035,.02)),
      "eye":mat("Eyes",(.012,.009,.006),.25),
      "white":mat("Rabbit ivory",(.94,.91,.82)),
      "pink":mat("Ear pink",(.95,.34,.44)),
      "grass":mat("Jungle ground",(.08,.24,.10)),
      "wood":mat("Tree bark",(.20,.095,.04)),
      "leaf":mat("Leaves",(.07,.31,.11)),
      "water":mat("Stream",(.06,.34,.58),.25),
    }
    bpy.ops.mesh.primitive_plane_add(size=200,location=(0,0,-.08))
    bpy.context.object.data.materials.append(M["grass"])
    for x in (-6,-4,4,6):
        cylinder("Tree trunk",(x,2.5,2),.25,4,M["wood"])
        for z in (3.1,4.0,4.8): sphere("Canopy",(x,2.5,z),(1.1,.75,.9),M["leaf"])
    if idx in (4,5,6):
        bpy.ops.mesh.primitive_cube_add(size=1,location=(0,.9,.02))
        water=bpy.context.object; water.name="Jungle stream"; water.scale=(7,1,.04); water.data.materials.append(M["water"])
    for x in (-2.5,2.5):
        for z in (.45,.8,1.1):
            leaf=sphere("Fern",(x,.65,z),(.5,.11,.11),M["leaf"]); leaf.rotation_euler[1]=.35 if x<0 else -.35
    t=tiger(M); b=bunny(M)
    if idx==1: t.location.x=2.0; b.location.x=-1.1; t.hide_render=True
    elif idx==2: t.location.x=-1.2; b.location.x=1.5; b.hide_render=True
    else: t.location.x=-.85; b.location.x=.85
    animate(t,seconds,idx); animate(b,seconds,idx)
    bpy.ops.object.camera_add(location=(0,-11.5,4.4))
    cam=bpy.context.object; target=Vector((0,0,1.25))
    cam.rotation_euler=(target-cam.location).to_track_quat("-Z","Y").to_euler()
    cam.data.type="ORTHO"; cam.data.ortho_scale=7.4; bpy.context.scene.camera=cam
    bpy.ops.object.light_add(type="AREA",location=(0,-5,8))
    light=bpy.context.object; light.data.energy=1200; light.data.shape="DISK"; light.data.size=8
    s=bpy.context.scene
    # Select an engine actually exposed by this Blender build. Ubuntu's
    # Blender 5.0.1 package exposes BLENDER_EEVEE rather than EEVEE_NEXT.
    engine_ids={item.identifier for item in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items}
    if "BLENDER_EEVEE_NEXT" in engine_ids:
        s.render.engine="BLENDER_EEVEE_NEXT"
    elif "BLENDER_EEVEE" in engine_ids:
        s.render.engine="BLENDER_EEVEE"
    else:
        s.render.engine="CYCLES"
    s.render.resolution_x=720; s.render.resolution_y=1280; s.render.resolution_percentage=100
    s.render.fps=24; s.frame_start=1; s.frame_end=seconds*24
    # Render numbered PNG frames. Encoding is handled by system FFmpeg in
    # pipeline.py, avoiding Blender-build-specific FFmpeg output problems.
    frames_dir=Path(out).resolve().parent/(Path(out).stem+"_frames")
    frames_dir.mkdir(parents=True,exist_ok=True)
    s.render.image_settings.file_format="PNG"
    s.render.image_settings.color_mode="RGB"
    s.render.image_settings.compression=15
    s.render.filepath=str(frames_dir/"frame_")
    s.world.color=(.035,.09,.045); s.view_settings.view_transform="Standard"
    print(f"Rendering scene {idx} to PNG sequence: {s.render.filepath}",flush=True)
    bpy.ops.render.render(animation=True)
    rendered=list(frames_dir.glob("*.png"))
    print(f"Scene {idx} rendered {len(rendered)} PNG frames in {frames_dir}",flush=True)
    if len(rendered) < seconds*24:
        raise RuntimeError(f"Expected {seconds*24} frames, found {len(rendered)}")

if __name__=="__main__":
    a=cli(); build(a.scene_index,a.seconds,a.output)
