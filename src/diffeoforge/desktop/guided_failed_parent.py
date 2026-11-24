"""A numerical failure does not hide the trusted fit or imply an optimizer restore."""

from PySide6.QtWidgets import QComboBox, QLabel, QPushButton


def render(window, snapshot, candidate, layout, guidance, action):
    from diffeoforge.desktop.reference_calibration_dialog import _set_action_emphasis
    from diffeoforge.pilot_regions import SYMPTOMS

    identifier = candidate.candidate_id
    evidence = guidance.get("failed_parents", {}).get(identifier) or {}
    reference = evidence.get("reference")
    if not reference:
        return
    if identifier not in guidance.get("guard_failures", {}):
        note = QLabel(evidence["reason"])
        note.setWordWrap(True)
        layout.addWidget(note)
    label = evidence["parent_label"]
    areas = ", ".join(evidence["area_labels"])
    inspect = QPushButton(
        f"Inspect retained fit · {label}" + (f" · marked areas {areas}" if areas else ""))
    _set_action_emphasis(inspect, False)
    inspect.clicked.connect(lambda: window._open_guided_saved_fit(reference, failed_for=identifier))
    layout.addWidget(inspect)
    if not evidence.get("available"):
        return
    proposals = guidance.get("failed_proposals", {}).get(identifier) or {}
    if not any(proposal.get("available") for proposal in proposals.values()):
        reason = evidence.get("adjustment_error") or next(
            (p["blocked_reason"] for p in proposals.values() if p.get("blocked_reason")), "")
        note = QLabel("No different test is available from this fit. " + reason)
        note.setWordWrap(True)
        layout.addWidget(note)
        return
    selector = QComboBox()
    selector.addItem("Choose a different test from the retained fit…", None)
    for request, proposal in proposals.items():
        if proposal.get("available"):
            label = proposal["title"]
            if request.startswith("regional:"):
                label += " · " + SYMPTOMS[request.split(":", 1)[1]]
            selector.addItem(label, request)
    layout.addWidget(selector)
    reason = QLabel(
        "Preparing creates a new test only. Run it separately after reviewing the plan."
    )
    reason.setWordWrap(True)
    layout.addWidget(reason)
    prepare = action(
        layout,
        "Prepare different test from retained fit",
        "recover_from_retained",
        identifier,
        available=False,
    )
    # Keep the disabled control visible: the explicit choice, not a hidden action, is missing.
    prepare.show()
    prepare.setEnabled(False)
    _set_action_emphasis(prepare, False)

    def ready():
        request = selector.currentData()
        proposal = proposals.get(request)
        return bool(
            proposal
            and proposal.get("available")
            and window._worker is None
            and not window._restoring_search
            and all(c.status in {"completed", "failed", "interrupted"} for c in snapshot.candidates)
        )

    def changed():
        request = selector.currentData()
        proposal = proposals.get(request)
        prepare.setEnabled(ready())
        reason.setText(
            proposal["reason"]
            if proposal
            else "Choose a different adjustment. The failed field is never restored."
        )

    def selected_prepare():
        from diffeoforge.guided_failed_parent import selection

        if ready():
            request = selector.currentData()
            window._start_pilot(
                adaptive=False,
                guided_action=(
                    "adaptive_recover_from_retained",
                    identifier,
                    selection(request, proposals[request]),
                ),
            )

    # The generic closure has goal=None; this explicit action binds the selected request.
    prepare.clicked.disconnect()
    prepare.clicked.connect(selected_prepare)
    selector.currentIndexChanged.connect(changed)


def inspection(snapshot, identifier, reference, pairs):
    """Load only verified mark positions on the saved parent the user opened."""
    from dataclasses import replace

    from diffeoforge.desktop.region_marking_geometry import load_region_marking_mesh
    from diffeoforge.guided_failed_parent import resolve
    from diffeoforge.pilot_region_scope import label
    from diffeoforge.reference_guided_pilot import record

    parent, evidence = resolve(snapshot, identifier, terminal=False)
    if evidence["reference"] != reference:
        raise ValueError("The retained starting fit changed. Reopen the saved pilot.")
    candidate = next(c for c in parent.candidates if c.candidate_id == reference["candidate_id"])
    target = reference["target"]
    pair, = [p for p in pairs if p.required and p.original_path.name == target]
    marks = evidence["marks"]
    if any(mark["source_sha256"] != pair.original_sha256 for mark in marks):
        raise ValueError("The marked original surface changed.")
    inherited = [m for m in marks if m.get("reconstruction")
                 and m["reconstruction"]["sha256"] != pair.reconstruction_sha256]
    geometry = None
    if inherited:
        try:
            geometry = load_region_marking_mesh(
                pair.reconstruction_path, pair.reconstruction_sha256)
            geometry.prepare_inherited_faces(candidate, target, inherited, cancelled=lambda: False)
        except InterruptedError:
            raise
        except (ValueError, OSError, RuntimeError):
            # The normal viewer independently verifies both surface hashes before rendering.
            # An unreadable mark lineage must never be replaced with guessed coordinates.
            pass
    positions, missing = [], []
    for index, mark in enumerate(marks):
        position = mark["center"]
        material = mark.get("reconstruction")
        if material and material["sha256"] != pair.reconstruction_sha256:
            position = geometry.tracked_point(mark) if geometry is not None else None
        if position is None:
            missing.append(label(index))
        else:
            positions.append((label(index), tuple(position)))
    title = f"Retained fit · Test {record(parent)['screen_trials_spent']} · {candidate.label}"
    if positions:
        title += " · marked areas " + ", ".join(name for name, _ in positions)
    if missing:
        title += " · location unverified for " + ", ".join(missing)
    return (replace(pair, inspection_markers=tuple(positions)),), dict(
        title=title, target=target, marks=marks, cleared=evidence["regions_cleared"])
