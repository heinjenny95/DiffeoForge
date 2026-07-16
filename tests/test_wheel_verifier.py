from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from tools.verify_wheel import (
    CONSOLE_ENTRY_POINT,
    WheelContractError,
    expected_package_members,
    main,
    verify_wheel,
)

DIST_INFO = "diffeoforge-0.0.0.dev0.dist-info"


def _write_wheel(
    path: Path,
    *,
    omitted: str | None = None,
    console_entry: str = CONSOLE_ENTRY_POINT,
    extra_members: tuple[str, ...] = (),
) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for member in sorted(expected_package_members() - {omitted}):
            archive.writestr(member, "{}\n" if member.endswith(".json") else "# module\n")
        archive.writestr(f"{DIST_INFO}/METADATA", "Metadata-Version: 2.4\n")
        archive.writestr(
            f"{DIST_INFO}/entry_points.txt",
            f"[console_scripts]\ndiffeoforge = {console_entry}\n",
        )
        for member in extra_members:
            archive.writestr(member, "test\n")
    return path


def test_verifier_accepts_complete_wheel_and_cli_reports_evidence(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    wheel = _write_wheel(tmp_path / "diffeoforge.whl")

    evidence = verify_wheel(wheel)
    result = main([str(wheel)])
    output = capsys.readouterr()

    assert evidence.schema_count == len(expected_package_members()) - 1
    assert evidence.dist_info_directory == DIST_INFO
    assert result == 0
    assert "Verified wheel:" in output.out
    assert "Versioned JSON schemas:" in output.out
    assert output.err == ""


def test_verifier_rejects_missing_schema(tmp_path: Path) -> None:
    missing = next(
        member for member in expected_package_members() if member.endswith(".json")
    )
    wheel = _write_wheel(tmp_path / "missing.whl", omitted=missing)

    with pytest.raises(WheelContractError, match="missing required.*schema"):
        verify_wheel(wheel)


def test_verifier_rejects_wrong_console_entry_point(tmp_path: Path) -> None:
    wheel = _write_wheel(
        tmp_path / "entry.whl",
        console_entry="diffeoforge.other:main",
    )

    with pytest.raises(WheelContractError, match="console entry point differs"):
        verify_wheel(wheel)


def test_verifier_rejects_duplicate_archive_members(tmp_path: Path) -> None:
    with pytest.warns(UserWarning, match="Duplicate name"):
        wheel = _write_wheel(
            tmp_path / "duplicate.whl",
            extra_members=("diffeoforge/__main__.py",),
        )

    with pytest.raises(WheelContractError, match="duplicate archive member"):
        verify_wheel(wheel)


@pytest.mark.parametrize(
    ("extra_members", "message"),
    [
        (("../unsafe.txt",), "unsafe archive member"),
        (("other-1.0.dist-info/METADATA",), "exactly one .dist-info"),
    ],
)
def test_verifier_rejects_unsafe_or_ambiguous_inventory(
    tmp_path: Path,
    extra_members: tuple[str, ...],
    message: str,
) -> None:
    wheel = _write_wheel(tmp_path / "invalid.whl", extra_members=extra_members)

    with pytest.raises(WheelContractError, match=message):
        verify_wheel(wheel)
