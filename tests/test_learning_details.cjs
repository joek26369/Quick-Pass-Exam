const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const {runInNewContext} = require('node:vm');

class Element {
  constructor(tag) { this.tag=tag; this.children=[]; this.value=''; this.className=''; }
  append(...children) { this.children.push(...children); }
  set textContent(value) { this.value=String(value); }
  get textContent() { return this.value + this.children.map(child => child.textContent).join(''); }
}
const add = (parent, tag, text, cls) => { const node=new Element(tag); node.textContent=text ?? ''; node.className=cls || ''; parent.append(node); return node; };
const callout = (parent, title, body, cls='') => { const node=add(parent, 'div', '', `callout ${cls}`); add(node, 'strong', title); add(node, 'div', body); };
const textList = (parent, title, values) => { add(parent, 'h3', title); for (const value of values) add(parent, 'li', value); };
const linkButton = (text, fn) => { const node=new Element('button'); node.textContent=text; node.onclick=fn; return node; };
const scope={add,callout,textList,linkButton,CMAP:{C2:{title:"目标知识"}},QMAP:{Q1:{}},state:{view:'notes',qid:''},render:()=>{}};
runInNewContext(readFileSync(join(__dirname, '../templates/learning-details.js'), 'utf8'), scope);

test('question mismatch warning hides answer details until the result section', () => {
  const root=new Element('main');
  const question={source_paper:'原始试卷',answer_mismatch:true,answer:'A',llm_answer:'B',generated_analysis:{answer_mismatch:true,llm_answer:'C'}};
  scope.renderQuestionTrustWarning(root,question);
  assert.ok(root.textContent.includes('答案存疑'));
  assert.ok(!root.textContent.includes('题库答案为 A'));
  scope.renderAnswerMismatchDetails(root,question);
  scope.renderAnswerMismatchDetails(root,question,question.generated_analysis);
  assert.ok(root.textContent.includes('题库答案为 A；模型判断为 B'));
  assert.ok(root.textContent.includes('题库答案为 A；模型辅助判断为 C'));
});

test('question fidelity details preserve native and model-generated learning fields', () => {
  const root=new Element('main');
  scope.renderQuestionLearningDetails(root,{core_exam_points:[{title:'考点',body:'EV/AC'}],calc_solution:{method_name:'挣值法',steps:'代入'},knowledge_expansion:[{topic:'扩展',body:'CV'}],method_extract:{method_name:'方法',description:'说明'}});
  scope.renderQuestionLearningDetails(root,{core_exam_points:[{title:'模型考点',body:'仅辅助'}],calc_solution:{method_name:'模型法',steps:'模型步骤'},knowledge_expansion:[{topic:'模型扩展',body:'模型内容'}],method_extract:{method_name:'模型方法',applicable_conditions:'模型条件'}},'模型生成');
  for(const text of ['核心考点','EV/AC','计算步骤','扩展知识','方法论抽取','模型生成核心考点','模型生成计算步骤','模型生成扩展知识','模型生成方法论抽取','适用条件：模型条件']) assert.ok(root.textContent.includes(text));
  assert.ok(!root.textContent.includes('applicable_conditions'));
});

test('concept references remain unverified and origin is explicitly labeled', () => {
  const root=new Element('main');
  scope.renderConceptFidelityDetails(root,{question_origins:[{question_id:'Q1'}],canonical_references:[{title:'输入来源'}],references:['旧来源'],unverified_generated_references:[{text:'模型来源'}]});
  for(const text of ['输入提供的来源（未额外核验）','输入来源','旧式来源字段（未核验）','旧来源','模型建议来源（未核验）','模型来源','不自动视为可信来源或教辅证据']) assert.ok(root.textContent.includes(text));
});

 test('question links are a union with no duplicates and missing targets remain visible', () => {
  const root=new Element('main');
  scope.renderConceptQuestionLinks(root,{question_ids:['Q1'],source_questions:['Q1','Q2'],question_origins:[{question_id:'Q1'}],related_questions:['Q3']});
  const buttons=root.children[1].children.filter(n=>n.tag==='button');
  assert.equal(buttons.length,1);
  buttons[0].onclick(); assert.equal(scope.state.qid,'Q1');
  assert.ok(root.textContent.includes('Q2（不在本学习包）'));
  assert.ok(root.textContent.includes('Q3（不在本学习包）'));
 });
 test('reference display deduplicates same source page but preserves distinct pages', () => {
  const root=new Element('main');
  scope.renderConceptFidelityDetails(root,{canonical_references:[{question_id:'Q1',source_file:'input/sub_abc_quiz_123_试题.pdf',source_page:12},{question_id:'Q2',source_file:'input/sub_abc_quiz_123_试题.pdf',source_page:12},{source_file:'input/sub_abc_quiz_123_试题.pdf',source_page:13}]});
  assert.equal(root.children[0].tag,'details');
  assert.equal(root.children[0].open,undefined);
  assert.equal(root.textContent.split('试题.pdf · 第 12 页').length-1,1);
  assert.ok(root.textContent.includes('试题.pdf · 第 13 页'));
  assert.ok(!root.textContent.includes('input/'));
 });

test('learning paths use explicit IDs, preserve unknown targets, and navigate by concept', () => {
  const root=new Element('main');
  scope.renderConceptLearningLinks(root,{id:'C1',chapter:'同章',learning_relations:{related_concepts:['C1','C2','C2','missing']}});
  const links=root.children[2];
  assert.equal(links.children.length,2);
  assert.equal(links.children[0].textContent,'目标知识');
  links.children[0].onclick();assert.equal(scope.state.cid,'C2');assert.equal(scope.state.view,'notes');
  assert.ok(root.textContent.includes('missing（不在本学习包）'));
  const empty=new Element('main');scope.renderConceptLearningLinks(empty,{id:'C1',chapter:'同章'});assert.equal(empty.children.length,0);
});

test('case knowledge links navigate to child instead of reporting missing question', () => {
  scope.CASES=[{id:'case1',sub_questions:[{id:'case1q1'}]}];
  scope.caseLabel=()=> '案例一（1）';
  const root=new Element('main');
  scope.renderConceptQuestionLinks(root,{source_questions:['case1q1']});
  const button=root.children[1].children[0];
  assert.equal(button.textContent,'案例一（1）');
  button.onclick();assert.equal(scope.state.view,'cases');assert.equal(scope.state.childId,'case1q1');
  assert.ok(!root.textContent.includes('不在本学习包'));
});
