/* Offline diagrams; all labels are text, never executable markup. */
function renderKnowledgeGraph(parent, value) {
  if (!value || !value.type || value.type === 'none') return;
  const strings = x => Array.isArray(x) ? x.filter(v => typeof v === 'string' && v.trim()) : [];
  const nodes = [...new Set(strings(value.nodes))], relations = strings(value.relations);
  if (!nodes.length && !relations.length) return;
  const make = (tag, text, cls) => { const n=document.createElement(tag); if(text !== undefined)n.textContent=text; if(cls)n.className=cls; return n; };
  parent.append(make('h3','知识图谱'));
  parent.append(make('p','根据学习笔记整理的示意图，非教材原图；来源核验状态见本页内容说明。','compare-hint'));
  if (typeof value.caption === 'string' && value.caption.trim()) parent.append(make('p',value.caption,'compare-hint'));
  const box=make('div',undefined,'knowledge-graph');parent.append(box);
  const keys=['权力高·利益低','权力高·利益高','权力低·利益低','权力低·利益高'];
  if(value.type==='quadrant' && keys.every(k=>nodes.includes(k)) && nodes.length===4) {
    box.append(make('p','权力 ↑ · 利益 →','graph-axis'));
    const grid=make('div',undefined,'graph-quadrants');box.append(grid);
    for(const key of keys) {
      const cell=make('div',undefined,'graph-quadrant');cell.append(make('strong',key));
      for(const r of relations) { const parts=r.split(/\s*→\s*/);if(parts.length===2 && parts[0]===key)cell.append(make('p',parts[1])); }
      grid.append(cell);
    }
  } else if(nodes.length) {
    const edges=[];
    for(const r of relations) {const p=r.split(/\s*→\s*/);if(p.length===2 && nodes.includes(p[0]) && nodes.includes(p[1]))edges.push([nodes.indexOf(p[0]),nodes.indexOf(p[1])]);}
    if(edges.length < relations.length)box.append(make('p',`${relations.length-edges.length} 条关系无法匹配图中节点，未绘制箭头；请展开下方文字说明查看。`,'callout warning'));
    // Topological layers; cycles use a deterministic single-node-per-layer layout.
    const degree=nodes.map(()=>0), levels=nodes.map(()=>0);edges.forEach(([a,b])=>degree[b]++);
    const queue=degree.map((d,i)=>d===0?i:-1).filter(i=>i>=0);let count=0;
    for(let pos=0;pos<queue.length;pos++){const a=queue[pos];count++;for(const [from,b] of edges)if(from===a){levels[b]=Math.max(levels[b],levels[a]+1);if(--degree[b]===0)queue.push(b);}}
    if(count!==nodes.length)nodes.forEach((_,i)=>levels[i]=i);
    const rows=[];nodes.forEach((_,i)=>(rows[levels[i]]??=[]).push(i));
    const lines=nodes.map(n=>{const chars=Array.from(n),out=[];for(let i=0;i<chars.length;i+=12)out.push(chars.slice(i,i+12).join(''));return out;});
    const heights=rows.map(row=>Math.max(...row.map(i=>lines[i].length*22+32)));
    const width=Math.max(440,...rows.map(row=>row.length*210+30));let y=24;const positions=[];
    rows.forEach((row,r)=>{row.forEach((i,j)=>positions[i]={x:(width-row.length*210)/2+j*210+10,y,h:heights[r]});y+=heights[r]+70;});
    const ns='http://www.w3.org/2000/svg';
    const svgNode=(tag,attrs,text)=>{const n=document.createElementNS(ns,tag);for(const [k,v] of Object.entries(attrs||{}))n.setAttribute(k,String(v));if(text!==undefined)n.textContent=text;return n;};
    const svg=svgNode('svg',{viewBox:`0 0 ${width} ${y}`,width,height:y,role:'img','aria-label':'知识节点及有向关系图'});
    svg.append(svgNode('title',{},'知识节点及有向关系图；完整关系见下方文字说明'));
    const defs=svgNode('defs');const marker=svgNode('marker',{id:'knowledge-arrow',viewBox:'0 0 10 10',refX:9,refY:5,markerWidth:7,markerHeight:7,orient:'auto-start-reverse'});marker.append(svgNode('path',{d:'M 0 0 L 10 5 L 0 10 z',fill:'#5778ab'}));defs.append(marker);svg.append(defs);
    for(const [a,b] of edges){const p=positions[a],q=positions[b],x1=p.x+95,y1=p.y+p.h,x2=q.x+95,y2=q.y;svg.append(svgNode('path',{d:`M ${x1} ${y1} C ${x1} ${y1+35}, ${x2} ${y2-35}, ${x2} ${y2}`,fill:'none',stroke:'#5778ab','stroke-width':2,'marker-end':'url(#knowledge-arrow)'}));}
    nodes.forEach((label,i)=>{const p=positions[i];svg.append(svgNode('rect',{x:p.x,y:p.y,width:190,height:p.h,rx:10,fill:'#eef5ff',stroke:'#87a7d6'}));const text=svgNode('text',{'text-anchor':'middle',fill:'#172033','font-size':15});lines[i].forEach((line,j)=>text.append(svgNode('tspan',{x:p.x+95,y:p.y+28+j*22},line)));svg.append(text);});
    const scroll=make('div',undefined,'graph-scroll');scroll.tabIndex=0;scroll.setAttribute('aria-label','关系图，可横向滚动');scroll.append(svg);box.append(scroll);
  }
  const details=make('details');details.append(make('summary','查看节点与关系文字说明'));
  const list=make('ul');for(const label of [...nodes,...relations])list.append(make('li',label));details.append(list);box.append(details);
}
