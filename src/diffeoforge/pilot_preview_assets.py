"""Passive display samples from an already computed native pilot flow."""

SOURCE = br'''"""Run-local publisher for the optional pilot live preview."""
import functools
import hashlib
import inspect
import json
import math
import os
from pathlib import Path
import re
import stat
import threading
import time
import uuid
import xml.etree.ElementTree as ET

import numpy as np

VERSION = 'pilot-live-preview-v1'
MAX_POINTS = 4096
MAX_CONTROLS = 128
MAX_REQUEST_AGE = 30
POLL_SECONDS = 3
FRAME_SECONDS = 20
_GA_SHA256 = '30c9b85d41624b67018ac31b0f7b1bd593e4c11226ceb05e6d981a0f770e7a25'


def _regular(info):
    return stat.S_ISREG(info.st_mode) and not getattr(info, 'st_file_attributes', 0) & 0x400


def _identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def _read_bounded(path, limit):
    listed = path.lstat()
    if not _regular(listed) or listed.st_size > limit:
        raise ValueError('Invalid live preview input')
    with path.open('rb') as handle:
        if _identity(listed) != _identity(os.fstat(handle.fileno())):
            raise ValueError('Preview input changed before read')
        content = handle.read(limit + 1)
        if (len(content) != listed.st_size
                or _identity(listed) != _identity(os.fstat(handle.fileno()))):
            raise ValueError('Preview input changed during read')
    return content


class Publisher:
    def __init__(self, engine):
        engine = Path(engine).resolve()
        self.directory = engine.parent / 'pilot-preview'
        self.request_path = self.directory / 'request.json'
        raw = _read_bounded(engine.parent / 'manifest.json', 16_777_216)
        self.manifest = hashlib.sha256(raw).hexdigest()
        manifest = json.loads(raw)
        self.object_id = manifest['effective_config']['model']['object_id']
        files = {row['path']: row['sha256'] for row in manifest['protected_artifacts']}
        model = _read_bounded(engine / 'model.xml', 1_048_576)
        if hashlib.sha256(model).hexdigest() != files['engine/model.xml']:
            raise ValueError('Preview model identity changed')
        objects = ET.fromstring(model).findall('template/object')
        identifiers = [obj.attrib['id'] for obj in objects]
        if identifiers.count(self.object_id) != 1:
            raise ValueError('Preview object is not unique')
        self.source_index = identifiers.index(self.object_id)
        self.types = tuple(obj.findtext('deformable-object-type').lower() for obj in objects)
        if self.types[self.source_index] != 'surfacemesh' or any(
            kind not in ('surfacemesh', 'landmark') for kind in self.types
        ):
            raise ValueError('Unsupported preview template objects')
        self.next_poll = self.next_frame = 0
        self.rejected_request = None
        self.busy = False

    def _request(self, expected=None):
        directory = self.directory.lstat()
        if (not stat.S_ISDIR(directory.st_mode)
                or getattr(directory, 'st_file_attributes', 0) & 0x400):
            return None
        info = self.request_path.lstat()
        age = time.time() - info.st_mtime
        if (
            not _regular(info)
            or not -5 <= age <= MAX_REQUEST_AGE
            or (expected is not None and _identity(info) != expected)
        ):
            return None
        request = json.loads(_read_bounded(self.request_path, 65536))
        if expected is not None and _identity(self.request_path.lstat()) != expected:
            return None
        if (
            not isinstance(request, dict)
            or set(request) != {
                'version', 'id', 'manifest_sha256', 'object_id', 'vertex_count', 'indices',
            }
            or request['version'] != VERSION
            or request['manifest_sha256'] != self.manifest
            or request['object_id'] != self.object_id
            or not isinstance(request['id'], str)
            or re.fullmatch('[0-9a-f]{32}', request['id']) is None
            or type(request['vertex_count']) is not int
            or request['vertex_count'] < 3
        ):
            return None
        rows = request['indices']
        if (
            not isinstance(rows, list) or not 3 <= len(rows) <= MAX_POINTS
            or any(type(i) is not int or not 0 <= i < request['vertex_count'] for i in rows)
            or len(set(rows)) != len(rows)
            or (self.directory / ('stop-' + request['id'])).exists()
        ):
            return None
        return request

    def offer(self, estimator, iteration):
        now = time.monotonic()
        if self.busy or now < max(self.next_poll, self.next_frame):
            return
        self.next_poll = now + POLL_SECONDS
        try:
            info = self.request_path.lstat()
            stamp = _identity(info)
            if not _regular(info) or stamp == self.rejected_request:
                return
            model = estimator.statistical_model
            if (
                model.name != 'DeterministicAtlas'
                or model.number_of_processes != 1
                or len(estimator.dataset.subject_ids) != 1
                or not model.freeze_template or not model.freeze_control_points
            ):
                return
            flow = model.exponential
            if flow.flow_is_modified or flow.shoot_is_modified:
                return
            objects = model.template.object_list
            if tuple(obj.type.lower() for obj in objects) != self.types:
                return
            counts = [obj.get_number_of_points() for obj in objects]
            count = counts[self.source_index]
            offset = sum(counts[:self.source_index])
            cache = flow.get_template_points()['landmark_points']
            if tuple(cache.shape) != (sum(counts), 3):
                return
            # The next native flow replaces its endpoint tensors. Detached views
            # hold the observed endpoint without retaining its autograd graph.
            vertices = cache.detach()
            endpoint = flow.control_points_t[-1].detach()
            if endpoint.ndim != 2 or endpoint.shape[1] != 3:
                return
            worker = threading.Thread(
                target=self._publish,
                args=(stamp, int(iteration), vertices, offset, count, endpoint),
                name='diffeoforge-pilot-preview',
                daemon=True,
            )
            self.busy = True
            try:
                worker.start()
            except Exception:
                self.busy = False
        except Exception:
            # The display observer has no authority over native computation.
            return

    def _publish(self, stamp, iteration, vertices, offset, count, endpoint):
        temporary = None
        request = None
        try:
            request = self._request(stamp)
            if request is None or request['vertex_count'] != count:
                self.rejected_request = stamp
                return
            self.next_frame = time.monotonic() + FRAME_SECONDS
            rows = [offset + i for i in request['indices']]
            points = vertices[rows, :].cpu().numpy()
            count = endpoint.shape[0]
            if count > MAX_CONTROLS:
                indices = np.linspace(0, count - 1, MAX_CONTROLS, dtype=np.int64).tolist()
                controls = endpoint[indices, :].cpu().numpy()
            else:
                controls = endpoint.cpu().numpy()
            if not np.isfinite(points).all() or not np.isfinite(controls).all():
                return
            temporary = self.directory / ('.frame-' + uuid.uuid4().hex + '.npz')
            with temporary.open('xb') as stream:
                np.savez(stream,
                         id=np.asarray(request['id'], dtype='U32'),
                         iteration=np.asarray(iteration, dtype=np.int64),
                         points=points, controls=controls)
            if self._request() == request:
                os.replace(temporary, self.directory / 'frame.npz')
        except Exception:
            # A closed observer, busy disk or invalid frame is dropped.
            if request is None:
                self.rejected_request = stamp
        finally:
            if temporary is not None:
                try:
                    temporary.unlink()
                except OSError:
                    pass
            self.busy = False


def _attach_guarded(publisher, guard_module):
    original_attach = guard_module.attach_instance

    @functools.wraps(original_attach)
    def attach(estimator, *args, **kwargs):
        guard = original_attach(estimator, *args, **kwargs)
        original_commit = guard.commit

        @functools.wraps(original_commit)
        def commit(state, iteration, initial=False):
            result = original_commit(state, iteration, initial=initial)
            # An older accepted vector in the guard cache cannot identify
            # the endpoint left by a later objective evaluation.
            try:
                if (
                    not initial
                    and state['evaluation'] == guard.evaluations
                    and getattr(estimator, 'parameters_order', None) == ['momenta']
                ):
                    publisher.offer(estimator, iteration)
            except Exception:
                pass
            return result

        guard.commit = commit
        return guard

    guard_module.attach_instance = attach


def _attach_gradient_ascent(publisher, gradient_ascent):
    # This pinned implementation calls print on its evaluated initial state
    # and after committing a successful line search. With only momenta free,
    # the final evaluated line-search candidate is necessarily the committed one.
    original_print = gradient_ascent.print
    source = inspect.getsourcefile(original_print)
    if source is None:
        return
    if hashlib.sha256(_read_bounded(Path(source), 262144)).hexdigest() != _GA_SHA256:
        return

    @functools.wraps(original_print)
    def show_progress(estimator):
        result = original_print(estimator)
        try:
            if (
                estimator.current_iteration > 0
                and set(estimator.current_parameters) == {'momenta'}
                and math.isfinite(estimator.current_log_likelihood)
            ):
                publisher.offer(estimator, estimator.current_iteration)
        except Exception:
            pass
        return result

    gradient_ascent.print = show_progress


def install(engine, guard_module=None, method='gradient_ascent'):
    """Attach only to newly rendered pilot runs with an eligible native path."""
    publisher = Publisher(engine)
    if method == 'lbfgs' and guard_module is not None:
        _attach_guarded(publisher, guard_module)
    elif method == 'gradient_ascent':
        from deformetrica.core.estimators.gradient_ascent import GradientAscent

        _attach_gradient_ascent(publisher, GradientAscent)
'''
