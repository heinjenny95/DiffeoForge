from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ISSUE_TEMPLATE_DIR = ROOT / ".github" / "ISSUE_TEMPLATE"
ISSUE_FORMS = (
    "01-bug-report.yml",
    "02-feature-request.yml",
    "03-scientific-change.yml",
    "04-usage-question.yml",
)
ALLOWED_BODY_TYPES = {"markdown", "input", "textarea", "dropdown", "checkboxes"}


def load_yaml(path: Path) -> dict:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict), f"{path} must contain a YAML mapping"
    return value


def test_issue_forms_have_actionable_github_schema() -> None:
    for filename in ISSUE_FORMS:
        form = load_yaml(ISSUE_TEMPLATE_DIR / filename)
        assert isinstance(form.get("name"), str) and len(form["name"]) > 3
        assert isinstance(form.get("description"), str) and form["description"]
        assert isinstance(form.get("body"), list) and form["body"]

        ids: set[str] = set()
        for element in form["body"]:
            assert isinstance(element, dict)
            assert element.get("type") in ALLOWED_BODY_TYPES
            assert isinstance(element.get("attributes"), dict)

            if element["type"] == "markdown":
                assert element["attributes"].get("value")
                continue

            element_id = element.get("id")
            assert isinstance(element_id, str) and element_id
            assert all(character.isalnum() or character in "-_" for character in element_id)
            assert element_id not in ids
            ids.add(element_id)
            assert element["attributes"].get("label")

            if element["type"] == "dropdown":
                options = element["attributes"].get("options")
                assert isinstance(options, list) and options
                assert len(options) == len(set(options))

            if element["type"] == "checkboxes":
                options = element["attributes"].get("options")
                assert isinstance(options, list) and options
                for option in options:
                    assert isinstance(option, dict) and option.get("label")
                    if "required" in option:
                        assert isinstance(option["required"], bool)

            validations = element.get("validations", {})
            assert isinstance(validations, dict)
            if "required" in validations:
                assert isinstance(validations["required"], bool)


def test_issue_chooser_requires_structured_templates() -> None:
    config = load_yaml(ISSUE_TEMPLATE_DIR / "config.yml")
    assert config["blank_issues_enabled"] is False
    assert isinstance(config["contact_links"], list)
    assert config["contact_links"]


def test_contribution_and_release_contracts_are_linked() -> None:
    contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    roadmap = (ROOT / "ROADMAP.md").read_text(encoding="utf-8")
    pull_request_template = (ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md").read_text(
        encoding="utf-8"
    )

    assert "issues/new/choose" in contributing
    assert "docs/RELEASE_CHECKLIST.md" in contributing
    assert "docs/RELEASE_CHECKLIST.md" in readme
    assert "- [x] Contribution issue templates and release checklist" in roadmap
    assert "Scientific or numerical change" in pull_request_template
    assert "private meshes" in pull_request_template
