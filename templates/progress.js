// Study state belongs to a local learner. The loopback library is the only
// supported automatic cross-package store; file:// receives a per-file fallback.
const StudyProgress = (() => {
  const match = location.protocol === 'http:' && location.hostname === '127.0.0.1'
    ? location.pathname.match(/^\/packages\/([a-f0-9]{16})\/web\/index\.html$/) : null;
  const endpoint = match ? `/api/packages/${match[1]}` : null;
  const localKey = `quick-pass-study-v1:${DATA.profile?.exam_code || 'default'}:${location.pathname}`;

  function localWrongbook(saved) {
    const answers = saved.answers || {}, bookmarked = new Set(saved.saved_choices || []);
    const dismissed = new Set(saved.dismissed_choices || []);
    const choices = [...new Set([...Object.keys(answers), ...bookmarked])]
      .filter(qid => bookmarked.has(qid) || (!answers[qid]?.ok && !dismissed.has(qid)))
      .filter(qid => QMAP[qid])
      .map(qid => ({kind: 'choice', qid, stem: QMAP[qid].question_zh || qid,
        wrong_count: answers[qid] && !answers[qid].ok ? 1 : 0, picked: answers[qid]?.picked || [], saved: bookmarked.has(qid)}));
    const cases = (saved.case_bookmarks || []).filter(id => CASEMAP[id])
      .map(case_id => ({kind: 'case', case_id, stem: CASEMAP[case_id].original_number || case_id}));
    return [...choices, ...cases];
  }

  function apply(saved) {
    state.answers = Object.assign(Object.create(null), saved.answers || {});
    state.picked = Object.create(null);
    for (const [qid, answer] of Object.entries(state.answers)) {
      if (Array.isArray(answer.picked)) state.picked[qid] = [...answer.picked];
    }
    state.savedChoices = Array.isArray(saved.saved_choices) ? saved.saved_choices : [];
    state.dismissedChoices = Array.isArray(saved.dismissed_choices) ? saved.dismissed_choices : [];
    state.caseBookmarks = Array.isArray(saved.case_bookmarks) ? saved.case_bookmarks : [];
    state.wrongbook = endpoint ? (Array.isArray(saved.wrongbook) ? saved.wrongbook : []) : localWrongbook(saved);
  }

  function saveLocal(saved) {
    localStorage.setItem(localKey, JSON.stringify(saved));
    apply(saved);
  }

  async function changeBookmark(payload) {
    const response = await fetch(endpoint + '/wrongbook', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload),
    });
    if (!response.ok) throw new Error('错题本未保存；请确认本地学习库仍在运行');
    apply(await response.json());
  }

  async function load() {
    if (endpoint) {
      const response = await fetch(endpoint + '/progress', {cache: 'no-store'});
      if (!response.ok) throw new Error('本地学习库无法读取作答记录');
      apply(await response.json());
      state.storageStatus = '已连接本地学习库 · 刷新及新学习包继承记录';
      return;
    }
    // Browser treatment of file:// storage differs. Keep this useful for
    // refresh/reopen, but never promise cross-package persistence here.
    const probe = localKey + ':probe';
    localStorage.setItem(probe, '1');
    localStorage.removeItem(probe);
    const value = localStorage.getItem(localKey);
    if (value) apply(JSON.parse(value));
    state.storageStatus = '当前为 file:// 单文件模式；若图片或 PDF 未随目录打开，请让 Agent 使用电脑端学习库返回的 http:// 地址';
  }

  async function record(q, picked) {
    if (endpoint) {
      const response = await fetch(endpoint + '/answer', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({qid: q.id, picked}),
      });
      if (!response.ok) throw new Error('作答未保存；请确认本地学习库仍在运行');
      const result = await response.json();
      apply(result);
      return;
    }
    const correct = q.options.filter(x => x.is_correct).map(x => x.label);
    const answers = Object.assign(Object.create(null), state.answers);
    answers[q.id] = {ok: picked.length === correct.length && correct.every(x => picked.includes(x)), picked: [...picked]};
    const dismissed_choices = answers[q.id].ok ? state.dismissedChoices :
      state.dismissedChoices.filter(id => id !== q.id);
    // Save first. A quota/security failure must not be shown as a completed answer.
    saveLocal({answers, saved_choices: state.savedChoices,
      dismissed_choices, case_bookmarks: state.caseBookmarks});
  }

  async function bookmarkChoice(q, save) {
    if (endpoint) return changeBookmark({kind: 'choice', action: save ? 'add' : 'remove', qid: q.id});
    const saved_choices = state.savedChoices.filter(id => id !== q.id);
    if (save) saved_choices.push(q.id);
    const dismissed_choices = save ? state.dismissedChoices.filter(id => id !== q.id) :
      [...new Set([...state.dismissedChoices, q.id])];
    saveLocal({answers: state.answers, saved_choices, dismissed_choices,
      case_bookmarks: state.caseBookmarks});
  }

  async function bookmarkCase(c, save) {
    if (endpoint) return changeBookmark({kind: 'case', action: save ? 'add' : 'remove', case_id: c.id});
    const case_bookmarks = state.caseBookmarks.filter(id => id !== c.id);
    if (save) case_bookmarks.push(c.id);
    saveLocal({answers: state.answers, saved_choices: state.savedChoices,
      dismissed_choices: state.dismissedChoices, case_bookmarks});
  }

  async function removeWrongbook(item) {
    if (endpoint) {
      const payload = item.kind === 'case'
        ? {kind: 'case', action: 'remove', case_id: item.case_id,
          source_package_id: item.source_package_id}
        : {kind: 'choice', action: 'remove', question_key: item.question_key};
      return changeBookmark(payload);
    }
    if (item.kind === 'case') return bookmarkCase({id: item.case_id}, false);
    return bookmarkChoice({id: item.qid}, false);
  }

  function wrongbookKey(item) {
    return item.kind === 'case' ? `case:${item.source_package_id || 'local'}:${item.case_id}` :
      item.question_key || item.history_url || item.qid || item.stem;
  }

  function selectedWrongbook() {
    const entries = state.wrongbook || [];
    const selected = entries.find(item => wrongbookKey(item) === state.wrongKey) || entries[0];
    state.wrongKey = selected ? wrongbookKey(selected) : null;
    return selected;
  }

  function renderWrongbook(parent) {
    const entries = state.wrongbook || [];
    if (!entries.length) {
      add(parent, 'p', '暂无待复习错题。答错的题目会自动出现在这里。', 'muted');
      return;
    }
    add(parent, 'strong', `错题本 · ${entries.length} 题`);
    selectedWrongbook();
    for (const item of entries) {
      const label = item.kind === 'case'
        ? `案例 · ${String(item.stem || item.case_id).slice(0, 28)}`
        : `${item.qid || '历史'} · ${String(item.stem || '').slice(0, 22)}` +
          (item.wrong_count ? `（错 ${item.wrong_count} 次）` : '（已收藏）');
      parent.append(button(label, () => {
        state.wrongKey = wrongbookKey(item);
        render();
      }, wrongbookKey(item) === state.wrongKey ? 'active' : ''));
    }
  }

  return {load, record, bookmarkChoice, bookmarkCase, removeWrongbook,
    selectedWrongbook, renderWrongbook};
})();

async function changeWrongbook(kind, item, save) {
  try {
    if (kind === 'remove') await StudyProgress.removeWrongbook(item);
    else if (kind === 'case') await StudyProgress.bookmarkCase(item, save);
    else await StudyProgress.bookmarkChoice(item, save);
    render();
  } catch (error) {
    const message = error.message || '错题本保存失败';
    state.storageStatus = message;
    if (kind === 'case') state.caseStatus = message;
    render();
  }
}

function wrongbookQuestion(item) {
  return item?.qid && QMAP[item.qid] ? QMAP[item.qid] : null;
}

function wrongbookCase(item) {
  if (item?.kind !== 'case' || !CASEMAP[item.case_id]) return null;
  const current = location.pathname.match(/^\/packages\/([a-f0-9]{16})\/web\/index\.html$/)?.[1];
  return !item.source_package_id || item.source_package_id === current ? CASEMAP[item.case_id] : null;
}

function wrongbookSnapshotImage(item, asset) {
  const packageId = item?.source_package_id;
  if (!/^[a-f0-9]{16}$/.test(packageId || '') ||
      !/^assets\/content\/[A-Za-z0-9._-]+$/.test(asset || '')) return null;
  return `/packages/${packageId}/web/${asset}`;
}

function wrongbookOriginal(parent, src, label, originalFile) {
  if (!src) return;
  const details = add(parent, 'details', undefined, 'question-source-page');
  details.open = false;
  add(details, 'summary', label);
  if (originalFile && originalFile !== src) {
    const link = add(details, 'a', '打开原文件');
    link.href = originalFile; link.target = '_blank'; link.rel = 'noopener';
  }
  const zoom = add(details, 'a');
  zoom.href = src; zoom.target = '_blank'; zoom.rel = 'noopener';
  image(zoom, src, label);
}

function showWrongbookBody() {
  const out = $('#content');
  out.replaceChildren();
  const article = add(out, 'article');
  const item = StudyProgress.selectedWrongbook();
  if (!item) {
    add(article, 'h2', '错题本');
    add(article, 'p', '暂无待复习错题。答错的选择题会出现在左侧。', 'muted');
    return;
  }
  if (item.kind === 'case') {
    showWrongbookCase(article, item);
    article.append(button('从错题本删除', () => changeWrongbook('remove', item), 'button'));
    return;
  }
  const question = wrongbookQuestion(item);
  const snapshot = item.snapshot || {};
  add(article, 'h2', question?.id || '历史错题');
  add(article, 'p', `累计答错 ${item.wrong_count || 0} 次` +
    (item.streak ? ` · 连续答对 ${item.streak} 次` : ''), 'muted');
  const stem = question?.question_zh || question?.question_en || snapshot.stem || item.stem || '';
  const body = add(article, 'div', undefined, 'question-body');
  if (question) markdown(body, stem, question.inline_image_assets || []);
  else add(body, 'p', stem);
  if (question) {
    source(article, question);
    for (const [index, asset] of (question.diagram_assets || []).entries())
      if (asset !== question.source_page_asset)
        wrongbookOriginal(article, asset, `查看原题图表 ${index + 1}`);
  } else {
    for (const [index, asset] of (snapshot.images || []).entries()) {
      const src = wrongbookSnapshotImage(item, asset);
      wrongbookOriginal(article, src, `查看历史原题原件 ${index + 1}`);
    }
  }
  const options = question?.options || snapshot.options || [];
  if (options.length) {
    add(article, 'h3', '选项');
    const list = add(article, 'div', undefined, 'options');
    const picked = item.picked || state.answers[question?.id]?.picked || [];
    for (const option of options) {
      const row = add(list, 'div', `${option.label || ''} · ${option.text || option.text_zh || option.text_en || ''}`,
        'option' + (option.is_correct ? ' ok' : picked.includes(option.label) ? ' bad' : ''));
      if (picked.includes(option.label)) add(row, 'small', ' · 上次选择');
      if (option.is_correct) add(row, 'small', ' · 正确答案');
    }
  }
  const explanation = question?.explanation || snapshot.explanation;
  if (explanation) callout(article, '题库解析原文', explanation);
  if (question && Q.length) article.append(button('去选择题重做', () => {
    state.view = 'quiz'; state.qid = question.id; render();
  }, 'button'));
  if (!question && item.history_url) {
    const link = add(article, 'a', '打开历史题页');
    link.href = item.history_url; link.target = '_blank'; link.rel = 'noopener';
  }
  if (!question && !Object.keys(snapshot).length)
    callout(article, '历史题详情暂不可用', '请打开历史题页查看原文。', 'warning');
  article.append(button('从错题本删除', () => changeWrongbook('remove', item), 'button'));
}

function showWrongbookCase(article, item) {
  const current = wrongbookCase(item);
  const c = current || item.snapshot || {};
  add(article, 'h2', c.original_number || item.stem || item.case_id || '案例题');
  add(article, 'p', c.scenario || '', 'question-body');
  if (current) {
    const pageAssets = new Set((current.source_page_assets || []).map(page => page.asset));
    for (const page of current.source_page_assets || [])
      wrongbookOriginal(article, page.asset, `查看原题所在第 ${page.page} 页`,
        current.source_file ? `${current.source_file}#page=${page.page}` : null);
    for (const [index, asset] of (current.diagram_assets || []).entries()) {
      if (pageAssets.has(asset)) continue;
      const isSourceImage = asset === current.source_file;
      wrongbookOriginal(article, asset, isSourceImage ? '查看原题截图' : `查看案例图表 ${index + 1}`);
    }
  } else for (const [index, asset] of (c.images || []).entries()) {
    const src = wrongbookSnapshotImage(item, asset);
    wrongbookOriginal(article, src, `查看历史案例原件 ${index + 1}`);
  }
  for (const child of c.sub_questions || []) {
    const section = add(article, 'section', undefined, 'case-child');
    add(section, 'h3', child.original_number || child.id || '案例子问题');
    add(section, 'p', child.question || '');
    const answer = child.reference_answer || {};
    if (answer.text || child.generated_analysis) {
      const details = add(section, 'details');
      add(details, 'summary', '查看参考答案与解析');
      if (answer.status === 'verified' && answer.text) callout(details, '原题参考答案', answer.text);
      else if (answer.text) callout(details, '答案待核验', answer.text, 'warning');
      if (child.generated_analysis) callout(details, '生成学习解析', child.generated_analysis, 'warning');
    }
  }
  if (current) article.append(button('前往案例题学习', () => {
    state.view = 'cases'; state.caseId = current.id; render();
  }, 'button'));
  else if (item.source_package_id && /^[a-f0-9]{16}$/.test(item.source_package_id)) {
    const link = add(article, 'a', '打开原案例学习包');
    link.href = `/packages/${item.source_package_id}/web/index.html`;
    link.target = '_blank'; link.rel = 'noopener';
  }
}

function renderWrongbookRail(parent) {
  const item = StudyProgress.selectedWrongbook();
  add(parent, 'strong', '本题关联');
  if (!item) {
    add(parent, 'p', '选择左侧错题后查看关联内容。', 'muted');
    return;
  }
  const question = wrongbookQuestion(item);
  const snapshot = item.snapshot || {};
  const caseItem = wrongbookCase(item);
  add(parent, 'h4', '关联考点');
  const ids = [...new Set(question?.concept_ids ||
    (caseItem?.sub_questions || []).flatMap(q => q.concept_ids || []))];
  const concepts = question || caseItem ? ids.map(id => CMAP[id] || {id, title: id}) : snapshot.concepts || [];
  if (!concepts.length) add(parent, 'p', '暂无明确关联考点。', 'muted');
  for (const concept of concepts) {
    if (concept.id && CMAP[concept.id]) parent.append(button(concept.title || concept.id, () => {
      state.view = 'notes'; state.cid = concept.id; render();
    }));
    else add(parent, 'p', concept.title || concept.id || '未命名考点', 'muted');
  }
  add(parent, 'h4', '关联方法');
  const methods = caseItem
    ? [...new Set((caseItem.sub_questions || []).flatMap(q => q.method_ids || []))]
      .map(id => METHODS.find(m => m.id === id) || {id, title: id})
    : question
    ? METHODS.filter(m => ids.some(id => (m.concept_ids || []).includes(id)))
    : snapshot.methods || [];
  if (!methods.length) add(parent, 'p', '暂无明确关联方法。', 'muted');
  for (const method of methods) {
    if (method.id && METHODS.some(m => m.id === method.id)) parent.append(button(method.title || method.id, () => {
      state.view = 'methods'; state.methodId = method.id; render();
    }));
    else add(parent, 'p', method.title || method.id || '未命名方法', 'muted');
  }
}
