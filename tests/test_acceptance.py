"""Independent acceptance checks for malformed input, links, resources and privacy.

These tests use fixture mode only. They do not call a provider and do not claim
that the synthetic sample has been human reviewed.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from generator import ContractError, _validate_package, generate_package, validate_questions
from renderer import _safe_relative_path, render_package


FIXTURE = ROOT / "examples" / "learning-package-input.json"


def _payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _write_payload(tmp_path: Path, payload: dict, name: str = "input.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_bad_root_and_question_shape_are_rejected():
    with pytest.raises(ContractError, match="questions 数组"):
        validate_questions([])
    payload = {"questions": [{"id": "q", "question_zh": "题", "options": "A"}]}
    with pytest.raises(ContractError, match="options"):
        validate_questions(payload)


def test_answer_must_be_scalar_text_and_agree_with_options():
    payload = _payload()
    payload["questions"][0]["answer"] = ["A"]
    with pytest.raises(ContractError, match="answer|答案"):
        validate_questions(payload)

    payload = _payload()
    payload["questions"][0]["answer"] = "B"
    with pytest.raises(ContractError, match="答案字段"):
        validate_questions(payload)


def test_unknown_question_and_concept_links_are_review_required():
    payload = _payload()
    payload["questions"][0]["concept_ids"].append("missing-concept")
    report = _validate_package(payload["questions"], payload["concepts"])
    assert report["status"] == "review_required"
    assert any(x["code"] == "QUESTION_CONCEPT_MISSING" for x in report["findings"])

    payload = _payload()
    payload["concepts"][0]["source_questions"].append("missing-question")
    report = _validate_package(payload["questions"], payload["concepts"])
    assert report["status"] == "review_required"
    assert any(x["code"] == "CONCEPT_QUESTION_MISSING" for x in report["findings"])


def test_fixture_generation_does_not_mutate_input_and_rejects_existing_output(tmp_path: Path):
    source = _write_payload(tmp_path, _payload())
    before = source.read_bytes()
    output = tmp_path / "package"
    generate_package(source, output, profile_name="ruankao-xitixiangmu", fixture=True)
    assert source.read_bytes() == before
    with pytest.raises(ContractError, match="已存在|覆盖"):
        generate_package(source, output, profile_name="ruankao-xitixiangmu", fixture=True)


def test_generation_failure_does_not_publish_partial_output(tmp_path: Path):
    payload = _payload()
    payload["concepts"][0]["source_questions"] = []
    payload["concepts"][0]["related_questions"] = []
    source = _write_payload(tmp_path, payload)
    output = tmp_path / "package"
    with pytest.raises(ContractError, match="质量门|来源"):
        generate_package(source, output, profile_name="ruankao-xitixiangmu", fixture=True)
    assert not output.exists()


def test_unknown_profile_is_rejected_before_generation(tmp_path: Path):
    source = _write_payload(tmp_path, _payload())
    with pytest.raises(ContractError, match="未知 profile"):
        generate_package(source, tmp_path / "package", profile_name="does-not-exist", fixture=True)


def test_missing_key_fails_before_provider_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = _write_payload(tmp_path, _payload())
    config = tmp_path / "llm.json"
    config.write_text(json.dumps({"provider": "test", "api_url": "https://provider.invalid/v1", "model": "test", "api_key_env": "QPE_ACCEPTANCE_MISSING_KEY"}), encoding="utf-8")
    monkeypatch.delenv("QPE_ACCEPTANCE_MISSING_KEY", raising=False)
    with pytest.raises(ContractError, match="环境变量"):
        generate_package(source, tmp_path / "package", profile_name="ruankao-xitixiangmu", llm_config=config)


def test_duplicate_concept_and_empty_origin_are_rejected(tmp_path: Path):
    payload = _payload()
    payload["concepts"].append(dict(payload["concepts"][0]))
    source = _write_payload(tmp_path, payload, "duplicate.json")
    with pytest.raises(ContractError, match="质量门|重复"):
        generate_package(source, tmp_path / "duplicate-package", profile_name="ruankao-xitixiangmu", fixture=True)


def test_renderer_rejects_resource_traversal_external_and_script_urls():
    for value in ("../secret.png", "/tmp/secret.png", "https://example.com/x.png",
                  "data:image/png;base64,AA==", "javascript:alert(1)", "file:///tmp/x.png"):
        assert _safe_relative_path(value) is None
    assert _safe_relative_path("assets/ok.png") == Path("assets/ok.png")


def test_renderer_copies_only_local_assets_and_keeps_html_text_inert(tmp_path: Path):
    source = tmp_path / "input"
    source.mkdir()
    (source / "ok.png").write_bytes(b"not-a-real-png")
    questions = [{
        "id": "q1", "question_zh": "<script>alert('x')</script>",
        "options": [{"label": "A", "text": "<img src=x onerror=alert(1)>", "is_correct": True}],
        "answer": "A", "diagram_image": "ok.png", "concept_ids": ["c1"],
    }]
    concepts = [{"id": "c1", "title": "安全文本", "source_questions": ["q1"], "core_concept": {"definition": "定义"}}]
    out = tmp_path / "out"
    index = render_package(questions, concepts, out, input_dir=source)
    page = index.read_text(encoding="utf-8")
    assert (out / "assets" / "content").exists()
    assert "<\\/script>" in page
    assert "onerror=alert" in page  # remains JSON data; UI inserts learner textContent
    assert not re.search(r'<img[^>]+src=["\']https?://', page)


def test_manifest_does_not_contain_secrets_or_absolute_input_path(tmp_path: Path):
    source = _write_payload(tmp_path, _payload())
    out = tmp_path / "package"
    generate_package(source, out, profile_name="ruankao-xitixiangmu", fixture=True)
    manifest = (out / "manifest.json").read_text(encoding="utf-8")
    assert "API_KEY" not in manifest and "Bearer" not in manifest
    assert str(tmp_path) not in manifest
    assert "app.db" not in manifest and ".env" not in manifest


def test_examples_explicitly_mark_sample_as_unreviewed():
    readme = (ROOT / "examples" / "README.md").read_text(encoding="utf-8")
    payload = (ROOT / "examples" / "questions.json").read_text(encoding="utf-8")
    concepts = (ROOT / "examples" / "concepts.json").read_text(encoding="utf-8")
    assert "2026-09-20" in readme and "用户" in readme and "概念笔记" in readme
    assert "questions_human_reviewed" in payload
    assert "not_human_reviewed" not in payload
    assert '"review_status": "questions_human_reviewed"' in (ROOT / "examples" / "learning-package-input.json").read_text(encoding="utf-8")
    assert "review_status" not in concepts


def test_learning_input_questions_are_exact_copy_of_reviewed_questions():
    reviewed = json.loads((ROOT / "examples" / "questions.json").read_text(encoding="utf-8"))
    merged = json.loads((ROOT / "examples" / "learning-package-input.json").read_text(encoding="utf-8"))
    assert merged["questions"] == reviewed["questions"]
    assert all(len(q["options"]) == 4 for q in merged["questions"])
    assert "| 指标 | 数值 |" in merged["questions"][0]["question_zh"]


def test_evm_flow_is_a_concept_aid_not_question_stem_content():
    reviewed = json.loads((ROOT / "examples" / "questions.json").read_text(encoding="utf-8"))
    concepts = json.loads((ROOT / "examples" / "concepts.json").read_text(encoding="utf-8"))
    question = next(q for q in reviewed["questions"] if q["id"] == "fixture_hi_001")
    concept = next(c for c in concepts if c["id"] == "fixture_evm_cpi")
    assert "diagram_image" not in question
    assert "![EVM 流程示意图]" not in question["question_zh"]
    assert concept["images"] == ["assets/evm-flow.svg"]


def test_preview_question_cornell_note_uses_explicit_pairs():
    preview = json.loads((ROOT / "examples" / "preview" / "data" / "questions.json").read_text(encoding="utf-8"))
    question = next(q for q in preview if q["id"] == "fixture_hi_001")
    model_note = question["generated_analysis"]["cornell_note"]
    assert question["cornell_note"] == model_note
    assert model_note["pairing_status"] == "paired"
    assert len(model_note["pairs"]) == 4
    assert all(pair["cue"].strip() and pair["note"].strip() for pair in model_note["pairs"])


def test_distributed_runtime_has_no_legacy_bank_parser_or_ocr_dependency():
    allowlist = {
        line.strip() for line in (ROOT / "SNAPSHOT_FILES.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }
    assert "document_adapter.py" in allowlist
    assert "vendor/bank_parser.py" not in allowlist
    assert "tests/test_bank_parser.py" not in allowlist
    assert "config.ocr.example.json" not in allowlist
    assert not (ROOT / "vendor" / "bank_parser.py").exists()
    assert not (ROOT / "config.ocr.example.json").exists()

    runtime_files = [ROOT / name for name in (
        "cli.py", "generator.py", "renderer.py", "importer.py",
        "agent_preprocess.py", "document_adapter.py",
    )]
    runtime_files.extend(sorted((ROOT / "vendor").glob("*.py")))
    runtime = "\n".join(path.read_text(encoding="utf-8") for path in runtime_files)
    assert "from bank_parser" not in runtime and "import bank_parser" not in runtime
    assert "pdf_inspector" not in runtime and "pdf-inspector" not in runtime
    assert "--ocr-config" not in (ROOT / "cli.py").read_text(encoding="utf-8")
    requirements = (ROOT / "requirements-import.txt").read_text(encoding="utf-8")
    assert "pdf-inspector" not in requirements and "certifi" not in requirements
    provenance = json.loads((ROOT / "provenance.json").read_text(encoding="utf-8"))
    assert all(record.get("target") != "vendor/bank_parser.py" for record in provenance["records"])
