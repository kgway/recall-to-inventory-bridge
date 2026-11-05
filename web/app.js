// SPDX-License-Identifier: MPL-2.0
"use strict";
const $ = id => document.getElementById(id);
let state = null;
let pendingUntil = 0;
let loading = false;
let connected = false;
let reviewCases = new Map();
let retailerRequest = null;
let retailerStorageError = "";
let inventoryPreview = null;
let searchPlan = null;
let sourceRequestId = null;
let discoveryRenderKey = "";
let monitorGeneration = null;
let monitorRenderKey = "";
try { retailerRequest = new RetailerRequest(sessionStorage, () => crypto.randomUUID()); }
catch (error) { retailerStorageError = error.message; }
const labels = {HOLD_RECALL:"Recall match",HOLD_REVIEW:"Review recommended",PENDING_EVALUATION:"Not evaluated",ELIGIBLE_IN_DEMO_SCOPE:"No match in selected notices"};
const decisions = {MATCH_RECALL:"Recall match",NO_MATCH_FOR_NOTICE:"Excluded for this notice",INSUFFICIENT_EVIDENCE:"Needs human review"};
const fields = {brand:"Brand",model:"Product model",adapter_model:"Adapter model",manufactured_month:"Manufacturing month",generation:"Generation"};
function node(tag, text, cls) {const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(cls)el.className=cls;return el;}
function message(text,error=false){$("message").textContent=text;$("message").className="message"+(error?" error":"");$("message").hidden=false;}
function rawDetails(title,value){const d=node("details",undefined,"raw-details");d.append(node("summary",title),node("pre",JSON.stringify(value,null,2)));return d;}
function externalLink(title,url){const a=node("a",title);a.href=url;a.target="_blank";a.rel="noopener noreferrer";return a;}
function productionReady(){return connected&&state?.production_running===true;}
function recordedDemo(){return state?.meta.experience_mode==="recorded-demo";}
function inventoryBridge(){return state?.meta.experience_mode==="inventory-bridge";}
function retailerReady(){return !inventoryBridge()&&productionReady()&&retailerRequest&&!retailerRequest.pending&&!retailerRequest.busy;}
async function api(action,payload){
  const controller=new AbortController();
  const timeout=setTimeout(()=>controller.abort(),35000);
  try{
    const options=payload===undefined?{}:{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)};
    const r=await fetch("api/"+action,{...options,signal:controller.signal,credentials:"same-origin",cache:"no-store"});
    let value;
    try{value=await r.json();}catch{throw Error("IRIS returned an unexpected response. Check that the Production is running and you are signed in.");}
    if(!r.ok||value.ok===false)throw Error(value.error||"Request failed.");
    return value.result===undefined?value:value.result;
  }finally{clearTimeout(timeout);}
}
function badge(status){return node("span",labels[status]||status,"badge "+status);}
function actionButton(text,run,cls){const b=node("button",text,cls);b.type="button";b.addEventListener("click",()=>run(b));return b;}
async function act(action,payload,success){try{const result=await api(action,payload);message(success||JSON.stringify(result));await load();return result;}catch(error){message(error.message,true);return null;}}
function assessmentCurrent(a,lot,note){return a&&a.notice_version===note.version&&a.inventory_version===lot.version&&state.runs.some(r=>r.run_id===a.run_id&&r.status==="COMPLETED"&&r.policy_version===a.policy_version);}
function noticePriority(note,lot){const a=state.assessments.find(a=>a.lot_id===lot.lot_id&&a.notice_id===note.notice_id);const priority=!assessmentCurrent(a,lot,note)?1:a.decision==="NO_MATCH_FOR_NOTICE"?2:0;const sameIdentity=a?.checks.some(c=>["brand","model","adapter_model"].includes(c.field)&&lot[c.field]&&String(c.value).toLowerCase()===String(lot[c.field]).toLowerCase());return priority*2+(sameIdentity?0:1);}
function detail(lot){
  $("detail-title").textContent=lot.name+" · "+lot.lot_id;
  const body=$("detail-content");body.replaceChildren();body.append(badge(lot.status));
  if(recordedDemo())body.append(node("p","Recorded investigation demo: saved genuine AI proposals revalidated in this instance. No new AI inference.","config"));
  body.append(node("p",(inventoryBridge()?"Reported snapshot quantity: ":"Synthetic simulator stock: ")+lot.quantity+" units. Product model: "+(lot.model||"unknown")+". Manufacturing month: "+(lot.manufactured_month||"unknown")+"."));
  if(inventoryBridge())body.append(node("p","Source: "+lot.source_system+" · External record: "+lot.external_id+" · Location: "+(lot.location||"unspecified")+". Advice only; external inventory is unchanged.","config"));
  if(lot.adapter_model)body.append(node("p","Adapter model: "+lot.adapter_model+" · Generation: "+(lot.generation||"unknown")));
  body.append(node("h3","Decision for each loaded notice"));
  for(const note of [...state.notices].sort((a,b)=>noticePriority(a,lot)-noticePriority(b,lot))){
    const a=state.assessments.find(a=>a.lot_id===lot.lot_id&&a.notice_id===note.notice_id);
    const section=node("section",undefined,"assessment-card");
    section.append(node("h3",note.notice_id+" · "+(a?decisions[a.decision]||a.decision:"Awaiting assessment")),externalLink(note.title+" ↗",note.url));
    if(!a){section.append(node("p","No current assessment is available for this notice. No clearance is implied."));body.append(section);continue;}
    if(!assessmentCurrent(a,lot,note))section.append(node("p","This assessment is outdated or its agent run did not complete. It cannot authorize a new request.","rejected"));
    section.append(node("p",a.reason));
    if(a.missing_fields.length)section.append(node("p","Evidence still needed: "+a.missing_fields.map(f=>fields[f]||f.replaceAll("_"," ")).join(", "),"missing-fields"));
    if(a.origin==="human-review")section.append(node("p","Resolved by authenticated human review · "+a.review_id));
    for(const check of a.checks){
      const item=node("div",undefined,"evidence-check");
      const expected=Array.isArray(check.value)?check.value.join(" through "):check.value;
      item.append(node("strong",(fields[check.field]||check.field)+": inventory “"+(lot[check.field]||"unknown")+"” · source condition “"+expected+"”"),node("blockquote",check.evidence.quote));
      const source=note.snapshots.find(s=>s.id===check.evidence.snapshot_id);
      item.append(node("small",(source?source.kind+" · ":"")+check.evidence.snapshot_id+(source?"":" · historical snapshot")));
      section.append(item);
    }
    section.append(node("p","Run "+a.run_id+" · Policy "+a.policy_version,"audit-reference"),rawDetails("Full assessment and original agent proposal",a));body.append(section);
  }
  if(lot.reasons.length){body.append(node("h3","Reasons requiring attention"));for(const r of lot.reasons)body.append(node("p",(r.notice_id?r.notice_id+": ":"")+r.reason));}
  $("detail-dialog").showModal();
}
function beginReview(lot){
  $("review-lot").value=lot.lot_id;const select=$("review-notice");select.replaceChildren();
  const assessments=state.assessments.filter(a=>a.lot_id===lot.lot_id&&a.decision==="INSUFFICIENT_EVIDENCE"&&state.notices.some(n=>n.notice_id===a.notice_id&&assessmentCurrent(a,lot,n)));
  reviewCases=new Map(assessments.map(a=>[a.notice_id,{notice_version:a.notice_version,inventory_version:a.inventory_version,run_id:a.run_id}]));
  for(const a of assessments){const option=node("option",a.notice_id);option.value=a.notice_id;select.append(option);}
  if(!assessments.length){message("A current completed ambiguous assessment is required before review.",true);return;}
  $("review-reason").value="";$("review-dialog").showModal();
}
function retailerControls(){
  const pending=retailerRequest?.pending;
  $("pending-request").hidden=!pending&&!retailerStorageError;
  $("pending-description").textContent=retailerStorageError||(pending?"Result pending: synthetic "+pending.kind+" · "+pending.lines[0].lot_id+" · request "+pending.idempotency_key+". Checking again uses this same ID and retrieves its original result.":"");
  $("retry-request").hidden=!pending;$("retry-request").disabled=!productionReady()||retailerRequest?.busy===true;
  for(const b of document.querySelectorAll("#lot-rows .retailer-button"))b.disabled=!retailerReady();
}
function showReceipt(result){message((result.allowed?"EXECUTED":"BLOCKED")+" · synthetic "+result.kind+" · "+result.lines.map(l=>l.lot_id).join(", ")+(result.replayed?" · original result retrieved":"")+"\nRequest "+result.idempotency_key+(result.blocked.length?"\n"+result.blocked.map(r=>r.reason||labels[r.status]||r.status).join("; "):""),!result.allowed);}
async function sendRetailer(){
  if(!retailerRequest||!productionReady())return;
  try{const sending=retailerRequest.send(request=>api("transact",request));retailerControls();const result=await sending;showReceipt(result);await load();}
  catch(error){message(error.message+" Keep this tab and check the original request before sending another order.",true);}
  finally{retailerControls();}
}
async function retailer(lot,kind){try{if(!retailerReady())return;retailerRequest.begin(lot.lot_id,kind);await sendRetailer();}catch(error){message(error.message,true);retailerControls();}}
function inventory(){
  const rows=$("lot-rows");rows.replaceChildren();const query=$("search").value.toLowerCase();
  const lots=state.lots.filter(l=>[l.name,l.model,l.adapter_model,l.lot_id,l.sku].join(" ").toLowerCase().includes(query));
  if(!lots.length){const tr=node("tr");const td=node("td",state.lots.length?"No lots match your filter.":"Import an inventory snapshot or choose the separate recorded sample course.","empty");td.colSpan=5;tr.append(td);rows.append(tr);}
  for(const lot of lots){
    const tr=node("tr");const product=node("td");product.append(node("span",lot.name,"product-name"),node("span",(lot.external_id||lot.lot_id)+" · "+lot.sku+(lot.location?" · "+lot.location:""),"subtle"));
    const model=node("td");model.append(node("span",lot.model||"Model unknown"),node("span",lot.manufactured_month||"Manufacturing month unknown","subtle"));if(lot.adapter_model)model.append(node("span","Adapter: "+lot.adapter_model,"subtle"));
    const status=node("td");status.append(badge(lot.status),node("br"),actionButton("View evidence",()=>detail(lot),"detail-button"));
    if(lot.candidate_notice_ids?.length)status.append(node("small",lot.candidate_notice_ids.length+" retrieved candidate(s) · not confirmed","subtle"));
    const actions=node("td");const group=node("div",undefined,"row-actions");if(!inventoryBridge())group.append(actionButton("Sale",()=>retailer(lot,"sale"),"retailer-button"),actionButton("Ship",()=>retailer(lot,"shipment"),"retailer-button"));else group.append(node("small","Read-only snapshot · export advice"));
    if(lot.status==="HOLD_REVIEW"){const b=actionButton("Review",()=>beginReview(lot));b.disabled=!productionReady();group.append(b);}actions.append(group);tr.append(product,model,node("td",String(lot.quantity)),status,actions);rows.append(tr);
  }
  retailerControls();const log=$("transactions");log.replaceChildren();const recent=[...state.transactions].sort((a,b)=>b.at.localeCompare(a.at)).slice(0,8);
  if(!recent.length)log.append(node("p","No requests yet.","empty"));
  for(const t of recent){
    const item=node("details",undefined,"transaction-record");const summary=node("summary");summary.append(node("strong",t.allowed?"EXECUTED":"BLOCKED",t.allowed?"approved":"rejected"),node("span",t.kind+" · "+t.lines.map(l=>l.lot_id).join(", ")),node("small",new Date(t.at).toLocaleTimeString()));
    item.append(summary,node("p","Request "+t.idempotency_key,"audit-reference"));for(const blocked of t.blocked)item.append(node("p",(blocked.lot_id?blocked.lot_id+": ":"")+(blocked.reason||labels[blocked.status]||blocked.status)));item.append(rawDetails("Full retailer receipt",t));log.append(item);
  }
}
function evidence(){
  const parent=$("recall-cards");parent.replaceChildren();
  for(const note of state.notices){
    const card=node("article",undefined,"recall-card");card.append(node("span","CPSC "+note.recall_number+" · "+note.notice_id,"meta"),node("h3",note.title));card.append(node("p",note.source_conflict?"Source reconciliation required. A qualifier is missing or the detail page is unavailable.":"Evidence is available for scoped applicability checks."));
    const actions=node("div",undefined,"card-actions");const run=actionButton(inventoryBridge()?"Investigate next batch with AI Hub":"Investigate with AI Hub",async b=>{b.disabled=true;pendingUntil=Date.now()+300000;await act("investigate",{notice_id:note.notice_id},"Investigation queued. Up to 20 associated snapshot records per bridge batch; no external inventory action is performed.");});
    run.disabled=recordedDemo()||!productionReady()||state.configuration.agent_mode!=="live"||!(state.configuration.api_key_present&&state.configuration.free_tier_confirmed)||state.runs.some(r=>r.status==="RUNNING"||r.status==="SUBMITTED");if(state.configuration.agent_mode!=="live"||recordedDemo())run.title="New AI investigations are disabled for this session. Saved runs are available in Agent & audit.";
    actions.append(run,externalLink("Official CPSC notice ↗",note.url));card.append(actions,node("p","Evidence acquired "+new Date(note.acquired_at).toLocaleString()+" · "+note.snapshots.length+" snapshot(s)"));
    for(const source of note.snapshots){const details=node("details");details.append(node("summary",source.kind+" · "+source.id),node("div",source.text,"source-block"));card.append(details);}parent.append(card);
  }
}
function runs(){
  const c=state.configuration;$("configuration").textContent="Provider: "+c.provider+" · Model: "+c.model+" · Mode: "+c.agent_mode+" · Key: "+(c.api_key_present?"configured":"missing")+" · Free Tier: "+(c.free_tier_confirmed?"confirmed by operator":"not confirmed")+" · Paid fallback: disabled";
  const list=$("run-list");list.replaceChildren();if(!state.runs.length)list.append(node("p","No agent runs yet. Open Recall evidence to investigate a notice.","empty"));
  for(const run of [...state.runs].sort((a,b)=>b.created_at.localeCompare(a.created_at))){
    const replay=run.mode==="recorded-demo";
    const d=node("details",undefined,"run-card");d.append(node("summary",run.notice_id+" · "+(replay?"RECORDED · revalidated":run.status)+" · "+run.prompt_version+" · "+run.tool_calls.length+(run.tool_calls.length===1?" tool call":" tool calls")),node("p",replay?"Saved genuine AI Hub output · no new inference or tool execution in this instance":"Actual "+run.mode+" investigation · "+run.provider+" / "+run.model));
    d.append(node("p","Started "+new Date(run.created_at).toLocaleString()+" · "+(run.finished_at?"Finished "+new Date(run.finished_at).toLocaleString():"Awaiting completion")));
    if(run.usage)d.append(node("p","Provider-returned tokens: "+run.usage.prompt_tokens+" input + "+run.usage.completion_tokens+" output = "+run.usage.total_tokens+" total. No price estimate."));if(run.error)d.append(node("p",run.error,"rejected"));
    if(replay){const origin=run.recorded_origin.run;d.append(node("p","Original live run "+origin.run_id+" · "+origin.provider+" / "+origin.model+" · "+new Date(origin.created_at).toISOString()),node("p","Captured native ReadContext hash: "+origin.tool_calls[0].result_sha256),node("p","Original evidence record: "+run.recorded_origin.evidence_file+" · SHA-256 "+run.recorded_origin.evidence_sha256));if(origin.usage)d.append(node("p","Historical provider-returned tokens: "+origin.usage.total_tokens+". New inference tokens in this demo: 0."));}
    const steps=node("ol",undefined,"run-steps");steps.append(node("li",(replay?"Loaded pinned recorded context and original proposals":"Production started investigation")+" · "+run.prompt_version+" · "+run.policy_version));for(const tool of run.tool_calls)steps.append(node("li",tool.name+" · "+new Date(tool.at).toLocaleTimeString()+" · read-only context hash "+tool.result_sha256));
    if(run.validation)steps.append(node("li","Evidence validation · "+run.validation.assessment_count+" assessments · revision "+run.validation.revision+(run.validation.without_additional_inference?" · stored output revalidated without inference":"")));if(run.finished_at)steps.append(node("li",run.status+" · "+new Date(run.finished_at).toLocaleTimeString()));
    d.append(steps,node("p","Run "+run.run_id,"audit-reference"),rawDetails("Full run, tool hashes and returned usage",run));list.append(d);
  }
  const events=$("event-list");events.replaceChildren();for(const event of [...state.events].reverse())events.append(node("div",new Date(event.at).toLocaleTimeString()+" · "+event.kind+" · "+JSON.stringify(event),"event"));
}
function render(){
  const liveReady=!recordedDemo()&&!inventoryBridge()&&state.configuration.agent_mode==="live"&&state.configuration.api_key_present&&state.configuration.free_tier_confirmed;
  const lots=state.lots;$("total").textContent=lots.length;$("held").textContent=lots.filter(l=>l.status==="HOLD_RECALL").length;$("review-count").textContent=lots.filter(l=>["HOLD_REVIEW","PENDING_EVALUATION"].includes(l.status)).length;$("eligible").textContent=lots.filter(l=>l.status==="ELIGIBLE_IN_DEMO_SCOPE").length;$("scope").textContent=state.notices.length+" selected CPSC notices · "+lots.length+(inventoryBridge()?" imported records.":" synthetic demo lots.");
  $("connection").textContent=state.production_running===true?"IRIS Production connected":"IRIS connected · Production stopped";$("seed").hidden=!liveReady;$("seed").disabled=!liveReady||state.meta.initialized||!productionReady();$("refresh").hidden=!liveReady;$("refresh").disabled=!liveReady||!state.meta.initialized||!productionReady();$("session-note").hidden=!recordedDemo()&&state.configuration.agent_mode==="live";
  $("session-note").textContent=recordedDemo()?"RECORDED INVESTIGATION DEMO · Saved genuine AI proposals are revalidated here. No new AI calls. Sale/Ship is a local synthetic downstream simulator.":"Fresh AI investigations are disabled. Snapshot import, official CPSC candidate retrieval and advisory export need no AI key. New AI assessments require an explicitly configured provider.";
  $("first-visit").hidden=state.meta.initialized||liveReady||lots.length>0;$("load-recorded").disabled=!productionReady()||state.configuration.agent_mode!=="disabled";
  $("recorded-setup-note").textContent=state.configuration.agent_mode==="disabled"?"Empty instance ready. Existing data is never replaced. For fresh AI investigations, use a separate empty instance configured for live mode.":"Set AGENT_MODE=disabled and restart this empty instance to enable the no-key demo. The separate live course requires a confirmed provider configuration before loading inventory.";
  const blocked=!state.meta.initialized||!state.notices.length||Boolean(state.meta.refresh_error);$("gate-note").hidden=inventoryBridge()||!blocked;$("gate-note").textContent="The optional local retailer simulator rejects requests until its selected notices and synthetic lots are assessed.";
  const demoConsumer=!inventoryBridge()&&lots.some(l=>l.synthetic===true&&!l.read_only_snapshot);
  $("demo-shortcuts").hidden=!demoConsumer;$("demo-transactions").hidden=!demoConsumer;$("consumer-column").textContent=demoConsumer?"Local simulator":"Integration";
  for(const b of document.querySelectorAll('[data-lot]'))b.disabled=!lots.some(l=>l.lot_id===b.dataset.lot);
  inventory();evidence();runs();renderBridge();renderMonitor();if(!productionReady())message("The IRIS Production is stopped. Saved evidence and advisory exports remain available; start it before importing or retrieving sources.",true);
}
async function load(){
  if(loading)return;loading=true;
  try{state=await api("state");connected=true;const found=retailerRequest?.pending&&state.transactions.find(t=>t.idempotency_key===retailerRequest.pending.idempotency_key);if(found){retailerRequest.acknowledge(found);showReceipt(found);}render();}
  catch(error){connected=false;$("connection").textContent="IRIS unavailable";$("seed").disabled=true;$("load-recorded").disabled=true;$("refresh").disabled=true;for(const b of document.querySelectorAll("#lot-rows .row-actions button, #recall-cards button"))b.disabled=true;retailerControls();message(error.message+" This page does not simulate a connected backend.",true);}
  finally{loading=false;}
}
$("retry-request").addEventListener("click",sendRetailer);
$("seed").addEventListener("click",()=>act("seed",{},"Loaded real CPSC snapshots and explicitly synthetic inventory. Lots stay blocked until assessed."));
$("load-recorded").addEventListener("click",async()=>{$("load-recorded").disabled=true;await act("load_recorded_demo",{},"Recorded investigation demo loaded. Saved proposals were revalidated; no new AI inference. Try the four cases and synthetic retailer requests.");});
$("refresh").addEventListener("click",()=>{pendingUntil=Date.now()+180000;act("refresh",{},"CPSC refresh queued. Source changes invalidate old assessments.");});
$("search").addEventListener("input",()=>{if(state)inventory();});
for(const b of document.querySelectorAll('[data-lot]')){b.disabled=true;b.addEventListener('click',()=>{const lot=state?.lots.find(l=>l.lot_id===b.dataset.lot);if(lot){$("search").value=lot.lot_id;inventory();detail(lot);}});}
for(const b of document.querySelectorAll("[data-tab]"))b.addEventListener("click",()=>{for(const t of document.querySelectorAll("[data-tab]")){const active=t===b;t.classList.toggle("active",active);t.setAttribute("aria-selected",String(active));}for(const pane of document.querySelectorAll(".pane"))pane.hidden=pane.id!==b.dataset.tab;});
$("close-detail").addEventListener("click",()=>$("detail-dialog").close());$("close-review").addEventListener("click",()=>$("review-dialog").close());
$("review-form").addEventListener("submit",async e=>{e.preventDefault();const reviewed=reviewCases.get($("review-notice").value);if(!reviewed){message("Reopen this case to review the current evidence.",true);return;}const submit=e.submitter;submit.disabled=true;try{const result=await act("review",{...reviewed,lot_id:$("review-lot").value,notice_id:$("review-notice").value,decision:$("review-decision").value,reason:$("review-reason").value},"Human review recorded with the authenticated IRIS user.");if(result)$("review-dialog").close();}finally{submit.disabled=false;}});

function inventoryPayload(){return {source_system:$("inventory-source").value,format:$("inventory-format").value,
  content:$("inventory-content").value,mapping:JSON.parse($("inventory-mapping").value||"{}"),
  delimiter:$("inventory-delimiter").value==="tab"?"\t":$("inventory-delimiter").value,
  data_classification:$("inventory-example").checked?"synthetic-example":"user-provided"};}
function invalidatePreview(){inventoryPreview=null;$("inventory-commit").disabled=true;$("inventory-preview-result").replaceChildren();}
function queryLabel(query){return Object.entries(query.filters||{[query.field]:query.term}).map(([field,term])=>field+" = “"+term+"”").join(" AND ");}
function renderBridge(){
  const canImport=inventoryBridge()||(!state.lots.length&&!state.notices.length);
  $("bridge-import").hidden=!canImport;$("bridge-discovery").hidden=!inventoryBridge();
  $("inventory-preview").disabled=!productionReady();$("inventory-commit").disabled=!productionReady()||!inventoryPreview?.valid;
  const task=state.meta.source_task;
  if(sourceRequestId&&state.monitor?.cycles.some(c=>c.request_id===sourceRequestId&&c.status!=="RUNNING")){sourceRequestId=null;pendingUntil=0;}
  if(sourceRequestId&&task?.request_id===sourceRequestId&&["COMPLETED","FAILED"].includes(task.status)){
    sourceRequestId=null;pendingUntil=0;if(task.status==="FAILED")message(task.error||"CPSC retrieval failed. Review the current inventory and search plan.",true);
  }
  const busy=Boolean(sourceRequestId)||task?.status==="RUNNING";
  $("discovery-plan").disabled=!productionReady()||busy;$("discovery-start").disabled=!productionReady()||busy||!searchPlan;
  const record=state.discoveries?.at(-1);const signature=JSON.stringify([record,task,productionReady(),busy]);
  if(discoveryRenderKey===signature)return;discoveryRenderKey=signature;
  const results=$("discovery-results");results.replaceChildren();
  if(task)results.append(node("p",task.action+" · "+task.status+(task.error?" · "+task.error:task.reason?" · "+task.reason:""),task.status==="FAILED"?"rejected":"config"));
  if(!record){results.append(node("p","No inventory-driven search has been performed."));return;}
  const currentVersions=Object.fromEntries(state.lots.map(l=>[l.lot_id,l.version]));
  const stale=JSON.stringify(Object.entries(record.inventory_versions).sort())!==JSON.stringify(Object.entries(currentVersions).sort());
  results.append(node("p",record.status+" · "+record.candidates.length+" candidate notices · scope is incomplete; no result is a safety assurance."));
  if(stale)results.append(node("p","Inventory identity changed. Review a new search plan before selecting candidates.","rejected"));
  if(record.plan.omitted_queries||record.plan.unsearched_lot_ids.length)results.append(node("p",record.plan.omitted_queries+" queries omitted · "+record.plan.unsearched_lot_ids.length+" inventory records not searched in this bounded batch."));
  for(const q of record.query_results)if(q.status==="FAILED"||q.limited||q.rejected_records)results.append(node("p",q.field+" = "+q.term+" · "+q.status+(q.limited?" · result limit reached":"")+(q.rejected_records?" · rejected unexpected records: "+q.rejected_records:""),"missing-fields"));
  const refined=c=>c.matched_queries.some(q=>q.field==="UPC"||Object.keys(q.filters||{}).length>1);
  const candidates=[...record.candidates].sort((a,b)=>Number(refined(b))-Number(refined(a))||a.title.localeCompare(b.title));
  const primaryCount=Math.min(5,Math.max(3,candidates.filter(refined).length));
  const more=node("details",undefined,"more-candidates");more.append(node("summary",Math.max(0,candidates.length-primaryCount)+" more retrieved candidates · broad text matches may be unrelated"));
  for(const [index,candidate] of candidates.entries()){
    const card=node("article",undefined,"recall-card");card.append(node("span","CANDIDATE ONLY · "+candidate.notice_id,"meta"),node("h3",candidate.title),node("p","Retrieved for "+candidate.lot_ids.length+" snapshot record(s) via "+candidate.matched_queries.map(queryLabel).join("; ")));
    const selected=state.notices.some(n=>n.notice_id===candidate.notice_id);
    const choose=actionButton(selected?"Refresh selected evidence":"Load official evidence",async()=>{
      sourceRequestId=crypto.randomUUID();pendingUntil=Date.now()+300000;
      const result=await act("select_candidates",{discovery_id:record.discovery_id,notice_ids:[candidate.notice_id],request_id:sourceRequestId},"Official evidence retrieval queued. No AI is called; no inventory action is sent.");
      if(!result)sourceRequestId=null;renderBridge();
    });choose.disabled=stale||busy||!productionReady();
    if(refined(candidate))card.append(node("small","Retrieved by combined product terms or UPC; still requires applicability assessment.","subtle"));
    const links=node("div",undefined,"card-actions");links.append(choose,externalLink("Official CPSC notice ↗",candidate.url));card.append(links,rawDetails("Captured API candidate text",candidate.api_snapshot));(index<primaryCount?results:more).append(card);
  }
  if(candidates.length>primaryCount)results.append(more);
}
for(const id of ["inventory-source","inventory-format","inventory-delimiter","inventory-content","inventory-mapping","inventory-example"])$(id).addEventListener("input",invalidatePreview);
$("inventory-import-id").value=crypto.randomUUID();
$("inventory-sample").addEventListener("click",()=>{
  $("inventory-source").value="sample-erp";$("inventory-format").value="csv";$("inventory-delimiter").value=",";$("inventory-mapping").value="{}";$("inventory-example").checked=true;
  $("inventory-content").value="external_id,sku,name,quantity,brand,model,lot_number,manufactured_month,location\n000101,HEAT-015,DREO space heater,47,DREO,DR-HSH015,LOT-APR25,2025-04,WH-EAST\n000102,SOUND-REST,Hatch Rest sound machine,12,Hatch,Rest,LOT-A,,WH-WEST\n000103,POWER-1263,Anker PowerCore 10000,18,Anker,A1263,LOT-B,,WH-EAST\n";
  $("inventory-import-id").value=crypto.randomUUID();invalidatePreview();
});
$("inventory-file").addEventListener("change",async()=>{const file=$("inventory-file").files[0];if(!file)return;if(file.size>100000){message("Choose a UTF-8 file up to 100,000 bytes.",true);return;}$("inventory-content").value=await file.text();$("inventory-format").value=file.name.toLowerCase().endsWith(".json")?"json":"csv";if(file.name.toLowerCase().endsWith(".tsv"))$("inventory-delimiter").value="tab";$("inventory-example").checked=false;$("inventory-import-id").value=crypto.randomUUID();invalidatePreview();});
$("inventory-preview").addEventListener("click",async()=>{try{inventoryPreview=await api("preview_inventory",inventoryPayload());const result=$("inventory-preview-result");result.replaceChildren(node("p",inventoryPreview.row_count+" rows · "+(inventoryPreview.valid?"valid preview":"fix row errors before import")),rawDetails("Detected mapping, ignored columns and preview rows",inventoryPreview));for(const error of inventoryPreview.errors)result.append(node("p","Row "+error.row+": "+error.error,"rejected"));renderBridge();}catch(error){invalidatePreview();message(error.message,true);}});
$("inventory-commit").addEventListener("click",async()=>{if(!inventoryPreview?.valid)return;try{const payload={...inventoryPayload(),preview_hash:inventoryPreview.preview_hash,workspace_revision:inventoryPreview.workspace_revision,import_id:$("inventory-import-id").value};$("inventory-commit").disabled=true;const result=await act("import_inventory",payload,"Snapshot imported locally. External inventory is unchanged. Review the CPSC search terms next.");if(result){invalidatePreview();searchPlan=null;$("discovery-plan-result").replaceChildren();}renderBridge();}catch(error){message(error.message,true);}});
$("discovery-plan").addEventListener("click",async()=>{try{searchPlan=await api("discovery_plan",{});const area=$("discovery-plan-result");area.replaceChildren(node("p",searchPlan.disclosure));const list=node("ul");for(const q of searchPlan.queries)list.append(node("li",queryLabel(q)+" · "+q.lot_ids.length+" inventory record(s)"));area.append(list,node("p",searchPlan.omitted_queries+" additional queries omitted; "+searchPlan.unsearched_lot_ids.length+" records not searched. No complete coverage is claimed."));renderBridge();}catch(error){message(error.message,true);}});
$("discovery-start").addEventListener("click",async()=>{if(!searchPlan)return;sourceRequestId=crypto.randomUUID();pendingUntil=Date.now()+300000;const result=await act("discover",{plan_hash:searchPlan.plan_hash,request_id:sourceRequestId},"CPSC candidate retrieval queued in the IRIS Production. This uses public product terms and no AI key.");if(!result)sourceRequestId=null;renderBridge();});
function renderMonitor(){
  const area=$("bridge-monitor");area.hidden=!inventoryBridge()||!state.monitor;if(area.hidden)return;
  const monitor=state.monitor,cfg=monitor.config;
  if(monitorGeneration!==cfg.generation){$("audit-enabled").checked=cfg.enabled;$("audit-ai").checked=cfg.auto_ai;$("audit-interval").value=String(cfg.interval_seconds);monitorGeneration=cfg.generation;}
  const aiReady=state.configuration.agent_mode==="live"&&state.configuration.api_key_present&&state.configuration.free_tier_confirmed;
  $("audit-ai").disabled=!aiReady;$("audit-ai-note").textContent=aiReady?"AI is opt-in: at most one investigation per audit, within the existing daily cap (automatic runs never exceed five/day). Current results are reused; unchanged failed inputs require manual retry.":"No model key is needed for monitoring. Automatic AI is unavailable in this profile; selected notices remain visibly unassessed until evaluated.";
  const busy=Boolean(cfg.active_cycle_id);$("audit-now").disabled=!productionReady()||busy||state.meta.source_task?.status==="RUNNING";$("audit-save").disabled=!productionReady();
  const next=cfg.next_due_at?new Date(cfg.next_due_at).toLocaleString():"not scheduled";
  $("audit-status").replaceChildren(node("p",(cfg.enabled?"Periodic checks enabled":"Periodic checks off")+" · Next due: "+next+(busy?" · Audit in progress":"")));
  const key=JSON.stringify(monitor.cycles);if(monitorRenderKey===key)return;monitorRenderKey=key;
  const history=$("audit-history");history.replaceChildren();if(!monitor.cycles.length)history.append(node("p","No audits yet. Run one now to establish a baseline; new candidates still require review.","subtle"));
  for(const cycle of monitor.cycles){
    const card=node("article",undefined,"recall-card");card.append(node("h3",cycle.status+" · "+(cycle.trigger==="timer"?"Scheduled check":"Requested check")),node("p",new Date(cycle.started_at).toLocaleString()+" · "+(cycle.new_candidate_ids?.length||0)+" new candidates · "+(cycle.changed_notice_ids?.length||0)+" changed notices · "+(cycle.advisory_changes?.length||0)+" changed inventory advisories"));
    card.append(node("p",(cycle.refreshed_notice_ids?.length||0)+" selected notices refreshed · "+(cycle.pending_evaluations?.length||0)+" notices still have unassessed inventory · "+(cycle.needs_attention??"—")+" inventory records need attention"));
    if(cycle.ai_deferred_reason)card.append(node("p","AI deferred: "+cycle.ai_deferred_reason,"subtle"));
    if(cycle.errors?.length||cycle.limitations?.length)card.append(node("p",[...(cycle.errors||[]),...(cycle.limitations||[])].join(" · "),"rejected"));
    card.append(node("small","Coverage is limited to retrieved candidates and selected notices; no result is a general safety assurance.","subtle"),rawDetails("Audit details and changes",cycle));history.append(card);
  }
}
$("audit-save").addEventListener("click",async()=>{
  if($("audit-enabled").checked&&!searchPlan){message("First click Review search terms in step 2 and read the terms, then save these settings.",true);return;}
  const aiReady=state.configuration.agent_mode==="live"&&state.configuration.api_key_present&&state.configuration.free_tier_confirmed;
  await act("audit_configure",{enabled:$("audit-enabled").checked,auto_ai:aiReady&&$("audit-ai").checked,interval_seconds:Number($("audit-interval").value),plan_hash:searchPlan?.plan_hash},"Audit settings saved. Periodic work requires this IRIS host and Production to stay running.");
});
$("audit-now").addEventListener("click",async()=>{sourceRequestId=crypto.randomUUID();pendingUntil=Date.now()+660000;const result=await act("audit_now",{request_id:sourceRequestId},"Audit queued through the IRIS Production. No external stock action is sent.");if(!result)sourceRequestId=null;});
let poll=0;
// Do not replace expanded receipts, source text or audit details while someone
// is reading them. Closing the detail resumes normal background status checks.
setInterval(()=>{const active=state&&(state.runs.some(r=>r.status==="RUNNING"||r.status==="SUBMITTED")||state.meta.source_task?.status==="RUNNING"||state.monitor?.config.active_cycle_id);const reading=document.querySelector('.pane:not([hidden]) details[open], #discovery-results details[open], #audit-history details[open]');if(!document.hidden&&!reading&&!$("review-dialog").open&&!$("detail-dialog").open&&!retailerRequest?.busy&&(active||Date.now()<pendingUntil||++poll>=5)){poll=0;load();}},3000);
load();
