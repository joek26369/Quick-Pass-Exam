function closeMaterialDialog(){
  const dlg=document.querySelector('#material-dialog');
  if(dlg&&dlg.open)dlg.close();
}

function materialPageImage(parent,item,compact=false){
  if(!item.thumbnail)return;
  const frame=add(parent,'span',undefined,'material-page'+(compact?' compact':''));
  image(frame,item.thumbnail,'教辅原版第 '+item.page+' 页');
  const r=item.region;
  if(r&&[r.x,r.y,r.width,r.height].every(Number.isFinite)){
    const mark=add(frame,'span',undefined,'material-region');
    mark.style.left=(r.x*100)+'%';mark.style.top=(r.y*100)+'%';
    mark.style.width=(r.width*100)+'%';mark.style.height=(r.height*100)+'%';
  }
}

function openMaterialDialog(item){
  const dlg=document.querySelector('#material-dialog');
  if(!dlg)return;
  const title=dlg.querySelector('.material-dialog-title');
  const body=dlg.querySelector('.material-dialog-body');
  title.textContent=item.source_title+(item.page?' · 第 '+item.page+' 页':'');
  body.replaceChildren();
  if(item.anchor)add(body,'h3',item.anchor);
  materialPageImage(body,item);
  if(item.snippet)callout(body,'教辅节选',item.snippet);
  if(item.relation||item.status)callout(body,'关联信息',[item.relation,item.status].filter(Boolean).join(' · '));
  const source=document.createElement('a');
  source.className='button primary';
  source.href=item.source_link;
  source.target='_blank';
  source.rel='noopener';
  source.textContent=item.page?'打开原文件第 '+item.page+' 页':'打开原文件';
  body.append(source);
  dlg.showModal();
}

function materialEvidenceCard(item){
  const card=button('',()=>openMaterialDialog(item),'material-card');
  materialPageImage(card,item,true);
  const copy=add(card,'span',undefined,'material-card-copy');
  add(copy,'strong',item.source_title+(item.page?' · 第 '+item.page+' 页':''));
  if(item.anchor)add(copy,'span',item.anchor,'material-anchor');
  if(item.relation||item.status)add(copy,'span',[item.relation,item.status].filter(Boolean).join(' · '),'material-meta');
  if(item.snippet)add(copy,'span',item.snippet,'material-snippet');
  return card;
}

function renderMaterialEvidence(parent,conceptId,evidence){
  const rows=(Array.isArray(evidence)?evidence:[]).filter(x=>x&&x.concept_id===conceptId);
  if(!rows.length)return;
  add(parent,'h3','教辅资料');
  const list=add(parent,'div',undefined,'material-list');
  for(const item of rows)list.append(materialEvidenceCard(item));
}

document.addEventListener('DOMContentLoaded',()=>{
  const dlg=document.querySelector('#material-dialog');
  dlg?.querySelector('.material-dialog-close')?.addEventListener('click',closeMaterialDialog);
  dlg?.addEventListener('click',event=>{if(event.target===dlg)closeMaterialDialog()});
});
