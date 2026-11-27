"""Explicit helper-environment isolation for newly prepared bounded actions.

The parent has already imported its protected hooks before clearing its own
PYTHONPATH environment variable. Its existing sys.path, C5 observer, mathematical
operations and accepted fields are unchanged. Compiler/query Python children must
not initialize that same scientific run a second time.
"""

from diffeoforge.config import ConfigurationError

KEY = "python_child_isolation"
DECLARATION = {"version": "bounded-child-pythonpath-isolation-v1"}
SOURCE = (
    "\n# Protected parent hooks are installed; helper Python must not re-enter this run.\n"
    "import os as _df_child_environment\n"
    "_df_child_environment.environ.pop('PYTHONPATH', None)\n"
)


def declaration(config):
    provenance = config.get("project", {}).get("parameter_provenance", {})
    if KEY not in provenance:
        return None
    if provenance[KEY] != DECLARATION:
        raise ConfigurationError("Unsupported Python child-environment isolation declaration")
    return provenance[KEY]


def validate(config):
    """Unknown or nonregional explicit declarations fail closed before rendering."""
    if declaration(config) is None:
        return
    _regional_scope(config)


def _regional_scope(config):
    from diffeoforge.reference_finite_accepted_guard import DECLARATION as REGIONAL

    provenance = config["project"]["parameter_provenance"]
    if provenance.get("finite_accepted_guard") != REGIONAL or not provenance.get("regional_fit"):
        raise ConfigurationError(
            "Child-environment isolation requires a new guarded regional action"
        )


def mark(config, record):
    """Only new bounded candidate creation opts in; no stored run is changed."""
    from diffeoforge.pilot_adaptive_fit import VERSION

    declaration(config)
    provenance = config["project"]["parameter_provenance"]
    bounded = ((record.get("guided") or {}).get("strategy") or {}).get("adaptive_fit")
    if bounded is None:
        provenance.pop(KEY, None)
        return False
    if not isinstance(bounded, dict) or bounded.get("version") != VERSION:
        raise ConfigurationError("Only the declared bounded action may isolate helper Python")
    _regional_scope(config)
    provenance[KEY] = dict(DECLARATION)
    validate(config)
    return True


def after_parent_setup(config, body):
    """No declaration is an exact byte-preserving legacy render operation."""
    validate(config)
    return body if declaration(config) is None else body + SOURCE
