"""Export an MPFB character from a .blend file to a TalkingHead-ready GLB, headlessly.

Runs the same steps as the manual guide (blender/MPFB/MPFB.md in TalkingHead):
export copy with Meta visemes + ARKit face units, rename the rig to "Armature",
TalkingHead "Scale character" + "Fix bone axes (A-pose)", apply transforms, opaque/cutout
materials, export GLB.
The source .blend is never saved.

Usage:
    blender -b tools/blender/yossi.blend --python blender/export_avatar.py -- frontend/prototype/avatars/yossi.glb

The .blend sources live in tools/blender/ (not in git: they reference the local MPFB asset library).
"""

import sys

import bpy

out_path = sys.argv[sys.argv.index("--") + 1]
scene = bpy.context.scene
view_layer = bpy.context.view_layer


def select_only(objects, active):
    bpy.ops.object.select_all(action="DESELECT")
    for o in objects:
        o.select_set(True)
    view_layer.objects.active = active


# 1. The original character: the armature that is not already an export copy.
rig = next(o for o in scene.objects if o.type == "ARMATURE" and "export" not in o.name.lower())
print(f"Source rig: {rig.name}")
select_only([rig], rig)

# 2. MPFB "Create export copy" with the same options as the guide. MPFB keeps these options in
# its own config set on the scene (they back the checkboxes in its export panel).
from bl_ext.blender_org.mpfb.ui.operations.exportops.exportopspanel import EXPORTOPS_PROPERTIES

for name, value in {
    "mask_modifiers": "BAKE", "subdiv_modifiers": "BAKE", "bake_shapekeys": True,
    "delete_helpers": True, "remove_basemesh": False, "visemes_meta": True,
    "visemes_microsoft": False, "faceunits_arkit": True, "interpolate": True, "collection": True,
}.items():
    EXPORTOPS_PROPERTIES.set_value(name, value, entity_reference=scene)
bpy.ops.mpfb.export_copy()

copy_rig = next(o for o in bpy.data.collections["export copy"].objects if o.type == "ARMATURE")
copy_rig.name = "Armature"  # TalkingHead looks for this root name (option modelRoot)
parts = [o for o in copy_rig.children_recursive]
print(f"Export copy: {copy_rig.name} with {len(parts)} parts")

# 3. TalkingHead fixes (they require exactly one selected armature).
select_only([copy_rig], copy_rig)
bpy.ops.talkinghead.scale_character()
bpy.ops.talkinghead.fix_bone_axes_a()

# 4. Apply all transforms on the whole copy.
select_only([copy_rig, *parts], copy_rig)
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

# Report what the lip-sync will be able to use.
for o in parts:
    if o.type == "MESH" and o.data.shape_keys:
        keys = [k.name for k in o.data.shape_keys.key_blocks]
        visemes = sum(k.startswith("viseme_") for k in keys)
        arkit = sum(k in ("eyeBlinkLeft", "jawOpen", "mouthSmileLeft", "browInnerUp") for k in keys)
        if visemes or arkit:
            print(f"  {o.name}: {visemes} visemes, ARKit sample {arkit}/4, {len(keys)} shape keys")

# 5. Materials for glTF. MPFB materials all come out as alpha BLEND, which breaks draw order in
# the browser (teeth show through lips, hair vanishes). Per the guide: strands (hair, brows, lashes)
# and eyes (clear cornea over the iris) get a cutout mask via a "Greater Than" math node; everything
# else becomes opaque.
MASKED = ("hair", "short", "long", "bob", "ponytail", "braid", "eyebrow", "eyelash",
          "high-poly", "low-poly")  # eyes: a transparent cornea sits over the iris


def fix_material(mat, masked):
    tree = mat.node_tree
    bsdf = next((n for n in tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf is None:
        return "no BSDF"
    alpha_in = bsdf.inputs["Alpha"]
    source = alpha_in.links[0].from_socket if alpha_in.is_linked else None
    # MPFB reads alpha through a second image node of the same picture; the glTF exporter only
    # keeps alpha that comes from the base color image node itself, so read it from there.
    color_in = bsdf.inputs["Base Color"]
    color_node = color_in.links[0].from_node if color_in.is_linked else None
    if (source is not None and color_node is not None and color_node.type == "TEX_IMAGE"
            and source.node.type == "TEX_IMAGE" and source.node.image == color_node.image):
        source = color_node.outputs["Alpha"]
    for link in list(alpha_in.links):
        tree.links.remove(link)
    if masked and source is not None:
        cut = tree.nodes.new("ShaderNodeMath")
        cut.operation = "GREATER_THAN"
        cut.inputs[1].default_value = 0.5
        tree.links.new(source, cut.inputs[0])
        tree.links.new(cut.outputs[0], alpha_in)
        return "MASK"
    alpha_in.default_value = 1.0
    return "OPAQUE"


for o in parts:
    if o.type != "MESH":
        continue
    masked = any(tag in o.name.lower() for tag in MASKED)
    for slot in o.material_slots:
        if slot.material and slot.material.use_nodes:
            slot.material = slot.material.copy()  # don't touch the original character's materials
            print(f"  material {slot.material.name}: {fix_material(slot.material, masked)}")

# 6. Export the copy only, without animations.
bpy.ops.export_scene.gltf(filepath=out_path, export_format="GLB", use_selection=True, export_animations=False)
print(f"Exported: {out_path}")
