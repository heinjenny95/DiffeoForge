"""Immutable, input-bound PCA media and an offline presentation-only sharing ZIP.

Only a verified reference PCA and physical-t=1 Shooting result are accepted.
Source geometry, scores and approvals are never rewritten. Render proxies are
bound to corresponding original vertices; heatmap ranges use full surfaces.
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
import shutil
import threading
import uuid
import zipfile
from pathlib import Path

import numpy as np

from diffeoforge.mesh import sha256_file
from diffeoforge.reference_pca import (
    DEFAULT_REFERENCE_PCA_DIRECTORY,
    REFERENCE_PCA_MANIFEST,
    load_reference_momenta,
    verify_reference_pca_bundle,
)
from diffeoforge.reference_pca_deformations import (
    DEFAULT_RESULT_DIRECTORY,
    RESULT_NAME,
    verify_reference_pca_deformation_result,
)
from diffeoforge.runs import publish_directory_exclusive

MEDIA_VERSION = "2"


class MediaCancelled(RuntimeError):
    pass


def _record(path):
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def _check(record):
    path = Path(record["path"])
    if (
        path.is_symlink()
        or path.stat().st_size != record["bytes"]
        or sha256_file(path) != record["sha256"]
    ):
        raise ValueError("PCA media source or output differs from verified bytes")


def verify_media(directory: Path, *, source_run: Path | None = None) -> dict:
    manifest = directory / "media.json"
    if (directory / "media.sha256").read_text().strip() != sha256_file(manifest):
        raise ValueError("PCA media manifest differs")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if data.get("version") != MEDIA_VERSION or data.get("status") != "complete":
        raise ValueError("Unsupported or incomplete PCA media")
    if source_run is not None and Path(data["source_run"]).resolve() != source_run.resolve():
        raise ValueError("PCA media belongs to another result")
    run_root = Path(data["source_run"]).resolve()
    for record in data["sources"]:
        try:
            Path(record["path"]).resolve().relative_to(run_root)
        except ValueError as error:
            raise ValueError("PCA media source escapes its result") from error
        _check(record)
    expected = set()
    for record in data["files"]:
        relative = Path(record["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Unsafe PCA media path")
        try:
            (directory / relative).resolve().relative_to(directory.resolve())
        except ValueError as error:
            raise ValueError("PCA media output escapes its cache") from error
        _check({**record, "path": str(directory / relative)})
        expected.add(relative.as_posix())
    actual = {
        p.relative_to(directory).as_posix()
        for p in directory.rglob("*")
        if p.is_file() and p.name not in {"media.json", "media.sha256"}
    }
    if actual != expected:
        raise ValueError("PCA media inventory differs")
    return data


def prepare_reference_media(
    run: Path,
    project: Path,
    *,
    progress=lambda _text: None,
    cancelled: threading.Event | None = None,
) -> Path:
    """Prepare once or freshly verify/reuse the matching immutable media cache."""
    run, project = run.resolve(), project.resolve()
    cancelled = cancelled or threading.Event()

    def phase(text):
        if cancelled.is_set():
            raise MediaCancelled("Visualization preparation cancelled")
        progress(text)

    phase("Checking saved PCA and axis shapes")
    bundle_path = run / DEFAULT_REFERENCE_PCA_DIRECTORY
    endpoint_root = run / DEFAULT_RESULT_DIRECTORY
    identity = hashlib.sha256(
        (
            sha256_file(bundle_path / REFERENCE_PCA_MANIFEST)
            + sha256_file(endpoint_root / RESULT_NAME)
        ).encode()
    ).hexdigest()
    target = project / "visualizations" / f"pca-{identity[:20]}-v{MEDIA_VERSION}"
    if target.exists():
        verify_media(target, source_run=run)
        return target
    bundle = verify_reference_pca_bundle(bundle_path, source_run=run)
    endpoint_result = verify_reference_pca_deformation_result(endpoint_root, source_run=run)
    if endpoint_result["result_version"] != "0.2":
        raise ValueError("Axis media require verified native physical endpoints (v0.2)")
    inputs = load_reference_momenta(run)
    pca = bundle.pca
    sources = [
        _record(bundle_path / REFERENCE_PCA_MANIFEST),
        _record(endpoint_root / RESULT_NAME),
        _record(run / "manifest.json"),
        _record(run / "result.json"),
        _record(run / "output-inventory.json"),
    ]
    reconstruction_records = []
    for label in pca.sample_labels:
        matches = [
            r
            for r in inputs.run_report.inventory
            if Path(r["path"]).name.endswith(f"__subject_{label}.vtk")
            and "__Reconstruction__" in Path(r["path"]).name
        ]
        if len(matches) != 1:
            raise ValueError("PCA subject does not bind exactly one reconstruction")
        record = matches[0]
        path = run / "output" / record["path"]
        source = {**record, "path": str(path)}
        _check(source)
        sources.append(source)
        reconstruction_records.append(source)
    endpoints = []
    for endpoint in endpoint_result["endpoints"]:
        source = {**endpoint, "path": str(endpoint_root / endpoint["path"])}
        _check(source)
        sources.append(source)
        endpoints.append(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp-{uuid.uuid4().hex}")
    temporary.mkdir()
    try:
        _render_media(
            temporary,
            pca,
            reconstruction_records,
            endpoints,
            phase,
            cancelled,
            endpoint_root=endpoint_root,
            config=inputs.run_report.manifest["effective_config"],
        )
        phase("Verifying source preservation and sharing ZIP")
        for source in sources:
            _check(source)
        records = [
            {**_record(path), "path": path.relative_to(temporary).as_posix()}
            for path in sorted(temporary.rglob("*"))
            if path.is_file()
        ]
        data = {
            "version": MEDIA_VERSION,
            "status": "complete",
            "source_run": str(run),
            "sources": sources,
            "files": records,
            "subject_count": len(pca.sample_labels),
            "specimen_labels": list(pca.sample_labels),
            "pca_method": pca.method,
            "scores_unchanged": True,
            "native_anchors": "physical t=1; mean and +/-2 SD",
            "movie": "17 native PC-path samples per axis; smooth display interpolation "
            "between adjacent corresponding samples, not optimizer iterations.",
            "coordinate_unit": "model coordinate units",
            "anatomical_approval": False,
        }
        manifest = temporary / "media.json"
        manifest.write_text(json.dumps(data, indent=2, allow_nan=False), encoding="utf-8")
        (temporary / "media.sha256").write_text(sha256_file(manifest), encoding="ascii")
        verify_media(temporary, source_run=run)
        publish_directory_exclusive(temporary, target)
        return target
    except BaseException:
        if temporary.exists() and temporary.parent == target.parent:
            shutil.rmtree(temporary)
        raise


def _render_media(
    root,
    pca,
    reconstructions,
    endpoints,
    phase,
    cancelled,
    *,
    endpoint_root,
    config,
    sample_source=None,
    rotation=None,
    view_name=None,
):
    # Imports stay in the background worker; ordinary workflow startup remains light.
    import imageio.v2 as imageio
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.font_manager import findfont
    from matplotlib.offsetbox import AnnotationBbox, OffsetImage
    from PIL import Image, ImageDraw, ImageFont

    from diffeoforge.analysis.pca_media_rendering import (
        VIEWS,
        SurfaceRenderer,
        display_proxy,
        faces,
        merge_bounds,
        point_normals,
        points,
        read_mesh,
        with_points,
    )

    gallery = root / "PCA-Gallery"
    figures, videos, thumbs = (gallery / name for name in ("figures", "videos", "thumbnails"))
    for folder in (figures, videos, thumbs):
        folder.mkdir(parents=True)
    phase("Preparing corresponding display surfaces")
    mean_record = next(r for r in endpoints if r["role"] == "mean")
    mean_mesh = read_mesh(mean_record["path"])
    mean, topology = points(mean_mesh), faces(mean_mesh).copy()
    proxy, ids = display_proxy(mean_mesh)
    normal = point_normals(mean_mesh)
    axis_values = {}
    limits = 0.0
    bounds = [mean_mesh.GetBounds()]
    for record in endpoints:
        mesh = read_mesh(record["path"])
        if not np.array_equal(faces(mesh), topology):
            raise ValueError("Native axis topology differs from mean")
        value = points(mesh)
        if value.shape != mean.shape:
            raise ValueError("Native axis vertex count differs")
        difference = value - mean
        limits = max(limits, float(np.linalg.norm(difference, axis=1).max()))
        if record["role"] != "mean":
            axis_values[(int(record["component"]), record["direction"])] = (
                value[ids],
                np.linalg.norm(difference, axis=1)[ids],
                np.einsum("ij,ij->i", difference, normal)[ids],
            )
        bounds.append(mesh.GetBounds())
    limits = max(limits, 1e-12)
    bounds = merge_bounds(bounds)
    components = sorted({key[0] for key in axis_values})
    from diffeoforge.reference_pca_samples import native_axis_samples

    anchors = {
        (pc, direction): axis_values[(pc, direction)][0]
        for pc in components
        for direction in ("minus", "plus")
    }
    anchors.update({(pc, "mean"): mean[ids] for pc in components})
    if sample_source is None:
        origin = read_mesh(endpoint_root / "source/estimated-template.vtk")
        if not np.array_equal(faces(origin), topology):
            raise ValueError("PC sample source topology differs from full native anchors")
        samples = native_axis_samples(
            root / "native-display-samples",
            endpoint_root=endpoint_root,
            pca=pca,
            config=config,
            template_proxy=with_points(proxy, points(origin)[ids]),
            components=components,
            anchors=anchors,
            scale=np.linalg.norm(bounds[1::2] - bounds[::2]),
            progress=phase,
        )
    else:
        # Camera changes reuse the inventoried native samples. Never shoot again.
        receipt = json.loads((sample_source / "native-display-samples/samples.json").read_text())
        if (
            receipt["return_code"] != 0
            or receipt["components"] != components
            or not np.array_equal(
                np.load(sample_source / "proxy-source-vertex-ids.npy", allow_pickle=False), ids
            )
        ):
            raise ValueError("Saved display samples do not match the rendering basis")
        values = []
        for index in range(len(components) * 17):
            phase("Reading saved PC-path display samples")
            mesh = read_mesh(
                sample_source / f"native-display-samples/output/Shooting_{index}__endpoint.vtk"
            )
            if not np.array_equal(faces(mesh), faces(proxy)):
                raise ValueError("Saved PC-path sample topology differs")
            values.append(points(mesh))
        samples = np.asarray(values).reshape(len(components), 17, len(ids), 3)
        for j, pc in enumerate(components):
            for k, label in ((0, "minus"), (8, "mean"), (16, "plus")):
                if (
                    np.linalg.norm(samples[j, k] - anchors[pc, label], axis=1).max()
                    > receipt["anchor_tolerance"]
                ):
                    raise ValueError("Saved PC-path anchor differs")
    limits = max(limits, float(np.linalg.norm(samples - mean[ids], axis=-1).max()))
    flattened = samples.reshape(-1, 3)
    sample_bounds = np.column_stack((flattened.min(axis=0), flattened.max(axis=0))).ravel()
    bounds = merge_bounds((bounds, sample_bounds))
    np.save(root / "proxy-source-vertex-ids.npy", ids)
    views = VIEWS
    if rotation is not None:
        from diffeoforge.desktop.mesh_view import checked_rotation

        rotation = checked_rotation(rotation)
        labels = ("Chosen view", "Opposite", "Below", "Above", "Right", "Left")
        views = tuple(
            (label, np.asarray(direction) @ rotation, np.asarray(up) @ rotation)
            for label, (_, direction, up) in zip(labels, VIEWS, strict=True)
        )
    primary = views[0]
    (root / "rendering.json").write_text(
        json.dumps(
            {
                "camera_bounds": bounds.tolist(),
                "displacement_range": [0, limits],
                "normal_component_range": [-limits, limits],
                "units": "model coordinate units",
                "views": [[label, list(direction), list(up)] for label, direction, up in views],
                "mesh_view": view_name,
                "projection": "orthographic",
                "components": components,
                "source_vertices": len(mean),
                "display_vertices": len(ids),
                "display_triangles": int(len(faces(proxy))),
                "display_only": True,
                "heatmap_measurement": "corresponding full-resolution endpoint vertices",
                "normal_orientation": "consistently oriented mean-surface normals",
                "sd_sample_spacing": 0.25,
                "samples_per_axis": 17,
                "movie_frames": 128,
                "movie_fps": 12,
                "movie_dimensions": [1260, 840],
                "mean_shape": "native shooting of mean momenta; no intrinsic-mean claim",
            },
            indent=2,
            allow_nan=False,
        ),
        encoding="utf-8",
    )
    renderer = SurfaceRenderer()
    font = ImageFont.truetype(findfont("DejaVu Sans"), 20)

    def six_plate(values, title, scalars=None, signed=False):
        mesh = with_points(proxy, values)
        image = Image.new("RGB", (1260, 840), "white")
        draw = ImageDraw.Draw(image)
        draw.text((20, 10), title, fill="#243c47", font=font)
        for i, view in enumerate(views):
            phase("Rendering view panels")
            x, y = i // 2 * 420, 90 + i % 2 * 360
            frame = renderer.render(
                mesh, bounds, view, scalars, (-limits, limits) if signed else (0, limits), signed
            )
            image.paste(frame, (x, y), frame)
            draw.text((x + 12, y - 26), view[0], fill="#3f5963", font=font)
        draw.text((20, 812), "−2 SD → Mean → +2 SD", fill="#3f5963", font=font)
        draw.text(
            (340, 816),
            "Signed · model units" if signed else "Displacement · model units",
            fill="#3f5963",
            font=font,
        )
        cmap = matplotlib.colormaps["coolwarm" if signed else "viridis"]
        bar = np.uint8(np.asarray(cmap(np.linspace(0, 1, 360)))[:, :3] * 255)
        image.paste(Image.fromarray(np.repeat(bar[None, :, :], 12, axis=0)), (730, 800))
        draw.text(
            (650, 816),
            f"{'−' if signed else ''}{limits:.3g}" if signed else "0",
            fill="#3f5963",
            font=font,
        )
        draw.text((1100, 816), f"{limits:.3g}", fill="#3f5963", font=font)
        return image

    image_files = []
    try:
        phase("Rendering mean and ±2 SD views")
        for pc in components:
            row = Image.new("RGB", (1260, 440), "white")
            draw = ImageDraw.Draw(row)
            draw.text((20, 10), f"PC{pc} · −2 SD / Mean / +2 SD", font=font, fill="#243c47")
            for i, value in enumerate(
                (axis_values[(pc, "minus")][0], mean[ids], axis_values[(pc, "plus")][0])
            ):
                frame = renderer.render(with_points(proxy, value), bounds, primary)
                row.paste(frame, (i * 420, 65), frame)
            name = f"PC{pc}-SD.png"
            row.save(figures / name)
            row.save(figures / name.replace(".png", ".pdf"), resolution=180)
            image_files.append((f"PC{pc} · −2 SD / Mean / +2 SD", name))
            for direction in ("minus", "plus"):
                value, magnitude, signed = axis_values[(pc, direction)]
                for kind, scalar, diverging in (
                    ("displacement", magnitude, False),
                    ("normal-displacement", signed, True),
                ):
                    label = f"PC{pc} · {'−2' if direction == 'minus' else '+2'} SD · {kind}"
                    image = six_plate(value, label, scalar, diverging)
                    name = f"PC{pc}-{direction}-{kind}.png"
                    image.save(figures / name)
                    image.save(figures / name.replace(".png", ".pdf"), resolution=180)
                    image_files.append((label, name))
        phase("Rendering specimen meshes at saved PCA scores")
        thumb_images, specimen_bounds, meshes = [], [], []
        for i, record in enumerate(reconstructions):
            phase(f"Preparing specimen {i + 1}/{len(reconstructions)}")
            mesh = read_mesh(record["path"])
            if not np.array_equal(faces(mesh), topology):
                raise ValueError("Reconstruction topology differs from the reference basis")
            meshes.append(points(mesh)[ids])
            specimen_bounds.append(mesh.GetBounds())
            _check(record)
        specimen_bounds = merge_bounds(specimen_bounds)
        # Private display-only geometry. It is inventoried outside the sharing
        # gallery, whose allowlist deliberately excludes geometry and checkpoints.
        from diffeoforge.desktop.morphospace_geometry import glyph_topology

        budget = max(8, min(128, 24000 // max(1, len(meshes))))
        vertex_ids, display_faces = glyph_topology(proxy, budget)
        np.savez_compressed(
            root / "morphospace-3d.npz",
            vertices=np.asarray(meshes)[:, vertex_ids],
            faces=display_faces,
            scores=pca.scores,
            ratios=pca.explained_variance_ratio,
        )
        for i, value in enumerate(meshes):
            phase(f"Rendering specimen {i + 1}/{len(meshes)}")
            frame = renderer.render(with_points(proxy, value), specimen_bounds, primary)
            frame.save(thumbs / f"{i + 1}.png")
            thumb_images.append(np.asarray(frame))
        pairs = [(0, 1)] if pca.number_of_components >= 2 else []
        if pca.number_of_components >= 3:
            pairs.extend(((0, 2), (1, 2)))
        for x, y in pairs:
            fig, ax = plt.subplots(figsize=(14, 10), dpi=150)
            try:
                scores = pca.scores
                for axis, values in ((ax.set_xlim, scores[:, x]), (ax.set_ylim, scores[:, y])):
                    pad = max(float(np.ptp(values)), 1e-6) * 0.15
                    axis(float(values.min()) - pad, float(values.max()) + pad)
                for i, frame in enumerate(thumb_images):
                    ax.add_artist(
                        AnnotationBbox(
                            OffsetImage(frame, zoom=0.14), scores[i, [x, y]], frameon=False
                        )
                    )
                ax.set_xlabel(f"PC{x + 1} ({pca.explained_variance_ratio[x]:.2%})")
                ax.set_ylabel(f"PC{y + 1} ({pca.explained_variance_ratio[y]:.2%})")
                ax.set_title(f"Mesh PCA · PC{x + 1} / PC{y + 1}")
                ax.grid(alpha=0.15)
                name = f"PCA-PC{x + 1}-PC{y + 1}"
                fig.savefig(figures / f"{name}.png", bbox_inches="tight")
                fig.savefig(figures / f"{name}.pdf", bbox_inches="tight")
                image_files.insert(0, (f"Mesh PCA · PC{x + 1} / PC{y + 1}", f"{name}.png"))
            finally:
                plt.close(fig)
        video_files = []
        for axis_index, pc in enumerate(components):
            phase(f"Rendering PC{pc} · six synchronized views")
            path = videos / f"PC{pc}-six-views.mp4"
            writer = imageio.get_writer(
                path,
                fps=12,
                codec="libx264",
                pixelformat="yuv420p",
                macro_block_size=1,
                ffmpeg_params=["-crf", "21", "-threads", "2", "-movflags", "+faststart"],
            )
            try:
                for sd in np.r_[
                    np.repeat(-2.0, 8),
                    np.linspace(-2, 0, 50),
                    np.repeat(0.0, 12),
                    np.linspace(0, 2, 50),
                    np.repeat(2.0, 8),
                ]:
                    if cancelled.is_set():
                        raise MediaCancelled("Video rendering cancelled")
                    coordinate = (float(sd) + 2) * 4
                    left = min(15, max(0, int(np.floor(coordinate))))
                    weight = coordinate - left
                    value = (1 - weight) * samples[axis_index, left] + weight * samples[
                        axis_index, left + 1
                    ]
                    magnitude = np.linalg.norm(value - mean[ids], axis=1)
                    position = "Mean · 0 SD" if abs(sd) < 1e-10 else f"{sd:+.2f} SD"
                    frame = six_plate(value, f"PC{pc} · {position}", magnitude)
                    writer.append_data(np.asarray(frame))
            finally:
                writer.close()
            reader = imageio.get_reader(path)
            try:
                if reader.count_frames() != 128 or reader.get_data(64).shape[:2] != (840, 1260):
                    raise ValueError("Encoded PC video differs from declared frames")
            finally:
                reader.close()
            video_files.append((f"PC{pc} · −2 SD → Mean → +2 SD", path.name))
        _write_gallery(gallery, image_files, video_files, pca)
        if rotation is not None:
            (gallery / "mesh-view.json").write_text(
                json.dumps(
                    {
                        "name": view_name,
                        "camera_rotation": rotation.tolist(),
                        "scores_unchanged": True,
                        "scope": "all visualizations",
                        "six_views": "Chosen view and five opposing/orthogonal views "
                        "in the chosen basis",
                    }
                ),
                encoding="utf-8",
            )
        _archive_gallery(gallery, root / "PCA-Gallery.zip")
    finally:
        renderer.close()


def _write_gallery(gallery, images, videos, pca):
    sections = [
        '<section><h2>Mesh PCA</h2><iframe title="Mesh PCA" src="mesh-pca.html" '
        'style="border:0;width:100%;height:780px"></iframe></section>'
    ]
    for title, name in images:
        sections.append(
            f"<section><h2>{html.escape(title)}</h2>"
            f'<a href="figures/{name.replace(".png", ".pdf")}">'
            f'<img loading="lazy" src="figures/{name}" alt="{html.escape(title)}"></a></section>'
        )
    for title, name in videos:
        sections.append(
            f'<section><h2>{html.escape(title)}</h2><video controls preload="metadata" '
            f'loop src="videos/{name}"></video></section>'
        )
    text = (
        '<!doctype html><meta charset="utf-8"><title>PCA Visualization</title><style>'
        "body{font:16px system-ui;background:#f5f8f9;color:#243c47;margin:24px}"
        "section{max-width:1400px;background:white;margin:20px auto;"
        "padding:20px;border-radius:12px}"
        "img,video{width:100%;height:auto}h2{font-size:22px}</style><h1>PCA Visualization</h1>"
    )
    comparison = (
        "<style>main.compare{display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));"
        "gap:12px}main.compare section{min-width:0;margin:0}"
        "main.compare iframe{height:500px}</style>"
        '<label><input type="checkbox" onchange="document.querySelector(\'main\').classList.toggle('
        "'compare',this.checked)\"> All side by side</label> "
        '<button id="play-all">Play / Pause all videos</button><main>'
    )
    video_script = r"""</main><script>
const movies=[...document.querySelectorAll('video')];
document.querySelector('#play-all').onclick=()=>{if(!movies.length)return;
let first=movies[0],start=first.paused;
movies.forEach(v=>{v.currentTime=first.currentTime;
if(start)v.play().catch(()=>{});else v.pause()})};
if(movies.length)movies[0].addEventListener('timeupdate',()=>{
if(movies[0].paused)return;movies.slice(1).forEach(v=>{
if(Math.abs(v.currentTime-movies[0].currentTime)>.12)v.currentTime=movies[0].currentTime})});
</script>"""
    (gallery / "index.html").write_text(
        text + comparison + "".join(sections) + video_script, encoding="utf-8"
    )
    items = [
        {
            "id": i + 1,
            "label": str(pca.sample_labels[i])
            if hasattr(pca, "sample_labels")
            else f"Mesh {i + 1}",
            "scores": row.tolist(),
            "image": "data:image/png;base64,"
            + base64.b64encode((gallery / "thumbnails" / f"{i + 1}.png").read_bytes()).decode(),
        }
        for i, row in enumerate(pca.scores[:, :3])
    ]
    (gallery / "mesh-pca.json").write_text(json.dumps(items, allow_nan=False), encoding="utf-8")
    # The offline document embeds images/data; no network, paths or identity key.
    script = r"""<!doctype html><meta charset="utf-8"><title>Mesh PCA</title>
<style>body{font:15px system-ui;color:#243c47;margin:8px}canvas{width:100%;height:680px;
touch-action:none;cursor:grab}button,select,input{margin:0 12px 8px 0}</style>
<select id="axes"><option value="0,1">PC1 / PC2</option>
<option value="0,2">PC1 / PC3</option>
<option value="1,2">PC2 / PC3</option></select>
<label>Mesh size <input id="size" type="range" min="25" max="140" value="72"></label>
<button id="reset">Reset</button><canvas id="plot" width="1200" height="680"></canvas>
<script>
const items=DATA,ratios=RATIOS,canvas=document.getElementById('plot'),ctx=canvas.getContext('2d');
let range,initial,drag;
items.forEach(item=>{item.img=new Image();item.img.onload=draw;item.img.src=item.image});
function axes(){return document.getElementById('axes').value.split(',').map(Number)}
function reset(){let [x,y]=axes();let xs=items.map(i=>i.scores[x]),ys=items.map(i=>i.scores[y]);
if(xs.some(v=>v===undefined)||ys.some(v=>v===undefined)){range=null;draw();return}
let dx=Math.max(Math.max(...xs)-Math.min(...xs),1e-6);
let dy=Math.max(Math.max(...ys)-Math.min(...ys),1e-6);
initial=[Math.min(...xs)-dx*.15,Math.max(...xs)+dx*.15,
Math.min(...ys)-dy*.15,Math.max(...ys)+dy*.15];
range=[...initial];draw()}
function draw(){ctx.clearRect(0,0,1200,680);if(!range)return;const [x,y]=axes(),[a,b,c,d]=range;
const X=v=>80+(v-a)/(b-a)*1080,Y=v=>610-(v-c)/(d-c)*560,n=+document.getElementById('size').value;
ctx.font='15px system-ui';ctx.fillStyle='#243c47';ctx.strokeStyle='#e1e9ec';
for(let j=0;j<=5;j++){let v=a+(b-a)*j/5,w=c+(d-c)*j/5;ctx.beginPath();ctx.moveTo(X(v),40);
ctx.lineTo(X(v),610);ctx.moveTo(80,Y(w));ctx.lineTo(1160,Y(w));ctx.stroke();
ctx.fillText(v.toPrecision(3),X(v)-20,635);ctx.fillText(w.toPrecision(3),8,Y(w)+5)}
ctx.fillText('PC'+(x+1)+' ('+(ratios[x]*100).toFixed(2)+'%)',500,670);
ctx.fillText('PC'+(y+1)+' ('+(ratios[y]*100).toFixed(2)+'%)',8,22);
ctx.save();ctx.beginPath();ctx.rect(80,40,1080,570);ctx.clip();
for(let item of items){let px=X(item.scores[x]),py=Y(item.scores[y]);
if(item.img.complete)ctx.drawImage(item.img,px-n/2,py-n/2,n,n*6/7);
ctx.fillText(item.id,px,py-n*.4)}ctx.restore()}
canvas.onwheel=e=>{if(!range)return;e.preventDefault();let b=canvas.getBoundingClientRect();
let px=(e.clientX-b.left)*1200/b.width,py=(e.clientY-b.top)*680/b.height;
let [a,z,c,d]=range,u=a+(px-80)/1080*(z-a),v=d-(py-50)/560*(d-c),k=e.deltaY>0?1.15:1/1.15;
range=[u+(a-u)*k,u+(z-u)*k,v+(c-v)*k,v+(d-v)*k];draw()};
canvas.onpointerdown=e=>{if(!range)return;drag=[e.clientX,e.clientY,...range];
canvas.setPointerCapture(e.pointerId)};
canvas.onpointermove=e=>{let b=canvas.getBoundingClientRect();
if(!drag){canvas.title='';if(!range)return;let [x,y]=axes(),[a,z,c,d]=range;
let px=(e.clientX-b.left)*1200/b.width,py=(e.clientY-b.top)*680/b.height;
let n=+document.getElementById('size').value;
for(let item of [...items].reverse()){let gx=80+(item.scores[x]-a)/(z-a)*1080;
let gy=610-(item.scores[y]-c)/(d-c)*560;
if(Math.abs(px-gx)<=n/2&&Math.abs(py-gy)<=n*3/7){canvas.title=item.label;break}}return}
let dx=(e.clientX-drag[0])/b.width*1200/1080*(drag[3]-drag[2]);
let dy=(e.clientY-drag[1])/b.height*680/560*(drag[5]-drag[4]);
range=[drag[2]-dx,drag[3]-dx,drag[4]+dy,drag[5]+dy];draw()};
canvas.onpointerup=()=>drag=null;canvas.onpointercancel=()=>drag=null;
document.getElementById('axes').onchange=reset;document.getElementById('size').oninput=draw;
document.getElementById('reset').onclick=reset;reset();
</script>"""
    encoded_items = (
        json.dumps(items, allow_nan=False).replace("<", "\\u003c").replace(">", "\\u003e")
    )
    script = script.replace("DATA", encoded_items).replace(
        "RATIOS", json.dumps(pca.explained_variance_ratio[:3].tolist())
    )
    (gallery / "mesh-pca.html").write_text(script, encoding="utf-8")


def _archive_gallery(gallery: Path, target: Path) -> None:
    """Reject unexpected scientific/log/identity files before creating a share archive."""
    files = []
    for path in sorted(gallery.rglob("*")):
        if path.is_symlink():
            raise ValueError("Sharing gallery must not contain symbolic links")
        if not path.is_file():
            continue
        relative = path.relative_to(gallery)
        allowed = relative.as_posix() in {
            "index.html",
            "mesh-pca.html",
            "mesh-pca.json",
            "mesh-view.json",
        }
        allowed |= len(relative.parts) == 2 and (
            (relative.parts[0] == "figures" and path.suffix in {".png", ".pdf"})
            or (relative.parts[0] == "thumbnails" and path.suffix == ".png")
            or (relative.parts[0] == "videos" and path.suffix == ".mp4")
        )
        if not allowed:
            raise ValueError("Unexpected file in presentation-only sharing gallery")
        files.append(path)
    with zipfile.ZipFile(target, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(gallery.parent).as_posix())
    with zipfile.ZipFile(target) as archive:
        if archive.testzip() is not None:
            raise ValueError("Sharing archive did not verify")
