// Display numbers are positions within a source batch. Stable IDs remain the
// keys for answers, bookmarks, and case progress.
function sourceBatchLabel(item, kind) {
  if (kind === 'quiz' && item.source_url) {
    try {
      const query = new URL(item.source_url).hash.split('?')[1] || '';
      const name = new URLSearchParams(query).get('name');
      if (name) return name;
    } catch (_) { /* fall back to a clearly unclassified group */ }
  }
  if (kind === 'cases') return String(item.original_number || '').replace(/\s*第\d+题.*$/, '').trim();
  return '';
}

function batchParts(label) {
  const match = String(label || '').match(/^(\d{4})年(上半年|下半年)(.*)$/);
  if (!match) return { year: '年份未标注', half: '场次未标注', batch: label || '批次未标注' };
  const tail = match[3].replace(/[-～~]?(持续更新中).*$/, '').trim();
  return { year: match[1] + '年', half: match[2], batch: tail || '未分批' };
}

function groupQuestions(items, kind) {
  const years = new Map(), byId = new Map(), byBatch = new Map();
  for (const item of items) {
    const { year, half, batch } = batchParts(sourceBatchLabel(item, kind));
    if (!years.has(year)) years.set(year, new Map());
    const halves = years.get(year);
    if (!halves.has(half)) halves.set(half, new Map());
    const batches = halves.get(half);
    if (!batches.has(batch)) batches.set(batch, []);
    const group = batches.get(batch);
    group.push(item);
    byId.set(item.id, { year, half, batch, number: group.length, group });
  }
  for (const entry of byId.values()) byBatch.set(entry.group, entry.group.length);
  return { years, byId };
}

const QUIZ_GROUPS = groupQuestions(Q, 'quiz');
const CASE_GROUPS = groupQuestions(CASES, 'cases');
const expandedQuestionGroups = { quiz: new Set(), cases: new Set() };
const collapsedQuestionGroups = { quiz: new Set(), cases: new Set() };
const expandedNoteChapters = new Set();
const collapsedNoteChapters = new Set();
let lastNoteSelection = null;

function relatedQuestionInfo(id) {
  const choice = QMAP[id];
  if (choice) {
    const entry = QUIZ_GROUPS.byId.get(id);
    return {
      meta: entry ? `${entry.year}${entry.half} · ${entry.batch} · 第${entry.number}题` : '选择题',
      summary: String(choice.question_zh || choice.question_en || '查看题目').replace(/\s+/g, ' ').trim(),
    };
  }
  const owner = CASES.find(c => c.id === id || (c.sub_questions || []).some(q => q.id === id));
  if (!owner) return null;
  const child = (owner.sub_questions || []).find(q => q.id === id);
  const entry = CASE_GROUPS.byId.get(owner.id);
  const questionNumber = child?.original_number ? ` · ${child.original_number}` : '';
  return {
    meta: entry ? `${entry.year}${entry.half} · ${entry.batch} · 案例第${entry.number}题${questionNumber}` : '案例题',
    summary: String(child?.question || owner.scenario || '查看案例').replace(/\s+/g, ' ').trim(),
  };
}

function relatedQuestionButton(id, open) {
  const info = relatedQuestionInfo(id);
  if (!info) return null;
  const link = button(undefined, open, 'related-question-link');
  add(link, 'small', info.meta);
  add(link, 'span', info.summary);
  link.title = `${info.meta} · ${info.summary}`;
  link.setAttribute('aria-label', link.title);
  return link;
}

function groupKey(parts) { return JSON.stringify(parts); }
function groupedQuestionTitle(item, number, kind) {
  const text = kind === 'quiz' ? item.question_zh || item.question_en : item.scenario;
  return `第${number}题 · ${String(text || '未命名题目').replace(/\s+/g, ' ').slice(0, 25)}`;
}

function renderNotesSidebar(sidebar, keyword) {
  const groups=Object.create(null);
  for (const concept of C) {
    const group = concept.chapter || (/[\u4e00-\u9fff]/.test(concept.parent || '') ? concept.parent : '未分组');
    if (keyword && !(group.includes(keyword) || (concept.title || '').includes(keyword) || (concept.tags || []).join(' ').includes(keyword))) continue;
    (groups[group] ??= []).push(concept);
  }
  if (state.cid !== lastNoteSelection) {
    const selected = C.find(concept => concept.id === state.cid);
    if (selected) {
      const chapter = selected.chapter || (/[\u4e00-\u9fff]/.test(selected.parent || '') ? selected.parent : '未分组');
      collapsedNoteChapters.delete(chapter);
      expandedNoteChapters.add(chapter);
    }
    lastNoteSelection = state.cid;
  }
  for (const [name, list] of Object.entries(groups)) {
    const chapter = add(sidebar, 'details', undefined, 'question-group note-chapter');
    chapter.open = keyword ? true : expandedNoteChapters.has(name) && !collapsedNoteChapters.has(name);
    const summary = add(chapter, 'summary');
    add(summary, 'span', name);
    add(summary, 'small', String(list.length));
    chapter.ontoggle = keyword ? null : () => {
      if (chapter.open) { expandedNoteChapters.add(name); collapsedNoteChapters.delete(name); }
      else { expandedNoteChapters.delete(name); collapsedNoteChapters.add(name); }
    };
    for (const concept of list) chapter.append(button(concept.title || concept.id,
      () => { state.cid = concept.id; render(); }, state.cid === concept.id ? 'active' : ''));
  }
  if (!Object.keys(groups).length) add(sidebar, 'p', '没有匹配的考点。', 'muted');
}

function batchOrder(label) {
  const match = label.match(/第([一二三四五六七八九十\d]+)批/);
  if (!match) return 0;
  const value = match[1];
  const number = Number(value);
  if (Number.isInteger(number)) return number;
  return '一二三四五六七八九十'.indexOf(value) + 1;
}

function renderGroupedSidebar(sidebar, kind, search) {
  const groups = kind === 'quiz' ? QUIZ_GROUPS : CASE_GROUPS;
  const selectedId = kind === 'quiz' ? state.qid : state.caseId;
  const expanded = expandedQuestionGroups[kind];
  const collapsed = collapsedQuestionGroups[kind];
  const keyword = String(search || '').trim();
  const makeBranch = (parent, title, path, count, selected, visible) => {
    const details = add(parent, 'details', undefined, 'question-group');
    const key = groupKey(path);
    details.open = keyword ? visible : (expanded.has(key) || selected) && !collapsed.has(key);
    const summary = add(details, 'summary');
    add(summary, 'span', title);
    add(summary, 'small', String(count));
    details.ontoggle = keyword ? null : () => {
      if (details.open) { expanded.add(key); collapsed.delete(key); }
      else { expanded.delete(key); collapsed.add(key); }
    };
    return details;
  };
  const years = [...groups.years.entries()].sort((a, b) => b[0].localeCompare(a[0], 'zh-CN'));
  let matches = 0;
  for (const [year, halves] of years) {
    const halfRows = [];
    for (const [half, batches] of [...halves.entries()].sort((a, b) => (a[0] === '上半年' ? -1 : 1) - (b[0] === '上半年' ? -1 : 1))) {
      const batchRows = [];
      for (const [batch, items] of [...batches.entries()].sort((a, b) => batchOrder(a[0]) - batchOrder(b[0]) || a[0].localeCompare(b[0], 'zh-CN'))) {
        const shown = items.filter((item, index) => !keyword ||
          groupedQuestionTitle(item, index + 1, kind).includes(keyword) ||
          `${year}${half}${batch}`.includes(keyword));
        if (shown.length) batchRows.push({ batch, items, shown });
      }
      if (batchRows.length) halfRows.push({ half, batches: batchRows });
    }
    if (!halfRows.length) continue;
    const yearCount = [...halves.values()].flatMap(b => [...b.values()]).reduce((n, list) => n + list.length, 0);
    const yearSelected = groups.byId.get(selectedId)?.year === year;
    const yearNode = makeBranch(sidebar, year, [year], yearCount, yearSelected, true);
    for (const { half, batches } of halfRows) {
      const halfCount = [...halves.get(half).values()].reduce((n, list) => n + list.length, 0);
      const halfSelected = yearSelected && groups.byId.get(selectedId)?.half === half;
      const halfNode = makeBranch(yearNode, half, [year, half], halfCount, halfSelected, true);
      for (const { batch, items, shown } of batches) {
        const batchSelected = halfSelected && groups.byId.get(selectedId)?.batch === batch;
        const batchNode = makeBranch(halfNode, batch, [year, half, batch], items.length, batchSelected, true);
        shown.forEach(item => {
          const number = groups.byId.get(item.id).number;
          const label = groupedQuestionTitle(item, number, kind);
          const open = kind === 'quiz'
            ? () => { state.qid = item.id; render(); }
            : () => openCase(item.id);
          batchNode.append(button(label, open, 'grouped-question ' + (item.id === selectedId ? 'active' : '')));
          matches++;
        });
      }
    }
  }
  if (!matches) add(sidebar, 'p', '没有匹配的题目。', 'muted');
}
