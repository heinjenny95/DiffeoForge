"""Run-local deterministic CPU triangle indexing for newly prepared guarded fits."""

DECLARATION = {"version": "deterministic-cpu-surface-gather-v1"}

SOURCE = br'''"""Equivalent CPU vertex selection with reproducible gradient accumulation."""
import hashlib
import inspect
import json
from pathlib import Path

DECLARATION = {'version': 'deterministic-cpu-surface-gather-v1'}
NATIVE_SHA = '7e42e1426d2c64247f90057b14232385862a452a674c3955bb3b2499f667be1f'


def install(context):
    import torch
    from deformetrica.core import default
    from deformetrica.support import utilities
    from deformetrica.core.observations.deformable_objects.landmarks.surface_mesh import SurfaceMesh

    provenance = context.manifest['effective_config']['project']['parameter_provenance']
    path = Path(__file__).resolve()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    policy = context.policy.get('surface_gather')
    row = context.protected.get('engine/cpu_surface_gather.py')
    if (provenance.get('surface_gather') != DECLARATION
            or policy != dict(declaration=DECLARATION, sha256=digest)
            or row is None or row['sha256'] != digest or row['bytes'] != path.stat().st_size
            or path != context.engine / 'cpu_surface_gather.py'):
        raise ValueError('CPU surface gather declaration/code binding differs')
    original = SurfaceMesh._get_centers_and_normals
    native = inspect.getsourcefile(original)
    if (getattr(SurfaceMesh, '_df_cpu_surface_gather', False) or native is None
            or original.__module__ != SurfaceMesh.__module__
            or hashlib.sha256(Path(native).read_bytes()).hexdigest() != NATIVE_SHA):
        raise ValueError('CPU surface gather requires the qualified original native method')

    def selected(points, triangles, tensor_scalar_type=default.tensor_scalar_type,
                 tensor_integer_type=default.tensor_integer_type, device='cpu'):
        if torch.device(device).type != 'cpu':
            return original(points, triangles, tensor_scalar_type, tensor_integer_type, device)
        points = utilities.move_data(points, dtype=tensor_scalar_type, device=device)
        triangles = utilities.move_data(triangles, dtype=tensor_integer_type, device=device)
        a, b, c = (torch.index_select(points, 0, triangles[:, i]) for i in range(3))
        centers = (a + b + c) / 3.
        normals = torch.cross(b - a, c - a) / 2
        assert torch.device(device) == centers.device == normals.device
        return centers, normals

    SurfaceMesh._get_centers_and_normals = staticmethod(selected)
    SurfaceMesh._df_cpu_surface_gather = True
    context.verify_content()
    with (context.root / 'output/surface-gather-runtime.json').open('x') as stream:
        json.dump(dict(declaration=DECLARATION, adapter_sha256=digest,
                       original_native_sha256=NATIVE_SHA,
                       cpu_threads=torch.get_num_threads(),
                       mathematical_formula='unchanged', gradient_tolerance='unchanged'), stream)
'''
