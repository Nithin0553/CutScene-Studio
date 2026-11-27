/* Mock-backend UI integration regression, using only Node's built-in vm/assert. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const src = fs.readFileSync('apps/studio-web/cinematic.js', 'utf8');
const css = fs.readFileSync('apps/studio-web/cinematic.css', 'utf8');

function boot({editorReady = true, censusUnresolved = false, multiSources = false,
  restoredJob = '', restoredPending = false, restoredAI = false, aiFailure = false,
  missingAI = false, approvalFails = false} = {}) {
  const listeners = {}, calls = [], requests = [];
  let html = '', writes = 0, copied = '';
  const app = {
    get innerHTML() {return html;},
    set innerHTML(value) {html=value;writes++;},
    addEventListener(name, fn) { listeners[name] = fn; },
  };
  let poll;
  let connected = null;
  let candidate = null;
  let currentJob = null;
  let approval = null;
  let inspectionRequested = false;
  let done = false;
  const unity = 'D:/CutSceneAI_Unity';
  const unreal = 'D:/CutSceneAI_Unreal';
  const csir = unity + '/CutSceneAI/Exports/Benchmark002.csir.json';
  const otherCsir = unity + '/CutSceneAI/Exports/Benchmark003.csir.json';
  const censusA = unity + '/CutSceneAI/Exports/feature-surface-unity-A.json';
  const censusB = unity + '/CutSceneAI/Exports/feature-surface-unity-B.json';
  const invalidCensus = unity + '/CutSceneAI/Exports/feature-surface-unity-foreign.json';
  let availableCensuses = true;
  const level = '/Game/CutSceneAI/L_Trial01';
  const file = unreal + '/CutSceneAI.uproject';
  const advisory = {status:'PREPARED_ADVISORY',execution_enabled:false,
    decision_counts:{proposed:5,unsupported:2,failed:0,not_analyzed:0},active_ced_alerts:186,
    reason:'Native AI verifier integration is pending; preparation only.'};
  if(restoredJob || restoredPending || restoredAI) {
    connected={unity_project:unity,target_project:file,level_path:level,
      csir,scene_name:'Benchmark002',source_rights_confirmed:true};
    if(restoredAI){
      candidate={candidate_id:'saved_ai_candidate',action_total:17,ai_analysis:advisory,
        automatic_setup:{available:true,ready:true,blockers:[]}};
      // Even a stale approval must not auto-submit a preparation-only candidate.
      approval={candidate_id:candidate.candidate_id,source_csir:csir};
    }
    if(restoredPending){
      candidate={candidate_id:'older_pending_candidate',action_total:26,
        automatic_setup:{available:true,ready:true,blockers:[]}};
      approval={candidate_id:'older_pending_candidate',source_csir:csir,
        target_project:file,target_level:level};
    }
    if(restoredJob)currentJob={job_id:'a'.repeat(32),candidate_id:'candidate001',
      created_at:'2026-11-09T17:00:00Z',
      status:restoredJob==='running'?'RUNNING':restoredJob==='failed'?
      'PARTIAL_SETUP_MUST_INSPECT':'GENERATED_AND_MEASURED_NOT_FIDELITY_VERIFIED',
      generation_status:restoredJob==='finished'?'GENERATED_UNVERIFIED':'NOT_STARTED',
      ...(restoredJob==='failed'?{
        error:'FBX import failed: unsupported & unresolved texture <invalid>',
        setup_error:'FBX import failed',
        failure_stage:'IMPORTING_ASSETS_AND_CREATING_ACTORS',
        setup_status:'PARTIAL_SETUP_MUST_INSPECT',
        setup_failed_step:{phase:'asset_import',name:'CharacterA.fbx'},
        setup_recovery:'Do not rerun this candidate; inspect staged assets.'
      }:{})};
    done=restoredJob==='finished';
  }
  const fake = {
    document: {querySelector(sel) {
      if (sel === '#app') return app;
      return null;
    }, visibilityState: 'visible'},
    navigator: {clipboard: {writeText: async value => {copied=String(value);}}},
    setInterval(fn) { poll = fn; },
    fetch: async (url, opts = {}) => {
      calls.push(url);
      const body = opts.body ? JSON.parse(opts.body) : {};
      requests.push({url,body});
      let result = {};
      if (url === '/api/status') {
        result = {token: 'stubtoken', repo_root: 'B:/Research/CutSceneAI/CutsceneAI', workspace:'C:/Users/Test/.cutscene-studio/runs',
          connection: connected, candidate, active_job: currentJob?.job_id || null,
          one_click_approval: approval,
          unreal_worker: {connected: editorReady, project: file, level, worker_version: 'studio-editor-v0.5'},
          destination_readiness: candidate && editorReady ?
            {status: 'READY', ready:true, candidate_id:candidate.candidate_id} :
            {status: 'WAITING_FOR_UNREAL', ready:false, next_action:'Open Unreal Editor'}};
      } else if (url === '/api/ai-native-preflight') {
        if(opts.method==='POST'){
          assert.equal(body.candidate_id,candidate.candidate_id);
          inspectionRequested=true;
          result={status:'AI_NATIVE_PREFLIGHT_REQUESTED',verified:false,execution_authorized:false};
        }else result=inspectionRequested?
          {status:'AI_NATIVE_SETUP_PREFLIGHT_PASSED',verified:true,execution_authorized:false,
           candidate_id:candidate.candidate_id,request_id:'b'.repeat(32),report_sha256:'c'.repeat(64)}:
          {status:'AI_NATIVE_PREFLIGHT_REQUIRED',verified:false,execution_authorized:false};
      } else if (url === '/api/pick-folder') {
        result = {cancelled:false, path:body.kind==='unity'?unity:unreal};
      } else if (url === '/api/discover') {
        result = {ready: Boolean(body.unity_folder && body.unreal_folder),
          unity:{folder:body.unity_folder||'',cutscenes:[{name:'Benchmark002',path:csir},
             ...(multiSources?[{name:'Benchmark003',path:otherCsir}]:[])]},
          unreal:{folder:body.unreal_folder||'',project:file,levels:[level],active_level:level}};
      } else if (url === '/api/connect-projects') {
        connected = {unity_project:unity,target_project:file,level_path:level,
          csir:body.csir,scene_name:'Benchmark002',source_rights_confirmed:true};
        // Reconnect resets the active candidate and one-click approval on
        // the real Studio backend without deleting their archived files.
        candidate=null;currentJob=null;approval=null;
        result = connected;
      } else if (url === '/api/source-surfaces') {
        result = {options:availableCensuses?[
          {name:'feature-surface-unity-A.json',path:censusA,
            project_identity_proven:true,source_scope_matched:true,
            strict_ready:!censusUnresolved,
            state:censusUnresolved?'REVIEW_REQUIRED':'MATCHED_COMPLETE',
            unresolved_components:censusUnresolved?7:0,
            source_snapshot_partial_count:0,
            unresolved_findings:censusUnresolved?[{
              native_type:'UnityEngine.Playables.DirectorWrapMode',
              object_path:'Benchmark001/Director',
              state:'NATIVE_COMPONENT_EXTRACTION_OR_ADAPTER_REQUIRED'
            }]:[]},
          {name:'feature-surface-unity-B.json',path:censusB,
            project_identity_proven:true,source_scope_matched:true,
            strict_ready:true,state:'MATCHED_COMPLETE',
            unresolved_components:0,source_snapshot_partial_count:7},
          {name:'feature-surface-unity-foreign.json',path:invalidCensus,
            project_identity_proven:false,source_scope_matched:false,
            strict_ready:false,state:'SOURCE_IDENTITY_NOT_PROVEN',
            unresolved_components:0}
        ]:[]};
      } else if (url === '/api/prepare') {
        if(body.enable_ai_agent&&aiFailure)return {ok:false,status:422,
          json:async()=>({error:'Local model inference failed; no candidate prepared.'})};
        candidate = {candidate_id:'candidate001',action_total:body.enable_ai_agent?17:29,
          ...(body.enable_ai_agent&&!missingAI?{ai_analysis:advisory}:{}),
          automatic_setup:{available:true,ready:true,blockers:[],planned_imports:18,planned_actors:10}};
        result = candidate;
      } else if (url === '/api/approve-one-click') {
        assert.equal(body.candidate_id,'candidate001');
        approval={candidate_id:body.candidate_id,source_csir:connected.csir};
        result={approved:true,candidate_id:body.candidate_id};
      } else if (url === '/api/approve-ai-execution') {
        assert.equal(body.candidate_id,candidate.candidate_id);
        assert.equal(body.request_id,'b'.repeat(32));
        assert.equal(body.report_sha256,'c'.repeat(64));
        if(approvalFails)return {ok:false,status:422,json:async()=>({error:'Native inspection expired'})};
        result={approved:true,approval_id:'d'.repeat(32),execution_queued:false};
      } else if (url === '/api/execute') {
        assert.equal(body.candidate_id,candidate.candidate_id);
        if(candidate.ai_analysis)assert.equal(body.approval_id,'d'.repeat(32));
        currentJob = {job_id:'a'.repeat(32),status:'QUEUED',generation_status:'NOT_STARTED'};
        result=currentJob;
      } else if (url.startsWith('/api/jobs/')) {
        result=done ? {...currentJob,status:'GENERATED_AND_MEASURED_NOT_FIDELITY_VERIFIED',
          generation_status:'GENERATED_UNVERIFIED',generated_sequence:'/Game/Trial/LS_Benchmark002',
          setup_status:'SETUP_SAVED_UNVERIFIED',assets_imported_count:18,
          bindings_created_count:12,diagnostic_file:'real-native-evidence.json'} : currentJob;
      } else if (url === '/api/verification') {
        result={persistence:{native_structure:'PASS',status:'PERSISTENCE_NOT_REOPENED'},
          visual:{status:'VISUAL_COMPLETENESS_REVIEW_REQUIRED'}};
      } else if (url === '/api/diagnostic/'+'a'.repeat(32)) {
        result={entities:{A:{actor_max_cm:10}}};
      } else if (url === '/api/closed-loop') {
        result={available:true,status:'REVIEW_REQUIRED',issues:[{category:'VISUAL_NATIVE_READBACK',code:'NO_DIRECTIONAL_LIGHT_FOUND'}]};
      } else {
        throw new Error('Unexpected API request '+url);
      }
      return {ok:true,status:200,json:async()=>result};
    },
    console, Promise,
  };
  vm.runInNewContext(src,fake,{filename:'cinematic.js'});
  const pause = () => new Promise(resolve => setTimeout(resolve, 0));
  async function click(action) {
    listeners.click({target:{closest(selector) {
      return selector === '[data-action]' ? {dataset:{action}} : null;
    }}});
    await pause();
  }
  async function change(name, value, checked=false) {
    listeners.change({target:{name,value,checked}});
    await pause();
  }
  return {app,calls,requests,click,change,poll:async()=>{poll();await pause();await pause();},
    writes:()=>writes, copied:()=>copied, pause,finish:()=>{done=true;},
    csir,otherCsir,censusA,censusB,invalidCensus,
    removeCensuses:()=>{availableCensuses=false;}};
}

async function testOneClick() {
  const x=boot({editorReady:true});
  await x.pause();
  assert.match(x.app.innerHTML,/CUTSCENE/);
  await x.click('projects');
  assert.match(x.app.innerHTML,/Select Unity Project/);
  await x.click('browse-unity');
  await x.click('browse-unreal');
  assert.match(x.app.innerHTML,/Cutscene/);
  assert.match(x.app.innerHTML,/Enable AI Agent \(local Ollama\)/);
  assert.doesNotMatch(x.app.innerHTML,/name="enable-ai-agent" checked/);
  await x.change('source-rights',null,true);
  await x.click('connect');
  assert.ok(x.calls.includes('/api/connect-projects'));
  assert.match(x.app.innerHTML,/Source details/);
  assert.match(x.app.innerHTML,/Select matching source details/);
  assert.match(x.app.innerHTML,/Start Transfer/);
  assert.match(x.app.innerHTML.match(/data-action="start"([^>]*)>/)[1],/disabled/,
    'the transfer must not start before a census is selected');
  await x.change('census',x.censusB);
  await x.click('start');
  await x.poll();
  assert.deepEqual(x.calls.filter(v=>v==='/api/execute').length,1);
  assert.ok(x.calls.indexOf('/api/prepare')<x.calls.indexOf('/api/approve-one-click'));
  assert.ok(x.calls.indexOf('/api/approve-one-click')<x.calls.indexOf('/api/execute'));
  const preparation=x.requests.find(req=>req.url==='/api/prepare');
  assert.ok(preparation);
  assert.equal(preparation.body.source_feature_surface_path,x.censusB,
    'forward the exact user-selected census, not the first/newest export');
  assert.equal(preparation.body.require_complete_source_features,true);
  assert.equal(preparation.body.enable_ai_agent,false);
  const approval=x.requests.find(req=>req.url==='/api/approve-one-click');
  assert.deepEqual(Object.keys(approval.body),['candidate_id']);
  assert.ok(!x.calls.some(url=>url==='/api/agents'));
  x.finish();
  await x.poll();
  assert.match(x.app.innerHTML,/Editable Sequence Generated/);
  assert.doesNotMatch(x.app.innerHTML,/Verified Release Transfer/);
  assert.match(x.app.innerHTML,/18/);
  assert.match(x.app.innerHTML,/12/);
  assert.match(x.app.innerHTML,/not certified/);
  assert.ok(!x.app.innerHTML.includes('72%'));
  const writes=x.writes();
  await x.poll();
  assert.equal(x.writes(),writes,'unchanged heartbeat must not reset the DOM');
}

async function testEarlyUnrealConnectionCommand() {
  const x=boot({editorReady:false});
  await x.pause();
  await x.click('projects');
  await x.click('browse-unity');
  assert.match(x.app.innerHTML,/Unreal Editor: <strong>Not connected/);
  assert.match(x.app.innerHTML,/Copy connection command/);
  await x.click('copy-worker');
  assert.match(x.copied(), /B:\/Research\/CutSceneAI\/CutsceneAI\/integrations\/unreal/);
  assert.match(x.copied(), /import studio_local_editor_worker as w; assert Path\(w\.__file__\)/);
  assert.match(x.copied(), /w.start\(workspace="C:\/Users\/Test\/\.cutscene-studio\/runs"\)/);
  assert.ok(!x.calls.includes('/api/execute'));
  assert.ok(!x.calls.includes('/api/prepare'));
  assert.ok(!x.calls.includes('/api/connect-projects'));
}

async function testOfflineDoesNotExecute() {
  const x=boot({editorReady:false});
  await x.pause();
  await x.click('projects');
  await x.click('browse-unity');
  await x.click('browse-unreal');
  await x.change('source-rights',null,true);
  await x.click('connect');
  await x.change('census',x.censusA);
  await x.click('start');
  await x.poll();
  assert.equal(x.calls.filter(v=>v==='/api/execute').length,0);
  assert.match(x.app.innerHTML,/Copy connection command/);
  assert.match(x.app.innerHTML,/WAITING_FOR_EDITOR/);
}

async function testStrictCensusBlockAndExplicitRecovery() {
  const x=boot({editorReady:true,censusUnresolved:true});
  await x.pause();
  await x.click('projects');
  await x.click('browse-unity');
  await x.click('browse-unreal');
  await x.change('source-rights',null,true);
  await x.click('connect');
  await x.change('census',x.censusA);
  await x.click('start');
  assert.equal(x.calls.filter(v=>v==='/api/execute').length,0,
    'strict incomplete source census cannot queue engine execution');
  assert.match(x.app.innerHTML,/7 source features need review/);
  assert.match(x.app.innerHTML,/Benchmark001\/Director/);
  assert.match(x.app.innerHTML,/Transfer supported parts/);
  await x.click('best-effort');
  await x.poll();
  assert.equal(x.calls.filter(v=>v==='/api/execute').length,1,
    'only explicit best-effort opt-in may submit a separate candidate');
}

async function testManualCSIRAndCensus() {
  const x=boot({multiSources:true});
  await x.pause();
  await x.click('projects');
  await x.click('browse-unity');
  await x.click('browse-unreal');
  await x.change('csir',x.otherCsir);
  await x.change('source-rights',null,true);
  await x.click('connect');
  assert.equal(x.requests.find(r=>r.url==='/api/connect-projects').body.csir,x.otherCsir);
  assert.doesNotMatch(x.app.innerHTML,/value="[^"]*feature-surface-unity-foreign.json"/);
  await x.change('census',x.censusB);
  await x.click('refresh-exports');
  assert.match(x.app.innerHTML,/Selected: feature-surface-unity-B.json/);
  await x.change('csir',x.csir);
  assert.match(x.app.innerHTML,/Reconnect projects before starting/);
  await x.click('start');
  assert.equal(x.calls.filter(r=>r==='/api/prepare').length,0);
  await x.click('connect');
  await x.change('census',x.censusA);
  await x.click('start');
  assert.equal(x.requests.find(r=>r.url==='/api/prepare').body.source_feature_surface_path,x.censusA);
}

async function testMissingSelectedCensusFailsClosed() {
  const x=boot();
  await x.pause();
  await x.click('projects');
  await x.click('browse-unity');
  await x.click('browse-unreal');
  await x.change('source-rights',null,true);
  await x.click('connect');
  await x.change('census',x.censusB);
  x.removeCensuses();
  await x.click('start');
  assert.equal(x.calls.filter(v=>v==='/api/prepare').length,0);
  assert.equal(x.calls.filter(v=>v==='/api/execute').length,0);
  assert.match(x.app.innerHTML,/Selected Source Census is missing/);
}

async function testSelectionLayoutContract() {
  // Prevent recurrence of screenshot regression: long copy and the refresh
  // button must never share a shrinking flex row with three selectors.
  assert.match(css,/\.projects-view \.project-choices\s*\{\s*display:\s*grid/);
  assert.match(css,/grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\)/);
  assert.match(css,/\.projects-view \.source-census-panel\s*\{/);
  assert.match(css,/\.projects-view \.export-refresh-row\s*\{/);
  assert.match(css,/@media \(max-width:\s*680px\)/);
  const x=boot();
  await x.pause();
  await x.click('projects');
  await x.click('browse-unity');
  await x.click('browse-unreal');
  await x.change('source-rights',null,true);
  await x.click('connect');
  const html=x.app.innerHTML;
  assert.match(html,/class="project-choices"/);
  assert.match(html,/class="source-census-panel"/);
  assert.match(html,/class="export-refresh-row"/);
  assert.match(html,/class="choice"><span>Cutscene/);
  assert.match(html,/class="choice"><span>Target level/);
  assert.match(html,/class="choice"><span>Source details/);
  assert.match(html,/Refresh/);
}

async function testStartupAlwaysHomeWithSavedResults() {
  const x=boot({restoredJob:'finished'});
  await x.pause();
  await x.pause();
  assert.match(x.app.innerHTML,/class="landing"/);
  assert.match(x.app.innerHTML,/Start Transfer/);
  assert.match(x.app.innerHTML,/View Previous Transfer Report/);
  assert.doesNotMatch(x.app.innerHTML,/Editable Sequence Generated/);
  await x.poll();
  assert.match(x.app.innerHTML,/class="landing"/,
    'polling a completed job must not redirect Home to Results');
  await x.click('results');
  assert.match(x.app.innerHTML,/Editable Sequence Generated/);
  await x.click('home');
  assert.match(x.app.innerHTML,/class="landing"/);
  await x.click('projects');
  assert.match(x.app.innerHTML,/Reconnect/);
}

async function testStartupHomeWithRunningJobCanResume() {
  const x=boot({restoredJob:'running'});
  await x.pause();
  await x.pause();
  assert.match(x.app.innerHTML,/class="landing"/);
  assert.match(x.app.innerHTML,/View Active Transfer/);
  await x.click('resume-transfer');
  assert.match(x.app.innerHTML,/class="transfer-view"/);
  await x.click('home');
  assert.match(x.app.innerHTML,/class="landing"/);
}

async function testBlockedGenerationShowsActualNativeFailureAndRecovery() {
  const x=boot({restoredJob:'failed'});
  await x.pause();
  await x.pause();
  assert.match(x.app.innerHTML,/class="landing"/);
  await x.click('results');
  const markup=x.app.innerHTML;
  assert.match(markup,/Transfer stopped before sequence generation/);
  assert.match(markup,/IMPORTING_ASSETS_AND_CREATING_ACTORS/);
  assert.match(markup,/PARTIAL_SETUP_MUST_INSPECT/);
  assert.match(markup,/asset_import/);
  assert.match(markup,/CharacterA\.fbx/);
  assert.match(markup,/Do not rerun this candidate/);
  assert.match(markup,/2026-11-09T17:00:00Z/);
  assert.match(markup,/unsupported &amp; unresolved texture &lt;invalid&gt;/,
    'Unreal exception text must be escaped, not injected as HTML');
  assert.match(markup,/Not applicable until an editable sequence has been generated/);
  assert.doesNotMatch(markup,/reopen the saved map in a new Unreal Editor process/);
  await x.click('copy-failure');
  assert.match(x.copied(),/Job: a{32}/);
  assert.match(x.copied(),/Status: PARTIAL_SETUP_MUST_INSPECT/);
  assert.match(x.copied(),/Stage: IMPORTING_ASSETS_AND_CREATING_ACTORS/);
  assert.match(x.copied(),/FBX import failed/);
  assert.match(x.copied(),/Candidate: candidate001/);
}


async function testConnectedReadySelectionEnablesStart() {
  const x=boot();
  await x.pause();
  await x.click('projects');
  await x.click('browse-unity');
  await x.click('browse-unreal');
  await x.change('source-rights',null,true);
  await x.click('connect');
  await x.change('census',x.censusB);
  const matches=x.app.innerHTML.match(/<button[^>]*data-action="start"[^>]*>/g)||[];
  assert.equal(matches.length,1,'Start Transfer must exist with connected matching source');
  assert.doesNotMatch(matches[0],/\bdisabled\b/,
    'valid CSIR, matching census and permission must enable the button');
}

async function testRestoredUnsubmittedCandidateCanStartFreshWithoutReplay() {
  const x=boot({restoredPending:true});
  await x.pause();
  await x.pause();
  await x.click('projects');
  assert.match(x.app.innerHTML,/Start New Transfer/);
  assert.match(x.app.innerHTML,/A previous candidate was prepared but no Unreal job was submitted/);
  await x.change('census',x.censusB);
  const matches=x.app.innerHTML.match(/<button[^>]*data-action="start-fresh"[^>]*>/g)||[];
  assert.equal(matches.length,1,'the old approved candidate must have an explicit fresh option');
  assert.doesNotMatch(matches[0],/\bdisabled\b/,
    'a stale approval is not an active Unreal job');
  await x.click('start-fresh');
  await x.poll();
  const calls=x.requests;
  const reconnects=calls.filter(r=>r.url==='/api/connect-projects');
  const preparations=calls.filter(r=>r.url==='/api/prepare');
  const executions=calls.filter(r=>r.url==='/api/execute');
  assert.equal(reconnects.length,1,'fresh start must clear old active pointer on backend');
  assert.equal(preparations.length,1,'fresh start prepares one NEW candidate');
  assert.equal(preparations[0].body.source_feature_surface_path,x.censusB,
    'explicit census selection survives an intentional fresh reconnection');
  assert.equal(executions.length,1);
  assert.equal(executions[0].body.candidate_id,'candidate001');
  assert.ok(calls.findIndex(r=>r.url==='/api/connect-projects')<
    calls.findIndex(r=>r.url==='/api/prepare'),'reconnect before prepare');
}

async function testPendingFreshStartCannotSilentlySubstituteCensus() {
  const x=boot({restoredPending:true});
  await x.pause();
  await x.pause();
  await x.click('projects');
  await x.change('census',x.censusB);
  x.removeCensuses();
  await x.click('start-fresh');
  assert.equal(x.calls.filter(v=>v==='/api/prepare').length,0);
  assert.equal(x.calls.filter(v=>v==='/api/execute').length,0);
  assert.match(x.app.innerHTML,/selected Source Census is no longer valid/);
  assert.match(x.app.innerHTML,/no transfer was prepared/);
}

async function testRunningJobShowsResumeInsteadOfDisabledStart() {
  const x=boot({restoredJob:'running'});
  await x.pause();
  await x.pause();
  await x.click('projects');
  assert.match(x.app.innerHTML,/View Active Transfer/);
  assert.match(x.app.innerHTML,/An Unreal job is already queued or running/);
  assert.doesNotMatch(x.app.innerHTML,/data-action="start"[^>]*>/,
    'never start a second candidate while an Unreal job is running');
  await x.click('resume-transfer');
  assert.match(x.app.innerHTML,/class="transfer-view"/);
  assert.equal(x.calls.filter(v=>v==='/api/prepare').length,0);
}

async function setupAI(x,census=x.censusB){
  await x.pause();
  await x.click('projects');
  await x.click('browse-unity');
  await x.click('browse-unreal');
  await x.change('source-rights',null,true);
  await x.click('connect');
  await x.change('census',census);
  await x.change('enable-ai-agent',null,true);
  assert.match(x.app.innerHTML,/Prepare AI Plan/);
}

function assertNoNativeCalls(x){
  assert.ok(!x.calls.includes('/api/approve-one-click'));
  assert.ok(!x.calls.includes('/api/approve-ai-execution'));
  assert.ok(!x.calls.includes('/api/execute'));
}

async function testAIPlanStopsBeforeNativeExecution(){
  const x=boot({editorReady:true});
  await setupAI(x);
  await x.click('start');
  await x.poll();
  const preparation=x.requests.find(req=>req.url==='/api/prepare');
  assert.equal(preparation.body.enable_ai_agent,true);
  assert.equal(preparation.body.source_feature_surface_path,x.censusB);
  assert.match(x.app.innerHTML,/AI plan prepared/);
  assert.match(x.app.innerHTML,/Proposed mappings/);
  assert.match(x.app.innerHTML,/Withheld mappings/);
  assert.match(x.app.innerHTML,/No native changes performed/);
  assert.match(x.app.innerHTML,/AI_PREPARED/);
  assertNoNativeCalls(x);
  await x.click('home');
  assert.match(x.app.innerHTML,/View AI Plan/);
  await x.click('view-ai-plan');
  await x.poll();
  assert.match(x.app.innerHTML,/AI plan prepared/);
  assertNoNativeCalls(x);
}

async function testRestoredAIPlanNeverAutoQueues(){
  const x=boot({restoredAI:true,editorReady:true});
  await x.pause();
  await x.pause();
  assert.match(x.app.innerHTML,/class="landing"/);
  await x.poll();
  await x.click('view-ai-plan');
  assert.match(x.app.innerHTML,/AI plan prepared/);
  assertNoNativeCalls(x);
  await x.click('projects');
  assert.match(x.app.innerHTML,/Prepare New AI Plan/);
  await x.change('enable-ai-agent',null,false);
  assert.match(x.app.innerHTML,/Start New Transfer/);
  await x.change('census',x.censusB);
  await x.click('start-fresh');
  assert.equal(x.requests.find(r=>r.url==='/api/prepare').body.enable_ai_agent,false);
  assert.equal(x.calls.filter(r=>r==='/api/connect-projects').length,1);
  assert.equal(x.calls.filter(r=>r==='/api/prepare').length,1);
  assert.equal(x.calls.filter(r=>r==='/api/approve-one-click').length,1);
  // Preparation holds the busy flag; the next status poll advances the
  // explicitly approved fresh deterministic candidate after readiness checks.
  await x.poll();
  const executions=x.requests.filter(r=>r.url==='/api/execute');
  assert.equal(executions.length,1);
  assert.equal(executions[0].body.candidate_id,'candidate001');
  assert.ok(x.calls.indexOf('/api/approve-one-click')<x.calls.indexOf('/api/execute'));
  await x.poll();
  assert.equal(x.calls.filter(r=>r==='/api/execute').length,1,
    'polling must not replay the newly submitted candidate');
}

async function testAIErrorNeverFallsBack(){
  for(const options of [{aiFailure:true},{missingAI:true}]){
    const x=boot(options);
    await setupAI(x);
    await x.click('start');
    await x.poll();
    assert.match(x.app.innerHTML,/Transfer blocked/);
    assert.match(x.app.innerHTML,/Local model inference failed|AI evidence missing/);
    assert.equal(x.calls.filter(r=>r==='/api/prepare').length,1);
    assertNoNativeCalls(x);
  }
}

async function testAIBestEffortStillPreparationOnly(){
  const x=boot({censusUnresolved:true});
  await setupAI(x,x.censusA);
  await x.click('start');
  assert.match(x.app.innerHTML,/Prepare supported parts/);
  assert.equal(x.calls.filter(r=>r==='/api/prepare').length,0);
  await x.click('best-effort');
  await x.poll();
  const req=x.requests.find(r=>r.url==='/api/prepare');
  assert.equal(req.body.enable_ai_agent,true);
  assert.equal(req.body.require_complete_source_features,false);
  assert.match(x.app.innerHTML,/AI plan prepared/);
  assertNoNativeCalls(x);
}

async function testExplicitAIInspectionNeverExecutes(){
  const x=boot({restoredAI:true,editorReady:true});
  await x.pause();
  await x.pause();
  await x.click('view-ai-plan');
  assert.match(x.app.innerHTML,/Inspect target \(read-only\)/);
  assert.equal(x.requests.filter(r=>r.url==='/api/ai-native-preflight'&&r.body.candidate_id).length,0);
  await x.click('inspect-ai-target');
  await x.poll();
  assert.equal(x.requests.filter(r=>r.url==='/api/ai-native-preflight'&&r.body.candidate_id).length,1);
  assert.match(x.app.innerHTML,/Native setup inspection passed/);
  assertNoNativeCalls(x);
}

async function testExplicitAIApprovalQueuesOnlyOnce(){
  const x=boot({restoredAI:true,editorReady:true});
  await x.pause();
  await x.pause();
  await x.click('view-ai-plan');
  await x.click('authorize-ai-transfer');
  assertNoNativeCalls(x);
  await x.click('inspect-ai-target');
  await x.poll();
  assert.match(x.app.innerHTML,/Authorize and transfer/);
  assertNoNativeCalls(x);
  await x.click('authorize-ai-transfer');
  await x.poll();
  assert.equal(x.calls.filter(r=>r==='/api/approve-ai-execution').length,1);
  assert.equal(x.calls.filter(r=>r==='/api/execute').length,1);
  assert.ok(x.calls.indexOf('/api/approve-ai-execution')<x.calls.indexOf('/api/execute'));
  assert.ok(!x.calls.includes('/api/approve-one-click'));
  await x.click('authorize-ai-transfer');
  await x.poll();
  assert.equal(x.calls.filter(r=>r==='/api/execute').length,1);
}

async function testAIApprovalFailureNeverQueues(){
  const x=boot({restoredAI:true,editorReady:true,approvalFails:true});
  await x.pause();
  await x.pause();
  await x.click('view-ai-plan');
  await x.click('inspect-ai-target');
  await x.poll();
  await x.click('authorize-ai-transfer');
  assert.match(x.app.innerHTML,/Native inspection expired/);
  assert.equal(x.calls.filter(r=>r==='/api/approve-ai-execution').length,1);
  assert.ok(!x.calls.includes('/api/execute'));
  await x.poll();
  assert.ok(!x.calls.includes('/api/execute'));
}

(async()=>{
  await testExplicitAIApprovalQueuesOnlyOnce();
  await testAIApprovalFailureNeverQueues();
  await testExplicitAIInspectionNeverExecutes();
  await testAIPlanStopsBeforeNativeExecution();
  await testRestoredAIPlanNeverAutoQueues();
  await testAIErrorNeverFallsBack();
  await testAIBestEffortStillPreparationOnly();
  await testSelectionLayoutContract();
  await testStartupAlwaysHomeWithSavedResults();
  await testStartupHomeWithRunningJobCanResume();
  await testBlockedGenerationShowsActualNativeFailureAndRecovery();
  await testConnectedReadySelectionEnablesStart();
  await testRestoredUnsubmittedCandidateCanStartFreshWithoutReplay();
  await testPendingFreshStartCannotSilentlySubstituteCensus();
  await testRunningJobShowsResumeInsteadOfDisabledStart();
  await testOneClick();
  await testEarlyUnrealConnectionCommand();
  await testOfflineDoesNotExecute();
  await testStrictCensusBlockAndExplicitRecovery();
  await testManualCSIRAndCensus();
  await testMissingSelectedCensusFailsClosed();
  console.log('Cinematic UI backend contract: 21 scenarios including explicit AI approval, read-only AI inspection, AI preparation-only, failure recovery, native errors and Home-first startup passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
