"""Read-only evidence and direct inspection actions after unsuccessful hypotheses."""

from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout

from diffeoforge.desktop.info_disclosure import InfoDisclosure
from diffeoforge.pilot_recovery import DESCRIPTIONS


def button(layout, text, callback):
    control = QPushButton(text)
    control.setStyleSheet("QPushButton { border: 1px solid #789994; "
                         "border-radius: 4px; padding: 8px; }")
    control.clicked.connect(callback)
    layout.addWidget(control)
    return control


def render(window, snapshot, identifier, layout, guidance):
    data = guidance.get("feedback", {}).get(identifier) or {}
    reference = data.get("selected")
    if not reference:
        return None
    rows = [r for r in guidance["cases"] if r["target"] == reference["target"]
            and r["method"] == reference["method"]]
    panel = QFrame()
    body = QVBoxLayout(panel)
    text = QLabel("Saved attempts on this form. Numerical convergence and visual suitability "
                  "are separate; marked-area measurements do not identify a unique cause.")
    text.setWordWrap(True)
    body.addWidget(text)
    measured = {r['fit']['directory']: r for r in
                next(iter(guidance.get('proposals', {}).get(identifier, {}).values()), {}).get(
                    'response_evidence', [])}
    for row in rows:
        title = DESCRIPTIONS.get(row.get("goal"), ("Starting fit", ""))[0]
        stop = {"tolerance_threshold": "numerical tolerance reached",
                "maximum_iterations": "iteration limit reached"}.get(row.get("stop"),
                                                                        "stop unconfirmed")
        outcome = row.get("outcome") or ("suitable" if row.get("approval") else "not reviewed")
        text = QLabel(f"{title} · {outcome} · {stop} · {row['control_count']} control points"
                      + (" · local or whole-shape regression flagged" if "regression" in
                         row.get("region_outcomes", [])
                         else ""))
        text.setWordWrap(True)
        body.addWidget(text)
        response = measured.get((row.get('fit') or {}).get('directory'))
        if response:
            status = {'improved': 'lower distances; visual review still required',
                      'unchanged': 'no reliable distance reduction',
                      'worse': 'distances increased',
                      'tradeoff': 'some errors reduced, others increased'}[response['status']]
            label = QLabel('On your current marked areas: ' + status
                           + ('; whole-shape regression' if response['global_worse'] else ''))
            label.setWordWrap(True)
            body.addWidget(label)
        if row.get("fit"):
            button(body, "Inspect this saved attempt",
                   lambda _checked=False, ref=row["fit"]: window._open_guided_saved_fit(ref))
    button(body, "Inspect retained starting fit",
           lambda: window._open_guided_saved_fit(reference))
    button(body, "Inspect original template alignment — no fit",
           lambda: inspect_inputs(window, reference))
    help_text = QLabel("In the input view, check orientation and whether the template can "
                       "represent the relevant features. If inputs need correction, close the "
                       "pilot and correct landmarks or choose a template in Step 1. Existing "
                       "results remain saved. Another fit always needs your explicit Run.")
    help_text.setWordWrap(True)
    body.addWidget(help_text)
    disclosure = InfoDisclosure("Saved attempts and input checks", panel)
    layout.addWidget(disclosure)
    return disclosure


def inspect_inputs(window, reference):
    if window._worker or window._view_loading or window._view_closed or window._review_saving:
        return
    origin = window.study_directory

    def prepare():
        from diffeoforge import reference_calibration_study as study
        from diffeoforge.guided_feedback import verify_reference

        with study.calibration_verification_scope():
            parent = verify_reference(reference)
            candidate = next(c for c in parent.candidates
                             if c.candidate_id == reference["candidate_id"])
            return _prepare_inputs(parent, candidate, reference["target"])

    window._viewer_preparation.request_operation(("guided-inputs", origin, reference), prepare)


def _prepare_inputs(snapshot, candidate, target_name):
    from diffeoforge import reference_calibration_study as study
    from diffeoforge.desktop.reference_calibration_dialog import CalibrationQcPair

    manifest = study._verify_manifest(snapshot.study_directory)
    target = next(r for r in manifest["inputs"]["subjects"] if r["filename"] == target_name)
    template = manifest["inputs"]["template"]
    pair = CalibrationQcPair("input-alignment", target_name,
        snapshot.study_directory / target["copy"],
        snapshot.study_directory / template["copy"], True,
        target["sha256"], template["sha256"])
    return snapshot, candidate, (pair,)


def inspect_template(window, identifier):
    """Open the exact staged template and target even when the preflight stopped Run."""
    if window._worker or window._view_loading or window._view_closed or window._review_saving:
        return
    origin = window.study_directory

    def prepare():
        from diffeoforge import reference_calibration_study as study
        from diffeoforge import reference_guided_pilot as guided

        with study.calibration_verification_scope():
            snapshot = study.load_reference_calibration_study(origin)
            candidate = next(c for c in snapshot.candidates if c.candidate_id == identifier)
            if candidate.status not in {"failed", "interrupted"}:
                raise ValueError("The failed attempt changed. Reopen the pilot result.")
            return _prepare_inputs(snapshot, candidate, guided.record(snapshot)["target"])

    window._viewer_preparation.request_operation(("guided-inputs", origin, identifier), prepare)
