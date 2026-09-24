from pathlib import Path
import re
import subprocess
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]


def _frontmatter() -> dict:
    text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    assert match, "SKILL.md must begin with YAML frontmatter"
    return yaml.safe_load(match.group(1))


def test_workbuddy_required_metadata_and_root_layout():
    meta = _frontmatter()
    for field in ("description", "description_zh", "description_en", "version", "author"):
        assert isinstance(meta.get(field), str) and meta[field].strip(), field
    assert meta["name"] == "quick-pass-exam"
    assert meta["display_name"] == "Quick-Pass-Exam"
    assert (ROOT / "references").is_dir()
    assert (ROOT / "scripts").is_dir()
    assert (ROOT / "templates").is_dir()
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "Apache License" in license_text
    assert "Version 2.0, January 2004" in license_text
    assert "END OF TERMS AND CONDITIONS" in license_text
    assert "Apache-2.0" in (ROOT / "NOTICE.md").read_text(encoding="utf-8")


def test_workbuddy_references_and_script_entrypoints_are_declared():
    text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    for name in ("validation.md", "case-authoring.md", "card-authoring.md", "card-quality-examples.md"):
        assert f"@references/{name}" in text
        assert (ROOT / "references" / name).is_file()
    declared = re.findall(r"@references/([A-Za-z0-9._-]+)", text)
    assert declared
    assert all((ROOT / "references" / name).is_file() for name in declared)
    assert "python3 scripts/quick-pass.py" in text
    assert "python3 scripts/study-library.py" in text
    assert "python3 cli.py" not in text
    assert "python3 study_server.py" not in text


def test_workbuddy_wrappers_expose_existing_cli_help():
    for script, marker in (("quick-pass.py", "--agent-content"), ("study-library.py", "{serve,open,register,collect}")):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / script), "--help"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert marker in result.stdout
