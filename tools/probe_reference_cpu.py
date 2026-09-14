"""Read-only public-fixture reduction probe for frozen Python 3.8 / Torch 1.6.

Not an atlas implementation or a replacement acceptance test. Run in the
reference environment; outputs expose the operands before the final float32
dot reductions so compiler/kernel differences can be separated from BLAS ones.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import platform
from pathlib import Path


def checked_meshes(repo):
    root = repo / "examples/synthetic/meshes"
    manifest_path = root / "dataset-manifest.json"
    if hashlib.sha256(manifest_path.read_bytes()).hexdigest() != (
        "40a51d572cb97ab1f90164025f36a366ade2ae4be6b995af283debf440f6c904"
    ):
        raise ValueError("Probe accepts only the unchanged public synthetic fixture")
    manifest = json.loads(manifest_path.read_text())
    paths = {}
    for item in manifest["surfaces"]:
        path = root / item["filename"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError("Public synthetic mesh checksum mismatch")
        paths[item["filename"]] = path
    return paths


def observe(repo):
    import torch
    from deformetrica.core import GpuMode
    from deformetrica.in_out.deformable_object_reader import DeformableObjectReader
    from deformetrica.support.kernels.keops_kernel import KeopsKernel

    paths = checked_meshes(repo)
    logging.disable(logging.CRITICAL)
    kernel = KeopsKernel(kernel_width=0.45, gpu_mode=GpuMode.NONE)
    source = DeformableObjectReader.create_object(str(paths["template.vtk"]), "SurfaceMesh")
    records = []
    for name, path in sorted(paths.items()):
        if not name.startswith("subject-"):
            continue
        target = DeformableObjectReader.create_object(str(path), "SurfaceMesh")
        points = torch.tensor(source.points, dtype=torch.float32, requires_grad=True)
        c1, n1 = source.get_centers_and_normals(points)
        c2, n2 = target.get_centers_and_normals()
        terms = []
        tensors = []
        for label, x, y, left, right in (
            ("source_self", c1, c1, n1, n1),
            ("target_self", c2, c2, n2, n2),
            ("cross", c1, c2, n1, n2),
        ):
            operand = kernel.convolve(x, y, right).view(-1)
            normal = left.view(-1)
            value = torch.dot(normal, operand)
            tensors.append(value)
            terms.append(
                {
                    "term": label,
                    "left_sha256": hashlib.sha256(normal.detach().numpy().tobytes()).hexdigest(),
                    "right_sha256": hashlib.sha256(operand.detach().numpy().tobytes()).hexdigest(),
                    "dot_float32": value.item(),
                    "dot_float64": torch.dot(normal.double(), operand.double()).item(),
                }
            )
        residual = tensors[0] + tensors[1] - 2 * tensors[2]
        (gradient,) = torch.autograd.grad(residual, points)
        records.append(
            {
                "subject": name,
                "terms": terms,
                "residual": residual.item(),
                "gradient_sha256": hashlib.sha256(gradient.numpy().tobytes()).hexdigest(),
            }
        )
    cpu = Path("/proc/cpuinfo")
    model = (
        next(
            (
                line.split(":", 1)[1].strip()
                for line in cpu.read_text().splitlines()
                if line.startswith("model name")
            ),
            "unavailable",
        )
        if cpu.exists()
        else "unavailable"
    )
    return {
        "protocol": "public-reference-cpu-reduction-v1",
        "torch": torch.__version__,
        "python": platform.python_version(),
        "cpu_model": model,
        "torch_build": torch.__config__.show(),
        "threads": torch.get_num_threads(),
        "environment": {
            key: os.environ.get(key)
            for key in ("MKL_CBWR", "MKL_ENABLE_INSTRUCTIONS", "MKL_NUM_THREADS", "OMP_NUM_THREADS")
        },
        "subjects": records,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists; evidence is never overwritten")
    result = observe(args.repository)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


if __name__ == "__main__":
    main()
