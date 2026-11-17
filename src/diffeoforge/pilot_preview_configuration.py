"""Select and stage the display observer only for new eligible guided trials."""

DECLARATION = {"version": "pilot-live-preview-v1"}
ASSET = "pilot_preview_runtime.py"


def _supported(config, subjects):
    project = config["project"].get("parameter_provenance", {})
    optimization = config["optimization"]
    method = optimization["method"]
    runtime = config["runtime"]
    return (
        subjects == 1
        and runtime["processes"] == 1
        and optimization["freeze_template"]
        and optimization["freeze_control_points"]
        and not project.get("pilot_review")
        and config["output"].get("checkpoint_mode") != "compact_convergence_export"
        and (method == "gradient_ascent"
             or method == "lbfgs" and bool(project.get("finite_accepted_guard")))
    )


def mark(config, manifest):
    """Declare display support in the new candidate before sealing its config."""
    project = config["project"].get("parameter_provenance")
    if project is None:
        return
    project.pop("pilot_live_preview", None)
    guided = (manifest.get("attachment_comparison") or {}).get("guided")
    if (guided and guided.get("phase") != "joint"
            and _supported(config, len(manifest["inputs"]["subjects"]))):
        project["pilot_live_preview"] = dict(DECLARATION)


def extend_engine_files(config, subjects, rendered):
    if (config["project"].get("parameter_provenance", {}).get("pilot_live_preview")
            != DECLARATION or not _supported(config, subjects)):
        return rendered
    from diffeoforge.pilot_preview_assets import SOURCE

    method = config["optimization"]["method"]
    body = (
        "\ntry:\n"
        "    from pathlib import Path as _df_preview_path\n"
        "    from pilot_preview_runtime import install as _df_preview_install\n"
        "    _df_preview_install(_df_preview_path(__file__).resolve().parent, "
        f"guard_module=globals().get('_df_guard'), method={method!r})\n"
        "except Exception:\n"
        "    pass  # A display-only observer cannot stop estimation.\n"
    )
    return dict(rendered, **{
        ASSET: SOURCE,
        "sitecustomize.py": rendered.get("sitecustomize.py", b"") + body.encode("utf-8"),
    })
