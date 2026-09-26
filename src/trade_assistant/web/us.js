'use strict';

function usObservationCard(item) {
  const tech=item.technical||{},period=cardPeriod(item.asset_id),p=item.premium;
  return `<article class="card candidate-card observation-card" data-asset-id="${esc(item.asset_id)}"><div class="title-line"><h3>${esc(item.name)}</h3><span class="pill neutral">${p?'境内执行工具':'期货观察'}</span></div><div class="card-chart-tools"><span class="small muted">${esc(item.asset_id)} · ${esc(tech.asof||'缺历史')}</span>${chartToggle(item.asset_id,period)}</div><div class="candle-chart">${chartSVG(item,period)}</div>${maControls(item.asset_id)}${p?`<div class="premium-line"><span>${esc(p.label||'溢价基准待取得')}</span><strong>${num(p.value)}${p.value==null?'':'%'}</strong></div><p class="small muted">报价 ${esc(p.price_asof||'未知')}<br>净值 ${esc(p.basis_date||'未取得')} · ${num(p.basis_value,4)} CNY</p><details><summary>溢价口径与固定依据</summary><div><p>${esc(p.definition||p.reason||'资料不足')}</p><p class="small muted">${esc(p.iopv_status)}；净值发布日期${esc(p.published_at||'未提供')}，不能用获取日期代替。</p><p class="small muted">${esc(item.pairing_ref)} · 首次固定 ${esc(item.selection?.selected_at||'')}；比较窗口 ${esc(item.selection?.window?.[0]||'')} → ${esc(item.selection?.window?.slice(-1)[0]||'')}</p></div></details>`:`<p class="small muted">COMEX近月连续观察；含提供方换月影响，非现货。</p>`}</article>`;
}

function usIndexGrid() {
  const f=currentRun.facts;
  return `<div class="us-index-grid">${f.candidates.filter(x=>x.kind==='index').map(x=>`<section class="index-pair">${candidateCard(x)}<div class="pair-link">对应境内ETF</div>${f.paired_etfs?.[x.asset_id]?usObservationCard(f.paired_etfs[x.asset_id]):'<div class="card empty small">ETF配对或行情资料不足。筛选依据见配置入口与数据覆盖记录。</div>'}</section>`).join('')}</div>`;
}

function usMacroCard(symbol,title) {
  const item=currentRun.facts.macro?.find(x=>x.symbol===symbol),rows=item?.rows||[],last=rows.slice(-1)[0];
  return `<article class="card macro-card"><div class="card-head"><h3>${esc(title||item?.name||symbol)}</h3><strong>${num(last?.value)}<small> ${esc(item?.unit||'')}</small></strong></div><p class="small muted">${esc(item?.asof||'尚无可核实序列')} · ${esc(item?.frequency||'')} ${last?.value_type?'· '+esc({actual:'实际已发布',estimate:'预测',mixed:'实际与预测混合'}[last.value_type]||last.value_type):''}</p>${currentRun.market_charts?.[symbol]||'<div class="empty small">数据缺口已保留，不填零或预测值。</div>'}<details><summary>定义、来源与记录</summary><div><p class="small">${esc(item?.definition||'已尝试免费来源；可在配置的补充观察入口录入有出处的资料。')}</p><p class="small muted">${esc(item?.source||'')}<br>获取 ${esc(item?.fetched_at||'未取得')} · 发布 ${esc(item?.published_at||'逐点未提供')}<br>${esc(item?.revision_note||'')}</p>${['US_DEFAULT_RATE','SP500_EPS','SP500_NET_MARGIN'].includes(symbol)?`<pre class="pre">${esc(JSON.stringify(rows.slice(-8),null,2))}</pre>`:''}</div></details></article>`;
}

function usFundamentals() {
  return `<section><div class="section-title"><h2>基本面观察</h2><span class="small muted">按各指标实际发布频率</span></div><div class="market-history-grid">${usMacroCard('NET_LIQUIDITY','短期 · 流动性参考')}${usMacroCard('SOFR','短期 · 资金价格')}</div><details class="us-block"><summary>中期 · 利率、美元与信用</summary><div class="market-history-grid">${usMacroCard('T10Y2Y')}${usMacroCard('DGS10')}${usMacroCard('DFII10')}${usMacroCard('DXY')}${usMacroCard('BAMLH0A0HYM2')}${usMacroCard('US_DEFAULT_RATE','美国企业实际违约')}</div></details><details class="us-block"><summary>长期 · 盈利与经济增长</summary><div class="market-history-grid">${usMacroCard('SP500_EPS','标普500 EPS')}${usMacroCard('SP500_EPS_YOY','实际EPS同比')}${usMacroCard('SP500_NET_MARGIN','标普500净利润率')}${usMacroCard('GDP_YOY','实际GDP同比')}</div></details></section>`;
}

function usRenderOverview() {
  if(!currentRun?.facts)return emptyReport();
  const f=currentRun.facts,m=currentRun.analysis?.result?.market||{},b=f.breadth||{},sel=currentRun.presentation||{},byId=new Map(f.candidates.map(x=>[x.asset_id,x]));
  return `${runChooser()}<p class="small muted us-time">美国行情日 ${esc(f.asof||'待取得')} · ${esc(f.calendar?.phase||'')} · ${esc(f.calendar?.timezone||'America/New_York')}；境内ETF日期单独展示</p><section class="summary-grid">${[['市场点评',m.commentary||m.summary],['盘面结构',m.structure],['市场模式',m.mode_summary||m.state]].map(([title,text])=>`<article class="card"><h3>${title}</h3><p>${esc(text||'本轮尚无AI理解，以下保留真实程序事实。')}</p></article>`).join('')}</section><div class="section-title"><h2>三大指数与固定ETF</h2></div>${usIndexGrid()}<div class="section-title"><h2>全市场广度与纽约金</h2></div><section class="market-history-grid"><article class="card"><div class="card-head"><h3>NYSE＋NASDAQ 涨跌家数</h3><span class="small">涨 ${num(b.advancing,0)} / 跌 ${num(b.declining,0)}</span></div><p class="small muted">${esc(b.asof||'待取得')} · ${b.complete?'来源完整':'已取得范围，覆盖有缺口'}</p>${currentRun.market_charts?.breadth||''}<details><summary>统计范围与历史覆盖</summary><div><p class="small">${esc(b.definition||'未取得')}</p><p class="small muted">平盘 ${num(b.unchanged,0)} · 缺报价 ${num(b.unknown_prices,0)} · 未识别类别 ${num(b.unclassified,0)}。历史 ${b.rows?.length||0} 日；按真实观察积累，缺失不补零。</p>${list(b.limitations||[])}</div></details></article>${(f.watch_indices||[]).map(usObservationCard).join('')}</section>${usFundamentals()}<div class="section-title"><div><h2>候选重点 · 最强三项</h2><p class="small muted">${esc(sel.label||'仅技术参考')}；相对强弱不是入场许可。</p></div></div><section class="us-index-grid">${(sel.overall_top3||[]).filter(id=>byId.has(id)).map(id=>candidateCard(byId.get(id))).join('')||'<div class="card empty">量价资料不足，当前没有完整可比的前三。</div>'}</section>${coveragePanel()}`;
}

function usRenderCandidates() {
  if(!currentRun?.facts)return emptyReport();
  return `${runChooser()}<div class="section-title"><h2>美国三大指数</h2></div>${usIndexGrid()}<div class="section-title"><div><h2>选定美国行业</h2><p class="small muted">使用明确标注的美国本土ETF观察代理；各图可独立切换日周与均线显示。</p></div></div><section class="market-history-grid">${currentRun.facts.candidates.filter(x=>x.kind==='industry').map(candidateCard).join('')}</section>${coveragePanel()}`;
}

function marketSettings() {
  const cfg=configInfo?.config||{},scheduled=cfg.scheduled_markets||['CN'];
  return `<section class="card"><h2>周期运行范围</h2><p class="small muted">查看市场与定时范围分开设置；每次启动默认关闭定时。</p><div class="toolbar">${['CN','US'].map(m=>`<label class="toggle"><input name="schedule-market" type="checkbox" value="${m}" ${scheduled.includes(m)?'checked':''}>${m==='US'?'美股':'A股'}</label>`).join('')}${button('保存运行范围','save-market-schedule')}</div></section>${selectedMarket==='US'?`<section class="card"><h2>境内ETF固定配对</h2><p class="small muted">日常刷新不换代码。重新筛选会先展示同20日窗口、跟踪目标和覆盖情况，确认后才变更当前配对；历史引用原版本。</p><div class="toolbar">${[['us:DJI','道琼斯'],['us:NDX','纳斯达克100'],['us:SPX','标普500']].map(([id,n])=>button('查看/调整 '+n,'pairing-preview',`data-id="${id}"`,Boolean(activeJob))).join('')}</div></section><section class="card"><h2>补充有出处的基本面资料</h2><p class="small muted">适用于免费来源暂缺的实际违约、标普500 EPS与净利润率。记录必须带来源、样本、期间及发布日期。</p>${button('补充观察记录','us-observation')}<p class="form-note">技术分析参数在完整配置的 us.technical；图表均线选择仅影响展示。</p></section>`:''}`;
}

async function showPairingPreview(id) {
  const [preview,current]=await Promise.all([api('/api/us/pairings/previews/'+encodeURIComponent(id)),api('/api/us/pairings')]);
  const old=current.pairings.find(x=>x.payload.index_id===preview.index_id),valid=preview.rows.filter(x=>x.eligible);
  openEditor('ETF固定配对 · '+preview.index_id,`<p>当前：${esc(old?old.payload.name+' '+old.payload.asset_id:'尚未固定')}。窗口 ${esc(preview.window[0])} → ${esc(preview.window.slice(-1)[0])}</p><p class="small muted">${esc(preview.policy)}</p>${!preview.coverage_complete?'<p class="notice">筛选覆盖尚不完整，不能认定全范围成交额最大；可以明确选取已核实品种。</p>':''}<div class="table-wrap"><table><thead><tr><th>ETF</th><th>20日均成交额</th><th>依据/缺口</th></tr></thead><tbody>${preview.rows.map(x=>`<tr><td>${esc(x.name)}<br>${esc(x.asset_id)}</td><td>${short(x.amount_mean20,'元')}</td><td>${esc(x.tracking||'身份未核实')}<br>${esc(x.reason||'')}</td></tr>`).join('')}</tbody></table></div><label class="field"><span>明确固定为</span><select name="asset_id">${valid.map(x=>`<option value="${esc(x.asset_id)}" ${x.asset_id===(old?.payload.asset_id||preview.selected)?'selected':''}>${esc(x.name+' '+x.asset_id)}</option>`).join('')}</select></label>`,valid.length?async form=>{
    await api('/api/us/pairings/bind','POST',{preview_id:preview.id,asset_id:form.get('asset_id'),expected_revision:old?.revision||0,confirmed:true});toast('已固定新配对版本；下轮分析使用，旧报告保留。');
  }:null,'确认固定代码');
}

async function usAction(target) {
  const name=target.dataset.action;
  if(name==='save-market-schedule'){
    const values=[...document.querySelectorAll('[name="schedule-market"]:checked')].map(x=>x.value);
    if(!values.length)throw new Error('至少选择一个周期运行市场。');
    const c=await api('/api/config');c.config.scheduled_markets=values;await api('/api/config','PUT',{config:c.config});configInfo=await api('/api/config');toast('周期范围已保存。');await loadState(true);return true;
  }
  if(name==='pairing-preview'){
    const r=await api('/api/us/pairings/preview','POST',{index_id:target.dataset.id});watchJob(r.job_id);await loadState();return true;
  }
  if(name==='us-observation'){
    openEditor('新增基本面观察',`<div class="fields"><label class="field"><span>指标</span><select name="symbol"><option value="US_DEFAULT_RATE">美国企业实际违约率</option><option value="SP500_EPS">标普500 EPS</option><option value="SP500_NET_MARGIN">标普500净利润率</option></select></label><label class="field"><span>实际/预期</span><select name="value_type"><option value="actual">实际已发布</option><option value="estimate">预测</option><option value="mixed">实际与预测混合</option></select></label>${field('value','数值（可为负EPS）')}${field('unit','单位，如 % / 美元每股')}${field('date','观测期日期','','date')}${field('published_at','来源发布日期','','date')}${field('region','地区','美国')}${field('sample','统计样本（债券/发行人/标普500）')}${field('period','期间与频率，例如季度 / TTM')}${field('source','公开来源URL（HTTPS）')}${field('definition','定义与计算口径','','textarea',true)}${field('revision_note','发布版本/修订说明','','textarea',true)}</div>`,async form=>{
      const c=await api('/api/config'),item=Object.fromEntries(form.entries());item.value=Number(item.value);c.config.us.observations.push(item);await api('/api/config','PUT',{config:c.config});configInfo=await api('/api/config');toast('已记录来源与版本，下轮分析使用。');
    });return true;
  }
  return false;
}
