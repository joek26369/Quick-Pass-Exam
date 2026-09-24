// Unit checks on synthetic data only; these are not browser/layout tests.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const {runInNewContext} = require('node:vm');
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.className = ''; this.attributes = {}; this.value = ''; this.dataset = {}; this.style = {}; this.events = {}; this.classList = {add: c => {this.className += ' ' + c;}}; }
  querySelector(selector) { return this.children.flatMap(c => [c, ...all(c).slice(1)]).find(c => c.className.split(' ').includes(selector.slice(1))) || null; }
  addEventListener(event, fn) { this.events[event] = fn; }
  append(...children) { this.children.push(...children); }
  setAttribute(k, v) { this.attributes[k] = v; }
  set textContent(v) { this.value = String(v); this.children = []; }
  get textContent() { return this.value + this.children.map(c => c.textContent).join(''); }
}
const document = {createElement: tag => new Element(tag), createTextNode: text => {const n = new Element('#text'); n.textContent = text; return n;}};
const scope = {document};
runInNewContext(readFileSync(join(__dirname, '../templates/cornell.js'), 'utf8'), scope);
const all = root => [root, ...root.children.flatMap(all)];
const render = data => {const root = new Element('main'); scope.renderCornell(root, data); return root;};

test('unpaired cue and note arrays are both shown without inventing pairs', () => {
  const root = render({cues:['第一提示','第二提示','第三提示'], notes:['**定义**：CPI','第二笔记'], summary:'总结内容', pairing_status:'unpaired'});
  assert.equal(all(root).filter(n => n.children.length === 2 && n.children[0].className.includes('cornell-cues') && n.children[1].className.includes('cornell-notes') && n.className !== 'cornell-body').length, 0);
  assert.equal(all(root).filter(n => n.tag === 'li').length, 5);
  for (const s of ['第一提示','第三提示','定义','第二笔记','总结内容']) assert.ok(root.textContent.includes(s));
  assert.equal(all(root).find(n => n.tag === 'strong').textContent, '定义');
  assert.ok(all(root).some(n => n.className === 'cornell-summary'));
});
test('explicit paired data keeps its cue and note in the same row', () => {
  const root = render({pairs:[{cue:'CPI公式？',note:'EV/AC'},{cue:'阈值？',note:'小于1成本效率偏低'}], summary:'小结'});
  const rows = all(root).filter(n => n.children.length === 2 && n.children[0].className.includes('cornell-cues') && n.children[1].className.includes('cornell-notes') && n.className !== 'cornell-body');
  assert.equal(rows.length, 2);
  assert.ok(rows[0].textContent.includes('CPI公式？') && rows[0].textContent.includes('EV/AC'));
  assert.ok(!rows[0].textContent.includes('阈值？'));
});
test('HTML-looking content remains text while emphasis is rendered', () => {
  const root = render({notes:['<img src=x onerror=alert(1)> **重点** `EV/AC`'],summary:'<script>unsafe</script>'});
  assert.equal(all(root).filter(n => ['img','script'].includes(n.tag)).length,0);
  assert.ok(root.textContent.includes('<img src=x onerror=alert(1)>'));
  assert.ok(all(root).some(n => n.tag === 'code' && n.textContent === 'EV/AC'));
});
test('legacy summary-only data remains readable without fabricated notes', () => {
  const root = render({summary:'原来的小结'});
  assert.ok(root.textContent.includes('原来的小结'));
  assert.ok(root.textContent.includes('尚未提供详细笔记'));
  assert.equal(render({}).children.length,0);
});

test('preview concepts render every question with its explicit answer in one row', () => {
  const concepts = JSON.parse(readFileSync(join(__dirname, '../examples/preview/data/concepts.json'), 'utf8'));
  for (const concept of concepts) {
    const note = concept.cornell_note;
    assert.equal(note.pairing_status, 'paired');
    assert.equal(note.pairs.length, note.cues.length);
    const root = render(note);
    const rows = all(root).filter(n => n.children.length === 2 && n.children[0].className.includes('cornell-cues') && n.children[1].className.includes('cornell-notes') && n.className !== 'cornell-body');
    assert.equal(rows.length, note.pairs.length);
    rows.forEach((row, i) => {
      assert.equal(row.children.length, 2);
      assert.ok(row.children[0].textContent.includes(note.pairs[i].cue));
      assert.ok(row.children[1].textContent.length > 0);
    });
  }
});

document.createElementNS = (_ns, tag) => new Element(tag);
runInNewContext(readFileSync(join(__dirname, '../templates/graph.js'), 'utf8'), scope);
test('preview CPI diagram renders every node and six directed edges', () => {
  const concepts=JSON.parse(readFileSync(join(__dirname,'../examples/preview/data/concepts.json'),'utf8'));
  const root=new Element('main');scope.renderKnowledgeGraph(root,concepts[0].visualization);
  assert.equal(all(root).filter(n=>n.tag==='rect').length,7);
  assert.equal(all(root).filter(n=>n.tag==='path' && n.attributes['marker-end']).length,6);
  assert.ok(all(root).some(n=>n.tag==='svg' && n.attributes.role==='img'));
});
test('stakeholder quadrants preserve high/low axes and matching strategies', () => {
  const concepts=JSON.parse(readFileSync(join(__dirname,'../examples/preview/data/concepts.json'),'utf8'));
  const root=new Element('main');scope.renderKnowledgeGraph(root,concepts[1].visualization);
  const cells=all(root).filter(n=>n.className==='graph-quadrant');
  assert.equal(cells.length,4);
  assert.ok(cells[0].textContent.includes('权力高·利益低令其满意'));
  assert.ok(cells[1].textContent.includes('权力高·利益高重点管理'));
  assert.ok(cells[3].textContent.includes('权力低·利益高随时告知'));
});
test('unknown edges stay in text and markup labels are inert', () => {
  const root=new Element('main');scope.renderKnowledgeGraph(root,{type:'flow',nodes:['<img src=x>','B'],relations:['<img src=x> → B','B → missing']});
  assert.equal(all(root).filter(n=>n.tag==='img').length,0);
  assert.equal(all(root).filter(n=>n.tag==='path' && n.attributes['marker-end']).length,1);
  assert.ok(root.textContent.includes('B → missing'));
  assert.ok(root.textContent.includes('1 条关系无法匹配图中节点'));
});

runInNewContext(readFileSync(join(__dirname, '../templates/comparisons.js'), 'utf8'), scope);
test('type comparison separates classification families without losing rules', () => {
  const concepts=JSON.parse(readFileSync(join(__dirname,'../examples/preview/data/concepts.json'),'utf8'));
  const root=new Element('main');scope.renderComparisons(root,concepts[1]);
  const typeSection=root.children[0];
  assert.equal(all(typeSection).filter(n=>n.tag==='table').length,2);
  for(const item of concepts[1].core_concept.type_comparison)assert.ok(root.textContent.includes(item.key_rules));
  assert.equal(all(typeSection).filter(n=>n.tag==='tbody').flatMap(n=>n.children).length,9);
});
test('legacy comparisons render as readable tables without losing distinctions', () => {
  const concept={title:'成本绩效指数 CPI',core_concept:{comparisons:[{vs:'SPI',difference:'SPI 关注进度，CPI 关注成本。'}]}};
  const root=new Element('main');scope.renderComparisons(root,concept);
  assert.equal(all(root).filter(n=>n.tag==='details').length,0);
  assert.equal(all(root).filter(n=>n.tag==='table').length,1);
  for(const text of ['对比维度','成本绩效指数 CPI','SPI','综合区别','SPI 关注进度，CPI 关注成本。','旧内容尚未按对象拆分'])assert.ok(root.textContent.includes(text));
});
test('dimensioned concept comparisons use dimension, current concept, and compared concept columns', () => {
  const root=new Element('main');scope.renderComparisons(root,{title:'确认范围',core_concept:{comparisons:[{vs:'控制范围',difference:'验收与监控的区别',commonality:'都属于范围管理',dimensions:[{dimension:'目的',current:'正式验收可交付成果',compared:'监督范围状态'},{dimension:'输出',current:'验收的可交付成果',compared:'工作绩效信息'}]}]}});
  assert.equal(all(root).filter(n=>n.tag==='table').length,2);
  for(const text of ['共同点','都属于范围管理','对比维度','确认范围','控制范围','目的','正式验收可交付成果','监督范围状态','输出','工作绩效信息'])assert.ok(root.textContent.includes(text));
  assert.ok(all(root).some(n=>n.className==='compare-table-scroll'));
});
