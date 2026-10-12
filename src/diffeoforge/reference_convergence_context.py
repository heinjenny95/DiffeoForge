"""Opt-in continuity of the native objective reference across immutable resumes."""

import math
import re

CHECKPOINT_KEY = "diffeoforge_convergence_reference"
# Audited, dedented GradientAscent.update from the supported reference runtime.
UPDATE_SHA256 = "4a4a368201436a40f4e4977d14763830be01345f4ba43a9c61c00b61db705aab"


def validate_context(context, tolerance):
    expected = {
        "version", "initial_log_likelihood", "origin_iteration",
        "origin_checkpoint_sha256", "convergence_tolerance",
    }
    if not isinstance(context, dict) or set(context) != expected:
        raise ValueError("Invalid convergence reference fields.")
    if type(context["version"]) is not int or context["version"] != 1:
        raise ValueError("Unsupported convergence reference version.")
    if type(context["origin_iteration"]) is not int or context["origin_iteration"] < 0:
        raise ValueError("Invalid convergence reference origin iteration.")
    for key in ("initial_log_likelihood", "convergence_tolerance"):
        if type(context[key]) not in (int, float) or not math.isfinite(context[key]):
            raise ValueError("Convergence reference values must be finite numbers.")
    if context["convergence_tolerance"] <= 0 or context["convergence_tolerance"] != tolerance:
        raise ValueError("Convergence reference tolerance differs from the run.")
    if not isinstance(context["origin_checkpoint_sha256"], str) or not re.fullmatch(
        "[0-9a-f]{64}", context["origin_checkpoint_sha256"]
    ):
        raise ValueError("Invalid convergence reference checkpoint hash.")
    return dict(context)


# Standalone Python 3.8 code. The objective equation, stopping comparator,
# gradient and line search are retained verbatim. Only the two initial objective
# assignments are adapted: the reference persists; the last objective stays local.
ADAPTER_SOURCE = '''
import ast as _df_ast
import hashlib as _df_hashlib
import inspect as _df_inspect
import math as _df_math
import pickle as _df_pickle
import re as _df_re
import textwrap as _df_textwrap
import types as _df_types
from deformetrica.core.estimators.gradient_ascent import GradientAscent as _df_reference_ga

_df_reference_key = "diffeoforge_convergence_reference"

def _df_validate_reference(context, tolerance, iteration):
    fields = {"version", "initial_log_likelihood", "origin_iteration",
              "origin_checkpoint_sha256", "convergence_tolerance"}
    if not isinstance(context, dict) or set(context) != fields:
        raise RuntimeError("Invalid convergence reference fields")
    if type(context["version"]) is not int or context["version"] != 1:
        raise RuntimeError("Unsupported convergence reference version")
    origin = context["origin_iteration"]
    if type(origin) is not int or not 0 <= origin <= iteration:
        raise RuntimeError("Invalid convergence reference origin iteration")
    for key in ("initial_log_likelihood", "convergence_tolerance"):
        if type(context[key]) not in (int, float) or not _df_math.isfinite(context[key]):
            raise RuntimeError("Nonfinite convergence reference")
    if context["convergence_tolerance"] <= 0 or context["convergence_tolerance"] != tolerance:
        raise RuntimeError("Convergence reference tolerance differs from the run")
    digest = context["origin_checkpoint_sha256"]
    if not isinstance(digest, str) or not _df_re.fullmatch("[0-9a-f]{64}", digest):
        raise RuntimeError("Invalid convergence reference checkpoint hash")
    return dict(context)

def _df_rebind_reference_update(original, expected_sha256, bootstrap, require_saved):
    source = _df_textwrap.dedent(_df_inspect.getsource(original))
    if _df_hashlib.sha256(source.encode("utf-8")).hexdigest() != expected_sha256:
        raise RuntimeError("Unsupported native GradientAscent.update source")
    tree = _df_ast.parse(source)
    function = tree.body[0]
    initial = [node for node in function.body if isinstance(node, _df_ast.Assign)
               and len(node.targets) == 1 and isinstance(node.targets[0], _df_ast.Name)
               and node.targets[0].id == "initial_log_likelihood"]
    last = [node for node in function.body if isinstance(node, _df_ast.Assign)
            and len(node.targets) == 1 and isinstance(node.targets[0], _df_ast.Name)
            and node.targets[0].id == "last_log_likelihood"]
    if (len(initial) != 1 or len(last) != 1
            or _df_ast.dump(initial[0].value) != _df_ast.dump(
                _df_ast.parse("self.current_log_likelihood", mode="eval").body)
            or _df_ast.dump(last[0].value) != _df_ast.dump(
                _df_ast.parse("initial_log_likelihood", mode="eval").body)):
        raise RuntimeError("Unsupported native reference initialization")

    def reference(self, current):
        if not _df_math.isfinite(float(current)):
            raise RuntimeError("Nonfinite current objective")
        with open(self.state_file, "rb") as stream:
            saved = _df_pickle.load(stream)
        if not isinstance(saved, dict) or saved.get("current_iteration") != self.current_iteration:
            raise RuntimeError("Convergence reference checkpoint iteration differs")
        context = saved.get(_df_reference_key)
        if context is None:
            if require_saved:
                raise RuntimeError("Checkpoint lost its convergence reference")
            context = bootstrap
        context = _df_validate_reference(
            context, self.convergence_tolerance, self.current_iteration)
        if context != bootstrap:
            raise RuntimeError("Checkpoint and protected convergence reference disagree")
        self._df_convergence_reference = context
        value = type(current)(context["initial_log_likelihood"])
        if float(value) != context["initial_log_likelihood"]:
            raise RuntimeError("Convergence reference cannot retain native objective precision")
        return value

    initial[0].value = _df_ast.parse(
        "_df_preserved_reference(self, self.current_log_likelihood)", mode="eval").body
    # The first line search must compare with the resumed current objective,
    # never with the older convergence reference.
    last[0].value = _df_ast.parse("self.current_log_likelihood", mode="eval").body
    carrier = _df_ast.ClassDef(name="_df_UpdateCarrier", bases=[], keywords=[],
                              body=[function], decorator_list=[])
    module = _df_ast.fix_missing_locations(_df_ast.Module(body=[carrier], type_ignores=[]))
    namespace = dict(original.__globals__)
    namespace["_df_preserved_reference"] = reference
    exec(compile(module, "<diffeoforge-convergence-reference>", "exec"), namespace)
    code = namespace["_df_UpdateCarrier"].update.__code__
    if code.co_freevars != original.__code__.co_freevars:
        raise RuntimeError("Unsupported native update closure")
    replacement = _df_types.FunctionType(code, namespace, original.__name__,
                                         original.__defaults__, original.__closure__)
    replacement.__kwdefaults__ = original.__kwdefaults__
    return replacement

def _df_install_reference(context, expected_sha256, require_saved):
    original_dump = _df_reference_ga._dump_state_file
    replacement = _df_rebind_reference_update(
        _df_reference_ga.update, expected_sha256, context, require_saved)

    def dump(self, *args, **kwargs):
        original_dump(self, *args, **kwargs)
        context = getattr(self, "_df_convergence_reference", None)
        if context is not None:
            # The outer scheduling adapter writes this bundle to a temporary
            # file, fsyncs it and replaces the checkpoint atomically.
            with open(self.state_file, "rb") as stream:
                state = _df_pickle.load(stream)
            state[_df_reference_key] = _df_validate_reference(
                context, self.convergence_tolerance, self.current_iteration)
            with open(self.state_file, "wb") as stream:
                _df_pickle.dump(state, stream, protocol=_df_pickle.HIGHEST_PROTOCOL)

    _df_reference_ga.update = replacement
    _df_reference_ga._dump_state_file = dump
'''


def adapter_source(context, *, require_saved=False):
    validated = validate_context(context, context.get("convergence_tolerance"))
    return ADAPTER_SOURCE + (
        f"\n_df_install_reference({validated!r}, {UPDATE_SHA256!r}, {require_saved!r})\n"
    )
