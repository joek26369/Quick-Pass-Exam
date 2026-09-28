// Case study state is intentionally separate from choice-question progress.
// Learner text is always inserted with textContent/value, never HTML.
const CASES=Array.isArray(DATA.cases)?DATA.cases:[], METHODS=Array.isArray(DATA.methods)?DATA.methods:[];
const CASEMAP=nullMap(CASES.map(x=>[x.id,x]));
function caseLabel(id){const method=METHODS.find(x=>x.id===id);if(method)return method.title;const concept=CMAP[id];if(concept)return concept.title;for(const c of CASES){if(c.id===id)return c.original_number||id;const q=(c.sub_questions||[]).find(x=>x.id===id);if(q)return (c.original_number||c.id)+' '+(q.original_number||q.id);}return id;}
if(CASES.length)document.querySelector('nav [data-view=cases]')?.classList.remove('hidden');
if(METHODS.length)document.querySelector('nav [data-view=methods]')?.classList.remove('hidden');
if(!C.length)document.querySelector('nav [data-view=notes]')?.classList.add('hidden');
if(!Q.length)document.querySelector('nav [data-view=quiz]')?.classList.add('hidden');
if(!C.length&&CASES.length)state.view='cases';
state.caseProgress=Object.create(null); state.caseStats={}; state.caseStatus='';
const CaseProgress=(()=>{
  const match=location.protocol==='http:'&&location.hostname==='127.0.0.1'?location.pathname.match(/^\/packages\/([a-f0-9]{16})\/web\/index\.html$/):null;
  const endpoint=match?`/api/packages/${match[1]}/cases/progress`:null;
  const key=`quick-pass-case-v1:${DATA.profile?.exam_code||'default'}:${location.pathname}`;
  const apply=data=>{state.caseProgress=Object.assign(Object.create(null),data?.items||{});state.caseStats=data?.stats||{};};
  async function load(){if(!CASES.length)return;if(endpoint){const r=await fetch(endpoint,{cache:'no-store'});if(!r.ok)throw new Error('案例题记录无法读取');apply(await r.json());state.caseStatus='案例题记录已连接本地学习库';return}const raw=localStorage.getItem(key);if(raw)apply(JSON.parse(raw));state.caseStatus='使用本文件的浏览器本地记录；案例记录不跨学习包继承';}
  const queues=Object.create(null);
  function save(id,change){const run=async()=>{const next=Object.assign({},state.caseProgress[id]||{},change);if(endpoint){const r=await fetch(endpoint,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(Object.assign({sub_question_id:id},change))});if(!r.ok)throw new Error('案例题未保存；请确认本地学习库仍在运行');apply(await r.json());return}const items=Object.assign({},state.caseProgress,{[id]:next});localStorage.setItem(key,JSON.stringify({items,stats:state.caseStats}));apply({items,stats:state.caseStats});};const prior=queues[id]||Promise.resolve();const queued=prior.catch(()=>{}).then(run);queues[id]=queued;return queued;}
  return {load,save};
})();
function caseLinks(parent,ids,label,go){if(!Array.isArray(ids)||!ids.length)return;add(parent,'h4',label);const box=add(parent,'div',undefined,'links');for(const id of ids)box.append(linkButton(caseLabel(id),()=>go(id)));}
function renderCaseEvidence(parent,ids){
  const requested=[...new Set(Array.isArray(ids)?ids:[])];
  if(!requested.length)return;
  const evidenceById=new Map((DATA.teaching_evidence||[]).filter(x=>x?.id).map(x=>[x.id,x]));
  const rows=requested.map(id=>evidenceById.get(id)).filter(Boolean);
  add(parent,'h4','关联证据');
  if(rows.length){
    const list=add(parent,'div',undefined,'material-list');
    for(const item of rows)list.append(materialEvidenceCard(item));
  }
  const missing=requested.filter(id=>!evidenceById.has(id));
  if(missing.length)add(parent,'p','以下关联证据未找到可展示的教辅原页：'+missing.join('、'),'warning');
}
function captureCaseDrafts(){for(const area of document.querySelectorAll('textarea[data-case-draft]')){const id=area.dataset.caseDraft;state.caseProgress[id]=Object.assign({},state.caseProgress[id]||{},{draft:area.value});}}
function caseOrigin(parent,item,label){if(!item?.source_file)return;const pages=item.source_pages||[];const box=add(parent,'div',undefined,'links');const a=document.createElement('a');a.href=item.source_file+(pages[0]?'#page='+pages[0]:'');a.target='_blank';a.rel='noopener';a.textContent=label+(pages.length?' · 第 '+pages.join('、')+' 页':'');box.append(a);for(const page of item.source_page_assets||[]){const b=linkButton('查看原页 '+page.page,()=>{const d=document.createElement('dialog');d.className='material-dialog';const body=add(d,'div',undefined,'material-dialog-body');image(body,page.asset,label+'第 '+page.page+' 页');const close=button('关闭',()=>d.close(),'button');body.append(close);document.body.append(d);d.addEventListener('close',()=>d.remove());d.showModal()});box.append(b)}}
function selectedCase(){
  if(state.childId){
    const owner=CASES.find(c=>(c.sub_questions||[]).some(q=>q.id===state.childId));
    if(owner)state.caseId=owner.id;
  }
  if(!CASEMAP[state.caseId])state.caseId=CASES[0]?.id;
  return CASEMAP[state.caseId];
}
function openCase(id){
  state.view='cases';state.caseId=id;state.childId=null;render();
  document.querySelector(`[data-case-id="${CSS.escape(id)}"]`)?.scrollIntoView({block:'start'});
}
function renderCaseRail(parent){
  const c=selectedCase();
  add(parent,'strong','本案例关联');
  if(!c){add(parent,'p','暂无案例题。','muted');return;}
  const info=CASE_GROUPS.byId.get(c.id);add(parent,'p',(info?`${info.year}${info.half} ${info.batch} · 第${info.number}题`:(c.original_number||c.id))+' · '+(c.sub_questions||[]).length+' 问','muted');
  const children=c.sub_questions||[];
  for(const [field,title,items,view,key] of [
    ['method_ids','关联方法',new Map(METHODS.map(x=>[x.id,x])),'methods','methodId'],
    ['concept_ids','关联考点',CMAP,'notes','cid'],
  ]){
    add(parent,'h4',title);
    const ids=[...new Set(children.flatMap(q=>q[field]||[]))];
    if(!ids.length){add(parent,'p','本案例未提供关联内容。','muted');continue;}
    for(const id of ids){
      const item=items instanceof Map?items.get(id):items[id];
      if(!item)continue;
      parent.append(button(item.title||id,()=>{state.view=view;state[key]=id;render()}));
    }
  }
}
function selectedMethod(){
  if(!METHODS.some(m=>m.id===state.methodId))state.methodId=METHODS[0]?.id;
  return METHODS.find(m=>m.id===state.methodId);
}
function renderMethodRail(parent){
  const m=selectedMethod();
  add(parent,'strong','本方法关联');
  if(!m){add(parent,'p','暂无方法卡。','muted');return;}
  add(parent,'h4','关联案例子题');
  const childIds=[...new Set(m.sub_question_ids||[])];
  if(!childIds.length)add(parent,'p','本方法未提供关联案例子题。','muted');
  for(const id of childIds){
    const owner=CASES.find(c=>(c.sub_questions||[]).some(q=>q.id===id));
    if(!owner)continue;
    parent.append(button(caseLabel(id),()=>{state.view='cases';state.childId=id;render()}));
  }
  add(parent,'h4','关联选择题');
  for(const id of m.question_ids||[]){const link=relatedQuestionButton(id,()=>{state.view='quiz';state.qid=id;render()});if(link)parent.append(link);}
  add(parent,'h4','关联考点');
  const conceptIds=[...new Set(m.concept_ids||[])];
  if(!conceptIds.length)add(parent,'p','本方法未提供关联考点。','muted');
  for(const id of conceptIds){
    const concept=CMAP[id];
    if(!concept)continue;
    parent.append(button(concept.title||id,()=>{state.view='notes';state.cid=id;render()}));
  }
}
function showCases(){const out=$('#content');out.replaceChildren();const children=CASES.flatMap(c=>c.sub_questions||[]),items=Object.values(state.caseProgress);const summary=add(out,'article',undefined,'case-summary');add(summary,'h2','案例题学习进度');add(summary,'p',`已作答 ${items.filter(x=>x.draft).length}/${children.length} · 待复习 ${items.filter(x=>x.review).length} · 掌握 ${items.filter(x=>x.self_assessment==='mastered').length} · 部分掌握 ${items.filter(x=>x.self_assessment==='partial').length} · 未掌握 ${items.filter(x=>x.self_assessment==='unmastered').length}`,'muted');if(state.caseStatus)add(summary,'p',state.caseStatus,state.caseStatus.includes('失败')||state.caseStatus.includes('无法')?'error':'muted');const review=children.filter(q=>state.caseProgress[q.id]?.review);if(review.length){add(summary,'h3','待复习');const list=add(summary,'div',undefined,'links');for(const q of review)list.append(linkButton(caseLabel(q.id),()=>{state.childId=q.id;render()}));}const c=selectedCase();if(c){const a=add(out,'article','', 'case-study');a.dataset.caseId=c.id;const info=CASE_GROUPS.byId.get(c.id);add(a,'h2',(info?`${info.year}${info.half} ${info.batch} · 第${info.number}题`:(c.original_number||c.id))+' · 案例题');a.append(button(state.caseBookmarks.includes(c.id)?'取消收藏':'收藏进错题本',()=>changeWrongbook('case',c,!state.caseBookmarks.includes(c.id)),'button'));add(a,'p',c.scenario||'');if(c.source_warning)callout(a,'来源不可用',c.source_warning,'warning');if(c.source_file&&c.source_pages?.length){const link=document.createElement('a');link.href=c.source_file+'#page='+c.source_pages[0];link.target='_blank';link.rel='noopener';link.textContent='打开案例原文件第 '+c.source_pages.join('、')+' 页';a.append(link)}for(const item of c.source_page_assets||[]){const d=add(a,'details',undefined,'question-source-page');add(d,'summary','查看原题所在第 '+item.page+' 页');image(d,item.asset,'案例原题第 '+item.page+' 页')}for(const p of c.diagram_assets||[])image(a,p,'案例图表');if((c.unavailable_diagrams||[]).length)callout(a,'资源不可用','以下案例图未复制到学习包：'+c.unavailable_diagrams.join('；'),'warning');for(const q of c.sub_questions||[])renderCaseChild(a,c,q);}if(state.childId){document.querySelector(`[data-case-child="${CSS.escape(state.childId)}"]`)?.scrollIntoView({block:'start'});state.childId=null;}}
function renderCaseChild(parent,c,q){const box=add(parent,'section',undefined,'case-child');box.dataset.caseChild=q.id;add(box,'h3',(q.original_number||q.id)+' · '+(q.type||'案例子题'));add(box,'p',q.question||'');const saved=state.caseProgress[q.id]||{};const area=document.createElement('textarea');area.dataset.caseDraft=q.id;area.placeholder='写下你的作答…';area.value=saved.draft||'';const status=add(box,'p','', 'muted');area.oninput=()=>{clearTimeout(area._timer);area._timer=setTimeout(()=>saveCase(q.id,{draft:area.value},area,false,status),700)};box.append(area);const ops=add(box,'div',undefined,'case-ops');ops.append(button('保存作答',()=>saveCase(q.id,{draft:area.value},area,true,status),'button'));for(const [value,label] of [['mastered','掌握'],['partial','部分掌握'],['unmastered','未掌握']])ops.append(button(label,()=>saveCase(q.id,{draft:area.value,self_assessment:value},area,true,status),'button '+(saved.self_assessment===value?'primary':'')));ops.append(button(saved.review?'移出待复习':'加入待复习',()=>saveCase(q.id,{draft:area.value,review:!saved.review},area,true,status),'button'));const reveal=button(saved.revealed?'收起参考':'查看参考答案与解析',()=>saveCase(q.id,{draft:area.value,revealed:!saved.revealed},area,true,status),'button');ops.append(reveal);if(saved.revealed){const ans=q.reference_answer||{},unresolved=ans.status==='unresolved';callout(box,ans.status==='verified'?'原题参考答案':unresolved?'答案归属待核验':'参考答案状态',unresolved?'归属待核验，不作为本问确定答案。'+(ans.text?' '+ans.text:''):(ans.text||'来源未提供可确认的答案。'),ans.status==='verified'?'':'warning');if(unresolved&&ans.reason)callout(box,'待核验原因',ans.reason,'warning');caseOrigin(box,ans,'答案来源');if(q.generated_analysis)callout(box,'生成学习解析',q.generated_analysis,'warning');textList(box,'计算步骤',q.calculation_steps?.map(x=>x.text));for(const step of q.calculation_steps||[])for(const basis of step.input_basis||[])caseOrigin(box,basis,'计算依据');textList(box,'评分点',q.scoring_points?.map(x=>x.text));if(q.score?.max_points!=null)callout(box,'本问分值',String(q.score.max_points)+' 分（仅展示来源评分信息，不自动判分）');caseOrigin(box,q.score,'分值依据');for(const point of q.scoring_points||[])caseOrigin(box,point,'评分点依据');textList(box,'易错点',q.pitfalls)}renderCaseEvidence(box,q.evidence_ids);}
async function saveCase(id,change,area,rerender,status){try{await CaseProgress.save(id,change);state.caseStatus='案例题已保存';if(status)status.textContent='已保存';if(rerender){captureCaseDrafts();render()}}catch(e){state.caseStatus=e.message||'案例题保存失败';if(status){status.textContent=state.caseStatus;status.className='error'}}}
function showMethods(){const out=$('#content');out.replaceChildren();const m=selectedMethod();if(!m){const empty=add(out,'article');add(empty,'h2','暂无方法卡');return}if(m){const a=add(out,'article',undefined,'method-card');add(a,'h2',m.title||m.id);add(a,'p',m.applicability||'');callout(a,'适用假设',m.assumptions);textList(a,'所需输入',m.input_requirements);callout(a,'公式/作答框架',m.formula||m.answer_structure);callout(a,'代入示例',m.substitution);callout(a,'单位/口径',m.units);textList(a,'步骤',m.steps);textList(a,'易错点',m.pitfalls);for(const basis of m.case_basis||[])caseOrigin(a,basis,'案例依据');renderCaseEvidence(a,m.evidence_ids);}}

const showQuizWithoutMethods=showQuiz;
showQuiz=function(){showQuizWithoutMethods();const a=$('#content article');const matched=METHODS.filter(m=>(m.question_ids||[]).includes(state.qid));if(a&&matched.length){add(a,'h3','关联方法');const links=add(a,'div',undefined,'links');for(const m of matched)links.append(linkButton(m.title,()=>{state.view='methods';state.methodId=m.id;render()}));}};
