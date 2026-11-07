"""Explicit NEW full-target singleton scope for the qualified native C5 observer.

This does not enable a new solver or rewrite the historical regional runtime.
The native L-BFGS objective, gradient, update and finite-state observer are reused.
Joint atlases, regional objectives, timed review and automatic recovery are excluded.
"""

import hashlib
import json

from diffeoforge.config import ConfigurationError
from diffeoforge.reference_guard_assets import C5_SOURCE, RUNTIME_PROFILE, RUNTIME_SOURCE

VERSION = "new-ordinary-c5-v1"
DECLARATION = {"version": VERSION, "scope": "new_full_target_singleton", "recovery": "none"}
SCOPE = {
    "version": "ordinary-full-target-v1",
    "execution_scope": "single_specimen_probe",
    "fit_scope": "full_original_target",
    "attachment": "varifold",
    "optimizer_history_restored": False,
}

# A single static scope validator is compiled for host preparation and included
# verbatim in the native Python 3.8 asset. No source is read from a run or config.
_SCOPE_VALIDATOR = """def require_scope(config, ordinary_plan, input_count):
    provenance = config.get('project', {}).get('parameter_provenance', {})
    if provenance.get('finite_accepted_guard') != DECLARATION:
        raise ValueError('Missing explicit NEW full-target singleton declaration')
    if any(k in provenance for k in (
            'regional_fit', 'regional_conditioning', 'pilot_review', 'surface_gather')):
        raise ValueError('Ordinary scope cannot inherit regional/review/indexing runtime')
    if ordinary_plan != SCOPE:
        raise ValueError('Full-target objective declaration differs')
    if input_count != {'templates': 1, 'subjects': 1}:
        raise ValueError('Ordinary guard requires one template and one original target')
    o = config['optimization']
    if o['method'] != 'lbfgs' or not o['freeze_template'] or not o['freeze_control_points']:
        raise ValueError('Ordinary guard requires native frozen single-form L-BFGS')
    model = config['model']
    if (model['attachment']['type'] != 'varifold'
            or not model['deformation'].get('initial_control_points')):
        raise ValueError('Ordinary guard requires varifold and explicit original controls')
    if config.get('output', {}).get('checkpoint_mode') == 'compact_convergence_export':
        raise ValueError('Convergence-only cohort scheduling is outside this scope')
    if config.get('runtime', {}).get('precision') != 'float32':
        raise ValueError('Ordinary scope requires the qualified Float32 runtime')
    scope = provenance.get('recommendation', {}).get('calibration_plan', {}).get('execution_scope')
    if scope != 'single_specimen_probe':
        raise ValueError('An explicit singleton probe plan is required')
"""
_HOST = {"DECLARATION": DECLARATION, "SCOPE": SCOPE}
exec(compile(_SCOPE_VALIDATOR, "<ordinary-scope>", "exec"), _HOST)


def validate(config, subject_count=1):
    """Validate the explicit scope before rendering or staging any native asset."""
    try:
        _HOST["require_scope"](config, SCOPE, {"templates": 1, "subjects": subject_count})
    except (KeyError, TypeError, ValueError) as error:
        raise ConfigurationError(str(error)) from error


def mark(config):
    """Opt in only while creating a new full-target configuration, never by inference."""
    provenance = config["project"]["parameter_provenance"]
    previous = provenance.get("finite_accepted_guard")
    if previous is not None and previous != DECLARATION:
        raise ConfigurationError("Cannot replace an existing guard scope implicitly")
    provenance["finite_accepted_guard"] = dict(DECLARATION)
    try:
        validate(config)
    except BaseException:
        if previous is None:
            provenance.pop("finite_accepted_guard")
        raise


def runtime_source():
    """Preserve the qualified shared observer; replace only its objective scope."""
    text = RUNTIME_SOURCE.decode("utf-8")
    changes = {
        "VERSION = 'new-regional-c5-v1'": "VERSION = " + repr(VERSION),
        "'scope': 'new_single_specimen_probe'": "'scope': 'new_full_target_singleton'",
        "regional_guard_runtime.py": "ordinary_guard_runtime.py",
        "input/regional/plan.json": "engine/ordinary-scope.json",
        "_df_regional_c5_installed": "_df_ordinary_c5_installed",
    }
    for before, after in changes.items():
        if before not in text:
            raise ConfigurationError("Qualified guard scope template changed")
        text = text.replace(before, after)
    start = text.index("def require_scope(")
    end = text.index("\n\nclass ManifestContext:", start)
    text = text[:start] + "SCOPE = " + repr(SCOPE) + "\n\n" + _SCOPE_VALIDATOR + text[end:]
    needle = (
        "        opt = ET.fromstring((self.engine / 'optimization_parameters.xml').read_bytes())\n"
    )
    if text.count(needle) != 1:
        raise ConfigurationError("Qualified guard XML scope template changed")
    text = text.replace(
        needle,
        needle
        + """        objects = model.findall('template/object')
        if (len(objects) != 1 or objects[0].findtext('deformable-object-type') != 'SurfaceMesh'
                or objects[0].findtext('attachment-type') != 'varifold'):
            raise ValueError('Ordinary XML requires one full surface-varifold object')
""",
    )
    compile(text, "ordinary_guard_runtime.py", "exec")
    return text.encode("utf-8")


def extend_engine_files(config, subject_count, rendered):
    validate(config, subject_count)
    from diffeoforge.reference_finite_accepted_guard import C5_SHA256

    if hashlib.sha256(C5_SOURCE).hexdigest() != C5_SHA256:
        raise ConfigurationError("Packaged qualified C5 observer changed")
    result = dict(rendered)
    body = result.get("sitecustomize.py", b"").decode("utf-8")
    if "_df_message_compat" not in body or "_df_minimize" not in body:
        raise ConfigurationError("Ordinary guard requires the existing SciPy message adapter")
    result["finite_accepted_guard.py"] = C5_SOURCE
    result["ordinary_guard_runtime.py"] = runtime_source()
    result["ordinary-scope.json"] = (json.dumps(SCOPE, sort_keys=True) + "\n").encode()
    policy = dict(
        version=VERSION,
        scope=dict(DECLARATION),
        initializer="staged_momenta"
        if config["model"]["deformation"].get("initial_momenta")
        else "native_zero",
        modules={
            name: hashlib.sha256(result[name]).hexdigest()
            for name in ("finite_accepted_guard.py", "ordinary_guard_runtime.py")
        },
        runtime=RUNTIME_PROFILE,
    )
    result["guard-policy.json"] = (
        json.dumps(policy, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode()
    body += "\nfrom pathlib import Path as _df_guard_Path\n"
    body += "import finite_accepted_guard as _df_guard\n"
    body += "from ordinary_guard_runtime import install as _df_guard_install\n"
    body += (
        "_df_guard_context = _df_guard_install(_df_guard_Path(__file__).resolve().parent, "
        "_df_guard, compatible_minimize=_df_message_compat, raw_minimize=_df_minimize)\n"
    )
    result["sitecustomize.py"] = (
        '"""New full-target finite accepted guard; fail-closed setup."""\ntry:\n'
        + "\n".join("    " + line for line in body.splitlines())
        + "\nexcept BaseException:\n    import os, sys, traceback\n"
        "    try:\n        traceback.print_exc()\n        sys.stderr.flush()\n"
        "    finally:\n        os._exit(1)\n"
    ).encode()
    return result
