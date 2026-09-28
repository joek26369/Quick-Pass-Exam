/* Read-only fidelity sections for fields already produced by the main pipeline.
 * These functions never fetch sources or infer trust. All learner text reaches
 * the DOM through the existing textContent-based helpers. */
function fidelityText(value) {
  if (typeof value === 'string') return value;
  if (!value || typeof value !== 'object') return '';
  return String(value.text || value.title || value.source_id || value.source_file || value.url || '未命名来源');
}

function fidelityList(value) {
  return Array.isArray(value) ? value.filter(item => item !== null && item !== undefined) : [];
}

function renderQuestionTrustWarning(parent, question) {
  const sourceLabel = question.source_paper || question.source_name || question.question_origin;
  if (sourceLabel) callout(parent, '来源题目（输入声明）', String(sourceLabel));
  const generated = question.generated_analysis || {};
  if (question.answer_mismatch || generated.answer_mismatch) {
    callout(parent, '答案存疑', '题库答案与模型辅助判断存在冲突；请提交答案后查看详情，并回到原始题库或来源资料核对。', 'warning');
  }
}

function renderAnswerMismatchDetails(parent, question, generated) {
  const mismatch = generated || question;
  if (!mismatch || !mismatch.answer_mismatch) return;
  const modelAnswer = mismatch.llm_answer || mismatch.answer || mismatch.model_answer || '未提供';
  const prefix = generated ? '模型辅助判断' : '模型判断';
  callout(parent, generated ? '模型生成答案冲突详情' : '答案冲突详情',
    `题库答案为 ${question.answer || '未提供'}；${prefix}为 ${modelAnswer}。请以原始题库或来源资料的复核结果为准。`, 'warning');
}

function renderQuestionLearningDetails(parent, question, titlePrefix = '') {
  const title = value => titlePrefix ? `模型生成${value}` : value;
  const points = fidelityList(question.core_exam_points);
  if (points.length) {
    add(parent, 'h3', title('核心考点'));
    for (const point of points) {
      if (!point || typeof point !== 'object') continue;
      callout(parent, String(point.title || '考点'), String(point.body || point.text || ''));
    }
  }
  const solution = question.calc_solution;
  if (solution && typeof solution === 'object') {
    const parts = [];
    if (solution.method_name) parts.push(`方法：${solution.method_name}`);
    if (solution.steps) parts.push(`步骤：${solution.steps}`);
    if (solution.common_patterns) parts.push(`常见模式：${solution.common_patterns}`);
    if (parts.length) callout(parent, title('计算步骤'), parts.join('\n'));
  }
  const expansions = fidelityList(question.knowledge_expansion);
  if (expansions.length) {
    add(parent, 'h3', title('扩展知识'));
    for (const item of expansions) {
      if (!item || typeof item !== 'object') continue;
      callout(parent, String(item.topic || '扩展要点'), String(item.body || item.text || ''));
    }
  }
  const method = question.method_extract;
  if (method && typeof method === 'object') {
    const parts = [];
    const labels = {method_name: '方法', steps: '步骤', description: '说明', applicable_conditions: '适用条件', common_patterns: '常见模式'};
    for (const key of Object.keys(labels)) {
      if (method[key]) parts.push(`${labels[key]}：${method[key]}`);
    }
    if (parts.length) callout(parent, title('方法论抽取'), parts.join('\n'));
  }
}

function conceptQuestionIds(concept) {
  const origins = fidelityList(concept.question_origins).map(item => typeof item === 'string' ? item : item && item.question_id);
  return [...new Set([...fidelityList(concept.question_ids), ...fidelityList(concept.related_questions), ...fidelityList(concept.source_questions), ...origins].filter(id => typeof id === 'string' && id))];
}

function renderConceptQuestionLinks(parent, concept) {
  const ids = conceptQuestionIds(concept);
  if (!ids.length) return;
  add(parent, 'h3', '关联题目');
  const links = add(parent, 'div', undefined, 'related-question-list');
  for (const id of ids) {
    if (QMAP[id]) links.append(relatedQuestionButton(id, () => { state.view = 'quiz'; state.qid = id; state.search = ''; render(); }));
    else if (typeof CASES !== 'undefined' && CASES.some(c => (c.sub_questions || []).some(q => q.id === id))) links.append(relatedQuestionButton(id, () => { state.view = 'cases'; state.childId = id; render(); }));
    else add(links, 'span', `${id}（不在本学习包）`);
  }
}

function fidelityReferences(value) {
  const seen = new Set();
  return fidelityList(value).flatMap(item => {
    const raw = fidelityText(item);
    const page = item && typeof item === 'object' ? (item.source_page ?? item.page_no ?? item.page) : null;
    const status = item && typeof item === 'object' ? item.verification_status || '' : '';
    const key = JSON.stringify([raw, page, status]);
    if (seen.has(key)) return [];
    seen.add(key);
    const name = raw.replace(/\\/g, '/').split('/').pop().replace(/^sub_[a-z0-9]+_(?:(?:quiz|syllabus)_)?\d+_/, '');
    return [{raw, label: name + (page ? ` · 第 ${page} 页` : '')}];
  });
}

function renderConceptFidelityDetails(parent, concept) {
  const box = add(parent, 'details');
  add(box, 'summary', '查看来源');
  const groups = [
    ['输入提供的来源（未额外核验）', concept.canonical_references],
    ['旧式来源字段（未核验）', concept.references],
    ['模型建议来源（未核验）', concept.unverified_generated_references],
  ];
  let count = 0;
  for (const [title, values] of groups) {
    const rows = fidelityReferences(values);
    if (!rows.length) continue;
    count += rows.length;
    add(box, 'h3', title);
    const list = add(box, 'ul');
    for (const row of rows) {
      const item = add(list, 'li', row.label);
      item.title = row.raw;
    }
  }
  if (count) callout(box, '来源状态', '来源信息按输入保留，未额外核验；旧式字段和模型建议不自动视为可信来源或教辅证据。具体内容请结合原题与教辅原页核对。', 'warning');
  else callout(box, '外部来源', '未提供可追溯的来源；关联题目不等于教材证据。', 'warning');
}

// Only explicitly authored relationships become learning links. Chapter order is not a prerequisite.
function renderConceptLearningLinks(parent, concept) {
  const rel = concept.learning_relations;
  if (!rel || typeof rel !== 'object' || Array.isArray(rel)) return;
  const groups = [['prerequisites','前置知识'], ['related_concepts','关联知识'], ['next_concepts','后续学习']];
  const rows = groups.map(([key,title]) => [title, [...new Set(fidelityList(rel[key]).filter(id => typeof id === 'string' && id && id !== concept.id))]]).filter(([,ids])=>ids.length);
  if (!rows.length) return;
  add(parent,'h3','知识关联与学习路径');
  for (const [title,ids] of rows) {
    add(parent,'h4',title);
    const links=add(parent,'div',undefined,'links');
    for (const id of ids) {
      const target=CMAP[id];
      if (target) links.append(linkButton(target.title||id,()=>{state.view='notes';state.cid=id;state.search='';render();}));
      else add(links,'span',`${id}（不在本学习包）`);
    }
  }
}
