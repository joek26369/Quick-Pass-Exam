"""Audit Agent-declared calculation coverage; never infer semantic correctness."""
from __future__ import annotations

SCHEMA = 'quick-pass-method-coverage-v1'
REPAIR = [
    '逐题阅读选择题和案例背景、小问、图表，填写 method_coverage.items；非计算题也须说明分类理由。',
    '按实际算法、输入条件和单位分类，不能按考点标签批量挂卡；一问可需要多个计算类型。',
    '补齐或拆分方法卡，保留既有题目与学习记录；每张计算卡声明一个 calculation_type，可在同一算法内说明不同条件。',
    '核对每个 requirement 的方法正文确实教会该算法；没有可靠依据则标 unresolved，不能填无关卡过关。',
    '在新目录生成，复查 reports/method-coverage.json 与生成后报告，再逐类型浏览器验收并补报缺口。',
]


def audit_method_coverage(questions, cases, methods, inventory, *, required=False):
    findings = []
    def fail(code, target, message):
        findings.append(dict(code=code, target=target, message=message))
    units = [(q['id'], q.get('question_zh') or q.get('question_en') or q.get('question', ''), 'choice', q)
             for q in questions]
    units += [(s['id'], c.get('scenario', '') + '\n' + s.get('question', ''), 'case', s)
              for c in cases for s in c.get('sub_questions', [])]
    unit_map = {u[0]: u for u in units}
    method_map = {m['id']: m for m in methods}
    if inventory is None:
        fail('METHOD_REVIEW_MISSING', 'method_coverage', '缺少全题计算分类清单；不能确认方法覆盖完整')
        return dict(status='blocked' if required else 'limited', findings=findings,
                    semantic_verification='not_performed', repair_instructions=REPAIR,
                    question_count=len(units), reviewed_count=0)
    items = inventory.get('items') if isinstance(inventory, dict) else None
    if not isinstance(items, list) or inventory.get('schema_version') != SCHEMA:
        fail('METHOD_REVIEW_INVALID', 'method_coverage', '清单版本或 items 无效')
        items = []
    reviewed = set()
    used = set()
    calculation_count = 0
    for row in items:
        if not isinstance(row, dict):
            fail('METHOD_REVIEW_INVALID', 'items', '条目必须是对象'); continue
        qid = row.get('question_id')
        if not isinstance(qid, str) or qid not in unit_map or qid in reviewed:
            fail('METHOD_REVIEW_ID_INVALID', str(qid), '题目不存在或重复登记'); continue
        reviewed.add(qid)
        _, text, kind, question = unit_map[qid]
        status = row.get('classification')
        if status not in ('calculation', 'non_calculation', 'unresolved'):
            fail('METHOD_CLASSIFICATION_INVALID', qid, '分类必须为 calculation/non_calculation/unresolved')
        if not isinstance(row.get('reason'), str) or not row['reason'].strip():
            fail('METHOD_REASON_MISSING', qid, '须说明题意与分类理由')
        if status == 'unresolved':
            fail('METHOD_REVIEW_UNRESOLVED', qid, '题型尚未核定，需回查原题或图表')
        requirements = row.get('requirements')
        if not isinstance(requirements, list):
            fail('METHOD_REQUIREMENTS_INVALID', qid, 'requirements 必须为数组'); continue
        if status == 'non_calculation' and requirements:
            fail('METHOD_CLASSIFICATION_CONFLICT', qid, '非计算题不得声明计算覆盖')
        if status != 'calculation':
            continue
        calculation_count += 1
        excerpt = row.get('input_excerpt')
        if not isinstance(excerpt, str) or not excerpt.strip() or excerpt not in text:
            fail('METHOD_INPUT_EXCERPT_INVALID', qid, '须摘录当前题干/背景中可核对的计算要求；图片信息应先忠实转录')
        if not requirements:
            fail('METHOD_REQUIREMENT_MISSING', qid, '计算题未声明所需算法及方法卡')
        types = set()
        for req in requirements:
            if not isinstance(req, dict):
                fail('METHOD_REQUIREMENTS_INVALID', qid, '计算需求必须是对象'); continue
            typ, mid = req.get('type_id'), req.get('method_id')
            if not isinstance(typ, str) or not typ.strip() or typ in types:
                fail('METHOD_TYPE_INVALID', qid, '算法类型为空或重复'); continue
            types.add(typ)
            method = method_map.get(mid) if isinstance(mid, str) else None
            if not method or method.get('type') != 'calculation' or method.get('calculation_type') != typ:
                fail('METHOD_TYPE_MISMATCH', qid, f'{typ} 未匹配同类型计算卡：{mid}'); continue
            used.add(mid)
            if not isinstance(req.get('reason'), str) or not req['reason'].strip():
                fail('METHOD_FIT_REASON_MISSING', qid, '须说明卡片步骤如何满足本问条件')
            link_field = 'question_ids' if kind == 'choice' else 'sub_question_ids'
            if qid not in method.get(link_field, []):
                fail('METHOD_LINK_MISSING', qid, f'{mid}.{link_field} 缺少本题')
            if kind == 'case' and mid not in question.get('method_ids', []):
                fail('METHOD_LINK_MISSING', qid, f'小问 method_ids 缺少 {mid}')
    for qid in sorted(set(unit_map) - reviewed):
        fail('METHOD_QUESTION_UNREVIEWED', qid, '题目未逐题分类')
    for m in methods:
        mid = m['id']
        for field, kind in [('question_ids', 'choice'), ('sub_question_ids', 'case')]:
            ids = m.get(field, [])
            if not isinstance(ids, list) or any(not isinstance(x, str) for x in ids):
                fail('METHOD_LINK_INVALID', mid, f'{field} 必须是 ID 数组'); continue
            if len(ids) != len(set(ids)) or any(x not in unit_map or unit_map[x][2] != kind for x in ids):
                fail('METHOD_LINK_INVALID', mid, f'{field} 有重复或不存在的题目')
        if m.get('type') != 'calculation':
            continue
        for field in ('calculation_type', 'applicability', 'formula', 'units', 'assumptions'):
            if not isinstance(m.get(field), str) or not m[field].strip():
                fail('METHOD_CONTENT_MISSING', mid, f'缺少 {field}')
        for field in ('steps', 'input_requirements', 'case_basis'):
            if not isinstance(m.get(field), list) or not m[field]:
                fail('METHOD_CONTENT_MISSING', mid, f'缺少 {field}')
        for field in ('steps', 'input_requirements'):
            if isinstance(m.get(field), list) and any(not isinstance(x, str) or not x.strip() for x in m[field]):
                fail('METHOD_CONTENT_MISSING', mid, f'{field} 必须是非空字符串数组')
        if mid not in used:
            fail('METHOD_CALCULATION_UNUSED', mid, '计算卡没有经逐题审查确认的适用题；检查错误关联或改为合适的非计算卡')
    return dict(status='blocked' if findings else 'passed', findings=findings,
                semantic_verification='agent_declared_not_independently_verified',
                question_count=len(units), reviewed_count=len(reviewed),
                calculation_question_count=calculation_count, covered_method_count=len(used),
                repair_instructions=REPAIR if findings else [])
