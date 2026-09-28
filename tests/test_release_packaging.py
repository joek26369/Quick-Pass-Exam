import hashlib
import json
from pathlib import Path
import zipfile

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_snapshot_build_is_byte_reproducible(tmp_path):
    from tools.build_snapshot import build

    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    build(first)
    build(second)
    assert first.read_bytes() == second.read_bytes()
    assert hashlib.sha256(first.read_bytes()).hexdigest() == hashlib.sha256(second.read_bytes()).hexdigest()
    with zipfile.ZipFile(first) as archive:
        assert len(archive.namelist()) == len(set(archive.namelist()))
        assert "SKILL.md" in archive.namelist()
        assert all(len(Path(name).parts) <= 2 for name in archive.namelist())
        assert not any(name.startswith(("tests/", "tools/")) for name in archive.namelist())
        assert "examples/agent-content-cases.json" in archive.namelist()
        content = json.loads(archive.read("examples/agent-content.json"))
        for source in content["sources"]:
            assert "examples/" + source["path"] in archive.namelist()


def test_public_beta_metadata_and_pdf_dependency_are_consistent():
    skill_text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    frontmatter = yaml.safe_load(skill_text.split("---", 2)[1])
    provenance = json.loads((ROOT / "provenance.json").read_text(encoding="utf-8"))
    imports = (ROOT / "requirements-import.txt").read_text(encoding="utf-8")

    assert frontmatter["version"] == "1.0.0-beta.6"
    assert provenance["release"]["version"] == frontmatter["version"]
    assert provenance["license_status"]["project_files"] == "project_owner_declared_apache-2.0"
    assert "pypdfium2" in imports
    assert "PyMuPDF" not in imports
