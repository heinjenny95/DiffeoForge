"""Read sealed terminal guard metadata without restoring a failed field."""

import json
import re
from pathlib import Path

from diffeoforge.mesh import sha256_file


def read_failure(directory):
    """Return a verified C5 stop, or None for a different kind of failure."""
    from diffeoforge import runs
    from diffeoforge.reference_finite_accepted_guard import DECLARATION

    run = Path(directory).resolve(strict=True)
    if not (run / "manifest.json").is_file():
        if (run / "output/numerical-guard").exists():
            raise ValueError("Guard failure has no manifest")
        return None
    manifest = runs._read_manifest(run)
    provenance = manifest["effective_config"]["project"].get("parameter_provenance", {})
    if provenance.get("finite_accepted_guard") != DECLARATION:
        return None
    runs._verify_protected_artifacts(run, manifest)
    result = runs._read_json_object(run / "result.json", "Failed result")
    if result.get("status") != "failed":
        return None
    control = runs._control_receipt(
        run, (run / "logs/backend-control-token").read_text(encoding="ascii")
    )
    if (result.get("run_id") != manifest["run_id"]
            or type(result.get("return_code")) is not int or result["return_code"] == 0
            or control.get("state") != "completed"
            or control.get("backend_return_code") != result["return_code"]):
        raise ValueError("Guard failure has no matching terminal result")
    _path, inventory = runs._read_output_inventory(run, result)
    names = ("numerical-guard/violation.json", "numerical-guard/events.jsonl")
    violation = run / "output" / names[0]
    records = {name: [r for r in inventory["files"] if r.get("path") == name]
               for name in names}
    if not records[names[0]] and not violation.exists():
        return None
    for name in names:
        path = runs._resolve_run_artifact(run, "output/" + name, "Guard failure")
        rows = records[name]
        if (len(rows) != 1 or path.stat().st_size != rows[0]["bytes"]
                or sha256_file(path) != rows[0]["sha256"]):
            raise ValueError("Guard failure metadata changed")
    if violation.stat().st_size > 1024 * 1024:
        raise ValueError("Guard failure metadata is oversized")
    data = json.loads(violation.read_text(encoding="utf-8"))
    with (run / "output" / names[1]).open("rb") as stream:
        stream.seek(max(0, stream.seek(0, 2) - 65536))
        terminal = json.loads(stream.read().splitlines()[-1])
    reason = data.get("reason")
    if (not isinstance(reason, str) or not re.fullmatch(r"[A-Za-z0-9_]{1,160}", reason)
            or data.get("automatic_restore") is not False
            or terminal.get("kind") != "terminal_violation"
            or terminal.get("reason") != reason):
        raise ValueError("Guard failure has inconsistent terminal metadata")
    details = data.get("details", {})
    if not isinstance(details, dict) or any(terminal.get(k) != v for k, v in details.items()):
        raise ValueError("Guard failure details disagree with the terminal event")
    message = (
        "Numerical consistency check stopped this trial: identical parameters produced "
        "different objective or gradient values. Inspect the retained earlier fit. "
        "Repeating this test or adding iterations does not resolve this inconsistency."
        if reason == "inconsistent_FG_for_identical_parameters" else
        "The numerical safety check stopped this trial. Inspect the retained earlier "
        "fit and failure details before preparing a different test."
    )
    return dict(reason=reason, message=message, verified=True, block_retry=True)


def for_candidate(candidate):
    """Fresh dispatch guard; presentation callers run this outside the Qt loop."""
    from diffeoforge.reference_calibration_study import calibration_candidate_run_directory

    if candidate.status != "failed" or not candidate.run_directory:
        return None
    try:
        return read_failure(calibration_candidate_run_directory(candidate))
    except (OSError, ValueError, RuntimeError, KeyError, IndexError, TypeError):
        return dict(reason="unverified_guard_failure", verified=False, block_retry=True,
                    message="Failed-run evidence could not be verified. Inspect the retained "
                    "earlier fit and failure details before starting another test.")
