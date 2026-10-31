"""Keep complete saved fields and their protection on one verified material grid."""
from pathlib import Path

import numpy as np

from diffeoforge.mesh import sha256_file


def _geometry(path):
    from diffeoforge.surface_io import load_surface_mesh

    return load_surface_mesh(path).geometry


def _same_connectivity(a, b):
    return (len(a.vertices) == len(b.vertices)
            and np.array_equal(a.triangles, b.triangles))


def common_grid(source, evaluations):
    """Choose an existing nested refinement, never downsample or interpolate a fit."""
    from diffeoforge.regional_frame import verify_source

    original = _geometry(source)
    grids = []
    for entry in evaluations:
        verify_source(entry)
        row = entry['reference_source']
        grids.append((row, _geometry(row['path'])))
    chosen, geometry = max(grids, key=lambda item: len(item[1].vertices))
    for other in [original, *(g for _, g in grids)]:
        vertices = np.asarray(other.vertices)
        if not np.array_equal(np.asarray(geometry.vertices)[:len(vertices)], vertices):
            raise ValueError('Saved fields do not share unchanged original material vertices')
        if len(vertices) == len(geometry.vertices) and not _same_connectivity(other, geometry):
            raise ValueError('Saved fields have conflicting original material connectivity')
    return chosen


def align(root, manifest, record, recipe, residual, source, automatic, anchor, retained_run):
    """A finer warm frame uses the existing explicit zero-residual contract."""
    from diffeoforge.regional_frame import qualify, verify_source

    root, source = Path(root), Path(source)
    response = None
    if residual is None and record['refinement']['initialization'] == 'learned':
        incoming = _geometry(source)
        if any(not _same_connectivity(incoming, _geometry(e['endpoint']['path']))
               for e in (automatic, anchor)):
            if sha256_file(source) != manifest['inputs']['template']['sha256']:
                raise ValueError('Incoming original material changed before frame preparation')
            grid = common_grid(source, (automatic, anchor))
            response = dict(version='regional-material-frame-v1',
                action='retain_complete_field_and_fit_zero_residual',
                incoming_source_sha256=sha256_file(source),
                original_material_grid=dict(grid), optimizer_restored=False,
                existing_field_parameters_changed=False, anatomical_approval=False)
            recipe = dict(recipe, residual=True, phase='detail', material_frame_response=response)
            strategy = dict(record['guided']['strategy'], regional_recipe=recipe,
                            initialization='residual')
            strategy['reason'] = strategy.get('reason', '') + (
                ' The saved fit uses refined original material. Keep its complete field '
                'as a fixed prefix and prepare a local zero-initialized residual on that grid.')
            record = dict(record, guided=dict(record['guided'], strategy=strategy))
            from diffeoforge.regional_residual import bind

            record = bind(root, manifest, record, recipe, source_grid=grid)
            residual = record['refinement']['residual']
            source = root / residual['source']['copy']
            automatic = record['refinement']['parent_evaluation']
    if residual and residual.get('original_source_grid'):
        row = residual['original_source_grid']
        grid = root / row['copy']
        if sha256_file(grid) != row['sha256']:
            raise ValueError('Shared original material grid changed')
        if not _same_connectivity(_geometry(source), _geometry(grid)):
            raise ValueError('Incoming residual and original material connectivity differ')
        aligned = []
        for name, run, entry in [('automatic', automatic['source_run'], automatic),
                                  ('retained', retained_run, anchor)]:
            verify_source(entry)
            if (Path(entry['source_run']).resolve() != Path(run).resolve()
                    or entry['reference_source']['sha256'] != row['sha256']):
                entry = qualify(run, root / (name+'-shared-material-frame'), source=grid)
            verify_source(entry)
            if entry['reference_source']['sha256'] != row['sha256']:
                raise ValueError('Saved comparison did not use the shared original material grid')
            aligned.append(entry)
        automatic, anchor = aligned
    return record, recipe, residual, source, automatic, anchor, response
