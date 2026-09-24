"""Loss-aware Agent handoff tests; they never call provider or legacy parsers."""
import json
import base64
import zipfile
from pathlib import Path
import sys
import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from importer import import_bank
from document_adapter import docx_document_payload
from generator import ContractError


def test_importer_rejects_existing_output_and_old_doc(tmp_path):
    src=tmp_path/'bank.txt';src.write_text('1、题目')
    with pytest.raises(ContractError, match='已存在'):
        import_bank(src,tmp_path)
    old=tmp_path/'bank.doc';old.write_bytes(b'old')
    with pytest.raises(ContractError,match='另存'):
        import_bank(old,tmp_path/'out')


def test_docx_handoff_preserves_body_order_table_and_embedded_image(tmp_path):
    docx=pytest.importorskip('docx')
    src=tmp_path/'sample.docx';doc=docx.Document()
    doc.add_paragraph('段落一')
    table=doc.add_table(rows=1, cols=2)
    table.cell(0,0).text='单元格 A'; table.cell(0,1).text='单元格 B'
    doc.add_paragraph('段落二')
    png=tmp_path/'image.png'
    png.write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScL9pAAAAABJRU5ErkJggg=='))
    doc.add_picture(str(png))
    doc.save(src); before=src.read_bytes()
    contract_path=import_bank(src,tmp_path/'out')
    contract=json.loads(contract_path.read_text())
    content=json.loads((tmp_path/'out'/'document-content.json').read_text())
    assert contract['source_kind']=='docx'
    assert [item['kind'] for item in content['items'][:3]] == ['paragraph','table','paragraph']
    assert content['items'][0]['text']=='段落一'
    assert content['items'][1]['rows'][0][0]['text']=='单元格 A'
    image_item=next(item for item in content['items'] if item['kind']=='paragraph' and item['images'])
    assert (tmp_path/'out'/'embedded-images'/image_item['images'][0]).is_file()
    assert src.read_bytes()==before
    assert not (tmp_path/'out'/'questions.json').exists()


def test_docx_preserves_tabs_breaks_content_controls_and_warns_for_lossy_objects(tmp_path):
    docx = pytest.importorskip('docx')
    from docx.oxml import OxmlElement
    source = tmp_path / 'rich.docx'
    doc = docx.Document()
    paragraph = doc.add_paragraph()
    paragraph.add_run('前').add_tab()
    paragraph.add_run('中').add_break()
    paragraph.add_run('后')
    outer = doc.add_table(rows=1, cols=1)
    outer.cell(0, 0).text = '外层'
    outer.cell(0, 0).add_table(rows=1, cols=1).cell(0, 0).text = '内层'
    wrapped = OxmlElement('w:sdt')
    content = OxmlElement('w:sdtContent')
    wrapped_paragraph = OxmlElement('w:p')
    run = OxmlElement('w:r'); text = OxmlElement('w:t'); text.text = '内容控件段落'
    run.append(text); wrapped_paragraph.append(run); content.append(wrapped_paragraph); wrapped.append(content)
    doc._body._element.append(wrapped)
    formula = OxmlElement('m:oMath')
    paragraph._p.append(formula)
    paragraph._p.append(OxmlElement('w:object'))
    doc.save(source)

    payload = docx_document_payload(source, tmp_path / 'assets')
    assert payload['items'][0]['text'] == '前\t中\n后'
    assert any(item['kind'] == 'paragraph' and item['text'] == '内容控件段落' for item in payload['items'])
    codes = {warning['code'] for warning in payload['warnings']}
    assert {'FORMULA_UNEXTRACTED', 'OBJECT_UNEXTRACTED', 'NESTED_TABLE_UNEXTRACTED'} <= codes


def test_docx_asset_directory_and_target_reject_symlinks(tmp_path):
    docx = pytest.importorskip('docx')
    source = tmp_path / 'image.docx'
    png = tmp_path / 'image.png'
    png.write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScL9pAAAAABJRU5ErkJggg=='))
    doc = docx.Document(); doc.add_picture(str(png)); doc.save(source)
    target_dir = tmp_path / 'target'; target_dir.mkdir()
    symlink_dir = tmp_path / 'symlink-assets'; symlink_dir.symlink_to(target_dir, target_is_directory=True)
    with pytest.raises(ValueError, match='符号链接'):
        docx_document_payload(source, symlink_dir)
    assets = tmp_path / 'assets'; assets.mkdir()
    with zipfile.ZipFile(source) as archive:
        media_name = Path(next(name for name in archive.namelist() if name.startswith('word/media/'))).name
    (assets / f'001-{media_name}').symlink_to(png)
    with pytest.raises(ValueError, match='符号链接'):
        docx_document_payload(source, assets)


def test_empty_docx_still_creates_agent_contract_without_questions(tmp_path):
    docx=pytest.importorskip('docx');src=tmp_path/'empty.docx';docx.Document().save(src)
    contract=import_bank(src,tmp_path/'out')
    assert contract.name=='agent-question-contract.json'
    assert not (tmp_path/'out/questions.json').exists()
    assert json.loads((tmp_path/'out/import-report.json').read_text())['status']=='needs_agent_input'


def test_docx_agent_contract_rejects_fabricated_page_number(tmp_path):
    docx = pytest.importorskip('docx')
    source = tmp_path / 'sample.docx'
    docx.Document().save(source)
    output = tmp_path / 'handoff'
    contract_path = import_bank(source, output)
    contract = json.loads(contract_path.read_text())
    contract['questions'] = [{
        'id': 'agent_docx_001', 'question_zh': '题干',
        'options': [{'label': 'A', 'text': '正确', 'is_correct': True}], 'answer': 'A', 'source_page': 1,
    }]
    contract_path.write_text(json.dumps(contract, ensure_ascii=False), encoding='utf-8')
    with pytest.raises(ContractError, match='非 PDF'):
        import_bank(source, output, resume_agent_contract=True)
    assert not (output / 'questions.json').exists()


def _scanned_pdf(path: Path, pages: int = 2) -> None:
    from reportlab.pdfgen import canvas
    document = canvas.Canvas(str(path))
    for _ in range(pages):
        # Vector marks, but no text layer: the importer must treat this as
        # visual material and must not send it to a provider by default.
        document.rect(36, 36, 144, 84)
        document.showPage()
    document.save()


def test_scanned_pdf_creates_resumable_agent_handoff(tmp_path):
    source = tmp_path / 'scan.pdf'
    _scanned_pdf(source)
    output = tmp_path / 'handoff'
    contract_path = import_bank(source, output)
    assert contract_path.name == 'agent-question-contract.json'
    contract = json.loads(contract_path.read_text())
    pages = json.loads((output / 'pages.json').read_text())['pages']
    assert contract['status'] == 'needs_agent_transcription'
    assert [page['physical_page'] for page in pages] == [1, 2]
    assert all((output / page['image']).is_file() for page in pages)
    report = json.loads((output / 'import-report.json').read_text())
    assert report['status'] == 'needs_agent_input'
    assert report['structuring_attempts'] == []

    contract['questions'] = [{
        'id': 'agent_q_001', 'question_zh': '题干',
        'options': [{'label': 'A', 'text': '正确', 'is_correct': True}],
        'answer': 'A', 'source_page': 2,
    }]
    contract_path.write_text(json.dumps(contract, ensure_ascii=False), encoding='utf-8')
    questions_path = import_bank(source, output, resume_agent_contract=True)
    question = json.loads(questions_path.read_text())['questions'][0]
    assert question['source_file'] == 'scan.pdf'
    assert question['source_page'] == 2
    report = json.loads((output / 'import-report.json').read_text())
    assert report['status'] == 'passed' and report['parser'] == 'agent-question-contract'


def test_agent_contract_rejects_out_of_range_page_without_publishing_questions(tmp_path):
    source = tmp_path / 'scan.pdf'
    _scanned_pdf(source, pages=1)
    output = tmp_path / 'handoff'
    contract_path = import_bank(source, output)
    contract = json.loads(contract_path.read_text())
    contract['questions'] = [{
        'id': 'agent_q_001', 'question_zh': '题干',
        'options': [{'label': 'A', 'text': '正确', 'is_correct': True}],
        'answer': 'A', 'source_page': 2,
    }]
    contract_path.write_text(json.dumps(contract, ensure_ascii=False), encoding='utf-8')
    with pytest.raises(ContractError, match='确定物理页'):
        import_bank(source, output, resume_agent_contract=True)
    assert not (output / 'questions.json').exists()


def test_agent_contract_rejects_tampered_page_manifest(tmp_path):
    source = tmp_path / 'scan.pdf'
    _scanned_pdf(source, pages=1)
    output = tmp_path / 'handoff'
    contract_path = import_bank(source, output)
    contract = json.loads(contract_path.read_text())
    contract['questions'] = [{
        'id': 'agent_q_001', 'question_zh': '题干',
        'options': [{'label': 'A', 'text': '正确', 'is_correct': True}], 'answer': 'A', 'source_page': 2,
    }]
    contract_path.write_text(json.dumps(contract, ensure_ascii=False), encoding='utf-8')
    pages_path = output / 'pages.json'
    pages = json.loads(pages_path.read_text())
    pages['pages'][0]['physical_page'] = 2
    pages_path.write_text(json.dumps(pages, ensure_ascii=False), encoding='utf-8')
    with pytest.raises(ContractError, match='实际物理页'):
        import_bank(source, output, resume_agent_contract=True)
    assert not (output / 'questions.json').exists()


def test_txt_creates_full_text_block_contract_and_resumes_without_page_numbers(tmp_path):
    source = tmp_path / 'bank.txt'
    source.write_text('1、第一题\nA. 正确\nB. 错误\n\n2、第二题\nA. 正确\nB. 错误', encoding='utf-8')
    output = tmp_path / 'handoff'
    contract_path = import_bank(source, output)
    contract = json.loads(contract_path.read_text())
    blocks = json.loads((output / 'text-blocks.json').read_text())
    assert contract['source_kind'] == 'text'
    assert len(blocks['blocks']) == 2
    assert blocks['text'] == source.read_text(encoding='utf-8')
    assert not (output / 'pages.json').exists()

    contract['questions'] = [{
        'id': 'agent_text_001', 'question_zh': '第一题',
        'options': [{'label': 'A', 'text': '正确', 'is_correct': True}], 'answer': 'A',
    }]
    contract_path.write_text(json.dumps(contract, ensure_ascii=False), encoding='utf-8')
    questions_path = import_bank(source, output, resume_agent_contract=True)
    question = json.loads(questions_path.read_text())['questions'][0]
    assert question['source_file'] == 'bank.txt'
    assert 'source_page' not in question and 'page_no' not in question


def test_text_agent_contract_rejects_fabricated_page_number(tmp_path):
    source = tmp_path / 'bank.md'
    source.write_text('1. 题目\nA. 正确', encoding='utf-8')
    output = tmp_path / 'handoff'
    contract_path = import_bank(source, output)
    contract = json.loads(contract_path.read_text())
    contract['questions'] = [{
        'id': 'agent_text_001', 'question_zh': '题目',
        'options': [{'label': 'A', 'text': '正确', 'is_correct': True}], 'answer': 'A', 'source_page': 1,
    }]
    contract_path.write_text(json.dumps(contract, ensure_ascii=False), encoding='utf-8')
    with pytest.raises(ContractError, match='不得填写'):
        import_bank(source, output, resume_agent_contract=True)
    assert not (output / 'questions.json').exists()


def test_native_text_pdf_uses_agent_contract_with_native_text(tmp_path):
    from reportlab.pdfgen import canvas
    source = tmp_path / 'native.pdf'
    document = canvas.Canvas(str(source))
    document.drawString(72, 760, 'This PDF has a native text layer. ' * 4)
    document.save()
    contract_path = import_bank(source, tmp_path / 'handoff')
    contract = json.loads(contract_path.read_text())
    pages = json.loads((tmp_path / 'handoff' / 'pages.json').read_text())['pages']
    assert contract['source_kind'] == 'pdf'
    assert pages[0]['physical_page'] == 1
    assert pages[0]['native_text_characters'] > 40
    assert 'native text layer' in pages[0]['native_text']


def test_importer_has_no_legacy_parser_or_provider_runtime_dependency():
    text = (ROOT / 'importer.py').read_text(encoding='utf-8')
    assert 'bank_parser' not in text
    assert '_client' not in text and '_ocr_config' not in text


def test_import_rejects_symlink_output_root_and_staged_source(tmp_path):
    source = tmp_path / 'bank.txt'
    source.write_text('1、题目\nA. 正确', encoding='utf-8')
    real_output = tmp_path / 'real-output'
    real_output.mkdir()
    linked_output = tmp_path / 'linked-output'
    linked_output.symlink_to(real_output, target_is_directory=True)
    with pytest.raises(ContractError, match='符号链接'):
        import_bank(source, linked_output)

    output = tmp_path / 'resume-output'
    output.mkdir()
    (output / source.name).symlink_to(source)
    with pytest.raises(ContractError, match='暂存源文件不得是符号链接'):
        import_bank(source, output, resume_agent_contract=True)


def test_import_canonicalizes_symlink_parent_but_not_output_root(tmp_path):
    """A normal macOS /tmp-style parent alias must remain usable."""
    source = tmp_path / 'bank.txt'
    source.write_text('1. 题目\nA. 答案', encoding='utf-8')
    real_parent = tmp_path / 'real-parent'
    real_parent.mkdir()
    alias_parent = tmp_path / 'parent-alias'
    alias_parent.symlink_to(real_parent, target_is_directory=True)

    contract = import_bank(source, alias_parent / 'handoff')

    assert contract == (real_parent / 'handoff' / 'agent-question-contract.json').resolve()
    assert contract.is_file()


def test_failed_resume_never_follows_report_symlink(tmp_path):
    source = tmp_path / 'bank.txt'
    source.write_text('1、题目\nA. 正确', encoding='utf-8')
    output = tmp_path / 'handoff'
    contract_path = import_bank(source, output)
    contract = json.loads(contract_path.read_text())
    contract['source_sha256'] = 'wrong'
    contract_path.write_text(json.dumps(contract), encoding='utf-8')
    outside = tmp_path / 'outside-report.json'
    outside.write_text('do-not-overwrite', encoding='utf-8')
    report = output / 'import-report.json'
    report.unlink()
    report.symlink_to(outside)

    with pytest.raises(ContractError, match='符号链接'):
        import_bank(source, output, resume_agent_contract=True)

    assert outside.read_text(encoding='utf-8') == 'do-not-overwrite'
    assert not (output / 'questions.json').exists()


def test_resume_rejects_dangling_questions_symlink(tmp_path):
    source = tmp_path / 'bank.txt'
    source.write_text('1、题目\nA. 正确', encoding='utf-8')
    output = tmp_path / 'handoff'
    contract_path = import_bank(source, output)
    contract = json.loads(contract_path.read_text())
    contract['questions'] = [{
        'id': 'q1', 'question_zh': '题目', 'answer': 'A',
        'options': [{'label': 'A', 'text': '正确', 'is_correct': True}],
    }]
    contract_path.write_text(json.dumps(contract, ensure_ascii=False), encoding='utf-8')
    outside = tmp_path / 'outside-questions.json'
    (output / 'questions.json').symlink_to(outside)

    with pytest.raises(ContractError, match='符号链接'):
        import_bank(source, output, resume_agent_contract=True)

    assert not outside.exists()


def test_pdf_handoff_rejects_symlink_page_directory_and_page_target(tmp_path):
    from agent_preprocess import prepare_agent_handoff

    source = tmp_path / 'scan.pdf'
    _scanned_pdf(source, pages=1)
    outside = tmp_path / 'outside-pages'
    outside.mkdir()
    output = tmp_path / 'linked-pages-output'
    output.mkdir()
    (output / 'pages').symlink_to(outside, target_is_directory=True)
    with pytest.raises(ContractError, match='符号链接'):
        prepare_agent_handoff(source, output)

    output = tmp_path / 'linked-page-output'
    output.mkdir()
    pages = output / 'pages'
    pages.mkdir()
    outside_page = tmp_path / 'outside-page.png'
    (pages / 'page-0001.png').symlink_to(outside_page)
    with pytest.raises(ContractError, match='符号链接'):
        prepare_agent_handoff(source, output)
    assert not outside_page.exists()
