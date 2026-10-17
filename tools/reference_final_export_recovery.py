"""Recover a failed final export without re-entering GradientAscent.

This support tool prepares an immutable, protected successor. The original
Deformetrica writer and every retained flow time point remain unchanged.
"""

from __future__ import annotations

import argparse
import json
import pickletools
import shutil
from pathlib import Path

from diffeoforge.config import ConfigurationError
from diffeoforge.mesh import sha256_file
from diffeoforge.runs import (
    ITERATION_RE,
    execute_run,
    inspect_resume_source,
    prepare_resume_run,
    verify_prepared_run,
)

RECORD_PATH = "resume/final-export-recovery.json"

# Runs inside the same reference interpreter. Fail closed: update cannot invoke
# an optimizer or gradient; the original writer still performs native shooting.
EXPORT_ADAPTER = r"""
try:
    import hashlib as _df_re_hash
    import json as _df_re_json
    import numpy as _df_re_np
    from pathlib import Path as _df_re_Path
    from deformetrica.core.estimators.gradient_ascent import GradientAscent as _df_re_ga

    _df_re_root = _df_re_Path(__file__).resolve().parent.parent
    _df_re_record_path = _df_re_root / "resume/final-export-recovery.json"
    _df_re_record = _df_re_json.loads(_df_re_record_path.read_text())
    if (_df_re_record["operation"] != "saved_state_final_export"
            or _df_re_record["schema_version"] != "0.1"):
        raise RuntimeError("Invalid saved-state export declaration")

    def _df_re_arrays(parameters):
        result = {}
        for name, value in sorted(parameters.items()):
            a = _df_re_np.asarray(value)
            if (not _df_re_np.issubdtype(a.dtype, _df_re_np.number)
                    or not _df_re_np.isfinite(a).all()):
                raise RuntimeError("Saved state contains nonfinite or nonnumeric parameters")
            result[name] = {"shape": list(a.shape), "dtype": str(a.dtype),
                            "sha256": _df_re_hash.sha256(a.tobytes(order="C")).hexdigest()}
        if not result:
            raise RuntimeError("Saved state has no parameters")
        return result

    def _df_re_update(self):
        if self.current_iteration != _df_re_record["checkpoint_iteration"]:
            raise RuntimeError("Saved-state iteration differs from protected declaration")
        checkpoint = _df_re_Path(self.state_file)
        actual_hash = _df_re_hash.sha256(checkpoint.read_bytes()).hexdigest()
        if actual_hash != _df_re_record["checkpoint_sha256"]:
            raise RuntimeError("Loaded checkpoint differs from protected source")
        self._df_re_before = _df_re_arrays(self.current_parameters)
        if _df_re_arrays(self._get_parameters()) != self._df_re_before:
            raise RuntimeError("Native restored model differs from saved parameters")
        self._df_re_update_calls = getattr(self, "_df_re_update_calls", 0) + 1
        if self._df_re_update_calls != 1:
            raise RuntimeError("Saved-state export was invoked twice")
        _df_log.info("DiffeoForge export-only recovery: restored iteration %s; "
                     "optimization skipped",
                     self.current_iteration)

    def _df_re_no_optimizer(*args, **kwargs):
        raise RuntimeError("Optimization/gradient evaluation forbidden during saved-state export")

    _df_re_original_write = _df_re_ga.write
    def _df_re_write(self, *args, **kwargs):
        if not hasattr(self, "_df_re_before"):
            raise RuntimeError("Saved-state export was not verified before writing")
        result = _df_re_original_write(self, *args, **kwargs)
        after = _df_re_arrays(self.current_parameters)
        if (after != self._df_re_before or _df_re_arrays(self._get_parameters()) != after
                or self.current_iteration != _df_re_record["checkpoint_iteration"]):
            raise RuntimeError("Saved-state parameters changed during final export")
        report = {"operation": "saved_state_final_export", "optimization_executed": False,
                  "checkpoint_iteration": self.current_iteration, "parameters_unchanged": True,
                  "parameter_arrays": after, "original_native_writer_used": True,
                  "all_flow_timepoints_retained": True}
        (_df_re_root / "output/final-export-state-verification.json").write_text(
            _df_re_json.dumps(report, indent=2) + "\n")
        return result

    _df_re_ga.update = _df_re_update
    _df_re_ga._evaluate_model_fit = _df_re_no_optimizer
    _df_re_ga.write = _df_re_write
except BaseException:
    import os as _df_re_os, traceback as _df_re_traceback
    _df_re_traceback.print_exc()
    _df_re_os._exit(1)
"""


def checkpoint_iteration(path: Path) -> int:
    """Inspect scalar pickle opcodes, never deserialize checkpoint objects."""
    data = path.read_bytes()
    found: list[int] = []
    waiting = False
    last = None
    last_position = None
    try:
        for opcode, argument, position in pickletools.genops(data):
            if argument == "current_iteration":
                if waiting:
                    raise ValueError("Ambiguous iteration key")
                waiting = True
            elif waiting and opcode.name in {
                "BININT",
                "BININT1",
                "BININT2",
                "INT",
                "LONG",
                "LONG1",
                "LONG4",
            }:
                found.append(argument)
                waiting = False
            elif waiting and opcode.name not in {"MEMOIZE", "PUT", "BINPUT", "LONG_BINPUT"}:
                raise ValueError("Iteration is not a literal integer")
            last, last_position = opcode.name, position
    except (ValueError, TypeError) as error:
        raise ConfigurationError("Checkpoint scalar opcodes are not readable") from error
    if len(found) != 1 or found[0] < 0 or last != "STOP" or last_position != len(data) - 1:
        raise ConfigurationError("Checkpoint has no unique, complete iteration scalar")
    return found[0]


def export_stop_evidence(source: Path, iteration: int, maximum: int) -> dict:
    matching = []
    for log in sorted((source / "output").glob("*_info.log")):
        if log.is_symlink():
            raise ConfigurationError("Native stop log must not be a symlink")
        text = log.read_text(encoding="utf-8", errors="replace")
        reason = next(
            (
                value
                for marker, value in (
                    (
                        "Tolerance threshold met. Stopping the optimization process.",
                        "native_tolerance",
                    ),
                    ("Maximum number of iterations reached", "iteration_limit"),
                )
                if marker in text
            ),
            None,
        )
        indices = [int(m.group(1)) for m in ITERATION_RE.finditer(text)]
        if (
            reason is None
            and indices
            and indices[-1] == iteration == maximum
            and "DiffeoForge final mesh export started" in text
            and "Number of line search loops exceeded" not in text
        ):
            reason = "iteration_limit"
        if reason and indices and indices[-1] <= iteration <= indices[-1] + 1:
            matching.append(
                {
                    "native_stop": reason,
                    "native_stop_log": log.relative_to(source).as_posix(),
                    "native_stop_log_sha256": sha256_file(log),
                }
            )
    if len(matching) != 1:
        raise ConfigurationError("No unique native optimizer stop precedes this checkpoint")
    return matching[0]


def required_export_space(source: Path, manifest: dict) -> int:
    """Reserve a complete new flow export, protected-input copies and 2 GiB."""
    flows = [
        p.stat().st_size for p in (source / "output").glob("*__flow__*.vtk") if not p.is_symlink()
    ]
    if not flows:
        raise ConfigurationError("No retained native flow file is available for export sizing")
    subjects = int(manifest["input_count"]["subjects"])
    points = int(manifest["effective_config"]["model"]["deformation"]["timepoints"])
    inputs = sum(p.stat().st_size for p in (source / "input").rglob("*") if p.is_file())
    # Observed native serialization, plus a ten-percent output planning margin.
    estimated = (max(flows) * (subjects * (points + 1) + 1) * 11 + 9) // 10
    return estimated + inputs + 2 * 1024**3


def prepare_final_export(source: Path, *, run_id: str) -> Path:
    evidence = inspect_resume_source(source)
    iteration = checkpoint_iteration(evidence.checkpoint_path)
    stop = export_stop_evidence(
        source,
        iteration,
        int(evidence.manifest["effective_config"]["optimization"]["max_iterations"]),
    )
    required = required_export_space(source, evidence.manifest)
    available = shutil.disk_usage(source.parent).free
    if available < required:
        raise ConfigurationError(
            f"Final export needs {required} free bytes; only {available} available"
        )
    successor = prepare_resume_run(source, run_id=run_id)
    manifest = dict(verify_prepared_run(successor))
    declaration = {
        "schema_version": "0.1",
        "operation": "saved_state_final_export",
        "source_run_id": source.name,
        "source_run_path": str(source.resolve()),
        "source_manifest_sha256": sha256_file(source / "manifest.json"),
        "source_result_sha256": sha256_file(source / "result.json"),
        "checkpoint_iteration": iteration,
        "checkpoint_sha256": evidence.checkpoint_sha256,
        "required_free_bytes_before_preparation": required,
        "support_tool_sha256": sha256_file(Path(__file__)),
        **stop,
    }
    record = successor / RECORD_PATH
    record.write_text(json.dumps(declaration, indent=2) + "\n", encoding="utf-8")
    adapter = successor / "engine/sitecustomize.py"
    if not adapter.is_file():
        raise ConfigurationError("A protected compact-checkpoint adapter is required")
    with adapter.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(EXPORT_ADAPTER)
    artifacts = list(manifest["protected_artifacts"])
    for artifact in artifacts:
        if artifact["path"] == "engine/sitecustomize.py":
            artifact.update(bytes=adapter.stat().st_size, sha256=sha256_file(adapter))
    artifacts.append(
        {"path": RECORD_PATH, "bytes": record.stat().st_size, "sha256": sha256_file(record)}
    )
    manifest["protected_artifacts"] = artifacts
    path = successor / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (successor / "manifest.sha256").write_text(sha256_file(path) + "\n", encoding="ascii")
    verify_prepared_run(successor)
    return successor


def execute_final_export(successor: Path) -> int:
    manifest = verify_prepared_run(successor)
    record = json.loads((successor / RECORD_PATH).read_text(encoding="utf-8"))
    if not any(a["path"] == RECORD_PATH for a in manifest["protected_artifacts"]):
        raise ConfigurationError("Final export declaration is not protected")
    source = Path(record["source_run_path"])
    for relative, key in (
        ("manifest.json", "source_manifest_sha256"),
        ("result.json", "source_result_sha256"),
        ("output/deformetrica-state.p", "checkpoint_sha256"),
        (record["native_stop_log"], "native_stop_log_sha256"),
    ):
        if sha256_file(source / relative) != record[key]:
            raise ConfigurationError("Source evidence changed before final export")
    if shutil.disk_usage(successor).free < required_export_space(source, manifest) - sum(
        p.stat().st_size for p in (source / "input").rglob("*") if p.is_file()
    ):
        raise ConfigurationError("Available storage fell below the final export reserve")
    return_code = execute_run(successor)
    if return_code == 0:
        report = json.loads((successor / "output/final-export-state-verification.json").read_text())
        if (
            report.get("optimization_executed") is not False
            or report.get("parameters_unchanged") is not True
            or report.get("checkpoint_iteration") != record["checkpoint_iteration"]
        ):
            raise ConfigurationError("Final export lacks unchanged-state postconditions")
    return return_code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--execute", action="store_true", help="Explicitly execute the export after preparation"
    )
    args = parser.parse_args()
    successor = prepare_final_export(args.source.resolve(), run_id=args.run_id)
    print(
        json.dumps({"prepared_successor": str(successor), "operation": "saved_state_final_export"}),
        flush=True,
    )
    return execute_final_export(successor) if args.execute else 0


if __name__ == "__main__":
    raise SystemExit(main())
