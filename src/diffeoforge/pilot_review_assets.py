# ruff: noqa: E501
"""Run-local observation of new regional fits; no alternate optimizer."""

DECLARATION = {"version": "accepted-pilot-review-v1", "interval_seconds": 600}

SOURCE = rb'''"""Accepted-state review with the existing native optimizer held in memory."""
import hashlib
import json
import os
from pathlib import Path
import secrets
import time
import xml.etree.ElementTree as ET
import numpy as np

VERSION = 'accepted-pilot-review-v1'

def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.sha256(f.read()).hexdigest()

def atomic(path, value):
    temporary = path.with_name('.' + path.name + '-' + secrets.token_hex(8))
    with temporary.open('x', encoding='utf-8') as f:
        json.dump(value, f, allow_nan=False); f.flush(); os.fsync(f.fileno())
    os.replace(str(temporary), str(path))

class Review:
    def __init__(self, context, estimator, guard, clock=time.monotonic):
        self.context, self.estimator, self.guard, self.clock = context, estimator, guard, clock
        self.interval = 600
        self.started = self.clock(); self.waited = 0.; self.next_review = self.interval
        self.root = context.root / 'output' / 'pilot-review'
        self.root.mkdir(exist_ok=False)
        self.manifest_sha = sha(context.root / 'manifest.json')
        self.generation = 0

    def due(self):
        return self.clock() - self.started - self.waited >= self.next_review

    def after_accept(self, state, initial=False):
        # No review after a native cap/tolerance stop, nor after an initial state.
        if initial or self.estimator.current_iteration > self.estimator.max_iterations or not self.due():
            return
        # Only the current FG evaluation has a trustworthy cached native flow.
        # A cached older accepted vector must not be paired with a later trial's mesh.
        if state['evaluation'] != self.guard.evaluations:
            return
        self.context.verify_content()
        actual = self.estimator._vectorize_parameters(self.estimator._get_parameters())
        self.guard.require_bound_vector(actual, self.guard.accepted, 'review_parameter_binding')
        model = self.estimator.statistical_model
        names = [o.attrib['id'] for o in ET.parse(str(self.context.engine / 'model.xml')).getroot().find('template')]
        expected_id = self.context.manifest['effective_config']['model']['object_id']
        if len(names) != len(model.template.object_list) or expected_id not in names:
            raise ValueError('Review surface object binding differs')
        index = names.index(expected_id)
        objects = model.template.object_list
        if any(o.type.lower() not in ('surfacemesh', 'landmark') for o in objects):
            raise ValueError('Unsupported review object type')
        offset = sum(o.get_number_of_points() for o in objects[:index])
        count = objects[index].get_number_of_points()
        points = model.exponential.get_template_points()['landmark_points'].detach().cpu().numpy()[offset:offset+count].copy()
        if points.shape != (count, 3) or not np.isfinite(points).all():
            raise ValueError('Nonfinite or incomplete review geometry')
        self.generation += 1
        folder = self.root / ('review-%04d' % self.generation); folder.mkdir()
        for name, values in [('points.npy', points), ('parameters.npy', state['x'])]:
            with (folder / name).open('xb') as f:
                np.save(f, values, allow_pickle=False); f.flush(); os.fsync(f.fileno())
        active = self.clock() - self.started - self.waited
        nonce = secrets.token_hex(32)
        receipt = dict(version=VERSION, manifest_sha256=self.manifest_sha, run_id=self.context.root.name,
            generation=self.generation, nonce=nonce, native_state_index=int(self.estimator.current_iteration),
            accepted_updates=self.guard.accepted_count-1, evaluation=state['evaluation'],
            parameter_sha256=state['key'], objective=state['f'], active_seconds=active,
            source_object_id=expected_id, points_count=count, coordinate_scope='native incoming template; display only',
            files={n:dict(sha256=sha(folder/n), bytes=(folder/n).stat().st_size) for n in ['points.npy','parameters.npy']},
            numerical_convergence=False, anatomical_approval=False)
        atomic(folder / 'receipt.json', receipt)
        live = dict(version=VERSION, status='waiting', generation=self.generation, nonce=nonce,
            manifest_sha256=self.manifest_sha, receipt_sha256=sha(folder/'receipt.json'))
        atomic(self.root / 'live.json', live)
        print('DF_PILOT_REVIEW waiting at accepted state %s; optimizer retained in memory' % self.estimator.current_iteration, flush=True)
        paused = self.clock()
        while True:
            self.guard._active()
            command_path = folder / 'command.json'
            if command_path.is_file():
                if command_path.stat().st_size > 4096: raise ValueError('Oversized review command')
                command = json.loads(command_path.read_text(encoding='utf-8'))
                binding = dict(version=VERSION, generation=self.generation, nonce=nonce, manifest_sha256=self.manifest_sha)
                if any(command.get(k) != v for k,v in binding.items()) or set(command) != set(binding) | {'action'}:
                    raise ValueError('Stale or mismatched review command')
                if command['action'] not in ('continue', 'finish'):
                    raise ValueError('Unsupported review command')
                break
            time.sleep(.2)
        self.context.verify_content()
        waited = self.clock() - paused; self.waited += waited
        # Always grant a fresh ten minutes of ACTIVE work; review waiting is excluded.
        self.next_review = self.clock() - self.started - self.waited + self.interval
        finished = command['action'] == 'finish'
        decision = dict(receipt_sha256=sha(folder/'receipt.json'), command_sha256=sha(command_path),
            action=command['action'], waiting_seconds=waited, generation=self.generation,
            native_state_index=int(self.estimator.current_iteration), parameter_sha256=state['key'],
            manifest_sha256=self.manifest_sha, numerical_convergence=False)
        atomic(folder/'decision.json', decision)
        atomic(self.root/'live.json', dict(live, status='finishing' if finished else 'running'))
        print('DF_PILOT_REVIEW decision %s' % command['action'], flush=True)
        if finished:
            atomic(self.root/'finish.json', decision)
            print('>> STOP: PILOT REVIEW REQUEST (accepted state; not convergence)', flush=True)
            # Native ScipyOptimize.update already catches its callback StopIteration
            # and performs the ordinary bound write/export. Do not fabricate a result.
            raise StopIteration

def install(context, guard_module):
    entry = context.manifest['effective_config']['project']['parameter_provenance'].get('pilot_review')
    if entry != dict(version=VERSION, interval_seconds=600):
        raise ValueError('Review declaration differs')
    if context.protected.get('engine/pilot_review_runtime.py', {}).get('sha256') != sha(__file__):
        raise ValueError('Review module is not protected by the manifest')
    original_attach = guard_module.attach_instance
    # The adapter is already loaded in this interpreter. Compiler/helper Python
    # children must not inherit it and try to initialize the same active run.
    os.environ.pop('PYTHONPATH', None)
    def attach(estimator, *args, **kwargs):
        guard = original_attach(estimator, *args, **kwargs)
        review = Review(context, estimator, guard)
        original_commit = guard.commit
        def commit(state, iteration, initial=False):
            result = original_commit(state, iteration, initial=initial)
            review.after_accept(state, initial=initial)
            return result
        guard.commit = commit
        return guard
    guard_module.attach_instance = attach
'''
