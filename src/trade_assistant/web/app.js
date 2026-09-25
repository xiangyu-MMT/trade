'use strict';
const token = document.querySelector('meta[name="csrf-token"]').content;
const $ = s => document.querySelector(s);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const labels = {overview:'市场概览',candidates:'候选与依据',plans:'交易计划',knowledge:'交易知识档案',settings:'本地配置'};
const kinds = {logic:'逻辑',technical:'技术',mode:'模式'};
const statuses = {draft:'待确认',confirmed:'已确认',recorded:'已回填',generated:'AI复盘',running:'运行中',completed:'已完成',partial:'部分资料可用',failed:'失败',interrupted:'已中断'};
const stances = {candidate:'可关注方向',observe:'观察',wait:'等待'};
let state = {knowledge:[],confirmed_knowledge:[],plans:[],confirmed_plans:[],executions:[],reviews:[],runs:[]};
let currentRun = null, configInfo = null, view = 'overview', selectedAsset = '', chartPeriod = 'daily', chartSeries = 'price';
let aiInfo = null;
let followLatest = true, stateSignature = '', editorSubmit = null, activeJob = null, loading = false, knowledgeFilter = 'all';
const watchedJobs = new Set();

async function api(path, method='GET', data=null) {
  const options = {method, headers:{'X-P03-Token':token}};
  if (data !== null) { options.headers['Content-Type']='application/json'; options.body=JSON.stringify(data); }
  let response;
  try { response = await fetch(path, options); }
  catch (_) { throw new Error('本地服务未连接，请确认启动窗口仍在运行。'); }
  const result = await response.json();
  if (!response.ok) throw new Error(result.error?.message || ('请求失败：'+response.status));
  return result;
}
function toast(message, error=false) {
  const box=$('#toast'); box.textContent=message; box.className=error?'error':''; box.hidden=false;
  clearTimeout(toast.timer); toast.timer=setTimeout(()=>box.hidden=true,error?7000:4000);
}
function time(value) {
  if (!value) return '未提供';
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value+'（日频）';
  const date=new Date(value); return Number.isNaN(date.valueOf())?String(value):date.toLocaleString('zh-CN',{hour12:false});
}
function num(value,digits=2) { return typeof value==='number'&&Number.isFinite(value)?value.toLocaleString('zh-CN',{maximumFractionDigits:digits}):'—'; }
function short(value,unit='') {
  if (typeof value!=='number'||!Number.isFinite(value)) return '—';
  if (Math.abs(value)>=1e12) return num(value/1e12)+'万亿'+unit;
  if (Math.abs(value)>=1e8) return num(value/1e8)+'亿'+unit;
  if (Math.abs(value)>=1e4) return num(value/1e4)+'万'+unit;
  return num(value)+unit;
}
function percent(value) { return typeof value==='number'?num(value*100)+'%':'—'; }
function cut(text,n=160) { const s=String(text||'');return s.length>n?s.slice(0,n)+'…':s; }
function pill(status) { const warn=['draft','partial','observe','wait','interrupted'].includes(status),bad=status==='failed';return `<span class="pill ${bad?'error':warn?'warn':''}">${esc(statuses[status]||stances[status]||status)}</span>`; }
function list(items) { return items?.length?`<ul class="data-list">${items.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>`:'<p class="muted small">暂无</p>'; }
function button(label,action,attrs='',disabled=false) { return `<button type="button" class="button small" data-action="${action}" ${attrs} ${disabled?'disabled':''}>${label}</button>`; }
function factItem(id) { return currentRun?.facts?.candidates?.find(x=>x.asset_id===id); }
function opinion(id) { return currentRun?.analysis?.result?.candidates?.find(x=>x.asset_id===id); }
function objectByRef(ref) { return [...state.plans,...(state.confirmed_plans||[])].find(x=>x.ref===ref); }
function evidenceName(ref) {
  const item=currentRun?.facts?.evidence?.[ref];
  if (item?.name) return item.name+' · '+time(item.asof);
  const names={'market:breadth':'沪深非ST市场统计','industry:ranking':'同花顺行业成交额排名','data:coverage':'数据覆盖记录','margin:balance':'融资余额发布数据'};
  return names[ref]||ref;
}
function knowledgeName(ref) {
  const items=currentRun?.knowledge_used||[...state.knowledge,...state.confirmed_knowledge];
  const x=items.find(x=>x.ref===ref);return x?(x.payload?.title||x.title)+' / '+ref:ref;
}

async function loadState(force=false) {
  if (loading) return;
  loading=true;
  try {
    const next=await api('/api/state');state=next;
    renderStatus(next);
    if (followLatest&&next.latest_report_id&&currentRun?.id!==next.latest_report_id) {
      currentRun=await api('/api/runs/'+encodeURIComponent(next.latest_report_id));force=true;
    }
    const signature=JSON.stringify([next.latest_report_id,next.knowledge.map(x=>[x.ref,x.status]),next.plans.map(x=>[x.ref,x.status]),next.executions.map(x=>x.ref),next.reviews.map(x=>x.ref),next.lifecycle,next.runs.map(x=>[x.id,x.status])]);
    if (force||signature!==stateSignature) {stateSignature=signature;render();}
    if (next.active&&!watchedJobs.has(next.active.id)) watchJob(next.active.id);
  } catch (error) {
    $('#runtime-status').textContent=error.message;
    if (force) toast(error.message,true);
  } finally {loading=false;}
}
function renderStatus(data) {
  activeJob=data.active;
  $('#run-button').disabled=Boolean(data.active);
  $('#cancel-run').hidden=!data.active;
  $('#progress').hidden=!data.active;
  $('#auto-refresh').checked=Boolean(data.auto_refresh);
  $('#auto-label').textContent=`运行时每${num((data.refresh_seconds||3600)/3600,1)}小时刷新`;
  if (data.active) {
    const elapsed=Math.max(0,Math.floor((Date.now()-new Date(data.active.created_at).valueOf())/1000));
    $('#runtime-status').textContent=`${data.active.stage} · ${data.active.detail||'处理中'} · ${elapsed}秒`;
  } else {
    $('#runtime-status').textContent=data.auto_refresh?'下次周期更新：'+time(data.next_refresh):'手动模式 · 本地服务已连接';
  }
  const msg=$('#global-message');msg.hidden=!data.config_error;
  if (data.config_error) {msg.textContent=data.config_error.message;msg.className='notice error';}
  else {
    const latest=(data.runs||state.runs||[])[0];
    if(!data.active&&latest&&['failed','interrupted'].includes(latest.status)) {
      msg.textContent='最近一轮'+(statuses[latest.status]||latest.status)+'：'+(latest.error?.message||'请查看运行记录')+'。当前保留此前的可用结果。';msg.className='notice';msg.hidden=false;
    }
  }
}
async function watchJob(id) {
  if (watchedJobs.has(id)) return;
  watchedJobs.add(id);
  const started=Date.now();
  try {
    while (Date.now()-started<20*60*1000) {
      await new Promise(resolve=>setTimeout(resolve,1500));
      const [job,status]=await Promise.all([api('/api/jobs/'+encodeURIComponent(id)),api('/api/status')]);
      renderStatus(status);
      if (job.status!=='running') {
        if (job.error) toast(job.error.message,true);
        else { toast(job.result?.status==='partial'?'分析已生成，数据缺口已保留':'任务已完成'); if (job.kind==='plan'||job.kind==='review') view='plans'; }
        await loadState(true);return;
      }
    }
    toast('任务仍在运行，可继续查看状态或停止本次。',true);
  } catch(error) {toast(error.message,true);}
  finally {watchedJobs.delete(id);}
}

function runChooser() {
  return `<div class="toolbar"><label class="small muted">查看轮次</label><select id="run-select" style="max-width:290px"><option value="latest" ${followLatest?'selected':''}>最近生成的结果</option>${state.runs.filter(x=>['completed','partial'].includes(x.status)).map(x=>`<option value="${esc(x.id)}" ${!followLatest&&currentRun?.id===x.id?'selected':''}>${esc(time(x.created_at))} · ${esc(statuses[x.status])}</option>`).join('')}</select>${currentRun?button('导出此轮HTML','report'):''}</div>`;
}
function emptyReport() {
  return '<div class="card empty"><h2>开始一轮有依据的分析</h2><p>点击右上角“更新分析”，获取市场与同花顺行业数据，再由 Codex 对照你的档案解读。</p><p class="small">首次取数与推导可能需要几分钟；页面会显示阶段。你也可以先进入档案和配置。</p></div>';
}
function marketChart(m) {
  const values=[m.advancing||0,m.declining||0,m.unchanged||0],total=values.reduce((a,b)=>a+b,0);
  if (!total) return '<div class="empty">尚无可用市场统计</div>';
  let x=20;
  const bars=values.map((v,i)=>{const width=v/total*560;const r=`<rect x="${x}" y="37" width="${width}" height="39" rx="2" fill="${['#ba5a49','#36866a','#a6b5ab'][i]}"><title>${['上涨','下跌','平盘'][i]} ${v}</title></rect>`;x+=width;return r;}).join('');
  return `<svg viewBox="0 0 600 145" role="img" aria-label="市场涨跌家数"><text x="20" y="20" fill="#5c6f72" font-size="12">${m.counts_complete?'来源目录已覆盖':'仅为已取得范围，非完整市场'} · 统计${num(m.eligible_count,0)}只</text>${bars}<text x="20" y="104" fill="#b64e3e" font-size="13">上涨 ${num(values[0],0)}</text><text x="240" y="104" fill="#247c5d" font-size="13">下跌 ${num(values[1],0)}</text><text x="470" y="104" fill="#667c6f" font-size="13">平盘 ${num(values[2],0)}</text><text x="20" y="131" fill="#5c6f72" font-size="11">剔除北交所/B股/ST；缺报价 ${num(m.unknown_prices,0)}</text></svg>`;
}
function plot(technical,period='daily',kind='price') {
  const all=period==='weekly'?(technical?.weekly||[]):(technical?.bars||[]);
  const bars=all.slice(-90);
  if (bars.length<2) return '<div class="empty">历史不足，未绘制图形</div>';
  const start=all.length-bars.length,series=[];
  let isBar=false;
  if (kind==='price'||period==='weekly') {
    series.push({name:period==='weekly'?'周收盘':'日收盘',color:'#2c536c',values:bars.map(x=>x.close)});
    if(period==='daily') for (const [p,color] of [['20','#ba9140'],['60','#4b886c'],['120','#92929c']]) {
      if (technical.ma?.[p]) series.push({name:'MA'+p,color,values:technical.ma[p].slice(start)});
    }
  } else if(kind==='volume') {isBar=true;series.push({name:'成交量',color:'#759586',values:bars.map(x=>x.volume)});}
  else if(kind==='macd') {
    series.push({name:'DIF',color:'#2c536c',values:(technical.dif||[]).slice(start)},
      {name:'DEA',color:'#ba9140',values:(technical.dea||[]).slice(start)},
      {name:'柱形×2',color:'#88aa99',values:(technical.histogram||[]).slice(start),bar:true});
  } else series.push({name:kind.toUpperCase(),color:'#3d8266',values:(technical[kind]||[]).slice(start)});
  const values=series.flatMap(s=>s.values).filter(x=>typeof x==='number'&&Number.isFinite(x));
  if(!values.length) return '<div class="empty">该指标尚未取得有效数值</div>';
  let min=Math.min(...values),max=Math.max(...values);
  if(isBar||kind==='macd') {min=Math.min(0,min);max=Math.max(0,max);}
  const span=max-min||Math.abs(max)*.01||1;
  min-=span*.06;max+=span*.06;
  const x=i=>52+i*550/(bars.length-1),y=v=>204-(v-min)/(max-min)*175;
  let drawing='';
  for(const s of series) {
    if(isBar||s.bar) drawing+=s.values.map((v,i)=>typeof v==='number'&&Number.isFinite(v)?`<rect x="${x(i)-2}" y="${Math.min(y(v),y(0))}" width="4" height="${Math.max(.7,Math.abs(y(v)-y(0)))}" fill="${s.color}" opacity=".7"><title>${esc(bars[i]?.date)} ${s.name} ${num(v)}</title></rect>`:'').join('');
    else {let path='',connected=false;s.values.forEach((v,i)=>{if(typeof v==='number'&&Number.isFinite(v)){path+=(connected?'L':'M')+x(i).toFixed(2)+','+y(v).toFixed(2)+' ';connected=true;}else connected=false;});drawing+=`<path d="${path}" fill="none" stroke="${s.color}" stroke-width="1.8"/>`;}
  }
  const guides=[0,.5,1].map(t=>{const v=min+(max-min)*t;return `<line x1="52" x2="602" y1="${y(v)}" y2="${y(v)}" stroke="#e5ece6"/><text x="46" y="${y(v)+4}" text-anchor="end" font-size="10" fill="#74867a">${esc(short(v))}</text>`;}).join('');
  return `<svg viewBox="0 0 625 239" role="img" aria-label="${esc(series[0].name)}走势图">${guides}${drawing}<text x="52" y="230" fill="#6b7e72" font-size="10">${esc(bars[0].date)}</text><text x="525" y="230" fill="#6b7e72" font-size="10">${esc(bars[bars.length-1].date)}</text></svg><div class="legend">${series.map(s=>`<span><i style="background:${s.color}"></i>${esc(s.name)}</span>`).join('')}</div>`;
}
function chartPanel() {
  const items=currentRun.facts.candidates||[];
  if(!items.some(x=>x.asset_id===selectedAsset))selectedAsset=items.find(x=>x.kind==='index')?.asset_id||items[0]?.asset_id||'';
  const item=factItem(selectedAsset);
  return `<div class="card"><div class="chart-controls"><select id="chart-asset">${items.map(x=>`<option value="${esc(x.asset_id)}" ${selectedAsset===x.asset_id?'selected':''}>${esc(x.name)}</option>`).join('')}</select><select id="chart-period"><option value="daily" ${chartPeriod==='daily'?'selected':''}>日线</option><option value="weekly" ${chartPeriod==='weekly'?'selected':''}>周线</option></select></div><div class="candle-chart">${currentRun.charts?.[selectedAsset]?.[chartPeriod]||''}</div><div class="ma-legend"><span>MA5</span><span>MA20</span><span>MA60</span><span>MA120</span></div><p class="small">${esc(item?.volume_price?.summary||'量价比较不足')}</p></div>`;
}
function marketVolumePanel() {
  const v=currentRun.facts.market_volume||{},exact=v.exact||{},ref=v.reference||{};
  const key=(exact.rows?.length||0)>=5?'exact':(ref.rows?.length?'reference':'exact'),data=v[key]||{};
  return `<div class="card"><div class="card-head"><div><h3>全市场量能</h3><p class="small muted">${key==='reference'?'沪深A股 · 含ST参考序列':'沪深非ST · 实际完整收盘记录'}</p></div><span class="pill neutral">成交金额</span></div><div class="turnover-chart">${currentRun.market_charts?.[key]||'<p class="small muted">旧轮次没有全市场量能历史，请重新运行分析。</p>'}</div><div class="volume-insight">${esc(data.summary||'历史资料尚不足')}</div><div class="metric-chips">${data.previous_ratio!=null?`<span>前日 ${num(data.previous_ratio)}×</span>`:''}${data.mean5_ratio!=null?`<span>前5日均额 ${num(data.mean5_ratio)}×</span>`:''}${data.mean20_ratio!=null?`<span>前20日均额 ${num(data.mean20_ratio)}×</span>`:''}</div>${key==='reference'?`<p class="small muted">严格剔除ST的历史积累 ${(exact.rows||[]).length} 日；此图为独立的含ST参考，不与严格统计拼接。</p>`:''}<details><summary>量能口径与原始来源</summary><div><p class="small">${esc(ref.scope||exact.scope||'待取得')}。盘中累计值不与完整日总额直接相除。</p>${list(v.notes||[])}${list(ref.limitations||[])}</div></details></div>`;
}

function candidateCard(item) {
  const ai=opinion(item.asset_id),v=item.volume_price||{},tech=item.technical||{};
  const read=ai?.volume_price_reading||v.summary||'量价历史不足';
  const strength=ai?.strength_reason||ai?.reason||'当前仅提供程序量价事实';
  return `<article class="card candidate-card"><div class="title-line"><h3>${esc(item.name)}</h3>${ai?pill(ai.stance):'<span class="pill neutral">量价参考</span>'}</div><div class="small muted">${esc(tech.asof||'缺历史')} · ${chartPeriod==='weekly'?'周线':'日线'}${tech.forming?' · 当日形成中':''}</div><div class="candle-chart">${currentRun.charts?.[item.asset_id]?.[chartPeriod]||'<p>图表未取得</p>'}</div><div class="volume-insight">${esc(cut(read,100))}</div><p>${esc(cut(strength,100))}</p>${ai?.against?.[0]?`<p class="counterpoint">留意：${esc(cut(ai.against[0],75))}</p>`:''}<div class="toolbar">${button('查看依据','candidate-detail',`data-id="${esc(item.asset_id)}"`)}${button('拟定计划','draft-plan',`data-id="${esc(item.asset_id)}"`,!ai||Boolean(activeJob))}</div></article>`;
}

function coveragePanel() {
  const f=currentRun.facts;
  return `<details><summary>数据覆盖、口径与局限</summary><div><div class="table-wrap"><table><thead><tr><th>数据组</th><th>状态</th><th>说明</th></tr></thead><tbody>${(f.coverage||[]).map(x=>`<tr><td>${esc(x.group)}</td><td>${x.status==='ok'?'<span class="pill">已取得</span>':'<span class="pill warn">需留意</span>'}</td><td>${esc(x.detail)}</td></tr>`).join('')}</tbody></table></div>${list(currentRun.analysis?.result?.limitations||[])}<p class="small muted">${esc(f.market?.limit_definition||'')}</p></div></details>`;
}
function renderOverview() {
  if(!currentRun?.facts)return emptyReport();
  const f=currentRun.facts,m=f.market,a=currentRun.analysis?.result,sel=currentRun.presentation||{},trace=currentRun.analysis?.trace;
  const cards=[['市场点评',a?.market?.commentary||a?.market?.summary||'尚无本轮AI点评，先查看程序事实。'],['盘面结构',a?.market?.structure||'本轮尚无结构解读，量能与市场广度分别列于下方。'],['市场模式',a?.market?.mode_summary||a?.market?.state||'证据未齐，保留判断。']];
  return `${runChooser()}<div class="analysis-meta"><span>数据 ${esc(f.asof)} · ${esc(f.calendar?.phase||'按源时点查看')}</span><span>${trace?esc(trace.provider||'codex')+' · '+(trace.fallback_used?'后备解读':'本轮解读'):'程序事实'} · ${esc(time(currentRun.finished_at))}${currentRun.metadata?.input_mode==='saved_snapshot'?' · 保存快照重放':''}</span></div>${currentRun.error?`<p class="notice">${esc(currentRun.error.message)}</p>`:''}<div class="market-insights">${cards.map(([title,body])=>`<article class="card"><h3>${title}</h3><p>${esc(cut(body,180))}</p></article>`).join('')}</div><div class="stats"><div class="stat"><span>上涨 / 下跌</span><strong><span class="up">${num(m.advancing,0)}</span> / <span class="down">${num(m.declining,0)}</span></strong><small>${m.counts_complete?'沪深非ST来源目录已覆盖':'当前覆盖不完整'}</small></div><div class="stat"><span>沪深非ST累计成交额</span><strong>${short(m.amount)}</strong><small>${m.amount_complete?'对应源数据时点':'当前已取得范围'}</small></div><div class="stat"><span>股池封板率</span><strong>${percent(m.seal_rate)}</strong><small>提供方原股池口径</small></div><div class="stat"><span>有效量价候选</span><strong>${num(sel.eligible_count,0)} / ${f.candidates.length}</strong><small>日线为主，周线辅助</small></div></div><div class="market-grid">${marketVolumePanel()}<div class="card"><h3>市场广度</h3><div class="chart">${marketChart(m)}</div><p class="small muted">涨跌幅中位数 ${num(m.median_change_pct)}% · 平盘 ${num(m.unchanged,0)}</p><details><summary>宏观环境与资金旁证</summary><div>${macroTable()}${marginTable()}</div></details></div></div><div class="section-title"><div><h2>候选重点 · 最强三项</h2><p class="small muted">${esc(sel.label||'排序资料待补充')} · 相对强势仍可能需要等待</p></div><button class="link-button" data-view="candidates">宽基与候选图表 →</button></div><div class="grid3">${(sel.overall_top3||[]).map(id=>factItem(id)).filter(Boolean).map(candidateCard).join('')||'<div class="card">有效量价历史不足，暂无法选出前三。</div>'}</div><details><summary>计划提醒与数据覆盖</summary><div><p class="small">${state.plans.length} 项计划 · ${state.plans.filter(x=>x.status==='draft').length} 项待确认</p>${button('管理计划','go-plans')}${coveragePanel()}${trace?`<p class="small muted">AI提供方 ${esc(trace.provider||'codex')} · 模型 ${esc(trace.model||'旧轮次未记录型号')}</p>`:''}</div></details>`;
}

function macroTable() {
  return `<div class="table-wrap"><table><thead><tr><th>观察项</th><th>值 / 单位</th><th>源时点</th></tr></thead><tbody>${(currentRun.facts.macro||[]).map(x=>`<tr><td>${esc(x.name)}</td><td>${num(x.value)} ${esc(x.unit)}</td><td class="small">${esc(time(x.asof))}</td></tr>`).join('')}</tbody></table></div>`;
}
function marginTable() {
  const m=currentRun.facts.margin;
  return `<p class="small muted" style="margin-top:12px">融资余额 ${short(m?.latest?.financing_balance,'元')} · 较前一发布日变化 ${short(m?.change,'元')} · ${esc(m?.asof||'缺失')}</p><div class="table-wrap"><table><thead><tr><th>ETF观察篮子</th><th>最新份额</th><th>较前一发布日</th></tr></thead><tbody>${(currentRun.facts.etf_shares||[]).map(x=>`<tr><td>${esc(x.name)}</td><td>${short(x.rows?.[0]?.shares,'份')}<div class="small muted">${esc(x.rows?.[0]?.date||'源日期未提供')}</div></td><td>${short(x.change,'份')}</td></tr>`).join('')}</tbody></table></div>`;
}
function renderCandidates() {
  if(!currentRun?.facts)return emptyReport();
  const p=currentRun.presentation||{},visible=(p.groups||[]).reduce((n,g)=>n+g.asset_ids.length,0);
  return `${runChooser()}<div class="section-title"><div><h2>候选与依据</h2><p class="small muted">已分析 ${p.analyzed_count||0} 项 · 常规展示 ${visible} 项 · ${esc(p.label||'等待排序')}</p></div><select id="chart-period" style="max-width:125px"><option value="daily" ${chartPeriod==='daily'?'selected':''}>日线量价</option><option value="weekly" ${chartPeriod==='weekly'?'selected':''}>周线量价</option></select></div><div class="ma-legend"><span>MA5</span><span>MA20</span><span>MA60</span><span>MA120</span><small>悬停蜡烛可看对应日期开高低收与量</small></div>${(p.groups||[]).filter(g=>g.asset_ids.length).map(g=>`<section class="candidate-group"><div class="section-title"><h2>${esc(g.title)}</h2><span class="small muted">${g.asset_ids.length} 项</span></div><div class="candidate-grid">${g.asset_ids.map(factItem).filter(Boolean).map(candidateCard).join('')}</div></section>`).join('')}<p class="small muted">成交额前十行业实际分析 ${p.dynamic_analyzed||0} 项，只展示其中最强三项；固定关注保留，同一对象合并展示。完整分析记录保存在本轮历史中。</p>${coveragePanel()}`;
}

function planCard(p) {
  const data=p.payload,confirmed=state.confirmed_plans?.find(x=>x.id===p.id),ref=(confirmed||p).ref;
  const records=state.executions.filter(x=>String(x.payload.plan_ref||'').startsWith(p.id+'@'));
  const reviews=state.reviews.filter(x=>String(x.payload.plan_ref||'').startsWith(p.id+'@'));
  return `<article class="list-item"><div class="card-head"><div><h3>${esc(data.name)}</h3><p class="small muted">${data.plan_type==='observation'?'观察计划':'具体品种计划'} · 第${p.revision}版 · ${esc(time(p.created_at))}</p></div>${pill(p.status)}</div><p class="content">${esc(cut(data.entry,190))}</p>${confirmed&&confirmed.revision!==p.revision?`<p class="small muted">第 ${confirmed.revision} 版已确认依据仍留存，新版本尚待确认。</p>`:''}${data.missing?.length?`<p class="small muted">待补充 ${data.missing.length} 项 · 实际品种 ${esc(data.execution_asset_id||'未指定')}</p>`:''}<div class="toolbar">${button('查看','plan-detail',`data-id="${p.id}"`)}${button('修订草稿','edit-plan',`data-id="${p.id}"`)}${p.status==='draft'?button('确认此版本','confirm-plan',`data-id="${p.id}" data-revision="${p.revision}"`):''}${button('回填记录','execution',`data-ref="${esc(ref)}"`)}${button('复盘','review',`data-id="${p.id}"`,!records.length||Boolean(activeJob))}${button('版本记录','versions',`data-id="${p.id}" data-kind="plans"`)}${button('移入回收站','trash',`data-id="${p.id}" data-revision="${p.revision}"`,Boolean(activeJob))}</div>${reviews.length?`<details><summary>最近复盘（${reviews.length}）</summary><div>${reviews.slice(0,3).map(reviewCard).join('')}</div></details>`:''}</article>`;
}
function reviewCard(r) {
  const p=r.payload;
  const refs=[p.plan_ref,...(p.execution_refs||[])].filter(Boolean),deleted=refs.filter(ref=>(state.lifecycle||[]).some(l=>l.object_id===ref.split('@')[0]&&l.is_deleted));
  return `<div class="detail-block" style="margin:10px 0">${deleted.length?`<p class="counterpoint">本复盘引用的 ${deleted.length} 项原记录已在回收站；以下保留当时依据。</p>`:''}<h4>${esc(time(r.created_at))}</h4><p>${esc(p.summary)}</p><details><summary>展开复盘依据与建议</summary><div><h4>计划</h4><p>${esc(p.plan_review)}</p><h4>执行</h4><p>${esc(p.execution_review)}</p><h4>结果</h4><p>${esc(p.outcome_review)}</p>${list(p.uncertainties)}${(p.knowledge_proposals||[]).map((x,i)=>`<div class="detail-block"><strong>${esc(x.title)}</strong><p>${esc(x.body)}</p>${button('保存为档案草稿','proposal-review',`data-id="${r.id}" data-index="${i}"`)}</div>`).join('')}</div></details></div>`;
}
function renderPlans() {
  return `<div class="section-title"><div><h2>计划与执行</h2><p class="small muted">确认计划，人工执行；记录可移入回收站并恢复。</p></div><div class="toolbar">${button('直接记录计划','new-plan')}${button('新增执行记录','execution')}</div></div><div class="list">${state.plans.length?state.plans.map(planCard).join(''):'<div class="card empty">还没有计划，可以从候选拟定或直接记录。</div>'}</div><details><summary>执行回填（${state.executions.length}）</summary><div class="table-wrap"><table><thead><tr><th>实际时间 / 动作</th><th>品种与数值</th><th>说明</th><th>管理</th></tr></thead><tbody>${state.executions.map(x=>{const p=x.payload;const deleted=(state.lifecycle||[]).some(l=>l.object_id===p.plan_ref?.split('@')[0]&&l.is_deleted);return `<tr><td>${esc(time(p.occurred_at))}<br>${esc({buy:'买入回填',sell:'卖出回填',note:'说明记录'}[p.action])}</td><td>${esc(p.asset_id)}<br>价格 ${num(p.price)} · 数量 ${num(p.quantity)}</td><td>${esc(p.note)}${deleted?'<p class="counterpoint">关联原计划已移入回收站</p>':''}<details><summary>偏差与记录人</summary><div>${list(p.deviations)}${esc(p.recorded_by)}</div></details></td><td>${button('移入回收站','trash',`data-id="${x.id}" data-revision="${x.revision}"`,Boolean(activeJob))}</td></tr>`;}).join('')}</tbody></table></div></details><details><summary>回收站（${state.trash?.length||0}）</summary><div class="list">${(state.trash||[]).map(x=>`<div class="list-item"><div class="card-head"><div><h3>${esc(x.kind==='plan'?(x.payload.name||'计划'):(x.payload.asset_id||'执行记录'))}</h3><p class="small muted">${x.kind==='plan'?'计划':'执行回填'} · 第${x.revision}版 · 恢复保留原有状态与关联</p></div>${button('恢复','restore',`data-id="${x.id}" data-revision="${x.revision}"`,Boolean(activeJob))}</div></div>`).join('')||'<p class="small muted">回收站为空</p>'}</div></details>${state.reviews.length?`<details><summary>全部历史复盘（${state.reviews.length}，含已删除计划的引用）</summary><div>${state.reviews.map(reviewCard).join('')}</div></details>`:''}`;
}

function renderKnowledge() {
  const filtered=state.knowledge.filter(x=>knowledgeFilter==='all'||x.kind===knowledgeFilter);
  return `<div class="section-title"><div><h2>逐步积累你的交易体系</h2><p class="small muted">新归纳内容先保存为草稿；确认指定版本后用于推导。</p></div>${button('新增档案','new-knowledge')}</div><div class="toolbar" style="margin-bottom:16px"><select id="knowledge-filter" style="max-width:210px">${[['all','全部档案'],['logic','逻辑'],['technical','技术'],['mode','模式']].map(([v,n])=>`<option value="${v}" ${v===knowledgeFilter?'selected':''}>${n}</option>`).join('')}</select><span class="small muted">${state.confirmed_knowledge.length} 个当前已确认条目</span></div><div class="list">${filtered.map(x=>{const active=state.confirmed_knowledge.find(a=>a.id===x.id);return `<article class="list-item"><div class="card-head"><div><h3>${esc(x.payload.title)}</h3><div class="small muted">${esc((x.payload.layers||[x.kind]).map(k=>kinds[k]||k).join(' / '))} · 第${x.revision}版 ${x.payload.usage==='risk'?'· 仓位/风险规则':''}</div></div>${pill(x.status)}</div><p class="content">${esc(x.payload.body)}</p><p class="small muted">来源：${esc(x.payload.source)}${active&&active.revision!==x.revision?' · 第'+active.revision+'版仍为当前已确认依据':''}</p><div class="toolbar">${button('修订','edit-knowledge',`data-id="${x.id}"`)}${x.status==='draft'?button('确认此版本','confirm-knowledge',`data-id="${x.id}" data-revision="${x.revision}"`):''}${button('历史版本','versions',`data-id="${x.id}" data-kind="knowledge"`)}</div></article>`;}).join('')}</div>${renderRunProposals()}`;
}
function renderRunProposals() {
  const proposals=currentRun?.analysis?.result?.knowledge_proposals||[];
  if(!proposals.length) return '';
  return `<div class="section-title"><h2>本轮归纳建议</h2></div><div class="list">${proposals.map((p,i)=>`<div class="list-item"><h3>${esc(p.title)}</h3><p class="content">${esc(p.body)}</p>${button('保存为草稿','proposal-run',`data-index="${i}"`)}</div>`).join('')}</div>`;
}
function renderSettings() {
  const cfg=configInfo?.config,ai=aiInfo?.config||cfg?.ai||{},ds=ai.deepseek||{};
  return `<section class="card"><div class="card-head"><div><h2>AI接入与后备</h2><p class="small muted">Codex沿用当前可用配置；DeepSeek可作后备或直接使用。</p></div>${button('检查接入状态','check-codex')}</div><p id="codex-status" class="small muted">${aiInfo?.key_configured?'DeepSeek凭据已配置，密钥不回显。':'DeepSeek尚未配置密钥。'}</p><div class="fields"><label class="field"><span>优先使用</span><select id="ai-provider"><option value="codex" ${ai.provider!=='deepseek'?'selected':''}>Codex · 失败时使用已启用后备</option><option value="deepseek" ${ai.provider==='deepseek'?'selected':''}>DeepSeek API</option></select></label><label class="field"><span>Codex命令</span><input id="ai-command" value="${esc(ai.command||'codex')}"></label><label class="field"><span>Codex模型（留空沿用现有配置）</span><input id="ai-model" value="${esc(ai.model||'')}"></label><label class="field"><span>Codex最长等待（秒）</span><input id="ai-timeout" type="number" min="30" max="900" value="${ai.timeout||300}"></label><label class="field"><span>DeepSeek服务地址</span><input id="ds-url" value="${esc(ds.base_url||'https://api.deepseek.com')}"></label><label class="field"><span>DeepSeek模型</span><input id="ds-model" value="${esc(ds.model||'deepseek-flash')}"></label><label class="field"><span>DeepSeek API Key（留空保留现有）</span><input id="ds-key" type="password" autocomplete="new-password" placeholder="${aiInfo?.key_configured?'已配置 · 输入以更新':'在本机填写密钥'}"></label><label class="field"><span>DeepSeek最长等待（秒）</span><input id="ds-timeout" type="number" min="30" max="900" value="${ds.timeout||180}"></label></div><div class="toolbar"><label class="toggle"><input id="ai-enabled" type="checkbox" ${ai.enabled!==false?'checked':''}> 启用AI</label><label class="toggle"><input id="ds-enabled" type="checkbox" ${ds.enabled?'checked':''}> 启用DeepSeek</label>${button('保存AI配置','save-ai')}</div><p class="form-note">密钥保存在本机独立凭据文件，报告与资料迁移不包含密钥。每次启动默认关闭周期运行。</p></section><section class="card"><div class="card-head"><h2>候选与数据配置</h2>${button('添加个股','add-stock')}</div><p class="small muted">同花顺行业定义，宽基/个股清单与实际交易品种映射由你配置。</p><details><summary>编辑完整配置文件</summary><div><p class="form-note">文件入口：${esc(configInfo?.path||state.config_path||'')}</p>${configInfo?.error?`<p class="notice error">${esc(configInfo.error.message)}</p>`:''}<textarea id="config-editor" class="code" spellcheck="false">${esc(cfg?JSON.stringify(cfg,null,2):(configInfo?.raw||''))}</textarea><div class="toolbar" style="margin-top:12px">${button('保存配置','save-config')}${button('重新读取','reload-config')}</div><p class="form-note">不要把密钥放进此JSON；上方有独立入口。</p></div></details></section><section class="card"><h2>本地资料迁移</h2><p class="small muted">知识、计划、执行、复盘、AI记录与回收站状态一起迁移；不包含登录凭据。导入不会开启定时。</p><div class="toolbar">${button('导出资料','export-archive')}<label class="button small">导入资料<input id="import-file" type="file" accept=".json,application/json" hidden></label></div></section>`;
}

function render() {
  document.querySelectorAll('.nav-item').forEach(x=>x.classList.toggle('selected',x.dataset.view===view));
  $('#page-title').textContent=labels[view];
  $('#view-content').innerHTML=({overview:renderOverview,candidates:renderCandidates,plans:renderPlans,knowledge:renderKnowledge,settings:renderSettings}[view])();
}

function field(name,label,value='',type='text',full=false) {
  const element=type==='textarea'?`<textarea name="${name}">${esc(value)}</textarea>`:`<input type="${type}" name="${name}" value="${esc(value)}" ${type==='number'?'step="any" min="0"':''}>`;
  return `<label class="field ${full?'full':''}"><span>${label}</span>${element}</label>`;
}
function openEditor(title,body,submit=null,label='保存') {
  $('#dialog-title').textContent=title;$('#editor-body').innerHTML=body;$('#form-error').hidden=true;
  $('#form-submit').hidden=!submit;$('#form-submit').textContent=label;editorSubmit=submit;
  if(!$('#editor').open) $('#editor').showModal();
}
function candidateDetail(id) {
  const item=factItem(id);if(!item)return;const a=opinion(id),t=item.technical||{},v=item.volume_price||{},last=t.latest||{};
  openEditor(item.name,`<div class="candle-chart">${currentRun.charts?.[id]?.[chartPeriod]||''}</div><div class="ma-legend"><span>MA5</span><span>MA20</span><span>MA60</span><span>MA120</span></div><h3>量价理解</h3><p>${esc(a?.volume_price_reading||v.summary||'资料不足')}</p><p class="small muted">比较截至 ${esc(v.asof||'未知')} ${v.current_forming?'（当前日线形成中，比较使用最近完整日）':''}</p><h3>综合强弱</h3><p>${esc(a?.strength_reason||a?.reason||'未获得AI综合解读')}</p><div class="metric-chips"><span>前5日量比 ${num(v.volume_vs_5)}×</span><span>前20日量比 ${num(v.volume_vs_20)}×</span><span>20日涨幅 ${num(v.return_20d_pct)}%</span></div><details><summary>逻辑、模式与反证</summary><div>${list(a?.logic_refs?.map(knowledgeName))}${list(a?.mode_refs?.map(knowledgeName))}${list(a?.against)}${list(a?.missing)}${list(v.missing)}</div></details><details><summary>辅助指标、原始依据与来源</summary><div><p class="small">MACD DIF ${num(last.dif)} / DEA ${num(last.dea)} · OBV ${short(last.obv)} · CCI ${num(last.cci)}</p>${list(a?.evidence_refs?.map(evidenceName))}<p class="small muted">${esc(t.adjustment||'')} · ${esc(t.volume_unit||'')} · ${esc(t.source||'')}</p>${list(t.reasons)}</div></details>`);
}

function planDetail(id) {
  const x=state.plans.find(x=>x.id===id);if(!x)return;const p=x.payload;
  openEditor(p.name,`${pill(x.status)}<p class="small muted">${esc(x.ref)} · ${p.plan_type==='observation'?'观察计划':'具体品种计划'} · 实际品种 ${esc(p.execution_asset_id||'未指定')}</p><div class="detail-grid">${[['逻辑依据',p.basis.logic],['技术依据',p.basis.technical],['模式依据',p.basis.mode],['买入/观察条件',p.entry],['退出条件',p.exit],['仓位与风险',p.position_risk],['有效期',p.validity]].map(([k,v])=>`<div class="detail-block"><h4>${k}</h4><p>${esc(v||'待补充')}</p></div>`).join('')}</div><h3>待补充</h3>${list(p.missing)}<p class="small muted">确认人 ${esc(x.confirmed_by||'尚未确认')} · ${esc(time(x.confirmed_at))}</p>`);
}
function editPlan(id=null) {
  const old=id?state.plans.find(x=>x.id===id):null,p=old?.payload||{},basis=p.basis||{};
  const body=`<p class="form-note">实际品种由你指定。关键资料未齐时保留为观察或待补充草稿；保存后仍需确认版本。</p><div class="fields">${field('name','名称',p.name)}${field('asset_id','分析标的ID，例如 ths:881155 / sh000300',p.asset_id)}<label class="field"><span>计划类型</span><select name="plan_type"><option value="observation" ${p.plan_type!=='action'?'selected':''}>观察计划</option><option value="action" ${p.plan_type==='action'?'selected':''}>已指定品种的计划</option></select></label>${field('execution_asset_id','实际ETF/个股ID，观察计划可空',p.execution_asset_id)}${field('basis_logic','逻辑依据',basis.logic,'textarea')}${field('basis_technical','技术依据',basis.technical,'textarea')}${field('basis_mode','模式依据',basis.mode,'textarea')}${field('entry','买入或观察条件',p.entry,'textarea')}${field('exit','退出条件',p.exit,'textarea')}${field('position_risk','仓位与风险限制',p.position_risk,'textarea')}${field('validity','有效期说明',p.validity,'textarea')}${field('validity_until','明确截止日期（可空）',p.validity_until,'date')}${field('missing','待补充事项，每行一项；补齐后再移除',(p.missing||[]).join('\n'),'textarea',true)}</div>`;
  openEditor(old?'修订计划 · 新版本草稿':'直接记录计划',body,async form=>{
    const payload={name:form.get('name'),asset_id:form.get('asset_id'),plan_type:form.get('plan_type'),execution_asset_id:form.get('execution_asset_id')?.trim()||null,basis:{logic:form.get('basis_logic'),technical:form.get('basis_technical'),mode:form.get('basis_mode')},entry:form.get('entry'),exit:form.get('exit'),position_risk:form.get('position_risk'),validity:form.get('validity'),validity_until:form.get('validity_until')||null,missing:String(form.get('missing')||'').split('\n').map(x=>x.trim()).filter(Boolean)};
    if(old)await api('/api/plans/'+old.id+'/revise','POST',{payload,expected_revision:old.revision});
    else await api('/api/plans/manual','POST',{payload});
    view='plans';toast('计划草稿已保存，确认版本后再按计划执行。');
  },'保存草稿');
}
function editKnowledge(id=null) {
  const old=id?state.knowledge.find(x=>x.id===id):null,p=old?.payload||{};
  const body=`<div class="fields">${field('title','标题',p.title)}<label class="field"><span>主要层面</span><select name="kind" ${old?'disabled':''}>${Object.entries(kinds).map(([k,v])=>`<option value="${k}" ${(old?.kind||'logic')===k?'selected':''}>${v}</option>`).join('')}</select></label><div class="field full"><span>可关联多个层面</span><div class="checkboxes">${Object.entries(kinds).map(([k,v])=>`<label><input type="checkbox" name="layers" value="${k}" ${(p.layers||[old?.kind||'logic']).includes(k)?'checked':''}> ${v}</label>`).join('')}</div></div>${field('body','定义、依据或总结',p.body,'textarea',true)}${field('source','来源',p.source||'用户补充','textarea',true)}${field('evidence','证据说明或链接，每行一项',(p.evidence||[]).join('\n'),'textarea',true)}<label class="field inline full"><input type="checkbox" name="risk" ${p.usage==='risk'?'checked':''}><span>这是个人仓位 / 风险规则，确认后供计划模块引用</span></label></div>`;
  openEditor(old?'修订档案 · 新版本草稿':'新增档案',body,async form=>{
    const kind=old?.kind||form.get('kind'),layers=[...new Set([kind,...form.getAll('layers')])];
    const payload={...(old?.payload||{}),title:form.get('title'),body:form.get('body'),layers,source:form.get('source'),usage:form.get('risk')?'risk':'general',evidence:String(form.get('evidence')||'').split('\n').map(x=>x.trim()).filter(Boolean)};
    if(old)await api('/api/knowledge/'+old.id+'/revise','POST',{payload,expected_revision:old.revision});
    else await api('/api/knowledge','POST',{kind,payload});
    view='knowledge';toast('档案草稿已保存。');
  },'保存草稿');
}
function localDateTime() {return new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date()).replace(' ','T');}
function executionForm(ref='') {
  const old=objectByRef(ref),p=old?.payload||{};
  const choices=[...state.confirmed_plans||[],...state.plans].filter((x,i,a)=>a.findIndex(t=>t.ref===x.ref)===i);
  const body=`<p class="form-note">这里只记录你实际操作或观察的事实，不会发送买卖委托。时间按北京时间填写。</p><div class="fields"><label class="field full"><span>关联计划版本</span><select name="plan_ref"><option value="">未关联计划（买卖会标注计划外）</option>${choices.map(x=>`<option value="${esc(x.ref)}" ${ref===x.ref?'selected':''}>${esc(x.payload.name)} / 第${x.revision}版 / ${esc(statuses[x.status])}</option>`).join('')}</select></label>${field('asset_id','实际品种ID；说明记录可填分析标的',p.execution_asset_id||p.asset_id||'')}<label class="field"><span>记录类型</span><select name="action"><option value="note">观察或说明（没有买卖）</option><option value="buy">实际买入回填</option><option value="sell">实际卖出回填</option></select></label>${field('occurred_at','实际发生时间 / 北京时间',localDateTime(),'datetime-local')}${field('price','成交价（可空）','','number')}${field('quantity','数量（可空）','','number')}${field('amount','金额（可空）','','number')}${field('note','事实说明与执行情况','','textarea',true)}</div>`;
  openEditor('回填实际记录',body,async form=>{
    const dt=String(form.get('occurred_at')||'');
    const body={plan_ref:form.get('plan_ref')||null,asset_id:form.get('asset_id'),action:form.get('action'),occurred_at:dt+(dt.length===16?':00':'')+'+08:00',price:form.get('price')||null,quantity:form.get('quantity')||null,amount:form.get('amount')||null,note:form.get('note'),recorded_by:'翔宇'};
    await api('/api/executions','POST',body);view='plans';toast('回填记录已保存。');
  });
}

async function action(target) {
  if(target.dataset.action==='go-plans'){view='plans';render();return;}
  if(['trash','restore'].includes(target.dataset.action)){
    const remove=target.dataset.action==='trash';
    if(remove&&!window.confirm('将此记录移入回收站？可以恢复，关联计划、执行和历史复盘会保留。'))return;
    await api('/api/objects/'+encodeURIComponent(target.dataset.id)+'/'+target.dataset.action,'POST',{expected_revision:Number(target.dataset.revision),actor:'翔宇'});
    toast(remove?'已移入回收站，可随时恢复。':'已恢复原记录。');await loadState(true);return;
  }
  if(target.dataset.action==='save-ai'){
    const cfg={...(aiInfo?.config||configInfo.config.ai),provider:$('#ai-provider').value,command:$('#ai-command').value.trim(),model:$('#ai-model').value.trim(),timeout:Number($('#ai-timeout').value),enabled:$('#ai-enabled').checked,deepseek:{enabled:$('#ds-enabled').checked,base_url:$('#ds-url').value.trim(),model:$('#ds-model').value.trim(),timeout:Number($('#ds-timeout').value)}};
    const body={config:cfg};if($('#ds-key').value.trim())body.api_key=$('#ds-key').value.trim();
    aiInfo=await api('/api/ai','PUT',body);configInfo=await api('/api/config');toast('AI配置已保存，下一次调用使用。');render();return;
  }
  const name=target.dataset.action,id=target.dataset.id;
  if(name==='close-dialog'){$('#editor').close();return;}
  if(name==='run'){const r=await api('/api/run','POST',{});watchJob(r.job_id);await loadState();return;}
  if(name==='cancel-run'){await api('/api/cancel','POST',{});toast('已请求停止，正在保存本轮状态。');return;}
  if(name==='report'){if(currentRun)window.open('/api/runs/'+encodeURIComponent(currentRun.id)+'/report','_blank','noopener');return;}
  if(name==='candidate-detail'){candidateDetail(id);return;}
  if(name==='draft-plan'){const r=await api('/api/plans/draft','POST',{run_id:currentRun.id,asset_id:id});toast('正在拟定计划草稿…');watchJob(r.job_id);await loadState();return;}
  if(name==='new-plan'){editPlan();return;}
  if(name==='edit-plan'){editPlan(id);return;}
  if(name==='plan-detail'){planDetail(id);return;}
  if(name==='execution'){executionForm(target.dataset.ref||'');return;}
  if(name==='new-knowledge'){editKnowledge();return;}
  if(name==='edit-knowledge'){editKnowledge(id);return;}
  if(name==='confirm-plan'||name==='confirm-knowledge'){
    const kind=name==='confirm-plan'?'plans':'knowledge',row=state[kind].find(x=>x.id===id),revision=Number(target.dataset.revision);
    if(!window.confirm(`确认“${row?.payload.title||row?.payload.name||id}”第${revision}版？\n本次确认会留下版本与时间记录。`))return;
    await api('/api/'+kind+'/'+encodeURIComponent(id)+'/confirm','POST',{revision,actor:'翔宇'});toast('该版本已确认。');await loadState(true);return;
  }
  if(name==='versions'){
    const rows=await api('/api/'+target.dataset.kind+'/'+encodeURIComponent(id)+'/versions');
    openEditor('版本记录',rows.map(x=>`<div class="detail-block" style="margin-bottom:10px"><h3>第${x.revision}版 ${pill(x.status)}</h3><p class="small muted">创建 ${esc(time(x.created_at))} · 确认 ${esc(time(x.confirmed_at))} · ${esc(x.confirmed_by||'')}</p><pre class="pre">${esc(JSON.stringify(x.payload,null,2))}</pre></div>`).join(''));return;
  }
  if(name==='review'){const r=await api('/api/reviews','POST',{plan_id:id});toast('正在对照历史计划与回填复盘…');watchJob(r.job_id);await loadState();return;}
  if(name==='proposal-review'){await api('/api/knowledge/from-review','POST',{review_id:id,index:Number(target.dataset.index)});view='knowledge';toast('建议已保存为待确认草稿。');await loadState(true);return;}
  if(name==='proposal-run'){await api('/api/knowledge/from-run','POST',{run_id:currentRun.id,index:Number(target.dataset.index)});view='knowledge';toast('建议已保存为待确认草稿。');await loadState(true);return;}
  if(name==='reload-config'){[configInfo,aiInfo]=await Promise.all([api('/api/config'),api('/api/ai')]);render();return;}
  if(name==='save-config'){
    let config;try{config=JSON.parse($('#config-editor').value);}catch(_){throw new Error('JSON格式无效，请检查引号、逗号和括号。');}
    await api('/api/config','PUT',{config});configInfo=await api('/api/config');toast('配置已保存，下轮使用。');await loadState(true);return;
  }
  if(name==='check-codex'){const r=await api('/api/codex');$('#codex-status').textContent=`Codex：${r.available?'命令可启动，实际以调用为准':'命令暂不可用'} · 认证 ${r.auth_kind}；DeepSeek：${r.deepseek?.key_configured?'凭据已配置':'未配置凭据'}${r.deepseek?.enabled?'，已启用':'，未启用'}`;return;}
  if(name==='add-stock'){
    openEditor('添加要分析的个股',`<p class="form-note">这是你主动配置的分析对象。示例格式 sh600000、sz000001。</p>${field('asset_id','个股ID')}${field('name','名称')}`,async form=>{
      const current=await api('/api/config');if(!current.config)throw new Error('请先修复配置JSON。');
      current.config.stocks.push({asset_id:form.get('asset_id'),name:form.get('name')});await api('/api/config','PUT',{config:current.config});configInfo=await api('/api/config');toast('个股已加入配置，下轮生效。');
    });return;
  }
  if(name==='export-archive'){
    const response=await fetch('/api/export');
    if(!response.ok){const data=await response.json();throw new Error(data.error?.message||'导出失败');}
    const url=URL.createObjectURL(await response.blob()),link=document.createElement('a');link.href=url;link.download='p03-trade-archive.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),30000);return;
  }
}

document.addEventListener('click',async event=>{
  const nav=event.target.closest('[data-view]');
  if(nav){view=nav.dataset.view;if(view==='settings')try{[configInfo,aiInfo]=await Promise.all([api('/api/config'),api('/api/ai')]);}catch(e){toast(e.message,true);}render();return;}
  const target=event.target.closest('[data-action]');if(!target)return;
  try{await action(target);}catch(error){toast(error.message,true);}
});
document.addEventListener('change',async event=>{
  const target=event.target;
  try{
    if(target.id==='auto-refresh'){
      const c=await api('/api/config');if(!c.config)throw new Error('请先修复配置。');c.config.auto_refresh=target.checked;await api('/api/config','PUT',{config:c.config});configInfo=c;await loadState(true);
    }else if(target.id==='run-select'){
      followLatest=target.value==='latest';const id=followLatest?state.latest_report_id:target.value;
      if(id)currentRun=await api('/api/runs/'+encodeURIComponent(id));render();
    }else if(target.id==='chart-asset'){selectedAsset=target.value;render();}
    else if(target.id==='chart-period'){chartPeriod=target.value;render();}
    else if(target.id==='chart-series'){chartSeries=target.value;render();}
    else if(target.id==='knowledge-filter'){knowledgeFilter=target.value;render();}
    else if(target.id==='import-file'){
      const file=target.files[0];if(!file)return;
      const max=configInfo?.config?.max_import_bytes||104857600;if(file.size>max)throw new Error('文件超过当前导入大小上限。');
      if(!window.confirm('合并此文件中的本地资料，并应用其中的候选配置？\n已有对象版本出现内容冲突时会拒绝覆盖。')){target.value='';return;}
      let archive;try{archive=JSON.parse(await file.text());}catch(_){throw new Error('迁移文件不是有效JSON。');}
      const r=await api('/api/import','POST',{archive,apply_config:true});toast(`导入完成：新增${r.objects_added}个版本、${r.runs_added}个轮次。`);configInfo=await api('/api/config');await loadState(true);
    }
  }catch(error){toast(error.message,true);$('#auto-refresh').checked=Boolean(state.auto_refresh);}
});
$('#editor-form').addEventListener('submit',async event=>{
  event.preventDefault();if(!editorSubmit)return;
  $('#form-submit').disabled=true;$('#form-error').hidden=true;
  try{await editorSubmit(new FormData(event.target));$('#editor').close();await loadState(true);}
  catch(error){$('#form-error').textContent=error.message;$('#form-error').hidden=false;}
  finally{$('#form-submit').disabled=false;}
});
loadState(true);
setInterval(()=>loadState(),15000);
