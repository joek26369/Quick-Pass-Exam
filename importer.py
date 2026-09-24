"""Create a loss-aware Agent handoff from an explicit document input directory."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import shutil

from generator import ContractError


def import_bank(input_path: Path, output_dir: Path, *, resume_agent_contract: bool = False) -> Path:
    """Stage a document then create or resume an Agent question contract.

    This adapter never reads provider configuration or makes external calls.
    """
    from agent_preprocess import checked_output_root

    source = input_path.resolve()
    output_dir = checked_output_root(output_dir)
    suffix = source.suffix.lower()
    if suffix not in ('.docx', '.pdf', '.txt', '.md'):
        raise ContractError('题库导入支持 .docx/.pdf/.txt/.md；旧 .doc 请先另存为 .docx')
    if not source.is_file():
        raise ContractError('输入文件不存在')
    if output_dir.exists() and not resume_agent_contract:
        raise ContractError('导入输出目录已存在，拒绝覆盖')
    if resume_agent_contract and suffix not in ('.pdf', '.txt', '.md', '.docx'):
        raise ContractError('--resume-agent-contract 只支持 PDF/TXT/MD/DOCX Agent 中间契约')
    output_dir.mkdir(parents=True, exist_ok=resume_agent_contract)
    staged = output_dir / source.name
    if staged.is_symlink():
        raise ContractError("暂存源文件不得是符号链接")
    if not staged.exists():
        try:
            with source.open("rb") as reader, staged.open("xb") as writer:
                shutil.copyfileobj(reader, writer)
                writer.flush()
                os.fsync(writer.fileno())
        except FileExistsError as exc:
            raise ContractError("暂存源文件已存在或被并发创建，拒绝覆盖") from exc
        except Exception:
            staged.unlink(missing_ok=True)
            raise
    elif hashlib.sha256(staged.read_bytes()).digest() != hashlib.sha256(source.read_bytes()).digest():
        raise ContractError('导入目录中的源文件与当前输入不一致，拒绝覆盖')
    report = {'format_version': 1, 'source_name': source.name,
              'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
              'input_format': suffix, 'parser_origin': 'agent_preprocess.py/document_adapter.py',
              'status': 'running', 'warnings': []}
    try:
        if resume_agent_contract:
            from agent_preprocess import import_agent_contract
            target = import_agent_contract(source, output_dir)
            questions = json.loads(target.read_text(encoding='utf-8'))['questions']
            report.update(status='passed', parser='agent-question-contract', question_count=len(questions),
                          source_pages=[{'question_id': q['id'], 'page': q.get('source_page')} for q in questions],
                          agent_contract='agent-question-contract.json')
            return target

        if suffix == '.pdf':
            from agent_preprocess import prepare_agent_handoff
            contract = prepare_agent_handoff(staged, output_dir)
            pages = json.loads((output_dir / 'pages.json').read_text(encoding='utf-8')).get('pages', [])
            report.update(status='needs_agent_input', parser='agent-visual-handoff',
                          agent_contract=contract.name, agent_page_count=len(pages),
                          warnings=['已生成逐页图片、原生文本和待填写 Agent 中间契约。未调用 OCR、结构化模型或旧题库解析器。'])
            return contract
        if suffix in ('.txt', '.md'):
            from agent_preprocess import prepare_text_agent_handoff
            from document_adapter import text_document_payload
            content = text_document_payload(staged)
            contract = prepare_text_agent_handoff(staged, output_dir, text=content['text'], blocks=content['blocks'])
            report.update(status='needs_agent_input', parser='agent-text-handoff',
                          agent_contract=contract.name, agent_block_count=len(content['blocks']),
                          warnings=['已生成完整原文、确定性行块和待填写 Agent 中间契约。TXT/MD 不含物理页码。'])
            return contract
        from agent_preprocess import prepare_docx_agent_handoff
        from agent_preprocess import _check_managed_path
        from document_adapter import docx_document_payload
        assets_dir = output_dir / 'embedded-images'
        _check_managed_path(assets_dir, output_dir)
        content = docx_document_payload(staged, assets_dir)
        contract = prepare_docx_agent_handoff(staged, output_dir, content=content)
        report.update(status='needs_agent_input', parser='agent-docx-handoff', agent_contract=contract.name,
                      agent_item_count=len(content['items']),
                      warnings=['已保留 DOCX 段落、表格和嵌入图片引用，等待 Agent 回填题目；未调用旧题库解析器。'])
        return contract
    except ValueError as exc:
        report['status'] = 'failed'
        raise ContractError(str(exc)) from exc
    except Exception:
        report['status'] = 'failed'
        raise
    finally:
        report['structuring_usage'] = {'attempts': 0, 'tokens': None}
        report['structuring_attempts'] = []
        report['extraction'] = {'external_ocr_attempts': 0}
        report['cost_scope'] = 'Agent handoff stage uses no OCR or structuring provider. Knowledge generation usage is separate.'
        from agent_preprocess import _write_json
        _write_json(output_dir / 'import-report.json', report)
