"""Verify the static inventory contract of one built DiffeoForge wheel."""

from __future__ import annotations

import argparse
import configparser
import sys
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = ROOT / "src" / "diffeoforge" / "schema"
CONSOLE_ENTRY_POINT = "diffeoforge.cli:main"


class WheelContractError(RuntimeError):
    """Raised when a built wheel violates the static package contract."""


@dataclass(frozen=True)
class WheelEvidence:
    """Concise evidence returned after a successful wheel audit."""

    wheel: Path
    member_count: int
    schema_count: int
    dist_info_directory: str


def expected_package_members() -> frozenset[str]:
    """Return repository-derived package members that every wheel must contain."""

    schemas = {
        path.relative_to(ROOT / "src").as_posix()
        for path in SCHEMA_ROOT.glob("*.json")
    }
    if not schemas:
        raise WheelContractError("Repository contains no versioned JSON schemas")
    return frozenset({"diffeoforge/__main__.py", *schemas})


def _safe_member_name(name: str) -> bool:
    path = PurePosixPath(name)
    return bool(name) and "\\" not in name and not path.is_absolute() and ".." not in path.parts


def verify_wheel(path: Path | str) -> WheelEvidence:
    """Verify inventory, archive-name safety, and public CLI metadata."""

    wheel = Path(path).expanduser().resolve()
    if not wheel.is_file() or wheel.suffix != ".whl":
        raise WheelContractError(f"Wheel does not exist or lacks .whl suffix: {wheel}")
    try:
        with zipfile.ZipFile(wheel) as archive:
            names = [item.filename for item in archive.infolist()]
            if len(names) != len(set(names)):
                raise WheelContractError("Wheel contains duplicate archive member names")
            unsafe = [name for name in names if not _safe_member_name(name)]
            if unsafe:
                raise WheelContractError(f"Wheel contains unsafe archive member: {unsafe[0]}")
            observed = set(names)
            expected = expected_package_members()
            missing = sorted(expected - observed)
            if missing:
                raise WheelContractError(
                    "Wheel is missing required package members: " + ", ".join(missing)
                )
            dist_info = sorted(
                {
                    PurePosixPath(name).parts[0]
                    for name in names
                    if PurePosixPath(name).parts
                    and PurePosixPath(name).parts[0].endswith(".dist-info")
                }
            )
            if len(dist_info) != 1:
                raise WheelContractError("Wheel must contain exactly one .dist-info directory")
            entry_points_name = f"{dist_info[0]}/entry_points.txt"
            if entry_points_name not in observed:
                raise WheelContractError("Wheel is missing .dist-info/entry_points.txt")
            parser = configparser.ConfigParser(interpolation=None)
            parser.read_string(archive.read(entry_points_name).decode("utf-8"))
    except (OSError, UnicodeError, zipfile.BadZipFile) as error:
        raise WheelContractError(f"Could not inspect wheel: {error}") from error
    if not parser.has_section("console_scripts"):
        raise WheelContractError("Wheel has no [console_scripts] entry-point section")
    observed_entry = parser.get("console_scripts", "diffeoforge", fallback=None)
    if observed_entry != CONSOLE_ENTRY_POINT:
        raise WheelContractError(
            "Wheel console entry point differs from diffeoforge = " + CONSOLE_ENTRY_POINT
        )
    return WheelEvidence(
        wheel=wheel,
        member_count=len(names),
        schema_count=len(expected) - 1,
        dist_info_directory=dist_info[0],
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path, help="Built .whl artifact to verify")
    args = parser.parse_args(argv)
    try:
        evidence = verify_wheel(args.wheel)
    except WheelContractError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    print(f"Verified wheel: {evidence.wheel}")
    print(f"Archive members: {evidence.member_count}")
    print(f"Versioned JSON schemas: {evidence.schema_count}")
    print(f"Metadata directory: {evidence.dist_info_directory}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
