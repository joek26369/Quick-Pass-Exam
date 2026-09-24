"""Agent-first packaging contracts; these tests never call an external model."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import generator
from generator import AGENT_CONTENT_SCHEMA, ContractError, generate_package


def _agent_payload(tmp_path: Path) -> dict:
    (tmp_path / "bank.txt").write_text("题库原文", encoding="utf-8")
    return {
        "schema_version": AGENT_CONTENT_SCHEMA,
        "questions": [{
            "id": "q1", "question_zh": "项目成本绩效如何判断？", "answer": "A",
            "source_id": "bank-1", "concept_ids": ["c1"],
            "options": [
                {"label": "A", "text": "使用 CPI", "is_correct": True},
                {"label": "B", "text": "只看工期", "is_correct": False},
            ],
        }],
        "concepts": [{
            "id": "c1", "title": "成本绩效指数", "source_questions": ["q1"],
            "one_liner": "CPI 用于衡量成本效率。",
            "cornell_note": {
                "pairs": [{"cue": "CPI 衡量什么？", "note": "衡量成本效率。"}],
                "summary": "比较挣值与实际成本。", "pairing_status": "paired",
            },
            "teaching_evidence_ids": [],
        }],
        "sources": [{"id": "bank-1", "role": "question_bank", "path": "bank.txt"}],
        "teaching_evidence": [],
    }


def _write(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "agent-content.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _v2_payload(tmp_path: Path) -> dict:
    """Two concepts share one explicit teaching evidence record."""
    (tmp_path / "bank.txt").write_text("题库原文", encoding="utf-8")
    from reportlab.pdfgen import canvas
    document = canvas.Canvas(str(tmp_path / "guide.pdf"))
    for page_number in (1, 2):
        document.drawString(36, 800, f"synthetic guide page {page_number}")
        document.showPage()
    document.save()
    payload = _agent_payload(tmp_path)
    payload["questions"][0]["concept_ids"] = ["c1", "c2"]
    payload["concepts"].append({
        "id": "c2", "title": "成本基线", "source_questions": ["q1"],
        "one_liner": "成本基线用于绩效测量。",
        "cornell_note": {"pairs": [{"cue": "成本基线？", "note": "用于测量。"}],
                         "summary": "成本基线。", "pairing_status": "paired"},
        "teaching_evidence_ids": ["ev-1"],
    })
    payload["concepts"][0]["teaching_evidence_ids"] = ["ev-1"]
    payload["sources"] = [
        {"id": "bank-1", "role": "question_bank", "path": "bank.txt"},
        {"id": "guide-1", "role": "teaching_material", "path": "guide.pdf"},
    ]
    payload["teaching_evidence"] = [{
        "id": "ev-1", "source_id": "guide-1", "status": "input_provided", "relation": "supports",
        "concept_ids": ["c1", "c2"],
        "locator": {"page": 2, "excerpt": "CPI 是成本绩效指数。",
                    "region": {"x": 0.1, "y": 0.2, "width": 0.8, "height": 0.6}},
    }]
    return payload


def test_agent_content_runs_quality_gate_and_renderer_without_llm(tmp_path, monkeypatch):
    source = _write(tmp_path, _agent_payload(tmp_path))

    def forbidden_client(*_args, **_kwargs):
        raise AssertionError("agent content path must not construct an LLM client")

    monkeypatch.setattr(generator, "_client", forbidden_client)
    output = generate_package(
        source, tmp_path / "package", profile_name="ruankao-xitixiangmu",
        agent_content=True,
    )

    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    report = json.loads((output / "reports" / "quality-report.json").read_text(encoding="utf-8"))
    questions = json.loads((output / "data" / "questions.json").read_text(encoding="utf-8"))
    assert manifest["mode"] == "agent"
    assert manifest["content_input_schema"] == AGENT_CONTENT_SCHEMA
    assert manifest["model"] is None and manifest["config_sha256"] is None
    assert manifest["usage"]["attempt_count"] == 0
    assert report["package"]["status"] == report["origin"]["status"] == "passed"
    assert questions[0]["concept_ids"] == ["c1"]
    assert (output / "web" / "index.html").is_file()


def test_agent_content_requires_schema_and_complete_cornell_pairs(tmp_path):
    payload = _agent_payload(tmp_path)
    payload.pop("schema_version")
    with pytest.raises(ContractError, match="schema_version"):
        generate_package(_write(tmp_path, payload), tmp_path / "bad-schema",
                         profile_name="ruankao-xitixiangmu", agent_content=True)

    payload = _agent_payload(tmp_path)
    payload["concepts"][0]["cornell_note"]["pairs"][0]["note"] = None
    with pytest.raises(ContractError, match="质量门"):
        generate_package(_write(tmp_path, payload), tmp_path / "bad-cornell",
                         profile_name="ruankao-xitixiangmu", agent_content=True)
    assert not (tmp_path / "bad-cornell").exists()


def test_cli_agent_content_command_needs_no_llm_config(tmp_path):
    source = _write(tmp_path, _agent_payload(tmp_path))
    output = tmp_path / "cli-package"
    result = subprocess.run(
        [sys.executable, str(ROOT / "cli.py"), "--input", str(source),
         "--output", str(output), "--agent-content"],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert Path(result.stdout.strip()) == output
    assert json.loads((output / "manifest.json").read_text(encoding="utf-8"))["mode"] == "agent"


def test_v2_agent_content_keeps_explicit_many_to_many_teaching_evidence(tmp_path):
    payload = _v2_payload(tmp_path)
    output = generate_package(
        _write(tmp_path, payload), tmp_path / "package",
        profile_name="ruankao-xitixiangmu", agent_content=True,
    )
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    report = json.loads((output / "reports" / "quality-report.json").read_text(encoding="utf-8"))
    concepts = json.loads((output / "data" / "concepts.json").read_text(encoding="utf-8"))
    sources = json.loads((output / "data" / "sources.json").read_text(encoding="utf-8"))
    evidence = json.loads((output / "data" / "teaching-evidence.json").read_text(encoding="utf-8"))
    assert manifest["content_input_schema"] == AGENT_CONTENT_SCHEMA
    assert report["package"]["agent_content"] == {
        "schema_version": AGENT_CONTENT_SCHEMA, "source_count": 2,
        "teaching_evidence_count": 1, "validation": "local_structural_only",
    }
    assert sources[1]["role"] == "teaching_material"
    assert len(sources[0]["sha256"]) == 64
    assert sources[1]["page_count"] == 2 and len(sources[1]["sha256"]) == 64
    assert evidence[0]["concept_ids"] == ["c1", "c2"]
    questions = json.loads((output / "data" / "questions.json").read_text(encoding="utf-8"))
    assert questions[0]["source_id"] == "bank-1"
    assert questions[0]["source_file"] == "bank.txt"
    for concept in concepts:
        assert concept["teaching_evidence_ids"] == ["ev-1"]
        assert concept["teaching_evidence"] == [{
            "id": "ev-1", "source_id": "guide-1", "source_file": "guide.pdf",
            "status": "input_provided", "relation": "supports", "page": 2,
            "snippet": "CPI 是成本绩效指数。",
            "region": {"x": 0.1, "y": 0.2, "width": 0.8, "height": 0.6},
        }]


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda payload: payload["teaching_evidence"][0].update(source_id="missing"), "不存在的 source_id"),
        (lambda payload: payload["teaching_evidence"][0]["locator"].update(page=3), "物理页范围"),
        (lambda payload: payload["concepts"][1].update(teaching_evidence_ids=[]), "双向一致"),
        (lambda payload: payload["sources"][1].update(path="../guide.pdf"), "越界路径"),
        (lambda payload: payload["teaching_evidence"][0]["locator"].update(excerpt=""), "非空节选"),
        (lambda payload: payload["teaching_evidence"][0].update(relation="guessed"), "relation 必须是"),
        (lambda payload: payload["questions"][0].pop("source_id"), "source_id 必须是"),
        (lambda payload: payload["questions"][0].update(source_id="guide-1", source_page=1), "role=question_bank"),
        (lambda payload: payload["questions"][0].update(source_file="bank.txt"), "只能使用 source_id/source_page"),
        (lambda payload: (payload["sources"][1].update(role="question_bank"),
                          payload["questions"][0].update(source_id="guide-1", source_page=3)), "有效物理页"),
        (lambda payload: payload["questions"][0].update(source_page=1), "非 PDF 题目"),
        (lambda payload: (payload["sources"][1].update(source_file="guide.pdf"),
                          payload["sources"][1].pop("path")), "不接受旧 source_file"),
        (lambda payload: (payload["teaching_evidence"][0].update(material_id="guide-1"),
                          payload["teaching_evidence"][0].pop("source_id")), "不接受旧 material_id"),
    ],
)
def test_v2_agent_content_rejects_invalid_explicit_provenance(tmp_path, mutate, message):
    payload = _v2_payload(tmp_path)
    mutate(payload)
    with pytest.raises(ContractError, match=message):
        generate_package(_write(tmp_path, payload), tmp_path / "bad",
                         profile_name="ruankao-xitixiangmu", agent_content=True)
    assert not (tmp_path / "bad").exists()


def test_agent_content_rejects_removed_v1_schema_and_top_level_materials_alias(tmp_path):
    payload = _agent_payload(tmp_path)
    payload["schema_version"] = "quick-pass-agent-content-v1"
    with pytest.raises(ContractError, match="quick-pass-agent-content-v2"):
        generate_package(_write(tmp_path, payload), tmp_path / "v1",
                         profile_name="ruankao-xitixiangmu", agent_content=True)

    payload = _agent_payload(tmp_path)
    payload["materials"] = payload.pop("sources")
    with pytest.raises(ContractError, match="不接受旧 materials"):
        generate_package(_write(tmp_path, payload), tmp_path / "materials-alias",
                         profile_name="ruankao-xitixiangmu", agent_content=True)
