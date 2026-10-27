/* Read-only presentation of database-backed metrics and server-derived review signals. */
window.RelayDashboard = (() => {
  'use strict';
  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const money = c => new Intl.NumberFormat('en-US', {style:'currency',currency:'USD',maximumFractionDigits:0}).format(c / 100);
  const precise = c => new Intl.NumberFormat('en-US', {style:'currency',currency:'USD'}).format(c / 100);
  const shortDate = v => new Date(v + 'T12:00:00Z').toLocaleDateString(undefined, {month:'short',day:'numeric',timeZone:'UTC'});
  const initials = v => v.split(' ').map(s => s[0]).slice(0,2).join('');
  const sign = p => p.kind === 'refund' ? -p.cents : p.cents;
  const icon = (name, cls='') => {
    const paths = {
      chart:'<path d="M4 18V6m0 12h16M8 14l4-5 4 3 4-7"/>',
      arrow:'<path d="M5 12h14m-5-5 5 5-5 5"/>',
      plus:'<path d="M12 5v14M5 12h14"/>',
      download:'<path d="M12 3v12m-4-4 4 4 4-4M5 16v4h14v-4"/>',
      shield:'<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6z"/><path d="m8 12 3 3 5-6"/>',
      clock:'<circle cx="12" cy="12" r="8"/><path d="M12 7v5l3 2"/>',
      check:'<path d="m5 12 4 4L19 6"/>',
      alert:'<path d="m12 3 10 18H2zM12 9v5m0 3v.1"/>',
      cash:'<rect x="3" y="5" width="18" height="14" rx="3"/><circle cx="12" cy="12" r="3"/><path d="M6 12h.1m11.9 0h.1"/>',
      users:'<circle cx="9" cy="8" r="3"/><path d="M3 20v-3a6 6 0 0 1 12 0v3m2-14a3 3 0 0 1 0 6m2 8v-3a6 6 0 0 0-2-4"/>',
      grid:'<rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="3" width="7" height="7" rx="2"/><rect x="3" y="14" width="7" height="7" rx="2"/><rect x="14" y="14" width="7" height="7" rx="2"/>',
      plug:'<path d="M9 3v5m6-5v5M7 8h10v3a5 5 0 0 1-10 0zM12 16v5"/>',
      mail:'<rect x="3" y="5" width="18" height="14" rx="3"/><path d="m3 7 9 6 9-6"/>',
      search:'<circle cx="10" cy="10" r="6"/><path d="m15 15 5 5"/>',
    };
    return `<svg class="ui-icon ${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || paths.chart}</svg>`;
  };
  function scope(data, state) {
    const leads = data.leads.filter(l => (!state.owner || l.owner === state.owner) && (!state.source || l.source === state.source));
    const ids = new Set(leads.map(l => l.id));
    const clock = new Date(data.insights.generated_at);
    const end = clock.toISOString().slice(0,10);
    const allPayments = data.payments.filter(p => ids.has(p.lead_id) && new Date(p.at) <= clock);
    let start = new Date(end + 'T00:00:00Z');
    if (state.days === 'all') {
      const oldest = allPayments.map(p => p.at.slice(0,10)).sort()[0] || end;
      start = new Date(oldest + 'T00:00:00Z');
    } else start.setUTCDate(start.getUTCDate() - Number(state.days) + 1);
    const payments = allPayments.filter(p => new Date(p.at) >= start);
    const rules = data.insights.rules.map(r => ({...r,matches:r.matches.filter(m => ids.has(m.lead_id))}));
    return {leads,ids,payments,rules,start,end,clock,
      appointments:data.appointments.filter(a => ids.has(a.lead_id)),
      jobs:data.jobs.filter(j => ids.has(j.lead_id)),
      gross:payments.filter(p => p.kind === 'settlement').reduce((a,p) => a + p.cents,0),
      refunds:payments.filter(p => p.kind === 'refund').reduce((a,p) => a + p.cents,0)};
  }
  const eligible = l => !l.reason && l.status === 'ready' && l.idle >= 7;
  const periodLabel = state => state.days === 'all' ? 'All recorded time' : `Last ${state.days} days`;
  function controls(data, state, financial=true) {
    const select = (key,label,items) => `<label class="scope-select"><span>${label}</span><select data-scope="${key}" aria-label="${label}">${items.map(([v,t]) => `<option value="${esc(v)}"${state[key] === v ? ' selected' : ''}>${esc(t)}</option>`).join('')}</select></label>`;
    const owners = [...new Set(data.leads.map(l => l.owner))].sort();
    const sources = [...new Set(data.leads.map(l => l.source))].sort();
    return `<div class="scope-toolbar"><div class="scope-left">${select('owner','Owner',[['','All owners'],...owners.filter(Boolean).map(v=>[v,v])])}${select('source','Source',[['','All sources'],...sources.filter(Boolean).map(v=>[v,v])])}${(state.owner || state.source) ? '<button class="clear-scope" data-action="clear-scope">Clear filters ×</button>' : ''}</div>${financial ? select('days','Collections window',[['7','Last 7 days'],['30','Last 30 days'],['90','Last 90 days'],['all','All recorded time']]) : '<span class="snapshot-label">Current pipeline · all recorded time</span>'}</div>`;
  }
  function meter(value, total, color='mint') {
    const n = 30, count = total ? Math.max(0, Math.min(n, Math.round(value / total * n))) : 0;
    return `<div class="tick-meter ${color}" aria-hidden="true">${Array.from({length:n},(_,i)=>`<i${i<count?' class="filled"':''}></i>`).join('')}</div>`;
  }
  function metric(title,value,subtitle,iconName,detail,color,action='') {
    return `<section class="metric-card"><div class="metric-label">${icon(iconName)}<span>${title}</span>${action?`<button class="metric-link" ${action} aria-label="Inspect ${title}">↗</button>`:''}</div><div class="metric-value">${value}</div>${detail}<p class="metric-caption"><span class="metric-dot ${color}"></span>${subtitle}</p></section>`;
  }
  function chart(s) {
    const days = [];
    for (let d=new Date(s.start);d.toISOString().slice(0,10)<=s.end;d.setUTCDate(d.getUTCDate()+1)) days.push(d.toISOString().slice(0,10));
    const totals = new Map(days.map(d=>[d,0]));
    for (const p of s.payments) totals.set(p.at.slice(0,10),(totals.get(p.at.slice(0,10))||0)+sign(p));
    // Bound the graphic for long histories; the report still retains every transaction.
    const step = Math.max(1,Math.ceil(days.length/60));
    const buckets = [];
    for(let i=0;i<days.length;i+=step) {
      const group=days.slice(i,i+step);
      buckets.push({day:group[0],end:group.at(-1),value:group.reduce((a,d)=>a+totals.get(d),0)});
    }
    const high = Math.max(...buckets.map(b=>b.value),10000), low=Math.min(0,...buckets.map(b=>b.value));
    const x = i => 56 + (i+.5)/buckets.length*824, y = v => 174-(v-low)/(high-low)*150;
    const points = buckets.map((b,i)=>`${x(i)},${y(b.value)}`).join(' ');
    const path = `M${x(0)},${y(0)} L${buckets.map((b,i)=>`${x(i)},${y(b.value)}`).join(' L')} L${x(buckets.length-1)},${y(0)} Z`;
    const ticks = Array.from({length:4},(_,i)=>low+(high-low)*i/3);
    return `<div class="cash-chart"><svg viewBox="0 0 900 210" role="img" aria-label="${step===1?'Daily':'Grouped daily'} net collections in USD, settlements less refunds"><defs><linearGradient id="cash-wash" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#9ed6bd" stop-opacity=".38"/><stop offset="100%" stop-color="#9ed6bd" stop-opacity=".025"/></linearGradient></defs>${ticks.map(v=>`<line x1="56" x2="880" y1="${y(v)}" y2="${y(v)}" stroke="#e9edeb" stroke-dasharray="3 5"/><text x="43" y="${y(v)+4}" text-anchor="end" fill="#64716b" font-size="10">${money(v)}</text>`).join('')}<path d="${path}" fill="url(#cash-wash)"/><polyline points="${points}" fill="none" stroke="#409c7d" stroke-width="2.2" stroke-linejoin="round"/>${buckets.filter(b=>b.value).map(b=>{const i=buckets.indexOf(b);return `<circle cx="${x(i)}" cy="${y(b.value)}" r="3.5" fill="#fff" stroke="#409c7d" stroke-width="2"/>`}).join('')}${[0,Math.floor(buckets.length/3),Math.floor(buckets.length*2/3),buckets.length-1].filter((v,i,a)=>a.indexOf(v)===i).map(i=>`<text x="${x(i)}" y="201" text-anchor="middle" fill="#64716b" font-size="10">${shortDate(buckets[i].day)}</text>`).join('')}</svg><div class="chart-hit-area">${buckets.map(b=>`<button class="chart-hit" data-day="${b.day}" data-day-end="${b.end}" aria-label="Inspect ${shortDate(b.day)}${b.day!==b.end?' to '+shortDate(b.end):''}: ${precise(b.value)} net"><span class="chart-tooltip">${shortDate(b.day)}${b.day!==b.end?' – '+shortDate(b.end):''}<strong>${precise(b.value)}</strong></span></button>`).join('')}</div></div>`;
  }
  function person(l) {
    return `<div class="person"><span class="initials">${esc(initials(l.name))}</span><div><button data-lead="${l.id}">${esc(l.name)}</button><small>${esc(l.source)} · ${esc(l.owner || 'Unassigned')}</small></div></div>`;
  }
  function overview(data, session, state) {
    const s=scope(data,state), ready=s.leads.filter(eligible);
    const urgent=s.rules.filter(r=>r.id!=='recovery'), urgentIds=new Set(urgent.flatMap(r=>r.matches.map(m=>m.lead_id)));
    const queued=s.jobs.filter(j=>j.status==='queued').length, protectedCount=s.leads.filter(l=>l.reason).length;
    const issues=s.rules.flatMap(r=>r.matches.map(m=>({...m,rule:r}))).slice(0,5);
    const stages=[['ready','Ready for review','mint'],['waiting','Awaiting reply','blue'],['booked','Call booked','violet'],['attended','Attended','amber'],['collected','Collected','slate']];
    const sourceRows=[...new Set(s.payments.map(p=>s.leads.find(l=>l.id===p.lead_id)?.source))].map(source=>({source,net:s.payments.filter(p=>s.leads.find(l=>l.id===p.lead_id)?.source===source).reduce((n,p)=>n+sign(p),0)})).sort((a,b)=>b.net-a.net);
    const sourceMax=Math.max(1,...sourceRows.map(r=>Math.abs(r.net)));
    const cohortRows=['treatment','control'].map(c=>{const leads=s.leads.filter(l=>l.cohort===c);const ids=new Set(leads.map(l=>l.id));const net=data.payments.filter(p=>ids.has(p.lead_id)).reduce((n,p)=>n+sign(p),0);return {c,leads:leads.length,net}});
    return `<div class="dashboard-heading"><div><div class="page-eyebrow">REVENUE OPERATIONS</div><h1>Recovery overview</h1><p>See what needs attention. Keep every opportunity moving.</p></div><div class="toolbar"><button class="button secondary" data-action="dashboard-export">${icon('download')}Export report</button><button class="button" data-rule="all">Review opportunities ${icon('arrow')}</button></div></div>${session.demo?`<section class="workspace-tour"><div><span class="tour-icon">${icon('grid')}</span><div><strong>Your recovery desk, in three steps.</strong><p>Explore the sample workflow. Nothing here sends a real message.</p></div></div><div class="tour-steps"><button data-action="tour-leak"><span>01</span>Find a gap ${icon('arrow')}</button><button data-action="tour-lead"><span>02</span>Review a lead ${icon('arrow')}</button><button data-action="tour-cash"><span>03</span>Inspect cash ${icon('arrow')}</button></div></section>`:''}${controls(data,state)}
    <section class="metric-grid">
      ${metric('Net collections',money(s.gross-s.refunds),`${periodLabel(state)} · USD`, 'cash',`<div class="metric-breakdown"><span>Gross ${money(s.gross)}</span><span>Refunds ${money(s.refunds)}</span></div>`,'mint','data-action="collections-detail"')}
      ${metric('Ready for recovery',ready.length,`of ${s.leads.length} leads · current pipeline`,'users',meter(ready.length,s.leads.length,'mint'),'mint','data-queue-filter="ready"')}
      ${metric('Needs attention',urgentIds.size,'Unique leads with an operational flag','alert',meter(urgentIds.size,s.leads.length,'amber'),'amber','data-rule="attention"')}
      ${metric('Scheduled messages',queued,`${s.jobs.filter(j=>j.status==='unknown').length} unknown delivery outcomes`,'clock',meter(queued,Math.max(s.jobs.length,1),'violet'),'violet','data-route="jobs"')}
    </section>
    <div class="dashboard-grid"><section class="panel collections-panel"><div class="panelheader"><div><h2>Collections over time</h2><small>Recorded cash, after refunds. Select a date to inspect the ledger.</small></div><span class="subtle-pill">${periodLabel(state)}</span></div><div class="chart-summary"><strong>${precise(s.gross-s.refunds)}</strong><span><i class="legend-dot"></i>Net collections <span class="chart-timezone">· UTC</span></span></div>${chart(s)}<div class="chart-footer"><span>${s.payments.filter(p=>p.kind==='settlement').length} settlements <span class="separator">/</span> ${s.payments.filter(p=>p.kind==='refund').length} refunds</span><button class="text-link" data-route="outcomes">Open full cash ledger ${icon('arrow')}</button></div></section>
    <section class="panel pipeline-panel"><div class="panelheader"><div><h2>Pipeline at a glance</h2><small>Current stages · ${s.leads.length} leads</small></div>${icon('chart')}</div><div class="stage-list">${stages.map(([status,label,color])=>{const n=s.leads.filter(l=>l.status===status).length;return `<button class="stage-row" data-stage="${status}"><span><i class="stage-dot ${color}"></i>${label}</span><strong>${n}</strong><svg viewBox="0 0 240 6" preserveAspectRatio="none" aria-hidden="true"><rect width="240" height="6" rx="3" fill="#f0f2f1"/><rect width="${s.leads.length?n/s.leads.length*240:0}" height="6" rx="3" class="stage-fill ${color}"/></svg></button>`}).join('')}</div><div class="protection-strip">${icon('shield')}<span><strong>${protectedCount} protected</strong> from recovery outreach</span><button data-queue-filter="protected" aria-label="View protected leads">↗</button></div></section>
    <section class="panel attention-panel"><div class="panelheader"><div><h2>Needs a next step <span class="count-label">${new Set(s.rules.flatMap(r=>r.matches.map(m=>m.lead_id))).size}</span></h2><small>Rule-based signals. Every flag links back to its evidence.</small></div><button class="text-link" data-rule="all">View leak detector ${icon('arrow')}</button></div><div class="tablewrap"><table class="attention-table"><thead><tr><th>Lead</th><th>Why it needs a review</th><th>Priority</th><th></th></tr></thead><tbody>${issues.map(m=>{const l=s.leads.find(l=>l.id===m.lead_id);return `<tr><td>${person(l)}</td><td><strong class="issue-title">${esc(m.rule.title)}</strong><small class="issue-evidence">${esc(m.evidence)}</small></td><td><span class="priority ${m.rule.severity}">${m.rule.severity==='low'?'Review':m.rule.severity}</span></td><td><button class="review-button" data-lead="${l.id}" aria-label="Review ${esc(l.name)}">${icon('arrow')}</button></td></tr>`}).join('') || '<tr><td colspan="4" class="empty">No review signals match these filters.</td></tr>'}</tbody></table></div></section>
    <section class="panel sources-panel"><div class="panelheader"><div><h2>Collections by source</h2><small>${periodLabel(state)} · settlements less refunds</small></div>${icon('cash')}</div><div class="source-list">${sourceRows.map((r,i)=>`<div class="source-row"><div><span>${esc(r.source)}</span><strong>${precise(r.net)}</strong></div><svg viewBox="0 0 260 9" preserveAspectRatio="none" aria-hidden="true"><defs><pattern id="source-stripes-${i}" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(25)"><rect width="6" height="6" fill="${['#95cdb9','#b6b1e5','#9dbddd'][i%3]}"/><path d="M0 0v6" stroke="#ffffff" stroke-opacity=".55" stroke-width="2"/></pattern></defs><rect width="260" height="9" rx="4" fill="#f0f2f1"/><rect width="${Math.abs(r.net)/sourceMax*260}" height="9" rx="4" fill="url(#source-stripes-${i})"/></svg></div>`).join('')||'<p class="empty">No transactions in this collection window.</p>'}</div><div class="panel-note">Attributed collections, not proof of incremental revenue.</div></section>
    <section class="panel experiment-panel"><div class="panelheader"><div><h2>Pilot comparison</h2><small>Fixed pilot cohorts · all recorded time</small></div><span class="subtle-pill">Descriptive</span></div><div class="cohort-grid">${cohortRows.map(r=>`<div><span class="cohort-label"><i class="legend-dot ${r.c==='control'?'control-dot':''}"></i>${r.c==='control'?'Existing process / control':'Recovery treatment'}</span><strong>${precise(r.net)}</strong><p>${r.leads} leads <span>· ${r.leads?precise(r.net/r.leads):'—'} / lead</span></p></div>`).join('')}</div><div class="panel-note">Assignment alone doesn’t prove lift. Check cohort maturity, baseline differences and refunds.</div></section>
    <section class="panel guardrail-panel"><div class="guardrail-icon">${icon('shield')}</div><div><h2>Human review. Clear evidence.</h2><p>Permission, ownership and delivery outcomes stay visible before the next send.</p></div><button class="text-link" data-route="connections">Review connections ${icon('arrow')}</button></section></div><div class="dashboard-footer"><span>${session.demo?'<i class="demo-dot"></i>Demo workspace · fictional data · no real sends':'Manually reconciled USD ledger · collections before fees and commissions'}</span><span>Snapshot ${new Date(data.insights.generated_at).toLocaleTimeString(undefined,{hour:'2-digit',minute:'2-digit'})} · refresh to update</span></div>`;
  }
  function leaks(data, session, state) {
    const s=scope(data,state), rules=s.rules;
    const selected=state.rule || 'all';
    const visible=rules.filter(r=>selected==='all'||selected==='attention'&&r.id!=='recovery'||selected===r.id);
    const matches=visible.flatMap(r=>r.matches.map(m=>({...m,rule:r})));
    return `<div class="dashboard-heading"><div><div class="page-eyebrow">PIPELINE INTELLIGENCE</div><h1>Pipeline leak detector</h1><p>Spot the gaps. See the evidence. Give each opportunity a next step.</p></div><button class="button secondary" data-action="dashboard-export">${icon('download')}Export report</button></div>${controls(data,state,false)}<div class="leak-rule-grid">${rules.map(r=>`<button class="leak-rule-card ${selected===r.id?'selected':''}" data-rule="${r.id}" aria-pressed="${selected===r.id}"><span class="rule-kicker"><i class="priority-dot ${r.severity}"></i>${r.severity==='low'?'Opportunity':r.severity+' priority'}</span><strong>${r.matches.length}</strong><span>${esc(r.title)}</span></button>`).join('')}</div><section class="panel leak-results"><div class="panelheader"><div><h2>${selected==='all'?'All review signals':selected==='attention'?'Operational flags':esc(rules.find(r=>r.id===selected)?.title||'Review signals')} <span class="count-label">${matches.length}</span></h2><small>${new Set(matches.map(m=>m.lead_id)).size} unique leads · a lead can have more than one flag</small></div><button class="text-link" data-rule="all">Show all checks</button></div><div class="tablewrap"><table><thead><tr><th>Lead / owner</th><th>Signal and evidence</th><th>Suggested next step</th><th></th></tr></thead><tbody>${matches.map(m=>{const l=s.leads.find(l=>l.id===m.lead_id);return `<tr><td>${person(l)}</td><td class="leak-evidence-cell"><span class="priority ${m.rule.severity}">${esc(m.rule.title)}</span><p>${esc(m.evidence)}</p></td><td class="leak-action-cell">${esc(m.rule.action)}${l.reason?`<small class="protected-note">Outreach protected: ${esc(l.reason)}</small>`:''}</td><td><button class="rowaction" data-lead="${l.id}">Review →</button></td></tr>`}).join('')||'<tr><td colspan="4" class="empty">No signals match this check and these filters. Nothing has been changed.</td></tr>'}</tbody></table></div></section><div class="method-note">${icon('shield')}<p><strong>A flag is a task to review, not a financial claim.</strong> Attendance is flagged one hour after a booked call. Quiet follow-ups require seven idle days and no pending job. Recovery checks enforce the existing protection policy. No records or send permissions are changed by these checks.</p></div><div class="dashboard-footer"><span>${session.demo?'Fictional demo records · same rules as the live workspace':esc(data.insights.basis)}</span><span>Current snapshot · refresh to update</span></div>`;
  }
  function dayDetail(data,state,start,end) {
    const s=scope(data,state), rows=s.payments.filter(p=>p.at.slice(0,10)>=start&&p.at.slice(0,10)<=end);
    return `<p class="form-note">${shortDate(start)}${start!==end?' – '+shortDate(end):''} · UTC · ${esc(state.owner||'All owners')} · ${esc(state.source||'All sources')}. Net ${precise(rows.reduce((n,p)=>n+sign(p),0))}.</p><div class="tablewrap"><table><thead><tr><th>Lead</th><th>Reference</th><th>Type</th><th>Amount</th></tr></thead><tbody>${rows.map(p=>`<tr><td>${esc(s.leads.find(l=>l.id===p.lead_id)?.name)}</td><td>${esc(p.reference)}</td><td>${esc(p.kind)}</td><td>${precise(sign(p))}</td></tr>`).join('')||'<tr><td colspan="4" class="empty">No recorded transactions in this date range.</td></tr>'}</tbody></table></div>`;
  }
  function exportReport(data,state) {
    const s=scope(data,state);
    const rows=[['Relay operations report','Generated',data.insights.generated_at],['Owner',state.owner||'All owners'],['Source',state.source||'All sources'],['Collections window (UTC)',s.start.toISOString().slice(0,10),s.end],['Gross USD',(s.gross/100).toFixed(2)],['Refunds USD',(s.refunds/100).toFixed(2)],['Net USD',((s.gross-s.refunds)/100).toFixed(2)],[],['Review signals (current pipeline, all recorded time)'],['Lead','Owner','Source','Signal','Evidence','Suggested action']];
    for(const r of s.rules) for(const m of r.matches) {const l=s.leads.find(l=>l.id===m.lead_id);rows.push([l.name,l.owner,l.source,r.title,m.evidence,r.action])}
    rows.push([],['Transactions in collection window'],['Reference','Lead','Kind','Signed USD','Recorded at']);
    for(const p of s.payments)rows.push([p.reference,s.leads.find(l=>l.id===p.lead_id)?.name,p.kind,(sign(p)/100).toFixed(2),p.at]);
    const cell=v=>{let str=String(v??'');if(/^[=+@\-\t\r]/.test(str))str="'"+str;return '"'+str.replaceAll('"','""')+'"'};
    const blob=new Blob(['\uFEFF'+rows.map(r=>r.map(cell).join(',')).join('\r\n')],{type:'text/csv;charset=utf-8'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='relay-operations-'+s.end+'.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  return {icon,overview,leaks,scope,dayDetail,exportReport};
})();
