"""Protected, run-local output scheduling for the unchanged reference optimizer."""

from copy import deepcopy

COMPACT_MODE = "compact_final_export"
CONVERGENCE_MODE = "compact_convergence_export"


def new_run_config(config):
    """Declare the new output default without rewriting source/legacy evidence."""
    result = deepcopy(dict(config))
    result["output"].setdefault("checkpoint_mode", COMPACT_MODE)
    return result


def needs_adapter(config):
    return config.get("output", {}).get("checkpoint_mode") in {COMPACT_MODE, CONVERGENCE_MODE}


# Executed by the original Python 3.8 reference interpreter, not the desktop
# runtime. Only output methods are wrapped; no likelihood, gradient, update,
# line-search, integration, geometry or convergence equation is replaced.
SITECUSTOMIZE = '''
import logging as _df_logging
import os as _df_os
import tempfile as _df_tempfile
from deformetrica.core.estimators.gradient_ascent import GradientAscent as _df_ga
from deformetrica.core.model_tools.deformations.exponential import Exponential as _df_exp

_df_log = _df_logging.getLogger("diffeoforge.checkpoints")
_df_export_on_convergence = False

class _df_StopCapture(_df_logging.Handler):
    def __init__(self, estimator):
        super().__init__()
        self.estimator = estimator

    def emit(self, record):
        if record.name != "deformetrica.core.estimators.gradient_ascent":
            return
        message = record.getMessage()
        if message == "Tolerance threshold met. Stopping the optimization process.":
            self.estimator._df_native_stop = "tolerance_threshold"
        elif message == "Number of line search loops exceeded. Stopping.":
            self.estimator._df_native_stop = "line_search_exhausted"

def _df_install(estimator_type):
    original_update = estimator_type.update
    original_write = estimator_type.write
    original_dump = estimator_type._dump_state_file

    def atomic_dump(self, *args, **kwargs):
        original_state_file = self.state_file
        target = _df_os.path.abspath(original_state_file)
        parent = _df_os.path.dirname(target)
        fd, temporary = _df_tempfile.mkstemp(prefix=".df-checkpoint-", dir=parent)
        _df_os.close(fd)
        self.state_file = temporary
        try:
            original_dump(self, *args, **kwargs)
            with open(temporary, "r+b") as stream:
                _df_os.fsync(stream.fileno())
            _df_os.replace(temporary, target)
        finally:
            self.state_file = original_state_file
            if _df_os.path.exists(temporary):
                _df_os.unlink(temporary)

    def update(self, *args, **kwargs):
        self._df_updating = True
        self._df_native_stop = None
        capture = _df_StopCapture(self)
        logger = _df_logging.getLogger("deformetrica.core.estimators.gradient_ascent")
        if _df_export_on_convergence:
            logger.addHandler(capture)
        try:
            return original_update(self, *args, **kwargs)
        finally:
            if _df_export_on_convergence:
                logger.removeHandler(capture)
            self._df_updating = False

    def write(self, *args, **kwargs):
        # Persist first, including before the slow final flow export. The
        # original serializer retains its exact native resume semantics.
        self._dump_state_file()
        if getattr(self, "_df_updating", False):
            _df_log.info("DiffeoForge checkpoint saved at iteration %s; mesh export deferred",
                         self.current_iteration)
            return
        if (_df_export_on_convergence
                and getattr(self, "_df_native_stop", None) != "tolerance_threshold"):
            reason = getattr(self, "_df_native_stop", None) or (
                "maximum_iterations" if self.current_iteration >= self.max_iterations else "unknown"
            )
            _df_log.info("DiffeoForge final mesh export deferred: native stop %s; "
                         "checkpoint retained", reason)
            return
        model = self.statistical_model
        model.exponential._df_export_total = len(self.dataset.subject_ids)
        model.exponential._df_export_done = 0
        _df_log.info("DiffeoForge final mesh export started: %s specimens",
                     len(self.dataset.subject_ids))
        try:
            result = original_write(self, *args, **kwargs)
        finally:
            del model.exponential._df_export_total
        _df_log.info("DiffeoForge final mesh export completed")
        return result

    estimator_type._dump_state_file = atomic_dump
    estimator_type.update = update
    estimator_type.write = write

_df_install(_df_ga)
_df_original_flow = _df_exp.write_flow

def _df_flow(self, *args, **kwargs):
    result = _df_original_flow(self, *args, **kwargs)
    if hasattr(self, "_df_export_total"):
        self._df_export_done += 1
        _df_log.info("DiffeoForge final mesh export: specimen %s of %s",
                     self._df_export_done, self._df_export_total)
    return result

_df_exp.write_flow = _df_flow
'''


def render_adapter(singleton_source="", atlas_source="", *, convergence_only=False):
    """Fail closed if Python's normally nonfatal sitecustomize hook fails."""
    policy = "\n_df_export_on_convergence = True\n" if convergence_only else ""
    body = singleton_source + SITECUSTOMIZE + policy + atlas_source
    return (
        '"""DiffeoForge reference output scheduling adapter v1."""\n'
        "try:\n"
        + "\n".join("    " + line for line in body.splitlines())
        + "\nexcept BaseException:\n"
        "    import os, traceback\n"
        "    traceback.print_exc()\n"
        "    os._exit(1)\n"
    )
