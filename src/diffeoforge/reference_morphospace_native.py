"""Bind diagnostics to accepted states of the pinned native atlas optimizer."""

from pathlib import PurePosixPath

from diffeoforge.reference_convergence_context import (
    ADAPTER_SOURCE,
    UPDATE_SHA256,
    validate_context,
)

REPORT_NAME = "morphospace-stability.json"
LIVE_PREFIX = "DiffeoForge morphospace stability: "


def manifest_subject_labels(manifest):
    """Recover the same ordered subject IDs as the generated native dataset."""
    return tuple(
        PurePosixPath(row["staged_path"]).name
        for row in manifest["inputs"]
        if row["role"] == "subject"
    )


def adapter_source(config, subject_labels, *, reference=None, require_saved=False):
    """Stage the same metric used by host atlas analysis in the native runtime."""
    policy = config.get("project", {}).get("atlas_stop")
    if policy is None:
        return ""
    if (config["output"].get("checkpoint_mode") != "compact_final_export"
            or config["optimization"]["method"] != "gradient_ascent"):
        raise ValueError("Atlas stopping evidence requires compact native GradientAscent")
    unlimited = policy.get("unlimited_iterations", False)
    if type(unlimited) is not bool or (unlimited and policy["mode"] != "morphospace_stability"):
        raise ValueError("Unlimited joint iterations require automatic morphospace stopping")
    labels = tuple(subject_labels)
    if len(labels) < 2 or len(set(labels)) != len(labels):
        raise ValueError("Atlas stopping evidence requires an ordered multi-specimen cohort")
    from diffeoforge.reference_morphospace_stopping import metric_source

    width = config["model"]["deformation"]["kernel_width"]
    hooks = ""
    if reference is not None:
        if policy["mode"] != "optimizer_convergence":
            raise ValueError("Atlas objective reference requires optimizer convergence stopping")
        reference = validate_context(reference, config["optimization"]["convergence_tolerance"])
        hooks = ADAPTER_SOURCE + "\n_df_install_reference_dump()\n"
    return (
        hooks + "\n" + metric_source() + NATIVE_SOURCE
        + f"\n_df_ms_install_update({policy!r}, {labels!r}, {width!r}, {UPDATE_SHA256!r}, "
        f"{reference!r}, {require_saved!r})\n"
    )


# Standalone Python 3.8 source runs inside the pinned native interpreter. The
# injected hooks observe installed parameters and preserve the native line search,
# step-size evolution, objective, integration and callback within one invocation.
NATIVE_SOURCE = '''
import ast as _df_ms_ast
import hashlib as _df_ms_hashlib
import inspect as _df_ms_inspect
import json as _df_ms_json
import logging as _df_ms_logging
import math as _df_ms_math
import os as _df_ms_os
import pathlib as _df_ms_pathlib
import tempfile as _df_ms_tempfile
import textwrap as _df_ms_textwrap
import types as _df_ms_types
import numpy as _df_ms_np
from deformetrica.core.estimators.gradient_ascent import GradientAscent as _df_ms_ga

_df_ms_logger = _df_ms_logging.getLogger("diffeoforge.morphospace")


class _df_ms_NumericalError(RuntimeError):
    pass


def _df_ms_digest(path):
    digest = _df_ms_hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _df_ms_atomic(path, write):
    fd, temporary = _df_ms_tempfile.mkstemp(prefix=".df-morphospace-", dir=str(path.parent))
    try:
        with _df_ms_os.fdopen(fd, "wb") as stream:
            write(stream)
            stream.flush()
            _df_ms_os.fsync(stream.fileno())
        _df_ms_os.replace(temporary, str(path))
    finally:
        if _df_ms_os.path.exists(temporary):
            _df_ms_os.unlink(temporary)


def _df_ms_json_bytes(value):
    text = _df_ms_json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
    return (text + "\\n").encode("utf-8")


class _df_ms_Session:
    def __init__(self, estimator, policy, labels, width):
        self.estimator = estimator
        self.policy = policy
        self.labels = labels
        self.width = width
        self.origin = int(estimator.current_iteration)
        self.accepted = self.origin
        self.root = _df_ms_pathlib.Path(estimator.output_dir)
        self.report = self.root / "morphospace-stability.json"
        self.fields = self.root / "morphospace-checkpoints"
        self.fields.mkdir()
        self.cache = {}
        self.observations = []
        self.terminal = None
        self.reason = None
        self.candidate = False
        self.finite_trial = False

    def publish(self):
        payload = dict(version=1, policy=self.policy, subject_labels=self.labels,
                       deformation_kernel_width=self.width, joint_origin_iteration=self.origin,
                       observations=self.observations, terminal=self.terminal)
        _df_ms_atomic(self.report, lambda stream: stream.write(_df_ms_json_bytes(payload)))

    def comparison(self, distances, window):
        previous = min((index for index in self.cache if index >= self.accepted - window),
                       default=None)
        old_checkpoint, old_distances = self.cache.get(previous, (None, None))
        change = dict(status="unavailable", cohort_percent=None, max_subject_percent=None,
                      worst_subjects=[], subject_percent=None, stable=False)
        if old_distances is not None and distances is not None:
            change = compare_distances(old_distances, distances, self.labels)
        span = self.accepted - previous if previous is not None else 0
        change["stable"] = bool(change["stable"] and span == window)
        return dict(previous_iteration=previous, window_iterations=span,
                    previous_checkpoint=old_checkpoint, **change)

    def can_stop(self, row):
        if self.policy["mode"] != "morphospace_stability" or not row["stable"]:
            return False
        long_window = self.policy.get("long_window_iterations")
        return (long_window is None or self.accepted - self.origin < long_window
                or row["long_window"]["stable"])

    def snapshot(self):
        if self.observations and self.observations[-1]["iteration"] == self.accepted:
            return self.observations[-1]
        estimator = self.estimator
        model = estimator.statistical_model
        target = self.fields / ("iteration-%d.npz" % self.accepted)
        checkpoint, distances = None, None
        try:
            momenta = _df_ms_np.asarray(model.get_momenta())
            controls = _df_ms_np.asarray(model.get_control_points())
            if (momenta.ndim == 3 and momenta.shape[0] == len(self.labels)
                    and controls.shape == momenta.shape[1:]
                    and controls.shape[0] > 0 and controls.shape[1] == 3
                    and _df_ms_np.issubdtype(momenta.dtype, _df_ms_np.floating)
                    and _df_ms_np.issubdtype(controls.dtype, _df_ms_np.floating)
                    and _df_ms_np.isfinite(momenta).all() and _df_ms_np.isfinite(controls).all()
                    and tuple(estimator.dataset.subject_ids) == self.labels):
                _df_ms_atomic(target, lambda stream: _df_ms_np.savez(
                    stream, momenta=momenta, control_points=controls))
                checkpoint = dict(path=target.relative_to(self.root).as_posix(),
                                  sha256=_df_ms_digest(target))
                distances = distance_matrix(
                    momenta.astype(_df_ms_np.float64, copy=False),
                    controls.astype(_df_ms_np.float64, copy=False), self.width)
        except (AttributeError, TypeError, ValueError, ArithmeticError,
                _df_ms_np.linalg.LinAlgError):
            distances = None

        window = self.policy["window_iterations"]
        long_window = self.policy.get("long_window_iterations")
        self.cache = {index: values for index, values in self.cache.items()
                      if index >= self.accepted - (long_window or window)}
        row = dict(iteration=self.accepted, checkpoint=checkpoint,
                   objective=float(estimator.current_log_likelihood),
                   weighted_fit_error=-float(estimator.current_attachment),
                   **self.comparison(distances, window))
        if long_window is not None:
            row["long_window"] = self.comparison(distances, long_window)
        self.cache[self.accepted] = checkpoint, distances
        self.observations.append(row)
        self.publish()
        _df_ms_logger.info("DiffeoForge morphospace stability: %s",
                           _df_ms_json_bytes(row).decode("ascii").strip())
        return row

    def finish(self, reason, export):
        checkpoint_sha256 = None
        if self.observations:
            self.estimator.current_iteration = self.accepted
            self.estimator._set_parameters(self.estimator.current_parameters)
            row = self.snapshot()
            if reason == "iteration_limit" and self.can_stop(row):
                reason = "morphospace_stable"
            self.estimator._dump_state_file()
            checkpoint_sha256 = _df_ms_digest(self.estimator.state_file)
        self.terminal = dict(reason=reason, iteration=self.accepted,
                             checkpoint_sha256=checkpoint_sha256, export=export)
        self.publish()


def _df_ms_check_gradient(gradient):
    if any(not _df_ms_np.isfinite(value).all() for value in gradient.values()):
        raise _df_ms_NumericalError("Nonfinite atlas gradient")


def _df_ms_check_objective(attachment, regularity):
    if not _df_ms_finite_objective(attachment, regularity):
        raise _df_ms_NumericalError("Nonfinite accepted atlas objective")


def _df_ms_finite_objective(attachment, regularity):
    return all(_df_ms_math.isfinite(float(value))
               for value in (attachment, regularity, attachment + regularity))


def _df_ms_trial(estimator, objective):
    if _df_ms_finite_objective(*objective):
        estimator._df_ms_session.finite_trial = True
    return objective


def _df_ms_exhausted(estimator):
    session = estimator._df_ms_session
    if not session.finite_trial:
        raise _df_ms_NumericalError("No finite atlas line-search objective")
    session.reason = "line_search_exhausted"


def _df_ms_initial(estimator, gradient):
    _df_ms_check_objective(estimator.current_attachment, estimator.current_regularity)
    _df_ms_check_gradient(gradient)
    estimator._df_ms_session.snapshot()


def _df_ms_accept(estimator):
    session = estimator._df_ms_session
    if int(estimator.current_iteration) != session.accepted + 1:
        raise RuntimeError("Accepted atlas iteration is not sequential")
    session.accepted = int(estimator.current_iteration)
    if (session.accepted - session.origin) % session.policy["check_interval"] == 0:
        session.candidate = session.can_stop(session.snapshot())


def _df_ms_tolerance(estimator, hit):
    session = estimator._df_ms_session
    if hit and session.policy["mode"] == "optimizer_convergence":
        session.reason = "native_tolerance"
        return True
    return False


def _df_ms_after_callback(estimator):
    session = estimator._df_ms_session
    if not estimator.callback_ret:
        session.reason = "optimizer_callback"
    elif session.candidate:
        session.reason = "morphospace_stable"
    return session.reason is not None


def _df_ms_rebind(original, expected_sha256, unlimited_iterations,
                  reference=None, require_saved=False):
    source = _df_ms_textwrap.dedent(_df_ms_inspect.getsource(original))
    if _df_ms_hashlib.sha256(source.encode("utf-8")).hexdigest() != expected_sha256:
        raise RuntimeError("Unsupported native GradientAscent.update source")

    def statement(text):
        return _df_ms_ast.parse(text).body[0]

    def find(body, test):
        matches = [index for index, node in enumerate(body) if test(node)]
        if len(matches) != 1:
            raise RuntimeError("Unsupported native accepted-state structure")
        return matches[0]

    def exact(text):
        wanted = _df_ms_ast.dump(statement(text))
        return lambda node: _df_ms_ast.dump(node) == wanted

    def conditional(text):
        wanted = _df_ms_ast.dump(_df_ms_ast.parse(text, mode="eval").body)
        return lambda node: (isinstance(node, _df_ms_ast.If)
                             and _df_ms_ast.dump(node.test) == wanted)

    function = _df_ms_ast.parse(source).body[0]
    initial = find(function.body, exact("self.print()"))
    function.body.insert(initial, statement("_df_ms_initial(self, gradient)"))
    loop = function.body[find(function.body, lambda node: isinstance(node, _df_ms_ast.While))]
    loop.body.insert(0, statement("self._df_ms_session.finite_trial = False"))
    for node in _df_ms_ast.walk(loop):
        if (isinstance(node, _df_ms_ast.Assign) and isinstance(node.value, _df_ms_ast.Call)
                and isinstance(node.value.func, _df_ms_ast.Attribute)
                and node.value.func.attr == "_evaluate_model_fit" and not node.value.keywords):
            trial = _df_ms_ast.parse("_df_ms_trial(self, None)", mode="eval").body
            trial.args[1] = node.value
            node.value = trial
    exhausted = loop.body[find(loop.body, conditional("not found_min"))]
    exhausted.body.insert(-1, statement("_df_ms_exhausted(self)"))
    before_accept = find(loop.body, exact("self.current_attachment = new_attachment"))
    loop.body.insert(before_accept, statement(
        "_df_ms_check_objective(new_attachment, new_regularity)"))
    after_accept = find(loop.body, exact("self._set_parameters(self.current_parameters)"))
    loop.body.insert(after_accept + 1, statement("_df_ms_accept(self)"))
    tolerance = loop.body[find(loop.body, conditional(
        "math.fabs(delta_f_current) < self.convergence_tolerance * math.fabs(delta_f_initial)"))]
    call = _df_ms_ast.parse("_df_ms_tolerance(self, None)", mode="eval").body
    call.args[1] = tolerance.test
    tolerance.test = call
    callback = find(loop.body, conditional("self.callback is not None"))
    loop.body.insert(callback + 1, statement("if _df_ms_after_callback(self): break"))
    gradient = loop.body[find(loop.body, conditional(
        "not self.current_iteration == self.max_iterations"))]
    gradient.body.append(statement("_df_ms_check_gradient(gradient)"))

    if unlimited_iterations:
        expected_loop = _df_ms_ast.parse(
            "self.callback_ret and self.current_iteration < self.max_iterations", mode="eval").body
        if _df_ms_ast.dump(loop.test) != _df_ms_ast.dump(expected_loop):
            raise RuntimeError("Unsupported native GradientAscent iteration condition")
        # Keep the native callback and recompute gradients beyond the declared
        # initialization budget without replacing it with a large numeric cap.
        loop.test = _df_ms_ast.parse("self.callback_ret", mode="eval").body
        index = loop.body.index(gradient)
        loop.body[index:index + 1] = gradient.body

    carrier = _df_ms_ast.ClassDef(name="_df_UpdateCarrier", bases=[], keywords=[], body=[function],
                                 decorator_list=[])
    namespace = dict(original.__globals__)
    if reference is not None:
        namespace["_df_preserved_reference"] = _df_bind_reference(
            function, reference, require_saved)
    module = _df_ms_ast.fix_missing_locations(_df_ms_ast.Module(body=[carrier], type_ignores=[]))
    namespace.update({name: globals()[name] for name in (
        "_df_ms_initial", "_df_ms_check_objective", "_df_ms_accept", "_df_ms_tolerance",
        "_df_ms_after_callback", "_df_ms_check_gradient", "_df_ms_trial", "_df_ms_exhausted")})
    exec(compile(module, "<diffeoforge-morphospace-stop>", "exec"), namespace)
    code = namespace["_df_UpdateCarrier"].update.__code__
    if code.co_freevars != original.__code__.co_freevars:
        raise RuntimeError("Unsupported native update closure")
    replacement = _df_ms_types.FunctionType(code, namespace, original.__name__,
                                             original.__defaults__, original.__closure__)
    replacement.__kwdefaults__ = original.__kwdefaults__
    return replacement


def _df_ms_install_update(policy, labels, width, expected_sha256,
                          reference=None, require_saved=False):
    original = _df_ms_ga.update
    unlimited_iterations = policy.get("unlimited_iterations", False)
    replacement = _df_ms_rebind(original, expected_sha256, unlimited_iterations,
                                reference, require_saved)

    def update(estimator, *args, **kwargs):
        if getattr(estimator, "_df_individual_initialization", False):
            return original(estimator, *args, **kwargs)
        if tuple(estimator.dataset.subject_ids) != labels:
            raise RuntimeError("Atlas stopping policy subject identities differ from staged inputs")
        session = estimator._df_ms_session = _df_ms_Session(estimator, policy, labels, width)
        try:
            result = replacement(estimator, *args, **kwargs)
        except KeyboardInterrupt:
            session.finish("cancelled", "not_started")
            raise
        except (_df_ms_NumericalError, FloatingPointError, _df_ms_np.linalg.LinAlgError):
            session.finish("numerical_failure", "not_started")
            raise
        except Exception as error:
            native_gradient_failure = (
                isinstance(error, RuntimeError) and error.args
                and str(error.args[0]).startswith("Failure of the gradient_ascent algorithm:"))
            reason = "numerical_failure" if native_gradient_failure else "backend_failure"
            session.finish(reason, "not_started")
            raise
        reason = session.reason or (
            "iteration_limit" if not unlimited_iterations and (
                session.accepted >= estimator.max_iterations)
            else "optimizer_callback")
        session.finish(reason, "pending")
        return result

    _df_ms_ga.update = update


def _df_ms_install_export(estimator_type):
    original = estimator_type.write

    def write(estimator, *args, **kwargs):
        session = getattr(estimator, "_df_ms_session", None)
        if (session is None or session.terminal is None
                or getattr(estimator, "_df_updating", False)):
            return original(estimator, *args, **kwargs)
        try:
            result = original(estimator, *args, **kwargs)
            checkpoint_sha256 = _df_ms_digest(estimator.state_file)
            if checkpoint_sha256 != session.terminal["checkpoint_sha256"]:
                raise RuntimeError("Final native export changed the accepted checkpoint")
        except KeyboardInterrupt:
            session.terminal["reason"] = "cancelled"
            session.terminal["export"] = "failed"
            session.publish()
            raise
        except Exception:
            session.terminal["export"] = "failed"
            session.publish()
            raise
        session.terminal["export"] = "complete"
        session.publish()
        return result

    estimator_type.write = write
'''
