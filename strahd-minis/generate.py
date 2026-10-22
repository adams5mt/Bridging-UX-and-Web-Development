"""Generate Curse of Strahd PC miniatures with the Meshy API.

Pipeline per character: concept image (text-to-image) -> textured model
(image-to-3d) -> scaled onto the shared 25 mm base (local, no credits).

Task IDs are saved to state.json, so re-running resumes instead of paying twice.

    python3 generate.py concept mathias     # 6 credits each
    python3 generate.py model mathias       # 30 credits each
    python3 generate.py base mathias        # free
    python3 generate.py all                 # every step, every character
"""

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent
SPEC = json.loads((ROOT / "characters.json").read_text())
STATE_FILE = ROOT / "state.json"
OUT = ROOT / "out"
API = "https://api.meshy.ai/openapi"
KEY = os.environ["MESHY_API_KEY"]

IMAGE_MODEL = "nano-banana-2"
MODEL_3D = "meshy-7.1"


def load_state():
    return json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2) + "\n")


def call(method, path, body=None):
    req = urllib.request.Request(
        API + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def wait(path, task_id):
    while True:
        task = call("GET", f"{path}/{task_id}")
        if task["status"] in ("SUCCEEDED", "FAILED", "CANCELED"):
            if task["status"] != "SUCCEEDED":
                raise RuntimeError(f"{task_id} {task['status']}: {task.get('task_error')}")
            return task
        print(f"  {task_id} {task['status']} {task.get('progress', 0)}%", flush=True)
        time.sleep(10)


def download(url, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(url, dest)
    return dest


def character(cid):
    return next(c for c in SPEC["characters"] if c["id"] == cid)


def concept(cid, state):
    s = state.setdefault(cid, {})
    if "concept_task" not in s:
        prompt = f"{character(cid)['look']} {SPEC['style']}"
        s["concept_task"] = call("POST", "/v1/text-to-image", {
            "ai_model": IMAGE_MODEL,
            "prompt": prompt,
            "aspect_ratio": "3:4",
        })["result"]
        save_state(state)
    task = wait("/v1/text-to-image", s["concept_task"])
    download(task["image_urls"][0], OUT / cid / "concept.png")
    print(f"{cid}: concept done ({task['consumed_credits']} credits)")


def model(cid, state, submit_only=False):
    s = state[cid]
    if "model_task" not in s:
        s["model_task"] = call("POST", "/v1/image-to-3d", {
            "input_task_id": s["concept_task"],
            "ai_model": MODEL_3D,
            "should_texture": True,
            "enable_pbr": True,
            "texture_resolution": "2k",
            "should_remesh": True,
            "target_polycount": 100000,
            "target_formats": ["glb", "stl"],
            "multi_view_thumbnails": True,
        })["result"]
        save_state(state)
    if submit_only:
        return
    task = wait("/v1/image-to-3d", s["model_task"])
    download(task["model_urls"]["glb"], OUT / cid / "raw.glb")
    for view, url in (task.get("thumbnail_urls") or {"front": task["thumbnail_url"]}).items():
        download(url, OUT / cid / f"thumb-{view}.png")
    print(f"{cid}: model done ({task['consumed_credits']} credits)")


def base(cid, state):
    import numpy as np
    import trimesh

    spec = character(cid)
    b = SPEC["base"]
    scene = trimesh.load(OUT / cid / "raw.glb", force="scene")
    figure = scene.to_geometry()

    # Meshy exports Y-up; turn it Z-up so the base math reads naturally.
    figure.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0]))
    # Height is sole to crown, so scale twice: roughly, then exactly once the
    # soles are found (a lowered sword tip would otherwise shrink the figure).
    lo, hi = figure.bounds
    figure.apply_scale(spec["height_mm"] / (hi[2] - lo[2]))
    ground, _ = find_feet(figure.vertices)
    figure.apply_scale(spec["height_mm"] / (figure.bounds[1][2] - ground))
    ground, feet = find_feet(figure.vertices)
    # Centre on the feet, not the bounding box, so a sword or staff held out
    # to one side doesn't push the feet off-centre. Anything lower than the
    # soles (a sword tip, a staff butt) sinks into the base and is cut flush.
    cx, cy = feet[:, 0].mean(), feet[:, 1].mean()
    figure.apply_translation([-cx, -cy, b["height_mm"] - ground - 0.3])  # sink 0.3 mm into the base

    disc = base_mesh(b["diameter_mm"], b["height_mm"])
    disc.visual = trimesh.visual.ColorVisuals(disc, face_colors=[38, 34, 38, 255])

    # Back to Y-up for the glTF viewer copy; the STL stays Z-up for slicers.
    to_y_up = trimesh.transformations.rotation_matrix(-np.pi / 2, [1, 0, 0])
    out = trimesh.Scene()
    for name, geom in (("figure", figure), ("base", disc)):
        g = geom.copy()
        g.apply_transform(to_y_up)
        out.add_geometry(g, geom_name=name)
    out.export(OUT / cid / f"{cid}.glb", extension_webp=True)  # WebP textures keep the GLB small

    solid = trimesh.Trimesh(figure.vertices, figure.faces)
    if solid.bounds[0][2] < 0:
        solid = solid.slice_plane([0, 0, 0.01], [0, 0, 1])
    printable = trimesh.util.concatenate([solid, disc])
    printable.export(OUT / cid / f"{cid}.stl")
    render(printable, OUT / cid / "based.png")
    print(f"{cid}: based at {spec['height_mm']} mm on {b['diameter_mm']} mm base")


def render(mesh, dest, px=24):
    """Flat-shaded front and side views of a Z-up mesh, to check the base fit."""
    import numpy as np
    from PIL import Image, ImageDraw

    views = []
    for angle in (0, np.pi / 2):
        rot = np.array([[np.cos(angle), -np.sin(angle), 0], [np.sin(angle), np.cos(angle), 0], [0, 0, 1]])
        v = mesh.vertices @ rot.T
        tris = v[mesh.faces]
        normals = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
        normals /= np.linalg.norm(normals, axis=1, keepdims=True) + 1e-12
        shade = np.clip(np.abs(normals @ np.array([0.3, -0.8, 0.5])), 0.15, 1)
        lo, hi = v.min(0), v.max(0)
        w, h = int((hi[0] - lo[0]) * px) + 20, int((hi[2] - lo[2]) * px) + 20
        img = Image.new("RGB", (w, h), "white")
        draw = ImageDraw.Draw(img)
        for i in np.argsort(-tris[:, :, 1].mean(1)):  # far to near
            pts = [((x - lo[0]) * px + 10, h - ((z - lo[2]) * px + 10)) for x, _, z in tris[i]]
            g = int(40 + 200 * shade[i])
            draw.polygon(pts, fill=(g, g, g))
        views.append(img)
    out = Image.new("RGB", (sum(i.width for i in views), max(i.height for i in views)), "white")
    x = 0
    for i in views:
        out.paste(i, (x, out.height - i.height))
        x += i.width
    out.save(dest)


def find_feet(v, band=0.6, min_area=12.0):
    """Return (sole height, sole vertices): the lowest band of the figure whose
    footprint is foot-sized, skipping thin things that reach lower than the feet."""
    from scipy.spatial import ConvexHull

    z = v[:, 2].min()
    while z < v[:, 2].max():
        pts = v[(v[:, 2] >= z) & (v[:, 2] < z + band)]
        if len(pts) >= 3:
            try:
                if ConvexHull(pts[:, :2]).volume >= min_area:  # 2-D hull "volume" is area
                    return z, pts
            except Exception:
                pass
        z += band / 4
    raise ValueError("no foot-sized footprint found")


def base_mesh(diameter, height, bevel=0.8, segments=96):
    """A round base with a bevelled top edge, flat bottom at z=0."""
    import trimesh

    r = diameter / 2
    profile = [(0, 0), (r, 0), (r, height - bevel), (r - bevel, height), (0, height)]
    return trimesh.creation.revolve(profile, sections=segments)


STEPS = {"concept": concept, "model": model, "base": base}

if __name__ == "__main__":
    step, ids = sys.argv[1], sys.argv[2:] or [c["id"] for c in SPEC["characters"]]
    state = load_state()
    if step in ("model", "all"):
        # Queue every model first so Meshy builds them in parallel.
        for cid in ids:
            if step == "all":
                concept(cid, state)
            model(cid, state, submit_only=True)
    for cid in ids:
        for name in (["concept", "model", "base"] if step == "all" else [step]):
            STEPS[name](cid, state)
