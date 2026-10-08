"""Protected, run-local output scheduling for the unchanged reference optimizer."""

from copy import deepcopy

COMPACT_MODE = "compact_final_export"


def new_run_config(config):
    """Declare the new output default without rewriting source/legacy evidence."""
    result = deepcopy(dict(config))
    result["output"].setdefault("checkpoint_mode", COMPACT_MODE)
    return result


def needs_adapter(config):
    return config.get("output", {}).get("checkpoint_mode") == COMPACT_MODE


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
        try:
            return original_update(self, *args, **kwargs)
        finally:
            self._df_updating = False

    def write(self, *args, **kwargs):
        # Persist first, including before the slow final flow export. The
        # original serializer retains its exact native resume semantics.
        self._dump_state_file()
        if getattr(self, "_df_updating", False):
            _df_log.info("DiffeoForge checkpoint saved at iteration %s; mesh export deferred",
                         self.current_iteration)
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


def render_adapter(singleton_source="", atlas_source=""):
    """Fail closed if Python's normally nonfatal sitecustomize hook fails."""
    body = singleton_source + SITECUSTOMIZE + atlas_source
    return (
        '"""DiffeoForge reference output scheduling adapter v1."""\n'
        "try:\n"
        + "\n".join("    " + line for line in body.splitlines())
        + "\nexcept BaseException:\n"
        "    import os, traceback\n"
        "    traceback.print_exc()\n"
        "    os._exit(1)\n"
    )
