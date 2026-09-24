const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function setup(entries) {
  const state = {wrongbook: entries, view: 'wrongbook', search: 'old'};
  const parent = {children: [], append(child) { this.children.push(child); }};
  const context = {state, DATA: {profile: {}}, QMAP: {q1: {}},
    location: {protocol: 'file:', pathname: '/package/web/index.html'},
    add: (p, tag, text) => { const item = {tag, text}; p.append(item); return item; },
    button: (text, click) => ({text, click}), render: () => { context.rendered = true; }};
  const script = fs.readFileSync(path.join(__dirname, '../templates/progress.js'), 'utf8');
  vm.runInNewContext(script + ';globalThis.progress = StudyProgress;', context);
  context.progress.renderWrongbook(parent);
  return {parent, context, state};
}

test('wrongbook renders an empty state instead of disappearing', () => {
  const {parent} = setup([]);
  assert.match(parent.children[0].text, /暂无待复习错题/);
});

test('selecting a local mistake keeps the wrongbook three-column view', () => {
  const {parent, state, context} = setup([{qid:'q1', stem:'题目', wrong_count:2}]);
  parent.children.find(x => x.click).click();
  assert.equal(state.view, 'wrongbook');
  assert.equal(state.wrongKey, 'q1');
  assert.equal(context.rendered, true);
});

test('selecting a historical mistake stays in the wrongbook', () => {
  const url='/history/known-question';
  const {parent, context} = setup([{qid:null, stem:'历史题', wrong_count:1, history_url:url}]);
  parent.children.find(x => x.click).click();
  assert.equal(context.state.wrongKey, url);
  assert.equal(context.state.view, 'wrongbook');
  assert.equal(context.location.href, undefined);
});

test('case bookmarks appear alongside choice mistakes', () => {
  const {parent, state, context} = setup([
    {kind:'choice', qid:'q1', stem:'选择题', wrong_count:1},
    {kind:'case', case_id:'case1', stem:'案例一'},
  ]);
  const entries = parent.children.filter(x => x.click);
  assert.equal(entries.length, 2);
  assert.match(entries[1].text, /案例 · 案例一/);
  entries[1].click();
  assert.equal(state.wrongKey, 'case:local:case1');
  assert.equal(context.rendered, true);
});

test('wrongbook original image is inside a collapsed disclosure', () => {
  const parent = {children: [], append(child) { this.children.push(child); }};
  const context = {state: {}, DATA: {profile: {}}, QMAP: {},
    location: {protocol: 'file:', pathname: '/package/web/index.html'},
    add: (node, tag, text, className) => {
      const child = {tag, text, className, children: [], append(value) { this.children.push(value); }};
      node.append(child); return child;
    },
    image: (node, src) => node.append({tag: 'img', src})};
  const script = fs.readFileSync(path.join(__dirname, '../templates/progress.js'), 'utf8');
  vm.runInNewContext(script + ';globalThis.original = wrongbookOriginal;', context);
  context.original(parent, 'assets/content/page.png', '查看原题所在第 1 页');
  const details = parent.children[0];
  assert.equal(details.tag, 'details');
  assert.equal(details.open, false);
  assert.equal(details.children[0].tag, 'summary');
  assert.equal(details.children[0].text, '查看原题所在第 1 页');
  assert.equal(details.children[1].children[0].tag, 'img');
});
