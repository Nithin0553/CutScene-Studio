/* CutScene Studio — real project discovery, planning, execution and result evidence.
   Advanced research console remains accessible through ?advanced=1. */
(() => {
  'use strict';
  const $ = q => document.querySelector(q);
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const short = v => String(v || '').split(/[\\/]/).pop();
  const norm = v => String(v || '').replaceAll('\\','/').toLowerCase();
  const state = {screen:'home', phase:'IDLE', busy:false, info:'', error:'', status:null,
    discovery:null, folders:{unity:'',unreal:''}, unrealProject:'', csir:'', level:'',
    sourceRights:false, allowPartial:false, enableAI:false, candidate:null, job:null, verification:null,
    diagnosis:null, feedback:null, aiPreflight:null, running:false, detailsOpen:false, menuOpen:false,
    censusOptions:[], censusPath:'', censusSelection:null, censusIssue:false, editorHelpOpen:false};
  const pathRoot = () => String(state.status?.repo_root||'').replaceAll('\\','/');
  const workerCommand = () => {
    const folder=pathRoot()+'/integrations/unreal';
    const workspace=String(state.status?.workspace||'').replaceAll('\\','/');
    return 'import sys; from pathlib import Path; sys.path.insert(0, '+JSON.stringify(folder)+'); import studio_local_editor_worker as w; assert Path(w.__file__).resolve() == Path('+JSON.stringify(folder+'/studio_local_editor_worker.py')+').resolve(), "Old Studio worker cached; save and restart Unreal once"; w.start(workspace='+JSON.stringify(workspace)+')';
  };
  const connection = () => state.status?.connection;
  const worker = () => state.status?.unreal_worker || {};
  const readiness = () => state.status?.destination_readiness || {};
  const aiCandidate = () => Boolean(state.candidate?.ai_analysis);
  const terminal = job => job && !['RUNNING','QUEUED'].includes(job.status);
  const generated = () => Boolean(state.job &&
    state.job.generation_status === 'GENERATED_UNVERIFIED' &&
    ['GENERATED_AND_MEASURED_NOT_FIDELITY_VERIFIED',
      'GENERATED_DIAGNOSTIC_INCOMPLETE'].includes(state.job.status));
  const ico = name => ({check:'✓',folder:'▱',link:'↔',arrow:'➜',menu:'☰',alert:'!',down:'↓',layers:'▤',report:'▧'}[name]||'●');
  const button = (label,name,disabled=false,variant='primary') =>
    '<button type="button" class="button '+variant+'" data-action="'+name+'" '+(disabled?'disabled':'')+'>'+label+'</button>';
  function validEditor(){
    const c=connection(),d=readiness(),w=worker();
    return Boolean(c&&w.connected&&norm(w.project)===norm(c.target_project)&&
      (w.level===c.level_path||(c.auto_create_level&&d.status==='NEW_LEVEL_REQUIRED')));
  }
  function canAutoSetup(){
    const a=state.candidate?.automatic_setup||{},d=readiness();
    const collisions=['wrong_actor_types','wrong_asset_types','duplicate_actors']
      .some(k=>(d[k]||[]).length>0);
    return Boolean(a.available&&a.ready&&!collisions&&
      (d.status==='NEW_LEVEL_REQUIRED'||d.candidate_id===state.candidate.candidate_id)&&
      ['READY','SCENE_SETUP_REQUIRED','ASSETS_REQUIRED','NEW_LEVEL_REQUIRED'].includes(d.status));
  }
  function canExecute(){
    const d=readiness();return Boolean(validEditor()&&state.candidate&&!state.job&&!aiCandidate()&&
      ((d.ready&&d.candidate_id===state.candidate.candidate_id)||canAutoSetup()));
  }
  function progress(){
    const planning=['PREPARING','ANALYZING_AI','AI_PREPARED'].includes(state.phase);
    const selected=state.screen==='results'?3:state.screen==='transfer'?(planning?1:2):state.candidate?1:0;
    return '<div class="steps" aria-label="Transfer workflow">'+
      ['Connect','Plan','Import','Results'].map((label,i)=>
        '<div class="step '+(i===selected?'active':i<selected?'done':'')+
        '"><span class="circle">'+(i<selected?ico('check'):i+1)+'</span><span>'+label+'</span></div>').join('')+'</div>';
  }
  function header(){
    return '<header class="topbar"><a href="/" class="brand">CUTSCENE <em>Studio</em></a>'+
      '<nav class="main-nav" aria-label="Main navigation">'+
      ['Home','Projects'].map(n=>'<button data-action="'+n.toLowerCase()+'">'+n+'</button>').join('')+
      '<button class="hamburger" data-action="menu" aria-label="More options" aria-expanded="'+state.menuOpen+'">'+ico('menu')+'</button></nav></header>'+
      (state.menuOpen?'<div class="menu-pop"><a href="?advanced=1">Advanced</a><button data-action="results">Results</button></div>':'');
  }
  function toast(){
    // Blocked errors are already presented with their full diagnostics in
    // the main content. Avoid a duplicate transient toast covering the UI.
    if(state.screen==='transfer'&&state.phase==='BLOCKED')return '';
    if(!state.error&&!state.info)return '';
    return '<div class="toast '+(state.error?'bad':'')+'" role="'+(state.error?'alert':'status')+'"><b>'+
      (state.error?ico('alert'):ico('check'))+'</b><span>'+esc(state.error||state.info)+
      '</span><button data-action="clear" aria-label="Dismiss message">×</button></div>';
  }
  function home(){
    return '<section class="landing"><div class="landing-center"><h1>CUTSCENE</h1>'+
      '<div class="studio-title"><i></i><span>STUDIO</span><i></i></div>'+
      '<p>Unity Timeline → Unreal Level Sequence</p>'+
      button('Start Transfer','projects')+
      (state.job?(terminal(state.job)?
        '<div class="landing-previous">'+button('View Previous Transfer Report','results',false,'secondary')+'</div>':
        '<div class="landing-previous">'+button('View Active Transfer','resume-transfer',false,'secondary')+'</div>'):
        aiCandidate()?'<div class="landing-previous">'+button('View AI Plan','view-ai-plan',false,'secondary')+'</div>':'')+
      '</div></section>';
  }
  function card(kind,folder,ready){
    const name=kind==='unity'?'Unity':'Unreal Engine';
    return '<div class="engine-card '+(ready?'validated':'')+'"><div class="engine-heading"><span class="engine-icon">'+
      (kind==='unity'?'⬡':'Ⓤ')+'</span><strong>'+name+'</strong>'+
      (ready?'<span class="valid">'+ico('check')+'</span>':'')+'</div>'+
      '<small>'+esc(short(folder)||'Not selected')+'</small><label>Select '+name+' Project Folder</label>'+
      '<div class="folder-picker"><span title="'+esc(folder)+'">'+esc(folder||'Select a folder')+'</span>'+
      '<button type="button" data-action="browse-'+kind+'" aria-label="Browse '+name+'">'+ico('folder')+'</button></div></div>';
  }
  function line(active){
    return '<div class="connector '+(active?'connected':'')+'" aria-hidden="true"><div class="connector-line"></div>'+
      '<span class="connector-center">'+ico(active?'check':'link')+'</span></div>';
  }
  function select(name,title,options,picked,placeholder){
    return '<label class="choice"><span>'+title+'</span><select name="'+name+'" '+(!options.length?'disabled':'')+'>'+
      '<option value="">'+placeholder+'</option>'+
      options.map(row=>{const value=typeof row==='string'?row:row.path;
        const title=typeof row==='string'?short(row):(row.name||short(row.path));
        return '<option value="'+esc(value)+'" '+(value===picked?'selected':'')+'>'+esc(title)+'</option>';
      }).join('')+'</select></label>';
  }
  function unrealConnectionPanel(project){
    if(!pathRoot()||!state.status?.workspace)return '';
    const w=worker();
    const same=Boolean(project&&w.connected&&norm(w.project)===norm(project)&&norm(w.checkout_root)===norm(pathRoot()));
    const label=same?'Connected':w.connected?'Check project / checkout':'Not connected';
    return '<section class="unreal-connect"><div class="unreal-connect-row"><span>Unreal Editor: <strong>'+label+'</strong></span>'+button('Copy connection command','copy-worker',false,'secondary')+'</div>'+
      '<p class="subnote">Paste into Unreal’s Python Console.</p><details class="editor-help" '+(state.editorHelpOpen?'open':'')+'><summary>Show command</summary><pre id="worker-command">'+esc(workerCommand())+'</pre></details></section>';
  }
  function projectForm(){
    const d=state.discovery||{},u=d.unity||{},r=d.unreal||{};
    const cutscenes=u.cutscenes||[],levels=r.levels||[],sources=d.unity_projects||[],
      unrealRoots=d.unreal_projects||[],projects=r.project_options||[];
    const csir=state.csir||(cutscenes.length===1?cutscenes[0].path:'');
    const level=state.level||r.active_level||(levels.length===1?levels[0]:'');
    const chosenU=u.folder||state.folders.unity,chosenR=r.folder||state.folders.unreal;
    const connected=Boolean(connection());
    const selectionChanged=connected&&(csir!==connection().csir||level!==connection().level_path);
    const activeJob=Boolean(state.job&&!terminal(state.job));
    // An approved candidate without a queued Unreal job is NOT an active
    // engine transfer. It must never leave Start Transfer silently disabled.
    const pendingCandidate=Boolean(connected&&(state.running||aiCandidate())&&state.candidate&&!state.job);
    const matchingCensuses=state.censusOptions.filter(x=>x.project_identity_proven &&
      x.source_scope_matched && x.state!=='INVALID');
    let choices='';
    if(sources.length>1&&!u.folder)choices+=select('unity-project','Unity project',sources,state.folders.unity,'Choose project');
    if(unrealRoots.length>1&&!r.folder)choices+=select('unreal-project-root','Unreal project folder',unrealRoots,state.folders.unreal,'Choose Unreal project');
    if(projects.length>1)choices+=select('unreal-project-file','Unreal project file',projects,state.unrealProject,'Choose project');
    if(chosenU)choices+='<div class="project-choices">'+
      select('csir','Cutscene',cutscenes.map(x=>({...x,
        name:(x.name||'Cutscene')+' — '+short(x.path)})),csir,'Select cutscene')+
      select('level','Target level',levels,level,'Choose level')+
      (connected?'<section class="source-census-panel" aria-label="Source Census selection">'+
        select('census','Source details',matchingCensuses.map(x=>({...x,
        name:x.name+(x.strict_ready?' — source complete':
          ' — '+x.unresolved_components+' findings')})),state.censusPath,
        'Select matching source details')+
        '<p class="subnote"></p>'+
        (state.censusSelection?'<p class="subnote">Selected: '+esc(short(state.censusPath))+
          ' · '+esc(state.censusSelection.unresolved_components)+' unresolved source findings, '+
          esc(state.censusSelection.source_snapshot_partial_count||0)+' partially captured components (Unreal fidelity unverified).</p>':
          '<p class="warning">Select matching source details before starting the transfer.</p>')+
        (!matchingCensuses.length?'<p class="subnote">In Unity, select the Timeline and run Export for Studio, then Refresh.</p>':'')+
        (state.censusOptions.length>matchingCensuses.length?
          '<p class="subnote">Unrelated files hidden.</p>':'')+
        '</section>':'')+
      '<div class="export-refresh-row">'+
      button('Refresh','refresh-exports',state.busy,'secondary')+
      (selectionChanged?'<p class="warning" role="status">Selection changed. Reconnect projects before starting.</p>':'')+
      '</div></div>';
    const action=activeJob?
      button('View Active Transfer '+ico('arrow'),'resume-transfer',state.busy,'secondary'):
      connected&&(terminal(state.job)||selectionChanged)?
      button('Reconnect '+ico('link'),'connect',
        state.busy||!state.sourceRights||!d.ready||!csir||!level):
      pendingCandidate?
      button((state.enableAI?'Prepare New AI Plan ':'Start New Transfer ')+ico('arrow'),'start-fresh',
        state.busy||!state.sourceRights||!state.censusSelection):
      connected?button((state.enableAI?'Prepare AI Plan ':'Start Transfer ')+ico('arrow'),'start',
        state.busy||!state.sourceRights||!state.censusSelection):
      button('Connect Projects '+ico('link'),'connect',state.busy||!d.ready||!csir||!level||!state.sourceRights);
    return progress()+'<main class="projects-view"><h1>'+(!chosenU?'Select Unity Project':!chosenR?'Select Unreal Project':'Connect Unity &amp; Unreal')+'</h1>'+
      '<form id="project-form"><div class="engine-pair">'+card('unity',chosenU,Boolean(u.folder))+
      (chosenU?line(connected):'')+(chosenU?card('unreal',chosenR,Boolean(r.folder||r.project)):'')+'</div>'+
      (chosenU?unrealConnectionPanel(state.unrealProject||r.project||''):'')+
      choices+(chosenU&&!cutscenes.length?'<p class="subnote">In Unity, select the Timeline, choose Tools → CutsceneAI → Export for Studio, then Refresh.</p>':'')+(chosenU?'<div class="permissions"><label><input type="checkbox" name="source-rights" '+
      (state.sourceRights?'checked':'')+' /> I have permission to copy source assets</label>'+
      '<label><input type="checkbox" name="allow-partial" '+(state.allowPartial?'checked':'')+
      ' /> Allow partial transfer (not verified)</label>'+
      '<label><input type="checkbox" name="enable-ai-agent" '+(state.enableAI?'checked ':'')+
      (state.busy||activeJob?'disabled':'')+' /> Enable AI Agent (local Ollama)</label>'+
      (state.enableAI?'<p class="subnote">Analyze the selected source and prepare a verified plan. Native AI transfer is not enabled yet.</p>':'')+
      '</div>':'')+
      (Object.values(d.errors||{})).map(v=>'<p class="warning">'+esc(v)+'</p>').join('')+
      '<div class="center-actions">'+(chosenU?action:'')+'</div></form>'+
      (aiCandidate()&&!state.job?'<div class="center-actions">'+button('View AI Plan','view-ai-plan',state.busy,'secondary')+'</div>':'')+
      (activeJob?'<p class="subnote">An Unreal job is already queued or running.</p>':
       pendingCandidate?'<p class="subnote">A previous candidate was prepared but no Unreal job was submitted.</p>':
       connected?'<p class="subnote">Ready to transfer.</p>':'')+
      '</main>';
  }
  function research(){
    const c=state.candidate,v=state.verification;
    return '<details class="research" '+(state.detailsOpen?'open':'')+'><summary>Details</summary>'+
      (c?'<div class="fact">Planned actions <b>'+esc(c.action_total||0)+'</b></div>'+
      '<div class="fact">Planned imports <b>'+esc(c.automatic_setup?.planned_imports??'Unknown')+'</b></div>'+
      '<div class="fact">Planned actors <b>'+esc(c.automatic_setup?.planned_actors??'Unknown')+'</b></div>'+
      '<div class="fact">Unresolved source components <b>'+esc(c.source_unresolved_components??'Not assessed')+'</b></div>'+
      ((c?.source_snapshot_partial_count||state.censusSelection?.source_snapshot_partial_count)?
        '<div class="fact">Source-captured partial components <b>'+
        esc(c?.source_snapshot_partial_count||state.censusSelection?.source_snapshot_partial_count)+'</b></div>'+
        '<p class="subnote">These source components are recorded but full Unreal behavior remains unverified.</p>':'')+
      (c.automatic_setup?.blockers||[]).map(x=>'<p class="warning">'+esc(x)+'</p>').join('')+
      (c.automatic_setup?.warnings||[]).map(x=>'<p class="subnote">'+esc(x)+'</p>').join('')+
      (c.review_flags||[]).map(x=>'<p class="subnote">'+esc(x)+'</p>').join(''):'<p>Plan not prepared.</p>')+
      (state.job?'<div class="fact">Job status <b>'+esc(state.job.status)+'</b></div>':'')+
      (state.feedback?'<div class="fact">CineTwin/visual feedback <b>'+esc(state.feedback.status)+'</b></div>'+
        (state.feedback.issues||[]).map(row=>'<p class="warning">'+esc(row.category)+': '+
        esc(row.code||row.source||row.detail||row.status)+'</p>').join(''):'')+
      (v?'<div class="fact">Native structure <b>'+esc(v.persistence?.native_structure||'Not verified')+'</b></div>'+
        '<div class="fact">Visual inspection <b>'+esc(v.visual?.status||'Not verified')+'</b></div>':'')+
      '<p class="subnote">Generation does not prove fidelity.</p>'+
      '<a href="?advanced=1" class="report-link">Advanced details</a></details>';
  }
  function aiPlanSummary(){
    const a=state.candidate.ai_analysis,c=a.decision_counts||{};
    return '<section class="research" aria-label="AI preparation report">'+
      '<h3>Source analysis and verified candidate</h3>'+
      resultRow('Proposed mappings',c.proposed??'Not reported')+
      resultRow('Withheld mappings',c.unsupported??'Not reported')+
      resultRow('Failed / not analyzed',(c.failed??'?')+' / '+(c.not_analyzed??'?'))+
      resultRow('Planned actions',state.candidate.action_total??'Not reported')+
      resultRow('Active source CED alerts',a.active_ced_alerts??'Not reported')+
      '<p class="subnote">'+esc(a.reason||'Native execution is not enabled.')+' No native changes performed. Fidelity remains unverified.</p>'+
      '<h3>Read-only Unreal inspection</h3>'+
       '<p class="subnote">'+esc(state.aiPreflight?.verified?'Native setup inspection passed. Import readback and execution approval remain pending.':state.aiPreflight?.reason||'Connect the selected staging level to inspect the candidate.')+'</p>'+
       button('Inspect target (read-only)','inspect-ai-target',state.busy||!validEditor()||!state.candidate.automatic_setup?.ready||state.aiPreflight?.status==='AI_NATIVE_PREFLIGHT_REQUESTED','secondary')+
       (!validEditor()?'<pre>'+esc(workerCommand())+'</pre>'+button('Copy connection command','copy-worker',false,'secondary'):'')+
       button('Back to projects','projects',false,'secondary')+'</section>';
  }
  function transfer(){
    const phase=state.phase,d=readiness(),j=state.job||{};
    const activelyWorking=['PREPARING','ANALYZING_AI','READY_TO_QUEUE'].includes(phase)||['RUNNING','QUEUED'].includes(j.status);
    const label=phase==='PREPARING'?'Preparing…':
      phase==='ANALYZING_AI'?'Analyzing source with local AI…':
      phase==='AI_PREPARED'?'AI plan prepared':
      phase==='WAITING_FOR_EDITOR'?'Connect Unreal':
      phase==='READY_TO_QUEUE'?'Checking target…':
      ['RUNNING','QUEUED'].includes(j.status)?'Transferring…':
      phase==='BLOCKED'?'Transfer blocked':'Checking transfer…';
    const command=workerCommand();
    return progress()+'<main class="transfer-view"><div class="engine-pair">'+
      card('unity',connection()?.unity_project||state.folders.unity,true)+line(validEditor())+
      card('unreal',connection()?.target_project||state.folders.unreal,validEditor())+'</div>'+
      '<h2>'+esc(label)+'</h2>'+
      (state.censusSelection?.source_snapshot_partial_count?
        '<p class="subnote">'+esc(state.censusSelection.source_snapshot_partial_count)+
        ' native source snapshots recorded; collision, URP and signal behavior remains Unreal-unverified. See Detailed report.</p>':'')+
      (phase==='AI_PREPARED'&&aiCandidate()?aiPlanSummary():'')+
      (phase==='WAITING_FOR_EDITOR'?'<div class="editor-instructions"><p>Open the target project. Paste this into the Unreal Python Console.</p>'+
        '<pre id="worker-command">'+esc(command)+'</pre>'+button('Copy connection command','copy-worker',false,'secondary')+
        '<p class="subnote">'+esc(worker().connected?('Open project: '+short(worker().project)+' · Level: '+(worker().level||'Unknown')+' · Selected level: '+(connection()?.level_path||'Unknown')):(d.next_action||'Waiting for the editor'))+'</p></div>':'')+
      (phase==='BLOCKED'?'<p class="warning" role="alert">'+esc(state.error||j.error||d.next_action||'Read the diagnostic report')+'</p>':'')+
      (phase==='BLOCKED'&&state.censusIssue&&state.censusSelection?
        '<section class="census-blocker"><h3>'+esc(state.censusSelection.unresolved_components)+
        ' source features need review</h3><p>These features are not supported yet:</p>'+
        '<div class="census-findings">'+(state.censusSelection.unresolved_findings||[])
          .map(f=>'<div class="census-finding"><strong>'+esc(f.native_type||'Unknown component')+
          '</strong><span>'+esc(f.object_path||f.scene_path||'Source object unknown')+
          '</span><small>'+esc(f.state||'UNRESOLVED')+'</small></div>').join('')+'</div>'+
        (state.censusSelection.findings_truncated?'<p class="subnote">Additional source findings are available in the advanced report.</p>':'')+
        '<p class="subnote">Partial transfer excludes unverified features.</p>'+
        button(state.enableAI?'Prepare supported parts':'Transfer supported parts','best-effort',state.busy,'secondary')+
        '</section>':'')+
      '<div class="transfer-progress"><div class="indeterminate '+(activelyWorking?'working':'')+
      '" role="progressbar" aria-label="Transfer state" aria-valuetext="'+esc(label)+'"><i></i></div>'+
      '<span>'+esc(['RUNNING','QUEUED'].includes(j.status)?j.status:phase)+'</span></div>'+
      (terminal(state.job)?button('View Results '+ico('arrow'),'results'):'')+research()+'</main>';
  }
  function resultRow(name,value){
    return '<div class="result-row"><span>'+name+'</span><strong>'+esc(value)+'</strong></div>';
  }
  function failureDetails(){
    const j=state.job||{};
    if(!terminal(j)||generated())return '';
    const stage=j.failure_stage||j.execution_stage||'UNKNOWN_NATIVE_STAGE';
    const reason=j.error||j.setup_error||
      'No native error message was recorded. Open Unreal Editor Output Log and inspect the saved job JSON.';
    const step=j.setup_failed_step;
    const operation=step&&typeof step==='object'?
      [step.phase,step.name||step.kind||step.path||step.level].filter(Boolean).join(' — '):
      typeof step==='string'?step:'';
    const partial=j.status==='PARTIAL_SETUP_MUST_INSPECT'||
      j.setup_status==='PARTIAL_SETUP_MUST_INSPECT';
    const recovery=partial?
      'Unreal may already contain imported assets or newly created actors. Do not rerun this candidate. Inspect the staging level and import receipt, then create a fresh candidate after correcting the problem.':
      j.setup_recovery||
      'Inspect the Unreal Editor Output Log for this job, correct the reported issue, and start a new transfer using a fresh candidate. Do not overwrite any existing sequence.';
    return '<section class="transfer-failure" role="alert" aria-label="Native transfer error">'+
      '<h2>Transfer stopped before sequence generation</h2>'+
      '<p><strong>Execution stage:</strong> '+esc(stage)+'</p>'+
      '<p><strong>Native error:</strong> '+esc(reason)+'</p>'+
      (j.setup_status?'<p><strong>Asset setup:</strong> '+esc(j.setup_status)+'</p>':'')+
      (operation?'<p><strong>Failed operation:</strong> '+esc(operation)+'</p>':'')+
      '<p class="failure-recovery"><strong>What to do next:</strong> '+esc(recovery)+'</p>'+
      '<div class="failure-actions">'+button('Copy failure details','copy-failure',false,'secondary')+'</div>'+
      '<p class="subnote">Job '+esc(j.job_id||'unknown')+
      (j.created_at?' · Created '+esc(j.created_at):'')+
      ' · This is an execution failure, not a CineTwin fidelity comparison.</p></section>';
  }
  function results(){
    const j=state.job||{},v=state.verification||{},ok=generated(),candidate=state.candidate||{};
    const imports=Number.isInteger(j.assets_imported_count)?j.assets_imported_count:'Not independently verified';
    const bindings=Number.isInteger(j.bindings_created_count)?j.bindings_created_count:'Not independently verified';
    return progress()+'<main class="results-view"><div class="results-card '+(ok?'ok':'')+'">'+
      '<h1>'+(ok?'Editable Sequence Generated':'Transfer Results')+'</h1>'+
      resultRow('Generated Sequence',ok?short(j.generated_sequence||j.sequence_path):'Not generated')+
      resultRow('Assets Imported',imports)+resultRow('Bindings Created',bindings)+
      '<div class="result-row"><span>Transfer Report</span><button class="report-link" data-action="view-report">View Report</button></div>'+
      '<p class="subnote">'+esc(j.status||'Not started')+' — '+(ok?'generation succeeded; fidelity is not certified':'no success claim')+'</p></div>'+
      failureDetails()+
      '<div class="verification"><p>Native structure: '+esc(ok?(v.persistence?.native_structure||'Not verified'):
        'Not verified — sequence generation did not finish')+'</p>'+
      '<p>Persistence after reopen: '+esc(!ok?'Not applicable until an editable sequence has been generated and saved':
        v.persistence?.restart_verified?'Verified in a different Unreal process':
        'Not verified — reopen the saved map in a new Unreal Editor process')+'</p>'+
      '<p>CineTwin behavioral parity: '+(state.diagnosis?'Measured — not full fidelity':'Not verified')+'</p>'+
      '<p>Visual fidelity: '+esc(v.visual?.status||'Not verified')+'</p>'+
      '</div>'+
      research()+'<div class="center-actions">'+button('New Transfer','projects',false,'secondary')+'</div></main>';
  }
  function about(){return '<main class="about-view"><h1>CutScene Studio</h1>'+
    '<p>This local system analyzes Unity cutscenes, plans native Unreal reconstruction, and measures known source-to-target differences. CineTwin and CED provide evidence and conversion strategies; unsupported effects are explicitly reported.</p>'+
    '<p>For full CED coverage, editing options, native audits and reports, use the <a href="?advanced=1">Advanced research workspace</a>.</p></main>';}
  // Reconcile the browser DOM, rather than replacing every node after each
  // two-second poll. This keeps ongoing CSS animations, focus, open details,
  // and the compositor layers alive while a status label changes.
  let lastMarkup = null;
  function reconcile(parent, freshParent){
    const original=Array.from(parent.childNodes);
    const incoming=Array.from(freshParent.childNodes);
    for(let i=0;i<incoming.length;i++){
      const next=incoming[i], old=original[i];
      if(!old){parent.appendChild(next.cloneNode(true));continue;}
      if(old.nodeType!==next.nodeType || old.nodeName!==next.nodeName){
        parent.replaceChild(next.cloneNode(true),old);continue;
      }
      if(old.nodeType===3 || old.nodeType===8){
        if(old.nodeValue!==next.nodeValue)old.nodeValue=next.nodeValue;
        continue;
      }
      if(old.nodeType!==1)continue;
      for(const attr of Array.from(old.attributes)){
        if(!next.hasAttribute(attr.name))old.removeAttribute(attr.name);
      }
      for(const attr of Array.from(next.attributes)){
        if(old.getAttribute(attr.name)!==attr.value)old.setAttribute(attr.name,attr.value);
      }
      if(old.tagName==='DETAILS' && old.hasAttribute('class') &&
        old.classList.contains('research')){
        // The browser's native details open state is authoritative.
        // The existing toggle listener remembers the user's preference.
        if(state.detailsOpen)old.setAttribute('open','');
        else old.removeAttribute('open');
      }
      if(old.tagName==='SELECT' && old===document.activeElement){
        // Preserve an actively open native dropdown until change/blur.
        continue;
      }
      if(old.tagName==='INPUT' && old===document.activeElement)continue;
      reconcile(old,next);
    }
    for(let i=original.length-1;i>=incoming.length;i--)parent.removeChild(original[i]);
  }
  function render(){
    const contents=state.screen==='home'?home():state.screen==='projects'?projectForm():
      state.screen==='transfer'?transfer():state.screen==='results'?results():about();
    const markup=header()+'<div class="page '+state.screen+'">'+contents+'</div>'+toast();
    if(markup===lastMarkup)return;
    const app=$('#app');
    lastMarkup=markup;
    if(typeof document.createElement==='function' &&
       typeof app.childNodes!=='undefined'){
      const fragment=document.createElement('template');
      fragment.innerHTML=markup;
      reconcile(app,fragment.content);
    }else{
      // Minimal DOM harness used by dependency-free Node regression tests.
      app.innerHTML=markup;
    }
  }
  async function api(route,data){
    const resp=await fetch('/api/'+route,{method:data===undefined?'GET':'POST',cache:'no-store',
      headers:data===undefined?{}:{'Content-Type':'application/json','X-CSAI-Token':state.status?.token||''},
      body:data===undefined?undefined:JSON.stringify(data)});
    let obj={};try{obj=await resp.json();}catch{throw Error('Invalid Studio server response.');}
    if(!resp.ok)throw Error(obj.error||'Request failed: '+resp.status);
    return obj;
  }
  async function scan(){
    const d=await api('discover',{unity_folder:state.folders.unity,unreal_folder:state.folders.unreal,
      unreal_project:state.unrealProject});
    state.discovery=d;
    if(d.unity?.folder)state.folders.unity=d.unity.folder;
    if(d.unreal?.folder)state.folders.unreal=d.unreal.folder;
    const sources=d.unity?.cutscenes||[],levels=d.unreal?.levels||[];
    if(!sources.some(x=>x.path===state.csir))state.csir=sources.length===1?sources[0].path:'';
    if(!levels.includes(state.level))state.level=d.unreal?.active_level||(levels.length===1?levels[0]:'');
    // Census choices must always be audited against the connected CSIR.
    if(connection() && state.csir===connection().csir)await loadCensuses();
    else{state.censusOptions=[];state.censusPath='';state.censusSelection=null;}
  }
  async function loadCensuses(){
    const response=await api('source-surfaces');
    state.censusOptions=response.options||[];
    const eligible=state.censusOptions.filter(x=>x.project_identity_proven && x.source_scope_matched && x.state!=='INVALID');
    const selected=eligible.find(x=>x.path===state.censusPath)||(!state.censusPath&&eligible.length===1?eligible[0]:null);
    state.censusSelection=selected||null;
    state.censusPath=selected?.path||'';
  }
  async function connectProjects(){
    if(!state.discovery?.ready||!state.csir||!state.level||!state.sourceRights)
      throw Error('Choose a detected cutscene and level, and approve asset-copy rights.');
    const info=await api('connect-projects',{unity_folder:state.folders.unity,
      unreal_folder:state.folders.unreal,unreal_project:state.unrealProject,
      csir:state.csir,level:state.level,source_rights_confirmed:state.sourceRights});
    state.status.connection=info;state.candidate=null;state.job=null;state.verification=null;state.diagnosis=null;state.feedback=null;state.running=false;
    state.censusOptions=[];state.censusPath='';state.censusSelection=null;
    state.phase='CONNECTED';state.info='Projects connected.';
    state.error='';state.censusIssue=false;
    await loadCensuses();
  }
  async function refresh(){
    const s=await api('status');state.status=s;
    if(!state.running)state.candidate=s.candidate||null;
    if(aiCandidate()&&state.screen==='transfer'){
      try{state.aiPreflight=await api('ai-native-preflight');}catch{state.aiPreflight=null;}
    }else state.aiPreflight=null;
    if(s.active_job)state.job=await api('jobs/'+s.active_job);
    if(terminal(state.job)){
      state.phase=generated()?'COMPLETE':'BLOCKED';
      try{state.verification=await api('verification');}catch{}
      if(state.job?.diagnostic_file&&!state.diagnosis){
        try{state.diagnosis=await api('diagnostic/'+state.job.job_id);}catch{}
      }
      if(!state.feedback) {
        try{const feedback=await api('closed-loop');if(feedback.available)state.feedback=feedback;}catch{}
      }
    }
  }
  async function prepare(){
    state.phase='PREPARING';render();
    const opts={enable_fbx_embedded_material_import:true,enable_actor_visibility_fallback:false,
      enable_ai_agent:state.enableAI};
    const chosen=state.censusPath;
    if(!chosen)throw Error('Choose a Source Census for this transfer before continuing.');
    // Revalidate the exact explicit choice. Do not switch to another census.
    await loadCensuses();
    if(!state.censusSelection||state.censusSelection.path!==chosen){
      throw Error('Selected Source Census is missing or does not match the connected CSIR. Refresh exports, select a matching census, and reconnect if the CSIR changed.');
    }
    opts.source_feature_surface_path=chosen;
    opts.require_complete_source_features=!state.allowPartial;
    if(!state.allowPartial && state.censusSelection &&
       !state.censusSelection.strict_ready){
      state.censusIssue=true;
      throw Error('Strict source census blocked: ' +
        state.censusSelection.unresolved_components +
        ' source component/scope findings. Review the exact findings below before choosing how to continue. No Unreal assets were modified.');
    }
    state.censusIssue=false;
    if(opts.enable_ai_agent){state.phase='ANALYZING_AI';render();}
    state.candidate=await api('prepare',opts);
    if(opts.enable_ai_agent&&!aiCandidate())throw Error('AI evidence missing from prepared candidate. No execution requested.');
    if(aiCandidate()){
      state.phase='AI_PREPARED';state.running=false;state.error='';state.info='';render();return;
    }
    // An existing, independently ready Unreal level may not require imports.
    // Never treat an import blocker as permission to bypass editor readiness.
    state.phase='READY_TO_QUEUE';
    await api('approve-one-click',{candidate_id:state.candidate.candidate_id});
  }
  async function advance(){
    if(!state.running||state.busy||state.job||!state.candidate||aiCandidate())return;
    if(!validEditor()){state.phase='WAITING_FOR_EDITOR';render();return;}
    const d=readiness();
    if(!d.ready && state.candidate.automatic_setup?.blockers?.length){
      throw Error('Unresolved source assets: '+state.candidate.automatic_setup.blockers.join('; '));
    }
    if(!canExecute()){
      if(['WRONG_TARGET','TARGET_EXISTS','UPGRADE_COMPANION','INSPECTION_FAILED'].includes(d.status))
        throw Error(d.next_action||d.status);
      state.phase='READY_TO_QUEUE';render();return;
    }
    // Start Transfer is the user approval for one guarded, non-overwriting
    // candidate. The backend revalidates source hashes, exact editor, level,
    // readiness, and non-overwrite requirements before accepting the job.
    state.busy=true;render();
    try{
      state.job=await api('execute',{candidate_id:state.candidate.candidate_id});
      state.phase='RUNNING';state.error='';
    }finally{state.busy=false;render();}
  }
  async function startFresh(){
    // User explicitly requested a new candidate instead of reusing the
    // restored approval. The backend refuses reconnect if an Unreal job
    // was queued while this screen was open.
    if(!connection()||state.job||(!state.running&&!aiCandidate())||!state.candidate)
      throw Error('There is no unsubmitted candidate to replace. Inspect the active job or reconnect.');
    const chosenCSIR=state.csir,chosenLevel=state.level,chosenCensus=state.censusPath;
    if(!chosenCensus||!state.censusSelection)
      throw Error('Choose a matching Source Census before starting a fresh transfer.');
    await connectProjects();
    if(state.csir!==chosenCSIR||state.level!==chosenLevel)
      throw Error('Connected source or destination changed. Select the correct CSIR and level again.');
    const selected=state.censusOptions.find(x=>x.path===chosenCensus &&
      x.project_identity_proven&&x.source_scope_matched&&x.state!=='INVALID');
    if(!selected)
      throw Error('The selected Source Census is no longer valid. Refresh exports and select it again; no transfer was prepared.');
    state.censusPath=chosenCensus;
    state.censusSelection=selected;
    await start();
  }
  async function start(){
    if(!connection()||!state.sourceRights)throw Error('Connect projects and confirm asset-copy rights.');
    if(state.csir!==connection().csir||state.level!==connection().level_path)
      throw Error('Selected CSIR or level changed. Reconnect projects before transferring.');
    if(!state.censusPath||!state.censusSelection)
      throw Error('Select matching source details before starting this transfer.');
    if(state.running||state.job)throw Error('A candidate is already active; inspect it before creating another.');
    state.screen='transfer';state.running=true;
    await prepare();await refresh();
    if(aiCandidate()){state.phase='AI_PREPARED';state.running=false;render();return;}
    state.phase='WAITING_FOR_EDITOR';render();await advance();
  }
  async function restore(){
    try{
      await refresh();
      if(connection()){
        state.folders.unity=connection().unity_project||'';
        state.folders.unreal=String(connection().target_project||'').replace(/[\\/][^\\/]+$/,'');
        state.csir=connection().csir;state.level=connection().level_path;
        state.unrealProject=connection().target_project;
        state.sourceRights=Boolean(connection().source_rights_confirmed);
        // A browser restart always lands on Home. Preserve server-side
        // transfer/report state, but never auto-navigate to the last report.
        state.screen='home';
        const approval=state.status.one_click_approval;
        state.running=Boolean(state.job||(approval?.candidate_id&&
          approval.candidate_id===state.candidate?.candidate_id&&
          approval.source_csir===connection().csir));
        if(aiCandidate()&&!state.job){state.enableAI=true;state.running=false;state.phase='AI_PREPARED';}
        else if(!terminal(state.job)&&state.job)state.phase='RUNNING';
        else if(state.running&&!state.job){state.phase='WAITING_FOR_EDITOR';}
        try{await scan();}catch{}
      }
    }catch(e){state.error=e.message;}render();
  }
  let polling=false;
  async function tick(){
    // Don't allow overlapping /api/status or /api/execute requests: stale
    // responses must not replace a more recent or user-selected screen.
    if(polling||state.busy||!state.status)return;
    polling=true;
    try{
      await refresh();
      if(state.running&&state.phase!=='BLOCKED'&&!state.job&&state.candidate)await advance();
      if(state.running&&terminal(state.job)&&state.screen==='transfer')state.screen='results';
      render();
    }catch(e){state.error=e.message;state.phase='BLOCKED';state.running=false;render();}
    finally{polling=false;}
  }
  async function action(name){
    if(name==='clear'){state.info='';state.error='';render();return;}
    if(name==='menu'){state.menuOpen=!state.menuOpen;render();return;}
    if(['home','projects','results','about'].includes(name)){
      state.screen=name;state.menuOpen=false;
      if(name==='projects'&&!state.discovery&&state.folders.unity)try{await scan();}catch{}
      render();return;
    }
    if(name==='refresh-exports'){
      if(state.busy)return;
      state.busy=true;render();
      try{
        await scan();
        state.info='Export list refreshed. Confirm your CSIR and Source Census selections.';
        state.error='';
      }catch(e){state.error=e.message;}
      finally{state.busy=false;render();}
      return;
    }
    if(name==='view-ai-plan'){
      if(aiCandidate()&&!state.job){state.screen='transfer';state.phase='AI_PREPARED';state.running=false;render();}
      return;
    }
    if(name==='inspect-ai-target'){
      if(state.busy||!aiCandidate()||state.job||!validEditor()||!state.candidate.automatic_setup?.ready)return;
      state.busy=true;state.error='';render();
      try{
        state.aiPreflight=await api('ai-native-preflight',{candidate_id:state.candidate.candidate_id});
        state.info='Read-only inspection requested. No transfer has been authorized.';
      }catch(e){state.error=e.message;state.aiPreflight=null;}
      finally{state.busy=false;render();}
      return;
    }
    if(name==='resume-transfer'){
      if((state.job&&!terminal(state.job))||
         (state.running&&state.candidate&&!state.job)){
        state.screen='transfer';render();
      }
      return;
    }
    if(name==='best-effort'){
      if(!state.censusIssue || !state.censusSelection ||
         !state.censusSelection.project_identity_proven ||
         !state.censusSelection.source_scope_matched ||
         state.job || !connection() || !state.sourceRights)return;
      state.allowPartial=true;
      state.censusIssue=false;
      state.error='';state.busy=true;state.running=true;state.screen='transfer';
      render();
      try{
        await prepare();
        await refresh();
        if(aiCandidate()){state.phase='AI_PREPARED';state.running=false;}
        else{state.phase='WAITING_FOR_EDITOR';await advance();}
      }catch(e){state.error=e.message;state.phase='BLOCKED';state.running=false;}
      finally{state.busy=false;render();}
      return;
    }
    if(name==='view-report'){state.detailsOpen=true;render();$('.research')?.scrollIntoView({behavior:'smooth'});return;}
    if(name==='copy-failure'){
      const j=state.job||{},step=j.setup_failed_step;
      const operation=step&&typeof step==='object'?
        [step.phase,step.name||step.kind||step.path||step.level].filter(Boolean).join(' — '):
        typeof step==='string'?step:'';
      const report=[
        'CutScene Studio — Native transfer failure',
        'Job: '+(j.job_id||'unknown'),
        'Candidate: '+(j.candidate_id||'unknown'),
        'Created: '+(j.created_at||'unknown'),
        'Status: '+(j.status||'unknown'),
        'Generation: '+(j.generation_status||'unknown'),
        'Stage: '+(j.failure_stage||j.execution_stage||'unknown'),
        'Cause: '+(j.error||j.setup_error||'No error recorded'),
        'Asset setup: '+(j.setup_status||'not recorded'),
        operation?'Failed operation: '+operation:'',
        j.setup_recovery?'Recovery: '+j.setup_recovery:'',
      ].filter(Boolean).join('\n');
      try{
        await navigator.clipboard.writeText(report);
        state.info='Native failure details copied. Review for sensitive local paths before sharing.';
        state.error='';
      }catch{state.error='Could not copy the failure details. Read the error above or inspect the saved job JSON.';}
      render();return;
    }
    if(name==='copy-worker'){
      try{await navigator.clipboard.writeText(workerCommand());
        state.info='Unreal Editor companion command copied.';}
      catch{state.editorHelpOpen=true;state.error='Copy the command manually from the box.';}render();return;
    }
    if(name==='browse-unity'||name==='browse-unreal'){
      state.busy=true;render();
      try{
        const kind=name.slice(7),choice=await api('pick-folder',{kind});
        if(!choice.cancelled){
          state.folders[kind]=choice.path;
          if(kind==='unreal')state.unrealProject='';
          state.discovery=null;state.csir='';state.level='';
          state.censusOptions=[];state.censusPath='';state.censusSelection=null;
          await scan();state.error='';
        }
      }catch(e){state.error=e.message;}finally{state.busy=false;render();}return;
    }
    if(name==='connect'||name==='start'||name==='start-fresh'){
      if(state.busy)return;
      state.busy=true;render();
      try{
        if(name==='connect')await connectProjects();
        else if(name==='start-fresh')await startFresh();
        else await start();
      }
      catch(e){state.error=e.message;state.phase='BLOCKED';state.running=false;}
      finally{state.busy=false;render();}return;
    }
  }
  $('#app').addEventListener('click',e=>{
    const node=e.target.closest('[data-action]');if(node)void action(node.dataset.action);
  });
  $('#app').addEventListener('change',async e=>{
    const n=e.target?.name,v=e.target?.value;
    if(n==='source-rights'){state.sourceRights=e.target.checked;render();return;}
    if(n==='allow-partial'){state.allowPartial=e.target.checked;render();return;}
    if(n==='enable-ai-agent'){if(!state.busy)state.enableAI=e.target.checked;render();return;}
    if(n==='csir'){
      state.csir=v;state.censusOptions=[];state.censusPath='';state.censusSelection=null;
      render();return;
    }
    if(n==='census'){
      const selected=state.censusOptions.find(x=>x.path===v&&
        x.project_identity_proven&&x.source_scope_matched&&x.state!=='INVALID');
      state.censusSelection=selected||null;
      state.censusPath=selected?selected.path:'';
      state.censusIssue=false;render();return;
    }
    if(n==='level'){state.level=v;render();return;}
    if(['unity-project','unreal-project-root','unreal-project-file'].includes(n)){
      if(n==='unity-project')state.folders.unity=v;
      else if(n==='unreal-project-root'){state.folders.unreal=v;state.unrealProject='';}
      else state.unrealProject=v;
      state.busy=true;render();try{await scan();}catch(e){state.error=e.message;}
      finally{state.busy=false;render();}
    }
  });
  $('#app').addEventListener('toggle',e=>{if(e.target.matches('.research'))state.detailsOpen=e.target.open;else if(e.target.matches('.editor-help'))state.editorHelpOpen=e.target.open;},true);
  void restore();
  setInterval(()=>{if(document.visibilityState==='visible')void tick();},2000);
})();
