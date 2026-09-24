/* Readable comparison grids, preserving supplied content without invented mnemonics. */
function renderComparisons(parent, concept) {
  const cc=concept.core_concept||{};
  const make=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
  const valid=x=>Array.isArray(x)?x.filter(v=>v && typeof v==='object'):[];
  function section(title, hint) {
    const s=make('section',undefined,'compare-section');s.append(make('h3',title),make('p',hint,'compare-hint'));parent.append(s);return s;
  }
  function table(container, headers, rows) {
    const t=make('table',undefined,'compare-table');const head=make('thead'),tr=make('tr');
    headers.forEach(label=>{const th=make('th',label);th.setAttribute('scope','col');tr.append(th);});head.append(tr);t.append(head);
    const body=make('tbody');
    for(const values of rows){const row=make('tr');values.forEach((value,i)=>{const cell=make(i===0?'th':'td');if(i===0)cell.setAttribute('scope','row');cell.setAttribute('data-label',headers[i]);
      if(i===0)cornellInline(cell,value);else {const lines=String(value||'未提供').split(/；|\n/).filter(x=>x.trim());for(const line of lines){const p=make('p');cornellInline(p,line);cell.append(p);}}
      row.append(cell);});body.append(row);}t.append(body);const scroll=make('div',undefined,'compare-table-scroll');scroll.append(t);container.append(scroll);
  }
  const types=valid(cc.type_comparison);
  if(types.length){
    const s=section('类型对比','先看类型，再横向对照判别方式与关键规则。');
    const groups=new Map();
    for(const item of types){const name=String(item.type||'未命名类型');const parts=name.split(/[:：]/);const group=parts.length===2?parts[0]:'分类速查';const label=parts.length===2?parts[1]:name;if(!groups.has(group))groups.set(group,[]);groups.get(group).push([label,item.syntax_example,item.key_rules]);}
    for(const [name,rows] of groups){s.append(make('h4',name));const hasRules=rows.some(row=>String(row[2]||'').trim());table(s,hasRules?['类型','判别 / 示例','关键规则']:['类型','判别 / 示例'],hasRules?rows:rows.map(row=>row.slice(0,2)));}
  }
  const comparisons=valid(cc.comparisons);
  if(comparisons.length){
    const current=String(concept.title||'当前考点');
    const s=section('易混对比','每行聚焦一个有效维度，直接横向核对概念差异。');
    for(const item of comparisons){
      const compared=String(item.vs||'对比对象');
      const dimensions=valid(item.dimensions).filter(row=>String(row.dimension||'').trim() && (String(row.current||'').trim() || String(row.compared||'').trim()));
      s.append(make('h4',`${current} ↔ ${compared}`));
      if(String(item.commonality||'').trim())table(s,['关系','说明'],[['共同点',item.commonality]]);
      if(dimensions.length){
        table(s,['对比维度',current,compared],dimensions.map(row=>[row.dimension,row.current,row.compared]));
      } else {
        table(s,['对比维度',current,compared],[['综合区别',item.difference||'未提供区别说明','旧内容尚未按对象拆分']]);
      }
    }
  }
}
