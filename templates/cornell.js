/* Cornell layout: explicit pairs stay paired; independent arrays stay separate. */
function cornellInline(parent, value) {
  const text = String(value ?? '');
  // A deliberately small, safe emphasis subset. User HTML stays text.
  for (const part of text.split(/(\*\*[^*\n]+\*\*|`[^`\n]+`)/g)) {
    if (!part) continue;
    const tag = part.startsWith('**') && part.endsWith('**') ? 'strong'
      : part.startsWith('`') && part.endsWith('`') ? 'code' : null;
    if (tag) {
      const node = document.createElement(tag);
      node.textContent = part.slice(tag === 'strong' ? 2 : 1, tag === 'strong' ? -2 : -1);
      parent.append(node);
    } else parent.append(document.createTextNode(part));
  }
}
function addCornellFlashcards(section, body, footer, pairs) {
  const button = document.createElement('button');
  button.type = 'button'; button.className = 'cl-mode'; button.dataset.mode = 'card';
  button.textContent = '闪卡';
  section.querySelector('.cl-head').append(button);

  const deck = document.createElement('div');
  deck.className = 'cl-cards';
  const stage = document.createElement('div'); stage.className = 'fc-stage';
  const card = document.createElement('div'); card.className = 'fc-card';
  card.tabIndex = 0; card.setAttribute('role', 'button'); card.title = '点击翻面';
  const front = document.createElement('div'); front.className = 'fc-face fc-front';
  const frontTag = document.createElement('span'); frontTag.className = 'fc-tag'; frontTag.textContent = 'CUE · 问题';
  const frontBody = document.createElement('div'); frontBody.className = 'fc-body'; front.append(frontTag, frontBody);
  const back = document.createElement('div'); back.className = 'fc-face fc-back';
  const backTag = document.createElement('span'); backTag.className = 'fc-tag'; backTag.textContent = 'NOTE · 答案';
  const backBody = document.createElement('div'); backBody.className = 'fc-body'; back.append(backTag, backBody);
  card.append(front, back); stage.append(card);
  const controls = document.createElement('div'); controls.className = 'fc-ops';
  const previous = document.createElement('button'); previous.type = 'button'; previous.textContent = '上一张';
  const count = document.createElement('span'); count.className = 'fc-count';
  const next = document.createElement('button'); next.type = 'button'; next.textContent = '下一张';
  controls.append(previous, count, next); deck.append(stage, controls); section.append(deck);

  const state = { index: 0, flipped: false };
  const fit = () => {
    card.classList.add('measuring');
    const height = Math.max(front.offsetHeight, back.offsetHeight, 180);
    card.classList.remove('measuring');
    card.style.height = `${height}px`;
  };
  const show = () => {
    const pair = pairs[state.index]; frontBody.replaceChildren(); backBody.replaceChildren();
    cornellInline(frontBody, pair.cue); cornellInline(backBody, pair.note);
    state.flipped = false; card.classList.remove('flipped');
    count.textContent = `${state.index + 1} / ${pairs.length}`;
    card.setAttribute('aria-label', '当前显示问题，点击查看答案');
    requestAnimationFrame(fit);
  };
  const flip = () => {
    state.flipped = !state.flipped; card.classList.toggle('flipped', state.flipped);
    card.setAttribute('aria-label', state.flipped ? '当前显示答案，点击查看问题' : '当前显示问题，点击查看答案');
  };
  card.addEventListener('click', flip);
  card.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); flip(); } });
  previous.addEventListener('click', () => { state.index = (state.index - 1 + pairs.length) % pairs.length; show(); });
  next.addEventListener('click', () => { state.index = (state.index + 1) % pairs.length; show(); });
  button.addEventListener('click', () => {
    const active = section.classList.toggle('card-mode');
    footer.hidden = active;
    button.textContent = active ? '康奈尔' : '闪卡'; button.dataset.mode = active ? 'cornell' : 'card';
    if (active) show();
  });
}
function renderCornell(parent, value, title = '康奈尔笔记') {
  if (!value || typeof value !== 'object') return;
  const strings = v => (Array.isArray(v) ? v : typeof v === 'string' ? [v] : [])
    .filter(x => typeof x === 'string' && x.trim());
  const pairs = Array.isArray(value.pairs) && value.pairing_status !== 'unpaired'
    ? value.pairs.filter(p => p && typeof p.cue === 'string' && typeof p.note === 'string' && p.cue.trim() && p.note.trim()) : [];
  const cues = strings(value.cues), notes = strings(value.notes ?? value.answers);
  const summary = typeof value.summary === 'string' ? value.summary : '';
  if (!pairs.length && !cues.length && !notes.length && !summary.trim()) return;
  const section = document.createElement('section');
  section.className = 'cornell'; section.setAttribute('aria-label', title);
  const heading = document.createElement('div'); heading.className = 'cl-head';
  const headingText = document.createElement('span'); headingText.className = 'cl-title'; headingText.textContent = 'CORNELL 自测';
  heading.append(headingText); section.append(heading);
  const body = document.createElement('div'); body.className = 'cornell-body';
  function cell(label, values, cls) {
    const box = document.createElement('div'); box.className = 'cornell-cell ' + cls;
    if (label) { const h = document.createElement('h4'); h.textContent = label; box.append(h); }
    if (values.length) {
      const list = document.createElement('ul'); list.className = 'cornell-list';
      for (const text of values) { const item = document.createElement('li'); cornellInline(item, text); list.append(item); }
      box.append(list);
    } else {
      const p = document.createElement('p'); p.className = 'cornell-empty';
      p.textContent = label === '提示 / 自测' ? '本条笔记尚未提供提示。' : '本条笔记尚未提供详细笔记。'; box.append(p);
    }
    return box;
  }
  if (pairs.length) {
    body.classList.add('cornell-paired');
    for (const pair of pairs) {
      const row = document.createElement('div'); row.className = 'cl';
      row.append(cell(null, [pair.cue], 'cornell-cues'), cell(null, [pair.note], 'cornell-notes'));
      body.append(row);
    }
  } else {
    if (cues.length && notes.length) {
      const hint = document.createElement('p'); hint.className = 'cornell-hint';
      hint.textContent = '提示与笔记分别整理，不按序号逐条对应。'; section.append(hint);
    }
    body.append(cell('提示 / 自测', cues, 'cornell-cues'), cell('笔记 / 要点', notes, 'cornell-notes'));
  }
  section.append(body);
  const footer = document.createElement('div'); footer.className = 'cornell-summary';
  const h = document.createElement('h4'); h.textContent = '总结'; footer.append(h);
  const p = document.createElement('p'); cornellInline(p, summary || '本条笔记尚未提供总结。'); footer.append(p);
  section.append(footer);
  if (pairs.length) addCornellFlashcards(section, body, footer, pairs);
  parent.append(section);
}
