"""Qt-independent parameter and workload review for desktop projects."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from diffeoforge.desktop.project_setup import DesktopEngine
from diffeoforge.report import (
    collect_preflight,
    default_preflight_report_path,
    write_preflight_report,
)


@dataclass(frozen=True)
class ReviewItem:
    """One effective value and the reason it matters to a researcher."""

    label: str
    value: str
    explanation: str


@dataclass(frozen=True)
class ProjectReviewResult:
    """Display-ready evidence collected through shared validated core services."""

    engine: DesktopEngine
    project_name: str
    config_path: Path
    report_path: Path
    report_label: str
    subject_count: int
    parameters: tuple[ReviewItem, ...]
    workload: tuple[ReviewItem, ...]
    warnings: tuple[str, ...]
    scientific_boundary: str


def _number(value: int | float) -> str:
    if isinstance(value, int):
        return f"{value:,}".replace(",", " ")
    return f"{value:.6g}"


def _bytes(value: int | None) -> str:
    if value is None:
        return "unbekannt"
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    amount = float(value)
    unit = units[0]
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            break
        amount /= 1024
    return f"{amount:.3g} {unit}"


def _setting(value: Any, *, none: str = "automatisches Maximum") -> str:
    if value is None:
        return none
    if isinstance(value, bool):
        return "ja" if value else "nein"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return _number(value)
    if isinstance(value, (list, tuple)):
        return " → ".join(str(item) for item in value)
    return str(value)


def _reference_review(config_path: Path) -> ProjectReviewResult:
    preflight = collect_preflight(config_path)
    config = preflight.config
    model = config["model"]
    deformation = model["deformation"]
    optimization = config["optimization"]
    runtime = config["runtime"]
    diagonal = preflight.template.bounding_box_diagonal
    ratios = preflight.parameter_ratios
    report_path = default_preflight_report_path(config_path)
    write_preflight_report(preflight, report_path, overwrite=report_path.exists())

    parameters = (
        ReviewItem(
            "Koordinateneinheit",
            str(config["input"]["units"]),
            "Bestimmt die physikalische Interpretation aller Längen und Distanzen.",
        ),
        ReviewItem(
            "Attachment",
            (
                f"{model['attachment']['type']} · Breite "
                f"{_number(model['attachment']['kernel_width'])}"
            ),
            "Vergleicht Template und Probandenoberflächen; die Breite steuert die räumliche Skala.",
        ),
        ReviewItem(
            "Deformationskernel",
            _number(deformation["kernel_width"]),
            "Steuert die räumliche Glätte der diffeomorphen Deformation.",
        ),
        ReviewItem(
            "Kontrollpunktabstand",
            _number(deformation["initial_control_point_spacing"]),
            "Steuert die Dichte der initialen Deformationsparameter.",
        ),
        ReviewItem(
            "Zeitdiskretisierung",
            f"{deformation['timepoints']} Zeitpunkte · RK2 {_setting(deformation['use_rk2'])}",
            "Legt die numerische Diskretisierung der Deformationsbahn fest.",
        ),
        ReviewItem(
            "Rauschstandardabweichung",
            _number(model["noise_std"]),
            "Gewichtet den Datenanpassungsterm im Atlasmodell.",
        ),
        ReviewItem(
            "Optimierung",
            (
                f"max. {optimization['max_iterations']} Iterationen · Schritt "
                f"{_number(optimization['initial_step_size'])}"
            ),
            "Starterwerte für Gradient Ascent; Konvergenz und biologische "
            "Plausibilität müssen geprüft werden.",
        ),
        ReviewItem(
            "Reproduzierbarkeit",
            (
                f"Seed {runtime['random_seed']} · {runtime['threads']} Threads · "
                f"{runtime['precision']}"
            ),
            "Explizite Laufzeitparameter für die externe Referenzroute.",
        ),
    )
    subject_points = [subject.points for subject in preflight.subjects]
    subject_faces = [subject.cells for subject in preflight.subjects]
    workload = (
        ReviewItem(
            "Datensatz",
            f"{len(preflight.subjects)} Probanden + 1 Template",
            "Vollständig geparste und validierte VTK-Oberflächen.",
        ),
        ReviewItem(
            "Template-Skala",
            _number(diagonal),
            "Diagonale der Template-Bounding-Box; Bezugsgröße der erzeugten Starterwerte.",
        ),
        ReviewItem(
            "Attachment / Template-Skala",
            f"{ratios['Attachment kernel width / template diagonal']:.3%}",
            "Dimensionsloses Verhältnis aus dem effektiven Preflight.",
        ),
        ReviewItem(
            "Deformation / Template-Skala",
            f"{ratios['Deformation kernel width / template diagonal']:.3%}",
            "Dimensionsloses Verhältnis aus dem effektiven Preflight.",
        ),
        ReviewItem(
            "Mesh-Auflösung",
            (
                f"{min(subject_points):,}–{max(subject_points):,} Punkte · "
                f"{min(subject_faces):,}–{max(subject_faces):,} Flächen"
            ).replace(",", " "),
            "Beobachtete Spanne der Probandenmeshes, keine Qualitätsbewertung "
            "der Formrepräsentation.",
        ),
        ReviewItem(
            "Quelldaten",
            _bytes(preflight.total_input_bytes),
            "Dateigröße der geprüften Meshes; keine RAM- oder Laufzeitprognose.",
        ),
        ReviewItem(
            "Rechenaufwand",
            "nicht modelliert",
            "Die Ausführung liegt in der externen Deformetrica-4.3-Umgebung; "
            "Pilotmessung erforderlich.",
        ),
    )
    warnings = (
        "Geometrieskalierte Starterwerte sind explorativ und keine wissenschaftlich "
        "validierten Presets.",
        *preflight.notices,
        "DiffeoForge hat Deformetrica nicht gestartet und prognostiziert hier weder "
        "Peak-RAM noch Laufzeit.",
    )
    return ProjectReviewResult(
        engine=DesktopEngine.DEFORMETRICA_REFERENCE,
        project_name=str(config["project"]["name"]),
        config_path=config_path,
        report_path=report_path,
        report_label="Preflight-Report",
        subject_count=len(preflight.subjects),
        parameters=parameters,
        workload=workload,
        warnings=warnings,
        scientific_boundary=(
            "Diese Ansicht bestätigt Schema, Pfade, Meshgeometrie und effektive Parameter. "
            "Sie bestätigt weder Parameter-Eignung noch biologische Validität und führt die "
            "externe Deformetrica-Engine nicht aus."
        ),
    )


def _modern_review(config_path: Path) -> ProjectReviewResult:
    try:
        from diffeoforge.modern_workflow import load_modern_workflow_config
        from diffeoforge.modern_workload import (
            REPORT_HTML_NAME,
            SCIENTIFIC_BOUNDARY,
            collect_modern_workload,
            default_modern_workload_path,
            write_modern_workload_report,
        )
    except ImportError as error:
        raise RuntimeError(
            "Modern engine dependencies are missing; install diffeoforge[modern-engine]."
        ) from error

    config = load_modern_workflow_config(config_path)
    report = collect_modern_workload(config_path)
    report_directory = default_modern_workload_path(config_path)
    write_modern_workload_report(
        report,
        report_directory,
        overwrite=report_directory.exists(),
    )
    report_path = report_directory / REPORT_HTML_NAME
    model = config["model"]
    deformation = model["deformation"]
    optimization = config["optimization"]
    analysis = config["analysis"]
    runtime = config["runtime"]
    procrustes = config["preprocessing"]["procrustes"]
    pairwise = report["engine"]["pairwise_evaluation"]
    pairwise_value = "dense · vollständige Paarmatrizen"
    if pairwise["mode"] == "blockwise":
        pairwise_value = (
            f"blockwise · Kacheln {pairwise['query_tile_size']} × {pairwise['source_tile_size']}"
        )
    noise_std = math.sqrt(model["noise_variance"])
    parameters = (
        ReviewItem(
            "Koordinateneinheit",
            str(config["input"]["units"]),
            "Bestimmt die physikalische Interpretation aller Längen und Distanzen.",
        ),
        ReviewItem(
            "Attachment",
            (
                f"{model['attachment']['type']} · Breite "
                f"{_number(model['attachment']['kernel_width'])}"
            ),
            "Vergleicht Template und Probandenoberflächen auf der konfigurierten räumlichen Skala.",
        ),
        ReviewItem(
            "Deformationskernel",
            _number(deformation["kernel_width"]),
            "Steuert die räumliche Glätte der diffeomorphen Deformation.",
        ),
        ReviewItem(
            "Kontrollpunkte",
            f"{config['initialization']['control_points']['count']} · farthest template vertices",
            "Anzahl und deterministische Initialisierung der Deformationsparameter.",
        ),
        ReviewItem(
            "Zeitintegration",
            (
                f"{deformation['timepoints']} Zeitpunkte · "
                f"{deformation['shooting_integrator']} / {deformation['flow_integrator']}"
            ),
            "Explizite Diskretisierung für Shooting und Template-Flow.",
        ),
        ReviewItem(
            "Rauschvarianz",
            f"{_number(model['noise_variance'])} · Standardabw. {_number(noise_std)}",
            "Gewichtet den Datenanpassungsterm; die Standardabweichung ist exakt aus "
            "der Varianz abgeleitet.",
        ),
        ReviewItem(
            "Optimierungsblöcke",
            f"{_setting(optimization['block_order'])} · max. {optimization['max_cycles']} Zyklen",
            "Deterministische Reihenfolge der getrennten Parameter-Updates.",
        ),
        ReviewItem(
            "PCA-Ausgabe",
            (
                f"Komponenten {_setting(analysis['pca_components'])} · "
                f"Deformationen {_setting(analysis['deformation_components'])}"
            ),
            "Begrenzt spätere PCA- und Extremform-Artefakte, nicht die Atlasoptimierung selbst.",
        ),
        ReviewItem(
            "Landmark-Procrustes",
            _setting(procrustes["enabled"]),
            "Optionale homologe Landmark-Ausrichtung vor der Atlasberechnung.",
        ),
        ReviewItem(
            "Ausführung",
            f"CPU · float64 · {runtime['threads']} Threads · Seed {runtime['random_seed']}",
            "Effektiver, reproduzierbarer Laufzeitvertrag der experimentellen Modern-Engine.",
        ),
        ReviewItem(
            "Paarweise Auswertung",
            pairwise_value,
            "Dieselbe Ausführungsstrategie, die der Atlas verwendet und der "
            "Workload-Report bilanziert.",
        ),
    )
    operation = report["operation_model"]
    forward = operation["one_objective_forward"]
    logical = operation["largest_logical_pair"]
    tile = operation["largest_execution_tile"]
    payload = report["payload_model"]
    optimizer = report["optimizer_bound"]
    output = report["output_bound"]
    host = report["host_observations"]
    workload = (
        ReviewItem(
            "Datensatz",
            f"{report['input']['subject_count']} Probanden + 1 Template",
            "Vollständig inventarisierte Meshes; Hashes und Dimensionen stehen im "
            "HTML/JSON-Report.",
        ),
        ReviewItem(
            "Ein Objective-Forward",
            (
                f"{_number(forward['gaussian_calls'])} Gaussian-Aufrufe · "
                f"{_number(forward['gaussian_pair_elements'])} Paarelemente"
            ),
            "Exakte Formel für die aktuell konfigurierte Engine und Meshinventur.",
        ),
        ReviewItem(
            "Größtes logisches Paar",
            (
                f"{logical['rows']} × {logical['columns']} · "
                f"{_bytes(logical['float64_xyz_difference_tensor_bytes'])} "
                "XYZ-Differenzen"
            ),
            "Logische All-pairs-Dimension; bei blockweiser Auswertung nicht zwingend "
            "eine einzelne Allokation.",
        ),
        ReviewItem(
            "Größte Ausführungskachel",
            (
                f"{tile['tile_rows']} × {tile['tile_columns']} · "
                f"{_bytes(tile['float64_xyz_difference_tensor_bytes'])}"
            ),
            "Exakte Obergrenze einer konfigurierten XYZ-Differenzkachel, nicht des "
            "gesamten Peak-RAM.",
        ),
        ReviewItem(
            "Bekannte Payload-Arithmetik",
            _bytes(payload["known_payload_arithmetic_subtotal_bytes"]),
            "Explizit bilanzierte Tensoranteile; Autograd, Allocator, BLAS und "
            "Betriebssystem fehlen bewusst.",
        ),
        ReviewItem(
            "Objective/Gradient-Obergrenze",
            _number(optimizer["objective_gradient_evaluation_upper_bound"]),
            "Konfigurationsbedingte Obergrenze inklusive Line Search, keine beobachtete "
            "Iterationszahl.",
        ),
        ReviewItem(
            "Gaussian-Paarelemente-Obergrenze",
            _number(optimizer["gaussian_pair_elements_upper_bound"]),
            "Exakte Multiplikation aus Forward-Modell und Optimizer-Obergrenze.",
        ),
        ReviewItem(
            "Maximale Bundle-Meshes",
            _number(output["maximum_bundle_vtk_meshes"]),
            "Obergrenze für spätere Atlas-, Rekonstruktions- und PCA-VTK-Artefakte.",
        ),
        ReviewItem(
            "Beobachteter Rechner",
            (
                f"{host.get('logical_cpus') or 'unbekannt'} logische CPUs · "
                f"{_bytes(host.get('physical_memory_bytes'))} physischer RAM"
            ),
            "Host-Beobachtung zum Planzeitpunkt; keine Zusage, dass diese Ressourcen "
            "frei verfügbar sind.",
        ),
        ReviewItem(
            "Peak-RAM und Laufzeit",
            "unbekannt · Pilotmessung erforderlich",
            "DiffeoForge erfindet keine Prognose aus unvollständigen Speicher- und Zeitmodellen.",
        ),
    )
    warnings = (
        "Geometrieskalierte Starterwerte sind explorativ und keine wissenschaftlich "
        "validierten Presets.",
        *(str(warning) for warning in report["warnings"]),
    )
    return ProjectReviewResult(
        engine=DesktopEngine.MODERN_CPU,
        project_name=str(config["project"]["name"]),
        config_path=config_path,
        report_path=report_path,
        report_label="Modern-Workload-Report",
        subject_count=report["input"]["subject_count"],
        parameters=parameters,
        workload=workload,
        warnings=warnings,
        scientific_boundary=(
            "Gezeigt werden exakte All-pairs-Operationszahlen und bekannte Tensor-Payloads "
            "für den konfigurierten CPU/float64-Plan. Dies ist keine Peak-RAM-Prognose, "
            "Laufzeitvorhersage, Benchmarkmessung oder Garantie für 300 Probanden. "
            "Autograd, Speicherverwaltung, BLAS-Threads und Betriebssystemlast können den "
            f"realen Bedarf verändern. Originaler Berichtsvertrag: {SCIENTIFIC_BOUNDARY}"
        ),
    )


def review_project(
    config_path: Path | str,
    engine: DesktopEngine | str,
) -> ProjectReviewResult:
    """Review one generated project without executing either atlas engine."""

    source = Path(config_path).expanduser().resolve()
    selected = DesktopEngine(engine)
    if selected is DesktopEngine.MODERN_CPU:
        return _modern_review(source)
    return _reference_review(source)
