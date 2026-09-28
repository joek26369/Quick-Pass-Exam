import base64
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from generator import ContractError, generate_package
from package_audit import audit_package


def inputs(tmp_path):
    original = tmp_path / "original"
    original.mkdir()
    (original / "教辅.txt").write_text("成本绩效指数等于挣值除以实际成本。", encoding="utf-8")
    (tmp_path / "guide.txt").write_bytes((original / "教辅.txt").read_bytes())
    (tmp_path / "bank.txt").write_text("题库原文", encoding="utf-8")
    (tmp_path / "page.png").write_bytes(base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aP1cAAAAASUVORK5CYII="))
    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps({"input_scope": {"root": str(original), "scopes": ["."]}, "files": [
        {"path": "教辅.txt", "decision": "included", "source_id": "guide"}
    ]}, ensure_ascii=False), encoding="utf-8")
    payload = {
        "schema_version": "quick-pass-agent-content-v2",
        "method_coverage": {"schema_version": "quick-pass-method-coverage-v1", "items": [{"question_id": "q1", "classification": "non_calculation", "reason": "识别 CPI 用途，不要求数值运算", "requirements": []}]},
        "sources": [{"id": "bank", "role": "question_bank", "path": "bank.txt"},
                    {"id": "guide", "role": "teaching_material", "path": "guide.txt"}],
        "questions": [{"id": "q1", "question_zh": "CPI 衡量什么？", "answer": "A",
                       "source_id": "bank", "concept_ids": ["c1"], "options": [
                           {"label": "A", "text": "成本效率", "is_correct": True}]}],
        "concepts": [{"id": "c1", "title": "成本绩效指数", "one_liner": "CPI 衡量成本效率。",
                      "source_questions": ["q1"], "teaching_evidence_ids": ["ev1"],
                      "cornell_note": {"pairing_status": "paired", "summary": "比较挣值与成本。",
                                       "pairs": [{"cue": "CPI？", "note": "挣值除以实际成本。"}]}}],
        "teaching_evidence": [{"id": "ev1", "source_id": "guide", "concept_ids": ["c1"],
                               "relation": "supports", "status": "input_provided",
                               "locator": {"excerpt": "成本绩效指数等于挣值除以实际成本。", "page_image": "page.png"}}],
    }
    path = tmp_path / "agent-content.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path, original, inventory


def generate(tmp_path):
    path, original, inventory = inputs(tmp_path)
    output = generate_package(path, tmp_path / "package", profile_name="ruankao-xitixiangmu",
                              agent_content=True, source_root=original, source_inventory=inventory)
    return output, original


def web_data(output):
    html = (output / "web/index.html").read_text(encoding="utf-8")
    offset = html.index("const DATA=") + len("const DATA=")
    web, end = json.JSONDecoder().raw_decode(html[offset:])
    return html, offset, end, web


def test_postflight_passes_and_freezes_inventory(tmp_path):
    output, _ = generate(tmp_path)
    assert (output / "data/source-inventory.json").is_file()
    assert json.loads((output / "manifest.json").read_text())["post_generation_status"] == "passed"
    assert audit_package(output, verify_manifest=True)["status"] == "passed"


@pytest.mark.parametrize("change,code", [
    ("edge", "WEB_EVIDENCE_MISMATCH"), ("snippet", "WEB_EVIDENCE_CONTENT_MISMATCH"),
    ("source", "SOURCE_ASSET_MISSING"), ("source_bytes", "COPIED_SOURCE_MISMATCH"),
    ("page", "PAGE_ASSET_MISSING"), ("new_original", "ORIGINAL_COVERAGE_FAILED"),
    ("original_bytes", "ORIGINAL_COVERAGE_FAILED"),
])
def test_postflight_detects_real_delivery_regressions(tmp_path, change, code):
    output, original = generate(tmp_path)
    html, offset, end, web = web_data(output)
    if change == "edge":
        web["teaching_evidence"] = []
    elif change == "snippet":
        web["teaching_evidence"][0]["snippet"] = "错误节选"
    elif change in ("source", "source_bytes"):
        asset = output / "web" / web["sources"][0]["source_file"]
        if change == "source":
            asset.unlink()
        else:
            asset.write_text("损坏后的内容")
    elif change == "page":
        (output / "web" / web["teaching_evidence"][0]["thumbnail"]).unlink()
    elif change == "new_original":
        (original / "后来添加的教辅.txt").write_text("新的资料")
    else:
        (original / "教辅.txt").write_text("更新后的原始资料")
    if change in ("edge", "snippet"):
        (output / "web/index.html").write_text(
            html[:offset] + json.dumps(web, ensure_ascii=False) + html[offset + end:], encoding="utf-8")
    report = audit_package(output)
    assert report["status"] == "blocked"
    assert code in {f["code"] for f in report["findings"]}
    assert report["repair_instructions"]


def test_generation_does_not_publish_broken_renderer_output(tmp_path, monkeypatch):
    import renderer
    actual = renderer.render_package

    def broken(*args, **kwargs):
        index = actual(*args, **kwargs)
        html = index.read_text(encoding="utf-8")
        at = html.index("const DATA=") + len("const DATA=")
        web, _ = json.JSONDecoder().raw_decode(html[at:])
        (index.parent / web["sources"][0]["source_file"]).unlink()
        return index

    monkeypatch.setattr(renderer, "render_package", broken)
    with pytest.raises(ContractError, match="生成后核对未通过"):
        generate(tmp_path)
    assert not (tmp_path / "package").exists()
    report = json.loads((tmp_path / "package.post-generation-check.json").read_text())
    assert report["status"] == "blocked"
    assert report["repair_instructions"]


def test_pinned_user_scope_cannot_be_replaced_by_staging_directory(tmp_path):
    path, original, inventory = inputs(tmp_path)
    staged = tmp_path / "staged"
    staged.mkdir()
    (staged / "教辅.txt").write_bytes((original / "教辅.txt").read_bytes())
    with pytest.raises(ContractError, match="input_scope 不一致"):
        generate_package(path, tmp_path / "package", profile_name="ruankao-xitixiangmu",
                         agent_content=True, source_root=staged, source_inventory=inventory)
    assert not (tmp_path / "package").exists()


def test_new_input_during_render_blocks_publication(tmp_path, monkeypatch):
    import renderer
    path, original, inventory = inputs(tmp_path)
    render = renderer.render_package

    def changed(*args, **kwargs):
        index = render(*args, **kwargs)
        (original / "new.txt").write_text("生成过程中新增的教辅")
        return index

    monkeypatch.setattr(renderer, "render_package", changed)
    with pytest.raises(ContractError, match="生成后核对未通过"):
        generate_package(path, tmp_path / "package", profile_name="ruankao-xitixiangmu",
                         agent_content=True, source_root=original, source_inventory=inventory)
    assert not (tmp_path / "package").exists()


def test_unpinned_legacy_inventory_does_not_claim_full_postflight_pass(tmp_path):
    path, original, inventory = inputs(tmp_path)
    data = json.loads(inventory.read_text())
    data.pop("input_scope")
    inventory.write_text(json.dumps(data), encoding="utf-8")
    output = generate_package(path, tmp_path / "package", profile_name="ruankao-xitixiangmu",
                              agent_content=True, source_root=original, source_inventory=inventory)
    report = audit_package(output, verify_manifest=True)
    assert report["status"] == "limited"
    assert report["input_scope_status"] == "not_checked"
    assert report["limitations"]
