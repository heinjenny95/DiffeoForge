"""Explicit NEW regional-run finite accepted guard composition.

Historical prepared runs and ordinary atlas/PCA processes retain their exact
rendered bytes. Native finite objective/gradient/line-search values are untouched.
"""

import hashlib
import json

from diffeoforge.config import ConfigurationError
from diffeoforge.reference_guard_assets import C5_SOURCE, RUNTIME_PROFILE, RUNTIME_SOURCE

VERSION = "new-regional-c5-v1"
DECLARATION = {"version": VERSION, "scope": "new_single_specimen_probe", "recovery": "none"}
C5_SHA256 = "c5acaa4fa961d2f413978dd798d8576c9c89ec49e793d4700acd1e597196b58e"


def declaration(config):
    return config.get("project", {}).get("parameter_provenance", {}).get("finite_accepted_guard")


def mark_new_configuration(config):
    """Called only while writing a newly created candidate configuration."""
    from diffeoforge.regional_fit import declaration as regional
    from diffeoforge.regional_fit import read_plan

    provenance = config["project"].get("parameter_provenance", {})
    if not regional(config):
        provenance.pop("finite_accepted_guard", None)
        return
    plan = read_plan(config)
    if (
        plan["execution_scope"] != "single_specimen_probe"
        or config["optimization"]["method"] != "lbfgs"
        or not config["optimization"]["freeze_template"]
        or not config["optimization"]["freeze_control_points"]
    ):
        raise ConfigurationError("New regional guard requires frozen single-form L-BFGS")
    if not config["model"]["deformation"].get("initial_control_points"):
        raise ConfigurationError(
            "New guarded regional runs require explicit recoverable original control points"
        )
    provenance["finite_accepted_guard"] = dict(DECLARATION)


def extend_engine_files(config, subject_count, rendered):
    entry = declaration(config)
    if entry is None:
        return rendered
    from diffeoforge.regional_fit import read_plan

    if (
        entry != DECLARATION
        or subject_count != 1
        or read_plan(config) is None
        or config["optimization"]["method"] != "lbfgs"
        or not config["optimization"]["freeze_template"]
        or not config["optimization"]["freeze_control_points"]
    ):
        raise ConfigurationError("Invalid explicitly guarded regional run")
    if not config["model"]["deformation"].get("initial_control_points"):
        raise ConfigurationError("Guard requires explicit recoverable original control points")
    if hashlib.sha256(C5_SOURCE).hexdigest() != C5_SHA256:
        raise ConfigurationError("Packaged qualified C5 source differs")
    result = dict(rendered)
    body = result.get("sitecustomize.py", b"").decode("utf-8")
    if "_df_message_compat" not in body or "_df_minimize" not in body:
        raise ConfigurationError("Guard requires the existing message compatibility adapter")
    result["finite_accepted_guard.py"] = C5_SOURCE
    result["regional_guard_runtime.py"] = RUNTIME_SOURCE
    policy = {
        "version": VERSION,
        "scope": dict(DECLARATION),
        "initializer": (
            "staged_momenta"
            if config["model"]["deformation"].get("initial_momenta")
            else "native_zero"
        ),
        "modules": {
            name: hashlib.sha256(result[name]).hexdigest()
            for name in ("finite_accepted_guard.py", "regional_guard_runtime.py")
        },
        "runtime": RUNTIME_PROFILE,
    }
    result["guard-policy.json"] = (
        json.dumps(policy, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode()
    body += "\nfrom pathlib import Path as _df_guard_Path\n"
    body += "import finite_accepted_guard as _df_guard\n"
    body += "from regional_guard_runtime import install as _df_guard_install\n"
    body += (
        "_df_guard_context = _df_guard_install(_df_guard_Path(__file__).resolve().parent, "
        "_df_guard, compatible_minimize=_df_message_compat, raw_minimize=_df_minimize)\n"
    )
    result["sitecustomize.py"] = (
        '"""New regional finite accepted guard v1; fail-closed setup."""\ntry:\n'
        + "\n".join("    " + line for line in body.splitlines())
        + "\nexcept BaseException:\n    import os, sys, traceback\n"
        "    try:\n        traceback.print_exc()\n        sys.stderr.flush()\n"
        "    finally:\n        os._exit(1)\n"
    ).encode()
    return result


def reject_guarded_resume(config):
    if declaration(config) is not None:
        raise ConfigurationError(
            "A guarded regional trial has no automatic restore/resume contract. "
            "Its immutable best accepted parameters remain saved; a separately "
            "authorized NEW trial can explicitly use that state without claiming "
            "restored SciPy Hessian or line-search memory."
        )
