'use strict';
const paths = {
  grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  inbox: '<path d="M4 4h16l2 12v4H2v-4z"/><path d="M2 15h6l2 3h4l2-3h6"/>',
  sparkles: '<path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5zM20 2v4m-2-2h4"/>',
  network: '<circle cx="12" cy="5" r="3"/><circle cx="5" cy="18" r="3"/><circle cx="19" cy="18" r="3"/><path d="m10.5 8-4 7m7-7 4 7M8 18h8"/>',
  shield: '<path d="m12 2 8 4v6c0 5-8 10-8 10S4 17 4 12V6z"/><path d="m8 12 3 3 5-6"/>',
  settings: '<path d="m9 3-1 3-3 1-2 4 2 2v4l4 3 3-1 3 1 4-3v-4l2-2-2-4-3-1-1-3z"/><circle cx="12" cy="12" r="3"/>',
  refresh: '<path d="M20 7v5h-5M4 17v-5h5"/><path d="M6 7a7 7 0 0 1 12-1l2 3M4 15l2 3a7 7 0 0 0 12-1"/>',
  arrow: '<path d="M4 12h16m-6-6 6 6-6 6"/>',
  play: '<path d="m9 5 11 7-11 7z"/>',
  money: '<rect x="2" y="5" width="20" height="14" rx="2"/><circle cx="12" cy="12" r="3"/><path d="M6 12h.01M18 12h.01"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  file: '<path d="M14 2H5v20h14V7zM14 2v6h5M8 12h8M8 16h6"/>',
  message: '<path d="M21 15a3 3 0 0 1-3 3H8l-5 4V5a3 3 0 0 1 3-3h12a3 3 0 0 1 3 3zM7 7h10M7 12h6"/>',
  download: '<path d="M12 2v13m-5-5 5 5 5-5M4 16v5h16v-5"/>',
  link: '<path d="m10 13 4-4m-5-2 3-3a5 5 0 0 1 7 7l-3 3m-1 3-3 3a5 5 0 0 1-7-7l3-3"/>',
  search: '<circle cx="10" cy="10" r="6"/><path d="m15 15 6 6"/>'
};
const icon = name => `<svg viewBox="0 0 24 24" aria-hidden="true">${paths[name] || paths.file}</svg>`;
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money = pence => new Intl.NumberFormat('en-GB', {style:'currency',currency:'GBP',maximumFractionDigits:2,minimumFractionDigits:0}).format(pence / 100);
const pretty = value => esc(JSON.stringify(value, null, 2));
const pill = (text, color='') => `<span class="pill ${color}">${esc(text)}</span>`;
let state = {cases:[],workflows:[],verification:null,configuration:{},audit:{events:0,pending:0,hash_chain_valid:true}};
let token = '', busy = false, activeCase = null, events = [], activeJob = null, memoryResult = null, toastTimer;
let route = (location.hash || '#overview').slice(1), preview = null;
let activeWorkflow=null;
const routes = {overview:'Overview',collections:'Collections',agents:'Agent workspace',protocol:'Legacy protocol preview',memory:'Memory & insights',policy:'Financial policy',integrations:'Integrations'};
const stageLabels = {ready:'Ready to create invoice',invoiced:'Dispute to review',adjusted:'Adjustment verified',promised:'Promise agreed',part_paid:'Partially paid',settled:'Settled',requires_review:'Needs review',proposed:'Proposal validated',original_retired:'Finalising replacements',replaced:'Replacements open'};
const eventNames = {case_created:'Collection case opened',financial_intent:'Policy-authorised Stripe request',stripe_response:'Stripe response received',dispute_decision:'Dispute2Cash evaluated SLA evidence',promise_agreed:'PromisePay arrangement agreed',payment_policy_allowed:'Payment passed financial policy',instalment_received:'Instalment verified with Stripe',invoice_reconciled:'Invoice balance reconciled',execution_stopped:'Execution stopped for review'};

async function api(path, data) {
  const response = await fetch(path, data === undefined ? {cache:'no-store'} : {method:'POST',headers:{'Content-Type':'application/json','X-CollectIQ-Token':token},body:JSON.stringify(data)});
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || `Request failed (${response.status})`);
  return value;
}
function notify(text, error=false) {
  const toast = document.querySelector('#toast');
  toast.textContent = text; toast.className = 'toast' + (error ? ' error' : '');
  clearTimeout(toastTimer); toastTimer = setTimeout(() => toast.classList.add('hidden'), error ? 20000 : 6000);
}
function heading(eyebrow, title, subtitle, buttons='') {
  return `<div class="page-heading"><div><span class="eyebrow">${eyebrow}</span><h1>${title}</h1><p>${subtitle}</p></div><div class="actions">${buttons}</div></div>`;
}
const button = (label, action, name='', primary=false, disabled=false) => `<button class="button${primary ? ' primary' : ''}" data-action="${action}" ${disabled || busy ? 'disabled' : ''}>${name ? icon(name) : ''}${label}</button>`;
function current() { return state.cases.find(c => c.id === activeCase) || state.cases[0]; }
function caseInvoices(c){return [c.invoice,...(c.replacements||[])].filter(Boolean);}
function outstanding(c){return caseInvoices(c).filter(i=>i.status==='open').reduce((n,i)=>n+i.amount_remaining,0);}
function received(c){return caseInvoices(c).reduce((n,i)=>n+(i.amount_paid||0),0);}
function pendingNotice() {
  if (!state.verification?.ready) return `<div class="notice amber">${icon('link')} &nbsp; Integrations need verification. Configure your server-side credentials, then <a href="#integrations"><strong>verify Cognee and Stripe →</strong></a>. Financial execution stays blocked until both checks pass.</div>`;
  if (state.audit.pending) return `<div class="notice amber">${state.audit.pending} audit record(s) await Cognee acknowledgement. Sync memory before continuing.</div>`;
  return '';
}
function caseTable() {
  return `<section class="panel"><div class="panel-header"><div class="panel-title">Active collections <small>${state.cases.length}</small></div><a href="#collections" class="text-link">View all ${icon('arrow')}</a></div>
  <div class="table-scroll"><table><thead><tr><th>CUSTOMER</th><th>OUTSTANDING</th><th>STATUS</th><th>NEXT ACTION</th></tr></thead><tbody>${state.cases.map(c => `<tr>
    <td><div class="customer-name"><span class="customer-avatar">NS</span><div>${esc(c.customer_name)}<span class="cell-secondary">${esc(c.invoice?.number || 'No Stripe invoice yet')}</span></div></div></td>
    <td class="money">${c.invoice ? money(outstanding(c)) : '—'}</td>
    <td>${pill(stageLabels[c.stage], c.stage === 'settled' ? 'green' : c.stage === 'requires_review' ? 'amber' : 'purple')}</td>
    <td><button class="text-link" data-case="${esc(c.id)}">Open case ${icon('arrow')}</button></td></tr>`).join('')}</tbody></table></div>
    ${!state.cases.length ? `<div class="empty-state"><div class="empty-icon">${icon('inbox')}</div><strong>Your first collection starts here</strong><p>Create the £1,000 demo case to begin. Invoice balances appear only after Stripe returns them.</p><button class="button small soft" data-action="new-case">＋ Create demo case</button></div>` : ''}</section>`;
}
function auditPanel() {
  const list = events.slice(-7).reverse();
  return `<section class="panel audit-panel"><div class="panel-header"><div class="panel-title">Decision trail</div><span class="live-indicator"><span class="status-dot ${state.audit.pending ? 'amber' : ''}"></span>${state.audit.events ? state.audit.events + ' events' : 'Waiting'}</span></div>
    ${list.length ? `<div class="audit-feed">${list.map(e => `<div class="audit-item"><span class="audit-node"></span><h4>${esc(eventNames[e.kind] || e.kind)}</h4><p>${esc(e.body.action || e.body.decision?.explanation || e.body.explanation || (e.kind === 'promise_agreed' ? '£300 now · £500 in 14 days' : e.body.error || 'Event recorded in the decision journal'))}</p><div class="timestamp"><span>${new Date(e.created).toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit'})} · ${e.memory_status === 'stored' ? 'Cognee stored' : 'Memory pending'}</span><button data-event="${e.seq}">Inspect ↗</button></div></div>`).join('')}</div>` : `<div class="empty-state"><div class="empty-icon">${icon('network')}</div><strong>Every decision has a story.</strong><p>Evidence, policies, Stripe receipts and memory acknowledgements will appear here as your agents work.</p></div>`}
    <div class="audit-note">${icon('shield')}<span>Hash-linked journal · ${state.audit.hash_chain_valid ? 'Integrity verified' : 'Integrity check failed'}<br>Cloud storage and graph indexing are tracked separately.</span></div></section>`;
}
function overview() {
  const paid = state.cases.reduce((n,c) => n + received(c),0), outstandingTotal = state.cases.reduce((n,c) => n + outstanding(c),0);
  const credits = state.cases.reduce((n,c) => n + (c.validation?.adjustment || c.credit_note?.amount || 0),0), settled = state.cases.filter(c => c.stage === 'settled' || c.stage==='replaced').length;
  const verified = ['stripe','cognee'].filter(s => state.verification?.[s]?.status === 'verified').length;
  return `${heading('YOUR COLLECTIONS, CONNECTED', 'Good business. <em>Better cash flow.</em>', 'A clear view of what’s owed, what’s agreed, and what happens next.', button('Decision trail','audit','download') + button('Run core workflow','run','play',true))}
  <div class="metrics">${[
    ['Cash collected',money(paid),'money',paid ? pill('Stripe confirmed','green') + ' Actual test payments' : 'Awaiting verified Stripe payments'],
    ['Outstanding balance',money(outstandingTotal),'clock',state.cases.some(c=>c.invoice) ? 'Open Stripe invoices · void invoices excluded' : 'No Stripe invoices created yet'],
    ['Approved adjustments',money(credits),'shield',credits ? pill('Within policy','purple') + ' Evidence-backed reduction' : '£200 target · evidence required'],
    ['Workflows completed',String(settled).padStart(2,'0'),'check',`${verified}/2 integrations verified · ${state.cases.length} collection cases`]
  ].map(([label,value,name,foot])=>`<div class="metric"><div class="metric-label">${label}${icon(name)}</div><div class="metric-value">${value}</div><div class="metric-foot">${foot}</div></div>`).join('')}</div>
  <section class="hero"><div class="hero-copy"><span class="eyebrow">${icon('sparkles')} THE £1,000 SETTLEMENT JOURNEY</span><h2>From disputed invoice<br>to a promise you can collect.</h2><p>A £200 incomplete-deliverable adjustment.<br>£300 now, £500 next month. Real Stripe test invoices.</p><a class="button small" href="#collections">Inspect the verified workflow ${icon('arrow')}</a></div>
  <div class="hero-journey" aria-label="Planned demo: 1000 pounds invoiced, 200 pounds adjusted, 800 pounds collected in two instalments"><div class="mini-invoice">${icon('file')}<small>ORIGINAL INVOICE</small><strong>£1,000<span class="cell-secondary">Planned demo</span></strong><div class="mini-line"></div><div class="mini-line short"></div></div><div class="journey-connector"><span></span><span></span>${icon('sparkles')}<span></span><span></span></div><div class="mini-settlement"><small>AFTER SLA ADJUSTMENT</small><strong>£800</strong>${pill('− £200 evidence-backed credit','purple')}${pill('£300 + £500 instalments','green')}</div></div></section>
  <div class="grid-main"><div><section class="panel"><div class="panel-header"><div class="panel-title">Your collection team ${pill('3 SPECIALISTS','purple')}</div><a class="text-link" href="#agents">Meet your agents ${icon('arrow')}</a></div>
    <div class="workflow">${[
      ['shield','green','01','Dispute2Cash','Find the evidence. Resolve the dispute.','Evidence-led adjustment'],
      ['message','blue','02','PromisePay','Turn cash-flow constraints into a clear plan.','Policy-bound negotiation'],
      ['sparkles','','03','Collections orchestrator','Execute the plan. Verify every payment.','Stripe test-mode execution']
    ].map(([i,c,n,t,d,s])=>`<div class="workflow-card"><div class="step-heading"><div class="agent-icon ${c}">${icon(i)}</div><span class="step-number">${n}</span></div><h3>${t}</h3><p>${d}</p>${pill(s)}</div>`).join('')}</div>
    <div class="workflow-footer"><span>${icon('network')} Shared context in Cognee Cloud</span><span>${icon('shield')} Deterministic financial authority</span></div></section>${caseTable()}</div>
    <div class="right-column">${auditPanel()}<div class="insight"><div class="insight-heading">${icon('sparkles')} DESIGNED FOR TRUST</div><h3>Resolve the reason.<br>Recover the relationship.</h3><p>Give your agents memory and your finances firm boundaries. No unsupported discounts. No assumed payments.</p><a class="text-link" href="#policy">Explore financial policy ${icon('arrow')}</a></div></div></div>`;
}
function collections() {
  const c = current();
  return `${heading('EVERY INVOICE, A PATH FORWARD','Collections, <em>with context.</em>','Follow a case from evidence to verified settlement.',button('New demo case','new-case','file',true))}${pendingNotice()}${caseTable()}
  ${c?.workflow==='replacement'? coreCase(c) : c ? `<section class="panel"><div class="panel-header"><div class="panel-title">${esc(c.customer_name)} ${pill(stageLabels[c.stage], c.stage==='settled'?'green':'purple')}</div><span class="code-tag">${esc(c.id)}</span></div><div class="case-detail"><p class="subtext">${esc(c.scenario)}. Agent-to-agent negotiation is simulated; billing calls use real Stripe test APIs.</p><div class="case-detail-grid">
    ${[['Original invoice',c.invoice ? money(c.invoice.total) : 'Not created'],['Adjustment issued',c.credit_note ? money(c.credit_note.amount) : 'Not issued'],['Payment received',c.invoice ? money(c.invoice.amount_paid) : 'Not charged']].map(([a,b])=>`<div class="case-stat"><small>${a}</small><strong>${b}</strong></div>`).join('')}</div>
    <div class="case-actions">${button('1. Create £1,000 invoice','invoice','file',false,!!c.invoice)}${button('2. Resolve £200 dispute','resolve','shield',false,!c.invoice || !!c.credit_note)}${button('3. Agree £300 / £500','negotiate','message',false,!c.credit_note || !!c.negotiation)}${button('4. Collect £300','pay-first','money',false,!c.negotiation || c.payments.length>0)}${button('5. Collect £500 early · test','pay-second','money',false,c.payments.length!==1)}${button('Reconcile invoice','reconcile','refresh',false,!c.invoice)}</div>
    ${c.invoice ? `<div class="section-subtitle">Actual Stripe test object</div><a class="button small" target="_blank" rel="noopener noreferrer" href="https://dashboard.stripe.com/test/invoices/${encodeURIComponent(c.invoice.id)}">${icon('link')}${esc(c.invoice.id)} ↗</a>` : ''}
    ${c.stage==='settled' ? `<div class="notice">${icon('check')} &nbsp; Stripe confirmed £800 paid, £200 credited and £0 remaining. Both instalments have succeeded PaymentIntent receipts.</div>`:''}
    ${c.negotiation ? `<h3 class="section-subtitle">PromisePay arrangement</h3><div class="case-detail-grid">${c.negotiation.plan.map((p,i)=>`<div class="case-stat"><small>Instalment ${i+1} · ${esc(p.due)}</small><strong>${money(p.amount)}</strong>${pill(c.payments[i] ? 'Stripe received' : 'Agreed · not collected', c.payments[i]?'green':'purple')}</div>`).join('')}</div>`:''}
    <button class="text-link" data-action="evidence">Inspect synthetic SLA evidence →</button></div></section><div class="grid-main"><section class="panel"><div class="panel-header"><div class="panel-title">Financial reconciliation</div><button class="text-link" data-action="audit">Export audit JSON ${icon('download')}</button></div><div class="panel-body"><pre>${pretty({invoice:c.invoice,credit_note:c.credit_note,payments:c.payments})}</pre></div></section>${auditPanel()}</div>`:''}`;
}
function coreCase(c){
  return `<section class="panel"><div class="panel-header"><div class="panel-title">Acme Solutions ${pill(stageLabels[c.stage],'purple')}</div><span class="code-tag">${esc(c.id)}</span></div><div class="case-detail"><p class="subtext">${esc(c.customer_message || 'Synthetic hackathon contract and incomplete-deliverable evidence.')}<br>Amounts below are from Stripe. Open replacement invoices are not payment receipts.</p><div class="case-detail-grid">${[['Outstanding',money(outstanding(c))],['Approved reduction',c.validation?money(c.validation.adjustment):'Not approved'],['Cash collected',money(received(c))]].map(([a,b])=>`<div class="case-stat"><small>${a}</small><strong>${b}</strong></div>`).join('')}</div><div class="case-actions">${button('1. Store facts & create original','core-prepare','file',false,!!c.invoice)}${button('2. Retrieve & validate proposal','core-propose','shield',false,!c.invoice||!!c.proposal)}${button('3. Create safe replacements','core-replace','refresh',false,!c.proposal||c.stage==='replaced')}${button('Verify existing workflow','core-run','check',false,c.stage!=='replaced')}</div></div>
    <div class="table-scroll"><table><thead><tr><th>ACTUAL STRIPE INVOICE</th><th>TOTAL</th><th>STATUS</th><th>DUE</th></tr></thead><tbody>${caseInvoices(c).map((i,index)=>`<tr><td><a class="text-link" target="_blank" rel="noopener noreferrer" href="https://dashboard.stripe.com/test/invoices/${encodeURIComponent(i.id)}">${esc(i.id)} ↗</a><span class="cell-secondary">${index===0?'Original · retired only after safeguards':'Replacement instalment '+index}</span></td><td class="money">${money(i.total)}</td><td>${pill(i.status,i.status==='void'?'amber':'purple')}</td><td>${index===0?'—':esc(c.proposal?.instalments[index-1]?.due)}</td></tr>`).join('')}</tbody></table></div><div class="panel-body"><div class="notice">${c.stage==='replaced'?'Verified: original void, £300 and £500 replacement invoices open. £800 remains outstanding; no payment has been collected.':'The original remains protected until two drafts and all replacement safeguards pass.'}</div><button class="button small" data-action="proposal">Inspect structured proposal & evidence ${icon('arrow')}</button><button class="button small" data-action="audit">Export complete history ${icon('download')}</button></div></section>
    <section class="panel"><div class="panel-header"><div class="panel-title">Complete transaction & decision history <small>${events.length}</small></div>${pill(state.audit.hash_chain_valid?'Hash chain verified':'Integrity failed',state.audit.hash_chain_valid?'green':'red')}</div><div class="panel-body history-list">${events.slice().reverse().map(e=>`<details class="history-event"><summary><span>${esc(new Date(e.created).toLocaleTimeString('en-GB'))}</span> ${esc(eventNames[e.kind]||e.kind.replaceAll('_',' '))} ${pill(e.memory_status==='stored'?'Cognee stored':'Pending',e.memory_status==='stored'?'green':'amber')}</summary><pre>${pretty(e)}</pre></details>`).join('')}</div></section>`;
}
function legacyAgents() {
  const c = current(), rounds = c?.negotiation?.rounds || preview?.negotiation?.rounds;
  return `${heading('A TEAM THAT REMEMBERS','Specialists. <em>Shared intelligence.</em>','Cognee provides persistent context and reasoning. Financial authority stays in deterministic code.',button('Preview negotiation','preview','message',true))}
    <div class="agent-grid">${[
      ['shield','Dispute2Cash','Evaluates the synthetic SLA against the service log, retrieves matching evidence from Cognee, and permits a £200 credit only when the evidence hash matches.','Evidence-backed resolution'],
      ['message','PromisePay','Retrieves a cloud-generated collection strategy, then uses a bounded negotiation protocol to agree £300 now and £500 in 14 days.','Simulated agent-to-agent protocol'],
      ['sparkles','Collections orchestrator','Coordinates the case, persists decision intent in Cognee, executes Stripe test-mode requests and reconciles the invoice from actual API responses.','Real API execution']
    ].map(([i,n,d,s])=>`<section class="agent-card"><div class="agent-icon">${icon(i)}</div><h3>${n}</h3><p>${d}</p>${pill(s,'purple')}</section>`).join('')}</div>
    <section class="panel"><div class="panel-header"><div class="panel-title">Negotiation room ${pill('SIMULATION','amber')}</div><span class="text-link">Bounded protocol · 5 messages</span></div>
    ${rounds ? `<div class="conversation">${rounds.map(r=>`<div class="message ${r.agent.includes('Buyer')?'buyer':''} ${r.type==='reject'?'reject':''}"><strong>${esc(r.agent)}</strong><small> &nbsp; ${esc(r.type)}</small><p>${esc(r.text)}</p></div>`).join('')}</div>` : `<div class="empty-state"><div class="empty-icon">${icon('message')}</div><strong>A thoughtful conversation. Firm boundaries.</strong><p>Preview the negotiation protocol, including a policy rejection of the buyer’s 45-day proposal. This preview performs no financial action.</p><button class="button small" data-action="preview">Preview conversation ${icon('arrow')}</button></div>`}</section>
    ${c?.reasoning ? `<section class="panel"><div class="panel-header"><div class="panel-title">Actual Cognee collection strategy</div>${pill(c.reasoning.mode,'purple')}</div><div class="panel-body"><pre>${pretty(c.reasoning)}</pre></div></section>`:''}`;
}
function selectedWorkflow(){return state.workflows?.find(w=>w.id===activeWorkflow)||state.workflows?.[0];}
function agents(){
  const workflows=state.workflows||[],w=selectedWorkflow();
  const steps=['RECEIVED','INVESTIGATING','NEGOTIATING','VALIDATING','EXECUTING','COMPLETED'];
  const visited=new Set((w?.state_history||[]).map(s=>s.state));
  return `${heading('AUTONOMOUS COLLECTION INTELLIGENCE','One team. <em>Grounded decisions.</em>','Real Cognee reasoning. Separate buyer and seller roles. Deterministic financial authority.',button('Run all · DRY_RUN','agent-all','play',true))}
    <div class="notice">New scenarios default to <strong>DRY_RUN</strong>. Scenario balances are synthetic inputs, not Stripe invoices. The buyer is simulated and has no authority over real customers. Existing Acme billing is protected.</div>
    <div class="agent-grid">${[
      ['A','Successful negotiation','£800 balance · £200 / £600 initial offer','PromisePay recalls a 30% upfront policy and negotiates within the buyer’s £250 maximum budget.'],
      ['B','Memory-informed rejection','£800 balance · prior broken promise','The same proposal faces stricter terms because customer-specific memory contains a broken commitment.'],
      ['C','Evidence-led dispute','£750 invoice input · £150 dispute','Dispute2Cash retrieves the contract and delivery record before negotiating the validated remaining balance.']
    ].map(([name,title,amount,text])=>{const result=workflows.find(x=>x.scenario===name);return `<section class="agent-card"><div class="step-heading"><div class="agent-icon">${icon(name==='C'?'shield':'message')}</div>${pill(result?.state||'NOT RUN',result?.state==='COMPLETED'?'green':'purple')}</div><h3>${name}. ${title}</h3><strong class="scenario-amount">${amount}</strong><p>${text}</p><div class="case-actions"><button class="button small" data-action="agent-${name}" ${busy?'disabled':''}>${result?.state==='COMPLETED'?'Replay saved workflow':'Run scenario'} ${icon('play')}</button>${result?`<button class="text-link" data-workflow="${esc(result.id)}">Inspect result →</button>`:''}</div></section>`;}).join('')}</div>
    ${w?`<section class="panel"><div class="panel-header"><div class="panel-title">${esc(w.customer_name)} ${pill('SCENARIO '+w.scenario,'purple')}${pill(w.outcome||w.state,w.outcome==='AGREED'?'green':'amber')}</div><span class="text-link">${w.rounds||0}/3 rounds · ${(w.model_calls||[]).length} actual model calls</span></div><div class="panel-body"><div class="workflow-states">${steps.map(s=>pill(s,visited.has(s)?'purple':'')).join('<span class="state-arrow">→</span>')}</div>${w.error?`<div class="notice error">${esc(w.error)}</div>`:''}<div class="notice">Execution: <strong>${esc(w.stripe_execution?.mode||'DRY_RUN')}</strong> · ${esc(w.stripe_execution?.status||'NOT_REQUESTED')} · ${w.stripe_execution?.status==='COMPLETED'?'Actual test invoices created; no payment claimed.':'No Stripe financial action requested.'}</div>
    ${w.routing?`<div class="strategy-row"><div><span class="eyebrow">SELECTED STRATEGY</span><h3>${esc(w.routing.classification.replaceAll('_',' '))} → ${esc(w.routing.specialist)}</h3><p class="subtext">${esc(w.routing.reasoning)}</p></div><div>${pill('Risk: '+w.routing.risk,w.routing.risk==='HIGH'?'amber':'purple')}${pill('Confidence '+Math.round(w.routing.confidence*100)+'%')}</div></div>`:'<p class="subtext">The orchestrator is retrieving evidence before selecting a strategy.</p>'}</div></section>
    <div class="grid-main"><div><section class="panel"><div class="panel-header"><div class="panel-title">Agent2Agent negotiation ${pill('REAL MODEL OUTPUT','purple')}</div>${pill('BUYER SIMULATED','amber')}</div><div class="conversation">${w.conversation?.length?w.conversation.map(m=>`<div class="message ${m.role==='Buyer'?'buyer':''} ${m.offer.action==='REJECT'?'reject':''}"><strong>${m.role==='Buyer'?'Simulated buyer':'Seller agent'}</strong><small> · Round ${m.round} · ${esc(m.offer.action)}</small><p>${esc(m.offer.reasoning)}</p>${m.offer.instalments.map(p=>`<span class="offer-term">${money(p.amount_pence)} · ${esc(p.due)}</span>`).join('')}<div class="evidence-tags">${m.offer.evidence_refs.map(r=>pill(r)).join(' ')}</div></div>`).join(''):'<div class="empty-state"><strong>No conversation has been generated yet.</strong><p>Only actual backend messages appear here.</p></div>'}</div></section>
    <section class="panel"><div class="panel-header"><div class="panel-title">Final proposal & deterministic validation</div><button class="text-link" data-agent-detail="policy">Inspect policy →</button></div><div class="panel-body">${w.accepted_offer?`<div class="case-detail-grid"><div class="case-stat"><small>Validated balance</small><strong>${money(w.limits.balance_pence)}</strong></div><div class="case-stat"><small>Evidence-backed adjustment</small><strong>${money(w.adjustment_pence)}</strong></div><div class="case-stat"><small>Required upfront</small><strong>${money(w.limits.minimum_upfront_pence)}</strong></div></div><pre>${pretty(w.accepted_offer)}</pre>`:w.promise_decision?`<div class="notice amber">${esc(w.promise_decision.explanation)}</div>`:'<p class="subtext">Awaiting a model proposal and policy validation.</p>'}<pre>${pretty(w.policy_validation||{status:'NOT_VALIDATED'})}</pre></div></section></div>
    <div><section class="panel"><div class="panel-header"><div class="panel-title">Retrieved Cognee evidence</div></div><div class="panel-body">${Object.entries(w.retrieved||{}).map(([kind,result])=>`<div class="evidence-row"><strong>${esc(w.facts[kind]?.reference||kind)}</strong><span>${esc(kind)} · HTTP ${esc(result.receipt?.http_status)}</span></div>`).join('')||'<p class="subtext">Waiting for real customer-scoped retrieval.</p>'}<p class="subtext">Separate dataset and role-specific sessions for this customer.</p><button class="button small" data-agent-detail="evidence">Inspect actual retrieval ${icon('network')}</button></div></section>
    <section class="panel"><div class="panel-header"><div class="panel-title">Why this decision?</div></div><div class="panel-body"><p class="subtext">Retrieve the saved decision from Cognee and generate an explanation with evidence references.</p><br><button class="button small primary" data-action="agent-why" ${!w.decision_record||busy?'disabled':''}>${icon('sparkles')}Explain saved decision</button><br><br><button class="text-link" data-agent-detail="history">Inspect full workflow history →</button></div></section><div class="insight"><div class="insight-heading">${icon('shield')} FINANCIAL AUTHORITY</div><h3>Models propose.<br>Policy authorises.</h3><p>Every proposed adjustment, instalment and acceptance is validated. Invalid output is recorded and rejected. Maximum three negotiation rounds.</p></div></div></div>`:`<section class="panel"><div class="empty-state"><div class="empty-icon">${icon('sparkles')}</div><strong>Start a real intelligence workflow.</strong><p>Run a scenario to retrieve Cognee memory and generate actual buyer/seller offers. No conversation is prewritten.</p></div></section>`}`;
}
function memory() {
  return `${heading('CONTEXT THAT COMPOUNDS','A memory for <em>every decision.</em>','Search persistent case context in Cognee Cloud. Results below are returned by the real API.',button('Sync & index memory','sync','refresh',true))}${pendingNotice()}
    <section class="panel"><div class="panel-header"><div class="panel-title">Ask your receivables memory ${pill('COGNEE CLOUD','purple')}</div><span class="text-link">Customer: ${esc(current()?.customer_name||'Select a case')}</span></div>
    <form class="memory-form" id="memory-form"><input id="memory-query" name="query" placeholder="What evidence supports Acme’s £200 adjustment?" aria-label="Memory query" required maxlength="4000"><select name="mode" aria-label="Retrieval mode"><option value="GRAPH_COMPLETION">Graph reasoning</option><option value="RAG_COMPLETION">RAG completion</option><option value="CHUNKS">Source chunks</option></select><button class="button primary" ${busy?'disabled':''}>${icon('search')}Search memory</button></form>
    <div class="suggestions">${['What evidence supports the £200 adjustment?','What payment arrangement was agreed?','Summarise the verified Stripe settlement.'].map(q=>`<button data-query="${esc(q)}">${esc(q)}</button>`).join('')}</div>
    <div class="result-box">${memoryResult ? `<span class="eyebrow">ACTUAL COGNEE RESPONSE</span><pre>${pretty(memoryResult)}</pre>` : `<div class="empty-state"><div class="empty-icon">${icon('network')}</div><strong>Knowledge, connected.</strong><p>Cloud retrieval results appear here after a successful search. There is no local or generated fallback.</p></div>`}</div></section>
    <div class="card-grid"><section class="integration-card"><h3>Decision journal</h3><p>${state.audit.events} hash-linked events · ${state.audit.pending} waiting for cloud storage.</p>${pill(state.audit.hash_chain_valid?'Hash chain verified':'Integrity failed',state.audit.hash_chain_valid?'green':'red')}<div class="integration-footer">SQLite tracks execution and delivery. Cognee is the primary persistent AI memory and retrieval system.</div></section><section class="integration-card"><h3>Storage ≠ retrieval readiness</h3><p>A successful add acknowledges storage. Cognify builds the knowledge graph. Authenticated marker-retrieval probes verify that the selected search modes can actually retrieve it.</p><div class="integration-footer">Failed storage blocks the next financial action. Failed indexing remains visible and can be retried.</div></section></div>`;
}
function legacyPolicy() {
  const rules = [
    ['Test mode, enforced at both ends','Reject live-mode keys before any request; require livemode=false on returned Stripe objects.'],
    ['Evidence before adjustment','Synthetic fixture SLA-4.2 and LOG-002 must match the exact approved values and case. Retrieve the evidence hash from Cognee before issuing the credit.'],
    ['A hard 20% credit ceiling','Two missed units × £100 = £200. No additional discretionary discount; original invoice is fixed at £1,000 GBP.'],
    ['Exact pence. Exact plan.','All amounts use integer pence. Exactly £300 + £500 must equal the £800 adjusted balance. Floating-point values and extra instalments are rejected.'],
    ['A 30-day settlement window','Dates must be ordered and complete within 30 days of agreement. The protocol rejects 45 days and agrees 14 days.'],
    ['No duplicate execution','Stable Stripe idempotency keys, persisted operation receipts and a single execution lane protect retries. Uncertain operations older than 23 hours require reconciliation.'],
    ['A decision record before money moves','Cognee must acknowledge every queued audit record and the new financial intent before a Stripe mutation proceeds.'],
    ['Settlement means Stripe confirmed it','Require two succeeded PaymentIntents, £800 amount_paid, £200 credit and £0 amount_remaining. An agent’s statement is never proof of payment.']
  ];
  return `${heading('AUTONOMY WITH ACCOUNTABILITY','Intelligent agents. <em>Firm boundaries.</em>','The model recommends. Deterministic policy decides. Stripe proves the outcome.',pill('POLICY v1 · GBP','purple'))}<div class="notice">The hackathon demo may collect the second instalment early using the Stripe <strong>pm_card_visa</strong> test payment method. The PromisePay agreement remains £300 now and £500 in 14 days.</div><section class="panel"><div class="panel-header"><div class="panel-title">Financial execution rules</div>${pill('Always enforced','green')}</div><div class="policy-list">${rules.map(([title,text])=>`<div class="policy-row"><span class="check">✓</span><div><h3>${title}</h3><p>${text}</p></div></div>`).join('')}</div></section>`;
}
function policy(){
  if(current()?.workflow!=='replacement')return legacyPolicy();
  const c=current();
  const rules=[['Customer-scoped evidence','Separate Cognee dataset and session per customer; reject foreign dataset results.'],['Evidence-backed £200 reduction','The incomplete report has a contracted value of £200. The adjustment cannot exceed 20% of the £1,000 original.'],['£300 now, £500 next month','Integer pence only. Next calendar month on the same day, clamped for shorter months. The Acme policy permits up to 45 days.'],['Prepare drafts before retiring the original','Both replacement amounts, ownership metadata and settlement hash must match the approved proposal.'],['Protect existing invoices','Only this workflow’s own unpaid/open test invoice can be retired. Require a creation receipt, zero payments and credits, no external attached payments, and auto_advance=false.'],['No duplicates on retry','Persist Stripe operation keys and receipts. Repeated core execution reconciles the same three invoice IDs.'],['Stripe response is the authority','Open invoices are outstanding, not collected cash. Voided invoice amounts are excluded from receivables.']];
  return `${heading('ACME FINANCIAL POLICY','Intelligent agents. <em>Firm boundaries.</em>','The verified replacement workflow follows the policy stored in Acme’s Cognee dataset.',pill('ACME REPLACEMENT v1','purple'))}<div class="notice">The Acme proposal is £300 due ${esc(c.proposal?.instalments[0]?.due||'today')} and £500 due ${esc(c.proposal?.instalments[1]?.due||'next month')}. Both replacement invoices remain unpaid.</div><section class="panel"><div class="panel-header"><div class="panel-title">Verified execution rules</div>${pill('Deterministically enforced','green')}</div><div class="policy-list">${rules.map(([title,text])=>`<div class="policy-row"><span class="check">✓</span><div><h3>${title}</h3><p>${text}</p></div></div>`).join('')}</div></section>`;
}
function integrations() {
  const v = state.verification;
  return `${heading('THE CONNECTIONS BEHIND THE INTELLIGENCE','Connected, <em>with proof.</em>','Verify authenticated API access and retrieval capabilities before starting financial execution.',button('Verify integrations','verify','link',true))}
    <div class="notice amber">Credentials are read only by the backend from environment variables or a local <code>.env</code> file. Configure them on the server and restart. Never paste API keys into the dashboard.</div>
    <div class="card-grid">${['stripe','cognee'].map(name=>{
      const result=v?.[name], ok=result?.status==='verified', configured=state.configuration[name];
      return `<section class="integration-card"><div class="integration-top"><span class="service-logo ${name}">${name}</span>${pill(ok?'Verified':result?.status==='failed'?'Connection failed':configured?'Configured · unverified':'Credentials needed',ok?'green':'amber')}</div><h3>${name==='stripe'?'Financial execution · test mode':'Persistent AI memory & reasoning'}</h3><p>${name==='stripe'?'Checks real /balance and /invoices API responses. Creates one invoice, a credit note and two partial PaymentIntents during the settlement demo.':'Discovers the deployed API schema, adds a unique probe, builds its graph and tests retrieval and reasoning against that probe.'}</p><code>${name==='stripe'?'STRIPE_SECRET_KEY=sk_test_…':'COGNEE_API_KEY=…'}</code>
      ${result?.error?`<div class="notice error">${esc(result.error)}</div>`:''}
      ${result?.capabilities?`<div class="capabilities">${result.capabilities.map(p=>`<div class="capability"><span>${esc(p.mode)}</span>${pill(p.status==='verified'?'Probe retrieved':p.status==='failed'?'Failed':'Not evidenced',p.status==='verified'?'green':'amber')}</div>`).join('')}</div>`:''}
      <div class="integration-footer">${name==='stripe'?'Live keys are rejected. Returned objects must explicitly state livemode=false.':'Advertised modes and successfully executed capabilities are recorded separately.'}<br>${v?'Last checked: '+esc(new Date(v.checked_at).toLocaleString('en-GB')):'Not yet verified in this workspace.'}</div></section>`;
    }).join('')}</div>
    <section class="panel"><div class="panel-header"><div class="panel-title">Verification evidence</div>${pill(v?.ready?'Ready for execution':'Execution blocked',v?.ready?'green':'amber')}</div><div class="panel-body"><p class="subtext">HTTP statuses, request IDs, capability results and explicit failures are preserved in the report.</p><pre>${pretty(v || {status:'not_run',message:'Configure credentials, then select Verify integrations.'})}</pre></div></section>`;
}
function render() {
  if (!routes[route]) route='overview';
  document.querySelector('#page-title').textContent=routes[route];
  document.querySelectorAll('[data-nav]').forEach(a=>{const active=a.dataset.nav===route;a.classList.toggle('active',active);if(active)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});
  document.querySelector('#case-count').textContent=state.cases.length;
  document.querySelector('#integration-dot').className='status-dot'+(state.verification?.ready?'':' amber');
  document.querySelector('#main').innerHTML=({overview,collections,agents,protocol:legacyAgents,memory,policy,integrations}[route])();
}
async function refresh(renderNow=true) {
  state=await api('/api/state');
  const c=current();
  if(c){activeCase=c.id;events=(await api('/api/audit/'+encodeURIComponent(c.id))).events;}else events=[];
  if(renderNow)render();
}
async function job(path,data,label) {
  if(busy)return;
  busy=true;document.querySelector('#busy-bar').classList.remove('hidden');document.querySelector('#busy-text').textContent=label;render();
  try{
    let work=await api(path,data);activeJob=work.id;
    while(['queued','running'].includes(work.status)){
      await new Promise(r=>setTimeout(r,1000));
      work=await api('/api/jobs/'+activeJob);await refresh();
      const last=events[events.length-1];
      if(last)document.querySelector('#busy-text').textContent=label+' · '+(eventNames[last.kind]||last.kind);
    }
    if(work.status==='failed')throw new Error(work.error);
    if(path==='/api/agents/why'){showDetails('Why did the agent decide this?',work.result);}
    else if(path==='/api/agents/run'&&work.result.state&&work.result.state!=='COMPLETED')notify('Agent workflow stopped: '+(work.result.error||work.result.state),true);
    else if(path==='/api/verify'&&!work.result.ready)notify('Verification incomplete. Inspect the integration report for the actual failure.',true);
    else if(path==='/api/memory/search'){memoryResult=work.result;notify('Cognee response received.');}
    else notify(path.endsWith('/run')?'Settlement workflow completed. Inspect the Stripe receipts.':label+' complete.');
    await refresh();
    return work.result;
  }catch(error){notify(error.message,true);await refresh().catch(()=>{});}
  finally{busy=false;activeJob=null;document.querySelector('#busy-bar').classList.add('hidden');render();}
}
function showDetails(title,value){document.querySelector('#dialog-title').textContent=title;document.querySelector('#dialog-content').innerHTML=`<pre>${pretty(value)}</pre>`;document.querySelector('#details-dialog').showModal();}
function exportAudit(){
  const c=current();if(!c){notify('Create a case to start its audit trail.');return;}
  const blob=new Blob([JSON.stringify({case:c,events,hash_chain_valid:state.audit.hash_chain_valid},null,2)],{type:'application/json'});
  const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=`collectiq-${c.id}-audit.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
async function act(action){
  if(busy)return;
  if(action.startsWith('agent-')){
    if(action==='agent-why'){const w=selectedWorkflow();if(w)return job('/api/agents/why',{workflow_id:w.id},'Recalling and explaining saved decision');return;}
    const name=action.slice(6);if(['A','B','C','all'].includes(name)){location.hash='agents';return job('/api/agents/run',{scenario:name},'Running real Cognee agents · DRY_RUN');}
  }
  if(action==='audit'){exportAudit();return;}
  if(action==='evidence'){showDetails('Synthetic SLA evidence',current()?.evidence);return;}
  if(action==='proposal'){showDetails('Acme proposal, evidence & actual reasoning',{proposal:current()?.proposal,validation:current()?.validation,facts:current()?.facts,reasoning:current()?.reasoning});return;}
  if(action==='preview'){
    try{preview=await api('/api/scenario');route='protocol';location.hash='protocol';render();notify('Legacy preview only: deterministic simulation with no financial execution.');}catch(e){notify(e.message,true);}return;
  }
  if(action==='verify'){location.hash='integrations';return job('/api/verify',{},'Verifying authenticated APIs');}
  if(action==='sync')return job('/api/memory/sync',{},'Storing and indexing Cognee memory');
  if(action==='new-case'){
    try{const c=await api('/api/cases',{request_id:crypto.randomUUID()});activeCase=c.id;await refresh();location.hash='collections';notify('Demo case created. No Stripe invoice has been created yet.');}catch(e){notify(e.message,true);}return;
  }
  if(!state.verification?.ready){location.hash='integrations';notify('Configure credentials and verify both APIs before financial execution.',true);return;}
  let c=current();
  if(!c){c=await api('/api/cases',{request_id:'acme-hackathon-settlement-001'});activeCase=c.id;}
  if(action==='run'&&c.workflow==='replacement')action='core-run';
  const labels={run:'Running the complete settlement',invoice:'Creating the Stripe invoice',resolve:'Resolving the SLA dispute',negotiate:'Negotiating PromisePay', 'pay-first':'Collecting £300 in test mode','pay-second':'Collecting £500 early in test mode',reconcile:'Reconciling Stripe balances','core-run':'Verifying the Acme core workflow','core-prepare':'Storing facts and creating an unpaid test invoice','core-propose':'Retrieving evidence and validating the proposal','core-replace':'Creating safeguarded replacement invoices'};
  if(labels[action])return job(`/api/cases/${encodeURIComponent(c.id)}/${action}`,{},labels[action]);
}
document.addEventListener('click',e=>{
  const workflow=e.target.closest('[data-workflow]');if(workflow){activeWorkflow=workflow.dataset.workflow;render();return;}
  const detail=e.target.closest('[data-agent-detail]');if(detail){const w=selectedWorkflow();const type=detail.dataset.agentDetail;showDetails('Actual agent '+type,type==='evidence'?w.retrieved:type==='policy'?{facts:w.facts.policy,limits:w.limits,validation:w.policy_validation}:w);return;}
  const action=e.target.closest('[data-action]');if(action){act(action.dataset.action).catch(error=>notify(error.message,true));return;}
  const row=e.target.closest('[data-case]');if(row){activeCase=row.dataset.case;refresh().then(()=>{location.hash='collections';render();}).catch(error=>notify(error.message,true));return;}
  const event=e.target.closest('[data-event]');if(event){showDetails('Decision & API evidence',events.find(x=>String(x.seq)===event.dataset.event));return;}
  const query=e.target.closest('[data-query]');if(query){document.querySelector('#memory-query').value=query.dataset.query;document.querySelector('#memory-query').focus();}
});
document.addEventListener('submit',e=>{if(e.target.id==='memory-form'){e.preventDefault();const form=new FormData(e.target);if(!current()){notify('Create a customer case before searching its memory.',true);return;}job('/api/memory/search',{query:form.get('query'),mode:form.get('mode'),case_id:current().id},'Searching customer-scoped Cognee memory');}});
window.addEventListener('hashchange',()=>{route=location.hash.slice(1);render();});
document.querySelector('#refresh-button').addEventListener('click',()=>refresh().then(()=>notify('Dashboard refreshed from the execution journal.')).catch(e=>notify(e.message,true)));
document.querySelector('#close-dialog').addEventListener('click',()=>document.querySelector('#details-dialog').close());
document.querySelector('#toast').addEventListener('click',()=>document.querySelector('#toast').classList.add('hidden'));
document.querySelector('#today').textContent=new Date().toLocaleDateString('en-GB',{weekday:'long',day:'numeric',month:'long',timeZone:'Europe/London'});
document.querySelectorAll('[data-icon]').forEach(el=>el.innerHTML=icon(el.dataset.icon));
async function init(){try{token=(await api('/api/session')).token;await refresh();}catch(e){render();notify('Cannot reach the CollectIQ backend: '+e.message,true);}}
init();
